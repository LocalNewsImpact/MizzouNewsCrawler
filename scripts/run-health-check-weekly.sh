#!/bin/bash
# Run weekly health check from production pod and email results

set -e

NAMESPACE="production"
DEPLOYMENT="mizzou-processor"
RECIPIENT_EMAIL="chair@localnewsimpact.org"

echo "Starting weekly health check from production pod..."
echo "Namespace: $NAMESPACE"
echo "Deployment: $DEPLOYMENT"
echo "Recipient: $RECIPIENT_EMAIL"
echo ""

# Get pod name
POD=$(kubectl get pods -n $NAMESPACE -l app=$DEPLOYMENT -o jsonpath='{.items[0].metadata.name}')

if [ -z "$POD" ]; then
    echo "Error: No pod found for deployment $DEPLOYMENT"
    exit 1
fi

echo "Using pod: $POD"
echo ""

# Create temporary Python script to run health check and send email
SCRIPT=$(cat <<'PYTHON_EOF'
import sys
import os
sys.path.insert(0, '/app/scripts')
sys.path.insert(0, '/app')

from datetime import datetime
from scripts.source_health_check import diagnose_source_health, get_all_sources, export_report_csv, export_report_json
from src.models.database import DatabaseManager
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import tempfile

# Get database session
db = DatabaseManager()
session = db.get_session()

# Run health checks
print("Running health diagnostics for all sources...", file=sys.stderr)
sources = get_all_sources(session)
source_list = list(sources)

diagnostics = []
for source_id, source_name, canonical_name in source_list:
    try:
        diag = diagnose_source_health(session, source_id, canonical_name)
        diag['source_name'] = source_name or canonical_name
        diag['source_id'] = source_id
        diagnostics.append(diag)
    except Exception as e:
        print(f"Warning: Error diagnosing {source_name}: {e}", file=sys.stderr)
        diagnostics.append({
            'source_id': source_id,
            'source_name': source_name or canonical_name,
            'status': 'error',
            'issues': [f'Diagnosis failed: {str(e)[:50]}'],
            'metrics': {}
        })

# Generate summary
summary = {
    'healthy': len([d for d in diagnostics if d['status'] == 'healthy']),
    'warning': len([d for d in diagnostics if d['status'] == 'warning']),
    'critical': len([d for d in diagnostics if d['status'] == 'critical']),
    'error': len([d for d in diagnostics if d['status'] == 'error']),
    'total': len(diagnostics)
}

print(f"Health check complete. Summary: {summary}", file=sys.stderr)

# Generate HTML report
critical_issues = [s for s in diagnostics if s['status'] == 'critical']
warning_issues = [s for s in diagnostics if s['status'] == 'warning']
problem_sources = [s for s in diagnostics if s['issues']][:20]

html_parts = [
    f"""<html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            h1 {{ color: #333; }}
            .metric {{ display: inline-block; margin-right: 30px; }}
            .critical {{ color: #d32f2f; font-weight: bold; }}
            .warning {{ color: #f57c00; font-weight: bold; }}
            .healthy {{ color: #388e3c; }}
            table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
            th {{ background-color: #f5f5f5; }}
            tr:nth-child(even) {{ background-color: #fafafa; }}
        </style>
    </head>
    <body>
        <h1>Weekly Source Health Report</h1>
        <p>Generated: {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
        
        <div class="summary">
            <h2>Summary</h2>
            <div class="metric"><span class="healthy">✓ Healthy: {summary['healthy']}</span></div>
            <div class="metric"><span class="warning">⚠ Warnings: {summary['warning']}</span></div>
            <div class="metric"><span class="critical">✗ Critical: {summary['critical']}</span></div>
        </div>
    """
]

if critical_issues:
    html_parts.append(f"""
        <div>
            <h2 style="color: #d32f2f;">Critical Issues ({len(critical_issues)} sources)</h2>
            <ul>
    """)
    for s in critical_issues:
        html_parts.append(f"<li><strong>{s['source_name']}</strong>: {', '.join(s['issues'])}</li>")
    html_parts.append("</ul></div>")

if warning_issues:
    html_parts.append(f"""
        <div>
            <h2 style="color: #f57c00;">Warnings ({len(warning_issues)} sources)</h2>
            <ul>
    """)
    for s in warning_issues:
        html_parts.append(f"<li><strong>{s['source_name']}</strong>: {', '.join(s['issues'])}</li>")
    html_parts.append("</ul></div>")

html_parts.append("""
        <h2>Top Issues Detail</h2>
        <table>
            <tr>
                <th>Source</th>
                <th>Status</th>
                <th>Issues</th>
                <th>Recent Discoveries</th>
                <th>Extraction Rate</th>
                <th>Filter Rate</th>
            </tr>
""")

for source in problem_sources:
    recent_disc = source['metrics'].get('recent_discoveries', 0)
    ext_rate = source['metrics'].get('extraction_rate', 'N/A')
    filter_rate = source['metrics'].get('filter_rate', 'N/A')
    html_parts.append(f"""
            <tr>
                <td>{source['source_name']}</td>
                <td style="color: {'#d32f2f' if source['status'] == 'critical' else '#f57c00' if source['status'] == 'warning' else '#388e3c'}">{source['status'].upper()}</td>
                <td>{'; '.join(source['issues'])}</td>
                <td>{recent_disc}</td>
                <td>{ext_rate}%</td>
                <td>{filter_rate}%</td>
            </tr>
    """)

html_parts.append("""
        </table>
    </body>
</html>
""")

html_body = ''.join(html_parts)

# Generate CSV
csv_lines = ["source_id,source_name,status,issues,discovery_rate,extraction_rate,filter_rate,recent_discoveries"]
for d in diagnostics:
    issues = ';'.join(d['issues']) if d['issues'] else ''
    csv_lines.append(f"{d['source_id']},{d['source_name']},{d['status']},{issues},{d['metrics'].get('discovery_rate', '')},{d['metrics'].get('extraction_rate', '')},{d['metrics'].get('filter_rate', '')},{d['metrics'].get('recent_discoveries', '')}")
csv_content = '\n'.join(csv_lines)

print("Preparing email payload (Gmail API)", file=sys.stderr)

# Compose message and write to EML (for optional manual inspection) – sending handled in Cloud Function
recipient_email = os.environ.get('REPORT_TO_EMAIL', '$RECIPIENT_EMAIL')
msg = MIMEMultipart('mixed')
msg['Subject'] = f"Weekly Source Health Report - {datetime.utcnow().strftime('%Y-%m-%d')}"
msg['From'] = os.environ.get('GMAIL_DELEGATED_USER', 'reports@localnewsimpact.org')
msg['To'] = recipient_email
msg.attach(MIMEText(html_body, 'html'))

csv_part = MIMEBase('application', 'octet-stream')
csv_part.set_payload(csv_content.encode())
encoders.encode_base64(csv_part)
csv_part.add_header('Content-Disposition', f'attachment; filename=source_health_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv')
msg.attach(csv_part)

with open('/tmp/health_report.eml', 'w') as f:
    f.write(msg.as_string())

print("EML generated for inspection. Gmail API send occurs in function runtime.", file=sys.stderr)
print(json.dumps({'status': 'success', 'summary': summary}))

session.close()
PYTHON_EOF
)

# Run in pod
echo "Script content created, executing in pod..."
kubectl exec -n $NAMESPACE $POD -- python -c "$SCRIPT" 2>&1

echo ""
echo "Health check complete!"
