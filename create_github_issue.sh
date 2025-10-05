#!/bin/bash
# Script to create GitHub issue from GITHUB_ISSUE_CONTENT.md
# Note: This requires GitHub CLI (gh) to be authenticated

set -e

TITLE="Test Infrastructure Fixes Required for Cloud SQL Migration"
LABELS="bug,testing,database,cloud-sql,priority-high"
BODY_FILE="GITHUB_ISSUE_CONTENT.md"

echo "Creating GitHub issue..."
echo "Title: $TITLE"
echo "Labels: $LABELS"
echo ""

# Check if gh is authenticated
if ! gh auth status &> /dev/null; then
    echo "Error: GitHub CLI is not authenticated."
    echo "Please run: gh auth login"
    exit 1
fi

# Create the issue
gh issue create \
    --title "$TITLE" \
    --body-file "$BODY_FILE" \
    --label "$LABELS" \
    --repo LocalNewsImpact/MizzouNewsCrawler

echo ""
echo "Issue created successfully!"
echo ""
echo "Alternatively, you can create the issue manually:"
echo "1. Go to: https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/new"
echo "2. Copy the contents of GITHUB_ISSUE_CONTENT.md"
echo "3. Set labels: bug, testing, database, cloud-sql, priority-high"
