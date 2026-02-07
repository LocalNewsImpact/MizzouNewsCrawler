from pathlib import Path

p = Path('/Users/kiesowd/VSCode/NewsCrawler/MizzouNewsCrawler/gcp_functions/weekly_source_health_check/main.py')
s = p.read_text()
old = (
    "\n        # Get configuration from environment or Secret Manager\n"
    "        try:\n"
    "            recipient_email = get_secret(\"health-check-recipient-email\")\n"
    "            print(f\"Using recipient email from Secret Manager: {recipient_email}\")\n"
    "        except Exception as sm_error:\n"
    "            print(f\"Warning: Could not get recipient from Secret Manager ({sm_error}). Using environment variable.\")\n"
    "            recipient_email = os.getenv(\"HEALTH_CHECK_EMAIL\")\n"
    "            if not recipient_email:\n"
    "                raise ValueError(\"No recipient email configured. Set HEALTH_CHECK_EMAIL env var or create health-check-recipient-email secret.\")\n"
)
new = (
    "\n        # Resolve recipient email with precedence: REPORT_TO_EMAIL -> Secret -> HEALTH_CHECK_EMAIL\n"
    "        recipient_email = os.getenv(\"REPORT_TO_EMAIL\")\n"
    "        if recipient_email:\n"
    "            print(f\"Using recipient email from REPORT_TO_EMAIL: {recipient_email}\")\n"
    "        else:\n"
    "            try:\n"
    "                recipient_email = get_secret(\"health-check-recipient-email\")\n"
    "                print(f\"Using recipient email from Secret Manager: {recipient_email}\")\n"
    "            except Exception as sm_error:\n"
    "                print(f\"Warning: Could not get recipient from Secret Manager ({sm_error}). Falling back to HEALTH_CHECK_EMAIL.\")\n"
    "                recipient_email = os.getenv(\"HEALTH_CHECK_EMAIL\")\n"
    "                if not recipient_email:\n"
    "                    raise ValueError(\"No recipient email configured. Set REPORT_TO_EMAIL or HEALTH_CHECK_EMAIL env var, or create health-check-recipient-email secret.\")\n"
)
if old in s:
    s = s.replace(old, new)
p.write_text(s)
print('Updated recipient precedence in', p)
