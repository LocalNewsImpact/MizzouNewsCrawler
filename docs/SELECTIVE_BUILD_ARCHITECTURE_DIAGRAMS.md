# Selective Service Build System - Visual Architecture Guide

## System Overview Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Developer Workflow                             │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │  Create Feature Branch  │
                    │  git checkout -b fix/.. │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │   Make Code Changes     │
                    │   Edit, test, commit    │
                    └────────────┬────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │                         │
                    ▼                         ▼
        ┌─────────────────────┐   ┌──────────────────────┐
        │  Test Locally       │   │ Verify Build Plan    │
        │  Run unit/integ     │   │ ./test-selective...  │
        │  tests              │   │ Expected: migrator,  │
        │                     │   │           processor  │
        └────────────┬────────┘   └──────────┬───────────┘
                     │                       │
                     └───────────┬───────────┘
                                 │
                                 ▼
                    ┌─────────────────────────────┐
                    │  Push to Feature Branch     │
                    │  git push origin fix/...    │
                    └────────────┬────────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────────┐
                    │  Create Pull Request        │
                    │  Request code review        │
                    └────────────┬────────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────────┐
                    │  Get Approval & Merge       │
                    │  Merge PR to main           │
                    └────────────┬────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│           GitHub Push to Main Triggers Workflow                     │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
         ┌───────────────────────────────────────────────┐
         │  GitHub Actions Workflow Starts               │
         │  selective-service-build.yml                  │
         └───────┬───────────────────────────────────────┘
                 │
         ┌───────▼──────────────────────────────┐
         │     JOB: detect-changes              │
         │  (Runs: git diff + pattern matching) │
         └───────┬──────────────────────────────┘
                 │
        ┌────────┴────────┬──────────────┬──────────────┬──────────────┐
        │                 │              │              │              │
        ▼                 ▼              ▼              ▼              ▼
   ┌────────┐        ┌─────────┐   ┌──────────┐  ┌─────────┐    ┌────────┐
   │ BASE   │        │ ML-BASE │   │MIGRATOR  │  │PROCESSOR│    │  API   │
   │        │        │         │   │          │  │         │    │        │
   │Changed?│        │Changed? │   │Always    │  │Changed? │    │Changed?│
   │        │        │         │   │rebuild   │  │         │    │        │
   │rebuild │        │rebuild  │   │on main   │  │rebuild  │    │rebuild │
   │  =     │        │  =      │   │  =       │  │  =      │    │  =     │
   │ FALSE  │        │ FALSE   │   │  TRUE    │  │ FALSE   │    │ FALSE  │
   └────────┘        └─────────┘   └──────────┘  └─────────┘    └────────┘
                                          ▲
                                          │
                                  ┌───────┴────────┐
                                  │  GIT DIFF:     │
                                  │                │
                                  │ Modified:      │
                                  │ alembic/       │
                                  │ versions/...   │
                                  └────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  GitHub Actions Workflow Outputs & Conditional Job Execution       │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
         ▼                       ▼                       ▼
   ┌──────────────┐        ┌──────────────┐      ┌──────────────┐
   │ BUILD: base  │        │BUILD: ml-base│      │BUILD:migrate │
   │ if:rebuild   │        │ if:rebuild   │      │ if:rebuild   │
   │ =true        │        │ =true        │      │ =true        │
   │              │        │              │      │              │
   │ Condition:   │        │ Condition:   │      │ Condition:   │
   │ FALSE        │        │ FALSE        │      │ TRUE (RUNS)  │
   │              │        │              │      │              │
   │ Status:      │        │ Status:      │      │ Status:      │
   │ SKIPPED ⏭️   │        │ SKIPPED ⏭️   │      │ RUNNING 🚀   │
   └──────────────┘        └──────────────┘      └──────┬───────┘
                                                        │
                                                        ▼
                                    ┌───────────────────────────────┐
                                    │  Authenticate to GCP          │
                                    │  gcloud auth ...              │
                                    └───────────────────────────────┘
                                                        │
                                                        ▼
                                    ┌───────────────────────────────┐
                                    │  Trigger Cloud Build          │
                                    │  gcloud builds triggers run   │
                                    │  migrator-manual              │
                                    │  --branch=main                │
                                    └───────────────────────────────┘
```

## Build Execution Flow

```
┌────────────────────────────────────────────────────────────────────┐
│          GitHub Actions: Service Build Dependency Order            │
└────────────────────────────────────────────────────────────────────┘

Diagram: BUILD DEPENDENCY CHAIN
(Only shows services that actually rebuild)

Sequential Phase:
┌──────────────────────┐
│   1. Build: base     │ ◄─── needs: (none - runs first)
│   gcloud triggers... │
│   (20 min)           │
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│  2. Build: ml-base   │ ◄─── needs: [base] (waits for base)
│   gcloud triggers... │
│   (10 min)           │
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│  3. Build: migrator  │ ◄─── needs: [base] (waits for base)
│   gcloud triggers... │
│   (5 min)            │
└──────┬──────────┬─────────┬──────────┐
       │          │         │          │
       ▼          ▼         ▼          ▼

Parallel Phase (AFTER sequential):
┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│4a. processor   │  │4b. api         │  │4c. crawler     │
│needs:[ml-base, │  │needs:[base,    │  │needs:[base,    │
│       migrator]│  │       migrator] │  │       migrator]│
│(15 min)        │  │(10 min)        │  │(12 min)        │
└────────────────┘  └────────────────┘  └────────────────┘
       │                   │                    │
       └───────────────────┼────────────────────┘
                           │
                           ▼
            ┌──────────────────────────────┐
            │ 5. Report Build Plan         │
            │    (GitHub Actions Summary)  │
            │    (1 min)                   │
            └──────────────────────────────┘
                           │
                           ▼
            ┌──────────────────────────────┐
            │ All Jobs Complete            │
            │ Ready for Cloud Deploy       │
            │                              │
            │ Total time: ~45 min (full)   │
            │            or ~20 min (ML)   │
            └──────────────────────────────┘
```

## File Pattern Matching Flow

```
┌─────────────────────────────────────────────────────────┐
│         Git Diff Analysis & Pattern Matching            │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
        ┌────────────────────────────┐
        │  Get Changed Files:        │
        │  git diff origin/main HEAD │
        │  --name-only               │
        │                            │
        │ Returns:                   │
        │ src/ml/classifier.py       │
        │ src/cli/commands/...       │
        │ alembic/versions/...       │
        └─────────┬──────────────────┘
                  │
        ┌─────────▼──────────────────┐
        │ Check Each Pattern:        │
        │                            │
        │ Pattern 1: BASE            │
        │ (Dockerfile.base|...)      │
        │ ❌ No match                │
        │                            │
        │ Pattern 2: ML-BASE         │
        │ (Dockerfile.ml-base|...)   │
        │ ❌ No match                │
        │                            │
        │ Pattern 3: MIGRATOR        │
        │ (alembic/versions/|...)    │
        │ ✅ MATCH! (/versions/...)  │
        │                            │
        │ Pattern 4: PROCESSOR       │
        │ (src/ml/|src/pipeline|...) │
        │ ✅ MATCH! (src/ml/...)     │
        │                            │
        │ Pattern 5: API             │
        │ (backend/|...)             │
        │ ❌ No match                │
        │                            │
        │ Pattern 6: CRAWLER         │
        │ (src/crawler/|...)         │
        │ ❌ No match                │
        └─────────┬──────────────────┘
                  │
                  ▼
        ┌────────────────────────────┐
        │ Detected Services:         │
        │ ✅ migrator                │
        │ ✅ processor               │
        │ ❌ api                     │
        │ ❌ crawler                 │
        │ ❌ base                    │
        │ ❌ ml-base                 │
        │                            │
        │ Apply Dependencies:        │
        │ MIGRATOR is always on main │
        │ → Always true              │
        │                            │
        │ Final rebuild set:         │
        │ ✅ migrator                │
        │ ✅ processor               │
        └────────────┬───────────────┘
                     │
                     ▼
        ┌────────────────────────────┐
        │ Output Workflow Flags:     │
        │                            │
        │ rebuild-base=false         │
        │ rebuild-ml-base=false      │
        │ rebuild-migrator=true      │
        │ rebuild-processor=true     │
        │ rebuild-api=false          │
        │ rebuild-crawler=false      │
        └────────────┬───────────────┘
                     │
                     ▼
        ┌────────────────────────────┐
        │ Conditional Job Execution: │
        │                            │
        │ build-base:                │
        │  if: rebuild-base == true  │
        │  Result: SKIPPED ⏭️         │
        │                            │
        │ build-migrator:            │
        │  if: rebuild-migrator==true│
        │  Result: RUNS 🚀            │
        │                            │
        │ build-processor:           │
        │  if: rebuild-processor==... │
        │  Result: RUNS 🚀            │
        └────────────────────────────┘
```

## Cloud Build Integration

```
┌────────────────────────────────────────────────────────────┐
│     GitHub Actions to Cloud Build Communication            │
└────────────────────────────┬───────────────────────────────┘
                             │
                             ▼
         ┌──────────────────────────────────────┐
         │ GitHub Actions: build-processor job  │
         │                                      │
         │ Steps:                               │
         │ 1. Checkout code                     │
         │ 2. Auth to GCP                       │
         │ 3. Trigger Cloud Build               │
         │    gcloud builds triggers run \      │
         │    processor-manual \                │
         │    --branch=main \                   │
         │    --project=PROJECT_ID              │
         └─────────┬──────────────────────────┘
                   │
                   ▼
    ┌──────────────────────────────────────────────┐
    │ Google Cloud Build Service                   │
    │                                              │
    │ Trigger: processor-manual                    │
    │ Branch: main                                 │
    │                                              │
    │ Executes: gcp/cloudbuild/cloudbuild-        │
    │           processor.yaml                     │
    │                                              │
    │ Build Steps:                                 │
    │  1. Pull base & ml-base images               │
    │  2. Build processor image with deps          │
    │  3. Tag: us-docker.pkg.dev/...:COMMIT_SHA   │
    │  4. Push to Artifact Registry                │
    └─────────┬──────────────────────────────────┘
              │
              ▼
   ┌──────────────────────────────────────────────┐
   │ Artifact Registry                            │
   │                                              │
   │ Image: mizzou-processor:abc1234              │
   │ Size: ~2.5GB                                 │
   │ Metadata:                                    │
   │ - Built: 2024-01-15 10:30:45 UTC            │
   │ - SHA: abc1234...                           │
   │ - Digest: sha256:def5678...                 │
   └─────────┬──────────────────────────────────┘
             │
             ▼
   ┌──────────────────────────────────────────────┐
   │ Cloud Deploy: Create Release                 │
   │                                              │
   │ Release: mizzou-processor-v1234567           │
   │ Images:                                      │
   │  - processor: abc1234 (NEW)                  │
   │  - (other services unchanged)                │
   │                                              │
   │ Target: prod-gke                             │
   └─────────┬──────────────────────────────────┘
             │
             ▼
   ┌──────────────────────────────────────────────┐
   │ Google Kubernetes Engine                     │
   │                                              │
   │ Namespace: production                        │
   │                                              │
   │ Deployment: mizzou-processor                 │
   │ Current:  pod-abc (image: old-sha)           │
   │ Updating: pod-def (image: abc1234) ▶ NEW    │
   │                                              │
   │ HPA scales pods as needed                    │
   │ CloudRun health checks pod                   │
   │                                              │
   │ Argo Workflows detect change                 │
   │ Trigger new pipeline execution               │
   └──────────────────────────────────────────────┘
```

## Decision Tree: Will This Change Trigger a Rebuild?

```
START: File Changed
│
├─ Does file match BASE pattern?
│  ├─ YES (Dockerfile.base, pyproject.toml, alembic/, etc.)
│  │  └─→ REBUILD: base, ml-base, migrator, processor, api, crawler
│  │
│  └─ NO
│     │
│     ├─ Does file match ML-BASE pattern?
│     │  ├─ YES (Dockerfile.ml-base, requirements-ml.txt)
│     │  │  └─→ REBUILD: migrator, ml-base, processor
│     │  │
│     │  └─ NO
│     │     │
│     │     ├─ Does file match MIGRATOR pattern?
│     │     │  ├─ YES (alembic/versions/*, Dockerfile.migrator)
│     │     │  │  └─→ REBUILD: migrator
│     │     │  │     (+ always migrator on main anyway)
│     │     │  │
│     │     │  └─ NO
│     │     │     │
│     │     │     ├─ Does file match PROCESSOR pattern?
│     │     │     │  ├─ YES (src/ml/, src/pipeline/, analysis.py, etc.)
│     │     │     │  │  └─→ REBUILD: migrator, processor
│     │     │     │  │
│     │     │     │  └─ NO
│     │     │     │     │
│     │     │     │     ├─ Does file match API pattern?
│     │     │     │     │  ├─ YES (backend/, api_backend.py, reports.py, etc.)
│     │     │     │     │  │  └─→ REBUILD: migrator, api
│     │     │     │     │  │
│     │     │     │     │  └─ NO
│     │     │     │     │     │
│     │     │     │     │     ├─ Does file match CRAWLER pattern?
│     │     │     │     │     │  ├─ YES (src/crawler/, discovery.py, etc.)
│     │     │     │     │     │  │  └─→ REBUILD: migrator, crawler
│     │     │     │     │     │  │
│     │     │     │     │     │  └─ NO
│     │     │     │     │     │     │
│     │     │     │     │     │     └─→ REBUILD: migrator (only)
│     │     │     │     │     │        (docs, README, config files, etc.)
│     │     │     │     │     │
│     │     │     │     │     └─ (Always migrator on main anyway)
│     │     │     │     │
│     │     │     │     └─ END
│     │     │     │
│     │     │     └─ END
│     │     │
│     │     └─ END
│     │
│     └─ END
│
└─ END

SUMMARY RULES:
1. If ANY pattern matches → rebuild that service + dependencies
2. Migrator ALWAYS rebuilds on main (mandatory)
3. BASE is foundational → if BASE changes, ALL services rebuild
4. ML-BASE only affects PROCESSOR → if ML-BASE changes, rebuild processor
5. Default (no match) → only rebuild migrator
```

## Performance Comparison

```
┌─────────────────────────────────────────────────────────────┐
│         Build Time Comparison: Old vs New System            │
└─────────────────────────────────────────────────────────────┘

OLD SYSTEM (All-or-Nothing):
Any change → Always rebuild ALL 6 services

┌──────────────────────────────────────────────┐
│ 1. base               [████████████] 20 min   │
├──────────────────────────────────────────────┤
│ 2. ml-base (needs 1)  [████████]     10 min   │
├──────────────────────────────────────────────┤
│ 3. migrator (needs 1) [████]          5 min   │
├──────────────────────────────────────────────┤
│ 4. processor (needs   [██████████]   15 min   │
│    2,3)               [sequential]            │
├──────────────────────────────────────────────┤
│ 5. api (needs 1,3)    [██████████]   10 min   │
│    (parallel w/ 4)    [parallel]              │
├──────────────────────────────────────────────┤
│ 6. crawler (needs 1,3)[██████████]   10 min   │
│    (parallel w/ 4,5)  [parallel]              │
└──────────────────────────────────────────────┘
Total Sequential Time: 20 + 10 + 5 = 35 min
Total Parallel Time: 35 + max(15,10,10) = 50 min
Cloud Build Cost: 6 image rebuilds

NEW SYSTEM (Selective):
Only rebuild services that changed

SCENARIO A: Crawler fix (src/crawler/)
┌──────────────────────────────────────────────┐
│ 1. migrator           [████]          5 min   │
├──────────────────────────────────────────────┤
│ 2. crawler (needs 1)  [██████████]   12 min   │
│    (parallel)         [parallel]              │
└──────────────────────────────────────────────┘
Total Time: 5 + 12 = 17 min
Savings: 50 - 17 = 33 min (66% faster!)
Cloud Build Cost: 2 image rebuilds (67% cost saving)

SCENARIO B: ML Feature (src/ml/)
┌──────────────────────────────────────────────┐
│ 1. base               [████████████] 20 min   │
│    (detected: alembic)                        │
├──────────────────────────────────────────────┤
│ 2. migrator (needs 1) [████]          5 min   │
├──────────────────────────────────────────────┤
│ 3. processor          [██████████]   15 min   │
│    (needs 1 + needs   (with ml-base          │
│    ml-base)           & src/ml/)              │
└──────────────────────────────────────────────┘
Total Time: 20 + 5 + 15 = 40 min
Savings: 50 - 40 = 10 min (20% faster)
Cloud Build Cost: 3 image rebuilds (50% cost saving)

SCENARIO C: Docs Only (README.md)
┌──────────────────────────────────────────────┐
│ 1. migrator           [████]          5 min   │
│    (always on main)                          │
└──────────────────────────────────────────────┘
Total Time: 5 min
Savings: 50 - 5 = 45 min (90% faster!)
Cloud Build Cost: 1 image rebuild (83% cost saving)
```

---

This completes the visual architecture documentation!
