#!/usr/bin/env bash
# make test-integration: the tests marked integration, against Postgres.
#
# The database comes from the environment -- the Makefile derives it from
# the CI service (PGHOST and friends) or from a throwaway database on the
# compose Postgres -- and is migrated to head first. The marker expression
# excludes `proxy`, which is the Firestore suite (make test-firestore).
set -euo pipefail

: "${DATABASE_URL:?run this through make test-integration, which sets the database}"
mkdir -p data
alembic upgrade head
pytest -v -m 'integration and not docker and not local_scripts and not proxy' \
    --tb=short --no-cov
