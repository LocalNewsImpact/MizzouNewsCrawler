# Where training labels come from

Three models are wanted beyond the CIN classifier: a better storysniffer,
a topic labeller (sports, obituaries, wire, columns), and whatever comes
after. The instinct is to build one screen where somebody designs a
labelling task and coders work through a queue.

That would be the wrong build for two of the three. These tasks differ in
where the label comes from, not in how a person clicks, and only one of
them needs anybody to read an article and decide.

## Three kinds of task

### Outcome-labelled: storysniffer

The label already exists, downstream of the prediction.

Storysniffer guesses whether a URL is a story *before* the fetch.
Extraction then finds out. A URL that came back a real article is a
positive; a 404, a feed, a search page, a section index is a negative.
The pipeline mints this ground truth continuously and nobody reads
anything.

**No labelling interface. A harvest query, a retraining job, and one
screen where a person promotes a model or does not.**

One trap, and it is the obvious query. `candidate_links.status` has two
writers: a pre-extraction URL rule, which is storysniffer's own decision,
and a post-extraction content rule, which is the outcome. Harvesting that
column without separating them trains the model on its own predictions.
It will score extremely well and have learned nothing.
`extraction_telemetry_v2` is what tells the two apart, so the harvest
joins through it.

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

Storysniffer first. It needs no labelling, the data exists already, and
the first two improvements need no retraining at all. Topic second, via
heuristic bootstrap and a verification queue. CIN stays on its own track
because its cost structure is not like either.

Before any of it: measure how many outcome-labelled URLs there actually
are, and score the current model against them. That is a read-only query,
and it decides whether this is a week of work or a quarter.
