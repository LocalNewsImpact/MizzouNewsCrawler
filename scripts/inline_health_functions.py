from pathlib import Path

MAIN = Path("/Users/kiesowd/VSCode/NewsCrawler/MizzouNewsCrawler/gcp_functions/weekly_source_health_check/main.py")
text = MAIN.read_text()

# Ensure timedelta import
text = text.replace("from datetime import datetime\n", "from datetime import datetime, timedelta\n")

insert_anchor = "return \"\".join(html_parts)\n\n"

functions_block = 