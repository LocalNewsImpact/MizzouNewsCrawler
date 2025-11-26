#!/bin/bash
# Create GitHub Issue from Production Monitoring Data
# Run this after monitoring completes (30 minutes)

set -e

echo "🔍 Looking for monitoring log file..."

LOG_FILE=$(ls -t /tmp/production_monitoring_*.json 2>/dev/null | head -1)

if [ -z "$LOG_FILE" ] || [ ! -f "$LOG_FILE" ]; then
    echo "❌ Error: No monitoring log file found"
    echo "   Expected: /tmp/production_monitoring_*.json"
    exit 1
fi

echo "📝 Found log file: $LOG_FILE"
echo ""

# Generate issue content
ISSUE_DATA=$(python3 << 'PYEOF'
import json
import sys
from datetime import datetime
from collections import defaultdict

LOG_FILE = sys.argv[1]

try:
    with open(LOG_FILE, 'r') as f:
        data = json.load(f)
except Exception as e:
    print(f"Error reading log file: {e}", file=sys.stderr)
    sys.exit(1)

checks = data.get("checks", [])
issues = data.get("issues_summary", [])

# Categorize issues
issue_types = defaultdict(list)
for issue in issues:
    issue_types[issue["type"]].append(issue)

# Generate title
title = f"Production Monitoring Report - {datetime.now().strftime('%Y-%m-%d')}"

# Generate body
body = f"""## Production Monitoring Report

**Duration:** 30 minutes  
**Start Time:** {data.get('start_time', 'N/A')}  
**Total Checks:** {len(checks)}  
**Issues Detected:** {len(issues)}

### Executive Summary

"""

if len(issues) == 0:
    body += "✅ **No issues detected during monitoring period**\n\n"
    body += "All systems operating normally:\n"
    body += "- Argo workflows running without failures\n"
    body += "- All pods in Running state\n"
    body += "- Resource usage within normal limits\n"
    body += "- No database connection issues\n"
else:
    # Summarize by type
    body += "| Issue Type | Count |\n"
    body += "|------------|-------|\n"
    for issue_type, type_issues in sorted(issue_types.items()):
        body += f"| {issue_type.title()} | {len(type_issues)} |\n"
    body += "\n"
    
    # Detail each issue type
    for issue_type, type_issues in sorted(issue_types.items()):
        body += f"### {issue_type.title()} Issues\n\n"
        
        # Group identical issues
        grouped = defaultdict(list)
        for issue in type_issues:
            grouped[issue['message']].append(issue['time'])
        
        for message, times in grouped.items():
            body += f"- **{message}**\n"
            body += f"  - Occurrences: {len(times)}\n"
            if len(times) <= 3:
                for t in times:
                    body += f"  - {t}\n"
            else:
                body += f"  - First: {times[0]}\n"
                body += f"  - Last: {times[-1]}\n"
            body += "\n"

# Add system state info
if checks:
    last_check = checks[-1]
    body += "### Final System State\n\n"
    
    workflows = last_check.get("workflows", {})
    pods = last_check.get("pods", {})
    
    body += f"**Workflows:**\n"
    body += f"- Running: {workflows.get('running', 'N/A')}\n\n"
    
    body += f"**Pods:**\n"
    body += f"- Processor: {pods.get('processor_count', 'N/A')}\n"
    body += f"- API: {pods.get('api_count', 'N/A')}\n\n"

# Recommendations
body += "### Recommendations\n\n"

if len(issues) == 0:
    body += "- ✅ Continue standard monitoring\n"
    body += "- ✅ No immediate action required\n"
    body += "- 📊 System performance is healthy\n"
else:
    # Analyze patterns
    workflow_issues = len([i for i in issues if i['type'] == 'workflow'])
    pod_issues = len([i for i in issues if i['type'] == 'pod'])
    resource_issues = len([i for i in issues if i['type'] == 'resource'])
    
    if workflow_issues > 0:
        body += f"- 🔴 **Workflow Issues ({workflow_issues}):**\n"
        body += "  - Investigate Argo workflow failures\n"
        body += "  - Check workflow logs: `argo logs -n production <workflow-name>`\n"
        body += "  - Review workflow definition for potential issues\n\n"
    
    if pod_issues > 0:
        body += f"- 🟡 **Pod Issues ({pod_issues}):**\n"
        body += "  - Check pod logs: `kubectl logs -n production <pod-name>`\n"
        body += "  - Review restart policies and resource limits\n"
        body += "  - Consider pod anti-affinity rules if restarts are frequent\n\n"
    
    if resource_issues > 0:
        body += f"- 🟠 **Resource Issues ({resource_issues}):**\n"
        body += "  - Review resource requests and limits\n"
        body += "  - Consider horizontal pod autoscaling\n"
        body += "  - Monitor for memory leaks or CPU spikes\n\n"

body += "\n"
body += "### Monitoring Details\n\n"
body += f"- **Log file:** `{LOG_FILE}`\n"
body += f"- **Monitoring script:** Automated 30-minute observation\n"
body += f"- **Check interval:** 2 minutes (15 total checks)\n"
body += f"- **Monitoring areas:** Argo workflows, pods, resources, work queue, database\n"

# Output JSON for gh CLI
import json
output = {
    "title": title,
    "body": body,
    "labels": ["monitoring", "production", "automated"]
}

# Add severity label
if len(issues) == 0:
    output["labels"].append("status:healthy")
elif len(issues) < 5:
    output["labels"].append("severity:low")
elif len(issues) < 15:
    output["labels"].append("severity:medium")
else:
    output["labels"].append("severity:high")

print(json.dumps(output))

PYEOF
)

if [ $? -ne 0 ]; then
    echo "❌ Failed to generate issue content"
    exit 1
fi

# Parse the output
TITLE=$(echo "$ISSUE_DATA" | jq -r '.title')
BODY=$(echo "$ISSUE_DATA" | jq -r '.body')
LABELS=$(echo "$ISSUE_DATA" | jq -r '.labels | join(",")')

echo "📋 Issue Preview:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Title: $TITLE"
echo "Labels: $LABELS"
echo ""
echo "Body (first 500 chars):"
echo "$BODY" | head -c 500
echo "..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

read -p "Create GitHub issue? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🚀 Creating GitHub issue..."
    
    gh issue create \
        --title "$TITLE" \
        --body "$BODY" \
        --label "$LABELS" \
        --repo LocalNewsImpact/MizzouNewsCrawler
    
    if [ $? -eq 0 ]; then
        echo "✅ GitHub issue created successfully!"
    else
        echo "❌ Failed to create issue"
        echo ""
        echo "You can create it manually with:"
        echo "gh issue create --title \"$TITLE\" --body-file <(echo \"$BODY\") --label \"$LABELS\""
    fi
else
    echo "ℹ️  Issue not created"
    echo ""
    echo "To create it later, run this script again"
fi
