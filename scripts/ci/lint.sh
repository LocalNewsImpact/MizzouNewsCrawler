#!/usr/bin/env bash
# make lint.
#
# Style and imports, plus the two configuration checks that have to fail a
# pull request and need nothing but the checkout: the Argo workflow
# template, and the processor deployment's PYTHONPATH and image reference.
set -euo pipefail

python -m ruff check .
python -m black --check src/ tests/ web/
python -m isort --check-only --profile black src/ tests/ web/
python3 scripts/validate_workflow_templates.py

# The processor runs from /app; a PYTHONPATH without it imports nothing.
if ! grep -q 'value: "/app:' k8s/processor-deployment.yaml; then
    echo "k8s/processor-deployment.yaml: PYTHONPATH does not include /app" >&2
    exit 1
fi
# The deploy job substitutes the built tag; a :latest here would never move.
if grep -q 'image:.*:latest' k8s/processor-deployment.yaml; then
    echo "k8s/processor-deployment.yaml: uses image:latest" >&2
    exit 1
fi
