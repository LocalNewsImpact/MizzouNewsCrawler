from pathlib import Path

p = Path('/Users/kiesowd/VSCode/NewsCrawler/MizzouNewsCrawler/gcp_functions/weekly_source_health_check/main.py')
s = p.read_text()
start_marker = "\n        # Run health checks for all sources\n        print(\"Running health diagnostics for all sources...\")\n"
end_marker = "\n        # Generate summary\n"
start_idx = s.find(start_marker)
end_idx = s.find(end_marker, start_idx)
assert start_idx != -1 and end_idx != -1, 'Markers not found'
new_block = (
    "\n        # Run health checks for all sources using a session\n"
    "        print(\"Running health diagnostics for all sources...\")\n"
    "        all_diagnostics = []\n"
    "        with Session() as session:\n"
    "            sources = get_all_sources(session)\n"
    "            for source_id, host, canonical_name in sources:\n"
    "                try:\n"
    "                    diag = diagnose_source_health(session, source_id, canonical_name)\n"
    "                    diag['source_name'] = host or canonical_name\n"
    "                    diag['source_id'] = source_id\n"
    "                    all_diagnostics.append(diag)\n"
    "                except Exception as diag_error:\n"
    "                    print(f\"Warning: Error diagnosing {canonical_name}: {diag_error}\")\n"
    "                    all_diagnostics.append({\n"
    "                        'source_id': source_id,\n"
    "                        'source_name': host or canonical_name,\n"
    "                        'status': 'error',\n"
    "                        'issues': [f'Diagnosis failed: {str(diag_error)[:50]}'],\n"
    "                        'metrics': {}\n"
    "                    })\n"
)
s = s[:start_idx] + start_marker + new_block + s[end_idx:]
p.write_text(s)
print('Replaced health diagnostics loop in', p)
