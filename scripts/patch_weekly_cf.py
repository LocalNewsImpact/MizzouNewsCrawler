import sys
from pathlib import Path

p = Path("/Users/kiesowd/VSCode/NewsCrawler/MizzouNewsCrawler/gcp_functions/weekly_source_health_check/main.py")
text = p.read_text()
# Fix invalid subject line f-string
text = text.replace(
    "msg[\"Subject\"] = f\"Weekly Source Health Report - {datetime.utcnow().strftime(%Y-%m-%d)}\"",
    "msg[\"Subject\"] = \"Weekly Source Health Report - \" + datetime.utcnow().strftime(\"%Y-%m-%d\")",
)
# Fix Gmail API result id logging
text = text.replace("result.get(id)", "result.get('id')")
# Add repo root to sys.path for src and scripts imports if missing
marker = "Add repo root (two levels up from this file)"
if marker not in text:
    insert_after = "sys.path.insert(0, '/app')\n"
    addition = (
        "try:\n"
        "    # Add repo root (two levels up from this file) to sys.path for src/ and scripts/\n"
        "    import os as _os\n"
        "    _repo_root = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), '..', '..'))\n"
        "    if _repo_root not in sys.path:\n"
        "        sys.path.insert(0, _repo_root)\n"
        "except Exception:\n"
        "    pass\n"
    )
    text = text.replace(insert_after, insert_after + addition)

p.write_text(text)
print("Patched:", p)