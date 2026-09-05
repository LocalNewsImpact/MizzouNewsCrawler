"""The base images are rebuilt when what goes into them changes.

ci-base:latest was built on 18 July and base:latest on 3 September.
Nothing rebuilt one when the other changed and nothing compared them, so
CI ran for seven weeks inside an image that could not hold what the
commits pinned -- a hundred collection errors in three jobs, none naming
the cause, and a pull request merged with them failing.

Each image is now tagged with a hash of its contents, and a child's hash
includes its parent's tag, so a base that changes gives its children tags
that do not exist yet. Going stale stops being something a person notices.

These assert the wiring, because the wiring is what failed. Nothing here
builds an image.

The chain's first two days produced six failed builds and no images, for
three reasons the first version of these tests did not cover: the deploy
workflow still ran the triggers without a tag, the configs read a
substitution Cloud Build never expanded, and the workflow took a queued
build for a finished one. Each has a test below.
"""

import os
import stat
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/base-images.yml"
DEPLOY_WORKFLOW = ROOT / ".github/workflows/build-and-deploy-services.yml"
RUN_TRIGGER = ROOT / "scripts/ci/run-cloud-build-trigger.sh"
IMAGES = ("base", "ml-base", "ci-base")


def _workflow(path=WORKFLOW):
    return yaml.safe_load(path.read_text())


def _triggers(workflow):
    """The `on:` block. YAML 1.1 reads a bare `on` as the boolean true."""
    return workflow.get("on", workflow.get(True))


def _config(name):
    return yaml.safe_load((ROOT / f"gcp/cloudbuild/cloudbuild-{name}.yaml").read_text())


def _build_step(job):
    return next(
        step
        for step in job["steps"]
        if "run-cloud-build-trigger.sh" in str(step.get("run", ""))
    )


def test_every_base_image_is_built_by_the_workflow():
    assert set(_workflow()["jobs"]) == {"base", "ml-base", "ci-base"}


def test_the_children_are_built_from_the_base_that_was_just_built():
    """The chain is the fix. Without it a base change leaves the children
    on whatever they were built against, which is exactly what happened."""
    jobs = _workflow()["jobs"]
    for child in ("ml-base", "ci-base"):
        assert jobs[child]["needs"] == "base", f"{child} does not follow base"
        steps = yaml.dump(jobs[child]["steps"])
        assert (
            "needs.base.outputs.image" in steps
        ), f"{child} does not take the base image it was just given"


def test_a_childs_tag_includes_its_parents():
    """A base that changes has to change its children's tags, or they are
    not rebuilt. The parent's tag reaches the hash as a build argument."""
    jobs = _workflow()["jobs"]
    for child in ("ml-base", "ci-base"):
        tag_step = next(
            step
            for step in jobs[child]["steps"]
            if "image-tag" in str(step.get("uses", ""))
        )
        assert "needs.base.outputs.image" in tag_step["with"]["build_args"]


def test_the_tag_comes_from_the_shared_action():
    """One definition of what an image should be tagged, across the
    suite."""
    steps = yaml.dump(_workflow()["jobs"])
    assert "lnic-contracts/.github/actions/image-tag@" in steps


def test_nothing_is_built_when_an_image_for_those_contents_exists():
    """Unless asked to: `force` is for an upstream layer the hash cannot
    see, and it is the only way past the check."""
    jobs = _workflow()["jobs"]
    for name in IMAGES:
        build = _build_step(jobs[name])
        assert build["if"] == "steps.tag.outputs.exists == 'false' || inputs.force"


def test_a_build_without_a_tag_is_refused():
    """A fallback would be a second implementation of the hash, and an
    image tagged with nothing is the failure the hash exists to remove."""
    for name in ("base", "ml-base", "ci-base"):
        assert _config(name)["substitutions"]["_TAG"] == ""
        # The raw file: yaml.dump re-escapes the shell and the literal
        # would never match.
        script = (ROOT / f"gcp/cloudbuild/cloudbuild-{name}.yaml").read_text()
        assert '[ -z "${_TAG}" ]' in script, f"{name} does not refuse an empty tag"


def test_the_children_are_refused_without_a_base_to_build_on():
    for name in ("ml-base", "ci-base"):
        config = _config(name)
        assert (
            config["substitutions"]["_BASE_IMAGE"] == ""
        ), f"{name} defaults its base image, which is how it went stale"


def test_the_region_allows_the_machine_type():
    """us-central1 refuses N1. A build submitted with --region fails on
    it, which is how the ci-base rebuild failed on its first attempt."""
    for name in ("base", "ml-base", "ci-base"):
        assert _config(name)["options"]["machineType"].startswith("E2_")


def test_the_rebuilt_ci_image_reaches_where_ci_pulls_from():
    """CI pulls ci-base from GHCR, not Artifact Registry. A rebuilt image
    that is not mirrored is one CI never sees, which is half of the
    original failure."""
    steps = yaml.dump(_workflow()["jobs"]["ci-base"]["steps"])
    assert "Mirror CI Images to GHCR" in steps


def test_the_build_runs_through_the_trigger():
    """`gcloud builds submit` uploads a source tarball, and the service
    account this workflow authenticates as cannot write to the Cloud
    Build source bucket -- the first run of this workflow failed on
    exactly that.

    The manual triggers read their config from git (gitFileSource, on
    refs/heads/main), so the build being run is the one in this
    repository and reviewable in a pull request. They were a deliberate
    choice and they are the right one; what was wrong was `:latest`, not
    the trigger.
    """
    jobs = _workflow()["jobs"]
    for name, trigger in (
        ("base", "build-base-manual"),
        ("ml-base", "build-ml-base-manual"),
        ("ci-base", "build-ci-base-manual"),
    ):
        assert (
            f"run-cloud-build-trigger.sh {trigger} " in _build_step(jobs[name])["run"]
        )
    script = RUN_TRIGGER.read_text()
    assert "gcloud builds triggers run" in script
    assert "gcloud builds submit" not in script


def test_the_trigger_is_told_which_tag_to_build():
    """The trigger for ml-base carries `_BASE_IMAGE=...base:latest` as a
    default, which is what let it build against whatever happened to be
    there. Passing it overrides that for the run."""
    jobs = _workflow()["jobs"]
    for name in ("ml-base", "ci-base"):
        steps = yaml.dump(jobs[name]["steps"])
        assert "_BASE_IMAGE=" in steps
        assert "_TAG=" in steps


def test_the_registry_substitution_is_one_cloud_build_expands():
    """Inside a user-defined substitution Cloud Build expands ${PROJECT_ID}
    and passes a bare $PROJECT_ID through to the shell unexpanded, where
    `set -u` stops the build at step 0 -- measured on 2026-09-05 with a
    build that echoed both forms. Every tagged base build had failed on
    it."""
    for name in IMAGES:
        registry = _config(name)["substitutions"]["_REGISTRY"]
        assert "${PROJECT_ID}" in registry, f"{name}: {registry}"
        assert "$PROJECT_ID/" not in registry, f"{name}: {registry}"


def test_the_deploy_workflow_builds_the_base_images_through_this_chain():
    """Run #228 (2026-09-05) failed in a job of the deploy workflow that
    still ran build-base-manual with no _TAG, a month after the configs
    came to require one. The deploy workflow now calls this one and
    builds its first service after it, so the ordering the chain needs is
    a `needs`, and there is one place that runs the base triggers."""
    deploy = _workflow(DEPLOY_WORKFLOW)
    callers = [
        name
        for name, job in deploy["jobs"].items()
        if job.get("uses") == "./.github/workflows/base-images.yml"
    ]
    assert len(callers) == 1, callers
    assert callers[0] in deploy["jobs"]["build-processor"]["needs"]
    assert deploy["jobs"][callers[0]].get("secrets") == "inherit"
    text = DEPLOY_WORKFLOW.read_text()
    for trigger in (
        "build-base-manual",
        "build-ml-base-manual",
        "build-ci-base-manual",
    ):
        assert trigger not in text, f"the deploy workflow still runs {trigger} itself"


def test_the_chain_is_called_and_not_also_pushed():
    """Two runs for one push would each find the image missing and each
    build it. The push trigger went; the caller runs on every push."""
    triggers = _triggers(_workflow())
    assert set(triggers) == {"workflow_call", "workflow_dispatch"}, triggers
    assert "push" not in _triggers(_workflow()), "the caller already runs on push"


def test_the_ci_image_is_mirrored_only_after_it_is_built():
    """Mirroring a queued build re-mirrors the previous image under the
    same name, which is the staleness the chain exists to end."""
    steps = _workflow()["jobs"]["ci-base"]["steps"]
    mirror = next(
        step for step in steps if "Mirror CI Images" in str(step.get("run", ""))
    )
    assert mirror["if"] == "steps.build.outcome == 'success'"
    assert _build_step(_workflow()["jobs"]["ci-base"])["id"] == "build"


def _stub_gcloud(tmp_path, statuses):
    """A `gcloud` that starts one build and then reports these statuses
    in turn, so the script's waiting can be run rather than read."""
    log = tmp_path / "statuses"
    log.write_text("\n".join(statuses) + "\n")
    counter = tmp_path / "polls"
    counter.write_text("0")
    stub = tmp_path / "bin" / "gcloud"
    stub.parent.mkdir()
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'case "$1 $2 $3" in\n'
        '  "builds triggers run") echo "build-0001"; exit 0 ;;\n'
        '  "builds describe "*)\n'
        f'    n=$(cat "{counter}"); echo $((n + 1)) > "{counter}"\n'
        f'    sed -n "$((n + 1))p" "{log}"; exit 0 ;;\n'
        '  "builds log "*) echo "(the log)"; exit 0 ;;\n'
        "esac\n"
        'echo "unexpected: $*" >&2; exit 2\n'
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    env = {
        **os.environ,
        "PATH": f"{stub.parent}:{os.environ['PATH']}",
        "PROJECT_ID": "a-project",
        "POLL_SECONDS": "0",
    }
    return env, counter


def _run_trigger(env):
    return subprocess.run(
        [str(RUN_TRIGGER), "build-base-manual", "abc123", "_TAG=deadbeef"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_a_build_is_waited_for_until_it_succeeds(tmp_path):
    """`gcloud builds triggers run` returns when the build is queued.
    The first version of the workflow took that for done: ml-base pulled
    a base that was still being built, and the run was green while every
    build behind it failed."""
    env, polls = _stub_gcloud(tmp_path, ["QUEUED", "WORKING", "WORKING", "SUCCESS"])
    result = _run_trigger(env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert polls.read_text().strip() == "4", "did not wait for the final status"
    assert "build-0001 succeeded" in result.stdout


def test_a_build_that_fails_fails_the_job(tmp_path):
    env, _ = _stub_gcloud(tmp_path, ["WORKING", "FAILURE"])
    result = _run_trigger(env)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "::error::" in result.stdout
    assert "ended FAILURE" in result.stdout


def test_the_manual_deploy_script_refuses_the_base_images(tmp_path):
    """scripts/deploy-services.sh also ran the base triggers without a
    tag. It points at the workflow rather than growing a second copy of
    the hash."""
    stub = tmp_path / "gcloud"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/deploy-services.sh"), "main", "base"],
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1
    assert "Base images" in result.stdout + result.stderr
