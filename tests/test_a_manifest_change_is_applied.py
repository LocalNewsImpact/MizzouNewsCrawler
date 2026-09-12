"""A change to what the cluster runs has to reach the cluster.

Images reach production from their own Cloud Build, which patches the
running tag (`kubectl set image`, plus
gcp/cloudbuild/update-workflow-template.sh for the one pipeline template
it names). EVERYTHING else in k8s/ -- a Deployment's resources, a
CronJob's schedule, an Argo template's steps, a suspend -- reaches it only
through scripts/apply-manifests.sh, and until this was added no workflow
called that script at all.

So a manifest change was merged, reported as deployed, and applied by
nothing. The corrected housekeeping workflow sat on main for hours while
production kept running the version that swept 4,802 candidate links.

These hold the deploy to applying it, and the tag resolver to never
deploying a tag it does not have.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/build-and-deploy-services.yml"
RESOLVER = ROOT / "scripts/resolve-image-tags.sh"


@pytest.fixture(scope="module")
def deploy():
    return yaml.safe_load(WORKFLOW.read_text())


# --- the deploy applies them ---------------------------------------------------


def test_a_job_applies_the_manifests(deploy):
    """Without this job, `scripts/apply-manifests.sh` is called by nothing
    in CI: it was reachable only through scripts/deploy-services.sh, which
    no workflow runs."""
    job = deploy["jobs"]["apply-manifests"]
    steps = " ".join(step.get("run", "") for step in job["steps"])
    assert "./scripts/apply-manifests.sh" in steps


def test_it_runs_when_only_a_manifest_changed(deploy):
    """The case that was never covered. A structural change builds no
    image, so a condition resting on a build would skip exactly the
    changes that need applying."""
    job = deploy["jobs"]["apply-manifests"]
    condition = job["if"]
    assert "needs.detect-changes.outputs.manifests == 'true'" in condition
    assert "build_id != ''" not in condition, "a build must not gate this"


def test_the_change_filter_catches_the_manifests(deploy):
    """`k8s/` is where they all live: Deployments, CronJobs and the Argo
    templates under k8s/argo/."""
    detect = deploy["jobs"]["detect-changes"]
    body = " ".join(step.get("run", "") for step in detect["steps"])
    assert "MANIFESTS=true" in body
    assert "'^k8s/'" in body
    assert "manifests=$MANIFESTS" in body
    assert (
        deploy["jobs"]["detect-changes"]["outputs"]["manifests"]
        == "${{ steps.detect.outputs.manifests }}"
    )


def test_every_manifest_path_the_repository_has_matches_the_filter():
    """A manifest outside `k8s/` would be invisible to the filter."""
    tracked = subprocess.run(
        ["git", "ls-files", "*.yaml", "*.yml"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    applied = set()
    for line in (ROOT / "scripts/apply-manifests.sh").read_text().splitlines():
        line = line.strip()
        if line.startswith("#"):
            continue
        for word in line.split():
            if word.endswith((".yaml", ".yml")):
                applied.add(word)
    outside = sorted(p for p in applied if not p.startswith("k8s/"))
    assert outside == [], f"applied but not matched by the filter: {outside}"
    assert applied and applied <= set(tracked), "a file is applied but not tracked"


def test_it_waits_for_the_builds(deploy):
    """A manifest naming a tag this push produced must be applied after
    that tag exists, or the workload cannot pull its image."""
    job = deploy["jobs"]["apply-manifests"]
    assert "wait-for-builds" in job["needs"]
    assert "needs.wait-for-builds.result" in job["if"]


def test_it_asks_every_build_job_directly(deploy):
    """`needs` exposes direct dependencies only. Reaching a build id
    through wait-for-builds yields an empty string, which is how a
    previous job reported success while doing nothing for four months."""
    job = deploy["jobs"]["apply-manifests"]
    for name in ("build-processor", "build-api", "build-crawler", "build-enrichment"):
        assert name in job["needs"], name


def test_it_only_deploys_from_main(deploy):
    job = deploy["jobs"]["apply-manifests"]
    assert "github.ref == 'refs/heads/main'" in job["if"]


# --- the tag resolver ------------------------------------------------------------


pytestmark_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _resolve(tmp_path, live, **built):
    """Run the resolver with a fake kubectl returning `live` images."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "kubectl").write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        f'  *deploy*) printf "%s\\n" {" ".join(repr(i) for i in live.get("deploy", []))} ;;\n'
        f'  *cronjob*) printf "%s\\n" {" ".join(repr(i) for i in live.get("cronjob", []))} ;;\n'
        "esac\n"
    )
    (bin_dir / "kubectl").chmod(0o755)
    return subprocess.run(
        ["bash", str(RESOLVER)],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", **built},
    )


REG = "us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler"
ALL_LIVE = {
    "deploy": [
        f"{REG}/processor:aaaaaaa",
        f"{REG}/api:aaaaaaa",
        f"{REG}/crawler:aaaaaaa",
    ],
    "cronjob": [f"{REG}/enrichment:aaaaaaa", "bitnami/kubectl:latest"],
}


def test_a_tag_this_deploy_built_wins(tmp_path):
    result = _resolve(tmp_path, ALL_LIVE, BUILT_PROCESSOR="bbbbbbb")
    assert result.returncode == 0, result.stderr
    assert "export PROCESSOR_TAG=bbbbbbb" in result.stdout
    assert "export CRAWLER_TAG=aaaaaaa" in result.stdout


def test_a_service_this_deploy_did_not_build_keeps_what_is_running(tmp_path):
    """Otherwise an apply rolls back every service the push did not
    touch."""
    result = _resolve(tmp_path, ALL_LIVE)
    for svc in ("PROCESSOR", "CRAWLER", "API", "ENRICHMENT"):
        assert f"export {svc}_TAG=aaaaaaa" in result.stdout


def test_enrichment_is_found_although_it_runs_from_no_deployment(tmp_path):
    """It runs from a CronJob and an Argo template. Reading Deployments
    alone leaves ENRICHMENT_TAG empty, and `envsubst` then writes the
    literal `${ENRICHMENT_TAG}` into the cluster."""
    result = _resolve(tmp_path, ALL_LIVE)
    assert "export ENRICHMENT_TAG=aaaaaaa" in result.stdout


def test_an_unresolvable_tag_fails_loudly(tmp_path):
    """Never `latest`, never empty: both deploy something nobody chose."""
    result = _resolve(tmp_path, {"deploy": [], "cronjob": []})
    assert result.returncode == 1
    assert "no tag for" in result.stderr
    assert "TAG=" not in result.stdout


def test_it_emits_shell_the_apply_can_source(tmp_path):
    result = _resolve(tmp_path, ALL_LIVE)
    assert all(
        line.startswith(("export ", "#"))
        for line in result.stdout.splitlines()
        if line.strip()
    )


def test_the_apply_job_sources_what_the_resolver_wrote(deploy):
    """A tag resolved into a subshell and never exported is a tag the
    apply does not have."""
    step = next(
        s
        for s in deploy["jobs"]["apply-manifests"]["steps"]
        if "resolve-image-tags.sh" in s.get("run", "")
    )
    assert ". ./versions.env" in step["run"]
    assert "./scripts/apply-manifests.sh" in step["run"]
