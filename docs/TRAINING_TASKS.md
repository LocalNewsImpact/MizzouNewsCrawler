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

### Four improvements, cheapest first

**1. Calibrate the margin.** The margin orders URLs; the scale means
nothing. Fitting isotonic or Platt calibration against outcome labels
turns it into a probability that can be reasoned about. No retraining, no
fork of the package. This alone gives a meaningful confidence column in
the discovery queue, a fetch queue that can be prioritised, and a
threshold that can be set against cost.

**2. Set the threshold to our cost asymmetry.** `guess()` decides at the
model's default. A wasted fetch is cheap; a missed local story is the
whole point of the project. Those are not symmetric and the current
threshold does not know it. Calibration is what makes this choosable
rather than guessed.

**3. Retrain the same architecture on our corpus.** The shipped model is
trained on general US news. This corpus is Missouri, Vermont and
Washington community papers running BLOX, Newzware and PMP, whose URL
conventions are specific and repetitive. The same pipeline shape retrained
on outcome labels should beat it, and drops in as a `skops` file with no
code change.

**4. Give it the host.** Only the path is used, so the same path at two
publishers scores identically. Publisher or CMS as a feature is a real
gain, with the obvious hazard: a model that memorises publishers rather
than learning URL shape. Held-out publishers, not just held-out URLs, is
how that gets caught.

### Contributing upstream

`storysniffer` is a general-purpose package and (1) is useful to everyone
using it. `guess()` returning only a boolean is the limitation; a
`score()` returning the log-space margin, with the saturation documented,
is a small and self-contained pull request. Worth offering rather than
carrying a private fork -- and the calibration, which is corpus-specific,
stays here.

## Order of work

Storysniffer first. It needs no labelling, the data exists already, and
the first two improvements need no retraining at all. Topic second, via
heuristic bootstrap and a verification queue. CIN stays on its own track
because its cost structure is not like either.

Before any of it: measure how many outcome-labelled URLs there actually
are, and score the current model against them. That is a read-only query,
and it decides whether this is a week of work or a quarter.
