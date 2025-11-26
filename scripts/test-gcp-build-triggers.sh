#!/bin/bash
set -e

# Test script to validate GCP Cloud Build triggers work before pushing to main
# Usage: ./scripts/test-gcp-build-triggers.sh [service1] [service2] ...
# Example: ./scripts/test-gcp-build-triggers.sh crawler processor

BRANCH="${GITHUB_REF_NAME:-$(git branch --show-current)}"
PROJECT_ID="${GCP_PROJECT:-mizzou-news-research}"

echo "🧪 Testing GCP Cloud Build triggers on branch: $BRANCH"
echo "Project: $PROJECT_ID"
echo ""

# If no services specified, detect changed files
if [ $# -eq 0 ]; then
    echo "📊 Auto-detecting changed services..."
    
    # Get changed files since last commit
    CHANGED_FILES=$(git diff --name-only HEAD~1 HEAD 2>/dev/null || echo "")
    
    if [ -z "$CHANGED_FILES" ]; then
        echo "❌ No changes detected. Specify services manually or commit changes first."
        exit 1
    fi
    
    echo "Changed files:"
    echo "$CHANGED_FILES" | sed 's/^/  /'
    echo ""
    
    # Detect which services to build
    SERVICES=()
    
    # Always test migrator on main
    SERVICES+=("migrator")
    
    # Check for crawler changes
    if echo "$CHANGED_FILES" | grep -qE '(Dockerfile\.crawler|requirements-crawler\.txt|src/crawler/|src/services/|src/utils/|src/cli/commands/(discovery|verification|extraction|content_cleaning)\.py)'; then
        SERVICES+=("crawler")
    fi
    
    # Check for processor changes
    if echo "$CHANGED_FILES" | grep -qE '(Dockerfile\.processor|requirements-processor\.txt|src/pipeline/|src/ml/|src/services/classification_service\.py|src/cli/commands/(analysis|entity_extraction)\.py|alembic/versions/)'; then
        SERVICES+=("processor")
    fi
    
    # Check for API changes
    if echo "$CHANGED_FILES" | grep -qE '(Dockerfile\.api|requirements-api\.txt|backend/|src/models/api_backend\.py|src/cli/commands/(cleaning|reports)\.py)'; then
        SERVICES+=("api")
    fi
    
    # Check for base changes
    if echo "$CHANGED_FILES" | grep -qE '(Dockerfile\.base|requirements-base\.txt|src/config\.py|pyproject\.toml|setup\.py)'; then
        SERVICES+=("base")
    fi
    
    # Check for ml-base changes
    if echo "$CHANGED_FILES" | grep -qE '(Dockerfile\.ml-base|requirements-ml\.txt)'; then
        SERVICES+=("ml-base")
    fi
    
    if [ ${#SERVICES[@]} -eq 0 ]; then
        echo "✅ No service changes detected"
        exit 0
    fi
    
    set -- "${SERVICES[@]}"
fi

echo "🎯 Services to test: $*"
echo ""

# Test each service trigger
for SERVICE in "$@"; do
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🔨 Testing: $SERVICE"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    TRIGGER_NAME="build-${SERVICE}-manual"
    
    # Check if trigger exists
    if ! gcloud builds triggers describe "$TRIGGER_NAME" --project="$PROJECT_ID" &>/dev/null; then
        echo "❌ Trigger '$TRIGGER_NAME' not found"
        exit 1
    fi
    
    echo "✅ Trigger exists: $TRIGGER_NAME"
    
    # Dry run - just verify the command would work
    echo "📝 Would execute:"
    echo "   gcloud builds triggers run $TRIGGER_NAME --branch=$BRANCH --project=$PROJECT_ID"
    echo ""
    
    # Uncomment to actually trigger builds:
    # echo "🚀 Triggering build..."
    # gcloud builds triggers run "$TRIGGER_NAME" --branch="$BRANCH" --project="$PROJECT_ID"
    # echo "✅ Build triggered successfully"
    # echo ""
done

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ All trigger tests passed!"
echo ""
echo "To actually trigger builds, uncomment the gcloud builds triggers run line in this script"
echo "Or use the GCP tasks in VS Code"
