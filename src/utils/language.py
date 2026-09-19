"""Which language a body is written in, measured paragraph by paragraph.

TWO JOBS, AND THEY NEED DIFFERENT ANSWERS
-----------------------------------------
1. A Spanish-language article must not be classified or enriched. CIN is an
   English-trained model and a Spanish body produces a label that means
   nothing: `redlatinastl.com` had two articles sitting at `Political life`
   before somebody set `non_english` on them by hand, and `abc17news.com`
   carries ~1,500 Spanish `CNN en Espanol` wire stories, several already
   labelled `Civic Life` and `Sports`.

2. A BILINGUAL article must be analysed on its English half. This is not a
   rare shape: `redlatinastl.com` runs the same story twice on one page, an
   English headline and paragraphs followed by the Spanish, and every article
   sampled measured between 46% and 57% Spanish BY PARAGRAPH. Discarding
   those records loses real local reporting; classifying the whole body feeds
   the model two languages at once.

WHY NOT A WHOLE-DOCUMENT LANGUAGE DETECTOR
------------------------------------------
Because a 50/50 document has no correct single label, and asking for one
returns a coin flip. Measured on 240 articles across eight hosts, the three
candidates disagreed on `redlatinastl` exactly as that predicts:

    function-word rate   es:30
    langdetect           es:18  en:12
    lingua               es:25  en:5

`lingua` reported ENGLISH with confidence 1.00 for an article headlined
"?El cafe es bueno o malo para el corazon?", and `langdetect` -- which seeds
its detector randomly unless `DetectorFactory.seed` is pinned -- returned
{'en', 'es'} across five runs of the SAME text. langdetect additionally
raised `LangDetectException` on 17 of the 240 (empty bodies) and called one
`stltoday.com` article Afrikaans.

So the unit of detection is the PARAGRAPH, where the question has an answer,
and the document-level verdict is a share computed from those answers. That
also gives job 2 its input for free: the English paragraphs are the body.

THE MEASURE
-----------
Function-word rate, the same measure `boilerplate.prose_density()` already
uses to decide whether a block is writing. Function words are the highest
frequency words in any language, they are grammatical rather than topical so
they do not move with subject matter, and the list is closed-class. On
monolingual text the separation is not close: Spanish wire on `abc17news`
scores es 0.47 / en 0.01, and NONE of 260 flagged paragraphs landed in the
0.15-0.20 band where a threshold argument would matter.

A word that exists in both languages cannot discriminate, so `a`, `no` and
`he` ("he visto") are in NEITHER set. That is why these sets are defined here
rather than imported from `boilerplate`: that set is tuned for prose density
and includes `said`, which is journalistic frequency, not grammar.
"""

from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

#: Grammatical English, minus every word Spanish also uses.
ENGLISH_FUNCTION_WORDS: frozenset[str] = frozenset("""
    an and are as at be been but by for from had has have his her if in into is
    it its not of on or she that the their there these this those to was were
    what when which who will with would you your
    """.split())

#: Grammatical Spanish, minus every word English also uses. Stored unaccented
#: because the comparison strips accents: the WSU notebook import mangled
#: apostrophes and accents, and "mas"/"mas" must count the same either way.
SPANISH_FUNCTION_WORDS: frozenset[str] = frozenset("""
    al como con cual cuando de del desde donde el ella ellos en entre era eran
    es esta estan este esto estos fue fueron ha han hasta hay la las le les lo
    los mas mi mientras muy nos nuestra o para pero por porque que quien se sea
    sera si sin sobre son su sus tambien tiene todo todos un una y ya
    """.split())

#: A paragraph shorter than this is not measured. Every detector behaves badly
#: on a fragment -- `lingua` answers ENGLISH with high confidence for an EMPTY
#: body, which is worse than an exception -- and a rate over six words is
#: noise. Datelines, photo credits and bylines all live below this line.
MIN_PARAGRAPH_WORDS = 12

#: The floor a language's rate must clear to be claimed at all. Below it the
#: paragraph is `None`: a list, a caption, a run of proper nouns.
MIN_FUNCTION_WORD_RATE = 0.10

#: Share of measured CHARACTERS that must be Spanish before the article is
#: treated as Spanish rather than bilingual. Deliberately high: the cost of
#: calling a bilingual article Spanish is losing the English reporting in it.
SPANISH_ARTICLE_SHARE = 0.85

#: English needed before a mixed article can be analysed on its English half.
#: Below this there is not enough writing to classify, whatever the ratio.
MIN_ENGLISH_CHARS = 400

ENGLISH = "en"
SPANISH = "es"

#: The article status a Spanish-language record is filed under. Already in the
#: production vocabulary -- two `redlatinastl.com` rows carry it -- and
#: selected by no stage, which is the property being relied on.
#:
#: THIS IS TERMINAL. Not a queue, not a hold, and nothing rewinds it: there is
#: no English text to classify and CIN is English-trained, so the record is
#: finished until a Spanish-language classifier exists. That is the one event
#: that reopens it, which is why the verdict is written to
#: `metadata.language` as well as the status -- the status says "not for this
#: pipeline", and the metadata is what a Spanish classifier will select on
#: when there is one. A re-extraction does not change the answer; the page is
#: in Spanish.
NON_ENGLISH_STATUS = "non_english"

#: Where the verdict is recorded on the row, and the key a future Spanish
#: classifier queries to find its corpus.
LANGUAGE_METADATA_KEY = "language"

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n|\r\n\s*\r\n|\n|\r")
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def _fold(word: str) -> str:
    """Lowercase and strip accents, so `mas` and `mas` are one word."""
    decomposed = unicodedata.normalize("NFD", word.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def paragraphs(text: str | None) -> list[str]:
    """The blocks a language verdict is formed over.

    Split on single newlines as well as blank lines. Bilingual publishers run
    the two languages as adjacent paragraphs, and a body stored with single
    newlines would otherwise arrive as one block carrying both.
    """
    if not text:
        return []
    return [p.strip() for p in _PARAGRAPH_SPLIT.split(text) if p.strip()]


def function_word_rates(text: str | None) -> tuple[float, float, int]:
    """English rate, Spanish rate, and the word count they were measured over."""
    words = [_fold(w) for w in _WORD.findall(text or "")]
    if not words:
        return 0.0, 0.0, 0
    english = sum(1 for w in words if w in ENGLISH_FUNCTION_WORDS)
    spanish = sum(1 for w in words if w in SPANISH_FUNCTION_WORDS)
    return english / len(words), spanish / len(words), len(words)


def paragraph_language(paragraph: str | None) -> str | None:
    """`en`, `es`, or None when the block is too short or too thin to say.

    None is a real answer and is kept as one. Counting an unmeasurable caption
    as English would put Spanish articles over the English threshold.
    """
    english, spanish, words = function_word_rates(paragraph)
    if words < MIN_PARAGRAPH_WORDS:
        return None
    best = max(english, spanish)
    if best < MIN_FUNCTION_WORD_RATE or english == spanish:
        return None
    return ENGLISH if english > spanish else SPANISH


class LanguageProfile(NamedTuple):
    """What the paragraphs said, and what follows from it.

    Shares are over measured CHARACTERS rather than paragraph counts, because
    paragraph lengths differ by language: the Spanish half of a bilingual
    story often runs longer, and a count would understate it.
    """

    verdict: str
    english_chars: int
    spanish_chars: int
    undetermined_chars: int
    english_paragraphs: int
    spanish_paragraphs: int
    undetermined_paragraphs: int

    @property
    def measured_chars(self) -> int:
        return self.english_chars + self.spanish_chars

    @property
    def spanish_share(self) -> float:
        total = self.measured_chars
        return (self.spanish_chars / total) if total else 0.0

    @property
    def analysable(self) -> bool:
        """Whether CIN and enrichment should run on this record at all."""
        return self.verdict in ("english", "mixed")


def profile(text: str | None) -> LanguageProfile:
    """Measure a body and say what should happen to it.

    verdict is one of:
      `english`       -- analyse as it stands
      `mixed`         -- analyse `english_text()`, not the stored body
      `spanish`       -- do not analyse; label ES
      `undetermined`  -- nothing measurable; do not analyse on a guess
    """
    en_chars = es_chars = un_chars = 0
    en_paras = es_paras = un_paras = 0
    for para in paragraphs(text):
        lang = paragraph_language(para)
        if lang == ENGLISH:
            en_chars += len(para)
            en_paras += 1
        elif lang == SPANISH:
            es_chars += len(para)
            es_paras += 1
        else:
            un_chars += len(para)
            un_paras += 1

    measured = en_chars + es_chars
    if not measured:
        verdict = "undetermined"
    elif es_chars / measured >= SPANISH_ARTICLE_SHARE:
        verdict = "spanish"
    elif es_chars == 0:
        verdict = "english"
    elif en_chars >= MIN_ENGLISH_CHARS:
        verdict = "mixed"
    else:
        # Spanish-dominant without enough English to stand on its own.
        verdict = "spanish"
    return LanguageProfile(
        verdict=verdict,
        english_chars=en_chars,
        spanish_chars=es_chars,
        undetermined_chars=un_chars,
        english_paragraphs=en_paras,
        spanish_paragraphs=es_paras,
        undetermined_paragraphs=un_paras,
    )


def english_text(text: str | None) -> str:
    """The English paragraphs only -- the body CIN and enrichment should read.

    Undetermined paragraphs are DROPPED rather than kept. On a bilingual page
    the unmeasurable blocks are captions, bylines and datelines belonging to
    whichever half they sit in, and keeping them would reintroduce Spanish
    into the text this function exists to clean.

    The stored body is never modified. This is a derived view: the capture is
    the provenance, and a record must still be able to show what the page
    served.
    """
    return "\n\n".join(p for p in paragraphs(text) if paragraph_language(p) == ENGLISH)


def analysis_text(text: str | None) -> str | None:
    """The text a stage should analyse, or None if the record must be skipped.

    One call for every caller that currently reads the body directly, so the
    English-only rule lives in one place rather than in each stage.

    FAILS OPEN. Only a positive `spanish` verdict returns None. `undetermined`
    hands back the body unchanged, because "no measurable language" is not
    evidence of Spanish and the stage's own gates already refuse an empty or
    furniture body. Blocking on it would silently drop short real writing:
    local news runs to a couple of sentences often enough that
    `looks_like_article()` carries no word-count floor for the same reason.
    """
    found = profile(text)
    if found.verdict == "spanish":
        return None
    if found.verdict == "mixed":
        return english_text(text)
    return text
