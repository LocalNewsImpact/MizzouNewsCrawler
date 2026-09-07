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

## 1. The gap is not only the queue

The obvious reading is "the extraction review queue has no case for
wire". It has a worse problem underneath.

Of the 9,335 wire articles in that window, **8,367 record no reason at
all** -- nothing in `articles.wire`, nothing under
`metadata.content_type_detection`, no row in
`content_type_detection_telemetry`. 964 record `wire_service_detected`
and 4 record obituary signals. The rest were removed from the corpus and
the pipeline did not write down why.

A queue cannot rank what has no evidence, so recording comes first.

## 2. Nine writers, three of which account for themselves

```
src/utils/content_type_detector.py:1219   status="wire"       records
src/utils/content_type_detector.py:1405   status="opinion"    records
src/utils/content_type_detector.py:1487   status="weather"    records
src/cli/commands/extraction.py:1177       article_status      wire_hints
src/cli/commands/extraction.py:1600       article_status      --
src/cli/commands/extraction.py:1702       article_status      --
src/cli/commands/extraction.py:2732       new_status          --
src/cli/commands/cleaning.py:157          new_status          --
src/services/url_verification.py:858      new_status          --
```

Only the three in `content_type_detector` write to
`content_type_detection_telemetry`, which is exactly why coverage of
wire is 10.4%. The others set a status and move on.

This is the same defect as the job counters and the missing telemetry
dataset: a stage that can act but cannot account for itself. The fix is
the same shape -- the writer records what it decided and on what
evidence, because it is the only thing that knows.

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

## 5. Order of work

1. **Record the decision.** Every writer in §2 records the method and its
   evidence where a query can reach it. Without this nothing else is
   possible, and every day it is not done adds rows that can never be
   audited.
2. **Backfill what is recoverable.** Some of the 8,367 can be attributed
   after the fact from the URL and the byline. Some cannot, and stay
   unattributed rather than guessed at.
3. **A queue case per machine exclusion**, grouped by method, doubt-ranked
   within it, with a random sample drawn and its probability recorded.
4. **Measure precision per method** from the sample, and set each
   method's review volume from it.

Nothing here changes what the pipeline excludes. It changes whether
anybody can find out that it was wrong.
