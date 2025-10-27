# GCP Deployment Configuration

This directory contains all Google Cloud Platform deployment configurations.

## Directory Structure

```
gcp/
├── cloudbuild/          # Cloud Build configuration files
│   ├── cloudbuild-*.yaml     # Build configs for each service
│   └── cloudbuild.yaml        # Main build config
├── triggers/            # Cloud Build trigger definitions
│   └── trigger-*.yaml         # Trigger configs for automated builds
└── clouddeploy/         # Cloud Deploy pipeline configs
    └── *.yaml                 # Deploy pipeline definitions
```

## Cloud Build Files

Build configurations define how Docker images are built and deployed:

- `cloudbuild-base.yaml` - Base Python image with dependencies
- `cloudbuild-ci-base.yaml` - CI testing image
- `cloudbuild-ml-base.yaml` - ML base image with PyTorch/Transformers
- `cloudbuild-api.yaml` - API service with full pipeline
- `cloudbuild-crawler.yaml` - Crawler service with full pipeline
- `cloudbuild-processor.yaml` - Processor service with full pipeline
- `cloudbuild-migrator.yaml` - Database migration runner
- `cloudbuild-*-only.yaml` - Fast rebuilds (skip base images)
- `cloudbuild-lab-*.yaml` - Lab environment builds

## Trigger Files

Cloud Build triggers automate builds on code changes:

- `trigger-base.yaml` - Auto-rebuild base image
- `trigger-ml-base.yaml` - Auto-rebuild ML base image
- `trigger-api.yaml` - Auto-deploy API on changes
- `trigger-crawler.yaml` - Auto-deploy crawler on changes
- `trigger-processor.yaml` - Auto-deploy processor on changes
- `trigger-migrator.yaml` - Migration runner trigger

## Usage

### Manual Build from Root Directory

```bash
# From repository root
gcloud builds submit --config=gcp/cloudbuild/cloudbuild-processor.yaml

# Or use the scripts in scripts/ directory
./scripts/deployment/deploy-*.sh
```

### Trigger Cloud Build

```bash
# List triggers
gcloud builds triggers list --project=mizzou-news-crawler

# Run a specific trigger
gcloud builds triggers run build-processor-manual --branch=main
```

### Cloud Deploy

```bash
# Create a release
gcloud deploy releases create processor-v1.0.0 \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1
```

## Migration Note

**Files moved from root → gcp/ on 2025-10-26**

If you have scripts or documentation that reference:
- `cloudbuild-*.yaml` → Update to `gcp/cloudbuild/cloudbuild-*.yaml`
- `trigger-*.yaml` → Update to `gcp/triggers/trigger-*.yaml`
- `clouddeploy.yaml` → Update to `gcp/clouddeploy.yaml`
