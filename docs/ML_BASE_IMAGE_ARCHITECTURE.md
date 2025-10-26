# ML Base Image Architecture

## Overview

To optimize build times, we've split ML dependencies into a separate base image hierarchy:

```
┌──────────────┐
│     base     │  ← Common dependencies (SQLAlchemy, requests, etc.)
└──────┬───────┘
       │
   ┌───┴────┬─────────────┐
   │        │             │
┌──▼───┐ ┌─▼─────────┐ ┌─▼───────┐
│ API  │ │  ml-base  │ │ crawler │
└──────┘ └─────┬─────┘ └─────────┘
               │
          ┌────▼──────┐
          │ processor │
          └───────────┘
```

## Build Times

| Image Type | Build Time | Frequency | Why? |
|------------|------------|-----------|------|
| **base** | ~2 min | Rare (common deps change) | Core Python packages |
| **ml-base** | ~5-8 min | Very rare (ML versions change) | PyTorch, Transformers |
| **processor** | **~30-60 sec** | **Every code change** | Just copies your code! |
| **api** | ~1 min | Code changes | Lightweight FastAPI |
| **crawler** | ~1 min | Code changes | Article extraction |

## Key Benefits

✅ **10x faster processor iterations** - Code-only changes build in ~30 seconds  
✅ **Smaller non-ML images** - API and crawler stay at ~500MB vs 8GB  
✅ **Lower costs** - Less build time, less storage, less bandwidth  
✅ **Easier maintenance** - ML dependencies managed in one place  

## Files

### ML Dependencies
- **`requirements-ml.txt`** - Heavy ML packages (torch, transformers, sklearn, newspaper4k, selenium)
- **`Dockerfile.ml-base`** - Builds ML base image extending base
- **`cloudbuild-ml-base.yaml`** - Cloud Build config for ml-base
- **`trigger-ml-base.yaml`** - Trigger definition (manual/on ML file changes)

### Processor (Extends ML Base)
- **`requirements-processor.txt`** - Now minimal (processor-specific only)
- **`Dockerfile.processor`** - Extends ml-base instead of base
- **`cloudbuild-processor.yaml`** - Uses `ML_BASE_IMAGE` build arg

## Workflow

### Initial Setup (One Time)

1. **Build base image** (if not already built):
   ```bash
   gcloud builds triggers run build-base-manual --branch=feature/gcp-kubernetes-deployment
   ```

2. **Build ml-base image** (first time):
   ```bash
   gcloud builds triggers run build-ml-base-manual --branch=feature/gcp-kubernetes-deployment
   ```
   ⏱️ Takes ~5-8 minutes

3. **Build processor** (now fast!):
   ```bash
   gcloud builds triggers run build-processor-manual --branch=feature/gcp-kubernetes-deployment
   ```
   ⏱️ Takes ~30-60 seconds! 🎉

### Daily Development

**For processor code changes:**
```bash
# Just rebuild processor - it's fast now!
gcloud builds triggers run build-processor-manual --branch=feature/gcp-kubernetes-deployment
```
⏱️ ~30-60 seconds

**When to rebuild ml-base:**
- Upgrading PyTorch version
- Updating transformers library
- Adding new ML dependencies
- Updating newspaper4k, selenium, etc.

```bash
gcloud builds triggers run build-ml-base-manual --branch=feature/gcp-kubernetes-deployment
```
⏱️ ~5-8 minutes (but rare!)

## Image Sizes

| Image | Size | Contents |
|-------|------|----------|
| base | ~500MB | Core Python, SQLAlchemy, common utils |
| ml-base | ~6-8GB | base + PyTorch + Transformers + extraction tools |
| processor | ~6-8GB | ml-base + processor code (no rebuild of deps!) |
| api | ~500MB | base + FastAPI code |
| crawler | ~600MB | base + crawler code |

## Local Development

The same hierarchy works locally:

```bash
# Build ml-base locally (one time)
docker build -f Dockerfile.ml-base -t ml-base:local .

# Build processor (fast!)
docker build -f Dockerfile.processor --build-arg ML_BASE_IMAGE=ml-base:local -t processor:local .
```

## Troubleshooting

### "ml-base image not found"
You need to build ml-base first:
```bash
gcloud builds triggers run build-ml-base-manual --branch=feature/gcp-kubernetes-deployment
```

### "Processor missing ML dependencies"
Check that `Dockerfile.processor` uses `ML_BASE_IMAGE` and ml-base is built:
```dockerfile
ARG ML_BASE_IMAGE=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/ml-base:latest
FROM ${ML_BASE_IMAGE} AS runtime
```

### Need to add a new ML package?
1. Add it to `requirements-ml.txt`
2. Rebuild ml-base: `gcloud builds triggers run build-ml-base-manual`
3. Rebuild processor: `gcloud builds triggers run build-processor-manual`

## Migration Notes

**Before:**
- Processor installed torch, transformers, etc. on every build
- Build time: ~5-8 minutes per code change
- Wasted time waiting for pip install

**After:**
- ML dependencies pre-installed in ml-base
- Processor just copies code
- Build time: ~30-60 seconds per code change
- **Savings: 10x faster iteration!**

## Future Enhancements

Consider:
- Cache HuggingFace models in ml-base (faster first run)
- Version ml-base tags (ml-base:v1.0.0) for stability
- Automated ml-base rebuilds on dependency updates
- Multi-architecture builds (ARM64 for Apple Silicon)
