"""The content filters were excluding reported news, measured four ways.

385 reviewed weather decisions, 262 opinion, 67 wire. What the reviewer
did with them is the only evidence any of these rules have, and it said
the same thing each time: the filters were matching a word rather than
recognising a kind of article.

The two errors do not cost the same, which is why every fix here leans
one way. A forecast that reaches the queue is a click. A flood story
that never reaches it is gone -- no row, no telemetry, nothing
downstream that can see it went missing.
"""

import pytest

from src.cli.commands.byline_surname_repair import _rebuilt_name
from src.utils.content_type_detector import ContentTypeDetector


def _detector():
    detector = ContentTypeDetector.__new__(ContentTypeDetector)
    return detector


# --- weather: a bulletin, not a subject ---------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "Winter Weather Advisory issued March 1 at 11:58AM CST until March 2",
        "PM Weather Update For Thursday 3/19/2026",
        "Friday, March 20 Bus Stop Forecast",
    ],
)
def test_an_unbylined_bulletin_is_still_excluded(title):
    """What the reviewer kept out: the automated ones, no byline."""
    result = _detector()._detect_weather(
        url="https://example.com/weather/x",
        title=title,
        keywords=[],
        meta_description=None,
        content="Short bulletin text.",
        author=None,
    )
    assert result is not None
    assert result.status == "weather"
    assert result.reason == "matched_weather_bulletin"


@pytest.mark.parametrize(
    "title",
    [
        # Every one of these was excluded, and restored by a reviewer.
        "Salute to Veterans (Desert Storm/Desert Shield 2026)",
        "A Hands-On Look Inside the Brain for Annapolis Students",
        "Active Shooter Training",
        "Trophy rainbow takes unusual path to Roaring River State Park",
        "Snowplowing in St. Louis is on track, official says",
        "Governor Kehoe declares State of Emergency due to storm threat",
        "City of Columbia receives public feedback on stormwater management plan",
        "Photography from the Train Show at Mitchell Park Domes",
    ],
)
def test_a_topic_word_no_longer_takes_a_story(title):
    """`rain` matched inside `training`, `brain`, `rainbow`; `storm`
    inside `Desert Storm` and `stormwater`. One substring was enough."""
    assert (
        _detector()._detect_weather(
            url="https://example.com/news/story",
            title=title,
            keywords=[],
            meta_description=None,
            content="Reported copy. " * 120,
            author="A Reporter",
        )
        is None
    )


def test_a_written_forecast_goes_through():
    """ "if there is a byline and written text, we are going to need to
    let it through" -- too much weather-related news is wrapped up in
    these: fires, accidents, floods, closures."""
    assert (
        _detector()._detect_weather(
            url="https://example.com/weather/first-alert",
            title="FIRST ALERT WEATHER: Strong to severe storms tonight",
            keywords=[],
            meta_description=None,
            content="The Ozarks will see a warm-up. " * 90,
            author="Nick Kelly",
        )
        is None
    )


def test_a_byline_over_a_stub_is_not_written_text():
    """A byline alone does not make a bulletin an article: the shortest
    of these ran 738 characters."""
    detector = _detector()
    assert detector._is_authored("A Reporter", "Too short.") is False
    assert detector._is_authored(None, "Long copy. " * 200) is False
    assert detector._is_authored("A Reporter", "A sentence here. " * 120) is True


# --- opinion: a columnist path says who wrote it, not what it is --------------


def test_a_columnist_path_is_not_an_opinion_signal():
    """stltoday files reported news under /column/joe-holleman/: 17 of
    19 reviewed were restored as news."""
    assert "column" not in ContentTypeDetector._OPINION_URL_SEGMENTS
    assert "columns" not in ContentTypeDetector._OPINION_URL_SEGMENTS
    assert "columnists" not in ContentTypeDetector._OPINION_URL_SEGMENTS


def test_an_opinion_section_still_is_one():
    """The trade is the columnist path, not the section."""
    for segment in ("opinion", "opinions", "editorial", "letters"):
        assert segment in ContentTypeDetector._OPINION_URL_SEGMENTS


# --- wire: a paper does not syndicate to itself -------------------------------


def test_a_paper_is_not_a_wire_service_to_its_own_newsroom():
    """ "Jefferson City News Tribune" slugs to news-tribune, and the host
    is newstribune.com -- hyphenless. The comparison missed, and 87 of
    the paper's own articles, bylined its own staff, were called
    syndicated."""
    bio = "Trevor Hahn is a reporter for the Jefferson City News Tribune"
    detected = _detector()._detect_cross_publication_byline(
        bio, "https://www.newstribune.com/news/2026/mar/01/story/"
    )
    assert detected == ("Jefferson City News Tribune", False)


def test_the_same_byline_elsewhere_is_syndication():
    bio = "Trevor Hahn is a reporter for the Jefferson City News Tribune"
    detected = _detector()._detect_cross_publication_byline(
        bio, "https://www.columbiamissourian.com/news/story/"
    )
    assert detected == ("Jefferson City News Tribune", True)


# --- the surname repair -------------------------------------------------------


def test_a_removed_surname_is_rebuilt():
    meta = {"authors": ["Jeffrey"], "wire_services": ["fox"]}
    assert _rebuilt_name("Jeffrey", meta) == "Jeffrey Fox"


def test_a_real_network_credit_is_left_alone():
    """ "NBC Olympics" is a credit, not a person."""
    meta = {"authors": ["NBC Olympics"], "wire_services": ["nbc"]}
    assert _rebuilt_name("NBC Olympics", meta) is None


@pytest.mark.parametrize(
    "author,meta",
    [
        # Two authors: the word order is no longer known.
        ("Molly", {"authors": ["Molly", "Kate"], "wire_services": ["fox"]}),
        # Two removed tokens: same.
        ("Chris", {"authors": ["Chris"], "wire_services": ["fox", "ap"]}),
        # The stored byline is not the one the metadata describes.
        ("Someone Else", {"authors": ["Jeffrey"], "wire_services": ["fox"]}),
        (None, {"authors": ["Jeffrey"], "wire_services": ["fox"]}),
    ],
)
def test_an_ambiguous_row_is_left_alone(author, meta):
    """A byline invented here would be indistinguishable from one
    somebody reported."""
    assert _rebuilt_name(author, meta) is None
