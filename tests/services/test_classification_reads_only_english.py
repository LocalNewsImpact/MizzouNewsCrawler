"""CIN reads the English half of a body, and refuses a Spanish one.

A Spanish story is still enriched: it goes on at `labeled` with no CIN label
(decided 2026-10-16).

CIN is English-trained, so a Spanish body produces a label that means nothing:
two `redlatinastl.com` articles sat at `Political life` before somebody set
`non_english` by hand, and `abc17news.com` carries Spanish `CNN en Espanol`
wire already labelled `Civic Life` and `Sports`.

Bilingual bodies are the case that makes this a filter on the TEXT rather than
on the record. `redlatinastl.com` runs each story twice on one page, English
then Spanish, and every sampled article measured 46-57% Spanish by paragraph --
so discarding the record loses real local reporting while classifying the whole
body feeds the model two languages at once.
"""

import json
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from src.services.classification_service import ArticleClassificationService
from src.utils import language

HEAD_EN = "Council approves budget"
EN = (
    "The city council voted on Tuesday to approve the budget for the coming "
    "year, and the mayor said the plan would protect the services that "
    "residents have come to rely on."
)
EN_2 = (
    "Two of the most influential leaders travelled to the district this week "
    "and told the crowd that the cuts would fall hardest on families who can "
    "least afford them."
)
ES = (
    "El concejo de la ciudad voto el martes para aprobar el presupuesto del "
    "proximo ano, y la alcaldesa dijo que el plan protegeria los servicios "
    "que los residentes necesitan."
)
ES_2 = (
    "Dos de los lideres mas influyentes viajaron al distrito esta semana y "
    "dijeron a la multitud que los recortes afectarian mas a las familias que "
    "menos pueden pagarlos."
)


class _Article:
    def __init__(self, raw=None, text=None, title=None, status="cleaned"):
        self.raw = raw
        self.text = text
        self.title = title
        self.status = status
        self.id = "article-1"
        self.metadata = None


def _service() -> ArticleClassificationService:
    session = MagicMock(spec=Session)
    session.bind = None
    session.scalars = MagicMock(return_value=iter(()))
    return ArticleClassificationService(session=session)


class TestEnglishIsUnchanged:
    def test_an_english_body_reaches_the_classifier_whole(self):
        out = _service()._prepare_text(_Article(text=f"{EN}\n\n{EN_2}", title=HEAD_EN))
        assert HEAD_EN in out
        assert EN in out
        assert EN_2 in out

    def test_a_short_brief_is_not_dropped(self):
        """The filter must not reintroduce a word-count floor: local news runs
        short, which is why `looks_like_article` carries none."""
        brief = (
            "The Seattle City Council adopted its 2025 budget on Thursday and "
            "voted to loosen restrictions on the tax it levies on the largest "
            "businesses in the city."
        )
        assert brief in _service()._prepare_text(_Article(text=brief))


class TestOnlyTheEnglishHalfOfABilingualBody:
    @staticmethod
    def _bilingual() -> str:
        return "\n\n".join([EN, EN_2, ES, ES_2] * 2)

    def test_the_spanish_paragraphs_do_not_reach_the_classifier(self):
        out = _service()._prepare_text(_Article(text=self._bilingual(), title=HEAD_EN))
        assert EN in out
        assert ES not in out
        assert "presupuesto" not in out

    def test_the_headline_is_still_classified(self):
        out = _service()._prepare_text(_Article(text=self._bilingual(), title=HEAD_EN))
        assert out.startswith(HEAD_EN)

    def test_the_stored_body_is_not_rewritten(self):
        article = _Article(text=self._bilingual(), title=HEAD_EN)
        before = str(article.text)
        _service()._prepare_text(article)
        assert article.text == before


class TestASpanishBodyIsRefusedAndFiled:
    def test_prepare_text_returns_no_body_for_spanish(self):
        out = _service()._prepare_text(_Article(text=f"{ES}\n\n{ES_2}"))
        assert out is None

    def test_a_spanish_body_is_not_classified_on_its_headline(self):
        """Six WSU stories from nwpb.org and Spokane Public Radio carried CIN
        labels on 2026-10-16: the body was refused, the Spanish headline was
        classified on its own."""
        article = _Article(
            text=f"{ES}\n\n{ES_2}", title="Grupos buscan proteger a los inmigrantes"
        )
        assert _service()._prepare_text(article) is None

    def test_a_story_with_no_body_is_still_classified_on_its_headline(self):
        assert _service()._prepare_text(_Article(title=HEAD_EN)) == HEAD_EN

    def test_the_story_goes_to_enrichment_with_no_cin_label(self):
        """Written through the session, as `save_article_classification` is."""
        service = _service()
        body = f"{ES}\n\n{ES_2}"
        found = language.profile(body)
        service._send_spanish_to_enrichment("article-1", found)

        move, drop = (c.args for c in service.session.execute.call_args_list)
        sql, params = str(move[0]), move[1]
        assert params["id"] == "article-1"
        assert "THEN 'labeled'" in sql, "labeled is what enrichment selects"
        assert "status IN ('cleaned', 'local')" in sql, "an enriched row stays"
        assert "primary_label = NULL" in sql
        assert language.NON_ENGLISH_STATUS not in sql
        assert "DELETE FROM article_labels" in str(drop[0])
        assert drop[1] == {"id": "article-1"}
        recorded = json.loads(params["note"])
        assert recorded["primary"] == language.SPANISH
        assert recorded["verdict"] == "spanish"
        assert recorded["spanish_share"] == 1.0
        assert recorded["detector"] == "function_word_rate_by_paragraph"

    def test_the_write_targets_only_the_language_key(self):
        """`jsonb_set` on one path, so a sibling metadata key survives: these
        rows carry `wsu_notebook.inputtext`, which is a study measurement."""
        service = _service()
        service._send_spanish_to_enrichment(
            "article-1", language.profile(f"{ES}\n\n{ES_2}")
        )
        stmt, params = service.session.execute.call_args_list[0].args
        sql = str(stmt)
        assert params["key"] == "{" + language.LANGUAGE_METADATA_KEY + "}"
        assert "jsonb_set" in sql
        assert "coalesce(metadata" in sql
        # create_missing, so the key is added rather than requiring a read
        assert "true" in sql


class TestTheBodyFieldIsTheCleanedOne:
    def test_text_is_preferred_over_raw(self):
        """Unchanged by the language filter: `text` is the cleaned column, `raw` the capture."""
        nav = "Skip to main content Home Categories Classifieds Columns"
        out = _service()._prepare_text(_Article(raw=nav, text=EN))
        assert EN in out
        assert nav not in out

    def test_raw_is_the_fallback(self):
        assert EN in _service()._prepare_text(_Article(raw=EN, text="  \n "))

    def test_an_empty_article_still_yields_nothing(self):
        assert _service()._prepare_text(_Article("", "  ", " ")) is None
