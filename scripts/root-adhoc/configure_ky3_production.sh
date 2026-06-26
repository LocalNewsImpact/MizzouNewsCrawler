#!/bin/bash
"""Configure ky3.com to use CloudScraper in production Cloud SQL."""

set -e

NAMESPACE="production"
DEPLOYMENT="mizzou-api"

echo "🚀 Configuring KY3 extraction method in production..."
echo "   Namespace: $NAMESPACE"
echo "   Deployment: $DEPLOYMENT"
echo ""

# Execute Python script in the production API pod
kubectl exec -n "$NAMESPACE" deployment/"$DEPLOYMENT" -- python -c "
from src.models.database import DatabaseManager
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db = DatabaseManager()

print('🔍 Finding KY3 sources in production...')
with db.get_session() as session:
    # Find ky3 sources
    query = text('''
        SELECT id, host, canonical_name, extraction_method, bot_protection_type
        FROM sources
        WHERE host LIKE '%ky3.com%'
           OR canonical_name LIKE '%KY3%'
           OR canonical_name LIKE '%KSPR%'
    ''')
    
    results = session.execute(query).fetchall()
    
    if not results:
        print('⚠️  No KY3 sources found')
        exit(1)
    
    print(f'✓ Found {len(results)} KY3 source(s):')
    for row in results:
        print(f'  ID: {row[0]}')
        print(f'    Host: {row[1]}')
        print(f'    Name: {row[2]}')
        print(f'    Current extraction_method: {row[3]}')
        print(f'    Current bot_protection_type: {row[4]}')
    
    # Update to use HTTP method (CloudScraper will handle it automatically)
    print()
    print('📝 Updating extraction configuration...')
    update_query = text('''
        UPDATE sources
        SET extraction_method = 'http',
            bot_protection_type = NULL,
            discovery_proxy = NULL
        WHERE host LIKE '%ky3.com%'
           OR canonical_name LIKE '%KY3%'
           OR canonical_name LIKE '%KSPR%'
    ''')
    
    session.execute(update_query)
    session.commit()
    
    print('✅ Updated sources to use CloudScraper:')
    print('   extraction_method: http')
    print('   bot_protection_type: NULL')
    print('   discovery_proxy: NULL')
    
    # Verify the update
    verify_query = text('''
        SELECT id, host, canonical_name, extraction_method, bot_protection_type
        FROM sources
        WHERE host LIKE '%ky3.com%'
           OR canonical_name LIKE '%KY3%'
           OR canonical_name LIKE '%KSPR%'
    ''')
    
    updated = session.execute(verify_query).fetchall()
    print()
    print('✓ Verification - Updated sources:')
    for row in updated:
        print(f'  {row[2]} ({row[1]})')
        print(f'    extraction_method: {row[3]}')
        print(f'    bot_protection_type: {row[4]}')
    
print()
print('✨ Configuration complete!')
print()
print('ℹ️  Next steps:')
print('   1. CloudScraper will now handle all ky3.com requests')
print('   2. Test extraction with: python -m src.cli extract --source \"KSPR/KY3\" --limit 5')
print('   3. Monitor extraction logs: kubectl logs -f -n production deployment/mizzou-processor')
"
