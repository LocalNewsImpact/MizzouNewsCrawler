"""A built image that never reaches the workload running it.

Each service's Cloud Build config ends with `kubectl set image` calls
naming the workloads to move onto the tag it just built. The list is
written by hand, and three workloads were not on it:

    mizzou-housekeeping     processor:0b28478   nine months behind
    proxy-health-monitor    api:latest          a moving tag
    proxy-health-all-nodes  api:latest          a moving tag

Nothing failed. The deployments moved, the CronJobs did not, and the
only way to notice was to read what the cluster was running.

These tests compare the manifests against the build configs: every
workload that runs one of our images must be named by the build that
produces it.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
K8S = ROOT / "k8s"
CLOUDBUILD = ROOT / "gcp/cloudbuild"

REGISTRY = "us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler"
#: The images a build produces, by the config that produces them.
BUILDS = {
    "processor": CLOUDBUILD / "cloudbuild-processor.yaml",
    "api": CLOUDBUILD / "cloudbuild-api.yaml",
    "crawler": CLOUDBUILD / "cloudbuild-crawler.yaml",
    "enrichment": CLOUDBUILD / "cloudbuild-enrichment.yaml",
}

#: Workloads whose manifest is in the repository and whose workload is not
#: in the cluster. An exemption has to be written down with its reason
#: rather than discovered from a stale tag.
#:
#: Checked against `production` on 2026-09-05: neither exists. They are
#: still edited -- both were touched by the SSD migration on 2026-08-29 --
#: which is the cost of keeping a manifest for something that is not
#: running: it takes maintenance and gives nothing back, and a reader
#: cannot tell it from the ones that matter.
NOT_DEPLOYED = {
    "minnesota-processor": (
        "Deployment for the Minnesota dataset; not in the cluster. It also "
        "pins processor:latest, which is why it is exempt from the moving-tag "
        "check too."
    ),
    "mizzou-processor-cronjob": (
        "CronJob in k8s/processor-cronjob.yaml, sharing its name with the "
        "Deployment; only the Deployment is in the cluster."
    ),
}
EXEMPT: dict[str, str] = NOT_DEPLOYED


def _manifests():
    for path in sorted(K8S.rglob("*.yaml")):
        if "overlays" in path.parts or path.name.endswith(".tpl.yaml"):
            continue
        text = path.read_text()
        # envsubst placeholders are not YAML; a tag is enough for parsing.
        text = re.sub(r"\$\{[A-Z_]+\}", "TAG", text)
        try:
            for doc in yaml.safe_load_all(text):
                if isinstance(doc, dict) and doc.get("kind"):
                    yield path, doc
        except yaml.YAMLError:
            continue


def _containers(doc):
    """Every container in a workload, whatever kind it is."""
    kind = doc.get("kind")
    spec = doc.get("spec") or {}
    if kind == "CronJob":
        spec = (spec.get("jobTemplate") or {}).get("spec") or {}
    template = (spec.get("template") or {}).get("spec") or {}
    return kind, template.get("containers") or []


def _ours(image):
    return image.startswith(REGISTRY)


def _workloads_running_our_images():
    """(kind, name, container, image-name) for each of ours."""
    found = []
    for path, doc in _manifests():
        kind, containers = _containers(doc)
        if kind not in {"Deployment", "CronJob"}:
            continue
        for container in containers:
            image = container.get("image", "")
            if not _ours(image):
                continue
            found.append(
                (
                    kind,
                    doc["metadata"]["name"],
                    container.get("name", ""),
                    image[len(REGISTRY) + 1 :].split(":")[0],
                    path,
                )
            )
    return found


def _updated_by(build_path):
    """The workloads a build config sets an image on."""
    steps = yaml.safe_load(build_path.read_text().replace("${", "$_{"))["steps"]
    updated = set()
    for step in steps:
        args = step.get("args") or []
        if args[:2] != ["set", "image"]:
            continue
        target = args[2]
        kind, _, name = target.partition("/")
        updated.add((kind, name))
    return updated


def test_the_manifests_are_readable():
    """A guard that reads nothing asserts nothing."""
    assert _workloads_running_our_images()


@pytest.mark.parametrize(
    "workload",
    _workloads_running_our_images(),
    ids=lambda w: f"{w[1]}:{w[3]}" if isinstance(w, tuple) else str(w),
)
def test_every_workload_is_moved_onto_the_tag_that_was_built(workload):
    kind, name, _container, image, path = workload
    key = f"{name}-cronjob" if kind == "CronJob" else name
    if key in EXEMPT:
        pytest.skip(EXEMPT[key])
    if name in EXEMPT and kind != "CronJob":
        pytest.skip(EXEMPT[name])
    build = BUILDS.get(image)
    assert build, f"{name} runs {image}, which no build config here produces"
    updated = _updated_by(build)
    assert (kind.lower(), name) in updated, (
        f"{name} ({path.name}) runs {image} and {build.name} does not "
        f"`kubectl set image` on it, so it stays on whatever tag it was "
        f"last applied with"
    )


@pytest.mark.parametrize(
    "workload",
    _workloads_running_our_images(),
    ids=lambda w: f"{w[1]}" if isinstance(w, tuple) else str(w),
)
def test_no_workload_pins_a_moving_tag(workload):
    """`:latest` makes "which code is running" unanswerable, and the two
    proxy-health CronJobs -- the check that says whether egress works at
    all -- were pinned to it."""
    _kind, name, _container, _image, path = workload
    if name in EXEMPT:
        pytest.skip(EXEMPT[name])
    text = path.read_text()
    assert f"{REGISTRY}/" in text
    for line in text.splitlines():
        if REGISTRY in line and line.strip().startswith("image:"):
            assert not line.rstrip().endswith(
                ":latest"
            ), f"{name} ({path.name}) pins a moving tag"


def test_the_container_names_match_what_the_build_sets():
    """`kubectl set image cronjob/x container=image` is silent when the
    container name is wrong -- it updates nothing and exits 0."""
    by_workload = {
        (kind.lower(), name): container
        for kind, name, container, _image, _path in _workloads_running_our_images()
    }
    for image, build in BUILDS.items():
        steps = yaml.safe_load(build.read_text().replace("${", "$_{"))["steps"]
        for step in steps:
            args = step.get("args") or []
            if args[:2] != ["set", "image"]:
                continue
            kind, _, name = args[2].partition("/")
            container = args[3].split("=")[0]
            expected = by_workload.get((kind, name))
            if expected is None:
                continue
            assert container == expected, (
                f"{build.name} sets {container}= on {name}, whose container "
                f"is named {expected}; kubectl would update nothing"
            )
