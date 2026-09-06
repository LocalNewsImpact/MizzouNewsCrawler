"""A manifest names its image with a placeholder, never a tag.

`k8s/argo/base-pipeline-workflow.yaml` carried six literal tags --
`crawler:d2b5008`, `processor:db99260` -- while every other manifest
here has always used `${CRAWLER_TAG}` and friends, resolved by
`envsubst` at apply time.

Because those tags were literal, something had to rewrite them after
every deploy, and that something could not push to `main`. So each
deploy opened a bookkeeping pull request for a person to approve --
about a change that had already happened, since Cloud Build repoints
the live WorkflowTemplate during the build
(gcp/cloudbuild/update-workflow-template.sh).

The literal tags were worse than noise. They went stale the moment they
were written, and `kubectl apply -f` on that file would roll the cluster
back to whichever tag was committed. A placeholder cannot: unset, it
renders empty and the apply fails.
"""

import re
from pathlib import Path

import pytest

K8S = Path(__file__).resolve().parent.parent / "k8s"

REGISTRY = "us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler"

#: `image: <our registry>/<name>:<tag>` — the tag is what matters.
OUR_IMAGE = re.compile(
    rf"image:\s*[\"']?{re.escape(REGISTRY)}/(?P<name>[a-z0-9-]+):(?P<tag>\S+?)[\"']?\s*$",
    re.M,
)

#: Tags that are not a build: a placeholder envsubst fills, the
#: `<COMMIT_SHA>` placeholder the hand-run migration manifests use, or a
#: moving tag deliberately chosen.
ALLOWED = re.compile(r"^\$\{[A-Z_]+\}$|^<[A-Z_]+>$|^latest$")

#: Manifests that pin a tag on purpose, each with the reason. These are
#: run by hand for one job and then finished with -- they are not
#: deployed, nothing rewrites them, and a fixed tag is the point: the
#: whole question is which image to run this once.
#:
#: They are listed rather than pattern-matched so that adding one is a
#: decision somebody writes down.
PINNED_ON_PURPOSE = {
    "migration-job.yaml": "hand-applied copy of the migration job",
    "lehigh-extraction-job.yaml": "one-off extraction for a single dataset",
    "extraction-test2.yaml": "ad-hoc extraction probe",
    "cli-deployment.yaml": "pinned CLI pod for interactive work",
}


def _manifests():
    return sorted(p for p in K8S.rglob("*.yaml") if p.is_file())


@pytest.mark.parametrize("path", _manifests(), ids=lambda p: p.name)
def test_no_manifest_pins_an_image_tag(path):
    if path.name in PINNED_ON_PURPOSE:
        pytest.skip(PINNED_ON_PURPOSE[path.name])
    literal = [
        (m.group("name"), m.group("tag"))
        for m in OUR_IMAGE.finditer(path.read_text(errors="ignore"))
        if not ALLOWED.match(m.group("tag"))
    ]
    assert not literal, (
        f"{path.name} names a tag of its own: {literal}. Use a ${{...}} "
        "placeholder, as the other manifests do — a literal goes stale the "
        "moment it is written, and applying the file would move the cluster "
        "onto it."
    )


def test_the_argo_template_uses_placeholders():
    """The file this was written for, named so a regression is obvious."""
    text = (K8S / "argo/base-pipeline-workflow.yaml").read_text()
    assert "${CRAWLER_TAG}" in text
    assert "${PROCESSOR_TAG}" in text


def test_nothing_expects_a_committed_versions_file():
    """`k8s/versions.env` was the other half of the bookkeeping commit. The
    tags of a deploy are on its run summary and attached to it as an
    artifact; nothing in the repository records them."""
    assert not (K8S / "versions.env").exists()


def test_every_exemption_still_earns_its_place():
    """An exemption for a file that no longer pins anything is a rule
    nobody is applying. Remove it rather than leave it standing."""
    unnecessary = []
    for name in PINNED_ON_PURPOSE:
        path = next((p for p in _manifests() if p.name == name), None)
        if path is None:
            unnecessary.append(f"{name} (file is gone)")
            continue
        pinned = [
            m.group("tag")
            for m in OUR_IMAGE.finditer(path.read_text(errors="ignore"))
            if not ALLOWED.match(m.group("tag"))
        ]
        if not pinned:
            unnecessary.append(f"{name} (pins nothing now)")
    assert not unnecessary, f"Exemptions no longer needed: {unnecessary}"


# --- what deleting the file actually broke ------------------------------------
#
# Removing k8s/versions.env was checked against the manifests and not
# against anything else. Three callers wanted it:
#
#   scripts/apply-manifests.sh   `source k8s/versions.env` at the top
#   scripts/deploy-services.sh   passed it to update-versions-env.sh
#   the deploy's report job      passed it to the same script, which EDITS
#                                an existing file and fails without one
#
# The last of those failed the first deploy after the merge. These check
# that nothing sources or edits a versions file the repository does not
# contain.

REPO = K8S.parent
SCRIPTS = REPO / "scripts"


def _shell_sources():
    for path in sorted(SCRIPTS.glob("*.sh")):
        for line in path.read_text(errors="ignore").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if stripped.startswith(("source ", ". ")) and "versions.env" in stripped:
                yield path, stripped


def test_no_script_unconditionally_sources_a_versions_file():
    """Sourcing a file that is not in the repository fails the script on
    its first line. Guarded with a test rather than a `-f` check alone so
    the reason is written down: the tags are the caller's to supply."""
    unguarded = [
        (p.name, line) for p, line in _shell_sources() if not line.startswith("[ -f")
    ]
    assert not unguarded, (
        f"These source a versions file that may not exist: {unguarded}. "
        "Guard it and require the tag variables instead."
    )


def test_the_apply_script_refuses_without_tags():
    """It applied whatever the stale file said. Now it says what it needs."""
    text = (SCRIPTS / "apply-manifests.sh").read_text()
    for var in ("PROCESSOR_TAG", "CRAWLER_TAG", "API_TAG"):
        assert var in text
    assert "is not set" in text, "the script does not say what is missing"


def test_nothing_calls_the_removed_versions_script():
    """`update-versions-env.sh` edited the committed file in place and
    rewrote the Argo template's tags back to literals. Both of those are
    gone, so it is too."""
    assert not (SCRIPTS / "update-versions-env.sh").exists()

    # Invocations, not mentions. Written the blunt way first, this failed
    # on the comment in the workflow that explains why the script is gone
    # -- a guard that cannot tell a caller from an explanation is one
    # people learn to work around by deleting the explanation.
    callers = []
    for path in [*SCRIPTS.glob("*.sh"), *(REPO / ".github/workflows").glob("*.yml")]:
        for line in path.read_text(errors="ignore").splitlines():
            code = line.split("#", 1)[0]
            if "update-versions-env.sh" in code:
                callers.append(f"{path.name}: {line.strip()}")
    assert not callers, f"these still call it: {callers}"
