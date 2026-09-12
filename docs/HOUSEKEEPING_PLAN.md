# Housekeeping: what went wrong, and the path to something that works

## The goal, restated

A record whose status a review queue rewinds must be carried through the
rest of the pipeline to its terminal status, daily, whether or not the
production crons are running. Only those records. Cost attributed by
dataset.

That is the whole of it, and it was stated three times before being met.

## What exists

| piece | state |
|---|---|
| reconciler (`datadesk`, `reconcile_queues`) | **works** — sets statuses from dispositions; ran once, 545 changes, 161 articles retracted; scheduled 02:30 UTC |
| housekeeping workflow (`k8s/argo/housekeeping-workflow.yaml`) | **built wrong** — stages select by status and take the whole backlog; suspended |
| geoids BigQuery sync | fixed — filters on status like the other three |
| `extraction_method` quoting | fixed — the Selenium escalation can see 1,126 sources instead of 32 |

## The flaws

### Structural

**1. Housekeeping was built from the pipeline's shape, not the requirement.**
Every pipeline stage selects by status. Housekeeping inherited that. But a
rewound record shares its status with the whole backlog, so a stage told
nothing takes everything: a run began extracting 4,802 links when the
dispositions accounted for 45. Status cannot express identity, and identity
is the requirement.

**2. The two halves have no contract.** The reconciler knows exactly which
records it moved and writes them to the console's audit log. Housekeeping,
in the crawler, cannot read that database. Two repositories, one feature,
no handoff. A file passed between pods was proposed to bridge it, which is
working state outside the database and disagrees with it the moment a run
dies halfway.

**3. The scope rule was applied where it cost money and nowhere else.**
Enrichment was guarded because it spends. Extraction and classification
were left sweeping because they are "free." They cost publisher requests
and Selenium minutes on records nobody asked about. Cost was the wrong
test.

### In the reconciler

**4. It plans by change, not by record.** Two articles matched two rules;
both said `not_article`, so no harm. Had they disagreed, the last rule
would have won silently. The doc says "must not act on a disposition it
cannot explain" and the code does not enforce it.

**5. Rules are hardcoded in one repository.** `lnic_contracts.discovery_verdict`
is the pattern that works: one definition, both sides read it. Reconciliation
rules live in `datadesk/review/reconcile.py`, so adding a disposition is a
code change in one repo that the other cannot see.

**6. The 142 refused articles are reported nightly, forever.** A list nobody
reads. Most are one diagnosis -- fetched without a browser, never with one
-- and could be a stage rather than a log line.

### In the schedule

**7. A 30-minute gap is not a dependency.** Reconciler at 02:30, housekeeping
at 03:00. The first reconciler run took 1m47 on 545 changes and will grow.
Housekeeping fires whether or not the reconciler finished, and whether or
not it produced anything. (Batching nightly is right; what is missing is
housekeeping checking whether there is anything to do.)

### In the process that built it

**8. Pieces were verified; the path never was.** Seven production failures,
each with passing unit tests behind it. Tests asserted that a file contained
a string, not that a reviewer pressing Submit changed the map.

**9. PRs were opened with the gap written in the body.** "Submitting does
not yet reach a map" is a reason not to open the PR, not a caveat to ship
with.

**10. Inference where the data had the answer.** `extracted` as an article
status; paused articles split by text length when `pause_reason` is a
column; "registration wall" when it was a JavaScript shell. Each fell apart
on reading the actual capture or code. `docs/PIPELINE_STATES.md` now exists
because it should have from the start.

## The design

One table, in the crawler, says which records owe work:

    pipeline_rework
      record_type    'candidate_link' | 'article'
      record_id
      stage          'extract' | 'classify' | 'enrich'
      reason         the disposition, in words
      requested_by
      requested_at
      done_at        NULL while outstanding
      outcome

- **The reconciler writes it** when it rewinds a record, through the same
  audited `CREATABLE` boundary `ArticlePlaceManual` uses. One row per
  record per stage; a duplicate request is the same request.
- **Every housekeeping stage reads it and nothing else.** `extract --rework`,
  `analyze --rework`, `enrich backfill --rework`. An empty table means
  nothing to do -- never "everything."
- **A stage closes the rows it handled**, with an outcome. "What is left" is
  `WHERE done_at IS NULL`; "what did housekeeping do last week" is the rest.
- **The workflow runs nightly, and does nothing if nothing is owed.**
  Overnight batching is the right cadence -- a disposition does not need
  carrying within the hour, and a run per change would be noise. Its
  first step counts outstanding rows and exits if there are none, so an
  empty night costs a few seconds.

- **It has to finish before the 07:00 UTC BigQuery sync**, or the night's
  work publishes a day late. The chain is: reconciler 02:30 (~2 min) →
  housekeeping 03:00 → extract → classify → enrich → `enriched` by 07:00.
  So housekeeping keeps its 03:00 start and gets an
  `activeDeadlineSeconds` of three hours: better to stop at 06:00 with
  rows still open -- tomorrow's run takes them -- than to overrun the sync
  with a run still going. The volume makes this realistic: with `--rework`
  a run is bounded by that night's dispositions, tens of records, not the
  4,802-link backlog that made the first run take hours.

The 142 refused extractions get a stage of their own: `stage='fetch_with_browser'`,
which the extraction step handles with Selenium. The diagnosis for most of
them is exactly "never rendered," and a row with that stage is an
instruction rather than a report.

## The development path

Each step has the test that proves it, and the test is written first.

| # | step | repo | proves |
|---|---|---|---|
| 1 | `pipeline_rework` table | crawler | migration applies and downgrades on real Postgres |
| 2 | `extract --rework` reads it, settles rows | crawler | with rows, only those links are selected; with none, nothing is; settled rows are closed with an outcome |
| 3 | `analyze --rework` likewise | crawler | same three, on articles |
| 4 | `enrich backfill --rework` | crawler | same three; `enrich run` is never invoked by housekeeping |
| 5 | workflow: every stage `--rework`, first step exits on empty | crawler | manifest test: no stage runs a bare sweeping command; the guard step exists |
| 6 | reconciler writes rework rows | datadesk | a disposition that rewinds produces a row naming the stage; one that reaches terminal produces none |
| 7 | reconciler plans by record, refuses conflicts | datadesk | two rules disagreeing on one record → skipped and reported, not last-wins |
| 8 | **end to end** | both | disposition → reconciler → rework row → stage → terminal status, on the test databases |
| 9 | `fetch_with_browser` stage for the refused | crawler | a `null_text` article gets a rework row for that stage, not a log line |
| 10 | rules to `lnic_contracts` | contracts, both | one definition read by both repos |

Steps 1–5 are one crawler PR. Steps 6–7 are one datadesk PR. Step 8 is in
both. Steps 9–10 follow.

Nothing is applied to the cluster until step 8 passes. The CronWorkflow
stays suspended until then.

## What this does not change

The reconciler's rules and their results stand. The 545 changes were
correct; the 161 retractions were what the queues said. What was missing
was everything after: the carrying.
