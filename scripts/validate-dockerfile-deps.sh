#!/bin/bash
# Verify that every file a Dockerfile copies is actually in the repository,
# so a build fails here rather than eight minutes into Cloud Build.
#
# WHY THIS SCRIPT COULD NOT FAIL
# ------------------------------
# It counted errors inside a `while` loop on the right-hand side of a pipe.
# A pipeline runs each stage in a subshell, so every `ERRORS=$((ERRORS + 1))`
# incremented a variable in a process that then exited; the parent's copy was
# still 0 at the end and the script printed "All Dockerfile dependencies
# exist" and returned 0 whatever it had found. It has been in CI since
# January, has never once failed, and could not have.
#
# The loop now reads from a process substitution, which runs in this shell.

set -euo pipefail

DOCKERFILES=(
    Dockerfile.base
    Dockerfile.ml-base
    Dockerfile.ci-base
    Dockerfile.api
    Dockerfile.crawler
    Dockerfile.processor
    Dockerfile.migrator
    Dockerfile.enrichment
)

# Sources a BUILD STEP provides, which a checkout therefore does not have.
# The model is 418 MB and lives in GCS, not git (`.gitignore` line 104);
# `cloudbuild-ml-base.yaml` fetches it into the context before the build.
# An exemption that outlives the step that justifies it is how a check
# stops checking, so tests/test_the_dockerfile_validator_can_fail.py
# asserts that each of these is still fetched by a Cloud Build config.
PROVIDED_AT_BUILD_TIME=(
    "models/productionmodel.pt"
)

echo "=========================================="
echo "Validating Dockerfile Dependencies"
echo "=========================================="

missing=()

for dockerfile in "${DOCKERFILES[@]}"; do
    if [ ! -f "$dockerfile" ]; then
        echo "⚠️  Skipping $dockerfile (not found)"
        continue
    fi

    echo ""
    echo "Checking $dockerfile..."

    # Join continuation lines first: a COPY split across two lines is one
    # instruction, and reading it as two hides the second half.
    while IFS= read -r line; do
        # `COPY --from=builder` copies out of an earlier stage, not the
        # build context, so the repository has nothing to check.
        [[ "$line" == *"--from="* ]] && continue

        # Everything but the instruction, the flags and the destination.
        read -r -a parts <<< "$line"
        sources=("${parts[@]:1:${#parts[@]}-2}")

        for source in "${sources[@]}"; do
            [[ "$source" == --* ]] && continue
            [[ -z "$source" || "$source" == /* ]] && continue
            [[ "$source" =~ ^https?:// ]] && continue
            # A wildcard that matches nothing is still a broken build, but
            # `[ -e ]` cannot answer for a glob; leave it to the build.
            [[ "$source" == *"*"* ]] && continue

            provided=""
            for artifact in "${PROVIDED_AT_BUILD_TIME[@]}"; do
                [ "$source" = "$artifact" ] && provided=yes && break
            done
            if [ -n "$provided" ]; then
                echo "  ⤓ Provided at build time: $source"
            elif [ -e "$source" ]; then
                echo "  ✓ Found: $source"
            else
                echo "  ❌ Missing: $source"
                missing+=("$dockerfile: $source")
            fi
        done
    done < <(awk '{
                 if (buf != "") { $0 = buf $0; buf = "" }
                 if (/\\$/) { sub(/\\$/, ""); buf = $0; next }
                 print
             } END { if (buf != "") print buf }' "$dockerfile" |
             grep -E '^[[:space:]]*(COPY|ADD)[[:space:]]+' || true)
done

echo ""
echo "=========================================="
if [ ${#missing[@]} -gt 0 ]; then
    echo "❌ Found ${#missing[@]} missing file(s) referenced in Dockerfiles"
    printf '   %s\n' "${missing[@]}"
    echo "   Docker builds will fail. Please restore or remove references."
    exit 1
fi
echo "✅ All Dockerfile dependencies exist"
