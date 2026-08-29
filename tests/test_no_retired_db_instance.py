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
