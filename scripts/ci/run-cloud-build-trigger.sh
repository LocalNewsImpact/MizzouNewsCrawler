#!/usr/bin/env bash
# Run a Cloud Build trigger and wait for the build it starts.
#
# `gcloud builds triggers run` returns as soon as the build is queued, not
# when it finishes. The first version of .github/workflows/base-images.yml
# read that return as the build being done: ml-base and ci-base started at
# once, pulled a base:<tag> that was still being built, and failed -- and
# the Actions run stayed green, because nothing asked Cloud Build how any
# of it ended. Six builds between 2026-09-04 and 2026-09-05, no images.
#
# Usage: run-cloud-build-trigger.sh TRIGGER SHA [SUBSTITUTIONS]
#
# SUBSTITUTIONS is what `--substitutions` takes: "_A=x,_B=y". PROJECT_ID
# must be set. Exits 0 only when the build's final status is SUCCESS.
# POLL_SECONDS is how long to wait between status checks; the test sets
# it to 0.
set -euo pipefail

trigger=$1
sha=$2
substitutions=${3:-}
: "${PROJECT_ID:?PROJECT_ID must be set}"

args=(--project="$PROJECT_ID" --sha="$sha" --format='value(metadata.build.id)')
if [ -n "$substitutions" ]; then
    args+=(--substitutions="$substitutions")
fi

build_id=$(gcloud builds triggers run "$trigger" "${args[@]}")
if [ -z "$build_id" ]; then
    echo "::error::$trigger did not start a build"
    exit 1
fi
echo "$trigger started build $build_id"
echo "https://console.cloud.google.com/cloud-build/builds/$build_id?project=$PROJECT_ID"

# Longer than the longest config's own timeout (ml-base: 3600s), so the
# build's timeout is the one reported, with its log, not this one.
deadline=$((SECONDS + 4200))
while :; do
    status=$(gcloud builds describe "$build_id" --project="$PROJECT_ID" \
        --format='value(status)')
    case "$status" in
        SUCCESS)
            echo "$trigger: build $build_id succeeded"
            exit 0
            ;;
        FAILURE | INTERNAL_ERROR | TIMEOUT | CANCELLED | EXPIRED)
            echo "::error::$trigger: build $build_id ended $status"
            # Best effort: the log needs a permission this key may not have.
            gcloud builds log "$build_id" --project="$PROJECT_ID" 2>/dev/null | tail -40 || true
            exit 1
            ;;
    esac
    if [ "$SECONDS" -ge "$deadline" ]; then
        echo "::error::$trigger: gave up waiting for build $build_id (last status: ${status:-none})"
        exit 1
    fi
    echo "  $trigger: ${status:-queued}"
    sleep "${POLL_SECONDS:-30}"
done
