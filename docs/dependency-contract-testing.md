# Dependency contract testing

## Why

Two production incidents proved that mocked unit tests cannot catch dependency
regressions:

- **transformers 5.x** removed `return_all_scores`; the classifier pipeline
  silently degraded to `top_k=1` and article classification failed on every
  batch for a day. The mocked tests **asserted the dead argument** and stayed
  green.
- **trafilatura 2.x** changed `bare_extraction()` from returning a dict to a
  `Document` object. The vendored mcmetadata extractor subscripts the result,
  so the trafilatura path — cascade step 1, the best extractor — threw
  `'Document' object is not subscriptable` on every article and the cascade
  silently fell through to lower-quality fallbacks.

Both bumps arrived via routine floor-only requirements (`>=x.y`) resolving to
new majors at image-build time.

## Policy

**Dependencies are not pinned to avoid staleness; they are tested to avoid
breakage.** Dependabot (and manual bumps) may propose any version. The gate is
the *contract test*: an unmocked probe of the exact calls `src/` makes into
that library. Green contract = evidence the bump is safe. Red contract = the
PR fails visibly instead of production failing silently.

When adding a new dependency (or a new call surface into an existing one),
add/extend its contract in `tests/dependency_contracts/`.

## Where they run

1. **Regular CI / pre-push hook** — against the current venv. Catches drift
   when the local/CI environment resolves new versions.
2. **Image Build Check (`cloudbuild-pr-image-check.yaml`)** — inside each
   freshly built image (`contracts <image>` helper). This is the venue that
   matters for a requirements PR: it is the only place the bumped versions
   actually exist, because regular PR CI runs inside prebuilt images.

Tests skip cleanly when a venue lacks a resource (Chrome outside the crawler
image, the model checkpoint outside ml-base/processor, spacy/nltk data), so
the same suite runs everywhere.

## Coverage map

| Module | Dependencies | Contract |
| --- | --- | --- |
| `test_ml_stack.py` | torch, transformers, storysniffer→scikit-learn, spacy, nltk | production checkpoint load + `predict_batch` shape; raw pipeline `top_k=None` returns all scores per text; skops model load + `.guess()`; spacy model + NER; nltk tokenize |
| `test_extraction_stack.py` | trafilatura, newspaper4k, readability-lxml, goose3, boilerpy3, htmldate, dateparser, py3langid, bs4/lxml/soupsieve, tldextract, furl, url-normalize | `TrafilaturaExtractor` normalizes dict/Document shapes (both metadata modes); newspaper parse from preset HTML incl. `.html` assignment; cascade fallbacks extract the fixture body; date finding/parsing; offline PSL parsing |
| `test_browser_stack.py` | selenium, undetected-chromedriver, selenium-stealth, cloudscraper | Chrome options flags surface; real headless Chrome boot + `page_source` (crawler image); `create_scraper()` construction |
| `test_data_stack.py` | pandas, numpy, pyarrow, feedparser, rapidfuzz, warcio | groupby/agg/`to_dict(records)`/`read_csv`; parquet roundtrip; RSS entry parsing; fuzzy match; WARC write/read roundtrip |
| `test_api_stack.py` | fastapi, pydantic | TestClient route roundtrip; pydantic v2 validate/dump + coercion |

Not duplicated here: sqlalchemy/psycopg2/alembic (covered by the PostgreSQL
integration suite), requests/proxy stack (covered by the proxy smoke suite).

## Testing the tests (mandatory before pushing contract changes)

The binding venue for contracts is *inside the built images* — repo-layout
local runs do not prove venue correctness (mount depth, upload manifest,
baked env vars all differ). Five CI cascades were burned learning this.

**Run `scripts/test_contracts_local.sh` before pushing any change to
`tests/dependency_contracts/` or the contracts() wiring.** It reproduces the
Cloud Build execution exactly: stages the suite from the real
`gcloud meta list-files-for-upload` manifest (catches .gcloudignore holes),
mounts it at `/contracts` read-only (catches path assumptions), and runs the
identical pytest invocation inside real images (catches baked-env
mismatches). ~1 minute after the one-time image pull; $0.

## Handling a red contract

1. Read the failure — it names the call site and the changed behavior.
2. Prefer **fixing forward** (adapt our call, as `TrafilaturaExtractor` now
   normalizes both return shapes) over pinning.
3. Pin (`<next-major`) only when fixing forward is a real migration that
   deserves its own PR — and leave the contract in place; it becomes the
   evidence gate for removing the pin later. Update the pin's comment to say
   which contract governs it.
4. Never merge a requirements bump whose Image Build Check contracts did not
   run (e.g. auth failure) — a skipped gate is not a green gate.
