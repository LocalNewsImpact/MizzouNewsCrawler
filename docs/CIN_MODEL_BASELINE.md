# What the CIN classifier is, and what is not known about it

The production model assigns one of ten critical-information-needs
categories to every article the pipeline classifies. It was built outside
this repository and the training pipeline that produced it no longer
exists. Only the checkpoint, the inference loader
(`src/ml/article_classifier.py`) and a conference paper survive.

This is what has been established from those three, and what is still
missing. It stands as the baseline for a retrain until the original
developer supplies the rest.

## The methodology

From *Training on Annotator Disagreement (ToAD) Enhances AI News Article
Classification* (Dial, Haithcoat, Kiesow, Artman; August 2025).

The model is a fine-tuned `bert-base-uncased` with a ten-way head. It is
**not** trained against a single consensus label. Each article's truth is
a probability distribution over the ten categories, each annotator
contributing `1/n`, and the loss is Kullback-Leibler divergence against
that distribution. The paper's argument is that collapsing annotator
disagreement — by majority vote, or by keeping only unanimous articles —
discards information that was expensive to collect, and that the
disagreement itself carries signal about which categories genuinely
overlap.

That matters for how the corpus reads. 35.5% of articles had no agreement
on the primary category and 60.4% carried more than one category across
primary and secondary. Disagreement is the normal case here, not an
annotation defect.

**The shipped model was fine-tuned on primary categories only.**
Secondary categories are named in the paper as further work. This is why
the checkpoint's head is called `classifier_primary` and has no sibling:
it is named against a planned second head that was never trained, not one
that was dropped. Loading the checkpoint reports no missing and no
unexpected keys, so nothing is being silently discarded at inference.

## The label order is not the paper's figure

Figure 1 of the paper lists the categories alphabetically for
readability: CL, CI, ED, EN, EM, EP, HE, PL, SP, TS. The checkpoint's
class ids are a different order entirely:

| id | label | id | label |
| --- | --- | --- | --- |
| 0 | Civic Life | 5 | Sports |
| 1 | Civic information | 6 | Environment and Planning |
| 2 | Emergencies and Public Safety | 7 | Education |
| 3 | Health | 8 | Political life |
| 4 | Transportation Systems | 9 | Economic Development |

The two agree on positions 0 and 1 and diverge everywhere after. A
training vector built from the paper's figure would put eight of ten
labels in the wrong class with no error raised — a model trained against
scrambled classes that looks entirely normal until its predictions are
read.

`lnic_contracts.cin_labels.LABELS` is the authority, and
`tests/test_the_label_order_is_the_checkpoints.py` pins it to the
checkpoint. `CODEBOOK_ORDER` is a display order and is deliberately
different; it is not an encoding.

## What the model is fed

`ArticleClassificationService._prepare_text` prepends the headline to the
cleaned body, joined by a blank line, and the tokenizer truncates at 512
tokens. The paper does not say whether training did the same, which
raised the question of whether the model is served an input shape it
never saw.

It is not. Scoring the 950 labelled articles that carry a headline, a
body and a final label, both ways, against the same checkpoint:

| input | agrees with the human label |
| --- | --- |
| body only | 760 / 950 (80.0%) |
| headline + body | 771 / 950 (81.2%) |

Only 40 of 950 predictions changed at all, and the net movement favours
including the headline. Had training been body-only, an unseen headline
occupying the position `[CLS]` attends to most would be expected to cost
accuracy rather than gain it. **There is no train/serve skew here**, and
the retrain should train with the headline included, because it helps
slightly and it matches what is served.

### These numbers are not a performance estimate

The 950 articles include the roughly 800 the model was trained on. Only
200 were held out, and which 200 is not known. The accuracy above is
inflated by memorisation and must not be quoted as the model's
performance.

The comparison survives the contamination — identical articles scored
both ways, so whatever memorisation exists applies equally to both rows —
but the absolute figures do not. The paper reports 190/200 on its held
-out set, and that figure cannot be reproduced or checked here.

## What is still missing

Blocking a valid retrain:

1. **The 200 held-out article ids.** Without them a retrain cannot be
   compared against 190/200, and may train on the old test set, which
   would make any measured improvement an artefact and leave no way to
   detect it afterwards.
2. **Hyperparameters**: learning rate, batch size, epochs, optimiser,
   scheduler, warmup, weight decay, seed, and how the final epoch was
   selected.
3. **Preprocessing**: any normalisation or HTML stripping before
   tokenising, and the truncation strategy at 512 tokens (head-only, or
   head and tail).
4. `transformers` and `torch` versions.

Also worth asking for, and easily missed: the article text **as it was
then**. The corpus has been cleaned since these labels were assigned —
boilerplate detection, ROT47 decoding, wire reattribution — so matching
on id and pulling today's text would train on different inputs than the
annotators actually read.

## What the review queue already improves

Records tagged NOT LOCAL, NO APPROPRIATE CATEGORY, TOO SHORT and
TECHNICAL ERROR were omitted from the original training. Three of those
are gated upstream in production: `analysis.py` excludes `wire`,
`paywall`, `not_article`, `opinion` and `obituary`, and classifies only
`cleaned` and `local`. So the omission matches what the model is actually
fed.

`NO APPROPRIATE CATEGORY` is the exception. Nothing gates it, so an
article that fits no category still receives one of ten. The model has no
way to abstain.

Two things the Datadesk classification queue changes for the next round:

- **Three annotators per record rather than two.** Under `1/n` encoding
  that is thirds rather than halves, so a three-way split is
  representable instead of collapsing to a coin flip.
- **`inclusion_probability` is recorded per sampled article.**
  Low-incidence categories were oversampled deliberately, so the training
  distribution is not the corpus distribution. The field is what allows
  that to be corrected, either in the loss or at inference — but it has
  to be applied on purpose.

## Reproducing the measurement

The checkpoint is not in this repository. The comparison above was run
against a scratch copy, read-only, with `torch.load`, the
`classifier_primary` → `classifier` rename the loader already performs,
and `lnic_contracts.cin_labels.LABELS` for the class order. It needs the
checkpoint, the aggregated coding data held in Datadesk under
`data/coding/` — which is not committed anywhere, because it carries the
article text of roughly a thousand publishers — and about a minute on a
GPU.
