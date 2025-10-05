# Base Image Quick Start Guide

Quick reference for working with the shared base image optimization.

## 🚀 TL;DR

```bash
# Local Development
./scripts/build-base.sh           # Build base once (8-10 min)
docker compose build              # Build services (2-3 min)
docker compose up -d              # Run services

# Cloud Deployment
gcloud builds triggers run build-base-manual      # Build base (~10 min)
gcloud builds triggers run build-api-manual       # Build API (~2 min)
gcloud builds triggers run build-processor-manual # Build processor (~2 min)
gcloud builds triggers run build-crawler-manual   # Build crawler (~2 min)
```

---

## 📚 What Changed?

### Before
Each service built independently:
- ⏱️ 15 minutes per service
- 💰 $0.15 per service
- 🔄 Redundant dependency installation

### After
Services use shared base image:
- ⏱️ 2-3 minutes per service
- 💰 $0.05 per service
- ✨ Base dependencies cached

---

## 🏗️ Architecture

```
Base Image (mizzou-base:latest)
└─ Common packages (pandas, sqlalchemy, spacy, etc.)
   ├─ API Service (+ FastAPI)
   ├─ Processor Service (+ ML libs)
   └─ Crawler Service (+ Selenium)
```

---

## 📝 Key Files

| File | Purpose |
|------|---------|
| `Dockerfile.base` | Base image with common deps |
| `requirements-base.txt` | 30 common packages |
| `requirements-api.txt` | 4 API packages |
| `requirements-processor.txt` | 4 ML packages |
| `requirements-crawler.txt` | 6 scraping packages |
| `cloudbuild-base.yaml` | Cloud Build config for base |
| `scripts/build-base.sh` | Automated build script |

---

## 💻 Local Development

### First Time Setup

```bash
# 1. Build base image once
./scripts/build-base.sh

# 2. Build services
docker compose build

# 3. Run everything
docker compose up -d

# 4. Test
curl http://localhost:8000/health
```

### Daily Development

```bash
# Just build services (fast)
docker compose build

# Or rebuild specific service
docker build -t mizzou-api:latest -f Dockerfile.api .
```

### When to Rebuild Base

**Rebuild base if you:**
- ✅ Add/remove packages in `requirements-base.txt`
- ✅ Update system dependencies
- ✅ Update spacy model

**Don't rebuild base if you:**
- ❌ Change application code
- ❌ Update service-specific requirements
- ❌ Change config

---

## ☁️ Cloud Deployment

### Building Base Image

```bash
# Trigger base build (manual, ~10 minutes)
gcloud builds triggers run build-base-manual

# Monitor progress
gcloud builds list --ongoing

# Verify image exists
gcloud artifacts docker images list \
  us-central1-docker.pkg.dev/PROJECT/mizzou-crawler/base
```

### Building Services

Services automatically use the base image:

```bash
# Trigger service builds (~2-3 min each)
gcloud builds triggers run build-api-manual
gcloud builds triggers run build-processor-manual
gcloud builds triggers run build-crawler-manual

# Or push to trigger branch (auto-build)
git push origin feature/my-branch
```

---

## 🔧 Common Tasks

### Update Base Dependencies

```bash
# 1. Edit base requirements
vim requirements-base.txt

# 2. Test locally
./scripts/build-base.sh

# 3. Commit
git add requirements-base.txt
git commit -m "Update base dependencies"
git push

# 4. Build in cloud
gcloud builds triggers run build-base-manual

# 5. Rebuild services (they'll use new base)
gcloud builds triggers run build-api-manual
```

### Add Service-Specific Dependency

```bash
# 1. Edit service requirements
vim requirements-api.txt  # or processor/crawler

# 2. Build service (base unchanged, fast!)
docker build -t mizzou-api:latest -f Dockerfile.api .

# 3. Test
docker run mizzou-api:latest python -c "import new_package"

# 4. Commit and deploy
git add requirements-api.txt
git commit -m "Add new API dependency"
git push
```

### Troubleshoot Build Issues

```bash
# Check if base image exists
docker images | grep mizzou-base

# Rebuild base without cache
docker build --no-cache -t mizzou-base:latest -f Dockerfile.base .

# View base image packages
docker run --rm mizzou-base:latest pip list

# Test service build with verbose output
docker build --progress=plain -t mizzou-api:test -f Dockerfile.api .
```

---

## 🧪 Testing

### Validate Implementation

```bash
# Run comprehensive tests
./scripts/test-base-image.sh

# Expected: All tests pass (46/46)
```

### Manual Testing

```bash
# Build everything
docker compose build

# Start services
docker compose up -d

# Test API
curl http://localhost:8000/health
curl http://localhost:8000/api/telemetry/summary

# Test Crawler
docker compose run --rm crawler python -m src.cli.main discover-urls --source-limit 1

# Test Processor
docker compose run --rm processor python -m src.cli.main extract --limit 5

# Check logs
docker compose logs -f api
docker compose logs -f processor
```

---

## 📊 Performance

### Build Times

| Service | Before | After | Improvement |
|---------|--------|-------|-------------|
| Base | N/A | 8-10 min | (One-time) |
| API | 15 min | 2-3 min | 80-87% ⬇️ |
| Processor | 15 min | 2-3 min | 80-87% ⬇️ |
| Crawler | 15 min | 2-3 min | 80-87% ⬇️ |
| **Total** | **45 min** | **15 min** | **67% ⬇️** |

### Cost Savings

- Build cost: $0.15 → $0.05 per service (67% reduction)
- Annual savings (500 builds): ~$100+
- Developer time saved: ~30 min per full build

---

## 🆘 Troubleshooting

### "Base image not found"

```bash
# Solution: Build base locally
./scripts/build-base.sh

# Or pull from cloud
docker pull us-central1-docker.pkg.dev/PROJECT/mizzou-crawler/base:latest
docker tag us-central1-docker.pkg.dev/PROJECT/mizzou-crawler/base:latest mizzou-base:latest
```

### "Package not found" during service build

```bash
# Check if package is in correct requirements file
grep "package-name" requirements-*.txt

# If in wrong file, move it
vim requirements-base.txt  # or service-specific file

# Rebuild appropriate image
./scripts/build-base.sh     # if base changed
docker build -f Dockerfile.api .  # if service changed
```

### "Build takes too long"

```bash
# Check if base image is cached
docker images | grep mizzou-base

# If missing, build it
./scripts/build-base.sh

# Clear Docker cache if needed
docker system prune -af
```

---

## 📖 Documentation

- 📘 **Full Roadmap**: [docs/issues/shared-base-image-optimization.md](./issues/shared-base-image-optimization.md)
- 📗 **Maintenance Guide**: [docs/BASE_IMAGE_MAINTENANCE.md](./BASE_IMAGE_MAINTENANCE.md)
- 📕 **Docker Guide**: [docs/DOCKER_GUIDE.md](./DOCKER_GUIDE.md)
- 📙 **Completion Report**: [docs/ISSUE_38_COMPLETION.md](./ISSUE_38_COMPLETION.md)

---

## 🎯 Key Takeaways

1. **Base image built once** → services build fast
2. **Only rebuild base** when base dependencies change
3. **Service changes** don't require base rebuild
4. **80%+ faster builds** = happier developers
5. **67% cost reduction** = happier budget

---

## ✅ Checklist

First time setup:
- [ ] Read this guide
- [ ] Run `./scripts/test-base-image.sh` (verify implementation)
- [ ] Build base: `./scripts/build-base.sh`
- [ ] Build services: `docker compose build`
- [ ] Test: `docker compose up -d && curl localhost:8000/health`

Daily workflow:
- [ ] Make code changes
- [ ] Build services only: `docker compose build`
- [ ] Test changes: `docker compose up -d`

When updating dependencies:
- [ ] Edit appropriate requirements file
- [ ] Rebuild base if `requirements-base.txt` changed
- [ ] Rebuild service if service requirements changed
- [ ] Test locally before pushing

---

*For more details, see the full documentation in `docs/BASE_IMAGE_MAINTENANCE.md`*
