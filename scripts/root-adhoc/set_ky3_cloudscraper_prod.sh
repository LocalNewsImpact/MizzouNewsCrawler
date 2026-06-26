#!/bin/bash
# Configure ky3.com to use CloudScraper in production via kubectl exec

kubectl exec -n production deployment/mizzou-api -- python << 'EOF'
from src.models.database import DatabaseManager
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

logger.info('=' * 70)
logger.info('🚀 Configuring ky3.com CloudScraper Extraction in Production')
logger.info('=' * 70)

db = DatabaseManager()

with db.get_session() as session:
    # Find ky3 sources
    logger.info('\n🔍 Finding ky3.com sources...')
    query = text('''
        SELECT id, host, canonical_name, extraction_method, bot_protection_type
        FROM sources
        WHERE host LIKE '%ky3%'
           OR canonical_name LIKE '%KY3%'
           OR canonical_name LIKE '%KSPR%'
    ''')
    
    results = session.execute(query).fetchall()
    
    if not results:
        logger.warning('⚠️  No KY3 sources found in production database')
        exit(1)
    
    logger.info(f'\n✓ Found {len(results)} KY3 source(s):')
    for row in results:
        logger.info(f'  • {row[2]} ({row[1]})')
        logger.info(f'    extraction_method: {row[3]}')
        logger.info(f'    bot_protection_type: {row[4]}')
    
    # Update extraction method
    logger.info('\n📝 Updating extraction method...')
    update_query = text('''
        UPDATE sources
        SET extraction_method = 'http'
        WHERE host LIKE '%ky3%'
           OR canonical_name LIKE '%KY3%'
           OR canonical_name LIKE '%KSPR%'
    ''')
    
    session.execute(update_query)
    session.commit()
    logger.info('✅ Updated extraction_method to "http"')
    
    # Verify
    logger.info('\n✓ Verification - Current configuration:')
    verify_query = text('''
        SELECT id, host, canonical_name, extraction_method, bot_protection_type
        FROM sources
        WHERE host LIKE '%ky3%'
           OR canonical_name LIKE '%KY3%'
           OR canonical_name LIKE '%KSPR%'
    ''')
    
    updated = session.execute(verify_query).fetchall()
    for row in updated:
        logger.info(f'  • {row[2]}')
        logger.info(f'    extraction_method: {row[3]} ✓')
        logger.info(f'    bot_protection_type: {row[4]} (kept for escalation)')

logger.info('\n' + '=' * 70)
logger.info('🎯 Configuration Complete!')
logger.info('=' * 70)
logger.info('\nky3.com will now use CloudScraper for extraction:')
logger.info('  • extraction_method="http" → uses fast CloudScraper first')
logger.info('  • bot_protection_type="cloudflare" → for fallback escalation')
logger.info('  • CloudScraper automatically bypasses Cloudflare JS challenges')
logger.info('  • Falls back to Selenium only if CloudScraper fails')
logger.info('')
EOF
