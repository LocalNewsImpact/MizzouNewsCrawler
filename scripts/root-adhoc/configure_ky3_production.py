#!/usr/bin/env python3
"""Configure KY3 extraction in production via kubectl exec."""

import subprocess
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_kubectl_command(namespace: str, deployment: str) -> int:
    """Execute configuration in production Cloud SQL via kubectl."""
    
    logger.info("🚀 Configuring KY3 extraction method in production Cloud SQL")
    logger.info(f"   Namespace: {namespace}")
    logger.info(f"   Deployment: {deployment}")
    logger.info("")
    
    python_script = """
from src.models.database import DatabaseManager
from sqlalchemy import text

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
"""
    
    try:
        # Run kubectl exec with the Python script
        cmd = [
            'kubectl', 'exec', '-n', namespace,
            f'deployment/{deployment}', '--',
            'python', '-c', python_script
        ]
        
        subprocess.run(cmd, check=True, text=True)
        
        logger.info("")
        logger.info("✨ Configuration complete!")
        logger.info("")
        logger.info("ℹ️  Next steps:")
        logger.info("   1. CloudScraper will now handle all ky3.com requests")
        logger.info("   2. Test extraction with:")
        logger.info('      python -m src.cli extract --source "KSPR/KY3" --limit 5')
        logger.info("   3. Monitor extraction logs:")
        logger.info("      kubectl logs -f -n production deployment/mizzou-processor")
        logger.info("")
        logger.info("📊 Expected improvements:")
        logger.info("   • Extraction time: ~2-5s per article (vs 15-30s with Selenium)")
        logger.info("   • Success rate: ~100% (no bot protection on ky3.com)")
        logger.info("   • Resource usage: Minimal (no Chrome processes)")
        
        return 0
        
    except subprocess.CalledProcessError as e:
        logger.error(f"✗ kubectl command failed: {e}")
        logger.error("Make sure you have kubectl configured and production cluster access")
        return 1
    except Exception as e:
        logger.error(f"✗ Configuration failed: {e}")
        return 1


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Configure KY3 extraction in production'
    )
    parser.add_argument(
        '--namespace',
        default='production',
        help='Kubernetes namespace (default: production)'
    )
    parser.add_argument(
        '--deployment',
        default='mizzou-api',
        help='API deployment name (default: mizzou-api)'
    )
    
    args = parser.parse_args()
    
    return run_kubectl_command(args.namespace, args.deployment)


if __name__ == '__main__':
    sys.exit(main())
