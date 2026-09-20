# Data enters the pipeline at a named point

Three shapes of data now arrive: a **source** to crawl, a **list of URLs**
somebody selected, and a **full record** that already carries headline, byline,
body text and a date. They enter at different stages, and each one skips work
the later stages assume was done.

The pipeline is already a status machine, so there is a coordinate system to
enter at:

```text
candidate_links.status   discovered -> article -> extracted | paywall
                                              | not_article | refetch | error
articles.status          extracted -> cleaned -> labeled -> enriched
                                                         | enrichment_skipped
```

`EXPORTABLE_STATUSES = ("enriched", "enrichment_skipped")` is the far end. A
record admitted at any point has to be able to reach it without a later stage
discovering that its precondition was never true.

## Native downstream, independent upstream

That is the whole requirement, and both halves are load-bearing.

**Native downstream.** A record admitted at any point must look, to every later
stage, exactly like one that walked the whole path. No stage should have to ask
how a record arrived, and none should carry a branch for it. If enrichment,
export, review or a visualisation has to special-case ingested rows, the entry
point did not finish its job.

**Independent upstream.** An entry point owes nothing to the stages before it and
must not be made to pretend it ran them. An ingested URL was selected by a
person, so `storysniffer` — a discovery-stage guess at whether a URL looks like
an article — has no standing over it, and neither does the MediaCloud wire
check. Running them anyway does not add safety; it can only remove records the
study was defined to contain.

**What connects the two: an entry point's admission checks are the
postconditions of the stages it skips.** That is what makes "native" checkable
rather than aspirational. Enter at `cleaned` and you are asserting, on behalf of
extraction and cleaning, that the body is prose rather than furniture, the
masthead is off the headline, the byline is parsed rather than raw, and the wire
question is settled — because those are the guarantees the next stage is entitled
to assume.

Derive the list, do not compose it. When a stage gains a postcondition, every
entry point downstream of it gains an admission check, and that is a mechanical
consequence rather than a judgement call. Note the asymmetry: skipped
*preconditions* are free (that is what independent-upstream means), skipped
*postconditions* must be asserted (that is what native-downstream costs).

## There is no other way in

Every ingestion is structured against a named entry point. Not a script, not a
notebook, not a hand-written `INSERT`, not a one-off importer written for one
dataset and left in the tree.

This is the rule because the alternative is what we already have. The corpus
contains 4,793 curated links across two datasets that arrived through ad hoc
paths, and the consequences are the ones above: a `wire_check_status` default
nobody chose, a bypass recorded on some rows and inferred for others, and no
record of who asserted what. Each importer was reasonable on its own day. The
cost is that there is no single place to add a check when a stage gains a
postcondition, so a new invariant has to be retrofitted into however many
importers happen to exist — and the one that gets missed fails silently, because
every failure mode in this pipeline is a plausible-looking default.

A new shape of incoming data is a new entry point: required fields, checks
derived from the stages it skips, a dispatch target, and the report below. It is
not a script that writes rows and moves on.

What this forbids, concretely:

- writing to `candidate_links` or `articles` from anywhere but the ingestion
  services — the golden path included, since the golden path is a composition of
  those services and not a privileged caller
- an ingestion CLI command that contains its own insert rather than wrapping a
  service
- admitting a record at a status whose preconditions were not checked, on the
  grounds that the caller says they are fine

Measured 2026-09-20. Every writer of those two tables is outside the services
layer, and **each entry point below already exists as its own independent
implementation**:

| writer | what it is | entry point |
| --- | --- | --- |
| `src/cli/commands/extraction.py` | the golden path | crawled |
| `src/cli/commands/extraction_backup.py` | a 452-line stale copy of it | — |
| `scripts/import_warc_minnesota.py` | ORM inserts from a WARC | a WARC |
| `scripts/import_manual_articles.py` | raw SQL from a TSV | a sheet |
| `scripts/import_wsu_notebook_labels.py` | a dataset-specific importer | — |

None is in `src/services/`. Three are one-off scripts named after the dataset or
the file they were written for, which is the tell: the name records the occasion,
not the contract. `warcio` is already a declared processor dependency for
"historical data ingestion", so the WARC path is not hypothetical — it is
production capability living in a script called `import_warc_minnesota.py`.

The backup copy is the rule's own argument: a second implementation of the write
path that no longer matches the first and that nothing tests.

An earlier version of this table listed four writers, from grepping `INSERT
INTO`. That missed the WARC importer, which writes through the ORM
(`session.add`). Worth recording, because it is the same lesson at a smaller
scale: a convention enforced by one spelling of one pattern is not enforced.

The prohibition is testable and should be tested: no `INSERT INTO
candidate_links` or `INSERT INTO articles` outside `src/services/`, asserted the
way the other structural invariants in this repository are. An unenforced
convention is the same as no convention — three ordering bugs shipped in one day
on 2026-09-20 precisely because nothing pinned the order they depended on.

## Why silence is the failure mode

Every entry point that exists today fails open, and each one has already cost
something:

- **A default that blocks.** `candidate_links.wire_check_status` is `NOT NULL
  DEFAULT 'pending'`, and `pending` is the one value the enrichment selector
  excludes. An ingested URL that skipped the wire check inherited the default
  and stopped short of the export — 154 WSU rows sat there on 2026-09-20.
  Skipping a check is not the same as having no opinion about it; the bypass has
  to write an affirmative value (`local`), and say who authorised it.
- **An insert that no-ops.** `ARTICLE_INSERT_SQL` ends `ON CONFLICT DO
  NOTHING`. Re-submitting a record is silently a success that changed nothing.
  An API that reports 200 for that is lying by omission.
- **Two entry points drifting.** `handle_extract_url_command` never calls
  `record_extraction`, while `_process_batch` does. One stage, two callers, one
  of which quietly lost a step. Nothing detected it because both "worked".

So an entry point states what it skipped, asserts the value the skipped stage
would have written, and reports what it actually did.

## The four entry points

Required fields are the context; checks are derived as above; dispatch is what
happens next and is part of the contract, not an afterthought.

### A source

| | |
| --- | --- |
| enters at | before discovery |
| requires | host, publication name, dataset |
| optional | state, county, paywall fields, login URL and credentials, alternate domains |
| skips | nothing |
| checks | host resolves; not already present under a www/bare variant; not on the never-crawl list |
| dispatch | discovery |

The required set is deliberately small, because a source with a host and a name
can be crawled and everything else can arrive later. The optional fields are not
decoration, though — several change behaviour the moment they are present, so an
endpoint that accepts them silently changes what the pipeline does:

- `requires_login` plus credentials moves the host into the authenticated worker
  pool and out of the anonymous one. A host that needs a login and has no
  credentials is claimable by neither, so it is fetched by nobody — a hole the
  entry point should name rather than create.
- `alternate_domains` is the dataset owner's declaration, never inferred, and it
  decides whether a cross-domain canonical URL reads as wire.
- `has_paywall` and `subscription_cost` are descriptive; `requires_login` is the
  one that means "seven automated logins".

The never-crawl list is a real constraint, not hygiene: `lynnwoodtoday.com` left
publisher control and serves gambling spam, and `mltnews.com` does not resolve.

### A list of URLs

| | |
| --- | --- |
| enters at | `candidate_links.status = 'article'`, `is_curated = true` |
| requires | URLs, dataset, who selected them |
| skips | discovery, URL verification, the MediaCloud wire check |
| checks | URL parses and is http(s); host maps to a known source in the dataset; not a duplicate link |
| dispatch | extraction, through the work queue |

This one is built. Uploading a set of URLs is an affirmative decision to collect
them, so selection **is** the filter and the verdicts of URL verification and
the wire check can only remove records the study was defined to contain. The
bypass is recorded per record — `candidate_links.is_curated`, backfilled from
`discovered_by` — because a dataset holds both kinds: WSU-Washington-State has
2,681 ingested links and 6 crawled, Mizzou-Missouri-State 234,784 crawled and
2,112 ingested (measured 2026-09-20). A dataset-level flag would be wrong in
both directions.

### A WARC file

| | |
| --- | --- |
| enters at | HTML already captured, nothing parsed |
| requires | the WARC, dataset, and a declaration of how its URLs were chosen |
| skips | discovery and **the fetch** |
| checks | response records only; `text/html`; original status 200; URL maps to a source in the dataset; capture time is not read as a publish date |
| dispatch | parse-only extraction — **never the work queue** |

A WARC is the fetch already done by somebody else, which is the architecture's
own "fetch once, parse many" with the fetch outside our process. The seam exists:
`extract_content(url, html=...)` runs the whole cascade — mcmetadata,
newspaper4k, BeautifulSoup — against supplied HTML and performs no fetch of its
own. So a WARC record is parsed by the same code that parses a live capture,
which is what makes its output native rather than a parallel path.

Three things make it distinct from the other entry points:

- **It must not be re-fetched.** Extraction otherwise goes through the work
  queue, and a worker fetches. A WARC record's body is the evidence; going back
  to the live site would silently replace a 2019 capture with today's page, or a
  410. Parse-only dispatch is not an optimisation, it is the point.
- **It carries its own `http_status` and headers**, authoritatively, from the
  capture. That is better provenance than a live fetch gets, and it is exactly
  the field the browser path only just began recording correctly.
- **`WARC-Date` is the capture time, not the publish date.** Conflating them
  would date every article in an archive to the day it was archived, and the
  study period is defined on publish date.

**How its URLs were chosen is a declaration, not an inference.** A WARC built by
capturing a hand-picked list is curated — selection was the filter, so
`storysniffer` and the wire check have no standing. A WARC from a broad crawl is
not, and its non-article URLs have never been filtered by anything. The same
distinction the corpus already draws per record with `is_curated`, drawn again
here, because the file itself cannot tell us which it is.

### A full record

| | |
| --- | --- |
| enters at | `articles.status = 'cleaned'` (candidate link at `extracted`) |
| requires | host, URL, dataset, headline, body, publish date, byline, provenance |
| skips | discovery, verification, the wire check, the fetch, extraction, cleaning |
| dispatch | enrichment — or the review queue when a check is ambiguous rather than failing |

**This one already exists, ad hoc, and that is the reason for the doc.**
`scripts/import_manual_articles.py` takes a TSV of URL / title / date / author /
body and writes both rows itself. It independently chose the same coordinates
derived above — `candidate_links.status = 'extracted'`,
`articles.status = 'cleaned'`, `wire_check_status = 'local'` — which is good
evidence the shape is right. What makes it ad hoc is everything around that:

- it is `kubectl cp`'d into a running pod to be used, per its own docstring
- it does not set `is_curated`, so its bypass is inferable from `discovered_by`
  rather than asserted on the row
- it dispatches nothing. The docstring ends by telling the operator to go and
  run `analyze --batch-size 50` by hand afterwards.
- its checks are its own, so a postcondition added to cleaning does not reach it

It skips the most of any entry point, so it owes the most:

- **body** is prose of a plausible length, not a teaser, not furniture, not a
  ROT47 payload (TownNews serves paywalled text ROT47-encoded; the signature is
  `k^Am`). 158 articles are already enriched under 200 characters because
  nothing gated length.
- **headline** does not carry the masthead. The structured-data title branch
  wins over `titles.from_html`, so the publication strip never ran and the tail
  arrived in stored headlines.
- **byline** is parsed into names, not a raw credit line, and a byline naming a
  different publication is a syndication signal rather than an author.
- **publish date** is present and plausible; a missing date is not a null to
  shrug at, it decides what a study period contains.
- **wire and CIN status** are set explicitly. Not defaulted — see above.
- **language** is known, because `non_english` is a terminal status downstream.

Ambiguity goes to review rather than to a rejection or a shrug. A body that is
short but plausibly a brief is exactly the case a person should see, and the
review queue already models dispositions as status rewinds.

## Which gates each entry point runs

Authoritative. Two rules produce it, and the second is the one that matters.

**Rule one: an entry point skips the STAGES it is upstream-independent of.**
Everything else runs.

| entry point | requires | skips | runs |
| --- | --- | --- | --- |
| sources | — | nothing | all gates |
| a WARC | sources admitted first | discovery, crawling | all other gates |
| a URL list | sources admitted first | discovery | crawl/extract, then classify and enrich |
| a spreadsheet | sources admitted first | discovery, crawl/extract | classify and enrich |

**Sources are always admitted first.** The other three tie records to sources, so
a row whose host has no source is rejected and reported — the caller admits the
publishers through the source endpoint, then re-submits. An endpoint for URLs
does not quietly register publishers as a side effect, because that would
register them without any of the source endpoint's own checks.

**Rule two: within a stage it runs, a gate is skipped when the caller SUPPLIED
the value that gate would have produced.**

This is what makes the matrix small. A gate exists to produce or validate a
field; if the field arrives in the payload, the gate has nothing to produce and
the caller has asserted the postcondition. So:

- a URL list with no byline column gets the full extraction and parse, byline
  cleaning included, because the byline is coming out of HTML and arrives as a
  raw credit line
- the same URL list **with** a byline column skips byline cleaning, because the
  byline was given rather than parsed
- a spreadsheet skips crawl/extract entirely for exactly this reason, generalised
  across several fields at once: headline, body and date are all supplied

What a supplied value costs: it is accepted as already satisfying the gate's
postcondition, so its **shape** is checked on admission even though the gate does
not run. A supplied byline must be parsed names, not `QUESTEN INGHRAM Yakima
Herald-Republic`. Accepting a raw credit line under a column called `byline`
would put differently-shaped data in the same field, and every downstream
consumer would need a branch — which is precisely what native-downstream forbids.

### The one gate that has to be split first

`BylineCleaner.clean_byline()` does two jobs in a single call: it normalises a
raw credit line into names, and it decides `is_wire_content`, which the caller
then reads as a wire signal. The rules above need those separable — a curated URL
list may need its byline normalised while the wire inference has no standing over
it, since selection was the filter.

So byline handling is two gates, not one:

| gate | produces | skipped when |
| --- | --- | --- |
| byline normalisation | names, from a credit line | a byline was supplied |
| byline wire inference | `is_wire_content` | the records are curated |

That they are currently one function is not a detail — it is the concrete example
of why the gates have to be callable alone before any of this can be wired.

## A rewind is an entry point

When a review decision rewinds an article, it demands whichever gates are
downstream of the status it was rewound to. That is the same sentence as the one
governing ingestion, and it should be the same code.

So the gate catalogue is **indexed by status**, and there is one question with
three callers:

| caller | asks |
| --- | --- |
| an entry point | which gates are downstream of the status I am admitting at |
| a review rewind | which gates are downstream of the status I am rewinding to |
| the golden path | all of them, in order |

The golden path is then not privileged. It is the case where the answer happens
to be "everything", which is why it must not be the only place the gates are
composed.

Two things this constrains:

**A rewind must not re-run what is upstream of it.** Rewinding to `cleaned` must
not re-fetch: the bytes are not in question, the judgement about them is. This is
the same prohibition the WARC path has, for the same reason — and the same trap,
because extraction normally goes through the work queue and a worker fetches.
`refetch` is the deliberate exception: it rewinds the *link* precisely because the
capture IS what is in question, and it is a different operation from a review
rewind even though both are status changes.

**A gate must respect an answer it has already been given.** Otherwise the row
returns to review on the same defect forever: a reviewer says the byline is
correct, the row rewinds, byline cleaning holds it again, and the queue never
drains. `review_hold.apply_hold` already models this — it takes the first defect
*a person has not already answered* as the claim, and a row with two wrong fields
is one question, the second asked once the first is decided. That behaviour is
the reason a gate's contract has to say what it writes on failure, not just what
it checks: the note is what a later run reads to know the question was settled.

Which makes the `apply_hold` finding worse than an oversight. The gate that holds
a row and the gate that respects the answer are the same function, so the golden
path neither holds rows nor would honour a disposition if something else held
them.

## The gates are the reusable unit, and they must be callable alone

The principle above only works if the checks are things you can *call*. If a
gate exists only as a stretch of code inside a stage's loop, every entry point
that owes it has to reimplement it — which is precisely what the import scripts
did, each inventing its own validation for the same invariants.

So each stage declares its gates, and each gate is a named predicate with a
documented contract: what it checks, what it presumes was already true, what it
writes when it fails, and which entry points owe it. A gate takes data and
returns a verdict. It does not know whether it was called by the crawler, by a
WARC unpacker, by an ingestion endpoint or by a test.

**Modular is not the same as wired, and we have the proof.** `src/pipeline/
review_hold.py` is already exactly this: `field_defects()` and `apply_hold()`,
pure functions, no pipeline knowledge, easy to test. And `apply_hold` has ONE
call site — inside `handle_extract_url_command`, the path used to run a single URL
by hand. `_process_batch`, the path that extracted the entire corpus, never calls
it. Measured 2026-09-20: production holds **6** rows at `in_review` against
~260,000 candidate links.

Nothing was broken. The module is fine, its tests pass, and the golden path runs
green. The gate was simply never composed into the path that matters, and no test
could notice because no declaration says which gates that path owes.

Hence the enforceable half: a stage declares its gate list, and a test asserts
the stage's implementation actually runs every gate it declares. That is what
would have caught the review hold, and it is what keeps the entry points honest
as gates are added.

**Why this is the testing strategy, not an aside.** The filtering here is
genuinely complicated — wire detection has three separate defects on record,
content-type detection distinguishes e-editions from articles, the byline
cleaner, the masthead strip, the paywall and ROT47 body checks, storysniffer, the
length gate, the language check, duplicate curation. Testing four entry points
against all of that combinatorially is not feasible. Testing each gate once in
isolation, then asserting composition per stage and per entry point, is. The
alternative is what the corpus already shows: the same invariant validated
differently in five places, and the sixth place that forgot.

Each gate therefore needs its own documentation — not a docstring describing the
code, but a statement of what it presumes and what it guarantees, because that is
the text an entry point reads to work out what it owes.

## Dispatch is part of the contract

An entry point that admits records and then waits for a cron is the current
behaviour and it is wrong for on-demand ingestion — the crons are suspended, and
a caller who has just handed us 300 URLs should not have to know that.

Three dispatch targets, chosen by what the data needs next:

| target | when | how |
| --- | --- | --- |
| the work queue | the records need fetching | they are claimable the moment they are `article`; a worker asks |
| parse-only extraction | the bytes are already in hand (a WARC) | `extract_content(url, html=...)`, no fetch, no queue |
| an Argo workflow | the records need a stage run now | submit `news-pipeline-template`, always with `--dataset` |
| the review queue | a check was ambiguous | a hold, expressed as a status rewind |

Extraction only ever goes through the work queue: one domain per worker per
request, at most three articles, a sixty-second cooldown. An ingestion endpoint
must not fetch on the request thread, and must not hand-roll a job.

## Where the code goes

The stage logic belongs in `src/services/<stage>.py`, and the CLI command, the
Argo step and the API route are all thin wrappers over one call. Several stages
already look like this — `url_verification`, `classification_service`,
`wire_detection`, and `refetch`'s `mark`/`clear`/`spend_attempt`/`give_up`. Two
do not:

- **enrichment** — per-article work is in `src/enrichment/`, but the batch loop,
  the spend ceiling and the submit-order persistence that makes an interrupted
  run keep what it paid for all live in `src/cli/commands/enrichment.py::_process`.
  Nothing else can enrich a subset without reimplementing that durability
  guarantee.
- **login verification** — `witness` and `record` are plain functions with clean
  signatures, but they live in `src/cli/commands/validate_login.py` and nothing
  outside that module imports them. There is no HTTP surface, so a verify button
  has nothing to call.

Ingestion itself goes in `src/services/ingestion/`, one module per shape, each
declaring its required fields, its derived checks and its dispatch, and calling
the same stage services the golden path calls. The golden path is then one
composition of those services rather than the only way to reach them.

## What every entry point reports

Not an exit code and not a bare 200:

| field | says |
| --- | --- |
| `accepted` | rows created, by status |
| `duplicate` | rows that already existed — the `ON CONFLICT DO NOTHING` case, named |
| `rejected` | which record, which check, what value |
| `held` | rows sent to review, and why |
| `dispatched` | what was enqueued or submitted, with the workflow name |

## Open

- **Idempotency key for a full record.** URL alone is wrong: a record can
  legitimately be re-ingested with corrected text. A submission id from the
  caller, or a content hash, decides whether a second POST is a duplicate or a
  correction.
- **Who may assert a bypass.** `is_curated` records that selection happened, not
  who selected. A full-record ingest asserts far more and needs an identity on
  the record, not just on the request.
- **Whether `cleaned` is the right entry status for a full record**, or whether
  it wants a status of its own so that "we were given this" is never confused
  with "we cleaned this".
