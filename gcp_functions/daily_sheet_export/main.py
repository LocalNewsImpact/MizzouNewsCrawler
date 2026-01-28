import functions_framework
import re
from google.cloud import bigquery
import google.auth
from googleapiclient.discovery import build

# Configuration
PROJECT_ID = "mizzou-news-crawler"
SHEET_ID = "1_0T4QeDUCBOSU7qXOkszhYVf2_6XATub8DsXBaORgwI"  # Updated via Chat
SHEET_RANGE = "Sheet1!A1" # Target sheet name

@functions_framework.http
def export_daily_analytics(request):
    """
    Cloud Function to query BigQuery for daily analytics data
    and append it to a Google Sheet.
    """
    try:
        # 1. Setup Clients
        credentials, project = google.auth.default(
            scopes=['https://www.googleapis.com/auth/spreadsheets', 
                    'https://www.googleapis.com/auth/bigquery']
        )
        bq_client = bigquery.Client(credentials=credentials, project=PROJECT_ID)
        sheets_service = build('sheets', 'v4', credentials=credentials)

        # 2. Define Query
        # This matches the "Saved Query" in BigQuery for daily extraction
        query = """
            -- Local news articles from most recent extraction date
            -- Excludes wire, obituaries, and opinion pieces
            SELECT 
                IFNULL(title, '') as title,
                IFNULL(url, '') as url,
                IFNULL(author, '') as author,
                IFNULL(SUBSTR(text, 0, 50000), '') as text,
                FORMAT_DATETIME("%Y-%m-%d %H:%M:%S", publish_date) as publish_date,
                FORMAT_DATETIME("%Y-%m-%d %H:%M:%S", extracted_at) as extracted_at,
                IFNULL(status, '') as status,
                IFNULL(primary_label, '') as primary_label,
                IFNULL(alternate_label, '') as alternate_label
            FROM `mizzou-news-crawler.mizzou_analytics.articles`
            WHERE DATE(extracted_at) = CURRENT_DATE - INTERVAL 1 day
              AND status NOT IN ("wire", "obituary", "opinion")
            ORDER BY extracted_at DESC
            LIMIT 500
        """

        print("Executing BigQuery export job...")
        query_job = bq_client.query(query)
        rows = list(query_job.result())
        print(f"Found {len(rows)} rows to export.")

        if not rows:
            return "No records found for yesterday. Nothing appended."

        # 3. Format Data for Sheets
        # Convert Row objects to list of lists
        values = []
        for row in rows:
            values.append([
                row.title,
                row.url,
                row.author,
                row.text,
                row.publish_date,
                row.extracted_at,
                row.status,
                row.primary_label,
                row.alternate_label
            ])

        # 4. Append to Sheets
        body = {
            'values': values
        }
        
        result = sheets_service.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range=SHEET_RANGE,
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()

        updated_cells = result.get('updates', {}).get('updatedCells')
        updated_range = result.get('updates', {}).get('updatedRange')

        # 5. Apply Formatting (Copy from Row 2)
        if updated_range:
            try:
                # Resolve Sheet ID from the response range (e.g., 'Sheet1!A100:H105')
                sheet_title = updated_range.split('!')[0]
                if "'" in sheet_title:
                    sheet_title = sheet_title.replace("'", "")
                
                sheet_metadata = sheets_service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
                sheet_id = 0
                for sheet in sheet_metadata.get('sheets', []):
                    if sheet['properties']['title'] == sheet_title:
                        sheet_id = sheet['properties']['sheetId']
                        break
                
                # Parse start row from range
                # Example: Sheet1!A100:H105 -> We need 100
                match = re.search(r'[A-Z]+(\d+):', updated_range)
                if match:
                    start_row = int(match.group(1)) - 1 # Convert 1-based to 0-based index
                    end_row = start_row + len(rows)

                    # Copy formatting from Row 2 (Index 1) to new rows
                    requests = [
                        {
                            "copyPaste": {
                                "source": {
                                    "sheetId": sheet_id,
                                    "startRowIndex": 1, # Row 2 (Template)
                                    "endRowIndex": 2
                                },
                                "destination": {
                                    "sheetId": sheet_id,
                                    "startRowIndex": start_row,
                                    "endRowIndex": end_row
                                },
                                "pasteType": "PASTE_FORMAT"
                            }
                        },
                        {
                            "updateDimensionProperties": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "dimension": "ROWS",
                                    "startIndex": start_row,
                                    "endIndex": end_row
                                },
                                "properties": {
                                    "pixelSize": 30
                                },
                                "fields": "pixelSize"
                            }
                        }
                    ]

                    sheets_service.spreadsheets().batchUpdate(
                        spreadsheetId=SHEET_ID,
                        body={'requests': requests}
                    ).execute()
                    print(f"Applied formatting to rows {start_row+1}-{end_row}")

            except Exception as format_err:
                print(f"Formatting warning: {format_err}")

        return f"Success: Appended {updated_cells} cells ({len(rows)} rows) to Sheet."

    except Exception as e:
        print(f"Error executing export: {e}")
        return f"Error: {e}", 500
