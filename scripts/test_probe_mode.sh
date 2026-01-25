#!/usr/bin/env bash
set -euo pipefail

# Simple smoke test for probe-mode runner (requires Docker)
SCRIPTDIR=$(cd "$(dirname "$0")" && pwd)
HOST=tools.scrapfly.io
$SCRIPTDIR/run_probes.sh $HOST
if [ ! -f "artifacts/probes/$HOST/probe.log" ]; then
  echo "probe.log missing" >&2
  exit 2
fi
if ! grep -q "probe-only result:" "artifacts/probes/$HOST/probe.log"; then
  echo "probe did not report a result" >&2
  exit 2
fi
echo "Probe smoke test passed for $HOST"
