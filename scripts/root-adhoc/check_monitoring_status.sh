#!/bin/bash

echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║       PRODUCTION MONITORING STATUS                            ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

# Check if monitoring is running
if ps -p 82157 > /dev/null 2>&1; then
    echo "✅ Monitoring process is RUNNING (PID: 82157)"
else
    echo "⏹️  Monitoring process has COMPLETED"
fi

echo ""

# Find the log file
LOG_FILE=$(ls -t /tmp/production_monitoring_*.json 2>/dev/null | head -1)

if [ -z "$LOG_FILE" ]; then
    echo "❌ No monitoring log file found"
    exit 1
fi

echo "📝 Log file: $LOG_FILE"
echo ""

# Parse and display status
python3 << 'PYEOF'
import json
import sys

try:
    LOG_FILE = "$LOG_FILE"
    with open(LOG_FILE.replace("$LOG_FILE", "$(ls -t /tmp/production_monitoring_*.json 2>/dev/null | head -1)")) as f:
        data = json.load(f)
except:
    print("⏳ Waiting for monitoring data...")
    sys.exit(0)

checks = data.get("checks", [])
issues = data.get("issues_summary", [])

print(f"📊 Progress: {len(checks)}/15 checks completed")
print(f"⚠️  Issues detected: {len(issues)}")
print("")

if checks:
    last = checks[-1]
    print(f"Last check at: {last['timestamp']}")
    print(f"  • Workflows: {last.get('workflows', {}).get('running', 0)} running")
    print(f"  • Processor pods: {last.get('pods', {}).get('processor_count', 0)}")
    print(f"  • API pods: {last.get('pods', {}).get('api_count', 0)}")

    if last.get('errors'):
        print(f"  • Errors: {len(last['errors'])}")

print("")

if issues:
    from collections import defaultdict
    by_type = defaultdict(int)
    for issue in issues:
        by_type[issue['type']] += 1

    print("Issue breakdown:")
    for issue_type, count in sorted(by_type.items()):
        print(f"  • {issue_type}: {count}")
else:
    print("✅ No issues detected!")

PYEOF

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "To view full log: cat $LOG_FILE | jq '.'"
