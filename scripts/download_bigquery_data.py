import os
from google.cloud import bigquery
import csv

# Configuration
PROJECT_ID = "mizzou-news-crawler"
DATASET_ID = "mizzou_analytics"
EXPORT_DIR = "data/bq_export"

def export_all_tables():
    # Ensure export directory exists
    os.makedirs(EXPORT_DIR, exist_ok=True)
    
    # Initialize client
    client = bigquery.Client(project=PROJECT_ID)
    
    # Get dataset content
    dataset_ref = client.dataset(DATASET_ID)
    tables = list(client.list_tables(dataset_ref))
    
    print(f"Found {len(tables)} tables in {DATASET_ID}. Starting export...")
    
    for table in tables:
        table_id = table.table_id
        print(f"Downloading {table_id}...", end=" ", flush=True)
        
        # Query full table
        query = f"SELECT * FROM `{PROJECT_ID}.{DATASET_ID}.{table_id}`"
        query_job = client.query(query)
        rows = query_job.result()
        
        # Define output file
        file_path = os.path.join(EXPORT_DIR, f"{table_id}.csv")
        
        # Write to CSV
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            
            # Write headers
            # Note: headers are available from schema
            # We get one row or use schema to get headers
            schema = rows.schema
            headers = [field.name for field in schema]
            writer.writerow(headers)
            
            count = 0
            for row in rows:
                writer.writerow(row.values())
                count += 1
                
        print(f"Done. ({count} rows saved to {file_path})")

if __name__ == "__main__":
    export_all_tables()
