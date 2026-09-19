"""The structured-data title gets the publication stripped off it too.

`<title>` and JSON-LD `headline` on a news page are conventionally the
headline, a separator, and the publication -- and the publication is already
on the row. `titles.from_html` has always stripped it. `extract()` does not
call `from_html` when structured data supplied a title: that branch WINS, and
`from_html` is the fallback. So the strip only ran when JSON-LD and og:title
had both failed.

Found 2026-09-19 on the Port Townsend Leader, whose JSON-LD `headline` is the
full "<headline> - Port Townsend & Jefferson County Leader". 196 of the 220
articles extracted from it that day carried the masthead in the stored
headline; the 6 extracted on 09-17 and 4 on 09-18, before that run, carried
none. The row's own `title_extraction_method` says `structured_json_ld`, which
is how the path was identified.

The masthead also costs dedup: `normalized_article_title` is derived from the
same string and is what identifies one story at two URLs, so a title carrying
the publication normalises to something no other copy matches.

Two separate defects are covered here. The second is that
`_extract_from_meta_tags` returned og:title without decoding entities, so the
real page's "Port Townsend &amp; Jefferson County Leader" travelled undecoded.
"""

from src.mcmetadata import extract
from src.mcmetadata.structured_data import _extract_from_meta_tags
from src.mcmetadata.titles import SHORT_TITLE_THRESHOLD, from_html, strip_publication

MASTHEAD = "Port Townsend & Jefferson County Leader"
HEADLINE = "OlyCAP conducts annual point-in-time count of homeless people"
URL = "https://www.ptleader.com/stories/olycap,195090"


def _page(jsonld_headline=None, og_title=None, title_tag=None, h1=None):
    """A page shaped like the real capture: the same string in every slot."""
    head = []
    if jsonld_headline is not None:
        head.append(
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"NewsArticle",'
            f'"headline":"{jsonld_headline}",'
            '"datePublished":"2025-02-05T04:00:00-08:00"}'
            "</script>"
        )
    if og_title is not None:
        head.append(f'<meta property="og:title" content="{og_title}">')
    if title_tag is not None:
        head.append(f"<title>{title_tag}</title>")
    body = f"<h1>{h1}</h1>" if h1 is not None else ""
    body += "<article><p>" + ("Real prose about the count. " * 40) + "</p></article>"
    return f"<html><head>{''.join(head)}</head><body>{body}</body></html>"


# --------------------------------------------------------------------------
# strip_publication: what it removes, and what it must leave alone
# --------------------------------------------------------------------------


def test_the_real_masthead_suffix_is_removed():
    assert strip_publication(f"{HEADLINE} - {MASTHEAD}") == HEADLINE


def test_a_headline_with_no_separator_survives_whole():
    plain = "County sends glass to landfill as recyclers halt operations"
    assert strip_publication(plain) == plain


def test_a_hyphen_inside_a_word_is_not_a_separator():
    # The separator pattern requires spaces around the hyphen, which is what
    # keeps this from becoming "fect Start: 8 Cats Find Homes".
    assert strip_publication("Purr-fect Start: 8 Cats Find Homes") == (
        "Purr-fect Start: 8 Cats Find Homes"
    )
    assert strip_publication("Van-Far girls widen gap") == "Van-Far girls widen gap"


def test_two_long_parts_keep_only_the_first():
    # Documenting the heuristic rather than endorsing it. When the leading part
    # is at or over the threshold the tail is taken for one or more suffixes
    # and dropped, even where it is really the rest of the headline. That is
    # pre-existing behaviour on every site and is deliberately NOT changed
    # here: this fix is about where the strip runs, not how it decides.
    both = "Port adopts 2025 budget - rates and fees will rise by 3.8 percent"
    assert strip_publication(both) == "Port adopts 2025 budget"


def test_a_short_leading_part_is_treated_as_a_prefix():
    # "Sports" is under the threshold and the remainder is not, so the short
    # side is the section label and the long side is the headline.
    assert len("Sports") < SHORT_TITLE_THRESHOLD
    assert strip_publication(
        "Sports - Hatchet-wielding wife convicted for 2021 attack"
    ) == ("Hatchet-wielding wife convicted for 2021 attack")


def test_a_prefix_removal_leaves_no_leading_space():
    # The slices are offset by 2 against a 3-character " - " separator, so
    # every prefix removal used to leave the space behind. `from_html` ended
    # with its own `.strip()` and hid it while it was the only caller; the
    # structured-data path is a direct caller and would have stored it.
    got = strip_publication("Sports - Hatchet-wielding wife convicted for 2021 attack")
    assert got == got.strip()
    assert not got.startswith(" ")


def test_an_empty_title_does_not_raise():
    assert strip_publication("") == ""


# --------------------------------------------------------------------------
# from_html: extracting the helper changed none of its behaviour
# --------------------------------------------------------------------------


def test_from_html_still_strips_the_publication():
    html = _page(
        og_title=f"{HEADLINE} - {MASTHEAD}", title_tag=f"{HEADLINE} - masthead"
    )
    assert from_html(html) == HEADLINE


def test_from_html_falls_back_to_the_supplied_title():
    assert from_html("<html><head></head><body></body></html>", HEADLINE) == HEADLINE


def test_from_html_returns_none_when_the_page_says_nothing():
    assert from_html("<html><head></head><body></body></html>") is None


# --------------------------------------------------------------------------
# extract(): the regression itself -- the structured branch, which wins
# --------------------------------------------------------------------------


def test_a_jsonld_headline_carrying_the_masthead_is_stripped():
    found = extract(URL, _page(jsonld_headline=f"{HEADLINE} - {MASTHEAD}"))
    assert found["title_extraction_method"] == "structured_json_ld"
    assert found["article_title"] == HEADLINE


def test_the_normalized_title_used_for_dedup_is_also_clean():
    # Two copies of one story, one of whose pages appends the masthead. They
    # must normalise to the same string or dedup never pairs them.
    with_masthead = extract(URL, _page(jsonld_headline=f"{HEADLINE} - {MASTHEAD}"))
    without = extract(URL, _page(jsonld_headline=HEADLINE))
    assert (
        with_masthead["normalized_article_title"] == without["normalized_article_title"]
    )
    assert MASTHEAD.lower() not in with_masthead["normalized_article_title"]


def test_an_og_title_masthead_is_stripped_when_there_is_no_jsonld():
    found = extract(URL, _page(og_title=f"{HEADLINE} - {MASTHEAD}"))
    assert found["title_extraction_method"] == "structured_meta_tags"
    assert found["article_title"] == HEADLINE


def test_a_clean_structured_headline_is_left_alone():
    found = extract(URL, _page(jsonld_headline=HEADLINE))
    assert found["article_title"] == HEADLINE


# --------------------------------------------------------------------------
# the entity leak on the meta-tag path
# --------------------------------------------------------------------------


def test_og_title_entities_are_decoded():
    html = _page(og_title=f"{HEADLINE} - Port Townsend &amp; Jefferson County Leader")
    assert _extract_from_meta_tags(html)["title"] == f"{HEADLINE} - {MASTHEAD}"


def test_an_entity_in_the_headline_itself_is_decoded_and_kept():
    html = _page(og_title=f"Smith &amp; Jones win the contract - {MASTHEAD}")
    assert _extract_from_meta_tags(html)["title"] == (
        f"Smith & Jones win the contract - {MASTHEAD}"
    )
