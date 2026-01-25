#!/usr/bin/env bash
set -euo pipefail

# Run the UA metadata diagnostic inside the chromedriver-test image and
# exit 0 if an acceptable payload was accepted (full_payload_exact or
# full_payload), or if the fallback top_platform_only was accepted.

docker run --rm -v "$PWD":/workspace -w /workspace chromedriver-test:ci bash -lc '
  pip install --no-cache-dir undetected-chromedriver
  python3 scripts/diagnose_user_agent_metadata.py > /tmp/diag.json || true
  python3 - <<PY
import json,sys
r=json.load(open("/tmp/diag.json"))

def passed(name):
    for e in r:
        if e.get("test")==name:
            return e.get("ok")
    return False

if passed("full_payload_exact"):
    print("✅ full_payload_exact accepted")
    sys.exit(0)
if passed("full_payload"):
    print("✅ full_payload accepted")
    sys.exit(0)
if passed("top_platform_only"):
    print("⚠️ full_payload rejected; top_platform_only accepted — continuing")
    sys.exit(0)
print("❌ UA metadata checks failed (full_payload and fallbacks not accepted)")
sys.exit(1)
PY
'
