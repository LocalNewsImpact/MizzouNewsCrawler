"""Strip <form>/<select> markup before content extraction picks a block.

Deliberately its own module, importing ONLY lxml. content.py pulls in the
whole extraction stack (dateparser, trafilatura, newspaper, goose3, boilerpy3,
readability) at module level, and those live in the crawler/processor images
but NOT in the CI base image. Anything importing content.py can therefore only
be tested inside a built crawler image -- and the PR image check mounts just
tests/dependency_contracts/, so such a test would skip in CI and never run in
the image either, i.e. be dead.

lxml is in the base image, so keeping this here means its tests actually run
on every PR.
"""

from __future__ import annotations

from lxml.html.clean import Cleaner

# Dropdown option lists are never real article prose on a legitimate page -- a
# country/state selector inside a subscription-purchase widget is pure form
# furniture -- but the "pick the largest/densest text block" heuristic every
# extractor uses has no way to know that, and a long option list easily
# outweighs a real but short article body in raw text volume.
#
# Confirmed live on emissourian.com/missourian.com (TownNews): a swim-meet
# recap's actual body was two lede sentences plus a JS-required paywall notice
# (~170 chars total, itself below MINIMUM_CONTENT_LENGTH), while a
# `<select id="field-postal-country-super-purchase">` from an unrelated
# subscription-checkout modal elsewhere on the page held 5,308 chars of
# concatenated country names. trafilatura picked the dropdown. All four
# <select> elements on that page were subscription-form fields
# (*-super-purchase ids) -- zero were legitimate content -- and that same
# widget, byte-identical, was the stored body for at least three articles
# across two domains.
#
# Deliberately narrow: only forms/selects are removed. meta/script/style/link
# tags are left untouched so extractors that read them (structured-data
# authorship, JSON-LD, canonical links) are unaffected -- this is NOT the same
# as content.py's `everything_cleaner`, which is far more aggressive and is
# wired only to the readability path.
_form_stripping_cleaner = Cleaner(
    scripts=False,
    javascript=False,
    comments=False,
    style=False,
    links=False,
    meta=False,
    page_structure=False,
    processing_instructions=False,
    embedded=False,
    frames=False,
    forms=True,
    annoying_tags=False,
    remove_unknown_tags=False,
    safe_attrs_only=False,
    kill_tags=["select"],  # belt-and-suspenders: catches a <select> with no
    # enclosing <form>, which forms=True alone would miss.
)


def strip_form_widgets(html_text: str) -> str:
    """Remove <form>/<select> markup so it can never be mistaken for article
    content. Returns the input unchanged if it isn't parseable HTML -- this is
    a defensive cleanup pass, not a required one, so a malformed document
    should fall through to the extractors exactly as before this existed."""
    if (
        not html_text
        or "<select" not in html_text.lower()
        and "<form" not in html_text.lower()
    ):
        # Cheap short-circuit: skip the lxml round-trip entirely when there is
        # nothing for this pass to do, which is the common case.
        return html_text
    try:
        return _form_stripping_cleaner.clean_html(html_text)
    except Exception:
        return html_text
