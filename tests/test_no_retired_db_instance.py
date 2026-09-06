"""Nothing that gets deployed may name the retired database instance.

The database moved from PD_HDD to PD_SSD. Cloud SQL cannot change
storage type in place, so it meant a new instance under a new name, and
`mizzou-db-prod` is being deleted.

A runtime change does not survive a deploy. Both datadesk Cloud Run
services were pointed at the new instance by hand and the next merge to
main put them back, because the connection name is written into the
deploy workflow and the Cloud Build substitutions. The service kept
serving the whole time -- against the wrong database. That is the class
of failure this guards: silent, and invisible from the outside.

Historical records under docs/ are deliberately not covered. They
describe what was true when they were written.

WHAT THIS MISSED, AND THE SECOND TEST BELOW
-------------------------------------------
The check above reads files for the retired name, and passed the whole
time the migration job was writing to the retired instance. It had
nothing to catch: `k8s/deploy-migration-job.tpl.yaml` named no instance
at all. It took one from the `cloudsql-db-credentials` secret, and the
secret in the `production` namespace still held the old name -- so the
one deployed file that did not say which database it meant was the one
that went to the wrong one, for eight days, reporting success.

So a file that is silent about its database is the failure mode, not
just a file that names the wrong one. Every deployed manifest that
connects to Cloud SQL must say so in the file.
"""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RETIRED = "mizzou-db-prod"

#: Everything whose contents reach a running system.
DEPLOYED = (
    "k8s/*.yaml",
    "k8s/templates/*.yaml",
    "k8s/argo/*.yaml",
    "gcp/cloudbuild/*.yaml",
    "manifests/*.yaml",
    "monitoring/*.sh",
    "gcp_functions/**/*.py",
    "scripts/*.py",
)


def _offending_lines(path):
    return [
        line.strip()
        for line in path.read_text(errors="ignore").splitlines()
        if RETIRED in line and f"{RETIRED}-ssd" not in line
    ]


@pytest.mark.parametrize("pattern", DEPLOYED)
def test_no_deployed_file_names_the_retired_instance(pattern):
    offenders = {}
    for path in REPO.glob(pattern):
        lines = _offending_lines(path)
        if lines:
            offenders[str(path.relative_to(REPO))] = lines
    assert not offenders, (
        f"These are deployed and still name {RETIRED}, which is being "
        f"deleted: {offenders}"
    )


#: The instance everything runs against. One place, so the next move is
#: one edit and this test names what it expects.
LIVE = "mizzou-news-crawler:us-central1:mizzou-db-prod-ssd"

#: Manifests that connect to the database.
MANIFESTS = ("k8s/*.yaml", "k8s/templates/*.yaml", "k8s/argo/*.yaml")


def _instance_settings(text):
    """Each `CLOUD_SQL_INSTANCE` env entry, with its own value and no
    other's.

    Read as text rather than parsed: these files carry `__IMAGE__` style
    placeholders and Argo's `{{...}}` templating, and half of them are
    not valid YAML until something renders them.

    The entry ends where the next one begins. A fixed window of lines
    read the FOLLOWING variable's `secretKeyRef` and reported it against
    this one, which flagged six manifests that were correct.
    """
    lines = text.splitlines()
    found = []
    for i, line in enumerate(lines):
        if not line.strip().startswith("- name: CLOUD_SQL_INSTANCE"):
            continue
        indent = len(line) - len(line.lstrip())
        block = [line]
        for following in lines[i + 1 :]:
            stripped = following.strip()
            starts_next = (
                stripped.startswith("- name:")
                and (len(following) - len(following.lstrip())) <= indent
            )
            if starts_next or (stripped and not following.startswith(" " * indent)):
                break
            block.append(following)
        found.append("\n".join(block))
    return found


@pytest.mark.parametrize("pattern", MANIFESTS)
def test_a_manifest_says_which_database_it_means(pattern):
    """No deployed manifest may take the instance from a secret.

    Credentials belong in a secret. An instance name is not a
    credential -- it is which database this is -- and a manifest that
    does not say cannot be reviewed, cannot be diffed, and is invisible
    to the check above.
    """
    from_secret = {}
    for path in REPO.glob(pattern):
        for block in _instance_settings(path.read_text(errors="ignore")):
            if "secretKeyRef" in block:
                from_secret[str(path.relative_to(REPO))] = block.strip()
    assert not from_secret, (
        "These take CLOUD_SQL_INSTANCE from a secret, so the file does not "
        f"say which database it means: {from_secret}"
    )


@pytest.mark.parametrize("pattern", MANIFESTS)
def test_every_manifest_names_the_live_instance(pattern):
    wrong = {}
    for path in REPO.glob(pattern):
        for block in _instance_settings(path.read_text(errors="ignore")):
            if LIVE not in block:
                wrong[str(path.relative_to(REPO))] = block.strip()
    assert not wrong, f"These name something other than {LIVE}: {wrong}"
