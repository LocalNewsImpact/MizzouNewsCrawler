"""Prose density is measured in the language the text is actually in.

Function words are the most language-specific thing in a body, and
`FUNCTION_WORDS` is an English list. So Spanish prose scores near zero against
it and reads as furniture no matter how well written it is.

Measured 2026-09-20 on real captures — Spokane Public Radio and Northwest Public
Broadcasting coverage of farmworker displacement, migrant labour policy and long
COVID:

| | English-only | measured in its own language |
| --- | --- | --- |
| seven Spanish captures | 0.037 – 0.050 | 0.376 – 0.408 |

The floor is 0.14. They were not marginal; they were ten times over it once asked
the right question, and all seven had been filed `not_article`.

`classify_furniture`'s docstring asserted the opposite — that the shape rules
"leave unusual-but-real prose alone (Spanish articles score low on the
English-only prose density but read as sentences)" and flagged "0 of the Spanish
captures" in the 2026-07-26 verification run. That claim was load-bearing: it is
the reason nobody checked.

The English measure is deliberately unchanged. `language.ENGLISH_FUNCTION_WORDS`
is longer but lacks `a`, `he` and `said`, all common in reporting, so adopting it
would move every English score and the 0.14 floor with it. Verified against 400
enriched English articles: zero scores changed, zero newly failed.

Spanish-only bodies still do not progress. `language.profile().analysable` is
`verdict in ("english", "mixed")`, so a Spanish story is labelled and held, and
only inline EN/ES reaches CIN and enrichment. This module does not change that —
it stops such a story being destroyed as furniture before the language question
is ever asked.
"""

from __future__ import annotations

import re

from src.utils.boilerplate import (
    FUNCTION_WORDS,
    MIN_PROSE_DENSITY,
    classify_furniture,
    prose_density,
)
from src.utils.language import profile

#: Two paragraphs of the Condado de Chelan capture, which was filed not_article.
SPANISH_REPORTING = (
    "El Condado de Chelan dejara de compartir las fechas de los incendios con "
    "las comunidades agricolas, una decision que segun los lideres locales "
    "dejara a los trabajadores sin informacion sobre cuando es seguro volver a "
    "los campos de manzanas.\n"
    "Los grupos comunitarios dijeron que la falta de avisos en espanol ya habia "
    "limitado la respuesta durante la temporada pasada, cuando el humo de los "
    "incendios cerro varias escuelas de la zona y muchas familias no supieron "
    "que hacer con sus hijos."
)

ENGLISH_REPORTING = (
    "The city council said it had not decided whether to renew the contract, "
    "and a spokesman for the department said the review would continue into the "
    "spring. Residents who spoke at the meeting had asked for more time.\n"
    "He said the budget would be published before the vote, and that the "
    "figures in it were the ones the auditors had already seen."
)

#: Enough further English that the bilingual fixture clears MIN_ENGLISH_CHARS.
ENGLISH_EXTRA = (
    "The auditors had asked for the figures in September and were told they "
    "would arrive before the end of the month, but the department said it had "
    "not been able to reconcile two of the accounts and would need longer than "
    "it had first expected to finish the work."
)

#: A menu, in Spanish. Function words are what distinguishes prose from a list,
#: in any language -- so adding Spanish must not make Spanish furniture pass.
SPANISH_MENU = "Inicio Noticias Deportes Obituarios Clasificados Empleos Contacto"


def _english_only(text: str) -> float:
    """What prose_density computed before this change."""
    words = re.findall(r"[a-zA-Z']+", text.lower())
    if not words:
        return 0.0
    return sum(1 for w in words if w in FUNCTION_WORDS) / len(words)


class TestSpanishProseIsMeasuredAsProse:
    def test_it_clears_the_floor_now(self):
        assert prose_density(SPANISH_REPORTING) >= MIN_PROSE_DENSITY

    def test_it_did_not_before(self):
        """The bug, reproduced, so the fix is aimed at something real."""
        assert _english_only(SPANISH_REPORTING) < MIN_PROSE_DENSITY

    def test_it_is_no_longer_called_furniture(self):
        assert classify_furniture(SPANISH_REPORTING) is None

    def test_accented_function_words_are_counted(self):
        """`[a-zA-Z']+` cannot see `más` or `está` at all.

        The Spanish rate comes from `language`, which matches unicode word
        characters and folds accents, so the words that carry the signal are the
        ones the English regex silently drops.
        """
        accented = (
            "La medida está más cerca de aprobarse según los concejales que "
            "hablaron después de la reunión, aunque todavía no hay una fecha."
        )
        assert prose_density(accented) > _english_only(accented)


class TestEnglishIsUntouched:
    def test_an_english_body_scores_exactly_what_it_did(self):
        """Asserted as an equality, because the 0.14 floor is tuned to it."""
        assert prose_density(ENGLISH_REPORTING) == _english_only(ENGLISH_REPORTING)

    def test_the_english_list_still_carries_the_words_that_matter(self):
        """`a`, `he` and `said` are absent from language's English list.

        Switching to it would have moved every English score. They are the reason
        this takes the max of two measures instead of replacing one.
        """
        from src.utils.language import ENGLISH_FUNCTION_WORDS

        for word in ("a", "he", "said"):
            assert word in FUNCTION_WORDS
            assert word not in ENGLISH_FUNCTION_WORDS

    def test_text_with_no_words_is_still_zero(self):
        assert prose_density("") == 0.0
        assert prose_density("12345 —— ***") == 0.0


class TestItIsTheHigherOfTheTwo:
    def test_a_menu_in_spanish_is_still_furniture(self):
        """Adding a language must not admit that language's furniture."""
        assert prose_density(SPANISH_MENU) < MIN_PROSE_DENSITY
        assert classify_furniture(SPANISH_MENU) is not None

    def test_a_bilingual_body_takes_whichever_reads_as_prose(self):
        mixed = ENGLISH_REPORTING + "\n" + SPANISH_REPORTING
        assert prose_density(mixed) >= MIN_PROSE_DENSITY


class TestTheLanguagePolicyIsUnchanged:
    def test_spanish_only_is_still_not_analysable(self):
        """Labelled and held, not progressed. Fixing the furniture test must not
        smuggle a Spanish-only story into CIN and enrichment."""
        pr = profile(SPANISH_REPORTING)
        assert pr.verdict == "spanish"
        assert pr.analysable is False

    def test_inline_english_and_spanish_is_analysable(self):
        """The bilingual case is the one that progresses -- but only with enough
        English to stand on its own.

        `MIN_ENGLISH_CHARS` is 400, so a token English sentence inside a Spanish
        story does not make it analysable. My first fixture here had 340 English
        characters and correctly came back `spanish`; the rule is the reason, and
        it is pinned below rather than worked around.
        """
        from src.utils.language import MIN_ENGLISH_CHARS

        bilingual = ENGLISH_REPORTING + "\n" + ENGLISH_EXTRA + "\n" + SPANISH_REPORTING
        pr = profile(bilingual)
        assert pr.english_chars >= MIN_ENGLISH_CHARS
        assert pr.verdict == "mixed"
        assert pr.analysable is True

    def test_a_token_english_paragraph_does_not_make_it_analysable(self):
        """Under MIN_ENGLISH_CHARS the verdict stays `spanish`."""
        from src.utils.language import MIN_ENGLISH_CHARS

        pr = profile(ENGLISH_REPORTING + "\n" + SPANISH_REPORTING)
        assert pr.english_chars < MIN_ENGLISH_CHARS
        assert pr.verdict == "spanish"
        assert pr.analysable is False

    def test_english_only_is_analysable(self):
        assert profile(ENGLISH_REPORTING).analysable is True
