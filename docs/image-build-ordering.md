# Image build ordering

Service images build `FROM` the base image:

```
base ──┬── crawler
       ├── api
       └── ml-base ── processor
```

**No dependent image may be built while a new base image is building.** A
dependent build resolves `base:latest` at the moment it starts; if a base
rebuild is in flight, it silently gets the *previous* base. The build succeeds,
the image ships without whatever was just added to `requirements-base.txt`, and
the gap only appears at runtime.

## What went wrong on 2026-07-20

Two PRs merged a minute apart, each triggering the build workflow. Within a
single run the ordering is correct — `build-crawler` `needs:` `build-api` →
`build-processor` → `build-ml-base` → `build-base`, and the base job blocks
until its Cloud Build finishes. But nothing serialized the *runs*.

| time (UTC) | event |
| --- | --- |
| 11:07:14 | base build starts |
| 11:08:20 | crawler build starts — pulls `base:latest`, still the old base |
| 11:10:13 | base finishes pushing (with the new dependency) |
| 11:11:21 | crawler pushes as `c843a31` — **missing the dependency** |
| 11:18:04 | second crawler build starts, now on the correct base |
| 11:21:14 | pushes, moving the `c843a31` tag to a different digest |

Both builds reported SUCCESS. The shipped crawler lacked `google-cloud-storage`,
so the raw HTML archive — which is deliberately fail-soft — no-opped in
production for hours without a single error.

A second failure compounded it: the `c843a31` tag pointed at two different
digests, and a node that had cached the first kept serving it under
`imagePullPolicy: IfNotPresent`. A test ran to completion on the stale image.

## Guardrails

1. **Serialized runs.** `.github/workflows/build-and-deploy-services.yml`
   declares a `concurrency` group, so only one build-and-deploy run is in
   flight. `cancel-in-progress: false` — a queued run must wait, never replace,
   or the build for that commit is lost.

2. **Build-time dependency verification.** Each service's Cloud Build runs
   `scripts/verify_image_dependencies.py` inside the freshly built image,
   before any deploy step. It asserts every package declared in the relevant
   requirements files is installed at a satisfying version, and fails the build
   naming what is missing. A stale-base image can no longer reach production.

   Run it by hand against any image:

   ```bash
   docker run --rm -v "$PWD:/repo:ro" IMAGE \
     python /repo/scripts/verify_image_dependencies.py \
     /repo/requirements-base.txt /repo/requirements-crawler.txt
   ```

3. **`imagePullPolicy: Always`** wherever a SHA tag is used, because those tags
   are mutable in practice — the same commit can be rebuilt and re-pushed.
   Pinning by digest (`image@sha256:...`) is stronger still when reproducing a
   specific run.

## When adding a dependency to requirements-base.txt

It reaches service images only after the base is rebuilt *and* dependents are
rebuilt on top of it. If you need it immediately, confirm the base finished
first, then rebuild dependents — and check the verification step passed rather
than assuming a green build means the package is present.
