#!/usr/bin/env bash
# Does a range of commits change nothing the suite covers?
#
#   scripts/ci/docs-only.sh <from> <to>
#
# Exit 0 when every file changed between the two commits is documentation
# -- Markdown, docs/, images, the licence, CODEOWNERS -- and 1 otherwise.
# The workflow's `changes` job and the pre-push hook both ask this, and
# they ask it here so the answer cannot differ between them.
#
# A deny-list, not an allow-list. The gate this replaced named the paths
# that did NOT count as code, and .github/workflows/ was on that list, so
# a change to CI itself was the one change CI never ran. Anything not
# named here runs the suite; YAML in particular always does.
#
# An empty range -- nothing changed, or the commits are the same -- is
# not docs-only. Running the suite is the safe answer when unsure.
set -euo pipefail

from="${1:?from-commit}"
to="${2:?to-commit}"

changed=$(git diff --name-only "$from" "$to")
[ -n "$changed" ] || exit 1

code=$(printf '%s\n' "$changed" \
    | grep -vE '^docs/|\.md$|\.(png|jpe?g|gif|svg|webp)$|^LICENSE$|^(\.github/)?CODEOWNERS$' \
    || true)
[ -z "$code" ]
