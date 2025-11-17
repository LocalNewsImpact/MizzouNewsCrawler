"""Cloud Function to send daily BigQuery report via email"""
import os
import base64
import json
from datetime import datetime, timedelta
from google.cloud import bigquery
from googleapiclient.discovery import build
from google.oauth2 import service_account
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def send_daily_report(request):
    """
    Cloud Function triggered by Cloud Scheduler to send daily article statistics.
    Uses Gmail API (free) instead of SendGrid.
    
    Environment variables required:
    - GMAIL_CREDENTIALS_JSON: Service account JSON (base64 encoded)
    - GMAIL_DELEGATED_USER: Email to send from
    - REPORT_TO_EMAIL: Recipient email address (comma-separated)
    - BQ_PROJECT_ID: BigQuery project ID
    """
    
    # Get configuration from environment
    credentials_json = os.environ.get('GMAIL_CREDENTIALS_JSON')
    delegated_user = os.environ.get('GMAIL_DELEGATED_USER')
    to_emails = os.environ.get('REPORT_TO_EMAIL', '').split(',')
    project_id = os.environ.get('BQ_PROJECT_ID')
    
    if not credentials_json:
        return {'error': 'GMAIL_CREDENTIALS_JSON not configured'}, 500
    if not delegated_user:
        return {'error': 'GMAIL_DELEGATED_USER not configured'}, 500
    if not to_emails or not to_emails[0]:
        return {'error': 'REPORT_TO_EMAIL not configured'}, 500
    
    # Initialize BigQuery client
    client = bigquery.Client(project=project_id)
    
    # Daily BigQuery sync check - last 60 days of extractions
    query_daily_import = f"""
        SELECT 
            DATE(extracted_at) as extraction_date,
            COUNT(*) as article_count,
            COUNT(DISTINCT candidate_link_id) as unique_links,
            MIN(extracted_at) as earliest_extraction,
            MAX(extracted_at) as latest_extraction
        FROM `{project_id}.mizzou_analytics.articles`
        WHERE extracted_at IS NOT NULL
        GROUP BY extraction_date
        ORDER BY extraction_date DESC
        LIMIT 60
    """
    
    try:
        # Execute query
        results = list(client.query(query_daily_import).result())
        
        if not results:
            return {'error': 'No data returned from query'}, 500
        
        # Get today's date for report title
        today = datetime.utcnow().strftime('%Y-%m-%d')
        
        # Calculate summary stats
        total_articles = sum(row.article_count for row in results)
        last_7_days = [
            r for r in results
            if r.extraction_date >= (
                datetime.utcnow() - timedelta(days=7)
            ).date()
        ]
        last_7_articles = sum(row.article_count for row in last_7_days)
        
        # Build HTML email
        html = f"""
        <html>
        <head>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    margin: 20px;
                }}
                h2 {{
                    color: #333;
                }}
                table {{
                    border-collapse: collapse;
                    width: 100%;
                    margin: 20px 0;
                }}
                th {{
                    background-color: #f2f2f2;
                    padding: 10px;
                    text-align: left;
                    border: 1px solid #ddd;
                }}
                td {{
                    padding: 8px;
                    border: 1px solid #ddd;
                }}
                tr:nth-child(even) {{
                    background-color: #f9f9f9;
                }}
                .summary {{
                    background-color: #e8f4f8;
                    padding: 15px;
                    border-radius: 5px;
                    margin: 20px 0;
                }}
                .summary-stat {{
                    display: inline-block;
                    margin: 0 20px;
                }}
                .recent {{
                    background-color: #fff3cd;
                }}
            </style>
        </head>
        <body>
            <h1>Daily BigQuery Import Check - {today}</h1>
            
            <div class="summary">
                <h3>Summary</h3>
                <span class="summary-stat">
                    <strong>Total Articles (60 days):</strong>
                    {total_articles:,}
                </span>
                <span class="summary-stat">
                    <strong>Last 7 Days:</strong>
                    {last_7_articles:,}
                </span>
                <span class="summary-stat">
                    <strong>Days with Data:</strong>
                    {len(results)}
                </span>
            </div>
            
            <h2>Articles by Extraction Date (Last 60 Days)</h2>
            <table>
                <tr>
                    <th>Extraction Date</th>
                    <th>Article Count</th>
                    <th>Unique Links</th>
                    <th>Earliest</th>
                    <th>Latest</th>
                </tr>
        """
        
        for i, row in enumerate(results):
            row_class = ' class="recent"' if i < 7 else ''
            earliest = row.earliest_extraction.strftime('%Y-%m-%d %H:%M')
            latest = row.latest_extraction.strftime('%Y-%m-%d %H:%M')
            html += f"""
                <tr{row_class}>
                    <td>{row.extraction_date}</td>
                    <td>{row.article_count:,}</td>
                    <td>{row.unique_links:,}</td>
                    <td>{earliest}</td>
                    <td>{latest}</td>
                </tr>
            """
        
        html += f"""
            </table>
            
            <p style="color: #666; font-size: 12px; margin-top: 40px;">
                Generated at {
                    datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                } UTC
            </p>
        </body>
        </html>
        """
        
        # Send email via Gmail API
        # Decode service account credentials
        creds_dict = json.loads(
            base64.b64decode(credentials_json).decode('utf-8')
        )
        
        # Create credentials with delegated user
        credentials = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=['https://www.googleapis.com/auth/gmail.send']
        )
        delegated_credentials = credentials.with_subject(delegated_user)
        
        # Build Gmail service
        service = build('gmail', 'v1', credentials=delegated_credentials)
        
        # Create email message
        message = MIMEMultipart('alternative')
        message['Subject'] = f'Daily BigQuery Import Check - {today}'
        message['From'] = delegated_user
        message['To'] = ', '.join([email.strip() for email in to_emails])
        
        # Attach HTML content
        html_part = MIMEText(html, 'html')
        message.attach(html_part)
        
        # Send via Gmail API
        raw_message = base64.urlsafe_b64encode(
            message.as_bytes()
        ).decode('utf-8')
        send_message = {'raw': raw_message}
        
        service.users().messages().send(
            userId='me',
            body=send_message
        ).execute()
        
        return {
            'status': 'success',
            'date': today,
            'total_articles_60days': total_articles,
            'articles_last_7_days': last_7_articles,
            'days_with_data': len(results),
            'email_sent_to': to_emails
        }, 200
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return {'error': str(e)}, 500
