"""Argo validates a workflow when it is SUBMITTED, not when it is applied.

`kubectl apply` accepts any WorkflowTemplate whose YAML parses. The
parameter wiring -- which step passes what to which template, and whether
`{{workflow.parameters.x}}` names anything -- is checked at submit, and a
mistake there fails the whole run before its first stage:

    templates.housekeeping.steps[2].classify templates.classify-step
    inputs.parameters.limit was not supplied

The housekeeping template shipped in exactly that state. Its tests read
step names, gates and commands out of the file -- assertions about strings
somebody had just written -- and nothing walked step to referenced
template. The apply reported success, and the error was waiting to be the
first thing a resumed schedule did.

These walk the graph. They are deliberately generic: every manifest here,
every step, every parameter.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
ARGO = sorted((ROOT / "k8s/argo").glob("*.yaml"))


def _docs():
    for path in ARGO:
        for doc in yaml.safe_load_all(path.read_text()):
            if isinstance(doc, dict) and doc.get("kind") in (
                "WorkflowTemplate",
                "CronWorkflow",
                "Workflow",
            ):
                yield path, doc


def _spec(doc):
    """The workflow spec, wherever this kind keeps it."""
    return doc["spec"].get("workflowSpec", doc["spec"])


def _required(template):
    """Parameters a template will not supply for itself."""
    return {
        p["name"]
        for p in (template.get("inputs") or {}).get("parameters", [])
        if "value" not in p and "default" not in p
    }


def _steps(template):
    for group in template.get("steps", []):
        for step in group:
            yield step
    for task in (template.get("dag") or {}).get("tasks", []):
        yield task


MANIFESTS = list(_docs())

#: Parameters that are declared and read by nothing, found by the test
#: below and left alone because they predate it and belong to a template
#: this work does not touch. Listed rather than tolerated silently: a knob
#: that does nothing reads as a control, and somebody will turn it.
KNOWN_DEAD_KNOBS = {
    ("base-pipeline-workflow.yaml", "pipeline", "verified-wait-seconds"),
    ("base-pipeline-workflow.yaml", "verification-step", "max-batches"),
}


def test_there_are_manifests_to_check():
    """A glob that matches nothing passes every test below."""
    assert MANIFESTS, "no Argo manifests found under k8s/argo/"


@pytest.mark.parametrize("path,doc", MANIFESTS, ids=lambda v: getattr(v, "name", ""))
def test_every_step_supplies_what_its_template_requires(path, doc):
    spec = _spec(doc)
    templates = {t["name"]: t for t in spec.get("templates", [])}
    for template in templates.values():
        for step in _steps(template):
            name = step.get("template")
            if name is None or name not in templates:
                # A templateRef points at another object; its inputs are
                # checked in the file that defines it.
                continue
            supplied = {
                p["name"] for p in (step.get("arguments") or {}).get("parameters", [])
            }
            missing = _required(templates[name]) - supplied
            assert not missing, (
                f"{path.name}: step {step['name']} calls {name} without "
                f"{sorted(missing)}. Argo refuses this at submit."
            )


@pytest.mark.parametrize("path,doc", MANIFESTS, ids=lambda v: getattr(v, "name", ""))
def test_every_workflow_parameter_referenced_is_declared(path, doc):
    """`{{workflow.parameters.x}}` resolves against the WORKFLOW's own
    arguments, not against a template's inputs. `enrich-step` defaulted
    its spend ceiling from a workflow parameter no manifest declared."""
    spec = _spec(doc)
    declared = {p["name"] for p in (spec.get("arguments") or {}).get("parameters", [])}
    used = set(
        re.findall(r"\{\{workflow\.parameters\.([A-Za-z0-9_-]+)\}\}", yaml.dump(spec))
    )
    assert used <= declared, (
        f"{path.name}: {sorted(used - declared)} referenced as "
        "workflow.parameters but declared nowhere"
    )


@pytest.mark.parametrize("path,doc", MANIFESTS, ids=lambda v: getattr(v, "name", ""))
def test_every_step_names_a_template_that_exists(path, doc):
    spec = _spec(doc)
    templates = {t["name"]: t for t in spec.get("templates", [])}
    body = yaml.dump(spec)
    for template in templates.values():
        for step in _steps(template):
            name = step.get("template")
            if name is None:
                assert step.get(
                    "templateRef"
                ), f"{path.name}: step {step['name']} names no template"
                continue
            assert (
                name in templates or f"name: {name}" in body
            ), f"{path.name}: step {step['name']} calls missing template {name}"


@pytest.mark.parametrize("path,doc", MANIFESTS, ids=lambda v: getattr(v, "name", ""))
def test_a_declared_parameter_is_used(path, doc):
    """A parameter nothing reads is a knob that does nothing. The
    housekeeping template advertised `extract-limit` and `extract-batches`
    while its extraction step hardcoded 25 and 8, so turning them down
    changed nothing."""
    spec = _spec(doc)
    body = yaml.dump(spec)
    for template in spec.get("templates", []):
        for param in (template.get("inputs") or {}).get("parameters", []):
            name = param["name"]
            reference = f"inputs.parameters.{name}"
            if (path.name, template["name"], name) in KNOWN_DEAD_KNOBS:
                continue
            assert body.count(reference) >= 1, (
                f"{path.name}: {template['name']} declares {name} and "
                "nothing reads it"
            )


def test_the_housekeeping_entrypoint_is_reachable():
    """The CronWorkflow names an entrypoint and wraps the shared template.
    A submit needs that entrypoint to exist, and `argo submit --from
    workflowtemplate` needed one the template itself did not name."""
    cron = yaml.safe_load(
        (ROOT / "k8s/argo/housekeeping-cronworkflow.yaml").read_text()
    )
    spec = cron["spec"]["workflowSpec"]
    entry = spec["entrypoint"]
    assert entry in {t["name"] for t in spec["templates"]}
