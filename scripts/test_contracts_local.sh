#!/usr/bin/env bash
# Local venue simulator for the dependency contracts.
#
# Reproduces EXACTLY how cloudbuild-pr-image-check.yaml runs the contracts —
# so venue bugs (mount-depth paths, files missing from the upload set, baked
# env-var invocations) surface here in ~1 minute instead of in a ~20-minute
# Cloud Build cascade.
#
# Fidelity guarantees:
#   1. The suite is staged from the ACTUAL gcloud upload manifest
#      (`gcloud meta list-files-for-upload`), so anything .gcloudignore
#      strips is missing here too — the tests/-exclusion bug would have
#      failed this script, not round 2 of CI.
#   2. Mounted at /contracts, read-only, same pytest flags — the parents[2]
#      crash would have failed this script, not round 4.
#   3. Runs inside the real images (default: current prod tags), so baked
#      env contracts (CHROMEDRIVER_PATH, CHROME_BIN, /app/models) hold —
#      the uc.Chrome driver-mismatch would have failed this script, not
#      round 5.
#
# Usage:
#   scripts/test_contracts_local.sh                    # processor + crawler
#   scripts/test_contracts_local.sh processor          # one image
#   IMAGES="api migrator" scripts/test_contracts_local.sh
#   TAG=pr-check scripts/test_contracts_local.sh       # locally built tags
set -euo pipefail

REGISTRY="${REGISTRY:-us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler}"
TAG="${TAG:-latest}"
IMAGES="${IMAGES:-${*:-processor crawler}}"

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

echo "── staging contracts from the real gcloud upload manifest ──"
manifest=$(gcloud meta list-files-for-upload . | grep '^tests/dependency_contracts/' || true)
if [ -z "$manifest" ]; then
  echo "❌ tests/dependency_contracts is NOT in the gcloud upload set —"
  echo "   .gcloudignore is stripping it; Cloud Build would see an empty mount."
  exit 1
fi
mkdir -p "$STAGE/contracts"
while IFS= read -r f; do
  cp "$f" "$STAGE/contracts/"
done <<< "$manifest"
echo "staged $(ls "$STAGE/contracts" | wc -l | tr -d ' ') files"

fail=0
for img in $IMAGES; do
  ref="$REGISTRY/$img:$TAG"
  # Prefer a local image (e.g. TAG=pr-check builds); else pull.
  if ! docker image inspect "$ref" >/dev/null 2>&1; then
    echo "── pulling $ref ──"
    docker pull -q "$ref" || { echo "❌ cannot pull $ref"; fail=1; continue; }
  fi
  echo ""
  echo "════ contracts in $img ($ref) ════"
  # Identical invocation to cloudbuild-pr-image-check.yaml contracts()
  if ! docker run --rm \
      -v "$STAGE/contracts":/contracts:ro \
      --entrypoint bash "$ref" -c '
        echo "── contract evidence: $(python -V 2>&1) ──"
        pip install --no-cache-dir -q pytest || pip install --no-cache-dir -q --user pytest
        python -m pytest /contracts -q -rs -o addopts="" -p no:cacheprovider
      '; then
    fail=1
  fi
done
exit $fail
