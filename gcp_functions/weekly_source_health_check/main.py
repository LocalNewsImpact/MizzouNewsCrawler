import functions_framework
from google.cloud import storage
from datetime import datetime
import json
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import base64
from google.oauth2 import service_account
from googleapiclient.discovery import build
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine.url import make_url
from google.cloud.sql.connector import Connector
import tempfile


def generate_html_report(report):
    summary = report["summary"]
    critical = [s for s in report["sources"] if s["status"] == "critical"]
    warning = [s for s in report["sources"] if s["status"] == "warning"]
    html = "<html><head><style>body{font-family:Arial;margin:20px}.critical{color:#d32f2f;font-weight:bold}.warning{color:#f57c00;font-weight:bold}.healthy{color:#388e3c}</style></head><body>"
    html += "<h1>Weekly Source Health Report</h1>"
    html += "<p>Generated: " + datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC") + "</p>"
    html += "<h2>Summary</h2><p>Healthy: " + str(summary["healthy"]) + " | Warnings: " + str(summary["warning"]) + " | Critical: " + str(summary["critical"]) + "</p>"
    if critical:
        html += "<h2>Critical (" + str(len(critical)) + ")</h2><ul>"
        for s in critical:
            html += "<li><b>" + s["source_name"] + "</b>: " + ", ".join(s["issues"]) + "</li>"
        html += "</ul>"
    if warning:
        html += "<h2>Warnings (" + str(len(warning)) + ")</h2><ul>"
        for s in warning:
            html += "<li><b>" + s["source_name"] + "</b>: " + ", ".join(s["issues"]) + "</li>"
        html += "</ul>"
    html += "</body></html>"
    return html


def send_email_report(email_to, report, csv_path, json_path):
    delegated_user = os.environ.get("GMAIL_DELEGATED_USER")
    credentials_json_b64 = os.environ.get("GMAIL_CREDENTIALS_JSON")
    if not delegated_user or not credentials_json_b64:
        raise ValueError("GMAIL_DELEGATED_USER or GMAIL_CREDENTIALS_JSON not set")
    sa_info = json.loads(base64.b64decode(credentials_json_b64).decode("utf-8"))
    credentials = service_account.Credentials.from_service_account_info(sa_info, scopes=["https://www.googleapis.com/auth/gmail.send"])
    delegated_credentials = credentials.with_subject(delegated_user)
    msg = MIMEMultipart("mixed")
    msg["Subject"] = "Weekly Source Health Report - " + datetime.utcnow().strftime("%Y-%m-%d")
    msg["From"] = delegated_user
    msg["To"] = email_to
    msg.attach(MIMEText(generate_html_report(report), "html"))
    for path, fname in [(csv_path, "source_health_report.csv"), (json_path, "source_health_report.json")]:
        if os.path.exists(path):
            with open(path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", "attachment; filename=" + fname)
                msg.attach(part)
    service = build("gmail", "v1", credentials=delegated_credentials)
    result = service.users().messages().send(userId="me", body={"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}).execute()
    print("Gmail API send succeeded, message id: " + str(result.get("id")))


@functions_framework.http
def weekly_source_health_check(request):
    try:
        print("Starting weekly source health check...")
        recipient_email = os.getenv("REPORT_TO_EMAIL") or os.getenv("HEALTH_CHECK_EMAIL")
        if not recipient_email:
            raise ValueError("No recipient email configured")
        print("Will send to: " + recipient_email)
        from source_health_check import diagnose_source_health, get_all_sources, export_diagnostics_csv
        print("Connecting to Cloud SQL...")
        # Prefer explicit env vars, fall back to DATABASE_URL parsing, finally default DB name
        database_url = os.getenv("DATABASE_URL", "")
        db_user = os.getenv("DB_USER", "mizzou_user")
        db_pass = os.getenv("DB_PASSWORD")
        db_name = os.getenv("DB_NAME")
        instance = os.getenv("CLOUDSQL_INSTANCE", "mizzou-news-crawler:us-central1:mizzou-db-prod")
        if database_url:
            try:
                url = make_url(database_url)
                db_user = url.username or db_user
                # url.password may be None if not present or contains special chars without proper encoding
                if url.password:
                    db_pass = url.password
                if url.database:
                    db_name = db_name or url.database
            except Exception as e:
                print("WARNING: Failed to parse DATABASE_URL:", str(e))
        if not db_name:
            raise ValueError("DB_NAME not set and could not parse from DATABASE_URL")
        if not db_pass:
            raise ValueError("DB_PASSWORD not set and could not parse from DATABASE_URL")
        # Log resolved connection (without password)
        try:
            print("Cloud SQL instance:", instance)
            print("Database:", db_name)
            print("User:", db_user)
        except Exception:
            pass

        connector = Connector()

        def getconn():
            return connector.connect(instance, "pg8000", user=db_user, password=db_pass, db=db_name)
        engine = create_engine("postgresql+pg8000://", creator=getconn)
        Session = sessionmaker(bind=engine)
        print("Running health diagnostics...")
        all_diagnostics = []
        # Optional query params to narrow scope for manual runs
        limit = None
        host_filter = None
        lookback_days = 30
        include_samples = True
        try:
            if request:
                host_filter = request.args.get("host")
                lim = request.args.get("limit")
                if lim:
                    try:
                        limit = int(lim)
                    except Exception:
                        pass
                # Optional lookback days
                days_arg = request.args.get("days") or request.args.get("lookback")
                if days_arg:
                    try:
                        lookback_days = int(days_arg)
                    except Exception:
                        pass
                # Optional include_samples toggle (default: False when limit provided)
                inc_arg = request.args.get("include_samples")
                if inc_arg is not None:
                    include_samples = str(inc_arg).lower() in {"1", "true", "yes"}
                # JSON body support
                payload = request.get_json(silent=True)
                if payload and "limit" in payload and limit is None:
                    try:
                        limit = int(payload.get("limit"))
                    except Exception:
                        pass
                if payload and "host" in payload and not host_filter:
                    host_filter = str(payload.get("host") or "").strip() or None
                if payload and "days" in payload:
                    try:
                        lookback_days = int(payload.get("days"))
                    except Exception:
                        pass
                if payload and "include_samples" in payload:
                    include_samples = bool(payload.get("include_samples"))
        except Exception:
            pass
        # Default: if limiting scope, skip sample URL query for speed unless explicitly enabled
        if limit and include_samples is True:
            include_samples = False

        with Session() as session:
            sources = get_all_sources(session, limit=limit, host_prefix=host_filter)
            for source_id, host, canonical_name in sources:
                try:
                    diag = diagnose_source_health(
                        session,
                        source_id,
                        canonical_name,
                        lookback_days=lookback_days,
                        host=host,
                        include_samples=include_samples,
                    )
                    diag["source_name"] = host or canonical_name
                    diag["source_id"] = source_id
                    all_diagnostics.append(diag)
                except Exception as e:
                    all_diagnostics.append({"source_id": source_id, "source_name": host or canonical_name, "status": "error", "issues": [str(e)[:50]], "metrics": {}})
        connector.close()
        summary = {"healthy": len([d for d in all_diagnostics if d["status"] == "healthy"]), "warning": len([d for d in all_diagnostics if d["status"] == "warning"]), "critical": len([d for d in all_diagnostics if d["status"] == "critical"]), "error": len([d for d in all_diagnostics if d["status"] == "error"]), "total": len(all_diagnostics)}
        report = {"timestamp": datetime.utcnow().isoformat(), "summary": summary, "sources": all_diagnostics}
        print("Health check complete. Summary: " + str(summary))
        csv_content = export_diagnostics_csv(all_diagnostics)
        json_content = json.dumps(report, indent=2)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            csv_path = f.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(json_content)
            json_path = f.name
        print("Sending email to " + recipient_email + "...")
        send_email_report(recipient_email, report, csv_path, json_path)
        print("Email sent!")
        os.unlink(csv_path)
        os.unlink(json_path)
        try:
            client = storage.Client()
            bucket = client.bucket("mizzou-news-crawler-reports")
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            bucket.blob("source_health_checks/" + ts + "/report.json").upload_from_string(json_content)
            bucket.blob("source_health_checks/" + ts + "/report.csv").upload_from_string(csv_content)
        except Exception as e:
            print("GCS backup failed: " + str(e))
        return {"status": "success", "recipient": recipient_email, "summary": summary}, 200
    except Exception as e:
        import traceback
        print("Error: " + str(e))
        traceback.print_exc()
        return {"status": "error", "error": str(e)}, 500
