#!/usr/bin/env bash
# make test: the coverage suite.
#
# Everything not marked postgres, docker or local_scripts, on SQLite,
# measured, then judged against the suite's floor. The floor is
# lnic-contracts' -- one number for every repository, read from
# coverage.xml -- so no --cov-fail-under here or in pytest.ini. The
# three database URLs are cleared first so a shell that exports one for
# the API or a script does not turn this into a different suite:
# conftest.py picks SQLite when DATABASE_URL is unset and whatever
# DATABASE_URL names when it is not, and CI sets none of them for this
# stage.
set -euo pipefail

mkdir -p data
unset DATABASE_URL TEST_DATABASE_URL TELEMETRY_DATABASE_URL
pytest -m 'not postgres and not docker and not local_scripts' \
    --cov=src --cov-report=xml --cov-report=html --cov-report=term-missing
python tools/generate_coverage_summary.py coverage.xml coverage-summary.md
python -m lnic_contracts.coverage_floor coverage.xml
