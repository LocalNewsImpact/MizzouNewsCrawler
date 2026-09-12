#!/usr/bin/env bash
# Log in to GHCR and pull one image, retrying the transient failures.
#
# WHY THIS IS NOT TWO LINES IN THE MAKEFILE. Six CI jobs start by pulling
# the CI image, and a single DNS hiccup on a runner failed one of them
# outright: `lookup ghcr.io on 127.0.0.53:53: i/o timeout`, on 2026-09-12,
# reported as "lint failed" 25 seconds in, before ruff had run. A registry
# pull is a network call on somebody else's network; it belongs behind a
# retry, and the retry belongs in one place because both the login and the
# pull can fail this way.
#
# Bounded, and it does not retry forever: four attempts with a widening
# wait, then the job fails for real. A pull that is broken rather than
# flaky (no such tag, no permission) fails on the first attempt and is not
# worth three more minutes of a runner -- so authentication and
# not-found are reported as themselves.
set -euo pipefail

image="${1:?usage: pull-image.sh <image>}"
attempts="${PULL_ATTEMPTS:-4}"
wait=5

login() {
    echo "${GITHUB_TOKEN:-$(gh auth token)}" | docker login ghcr.io \
        -u "${GITHUB_ACTOR:-$USER}" --password-stdin
}

for attempt in $(seq 1 "$attempts"); do
    if output=$( { login && docker pull "$image"; } 2>&1 ); then
        echo "$output"
        exit 0
    fi
    echo "$output" >&2

    # A permission or missing-tag answer is the registry working. Retrying
    # it just spends the runner's time and hides the real message.
    if grep -qiE "denied|unauthorized|not found|manifest unknown" <<<"$output"; then
        echo "pull-image: $image was refused, not dropped -- not retrying" >&2
        exit 1
    fi

    if [ "$attempt" -eq "$attempts" ]; then
        echo "pull-image: $image failed $attempts times, giving up" >&2
        exit 1
    fi
    echo "pull-image: attempt $attempt/$attempts failed, retrying in ${wait}s" >&2
    sleep "$wait"
    wait=$((wait * 3))
done
