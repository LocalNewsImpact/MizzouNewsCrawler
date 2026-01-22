#!/bin/bash
# Deploy unblock proxy extraction feature
# This script:
# 1. Creates K8s secret for unblock proxy credentials
# 2. Runs database migration to add extraction_method column
# 3. Updates Nexstar domains to use 'unblock' method
# 4. Deploys updated processor service

set -e

NAMESPACE="production"
BRANCH="${1:-main}"

echo "======================================================"
echo "Deploying Unblock Proxy Extraction Feature"
echo "======================================================"
echo "Namespace: $NAMESPACE"
echo "Branch: $BRANCH"
echo ""

# Step 1: Sync K8s, GCP and GitHub secrets
echo "Step 1/4: Syncing unblock proxy credentials to K8s, GCP Secret Manager, and GitHub..."
# Use existing environment vars if present: UNBLOCK_PROXY_USER / UNBLOCK_PROXY_PASS
./scripts/sync-decodo-credentials.sh --gcp-project "$GOOGLE_CLOUD_PROJECT" --github-repo "LocalNewsImpact/MizzouNewsCrawler" production
echo ""

# Step 2: Run database migration
echo "Step 2/4: Running database migration..."
kubectl exec -n $NAMESPACE deployment/mizzou-api -- alembic upgrade head
echo "✅ Migration complete"
echo ""

# Step 3: Update Nexstar domains
echo "Step 3/4: Updating Nexstar domains to use 'unblock' method..."
kubectl exec -n $NAMESPACE deployment/mizzou-api -- python -c "
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
with db.get_session() as session:
    # Update Nexstar domains
    result = session.execute(text('''
        UPDATE sources
        SET
            extraction_method = 'unblock',
            bot_protection_type = 'perimeterx',
            bot_protection_detected_at = NOW()
        WHERE host IN (
            'fox2now.com',
            'fox4kc.com',
            'fourstateshomepage.com',
            'ozarksfirst.com'
        )
        AND (extraction_method != 'unblock' OR extraction_method IS NULL)
    '''))

    updated = result.rowcount
    session.commit()

    print(f'Updated {updated} domains to use unblock method')

    # Verify
    rows = session.execute(text('''
        SELECT host, extraction_method, bot_protection_type
        FROM sources
        WHERE host IN ('fox2now.com', 'fox4kc.com', 'fourstateshomepage.com', 'ozarksfirst.com')
        ORDER BY host
    ''')).fetchall()

    print('\nVerification:')
    for row in rows:
        print(f'  {row[0]}: {row[1]} ({row[2]})')
"
echo ""

# Step 4: Deploy processor service
echo "Step 4/4: Deploying processor service..."
./scripts/deploy-services.sh $BRANCH processor
echo ""

echo "======================================================"
echo "✅ Deployment Complete!"
echo "======================================================"
echo ""
echo "Next steps:"
echo "1. Verify extraction is working:"
echo "   kubectl logs -n production -l app=mizzou-processor --tail=100 -f"
echo ""
echo "2. Test with a Nexstar URL:"
echo "   kubectl exec -n production deployment/mizzou-processor -- python -m src.cli.cli_modular extract-url https://fox2now.com/news/missouri/some-article"
echo ""
echo "3. Monitor for 'unblock_proxy' in extraction logs"
