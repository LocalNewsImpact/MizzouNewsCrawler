# Every exclusion says who made it, and can be checked

More is thrown out of the corpus than kept, and almost none of it can be
inspected. Measured on 2026-09-07, against March 2026 Mizzou -- the only
window whose data is cleaned, so the only one worth counting:

```
enriched                       12,962   kept
--------------------------------------------
wire                            9,335   excluded by machine
weather                           361   excluded by machine
opinion                           277   excluded by machine
paywall                             2   excluded by machine
--------------------------------------------
                                9,975   excluded, no review surface
obituary                          745   excluded, REVIEWABLE
not_article                       142   excluded, REVIEWABLE
out_of_scope                    3,662   excluded by a PERSON
```

`out_of_scope` is not on the machine list: one writer sets it, a reviewer
choosing "Out of scope". A status a human wrote is a decision, not a
flag, and the review queue deliberately does not re-surface those.

Obituaries are reviewable, and have been reviewed in quantity. That is
the shape the rest of this should take, and the proof it works.

## 1. The gap was the surface, not the record

The pipeline does write down why. An earlier draft of this document said
it did not -- that 8,367 of the 9,335 wire articles recorded no reason --
and that was wrong. It came from reading one key, `wire.detection_method`,
which is absent on these rows because `articles.wire` holds an array of
services here rather than an object. The reason is in
`metadata.wire_detection`, and the rule records what it fired on:

```json
{"hearst_source_name": {
   "detected_by": ["canonical_cross_domain"],
   "evidence": ["canonical=https://www.npr.org/2026/03/23/nx-s1-5699407/..."],
   "wire_services": ["NPR"]}}
```

7,555 of the March rows carry it. What was missing was a place to look at
them: a reviewer could not open a wire exclusion, so nobody could tell a
good one from a bad one at any volume.

## 2. The methods, and what they are worth

`detected_by` names the signal. Across the March rows carrying
`wire_detection`:

```
canonical_cross_domain      4,807
meta_author                 2,514
jsonld_author               1,159
og_distributor_category       381
jsonld_isBasedOn               95
jsonld_mainEntity              95
jsonld_contentSourceCode       95
```

This is the axis precision attaches to. A syndication is not a method:
"NPR" is not right or wrong, the rule that concluded NPR is.

**`canonical_cross_domain` is measured and promoted.** 500 rows reviewed
with no errors, then 100 drawn at random with no errors, then 200 more.
It is the largest method in the bucket and it clears the bar, so it keeps
a standing sample and nothing else. That is 4,807 of 9,335 removed from
the review list on evidence.

What it does is credit an article to a source named in its canonical URL
when that source is a different outlet from the publisher. Co-ownership
does not make that wrong: one known outlet credited, another known outlet
publishing, is syndication whoever owns them.

The remaining methods are unmeasured. The local-syndication rules --
byline identification, copyright-text matching -- are expected to be the
difficult ones, and they are where the review effort now goes.

## 3. What review is for, and how much of it to do

Human review here has two jobs, and they need different rows:

- **Finding errors.** A method that is often wrong should be reviewed
  heavily, and the rows likeliest to be wrong shown first.
- **Measuring the methods.** Precision and recall per method, which is
  what says how much review the first job needs -- and which cannot be
  computed from doubt-ranked rows, because they were not drawn at random.

So review is allocated **by method**, and each method gets both: a
doubt-ranked stream that finds mistakes efficiently, and a random sample
that measures the method honestly. This is the stratum-and-probability
design already settled for the discovery review queue
(docs/DISCOVERY_REVIEW_QUEUE.md); the same recording applies.

### The bar for running without review

**99% precision and 95% recall.** Below either, the method keeps human
review; at or above both, it runs on its own with only a standing sample
to notice if it drifts.

Both halves are required, because they are the two error types, and the
same two the discovery queue is built around
(docs/DISCOVERY_REVIEW_QUEUE.md). The polarity is inverted here, because
there the positive act is admitting a URL and here it is excluding an
article:

| | discovery queue | exclusion rules | recoverable |
|---|---|---|---|
| **Type I** | a non-story admitted | an exclusion missed (recall) | yes -- later stages still see it |
| **Type II** | a story rejected | an article wrongly excluded (precision) | **no** -- nothing else looks |

One vocabulary across both surfaces, and the same asymmetry decides the
thresholds: the bar on precision is higher than the bar on recall because
a Type II error is permanent and a Type I error is not.

They fail in different directions:

- **Precision below 99%** means the method is excluding articles that
  belong in the corpus. Every one is lost, and no other surface would
  ever show it -- the article simply is not there.
- **Recall below 95%** means the method is missing exclusions it should
  make. Those survive into the corpus, where enrichment and the review
  queues do get a look at them. A miss is recoverable downstream; a
  wrongful exclusion is not.

So a method may sit at 100% precision and still earn review, because it
is only catching half of what it should. Several URL-matching rules are
expected to reach the precision bar easily -- a URL under `/cnn.com/` is
a CNN story and no reviewer needs to confirm it -- and the open question
for those is recall, which is measured from the articles the rule did
NOT fire on.

Review effort is finite and belongs where a method has not cleared the
bar.

This is why the recording must name the **method**, not just the
category. "Wire" is not a thing with a precision; `url_normalization`
against a provider list is, and so is a byline pattern, and they are not
the same number.

## 4. What the labels are worth afterwards

Every decision a reviewer makes here is a labelled example of exactly the
judgement the pipeline is trying to automate, on the natural distribution
of a real corpus. Three models are wanted (see
docs/DISCOVERY_REVIEW_QUEUE.md), and this queue produces training data
for the third: post-extraction categorisation, with the body in hand
rather than only a URL.

The random-sample stratum is what makes the labels usable for measurement
as well as training, and the selection probability has to be recorded at
the moment of selection -- never recomputed later, when the ranking has
moved.

## 5. Where this stands

1. **A queue case for wire** — built (datadesk #269), filterable by
   `detected_by` and by attributed syndication. This is what was missing.
2. **`canonical_cross_domain` measured and promoted** — 4,807 rows,
   reviewed at 500 then 300 random, no errors. Standing sample only.
3. **The remaining wire methods**, 2,748 rows between them, are the next
   thing to sample. `meta_author` and `jsonld_author` are the volume;
   the byline and copyright rules are the difficulty.
4. **The other machine exclusions** — weather 361, opinion 277,
   paywall 2 — have no case yet. Small enough to review outright rather
   than sample.

Not needed, contrary to an earlier draft: a recording fix. The writers
already record. §1 explains how that was got wrong.

Nothing here changes what the pipeline excludes. It changes whether
anybody can find out that it was wrong.
