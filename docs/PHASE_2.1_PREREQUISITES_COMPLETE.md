# Phase 2.1: Prerequisites - COMPLETE ✅

**Date**: October 3, 2025  
**Status**: Prerequisites Installed

## Installation Summary

### ✅ kubectl
- **Status**: Already installed
- **Version**: v1.34.1
- **Location**: `/usr/local/bin/kubectl`

### ✅ gcloud CLI
- **Status**: Freshly installed via Homebrew
- **Version**: 541.0.0
- **Location**: `/opt/homebrew/bin/gcloud`
- **Components Installed**:
  - gcloud (core)
  - bq (BigQuery CLI)
  - gsutil (Cloud Storage CLI)
  - docker-credential-gcloud
  - git-credential-gcloud

## Next Steps

### Step 1: Initialize gcloud and Authenticate

Run the following command to authenticate with your localnewsimpact.org account:

```bash
gcloud init
```

This will:
1. Open a browser for authentication
2. Let you select or create a project
3. Set default compute region/zone
4. Configure default settings

**Important**: When prompted:
- Choose to create a **new project**: `mizzou-news-crawler`
- Set default region to: `us-central1`
- Set default zone to: `us-central1-a`

### Step 2: Alternative - Manual Authentication

If you prefer to set things up manually:

```bash
# Authenticate
gcloud auth login

# This will open browser - login with localnewsimpact.org credentials
```

After authentication, you'll need to:
1. Find your organization ID
2. Create the GCP project
3. Enable billing
4. Enable required APIs

### Step 3: Verify Authentication

After running `gcloud init` or `gcloud auth login`, verify:

```bash
# Check authentication
gcloud auth list

# Should show:
# ACTIVE  ACCOUNT
# *       your-email@localnewsimpact.org

# List organizations
gcloud organizations list

# Save the ORGANIZATION_ID for later
```

### Step 4: Set Up Project Variables

Once authenticated, we'll set up environment variables for the project:

```bash
# Set these based on your authentication results
export ORG_ID="YOUR_ORG_ID_HERE"  # From 'gcloud organizations list'
export PROJECT_ID="mizzou-news-crawler"
export PROJECT_NAME="MizzouNewsCrawler"
export REGION="us-central1"
export BILLING_ACCOUNT_ID="YOUR_BILLING_ACCOUNT_ID"  # From 'gcloud billing accounts list'

# Save these to a file for future sessions
cat > ~/.mizzou-gcp-env << EOF
export ORG_ID="${ORG_ID}"
export PROJECT_ID="${PROJECT_ID}"
export PROJECT_NAME="${PROJECT_NAME}"
export REGION="${REGION}"
export BILLING_ACCOUNT_ID="${BILLING_ACCOUNT_ID}"
EOF

chmod 600 ~/.mizzou-gcp-env
```

## What's Next?

Once you've completed authentication, we'll proceed with:

**Phase 2.2: GCP Project Setup**
- Create the mizzou-news-crawler project
- Link billing account
- Enable required APIs
- Set up service accounts

**Estimated Time**: 15 minutes

---

## Quick Reference Commands

```bash
# Load environment variables for future sessions
source ~/.mizzou-gcp-env

# Check current project
gcloud config get-value project

# List all projects
gcloud projects list

# Switch projects
gcloud config set project PROJECT_ID

# Check current configuration
gcloud config list

# View help for any command
gcloud help
gcloud container help
gcloud sql help
```

---

## Troubleshooting

### Issue: Browser doesn't open for authentication
```bash
# Use this alternative command
gcloud auth login --no-launch-browser

# Copy the URL shown and open in your browser manually
```

### Issue: Multiple Google accounts
```bash
# List all authenticated accounts
gcloud auth list

# Switch between accounts
gcloud config set account EMAIL_ADDRESS
```

### Issue: Need to re-authenticate
```bash
# Revoke current auth
gcloud auth revoke

# Re-authenticate
gcloud auth login
```

---

## Ready to Continue?

When you're ready to authenticate and set up the project, let me know and I'll guide you through the next steps!

**Command to run now:**
```bash
gcloud init
```

Or if you prefer manual setup:
```bash
gcloud auth login
```
