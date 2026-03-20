# Provide a local shim for functions_framework to allow running as a CLI
try:
    import functions_framework
except Exception:
    class functions_framework:  # type: ignore
        @staticmethod
        def http(func):
            return func
import re
from urllib.parse import urlparse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import sys
from google.cloud import bigquery
import google.auth
from googleapiclient.discovery import build

# Configuration
PROJECT_ID = "mizzou-news-crawler"
SHEET_ID = "1_0T4QeDUCBOSU7qXOkszhYVf2_6XATub8DsXBaORgwI"  # Google Sheet ID
# Use quoted sheet name for spaces; the tab was renamed to 'Active Month'
SHEET_RANGE = "'Active Month'!A1"  # Target sheet/tab and starting cell

@functions_framework.http
def export_daily_analytics(request):
    """
    Cloud Function to query BigQuery for daily analytics data and append it to a Google Sheet.

    Query parameters (optional):
    - date: YYYY-MM-DD (single day)
    - start_date: YYYY-MM-DD (inclusive range start)
    - end_date: YYYY-MM-DD (inclusive range end)
    - limit: integer row limit per day (default 500)
    - dry_run: 'true' to run queries without writing to Sheets
    """
    try:
        # 1. Setup Clients
        credentials, project = google.auth.default(
            scopes=['https://www.googleapis.com/auth/spreadsheets', 
                    'https://www.googleapis.com/auth/bigquery']
        )
        bq_client = bigquery.Client(credentials=credentials, project=PROJECT_ID)
        sheets_service = build('sheets', 'v4', credentials=credentials)
        # 2. Parse query parameters
        args = request.args or {}
        json_data = None
        try:
            json_data = request.get_json(silent=True) or {}
        except Exception:
            json_data = {}

        def _get_arg(name, default=None):
            return (args.get(name) or json_data.get(name) or default)

        def _parse_date(val):
            return datetime.strptime(val, "%Y-%m-%d").date()

        def _parse_bool(val):
            if val is None:
                return False
            return str(val).lower() in ("1", "true", "t", "yes", "y")

        def _parse_int(val, default):
            try:
                return int(val)
            except Exception:
                return default

        # Daily export limit: no cap, export all eligible articles
        # If no limit specified, export all (use 10000 as practical max)
        limit = _parse_int(_get_arg('limit'), 10000)
        dry_run = _parse_bool(_get_arg('dry_run', False))

        date_param = _get_arg('date')
        start_date_param = _get_arg('start_date')
        end_date_param = _get_arg('end_date')

        # Build list of dates to process
        dates_to_run = []
        try:
            if date_param:
                dates_to_run = [_parse_date(date_param)]
            elif start_date_param and end_date_param:
                start_d = _parse_date(start_date_param)
                end_d = _parse_date(end_date_param)
                if start_d > end_d:
                    raise ValueError("start_date must be <= end_date")
                span = (end_d - start_d).days + 1
                dates_to_run = [start_d + timedelta(days=i) for i in range(span)]
            else:
                # Compute "yesterday" in Central Time (America/Chicago)
                ct = ZoneInfo("America/Chicago")
                yesterday_ct = (datetime.now(ct) - timedelta(days=1)).date()
                dates_to_run = [yesterday_ct]
        except Exception as de:
            return {"status": "error", "error": f"Invalid date parameter(s): {de}"}, 400

        print(f"Executing export for {len(dates_to_run)} day(s): {[d.isoformat() for d in dates_to_run]} (limit={limit}, dry_run={dry_run})")

        # Helper: resolve target sheet title without quotes
        target_sheet = SHEET_RANGE.split('!')[0] if '!' in SHEET_RANGE else "Active Month"
        if target_sheet.startswith("'") and target_sheet.endswith("'"):
            target_sheet = target_sheet[1:-1]

        total_rows = 0
        append_summaries = []

        for target_day in dates_to_run:
            # 3. Define per-day query
            # Note: extracted_at is stored as DATETIME in UTC. Cast to TIMESTAMP then convert to CT for date filtering.
            query = f"""
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
                WHERE DATE(TIMESTAMP(extracted_at), "America/Chicago") = DATE('{target_day.isoformat()}')
                  AND status NOT IN ('wire', 'obituary', 'opinion')
                ORDER BY extracted_at DESC
                LIMIT {limit}
            """

            print(f"Executing BigQuery export job for {target_day.isoformat()}...")
            query_job = bq_client.query(query)
            rows = list(query_job.result())
            print(f"[{target_day.isoformat()}] Found {len(rows)} rows to export.")

            if not rows:
                append_summaries.append({"date": target_day.isoformat(), "rows": 0, "status": "no-data"})
                continue

            if dry_run:
                total_rows += len(rows)
                append_summaries.append({"date": target_day.isoformat(), "rows": len(rows), "status": "dry-run"})
                continue

            # 4. Format Data for Sheets
            # Determine next serial ID by getting actual row count from sheet metadata
            # CRITICAL: Use metadata, not values().get(), to avoid filter/sort issues
            next_id = 1
            try:
                # Get sheet metadata to find actual grid dimensions (ignores filters)
                sheet_metadata = sheets_service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
                for sheet in sheet_metadata.get('sheets', []):
                    sheet_title_meta = sheet['properties']['title']
                    if sheet_title_meta == target_sheet:
                        grid_properties = sheet['properties'].get('gridProperties', {})
                        actual_row_count = grid_properties.get('rowCount', 0)
                        # Next ID should be at least the row count (accounts for header + data)
                        next_id = max(1, actual_row_count)
                        print(f"Using actual row count from metadata: {actual_row_count} (ignoring any active filters)")
                        break
            except Exception as e:
                print(f"Warning: Could not determine next ID from sheet metadata: {e}")
                next_id = 1

            # Convert Row objects to list of lists
            values = []
            for i, row in enumerate(rows, next_id):
                # Extract host from URL
                try:
                    host = urlparse(row.url).netloc
                    if host.startswith('www.'):
                        host = host[4:]
                except Exception:
                    host = ""

                values.append([
                    i,          # Col 1: Serialized ID
                    host,       # Col 2: Host Name
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

            # 5. Append to Sheets
            body = {'values': values}
            result = sheets_service.spreadsheets().values().append(
                spreadsheetId=SHEET_ID,
                range=SHEET_RANGE,
                valueInputOption="USER_ENTERED",
                body=body
            ).execute()

            updated_cells = result.get('updates', {}).get('updatedCells')
            updated_range = result.get('updates', {}).get('updatedRange')

            # 6. Apply Formatting (Copy from Row 2) — best-effort
            if updated_range:
                try:
                    sheet_title = updated_range.split('!')[0]
                    if "'" in sheet_title:
                        sheet_title = sheet_title.replace("'", "")

                    sheet_metadata = sheets_service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
                    sheet_id = 0
                    for sheet in sheet_metadata.get('sheets', []):
                        if sheet['properties']['title'] == sheet_title:
                            sheet_id = sheet['properties']['sheetId']
                            break

                    match = re.search(r'[A-Z]+(\d+):', updated_range)
                    if match:
                        start_row = int(match.group(1)) - 1
                        end_row = start_row + len(rows)

                        requests = [
                            {
                                "copyPaste": {
                                    "source": {
                                        "sheetId": sheet_id,
                                        "startRowIndex": 1,
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
                                    "properties": {"pixelSize": 30},
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

            total_rows += len(rows)
            append_summaries.append({
                "date": target_day.isoformat(),
                "rows": len(rows),
                "updatedCells": updated_cells,
                "updatedRange": updated_range,
                "status": "ok"
            })

        return {
            "status": "success",
            "total_days": len(dates_to_run),
            "total_rows": total_rows,
            "summaries": append_summaries
        }, 200

    except Exception as e:
        print(f"Error executing export: {e}")
        return {"status": "error", "error": str(e)}, 500


# Local CLI runner for testing without Cloud Functions
if __name__ == "__main__":
    # Very small CLI harness to support local runs
    # Usage examples:
    #   python gcp_functions/daily_sheet_export/main.py --date 2026-02-05
    #   python gcp_functions/daily_sheet_export/main.py --start_date 2026-02-01 --end_date 2026-02-05 --limit 200
    #   python gcp_functions/daily_sheet_export/main.py --dry_run true

    # Parse simple args
    argv = sys.argv[1:]
    arg_map = {}
    k = None
    for token in argv:
        if token.startswith("--"):
            k = token[2:]
            arg_map[k] = "true"  # default truthy for flags
        else:
            if k is not None:
                arg_map[k] = token
                k = None

    class _LocalRequest:
        def __init__(self, args):
            self.args = args
        def get_json(self, silent=False):
            return {}

    resp, code = export_daily_analytics(_LocalRequest(arg_map))
    print({"status_code": code, "response": resp})
