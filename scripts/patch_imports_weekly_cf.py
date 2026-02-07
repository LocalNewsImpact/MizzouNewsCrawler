import re
from pathlib import Path

p = Path('/Users/kiesowd/VSCode/NewsCrawler/MizzouNewsCrawler/gcp_functions/weekly_source_health_check/main.py')
s = p.read_text()

# Replace import try-except block with direct local imports
s = re.sub(
    r"\n\s*# For Cloud Function execution[\s\S]*?from database import DatabaseManager\n",
    "\n        # Import local health helper functions packaged with the Cloud Function\n        from source_health_check import (\n            diagnose_source_health,\n            get_all_sources,\n            export_diagnostics_csv,\n        )\n\n",
    s,
    flags=re.MULTILINE,
)

# Replace DatabaseManager instantiation with SQLAlchemy session creation
s = s.replace(
    "\n        # Get database session\n        print(\"Connecting to database...\")\n        db = DatabaseManager()\n",
    "\n        # Create direct SQLAlchemy session from DATABASE_URL\n        print(\"Connecting to database...\")\n        database_url = os.getenv(\"DATABASE_URL\")\n        if not database_url:\n            raise ValueError(\"DATABASE_URL env var is not set\")\n        Engine = create_engine(database_url, connect_args={}, echo=False)\n        Session = sessionmaker(bind=Engine)\n",
)

# Replace sources fetching and loop to use Session
s = s.replace(
    "\n        # Run health checks for all sources\n        print(\"Running health diagnostics for all sources...\")\n        sources = get_all_sources(db.get_session())\n\n        all_diagnostics = []\n        for source_id, source_name, canonical_name in sources:\n            try:\n                diag = diagnose_source_health(db.get_session(), source_id, canonical_name)\n                diag['source_name'] = source_name or canonical_name\n                diag['source_id'] = source_id\n                all_diagnostics.append(diag)\n            except Exception as diag_error:\n                print(f\"Warning: Error diagnosing {source_name}: {diag_error}\")\n                # Still add to report with error status\n                all_diagnostics.append({\n                    'source_id': source_id,\n                    'source_name': source_name or canonical_name,\n                    'status': 'error',\n                    'issues': [f'Diagnosis failed: {str(diag_error)[:50]}'],\n                    'metrics': {}\n                })\n",
    "\n        # Run health checks for all sources\n        print(\"Running health diagnostics for all sources...\")\n        all_diagnostics = []\n        with Session() as session:\n            sources = get_all_sources(session)\n            for source_id, host, canonical_name in sources:\n                try:\n                    diag = diagnose_source_health(session, source_id, canonical_name)\n                    diag['source_name'] = host or canonical_name\n                    diag['source_id'] = source_id\n                    all_diagnostics.append(diag)\n                except Exception as diag_error:\n                    print(f\"Warning: Error diagnosing {canonical_name}: {diag_error}\")\n                    all_diagnostics.append({\n                        'source_id': source_id,\n                        'source_name': host or canonical_name,\n                        'status': 'error',\n                        'issues': [f'Diagnosis failed: {str(diag_error)[:50]}'],\n                        'metrics': {}\n                    })\n",
)

p.write_text(s)
print('Patched imports and session usage in', p)
