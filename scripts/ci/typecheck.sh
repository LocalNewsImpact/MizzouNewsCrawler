#!/usr/bin/env bash
# make typecheck. Blocking: this was the `mypy-strict` job, a required
# check, while `make lint` ran the same command with a `-` in front of it.
set -euo pipefail

python -m mypy src/ --ignore-missing-imports
