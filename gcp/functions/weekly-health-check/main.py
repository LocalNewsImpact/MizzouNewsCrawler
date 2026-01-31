"""Cloud Function to send weekly source health check report via email using BigQuery"""
import os
import base64
import json
import io
from datetime import datetime
from google.cloud import bigquery
from googleapiclient.discovery import build
from google.oauth2 import service_account
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders


def send_weekly_health_check(request):
    """
    Cloud Function to send weekly source health check with diagnostic metrics.
    Identifies problematic sources based on discovery, extraction, and filter rates.
    
    Environment variables required:
    - GMAIL_CREDENTIALS_JSON: Service account JSON (base64 encoded)
    - GMAIL_DELEGATED_USER: Email to send from
    - REPORT_TO_EMAIL: Recipient email address
    - BQ_PROJECT_ID: GCP project ID
    """

    # Get configuration from environment
    credentials_json_b64 = os.environ.get('GMAIL_CREDENTIALS_JSON')
    delegated_user = os.environ.get('GMAIL_DELEGATED_USER')
    to_emails = os.environ.get('REPORT_TO_EMAIL', '').split(',')
    to_emails = [e.strip() for e in to_emails if e.strip()]
    project_id = os.environ.get('BQ_PROJECT_ID')

    # Validate configuration
    if not credentials_json_b64:
        print("ERROR: GMAIL_CREDENTIALS_JSON not configured")
        return {'error': 'GMAIL_CREDENTIALS_JSON not configured'}, 500
    if not delegated_user:
        print("ERROR: GMAIL_DELEGATED_USER not configured")
        return {'error': 'GMAIL_DELEGATED_USER not configured'}, 500
    if not to_emails:
        print("ERROR: REPORT_TO_EMAIL not configured")
        return {'error': 'REPORT_TO_EMAIL not configured'}, 500
    if not project_id:
        print("ERROR: BQ_PROJECT_ID not configured")
        return {'error': 'BQ_PROJECT_ID not configured'}, 500

    try:
        # Decode credentials
        print("Decoding Gmail credentials...")
        credentials_json = base64.b64decode(credentials_json_b64).decode('utf-8')
        credentials_dict = json.loads(credentials_json)
        
        # Query BigQuery for source health diagnostics
        print("Querying BigQuery for source health metrics...")
        bq_client = bigquery.Client(project=project_id)
        
        # Get actual pipeline health data
        query = f"""
        WITH discovery_metrics AS (
            SELECT
                REGEXP_REPLACE(REGEXP_EXTRACT(url, r'https?://([^/]+)'), r'^www\\.', '') as hostname,
                COUNT(*) as total_discovered_14d,
                SUM(CASE WHEN CAST(discovered_at AS TIMESTAMP) >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY) THEN 1 ELSE 0 END) as discovered_7d,
                MAX(discovered_at) as last_discovery
            FROM `{project_id}.mizzou_analytics.candidate_links`
            WHERE CAST(discovered_at AS TIMESTAMP) >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
            GROUP BY hostname
        ),
        extraction_metrics AS (
            SELECT
                REGEXP_REPLACE(REGEXP_EXTRACT(url, r'https?://([^/]+)'), r'^www\\.', '') as hostname,
                COUNT(*) as total_extracted_14d,
                SUM(CASE WHEN CAST(extracted_at AS TIMESTAMP) >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY) THEN 1 ELSE 0 END) as extracted_7d,
                MAX(extracted_at) as last_extraction
            FROM `{project_id}.mizzou_analytics.articles`
            WHERE CAST(extracted_at AS TIMESTAMP) >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
            GROUP BY hostname
        ),
        article_status_check AS (
            SELECT
                REGEXP_REPLACE(REGEXP_EXTRACT(url, r'https?://([^/]+)'), r'^www\\.', '') as hostname,
                SUM(CASE WHEN status = 'extracted' THEN 1 ELSE 0 END) as articles_at_extracted,
                SUM(CASE WHEN status = 'cleaned' THEN 1 ELSE 0 END) as articles_at_cleaned,
                SUM(CASE WHEN status = 'labeled' THEN 1 ELSE 0 END) as articles_at_labeled
            FROM `{project_id}.mizzou_analytics.articles`
            WHERE CAST(extracted_at AS TIMESTAMP) >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
            GROUP BY hostname
        )
        SELECT
            COALESCE(d.hostname, e.hostname) as hostname,
            'active' as source_status,
            COALESCE(d.discovered_7d, 0) as discovered_7d,
            COALESCE(d.total_discovered_14d, 0) as total_discovered_14d,
            COALESCE(e.extracted_7d, 0) as extracted_7d,
            COALESCE(e.total_extracted_14d, 0) as total_extracted_14d,
            CASE 
                WHEN COALESCE(e.total_extracted_14d, 0) = 0 AND COALESCE(d.total_discovered_14d, 0) = 0 THEN 'No Activity'
                WHEN COALESCE(e.extracted_7d, 0) = 0 AND COALESCE(d.total_discovered_14d, 0) > 0 THEN 'Extraction Issue'
                WHEN COALESCE(d.discovered_7d, 0) = 0 THEN 'Discovery Issue'
                ELSE 'Healthy'
            END as health_status,
            CASE
                WHEN COALESCE(e.total_extracted_14d, 0) = 0 AND COALESCE(d.total_discovered_14d, 0) = 0 THEN 'No discoveries or extractions in 14 days'
                WHEN COALESCE(e.extracted_7d, 0) = 0 AND COALESCE(d.total_discovered_14d, 0) > 0 THEN 'No extractions in past 7 days (may indicate scraping failure)'
                WHEN COALESCE(d.discovered_7d, 0) = 0 THEN 'Discovery pipeline not finding URLs (may be paused)'
                ELSE NULL
            END as issue_details,
            CASE 
                WHEN COALESCE(d.total_discovered_14d, 0) > 0 THEN ROUND(100.0 * COALESCE(e.total_extracted_14d, 0) / COALESCE(d.total_discovered_14d, 0), 1)
                ELSE 0
            END as extraction_success_rate,
            d.last_discovery,
            e.last_extraction,
            COALESCE(a.articles_at_extracted, 0) as articles_at_extracted,
            COALESCE(a.articles_at_cleaned, 0) as articles_at_cleaned,
            COALESCE(a.articles_at_labeled, 0) as articles_at_labeled
        FROM discovery_metrics d
        FULL OUTER JOIN extraction_metrics e USING (hostname)
        LEFT JOIN article_status_check a USING (hostname)
        ORDER BY
            CASE 
                WHEN COALESCE(e.extracted_7d, 0) = 0 AND COALESCE(d.total_discovered_14d, 0) > 0 THEN 1
                WHEN COALESCE(d.discovered_7d, 0) = 0 THEN 2
                WHEN COALESCE(e.total_extracted_14d, 0) = 0 AND COALESCE(d.total_discovered_14d, 0) = 0 THEN 3
                ELSE 4
            END,
            COALESCE(d.total_discovered_14d, 0) DESC
        """
        
        print(f"Running BigQuery health check query...")
        query_job = bq_client.query(query)
        all_results = list(query_job.result())
        
        if not all_results:
            print("WARNING: No source data in BigQuery")
            return {'error': 'No source data in BigQuery'}, 500
        
        # Filter to problematic sources only
        problematic = [r for r in all_results if r.health_status != 'Healthy']
        extraction_issues = [r for r in problematic if r.health_status == 'Extraction Issue']
        discovery_issues = [r for r in problematic if r.health_status == 'Discovery Issue']
        no_activity = [r for r in problematic if r.health_status == 'No Activity']
        
        print(f"Found {len(all_results)} total sources: {len(extraction_issues)} extraction issues, {len(discovery_issues)} discovery issues, {len(no_activity)} inactive")
        
        # Generate HTML report
        print("Generating HTML report...")
        html_body = generate_html_report(problematic, extraction_issues, discovery_issues, no_activity)
        
        # Generate CSV
        print("Generating CSV attachment...")
        csv_content = generate_csv(all_results)
        
        # Create service account credentials
        print("Creating Gmail credentials...")
        credentials = service_account.Credentials.from_service_account_info(
            credentials_dict,
            scopes=['https://www.googleapis.com/auth/gmail.send']
        )
        
        # Create delegated credentials
        delegated_credentials = credentials.with_subject(delegated_user)
        
        # Build email message
        print("Building email message...")
        message = MIMEMultipart('mixed')
        message['Subject'] = f"Weekly Source Health Report - {datetime.utcnow().strftime('%Y-%m-%d')}"
        message['From'] = delegated_user
        message['To'] = ', '.join(to_emails)
        
        # Attach HTML body
        msg_alternative = MIMEMultipart('alternative')
        message.attach(msg_alternative)
        msg_alternative.attach(MIMEText(html_body, 'html'))
        
        # Attach CSV
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(csv_content.encode('utf-8'))
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment; filename="source_health_report.csv"')
        message.attach(part)
        
        # Send via Gmail API
        print(f"Sending email to {', '.join(to_emails)}...")
        service = build('gmail', 'v1', credentials=delegated_credentials)
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        
        send_message = {'raw': raw_message}
        result = service.users().messages().send(userId='me', body=send_message).execute()
        
        print(f"✓ Email sent successfully: {result['id']}")
        
        return {
            'status': 'success',
            'message': 'Weekly source health report sent',
            'timestamp': datetime.utcnow().isoformat(),
            'total_sources': len(all_results),
            'extraction_issues': len(extraction_issues),
            'discovery_issues': len(discovery_issues),
            'no_activity': len(no_activity),
            'problematic_sources': len(problematic),
            'recipients': to_emails,
            'message_id': result['id']
        }, 200
        
    except Exception as e:
        print(f"✗ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }, 500


def generate_html_report(problematic, extraction_issues, discovery_issues, no_activity):
    """Generate HTML email from actual pipeline diagnostics"""
    
    html = f"""<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; color: #333; }}
        h1 {{ color: #1a73e8; border-bottom: 3px solid #1a73e8; padding-bottom: 10px; }}
        h2 {{ color: #555; margin-top: 30px; font-size: 16px; }}
        .summary {{ margin: 20px 0; padding: 15px; background-color: #f8f9fa; border-radius: 5px; }}
        .metric {{ display: inline-block; margin-right: 40px; padding: 10px; }}
        .metric-value {{ font-size: 28px; font-weight: bold; }}
        .extraction-issue {{ color: #d32f2f; }}
        .discovery-issue {{ color: #f57c00; }}
        .no-activity {{ color: #666; }}
        .metric-label {{ font-size: 11px; color: #666; text-transform: uppercase; margin-top: 5px; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 15px; }}
        th, td {{ border: 1px solid #ddd; padding: 11px; text-align: left; font-size: 13px; }}
        th {{ background-color: #1a73e8; color: white; font-weight: bold; }}
        tr:nth-child(even) {{ background-color: #f8f9fa; }}
        tr:hover {{ background-color: #e8f0fe; }}
        .issue-extraction {{ background-color: #ffebee; }}
        .issue-discovery {{ background-color: #fff3e0; }}
        .issue-inactive {{ background-color: #f5f5f5; }}
        .status-badge {{ display: inline-block; padding: 3px 8px; border-radius: 3px; font-weight: bold; font-size: 12px; }}
        .status-extraction-issue {{ background-color: #ffcdd2; color: #c62828; }}
        .status-discovery-issue {{ background-color: #ffe0b2; color: #e65100; }}
        .status-no-activity {{ background-color: #e0e0e0; color: #424242; }}
        .section-header {{ margin-top: 25px; margin-bottom: 10px; }}
        .issue-description {{ color: #666; font-size: 12px; margin: 10px 0; font-style: italic; }}
        .pipeline-row {{ margin: 15px 0; padding: 10px; background-color: #f9f9f9; border-left: 4px solid #1a73e8; }}
        .rate-good {{ color: #388e3c; font-weight: bold; }}
        .rate-bad {{ color: #d32f2f; font-weight: bold; }}
    </style>
</head>
<body>
    <h1>🔍 Weekly Pipeline Health Report</h1>
    <p>Report Period: Last 14 Days | Generated: {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
    
    <div class="summary">
        <h2 style="margin-top: 0;">Issues Found</h2>
        <div class="metric">
            <div class="metric-value extraction-issue">{len(extraction_issues)}</div>
            <div class="metric-label">🔴 Extraction Issues<br>(URLs found, but can't scrape)</div>
        </div>
        <div class="metric">
            <div class="metric-value discovery-issue">{len(discovery_issues)}</div>
            <div class="metric-label">🟠 Discovery Issues<br>(Not finding URLs)</div>
        </div>
        <div class="metric">
            <div class="metric-value no-activity">{len(no_activity)}</div>
            <div class="metric-label">⚪ No Activity<br>(14+ days inactive)</div>
        </div>
    </div>
    
    <div class="pipeline-row">
        <strong>Pipeline Status:</strong> Sources with HIGH successful extraction = Working Correctly | Sources with LOW discovery OR HIGH extraction failure = Investigate
    </div>
"""
    
    if extraction_issues:
        html += f"""    <div class="section-header">
        <h2>🔴 Extraction Issues ({len(extraction_issues)} sources)</h2>
        <p class="issue-description">These sources have discovered URLs but are failing to extract articles. May indicate scraping/parsing problems or site changes.</p>
    </div>
    <table>
        <tr>
            <th>Rank</th>
            <th>Source</th>
            <th>Discovered (14d)</th>
            <th>Discovered (7d)</th>
            <th>Extraction Success Rate</th>
            <th>Last Discovery</th>
            <th>Pipeline Status</th>
        </tr>
"""
        for i, row in enumerate(extraction_issues[:10], 1):
            rate = f'{row.extraction_success_rate}%' if row.extraction_success_rate > 0 else '0%'
            rate_class = 'rate-good' if row.extraction_success_rate >= 50 else 'rate-bad'
            last_disc = row.last_discovery.strftime("%m-%d %H:%M") if row.last_discovery else "N/A"
            
            html += f"""        <tr class="issue-extraction">
            <td><strong>{i}</strong></td>
            <td>{row.hostname}</td>
            <td>{row.total_discovered_14d}</td>
            <td>{row.discovered_7d}</td>
            <td><span class="{rate_class}">{rate}</span></td>
            <td>{last_disc}</td>
            <td>Extracted: {row.total_extracted_14d} / Stuck at extraction: {row.articles_at_extracted}</td>
        </tr>
"""
        html += "    </table>\n"
    
    if discovery_issues:
        html += f"""    <div class="section-header">
        <h2>🟠 Discovery Issues ({len(discovery_issues)} sources)</h2>
        <p class="issue-description">These sources have NO recent discoveries (last 7 days). Site may be paused, feeds broken, or discovery configuration changed.</p>
    </div>
    <table>
        <tr>
            <th>Rank</th>
            <th>Source</th>
            <th>Discovered (14d)</th>
            <th>Last Discovery</th>
            <th>Total Extracted (14d)</th>
            <th>Action</th>
        </tr>
"""
        for i, row in enumerate(discovery_issues[:10], 1):
            last_disc = row.last_discovery.strftime("%m-%d %H:%M") if row.last_discovery else "Never"
            action = "Check if paused" if row.source_status == "paused" else "Investigate discovery pipeline"
            
            html += f"""        <tr class="issue-discovery">
            <td><strong>{i}</strong></td>
            <td>{row.hostname}</td>
            <td>{row.total_discovered_14d}</td>
            <td>{last_disc}</td>
            <td>{row.total_extracted_14d}</td>
            <td>{action}</td>
        </tr>
"""
        html += "    </table>\n"
    
    if no_activity:
        html += f"""    <div class="section-header">
        <h2>⚪ No Activity ({len(no_activity)} sources)</h2>
        <p class="issue-description">No discoveries or extractions in 14 days. Likely paused or permanently disabled.</p>
    </div>
    <table>
        <tr>
            <th>Source</th>
            <th>Status</th>
            <th>Last Discovery</th>
            <th>Last Extraction</th>
        </tr>
"""
        for row in no_activity[:10]:
            last_disc = row.last_discovery.strftime("%m-%d") if row.last_discovery else "Never"
            last_ext = row.last_extraction.strftime("%m-%d") if row.last_extraction else "Never"
            
            html += f"""        <tr class="issue-inactive">
            <td>{row.hostname}</td>
            <td>{row.source_status}</td>
            <td>{last_disc}</td>
            <td>{last_ext}</td>
        </tr>
"""
        html += "    </table>\n"
    
    html += """    <div style="margin-top: 30px; padding: 15px; background-color: #f0f4ff; border-left: 4px solid #1a73e8;">
        <strong>Key Metrics Explained:</strong>
        <ul>
            <li><strong>Extraction Success Rate:</strong> (Extracted / Discovered) × 100. HIGH = System working well. LOW = Scraping/parsing problems.</li>
            <li><strong>Extraction Issues:</strong> URLs found but extraction failing. Check: Is site blocking? Did HTML structure change?</li>
            <li><strong>Discovery Issues:</strong> No recent URLs found. Check: Is site paused? Feed broken? Site structure changed?</li>
            <li><strong>No Activity:</strong> Nothing for 14+ days. Likely paused or deprecated source.</li>
        </ul>
    </div>
    
    <div style="margin-top: 20px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 12px;">
        <p><small>Full diagnostic dataset in CSV attachment for detailed analysis and tracking.</small></p>
    </div>
</body>
</html>
"""
    return html


def generate_csv(all_results):
    """Generate CSV for spreadsheet analysis with all diagnostic fields"""
    output = io.StringIO()
    
    # Write header
    output.write(','.join([
        'Rank', 'Hostname', 'Health Status', 'Issue Details', 'Source Status',
        'Discovered (14d)', 'Discovered (7d)', 'Extracted (14d)', 'Extracted (7d)',
        'Extraction Success Rate (%)', 'Last Discovery', 'Last Extraction',
        'Articles at Extracted', 'Articles at Cleaned', 'Articles at Labeled'
    ]) + '\n')
    
    # Sort all results by health status (extraction issues first, then discovery, then no activity, then healthy)
    health_order = {'Extraction Issue': 0, 'Discovery Issue': 1, 'No Activity': 2, 'Healthy': 3}
    sorted_results = sorted(all_results, key=lambda x: health_order.get(x.health_status, 4))
    
    for rank, row in enumerate(sorted_results, 1):
        last_disc = row.last_discovery.strftime("%Y-%m-%d %H:%M:%S") if row.last_discovery else ""
        last_ext = row.last_extraction.strftime("%Y-%m-%d %H:%M:%S") if row.last_extraction else ""
        
        rate = f'{row.extraction_success_rate:.1f}' if row.extraction_success_rate else '0'
        
        issue_details = row.issue_details if hasattr(row, 'issue_details') and row.issue_details else ""
        
        csv_row = [
            str(rank),
            row.hostname,
            row.health_status,
            issue_details,
            row.source_status or "active",
            str(row.total_discovered_14d or 0),
            str(row.discovered_7d or 0),
            str(row.total_extracted_14d or 0),
            str(row.extracted_7d or 0),
            rate,
            last_disc,
            last_ext,
            str(row.articles_at_extracted or 0),
            str(row.articles_at_cleaned or 0),
            str(row.articles_at_labeled or 0)
        ]
        
        # Escape CSV fields with quotes if they contain commas or newlines
        escaped_row = [f'"{field.replace(chr(34), chr(34) + chr(34))}"' if ',' in field or '\n' in field or '"' in field else field for field in csv_row]
        output.write(','.join(escaped_row) + '\n')
    
    return output.getvalue()
