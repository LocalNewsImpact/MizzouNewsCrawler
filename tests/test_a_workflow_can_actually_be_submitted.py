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


# --- a secret reference names a key the secret has -------------------------------


def _secret_refs(doc):
    """Every (secret, key) an env var in this manifest reads."""
    spec = _spec(doc)
    refs = set()
    for template in spec.get("templates", []):
        container = template.get("container") or template.get("script") or {}
        for env in container.get("env") or []:
            ref = ((env.get("valueFrom") or {}).get("secretKeyRef")) or {}
            if ref.get("name") and ref.get("key"):
                refs.add((ref["name"], ref["key"]))
    return refs


def test_every_secret_key_matches_one_another_manifest_uses():
    """A key that does not exist in the secret is not a validation error
    anywhere: `kubectl apply` accepts it, `argo submit` accepts it, and
    kubelet reports "couldn't find key ... in Secret" while RESTARTING the
    container. Argo shows the step Pending, never Failed, so the run looks
    like it is working -- 278 restarts over 63 minutes, until the deadline
    killed it.

    Nothing in a repository can see a live secret's keys, but the cronjobs
    that have been running for months name the same secrets. Held to those:
    a manifest inventing a key name disagrees with the one that works.
    """
    known: dict[str, set[str]] = {}
    for path in ROOT.glob("k8s/*.yaml"):
        for doc in yaml.safe_load_all(path.read_text()):
            if not isinstance(doc, dict):
                continue
            for secret, key in _all_refs(doc):
                known.setdefault(secret, set()).add(key)
    assert known, "no secret references found under k8s/; check the glob"

    for path in sorted(ROOT.glob("k8s/argo/*.yaml")):
        for doc in yaml.safe_load_all(path.read_text()):
            if not isinstance(doc, dict) or "spec" not in doc:
                continue
            for secret, key in _secret_refs(doc):
                if secret not in known:
                    continue
                assert key in known[secret], (
                    f"{path.name} reads {secret}/{key}; the manifests that "
                    f"run name {sorted(known[secret])}"
                )


def _all_refs(doc):
    """Secret references anywhere in a plain Kubernetes manifest."""
    found = set()

    def walk(node):
        if isinstance(node, dict):
            ref = node.get("secretKeyRef")
            if isinstance(ref, dict) and ref.get("name") and ref.get("key"):
                found.add((ref["name"], ref["key"]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(doc)
    return found
