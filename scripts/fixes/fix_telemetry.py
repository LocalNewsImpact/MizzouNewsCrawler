#!/usr/bin/env python3

# Fix telemetry.py to update discovery_attempted field in sources table


# Read the file
with open("src/utils/telemetry.py") as f:
    content = f.read()

# Find the specific pattern and replace it
old_pattern = """            with self.db_engine.connect() as conn:
                conn.execute(text(insert_sql), outcome_data)
                conn.commit()
                
                # Update discovery_attempted timestamp in sources table
                # This ensures sources are marked as attempted even if they failed
                sources_update_sql = \"\"\"
                UPDATE sources 
                SET discovery_attempted = CURRENT_TIMESTAMP 
                WHERE id = :source_id
                \"\"\"
                conn.execute(text(sources_update_sql), {"source_id": source_id})"""

new_pattern = """            with self.db_engine.connect() as conn:
                conn.execute(text(insert_sql), outcome_data)
                
                # Update discovery_attempted timestamp in sources table
                # This ensures sources are marked as attempted even if they failed
                sources_update_sql = \"\"\"
                UPDATE sources 
                SET discovery_attempted = CURRENT_TIMESTAMP 
                WHERE id = :source_id
                \"\"\"
                conn.execute(text(sources_update_sql), {"source_id": source_id})
                
                conn.commit()"""

# Replace the pattern
content = content.replace(old_pattern, new_pattern)

# Write back to file
with open("src/utils/telemetry.py", "w") as f:
    f.write(content)

print("Fixed telemetry.py - moved commit after sources update")
