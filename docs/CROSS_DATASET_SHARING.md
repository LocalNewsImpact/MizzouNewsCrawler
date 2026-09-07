# Sharing one extraction across datasets

Deferred. Nothing in this document is built. It records a design decision
taken on 7 September 2026 and the measurements behind it, so the shape is
settled before anyone writes the migration.

The idea: when a URL is discovered under more than one dataset, extract it
once and let the second dataset adopt the existing record rather than
fetching and parsing the same page again.

---

## 1. What the pipeline does today

Discovery writes one `candidate_links` row per (URL, dataset). Extraction
reads a candidate link and writes one `articles` row pointing back at it
through `articles.candidate_link_id`, which is one-to-one.

So a URL discovered under two datasets produces two candidate links, and
extraction — which reads candidate links, not URLs — fetches the page
twice and writes two article rows. Two fetches, two parses, two rows,
one page.

This is not currently happening. Measured against production on
7 September 2026:

```
URLs appearing under more than one dataset          0
candidate_links rows                          262,137
  with a dataset_id                           258,815
datasets                                            4
```

The four datasets are geographically disjoint — Missouri, Vermont,
Washington, the Lehigh Valley — and no publisher in one appears in
another. The duplicate case is real in principle and absent in fact.

That is why this is deferred rather than built: there is nothing to
deduplicate yet.

## 2. Why it matters later

Two datasets covering overlapping geography is the ordinary case as soon
as one is added that is not defined by state. A national wire-service
dataset, a topic dataset, a second university's Missouri project — any of
these overlaps an existing one, and every overlapping URL is then fetched
twice.

The cost is not only compute. A second fetch is a second request to the
publisher from the same egress, against sites that already rate-limit and
bot-block. Deduplication reduces the pipeline's footprint on publishers
it is trying not to antagonise.

## 3. The decision the design turns on

`articles.candidate_link_id` is one-to-one. Adoption means one article
reached from *many* candidate UUIDs, one per dataset that discovered it.

That is the whole of the change. Everything else follows: skip the fetch
when a candidate's URL already has an article, count the article in both
datasets' corpora, export it once per dataset that claims it.

Two ways to express it, and the choice is not obvious:

**A join table** — `article_discoveries (article_id, candidate_link_id)`.
Additive; `articles.candidate_link_id` can stay as the first discovery
for as long as anything still reads it. Every consumer that wants "which
datasets is this article in" joins one more table.

**Invert the FK** — drop `articles.candidate_link_id`, put `article_id`
on `candidate_links`. Each discovery names the article it resolved to,
null until extraction. Fewer tables, but it rewrites the direction every
existing query reads, and there are many.

The join table is the smaller change and the reversible one. Recommended
on that basis, not on elegance.

## 4. What is already in place for it

Two properties of the current schema make adoption cheaper than it would
have been, both landing in the same change as this document:

- **Extraction telemetry records the candidate UUID.** Before, a row
  named only an `article_id` minted before the fetch — which refers to
  nothing when the extraction yields no article, as it does for 156,712
  of 315,631 rows. Recording `candidate_link_id` means "which discovery
  did this work belong to" survives whether or not an article resulted,
  which is exactly the question a shared extraction raises.

- **`articles` has no `dataset_id`.** This reads as a gap today —
  reaching an article's dataset needs a join through its candidate link.
  Under adoption it is correct: an article shared by three datasets must
  not carry one of them as a column. The datasets reach it through their
  own discoveries.

## 5. Where telemetry sits

Telemetry records **who did the work**, not who consumes it.

If one extraction is shared by three datasets,
`extraction_telemetry_v2.dataset_id` still names the single dataset whose
job fetched and parsed the page. The column stays scalar and stays true.
Adoption is a property of the record, not of the run that produced it,
and belongs on the join table in §3.

A per-dataset activity view is therefore unaffected by this design: the
dataset that ran the extraction is the one whose live log shows the work,
and the adopting dataset shows a discovery that resolved without a fetch.

## 6. What would have to be decided before building

- Whether an adopting dataset re-runs the per-dataset stages. Wire
  checking and CIN labelling are judgements about local relevance, and
  local to Missouri is not local to Vermont. The body is shared; the
  labels probably are not.
- What the review queues show when two datasets disagree about a shared
  article's disposition.
- Whether the BigQuery export emits one row per article or one per
  (article, dataset). The March reconciliation treats a row as belonging
  to one corpus.

None of these has an obvious answer, which is the second reason to defer:
the schema change is small and the policy questions attached to it are
not.
