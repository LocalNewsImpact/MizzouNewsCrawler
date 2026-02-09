from src.models.database import DatabaseManager
from sqlalchemy import text
db = DatabaseManager()
sess = db.get_session().__enter__()
print("Updating bot protection type for KY3...")
sess.execute(text("UPDATE sources SET bot_protection_type = 'cloudflare' WHERE canonical_name LIKE '%KY3%' OR canonical_name LIKE '%KSPR%'"))
sess.commit()
r = sess.execute(text("SELECT canonical_name, extraction_method, bot_protection_type FROM sources WHERE canonical_name LIKE '%KY3%' LIMIT 2")).fetchall()
print("\nKY3 CloudScraper Configuration in Production:")
for row in r:
    print(f"  {row[0]}: extraction_method={row[1]}, bot_protection={row[2]}")
