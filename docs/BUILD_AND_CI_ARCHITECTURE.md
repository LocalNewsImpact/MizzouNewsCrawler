# Build and CI architecture across the suite

Three repositories share a database, a contracts package and a deployment
project today, and analysis/enrichment is to become a fourth. The
application architecture supports that. The build and CI architecture does
not: it has one repository's worth of conventions, invented independently
in each repository, and the crawler's copy failed twice on 2026-09-04 in
ways that no test could have caught.

This describes what is there, what broke, what to change, and in what
order. Written against the repositories and the registry on 2026-09-04.

---

## 1. What is there now

### 1.1 Images

| Image | Built from | Size | Last built |
| --- | --- | ---: | --- |
| `base` | `requirements-base.txt` | 1.4 GB | 2026-09-03 |
| `ml-base` | `base` + `requirements-ml.txt` | — | 2026-09-03 |
| `ci-base` | `base` + every service's requirements | **6.66 GB** | **2026-07-18** |
| `processor` | `ml-base` | 9.99 GB | 2026-09-03 |
| `crawler` | `base` | 3.41 GB | 2026-09-03 |
| `api` | `base` | 2.75 GB | 2026-09-03 |
| `migrator` | `python:3.11-slim` | — | 2026-08-28 |
| `enrichment` | `base` | — | not deployed |

Eight Dockerfiles and eight requirements files in one repository.
datadesk and the Source Directory have two Dockerfiles each and produce
images around 300 MB.

### 1.2 Three CI dialects

*As written on 2026-09-04. Superseded the next day: all three now call
the shared workflows (§3.4), and the crawler's database is `postgres:16`.
The table stands as the record of what the pattern replaced.*

| Repository | How tests get their dependencies | Database |
| --- | --- | --- |
| Source Directory | `pip install -r requirements-dev.txt` on the runner | `postgres:16` service |
| datadesk | `pip install -r requirements-dev.txt` on the runner | `postgres:16` service (added 2026-09-03) |
| MizzouNewsCrawler | pulls a prebuilt 6.66 GB image from GHCR | `postgres:15` service |

Two of the three install what the commit pins. The crawler runs its tests
inside an image built earlier, from a different commit, and that is the
only one of the three with a staleness problem.

The crawler's approach exists for a reason: spacy, nltk, torch, selenium
and trafilatura are slow to install, and five jobs installing them per
pull request would be slower than pulling the image. The cost is that CI
cannot test what a pull request pins.

### 1.3 Registries

Images are pushed to Artifact Registry and mirrored to GHCR
(`mirror-images.yml`), because pulling multi-GB images to GitHub-hosted
runners from Artifact Registry costs roughly $0.35–0.50 each in egress and
GHCR is free for the runner. The mirror copies whatever Artifact Registry
holds; it does not build.

---

## 2. What broke, and why it was not catchable

Two failures on the same branch on 2026-09-04, both structural.

### 2.1 The CI image was seven weeks old

`ci-base:latest` was built on 18 July; `base:latest` on 3 September.
Nothing rebuilds `ci-base` when `base` changes, and no check compares
them.

`lnic_contracts` was added to `requirements-base.txt` on 3 September and
`src/pipeline/review_hold.py` imports it at module scope, which most test
modules reach transitively. The image did not have it, so three jobs
produced about a hundred collection errors reading `ModuleNotFoundError`,
none of which named the cause. **PR #498 was merged with those jobs
failing.**

The local gate cannot catch this. `make test` and the pre-push hook run in
a developer's virtualenv, where the package is installed. The image is the
only place it is absent, and no local command looks at the image.

### 2.2 A pull request cannot change a pinned dependency

Rebuilding `ci-base` fixed the missing module and produced the next
failure: `module 'lnic_contracts.review_note' has no attribute
'is_answered'`. The rebuilt image carries the version
`requirements-base.txt` pinned **at merge time**, and the branch bumps it.

A pull request that adds or bumps a dependency is tested against an image
built from the previous version of the file that declares it. It cannot
pass, and no amount of local testing changes that.

The workaround was already in the repository: two test commands carried a
one-package `pip install google-cloud-firestore>=2.21.0`, added when
somebody hit the same wall with that package. One package at a time, as
each was noticed.

**Fixed 2026-09-04:** every containerised test run now installs
`requirements-base.txt` and `requirements-dev.txt` before pytest. It is a
no-op when the image is current and installs the difference when it is
not. That removes the class; the rest of this document is about not
needing it.

---

## 3. What to change

Four problems, in the order they should be addressed. The enrichment split
comes last deliberately: a fourth repository built on the current pattern
inherits all of it.

### 3.1 An image's tag should say what is in it

`:latest` cannot be stale, because nothing says what it should contain.

Tag every base image with a hash of the files it was built from —
`base:req-<sha8 of requirements-base.txt>` — and have CI resolve the tag
from the working tree rather than pulling `:latest`. A tag that does not
exist is a clear failure naming the build to run, instead of tests failing
against the wrong contents.

`Dockerfile` already takes `BASE_IMAGE` as a build argument in every
service, and datadesk already pins its base to a hash of
`requirements.txt`. The pattern exists; the crawler does not use it.

This also makes the top-up install in §2.2 unnecessary rather than load
bearing.

### 3.2 The base image is carrying other services' dependencies

`requirements-base.txt` pins spacy, nltk and selenium, so every image
built on it carries an NLP stack and a browser driver whether it uses them
or not. `base` is 1.4 GB before a service layer.

The enrichment split is the occasion to fix this: enrichment is the only
consumer of the NLP stack, so once it leaves, `base` can drop spacy, nltk
and torch, and `ml-base` becomes enrichment's own base rather than a
shared one.

Target shape:

```
python:3.11-slim
  └── base            database, storage, logging, http   (~400 MB)
        ├── crawler   + selenium, trafilatura
        ├── api       + fastapi
        ├── processor + nothing heavy
        └── ml-base   + spacy, nltk, torch  →  enrichment
```

`ci-base` then extends `base` and installs only what tests need beyond
it, rather than every service's requirements at once.

### 3.3 One requirements file per image

There are eight, and `requirements.txt` is a 50-line union of the others.
A pin can differ between the union and the per-service file, and both are
installed in different images.

Delete the union. One file per image, each including the ones it builds
on. Nothing should have to know which of eight files a package is in.

### 3.4 Three repositories should share one CI definition

The three CI configurations were written independently and agree on
nothing: how dependencies are installed, whether tests run in a container,
how the database is provided, how images are tagged, how a deploy is
triggered. A fourth repository will make it four.

GitHub reusable workflows (`workflow_call`) hold a repository's worth of
this. One repository — the contracts package is the natural home, since
both consumers already depend on it — publishes:

- `python-checks.yml` — ruff, black, isort, mypy against a named version
- `python-tests.yml` — Postgres service, dependency install, pytest
- `image-build.yml` — build, tag by requirements hash, push, mirror

Each repository's `ci.yml` becomes a short file naming the workflows and
its own parameters. The crawler keeps its container-based job, because its
dependency set justifies it; what it stops doing is defining its own
answer to every other question.

**What was built (2026-09-05).** The contracts repository publishes two
workflows, not three: `python-checks.yml` runs the stages lint →
typecheck → test → integration, each as `make <stage>` and nothing else,
with a Postgres service on the two test stages; `conforms.yml` checks
that a repository's Makefile and hook keep to that. The image-build
workflow was not needed: nothing in a pull request builds an image.

The crawler's side of it:

- `scripts/ci/<stage>.sh` is what a stage does, one file per stage. The
  Makefile runs the script on the virtualenv locally and, when
  `GITHUB_ACTIONS` is set, inside `mizzou-ci-base` through
  `scripts/ci/in-image`, which tops the image up to the commit's pins.
  Same script, same string, both places.
- `make check` is the four stages. The pre-push hook runs it on a clean
  worktree of the commit being pushed, so what reaches GitHub has
  already passed what GitHub will run.
- The virtualenv is kept at the pins by a stamp named after the content
  of the requirements files; every local stage depends on it. This
  closed the last version gap: on 2026-09-04 local lint was running ruff
  0.15.22 against a pinned 0.16.0, and nothing had said so.
- `scripts/ci/docs-only.sh` decides, for the workflow and the hook
  alike, whether a change is documentation only. A deny-list: YAML,
  workflows included, always runs the suite.
- The suites that are the crawler's alone — headful Selenium, Firestore,
  the weekly security scan and stress run — stay as jobs in `ci.yml`,
  each a make target too.

---

## 4. What the enrichment split needs

The split is sound and should happen after §3.1–3.3, not before. What it
would cost and what it would risk is measured in
[SPLITTING_ENRICHMENT.md](SPLITTING_ENRICHMENT.md).

**A repository split does not divide the images.** Enrichment currently
builds on `base` (`Dockerfile.enrichment`) while `processor` builds on
`ml-base`. After the split, enrichment owns the NLP stack and the crawler
should no longer carry it — which is only true if §3.2 is done first.

**The contract package becomes load-bearing.** Two repositories share it
today and had to be bumped by hand, in lockstep, with an image rebuild
between them; a third makes that worse. A release in the contracts
repository should open the version-bump pull request in each consumer,
rather than somebody remembering.

**The database boundary is already the hard part.** Enrichment reads
`articles` and writes `article_enrichment`; the crawler writes `articles`.
A repository boundary does not create a service boundary, and the two will
go on sharing a database — which is the same constraint the sources
migration works under (`NewsSourceDirectory/docs/sources-migration.md`
§1.2): they cannot join across databases, so the split must not assume
they can.

---

## 5. Phases

| Phase | Change | Blocked by |
| --- | --- | --- |
| 0 | **Done 2026-09-04.** Rebuild `ci-base`; top up the image with the commit's requirements before pytest | — |
| 1 | Tag base images by requirements hash; CI resolves the tag from the tree | — |
| 2 | Move spacy/nltk/torch out of `base` into `ml-base`; rebuild the tree in §3.2 | 1 |
| 3 | One requirements file per image; delete the union | 2 |
| 4 | **Done 2026-09-05.** Reusable workflows published from the contracts repository (`ci-v1`); datadesk, the Source Directory and the crawler call them | — |
| 5 | Automate the contract release and the consumer version bumps | 4 |
| 6 | Split analysis/enrichment into its own repository, on the finished pattern | 2, 4, 5 |

---

## 6. Risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Retagging base images breaks a running deploy that pins `:latest` | High | Keep `:latest` as a moving alias alongside the hash tag; change consumers one at a time. The crons are suspended, which is the cheapest condition in which to do it |
| Removing spacy/nltk from `base` breaks a service that imports them without declaring them | High | Build each service image and import every module before switching; the vendored `src/mcmetadata` already caused this once when trafilatura was missing and `MCMETADATA_AVAILABLE` silently went False |
| Reusable workflows become a single point of failure across three repositories | Medium | Version them by tag, as with the contracts package; a repository pins a tag and upgrades deliberately |
| The split lands before the base image is fixed, and enrichment inherits the NLP stack it was supposed to take with it | Medium | Phase order. §6 is last for this reason |
| CI slows down because each job installs dependencies | Medium | Phase 1 makes the top-up unnecessary; measure before and after. The current coverage job is about 4 minutes |
| GHCR mirror drifts from Artifact Registry again | Medium | Hash tags make drift visible: a tag that does not exist fails loudly instead of pulling something older |

---

## 7. What this does not cover

Runtime compute — machine types, autoscaling, the spot pool — is a
separate question from how images are built and tested, and is tracked in
the GCP cost work. The one overlap is image size: a 9.99 GB processor
image is paid for on every cold start, and §3.2 is the lever.

---

## 8. Documents this replaced

Nineteen documents described machinery that is no longer here. They were
removed rather than corrected: each one is a full account of a system
that was taken out, and half-updating them produces the worst kind of
document -- one that is right about enough to be trusted and wrong about
the part that matters. The text is in git history.

| Removed | Described | Where it lives now |
| --- | --- | --- |
| `SELECTIVE_BUILD_*` (six), `CI_CD_SERVICE_DETECTION.md`, `root-md/SELECTIVE_BUILD_README.md`, `root-md/TEAM_BRIEFING_SELECTIVE_BUILD.md` | `selective-service-build.yml`, a workflow this repository does not have | The `detect-changes` job in `build-and-deploy-services.yml`, held to what each Dockerfile copies by `tests/test_deploy_filters_match_the_dockerfiles.py` |
| `BASE_IMAGE_MAINTENANCE.md`, `BASE_IMAGE_QUICKSTART.md`, `ML_BASE_IMAGE_ARCHITECTURE.md` | rebuilding `:latest` by hand with `docker build`, and when to decide to | `base-images.yml`: an image is tagged with a hash of its contents, a child's hash includes its parent's tag, and a tag that does not exist is built. Nobody decides |
| `CI_OPTIMIZATION_ANALYSIS.md`, `CI_OPTIMIZATION_COMPLETE.md`, `TESTING_STRATEGY.md` | pytest invocations and their flags, per job | The four stages, each a make target, in `python-checks.yml@ci-v1`. §3.4 |
| `CI_CD_ENFORCEMENT.md` | `tests/test_sitecustomize_integration.py`, which is not in the repository | -- |
| `DEPENDENCY_SUBMISSION_OPTIMIZATION.md`, `DEPENDENCY_SUBMISSION_SUCCESS.md`, `DISABLE_AUTOMATIC_DEPENDENCY_SUBMISSION.md` | GitHub's automatic `dynamic` submission, and turning it off (October 2025) | `dependency-submission.yml`, which is explicit, runs weekly, and is the only job here that pip-installs on a runner |

The pattern in all five rows is the same: a document written to announce
a system, and nothing that failed when the system left. A test fails when
what it asserts stops being true; a document does not, which is why the
ones that matter here are short and the assertions are in `tests/`.

---

## Sources

- Artifact Registry image list, `mizzou-crawler` repository, 2026-09-04.
- `.github/workflows/ci.yml` in all three repositories, 2026-09-04.
- Build failures: MizzouNewsCrawler PR #498 (merged red) and PR #499.
