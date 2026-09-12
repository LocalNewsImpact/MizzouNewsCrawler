"""A manifest in the repository is not a manifest on the cluster.

`k8s/argo/housekeeping-workflow.yaml` and its CronWorkflow were written,
reviewed, merged and deployed -- and never applied, because
`scripts/apply-manifests.sh` names every file it applies and nobody added
them to it. Nothing failed. The workflow simply did not exist anywhere
that could run it.

What that cost: the reconciliation set 545 statuses on its first run and
nothing picked them up. 4,805 links sat at `article` waiting for
extraction and 450 articles at `cleaned` waiting for classification, with
no stage deployed to take either.

This test is a file-list comparison, which is a weak kind of test, and it
is here because the failure it catches is invisible: the manifest is
valid, the tests pass, the deploy is green, and the thing does not run.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/apply-manifests.sh"
ARGO = ROOT / "k8s/argo"

#: Manifests that describe something the cluster should hold. A
#: WorkflowTemplate or CronWorkflow that is never applied is inert.
KINDS_THAT_MUST_BE_APPLIED = {"WorkflowTemplate", "CronWorkflow", "CronJob"}

#: Applied by something other than this script, and why.
#:
#: `base-pipeline-workflow.yaml` is repointed by Cloud Build during the
#: build (gcp/cloudbuild/update-workflow-template.sh), so applying it here
#: as well would roll the live template back to whatever tag is committed.
EXEMPT = {
    "base-pipeline-workflow.yaml",
    "dataset-pipeline-template.yaml",
    # Applied through Kustomize instead (`k8s/base/kustomization.yaml`),
    # which is a second apply path this repository has and this script
    # does not know about. Found by this test failing on it.
    "mizzou-pipeline-cronworkflow.yaml",
    "rbac.yaml",
}


def _kind(path):
    match = re.search(r"^kind:\s*(\w+)", path.read_text(), re.M)
    return match.group(1) if match else ""


@pytest.fixture(scope="module")
def applied():
    return SCRIPT.read_text()


def test_the_script_applies_something():
    """A rename would otherwise make this pass by finding nothing."""
    assert "kubectl apply" in SCRIPT.read_text()


@pytest.mark.parametrize(
    "manifest",
    [p for p in sorted(ARGO.glob("*.yaml")) if p.name not in EXEMPT],
    ids=lambda p: p.name,
)
def test_every_argo_manifest_is_applied(manifest, applied):
    if _kind(manifest) not in KINDS_THAT_MUST_BE_APPLIED:
        pytest.skip(f"{manifest.name} is a {_kind(manifest) or 'fragment'}")
    assert manifest.name in applied, (
        f"{manifest.name} is never applied, so it exists in this repository "
        "and nowhere that can run it"
    )


def test_the_template_is_applied_before_the_schedule(applied):
    """A CronWorkflow references its template by name. Applied first, it
    fires and fails on a missing templateRef -- which reports as a
    workflow error rather than as "nothing is deployed"."""
    template = applied.index("housekeeping-workflow.yaml")
    schedule = applied.index("housekeeping-cronworkflow.yaml")
    assert template < schedule


@pytest.mark.parametrize(
    "tag", sorted({"CRAWLER_TAG", "PROCESSOR_TAG", "ENRICHMENT_TAG"})
)
def test_every_tag_a_manifest_uses_is_substituted(tag):
    """`apply_file` names the variables envsubst replaces. One a manifest
    uses and the list omits passes through as a literal, and the applied
    template names an image that cannot be pulled -- which surfaces as a
    workflow failing at that step, long after the apply said it worked.

    ENRICHMENT_TAG was missing when the housekeeping workflow was added.
    """
    used = set()
    for manifest in ARGO.glob("*.yaml"):
        used |= set(re.findall(r"\$\{([A-Z_]+_TAG)\}", manifest.read_text()))
    if tag not in used:
        pytest.skip(f"{tag} is not used by any manifest")
    envsubst = re.search(r"envsubst '([^']+)'", SCRIPT.read_text())
    assert envsubst, "apply_file no longer substitutes"
    assert tag in envsubst.group(
        1
    ), f"{tag} is used by a manifest and never substituted"


def test_a_manifest_with_tags_is_applied_through_the_substituting_helper():
    """`kubectl apply -f` directly would push `${CRAWLER_TAG}` as text."""
    body = SCRIPT.read_text()
    for line in body.splitlines():
        if "kubectl apply" in line and "k8s/argo/" in line:
            name = line.split("k8s/argo/")[1].strip()
            manifest = ARGO / name
            if manifest.exists() and "_TAG}" in manifest.read_text():
                raise AssertionError(
                    f"{name} carries tag placeholders and is applied without substitution"
                )


def test_the_exemptions_say_why():
    """An exemption without a reason becomes a place to hide a manifest
    somebody forgot."""
    body = SCRIPT.read_text() + (ROOT / "tests" / Path(__file__).name).read_text()
    for name in EXEMPT:
        assert name in body, f"{name} is exempt and nothing says why"
