#!/usr/bin/env bash
# make test-selenium, inside ghcr.io/localnewsimpact/mizzou-crawler as root.
#
# The crawler image, not the CI image: this is the one suite that needs
# the Chrome the crawler ships. It runs the headful path under Xvfb, as
# appuser, which is who runs it in production. The workspace is chowned
# because the mount belongs to the runner and appuser has to write
# .pytest_cache and the like into it, and handed back on exit so the
# runner's own post-steps can still write to it.
set -euo pipefail

if ! command -v Xvfb >/dev/null; then
    export DEBIAN_FRONTEND=noninteractive
    mkdir -p /var/lib/apt/lists/partial && chmod -R 755 /var/lib/apt/lists
    apt-get update >/dev/null && apt-get install -y xvfb >/dev/null
fi

cat <<'WRAPPER' >/usr/local/bin/run-with-xvfb.sh
#!/bin/bash
set -euo pipefail
DISPLAY_ID=":99"
XVFB_ARGS="-screen 0 1920x1080x24 -ac +extension GLX +render -noreset"
Xvfb "$DISPLAY_ID" $XVFB_ARGS &
XVFB_PID=$!
trap "kill $XVFB_PID" EXIT
DISPLAY=$DISPLAY_ID "$@"
WRAPPER
chmod +x /usr/local/bin/run-with-xvfb.sh

owner=$(stat -c '%u:%g' /workspace)
trap 'chown -R "$owner" /workspace' EXIT
chown -R appuser:appuser /workspace
# The files are named, not the whole suite: this runs in the crawler
# image, which carries no test-only dependencies, and collecting
# tests/ there fails on 24 modules before a browser is ever started.
# Within them, `-m enable_selenium` picks the tests that need Chrome.
#
# test_headful_chrome_runs_in_this_image.py is the point of the job:
# it starts a non-headless Chrome from the crawler's own driver
# factory and uses it. Nothing did that before -- every test in
# test_selenium_only_feature.py mocks the browser away, and the job
# passed because one unmocked, assertionless test fell through to a
# real browser for 177 seconds.
su appuser -c 'export SELENIUM_EXECUTION_MODE=headful && /usr/local/bin/run-with-xvfb.sh pytest -m enable_selenium tests/test_headful_chrome_runs_in_this_image.py tests/test_selenium_only_feature.py -vv'
