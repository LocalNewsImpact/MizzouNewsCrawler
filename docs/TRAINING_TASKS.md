# Where training labels come from

Three models are wanted beyond the CIN classifier: a better storysniffer,
a topic labeller (sports, obituaries, wire, columns), and whatever comes
after. The instinct is to build one screen where somebody designs a
labelling task and coders work through a queue.

That would be the wrong build for two of the three. These tasks differ in
where the label comes from, not in how a person clicks, and only one of
them needs anybody to read an article and decide.

## Three kinds of task

### Outcome-labelled, but only on one side: storysniffer

Storysniffer guesses whether a URL is a story *before* the fetch, and
extraction then finds out. A URL that came back a real article is a
positive. The pipeline mints that continuously and nobody reads anything.

It does not mint the other half, and the reason is structural rather than
a shortage. **A rejected URL is never fetched, so nobody ever learns
whether it was a story.** Outcomes exist only for URLs the model already
accepted. The cases where its judgement actually matters are exactly the
ones with no label.

Measured on March 2026, Missouri State News Sources, 50,091 URLs
discovered in the month:

| | count |
| --- | ---: |
| Positive -- fetched, was a story | 34,391 |
| Negative -- fetched, was not | 498 |
| Unlabelled -- rejected on the URL rule, never fetched | 4,232 |
| Unlabelled -- never fetched, other reasons | 10,938 |

Sixty-nine positives per negative, and 426 of those 498 negatives are
`404` -- dead links, not "this URL was never a story". Trained on this
alone a model learns to say yes to everything, scores about 99% against
its own evaluation, and is worthless.

So the harvest is worth doing for what it is good for -- precision and
calibration in the region the model already accepts -- and it cannot
settle the decision boundary on its own.

**One trap in the harvest**, and it is the obvious query.
`candidate_links.status` has two writers: a pre-extraction URL rule,
which is storysniffer's own decision, and a post-extraction content rule,
which is the outcome. Harvesting that column without separating them
trains the model on its own predictions. `extraction_telemetry_v2` is
what tells them apart -- a row with no telemetry was never fetched and
has no outcome, whatever its status says.

### The review queue is already the missing half

The discovery review queue asks a person about a candidate link and
offers two verbs, "It is a story" and "Not a story". That is a human
binary label on the same URLs the model decided about, **including the
ones it rejected** -- which is the class the outcome data cannot contain.

Two days of reviewing, 553 decisions:

| | human: is a story | human: not a story |
| --- | ---: | ---: |
| pipeline accepted | 309 | 72 |
| pipeline rejected | **96** | 76 |

Ninety-six confirmed false negatives: real stories thrown away before
anyone saw them. Seventy-six confirmed true negatives, against 498 in a
month of outcomes, most of which were dead links.

Two days of review produced a better-shaped training set than a month of
pipeline outcomes. It is balanced across both kinds of error and it
samples where the model is actually wrong, because a person is looking at
the ambiguous cases rather than a sampler drawing at random.

The exploration mechanism this note was going to propose already exists.
What is missing is that nothing harvests it.

#### Where the signals are

| | |
| --- | --- |
| datadesk, `review_reviewdecision` | `queue='discovery'`, `subject_type='candidate_link'`, verb `story` or `not_story`, the prior status in `before`, a story kind in `value` |
| crawler, `url_verifications` | `storysniffer_result`, the bool with overrides applied; `verification_confidence`, the log-odds margin; `previous_status` and `new_status` |

Joined on the candidate link, that is the model's verdict, its margin and
a person's answer on the same URL. Two databases on one instance, so the
harvest reads both rather than joining in SQL.

#### What the 96 lost stories were killed by

`UrlVerification` records that 12,464 of March's 13,764 rejections carry
a *positive* margin -- the model wanted to accept and a hand-written
blacklist overruled it. That invites the conclusion that the rule list is
the problem. On the 96 confirmed false negatives it is not:

| | count | mean margin |
| --- | ---: | ---: |
| the model itself said no | 91 | -12.3 |
| an override killed it despite a positive margin | 5 | +829.8 |

Ninety-five percent were the model's own call, and only just -- a mean
margin of -12 is a hair below its own line. The overrides are noisy
across all rejections and are not what loses stories.

#### The review data cannot measure the model

The margin separates story from not-story on reviewed URLs at an AUC of
**0.489** -- worse than a coin. That is not a dead model, it is the
queue working as designed.

| | n | AUC of the margin |
| --- | ---: | ---: |
| all reviewed | 553 | 0.489 |
| inside the doubtful band, `abs(margin) <= 25` | 503 | 0.499 |
| outside it | 50 | 0.717 |

The doubtful stratum filters on `verification_confidence` between -25 and
+25, so 91% of what a reviewer sees is drawn from the band where the
score is uninformative *by selection*. Outside the band the same margin
separates at 0.717. Human attention is being spent precisely where the
model has nothing to say, which is the right place to spend it.

The consequence is a discipline, not a defect. **Review decisions are
training data for the boundary. They are not an evaluation set, and they
cannot be used to tune a threshold**, because which URLs got reviewed
depended on the score being thresholded. Any measurement of whether a new
model is better has to come from a separately drawn random sample. This
is the same selective-labels problem as the unfetched rejects, one level
up, and it is easier to miss because the labels here are real and
plentiful.

#### What this changes

Storysniffer is not an outcome-labelled task with a promotion gate. It is
**outcome-labelled for positives and human-labelled at the boundary**,
and the review queue is what supplies the second. The promotion gate
still holds; what changes is that the queue is a training input and
should be treated as one, including the discipline that follows: reviewed
URLs are not a random sample, and a model evaluated on them will read
better than it is. The held-out evaluation set stays separate and random.

### Weakly-labelled: topic

Heuristics produce a large, noisy training set for nothing. Section paths
(`/sports/`, `/obituaries/`), bylines (`Associated Press`), the wire
detection already built, the URL kinds already enumerated for the
discovery queue. None is reliable alone; together they cover most of the
corpus with a known error rate.

People are needed for two jobs only: auditing the heuristic's precision
on a sample, and deciding the cases where heuristics abstain or disagree.

**A verification queue, not a labelling queue.** Confirm or correct a
proposed label, one keystroke, against reading an article and deciding
from scratch. The difference is roughly an order of magnitude in cost per
label, and it is what makes topic labelling affordable at all.

### Judgement-labelled: CIN

Irreducibly human. A codebook, double coding, adjudication, inter-coder
agreement, and the round machinery in the datadesk repository's
`CIN_ROUNDS.md`.

This is the expensive one. It should stay the exception rather than the
template every other task is built from.

## What is shared

One spine, three flows over it.

- **A held-out evaluation set**, drawn at random, reserved before any
  training label is collected, never touched by active selection. If a
  model is trained on the examples it was least sure about and then
  scored on them, every number is wrong in the direction that flatters.
  This is enforced, not offered as an option.
- **A promotion gate**: the current model against the candidate, on that
  set, with a person deciding to ship. For storysniffer this is the only
  screen needed.
- **The confusion, per class**, so the binding weakness is visible rather
  than averaged away.

## What not to build

**A generic "design an ML task" builder.** The three kinds have
genuinely different shapes -- binary with free labels, multiclass with a
heuristic bootstrap, multiclass with a codebook -- and a form general
enough for all three is twenty fields nobody can fill correctly. Three
purpose-built flows over the shared spine will be smaller in total and
far likelier to produce a valid result.

**Model configuration in the interface.** The interface owns what gets
labelled and when a round is finished. Architecture, hyperparameters and
training runs belong in a pipeline that takes a round id as its input. A
round is a specification; a model is a build product.

**A typed target.** Covered in `CIN_ROUNDS.md` and it generalises: state
the effect worth detecting and derive the count. A number somebody types
carries no reasoning and cannot warn them that what they asked for costs
twenty times what they expect.

## What the interface can actually be expert about

One thing, and it is worth more than the rest combined: **a learning
curve from our own past rounds.** Score a model at 200, 400, 800, 1,600
labels and fit the curve, then answer the only question anybody actually
has -- what does another 500 labels buy?

Today that is unanswerable, so rounds are sized by intuition. With it the
interface can say that another 500 labels on the rarest category moves it
six points and another 500 on the commonest moves it half of one, which
is also how somebody learns to stop labelling and go and fix the codebook
instead.

Everything else the interface should warn rather than advise: name the
binding category, show the cost before the commitment, flag a target that
cannot move the metric it is aimed at.

## Storysniffer specifically

What it is, read from the installed package (1.0.9):

- Two scikit-learn pipelines serialised with `skops`: `path-only-model`
  and `path-and-text-model`. Naive Bayes over character n-grams.
- The only features are the URL **path** and, optionally, the link's
  anchor text. Not the host, not the query string.
- Hand-written blacklists and whitelists wrap the model, applied *after*
  it. A URL can score positive and still be rejected by a prefix rule.
- `guess()` returns a bare boolean.

`url_verification.score_margin` already establishes the rest, and it is
the finding everything below rests on: `predict_proba` saturates -- 97.5%
of three thousand production URLs come back at exactly 0.0 or 1.0,
because naive Bayes treats correlated n-grams as independent and the
exponential destroys the information. In log space it survives. The same
three thousand URLs give 2,990 distinct margins across a range of -194 to
+3,497.

So there is a usable ordering signal and no calibrated one. That is the
opening.

### What the upstream training looks like

The repository is public and carries its notebooks and its labelled data,
so none of this is guesswork.

- **2,838 usable labelled URLs** across 499 hosts, 41.8% of them stories.
  Sampled in 2022 from a global mix -- Nikkei, Times of India, Stern,
  Punjab Kesari, SF Chronicle. Broad, and almost nothing like a Missouri
  weekly.
- `CountVectorizer(min_df=0.1, max_df=0.9, ngram_range=(1,8),
  analyzer="char")`. A character n-gram must appear in at least a tenth
  of all documents to become a feature, which leaves about **180
  features**.
- `GaussianNB()` on those dense counts.
- A random row-wise train/test split.

Two of those look like mistakes and, tested, are not:

- **GaussianNB on count features.** The textbook choice is multinomial.
  Swapped, it is markedly worse here: f1 0.830 against 0.921. With only
  180 dense features, Gaussian is the right call and the aggressive
  `min_df` is what makes it one.
- **A row-wise split across 499 hosts** puts the same publisher on both
  sides, which should flatter the score. Splitting by host instead, it
  goes *up* -- 0.934 against 0.921. The model is not memorising
  publishers.

Both were worth testing rather than asserting. Neither is the problem.

### The problem is the confidence, and it is fixable

`score_margin` computes a log-space margin because `predict_proba`
saturates. Measured on eight host-grouped splits of the upstream data,
that saturation is **97.6%** of predictions at exactly 0 or 1. The
margin hack exists because of it.

Keep the features and change the classifier, and it goes away:

| | f1 | AUC | saturated | Brier |
| --- | --- | --- | --- | --- |
| GaussianNB, `min_df=0.1` (shipped) | 0.898 ±0.024 | 0.956 ±0.012 | 97.6% | 0.085 |
| LogisticRegression, `min_df=3` | 0.898 ±0.034 | 0.977 ±0.006 | 3.1% | 0.069 |

Eight host-grouped splits, mean and standard deviation. Identical
classification accuracy. Better ranking on **8 splits out of 8**, and a
better Brier score on 6 of 8.

That is the whole finding. The shipped model is not less accurate; it is
unable to say how sure it is, and that is the one thing this project
needs from it. A calibrated probability makes the discovery queue's
confidence column mean something, lets the fetch queue be ordered by
expected value, and lets the accept threshold be set against a cost
asymmetry rather than left at the default.

It also removes two workarounds rather than adding a layer: the log-space
margin in `score_margin`, and the post-hoc calibration that would
otherwise be needed.

### What to do, in order

**1. Change the classifier, not the features.** Logistic regression over
`min_df=3` character n-grams. Same accuracy, usable probabilities. This
is a change to the training notebook, not to the corpus.

**2. Set the threshold to our cost asymmetry.** A wasted fetch is cheap;
a missed local story is the point of the project. Only possible once (1)
gives a probability to threshold.

**3. Retrain on our corpus.** 2,838 globally-sampled URLs is a small set,
and community papers running BLOX, Newzware and PMP are exactly what it
does not contain. Our outcome labels are the contribution -- the same
architecture retrained on them should beat a general model on our URLs,
and drops in as a `skops` file with no code change.

**4. Consider the host as a feature.** Only the path is used, so the same
path at two publishers scores identically. Worth testing, with the hazard
in mind: the grouped split above shows no memorisation today, and adding
the host is exactly the change that could introduce it. Any test of it is
grouped by host or it is meaningless.

### Contributing upstream

(1) is a general improvement, not a local preference -- the evidence is
from upstream's own data and notebook, and it costs them nothing in
accuracy. A pull request changing the classifier and exposing a `score()`
alongside `guess()` would let every user of the package have a confidence
signal, and would retire our margin workaround rather than entrench it.

The retrained weights from (3) are corpus-specific and stay here.

## Order of work

Storysniffer first, and the counting is done: 34,391 confirmed positives
in one month of Missouri, 498 negatives worth little, and 553 human
decisions in two days that are worth a great deal more.

1. **Harvest the review queue.** It is the only source of the labels that
   decide the boundary, it is already being produced, and nothing reads
   it. This is a join across two databases, not a new interface.
2. **Draw a random evaluation sample.** Nothing can be measured
   without one. The reviewed URLs cannot serve, because the queue
   selected them on the score any new model would be judged against, and
   the fetched outcomes cannot either, because they exist only where the
   model said yes. A few hundred URLs drawn at random and reviewed is the
   missing instrument, and it is small.

   The overrides are not the place to start: of the 96 confirmed false
   negatives, 91 were the model's own call and 5 were overrides.
3. **Change the classifier**, per the measurements below: same accuracy,
   usable probabilities, retires the margin workaround.
4. **Retrain on our corpus**, once there are enough boundary labels to
   evaluate honestly.

Topic second, via heuristic bootstrap and a verification queue. CIN stays
on its own track because its cost structure is not like either.
