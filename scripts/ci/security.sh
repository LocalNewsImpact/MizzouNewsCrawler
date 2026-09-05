#!/usr/bin/env bash
# make security. Advisory, as it was as a CI job: both scanners report and
# neither fails the build.
set -euo pipefail

python -m bandit -r src/ -ll -f txt || echo "bandit found issues (review recommended)"
python -m safety check --json || echo "safety found issues (review recommended)"
