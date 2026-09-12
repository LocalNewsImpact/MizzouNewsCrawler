#!/usr/bin/env bash
# Emit `export <SERVICE>_TAG=...` lines for a manifest apply.
#
# WHY. Applying a manifest substitutes an image tag into it, so an apply
# needs a tag for every service the manifests mention -- including ones
# this deploy did not build. Left empty, `envsubst` writes the literal
# `${CRAWLER_TAG}` into the cluster and the workload fails to pull an
# image called `${CRAWLER_TAG}`; guessed as `latest`, it silently rolls a
# service back to whatever `latest` last pointed at.
#
# So: a tag this deploy built wins, and anything else keeps what the
# cluster is already running. An apply never moves an image the push did
# not change.
#
# Usage:
#   BUILT_PROCESSOR=8ad6aee ./scripts/resolve-image-tags.sh > versions.env
#   . versions.env
#
# One BUILT_<SERVICE> per service that was built, holding the tag. Live
# tags are read from the namespace's Deployments and CronJobs, which
# between them run every image (enrichment runs only from a CronJob and
# an Argo template, so Deployments alone are not enough -- that is the
# shape that made a previous version of this leave ENRICHMENT_TAG empty).
set -euo pipefail

NAMESPACE="${NAMESPACE:-production}"
SERVICES="${SERVICES:-processor crawler api enrichment}"

live_images() {
    kubectl get deploy -n "$NAMESPACE" -o \
        jsonpath='{range .items[*]}{range .spec.template.spec.containers[*]}{.image}{"\n"}{end}{end}' 2>/dev/null
    kubectl get cronjob -n "$NAMESPACE" -o \
        jsonpath='{range .items[*]}{range .spec.jobTemplate.spec.template.spec.containers[*]}{.image}{"\n"}{end}{end}' 2>/dev/null
}

IMAGES="$(live_images || true)"

for svc in $SERVICES; do
    upper="$(echo "$svc" | tr '[:lower:]' '[:upper:]')"
    built_var="BUILT_${upper}"
    tag="${!built_var:-}"
    source="built by this deploy"

    if [ -z "$tag" ]; then
        # The longest match wins nothing here: the reference is
        # `<registry>/<repo>/<service>:<tag>`, so anchor on the slash.
        # `|| true`: grep exits 1 when nothing matches, and under
        # `set -e` with `pipefail` that killed the script before the
        # error below could say WHICH service had no tag -- exit 1 and
        # not a word on stderr.
        tag="$(printf '%s\n' "$IMAGES" | grep -oE "/${svc}:[A-Za-z0-9_.-]+" | head -1 | cut -d: -f2 || true)"
        source="already running"
    fi

    if [ -z "$tag" ]; then
        echo "::error::no tag for ${svc}: it was not built here and nothing" \
             "in namespace ${NAMESPACE} is running it. Applying a manifest" \
             "with an empty tag deploys a pull failure." >&2
        exit 1
    fi
    echo "# ${svc}: ${source}"
    echo "export ${upper}_TAG=${tag}"
done
