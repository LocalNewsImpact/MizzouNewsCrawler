#!/usr/bin/env bash
# make test-selenium, inside ghcr.io/localnewsimpact/mizzou-crawler as root.
#
# The crawler image, not the CI image: this is the one suite that needs
# the Chrome the crawler ships. It runs the headful path under Xvfb, as
# appuser, which is who runs it in production. The workspace is chowned
# because the mount belongs to the runner and appuser has to write
# .pytest_cache and the like into it.
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

chown -R appuser:appuser /workspace
su appuser -c 'export SELENIUM_EXECUTION_MODE=headful && /usr/local/bin/run-with-xvfb.sh pytest -m enable_selenium tests/test_selenium_only_feature.py -vv'
