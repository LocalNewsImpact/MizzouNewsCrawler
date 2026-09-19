"""A body is measured paragraph by paragraph, and only its English is analysed.

The shapes under test are the ones production actually serves:
`redlatinastl.com` runs one story twice on a page, English then Spanish, and
`abc17news.com` carries monolingual `CNN en Espanol` wire.
"""

from __future__ import annotations

import pytest

from src.utils import language as L

# Real shapes, shortened. Each paragraph has to clear MIN_PARAGRAPH_WORDS.
ENGLISH_PARA = (
    "The city council voted on Tuesday to approve the budget for the coming "
    "year, and the mayor said the plan would protect services that residents "
    "have come to rely on."
)
ENGLISH_PARA_2 = (
    "Two of the most influential leaders travelled to the district this week "
    "and told a crowd that the cuts would fall hardest on the families who "
    "can least afford them."
)
SPANISH_PARA = (
    "El concejo de la ciudad voto el martes para aprobar el presupuesto del "
    "proximo ano, y la alcaldesa dijo que el plan protegeria los servicios "
    "que los residentes necesitan."
)
SPANISH_PARA_2 = (
    "Dos de los lideres mas influyentes viajaron al distrito esta semana y "
    "dijeron a la multitud que los recortes afectarian mas a las familias que "
    "menos pueden pagarlos."
)


class TestAParagraphIsTheUnitOfDetection:
    def test_an_english_paragraph_is_english(self):
        assert L.paragraph_language(ENGLISH_PARA) == L.ENGLISH

    def test_a_spanish_paragraph_is_spanish(self):
        assert L.paragraph_language(SPANISH_PARA) == L.SPANISH

    def test_a_fragment_is_not_guessed_at(self):
        """Below MIN_PARAGRAPH_WORDS the answer is None, not a coin flip.

        Datelines, photo credits and bylines all live here, and `lingua`
        answering ENGLISH with high confidence for an empty body is the
        failure this avoids.
        """
        assert L.paragraph_language("WENATCHEE -- World photo/Renee Diaz") is None
        assert L.paragraph_language("") is None
        assert L.paragraph_language(None) is None

    def test_a_word_in_both_languages_decides_nothing(self):
        """`a`, `no` and `he` are in neither set, so they cannot tip a verdict."""
        for word in ("a", "no", "he"):
            assert word not in L.ENGLISH_FUNCTION_WORDS
            assert word not in L.SPANISH_FUNCTION_WORDS

    def test_accents_do_not_change_the_count(self):
        """The WSU import mangled accents; `mas` and `mas` must count alike."""
        plain = L.function_word_rates("esto es mas de lo que era")
        accented = L.function_word_rates("esto es más de lo que era")
        assert plain == accented


class TestAMonolingualBody:
    def test_english_is_analysed_as_it_stands(self):
        body = f"{ENGLISH_PARA}\n\n{ENGLISH_PARA_2}"
        assert L.profile(body).verdict == "english"
        assert L.analysis_text(body) == body

    def test_spanish_is_refused(self):
        body = f"{SPANISH_PARA}\n\n{SPANISH_PARA_2}"
        found = L.profile(body)
        assert found.verdict == "spanish"
        assert found.spanish_share == pytest.approx(1.0)
        assert L.analysis_text(body) is None
        assert not found.analysable


class TestABilingualBody:
    """The shape that makes whole-document detection useless."""

    @staticmethod
    def _bilingual() -> str:
        # ~50/50 by character, as measured on every redlatinastl sample.
        return "\n\n".join(
            [ENGLISH_PARA, ENGLISH_PARA_2, SPANISH_PARA, SPANISH_PARA_2] * 2
        )

    def test_it_is_mixed_not_spanish(self):
        found = L.profile(self._bilingual())
        assert found.verdict == "mixed"
        assert 0.3 < found.spanish_share < 0.7
        assert found.analysable

    def test_only_the_english_reaches_analysis(self):
        body = self._bilingual()
        analysed = L.analysis_text(body)
        assert analysed == L.english_text(body)
        assert ENGLISH_PARA in analysed
        assert SPANISH_PARA not in analysed
        assert "presupuesto" not in analysed

    def test_the_stored_body_is_never_modified(self):
        body = self._bilingual()
        before = str(body)
        L.analysis_text(body)
        assert body == before

    def test_undetermined_blocks_are_dropped_not_kept(self):
        """A caption between the halves belongs to one of them; keeping it
        would put Spanish back into the text this function exists to clean."""
        body = f"{ENGLISH_PARA}\n\nFoto: Renee Diaz\n\n{SPANISH_PARA}"
        assert "Foto" not in L.english_text(body)

    def test_spanish_dominant_without_enough_english_is_refused(self):
        """A stray English sentence does not make a Spanish article analysable."""
        body = "\n\n".join([SPANISH_PARA, SPANISH_PARA_2] * 4 + [ENGLISH_PARA])
        found = L.profile(body)
        assert found.verdict == "spanish"
        assert L.analysis_text(body) is None


class TestTheFilterFailsOpen:
    """Only a positive Spanish verdict refuses. Anything unmeasurable passes."""

    def test_unmeasurable_text_is_passed_through(self):
        assert L.profile("Budget vote").verdict == "undetermined"
        assert L.analysis_text("Budget vote") == "Budget vote"

    def test_empty_and_none_are_returned_unchanged(self):
        assert L.analysis_text("") == ""
        assert L.analysis_text(None) is None

    def test_a_short_real_brief_is_not_dropped(self):
        """`looks_like_article` carries no word floor because local news runs
        short; this filter must not reintroduce one."""
        brief = (
            "The Seattle City Council has officially adopted its 2025 budget "
            "on Thursday, and in doing so voted to loosen restrictions on the "
            "tax it levies on the largest businesses in the city."
        )
        assert L.analysis_text(brief) == brief


class TestParagraphSplitting:
    def test_single_newlines_separate_languages(self):
        """A body stored with single newlines would otherwise arrive as one
        block carrying both languages."""
        body = f"{ENGLISH_PARA}\n{SPANISH_PARA}"
        assert len(L.paragraphs(body)) == 2
        assert L.profile(body).verdict in ("mixed", "spanish")

    def test_blank_lines_also_separate(self):
        assert len(L.paragraphs(f"{ENGLISH_PARA}\n\n{ENGLISH_PARA_2}")) == 2

    def test_no_text_yields_no_paragraphs(self):
        assert L.paragraphs(None) == []
        assert L.paragraphs("   ") == []


class TestSharesAreOverCharactersNotParagraphs:
    def test_a_longer_spanish_half_is_not_understated(self):
        """Paragraph counts would call this even; the Spanish half is longer."""
        body = "\n\n".join([ENGLISH_PARA, SPANISH_PARA + " " + SPANISH_PARA_2])
        found = L.profile(body)
        assert found.english_paragraphs == found.spanish_paragraphs == 1
        assert found.spanish_share > 0.5


class TestSpanishIsTerminal:
    """`non_english` is an end state, not a queue.

    There is no English text to classify and CIN is English-trained, so a
    Spanish record is finished until a Spanish-language classifier exists. A
    re-extraction cannot change the answer -- the page is in Spanish.
    """

    def test_the_status_is_selected_by_no_analysis_stage(self):
        classify_selects = ("cleaned", "local")
        enrich_selects = ("labeled",)
        export_selects = ("enriched", "enrichment_skipped")
        assert L.NON_ENGLISH_STATUS not in classify_selects
        assert L.NON_ENGLISH_STATUS not in enrich_selects
        assert L.NON_ENGLISH_STATUS not in export_selects

    def test_a_spanish_body_is_never_analysable(self):
        body = "\n\n".join([SPANISH_PARA, SPANISH_PARA_2] * 2)
        found = L.profile(body)
        assert found.verdict == "spanish"
        assert not found.analysable
        assert L.analysis_text(body) is None
        # Nothing about a second look changes it.
        assert L.analysis_text(body) is None

    def test_the_verdict_is_recorded_for_a_future_spanish_classifier(self):
        """The status says 'not for this pipeline'; the metadata key is how the
        Spanish corpus is found once there is a classifier for it."""
        assert L.LANGUAGE_METADATA_KEY == "language"
