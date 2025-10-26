import os
import csv
import json
from datetime import datetime
os.environ['DATABASE_ENGINE'] = 'postgresql+psycopg2'
from src.models.database import DatabaseManager
from sqlalchemy import text, inspect
from src.pipeline.text_cleaning import decode_rot47_segments

db = DatabaseManager()
session = db.session

result = session.execute(text("SELECT id FROM datasets WHERE slug = 'Penn-State-Lehigh'"))
dataset = result.fetchone()
dataset_id = dataset.id

# Get schema
inspector = inspect(db.engine)
columns = inspector.get_columns('articles')
print('=== Articles Table Schema ===')
for col in columns:
    print(f"{col['name']:<25} {str(col['type']):<30} {'NULL' if col['nullable'] else 'NOT NULL'}")

# Query all articles for the dataset
result = session.execute(text('''
    SELECT a.*, cl.source_name, cl.source_city, cl.source_county
    FROM articles a
    JOIN candidate_links cl ON a.candidate_link_id = cl.id
    WHERE cl.dataset_id = :did
    ORDER BY a.created_at DESC
'''), {'did': dataset_id})
rows = result.fetchall()

print(f"\nExporting {len(rows)} articles...")

# Query all entities for these articles
print("Querying entities...")
result = session.execute(text('''
    SELECT ae.article_id, 
           ae.entity_text, 
           ae.entity_norm, 
           ae.entity_label,
           ae.osm_category,
           ae.osm_subcategory,
           ae.confidence,
           ae.match_name,
           ae.match_score
    FROM article_entities ae
    JOIN articles a ON ae.article_id = a.id
    JOIN candidate_links cl ON a.candidate_link_id = cl.id
    WHERE cl.dataset_id = :did
    ORDER BY ae.article_id, ae.entity_text
'''), {'did': dataset_id})
entity_rows = result.fetchall()

# Group entities by article_id
entities_by_article = {}
for entity in entity_rows:
    article_id = entity.article_id
    if article_id not in entities_by_article:
        entities_by_article[article_id] = []
    entities_by_article[article_id].append({
        'text': entity.entity_text,
        'norm': entity.entity_norm,
        'label': entity.entity_label,
        'osm_category': entity.osm_category,
        'osm_subcategory': entity.osm_subcategory,
        'confidence': entity.confidence,
        'match_name': entity.match_name,
        'match_score': entity.match_score,
    })

print(f"Found {len(entity_rows)} entities for {len(entities_by_article)} articles")

with open('/tmp/lehigh_all_articles.csv', 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.writer(f)
    # Write header with entity columns
    if rows:
        base_columns = list(rows[0]._mapping.keys())
        entity_columns = [
            'entity_count',
            # NER label-based columns
            'entities_person',  # PERSON - People/names
            'entities_org',  # ORG - Organizations
            'entities_gpe',  # GPE - Geopolitical Entities
            'entities_loc',  # LOC - Locations
            'entities_fac',  # FAC - Facilities
            'entities_norp',  # NORP - Nationalities/Religious/Political
            'entities_event',  # EVENT - Named events
            # OSM category-based columns
            'osm_institutions',  # institution
            'osm_places',  # place
            'osm_landmarks',  # landmark
            'osm_businesses',  # business
            'osm_schools',  # school
            'osm_events',  # event
            'all_entities_json'  # Full entity data as JSON
        ]
        writer.writerow(base_columns + entity_columns)
        
        # Write data rows
        for article in rows:
            row = []
            for col in base_columns:
                val = getattr(article, col, '')
                if isinstance(val, datetime):
                    val = val.isoformat()
                # Clean ROT47 encoding from text fields
                if col in ('content', 'text') and val:
                    val = decode_rot47_segments(val) or val
                row.append(val or '')
            
            # Add entity data
            article_id = article.id
            entities = entities_by_article.get(article_id, [])
            
            # Count entities
            row.append(len(entities))
            
            # Group by NER entity label
            person_ents = [e['text'] for e in entities if e['label'] == 'PERSON']
            org_ents = [e['text'] for e in entities if e['label'] == 'ORG']
            gpe_ents = [e['text'] for e in entities if e['label'] == 'GPE']
            loc_ents = [e['text'] for e in entities if e['label'] == 'LOC']
            fac_ents = [e['text'] for e in entities if e['label'] == 'FAC']
            norp_ents = [e['text'] for e in entities if e['label'] == 'NORP']
            event_ents = [e['text'] for e in entities if e['label'] == 'EVENT']
            
            row.append('|'.join(person_ents))
            row.append('|'.join(org_ents))
            row.append('|'.join(gpe_ents))
            row.append('|'.join(loc_ents))
            row.append('|'.join(fac_ents))
            row.append('|'.join(norp_ents))
            row.append('|'.join(event_ents))
            
            # Group by OSM category
            osm_inst = [e['text'] for e in entities if e['osm_category'] == 'institution']
            osm_place = [e['text'] for e in entities if e['osm_category'] == 'place']
            osm_landmark = [e['text'] for e in entities if e['osm_category'] == 'landmark']
            osm_biz = [e['text'] for e in entities if e['osm_category'] == 'business']
            osm_school = [e['text'] for e in entities if e['osm_category'] == 'school']
            osm_event = [e['text'] for e in entities if e['osm_category'] == 'event']
            
            row.append('|'.join(osm_inst))
            row.append('|'.join(osm_place))
            row.append('|'.join(osm_landmark))
            row.append('|'.join(osm_biz))
            row.append('|'.join(osm_school))
            row.append('|'.join(osm_event))
            
            # Add full entity data as JSON
            row.append(json.dumps(entities) if entities else '')
            
            writer.writerow(row)

print('Exported to /tmp/lehigh_all_articles.csv')
session.close()
