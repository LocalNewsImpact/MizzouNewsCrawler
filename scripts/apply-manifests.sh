#!/bin/bash
set -e

# Usage: ./scripts/apply-manifests.sh [services...]
# Services: api, processor, crawler, all (or no args for all)
# Examples:
#   ./scripts/apply-manifests.sh crawler           # Only crawler manifests
#   ./scripts/apply-manifests.sh api processor     # API and processor manifests
#   ./scripts/apply-manifests.sh all               # All manifests (same as no args)
#   ./scripts/apply-manifests.sh                   # All manifests

# The tags to apply.
#
# k8s/versions.env used to be committed and sourced here, and it went
# stale after every deploy -- so applying by hand could move the cluster
# BACKWARDS onto whatever the file happened to say. The repository no
# longer records what is deployed.
#
# Say what you mean, in the environment:
#
#   CRAWLER_TAG=abc1234 PROCESSOR_TAG=abc1234 API_TAG=abc1234 \
#     ./scripts/apply-manifests.sh crawler
#
# A versions.env downloaded from a deploy's run (the `versions-env`
# artifact) still works: source it first, or leave it here and it is
# picked up.
[ -f versions.env ] && source versions.env
[ -f k8s/versions.env ] && source k8s/versions.env

for _needed in PROCESSOR_TAG CRAWLER_TAG API_TAG; do
    if [ -z "${!_needed:-}" ]; then
        echo "❌ $_needed is not set."
        echo "   Pass the tags you mean to deploy, or source the versions-env"
        echo "   artifact from the deploy whose images you want:"
        echo "     gh run download <run-id> -n versions-env && source versions.env"
        echo "   What is running now:"
        echo "     kubectl get deploy -n production -o jsonpath='{range .items[*]}{.metadata.name}{\"\\t\"}{.spec.template.spec.containers[0].image}{\"\\n\"}{end}'"
        exit 1
    fi
done

apply_file() {
    local file=$1
    if [ ! -f "$file" ]; then
        echo "❌ File not found: $file"
        return 1
    fi

    echo "🚀 Applying $file with substitutions..."
    # Use envsubst to replace variables defined in versions.env
    # We only substitute variables that are defined to avoid breaking other $VARs in the yaml
    # ENRICHMENT_TAG is here because the housekeeping workflow runs the
    # enrichment image. Left out, envsubst passes `${ENRICHMENT_TAG}`
    # through as a literal and the applied template names an image that
    # cannot be pulled -- which surfaces as a workflow that fails at its
    # last step, long after the apply reported success.
    envsubst '${PROCESSOR_TAG} ${CRAWLER_TAG} ${API_TAG} ${ENRICHMENT_TAG}' < "$file" | kubectl apply -n production -f -
}

apply_api() {
    apply_file k8s/api-deployment.yaml
}

apply_processor() {
    apply_file k8s/processor-deployment.yaml
}

apply_crawler() {
    apply_file k8s/work-queue-deployment.yaml
    apply_file k8s/crawler-cronjob.yaml
    apply_file k8s/housekeeping-cronjob.yaml
    # Apply Minnesota Argo workflow (runs on demand, not continuously)
    kubectl apply -n production -f k8s/argo/minnesota-processing-workflow.yaml
    # The daily housekeeping workflow, and the schedule that fires it.
    #
    # Both, and in this order: the CronWorkflow references the template by
    # name, so a schedule applied without it fires and fails on a missing
    # templateRef -- which reports as a workflow error rather than as
    # "nothing is deployed", and reads like a bug in the pipeline.
    #
    # Without these lines the workflow lives in the repository and nowhere
    # else. The reconciler sets statuses nightly and nothing picks them
    # up: 4,805 links sat at `article` and 450 articles at `cleaned` after
    # the first reconciliation, waiting for a stage that was never
    # deployed.
    apply_file k8s/argo/housekeeping-workflow.yaml
    apply_file k8s/argo/housekeeping-cronworkflow.yaml
}

apply_all() {
    echo "Applying all manifests..."
    apply_api
    apply_processor
    apply_crawler
}

# Parse arguments
if [ $# -eq 0 ]; then
    apply_all
else
    for arg in "$@"; do
        case "$arg" in
            all)
                apply_all
                ;;
            api)
                apply_api
                ;;
            processor)
                apply_processor
                ;;
            crawler)
                apply_crawler
                ;;
            *)
                # Treat as file path for backwards compatibility
                if [ -f "$arg" ]; then
                    apply_file "$arg"
                else
                    echo "❌ Unknown service or file: $arg"
                    echo "Valid services: api, processor, crawler, all"
                    exit 1
                fi
                ;;
        esac
    done
fi
