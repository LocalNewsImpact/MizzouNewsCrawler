#!/usr/bin/env bash
# make stress: the versioning concurrency tests, against Postgres, weekly.
set -euo pipefail

: "${DATABASE_URL:?run this through make stress, which sets the database}"
alembic upgrade head
RUN_STRESS_TESTS=1 pytest --override-ini addopts='-q' tests/test_versioning_concurrent_stress.py
