# A body says which language it is, paragraph by paragraph

CIN is English-trained. A Spanish body produces a label that means nothing, and
the corpus already carries those labels: two `redlatinastl.com` articles sat at
`Political life` until somebody set `non_english` on them by hand, and
`abc17news.com` holds roughly 1,500 Spanish `CNN en Espanol` wire stories,
several already labelled `Civic Life` and `Sports`.

Two things follow, and they are not the same thing:

1. A **Spanish-language** article must not be classified or enriched, and is
   filed `non_english`.
2. A **bilingual** article must be analysed on its English half. Discarding it
   loses real local reporting; classifying the whole body feeds the model two
   languages at once.

## The unit of detection is the paragraph

Because the second case is not rare. `redlatinastl.com` runs each story twice on
one page — an English headline and paragraphs, then the Spanish — and every one
of 30 sampled articles measured between **46% and 57% Spanish by paragraph**.

A 50/50 document has no correct single label, so asking a whole-document
detector for one returns a coin flip. Measured over 240 articles on eight hosts:

| detector | verdict on the 30 `redlatinastl` articles |
| --- | --- |
| function-word rate | es:30 |
| `langdetect` | es:18, en:12 |
| `lingua` | es:25, en:5 |

`lingua` reported ENGLISH with confidence **1.00** for an article headlined
"¿El café es bueno o malo para el corazón?". `langdetect`, which seeds its
detector randomly unless `DetectorFactory.seed` is pinned, returned `{'en',
'es'}` across five runs of the **same text**; it also raised
`LangDetectException` on 17 of the 240 (empty bodies) and called one
`stltoday.com` article Afrikaans. On the empty bodies `lingua` answered ENGLISH
with high confidence, which is worse than an exception.

None of that is an argument against those libraries in general. It is the
observation that a document-level answer is the wrong shape for this corpus.
Per paragraph the question has an answer, the document verdict is a share
computed from those answers, and job 2 gets its input for free: the English
paragraphs are the body.

## The measure

Function-word rate — the same measure `boilerplate.prose_density()` already
uses to decide whether a block is writing. Function words are the highest
frequency words in any language, they are grammatical rather than topical so
they do not move with subject matter, and the list is closed-class.

On monolingual text the separation is not close. Spanish wire on
`abc17news.com` scores es 0.47 against en 0.01, and **none** of 260 flagged
paragraphs landed in the 0.15–0.20 band where a threshold argument would
matter.

A word that exists in both languages cannot discriminate, so `a`, `no` and `he`
("he visto") are in **neither** set. The sets are defined in
`src/utils/language.py` rather than imported from `boilerplate` because that set
is tuned for prose density and includes `said`, which is journalistic
frequency, not grammar.

## The filter fails open

Only a positive `spanish` verdict refuses. `undetermined` hands the body back
unchanged, because "no measurable language" is not evidence of Spanish and each
stage's own gates already refuse an empty or furniture body. Blocking on it
would silently drop short real writing — `looks_like_article()` carries no
word-count floor precisely because local news runs short.

## `non_english` is terminal

Not a queue, not a hold, and nothing rewinds it. There is no English text to
classify, and a second fetch returns the same Spanish page. The one event that
reopens these records is a Spanish-language classifier.

That is why the verdict is written to `metadata.language` as well as to the
status: the status says "not for this pipeline", and the metadata is what a
Spanish classifier selects on when there is one.

    metadata.language = {"primary": "es", "verdict": "spanish",
                         "spanish_share": 0.98, "english_chars": 0,
                         "spanish_chars": 2841,
                         "detector": "function_word_rate_by_paragraph"}

## What this change contains

- `src/utils/language.py` — `paragraph_language`, `profile`, `english_text`,
  `analysis_text`. The stored body is never modified; the English-only body is
  a derived view, because the capture is the provenance and a record must still
  be able to show what the page served.
- `ArticleClassificationService._prepare_text` passes the body through
  `language.analysis_text`, so CIN reads English only, and
  `_mark_non_english` files a Spanish record terminally rather than skipping it
  forever. Without the status write the article keeps an eligible status and is
  re-selected on every run: `attempted_article_ids` only suppresses a repeat
  inside one run.

## What it does not contain

- **Enrichment is not yet wired.** Enrichment selects `status = 'labeled'`, so
  no Spanish record reaches it once classification files it — but a record
  labelled before this change still can. The same one-line call belongs in the
  enrichment repository's body read.
- **No backfill.** Roughly 2,215 articles score Spanish corpus-wide, of which
  only **28** are in the export. The rest are already `wire` or otherwise held
  out. A backfill should file the Spanish ones `non_english` and re-classify
  the bilingual ones on their English half; both need a run and a snapshot,
  and neither is a code change.
- **No `language` column.** The verdict lives in `metadata.language`. A column
  is the right home once there is a second consumer, and it needs a migration.
- **Spanish is the only non-English language handled.** The corpus's
  non-English publishers are Spanish-language (`redlatinastl.com`,
  `dosmundos.com`, `comobuz.com`, `abc17news.com` wire). A third language needs
  a third function-word set and nothing else.
