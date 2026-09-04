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
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/base-images.yml"


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def _config(name):
    return yaml.safe_load((ROOT / f"gcp/cloudbuild/cloudbuild-{name}.yaml").read_text())


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
    jobs = _workflow()["jobs"]
    for name in ("base", "ml-base", "ci-base"):
        build = next(
            step
            for step in jobs[name]["steps"]
            if "gcloud builds triggers run" in str(step.get("run", ""))
        )
        assert build["if"] == "steps.tag.outputs.exists == 'false'"


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
        steps = yaml.dump(jobs[name]["steps"])
        assert f"gcloud builds triggers run {trigger}" in steps
        assert "gcloud builds submit" not in steps.replace("`builds submit`", "")


def test_the_trigger_is_told_which_tag_to_build():
    """The trigger for ml-base carries `_BASE_IMAGE=...base:latest` as a
    default, which is what let it build against whatever happened to be
    there. Passing it overrides that for the run."""
    jobs = _workflow()["jobs"]
    for name in ("ml-base", "ci-base"):
        steps = yaml.dump(jobs[name]["steps"])
        assert "_BASE_IMAGE=" in steps
        assert "_TAG=" in steps
