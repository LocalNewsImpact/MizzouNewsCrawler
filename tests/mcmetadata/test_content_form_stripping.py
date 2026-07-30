"""strip_form_widgets(): <form>/<select> markup can never become article body.

Found 2026-07-29 on real emissourian.com/missourian.com (TownNews) captures:
a swim-meet recap's real body was two lede sentences plus a JS-required
paywall notice (~170 chars, itself below MINIMUM_CONTENT_LENGTH), while a
`<select id="field-postal-country-super-purchase">` from an unrelated
subscription-checkout modal elsewhere on the page held 5,308 chars of
concatenated country names. trafilatura's "pick the largest/densest text
block" heuristic chose the dropdown. All four <select> elements on that page
were subscription-form fields -- zero were legitimate content -- and the same
widget, byte-identical, was the stored body for at least three different
articles across two domains (clayton-wins-home-swim-dual,
pumpkin-palooza-set-for-saturday, st-clair-man-pleads-guilty-to-kidnapping).

The module is loaded BY FILE PATH rather than as src.mcmetadata.form_widgets,
and that is deliberate. src/mcmetadata/__init__.py does
`from . import content, ...`, and content.py imports the whole extraction
stack at module level (dateparser, trafilatura, newspaper, goose3, boilerpy3,
readability) -- none of which is in the CI base image these jobs run in. So
ANY normal import from the package triggers that chain: a module-level
`from src.mcmetadata import content` here took down three CI jobs with
ModuleNotFoundError.

Guarding with importorskip was the wrong fix: it would make these tests skip
in CI and never run in the image either, since the PR image check mounts only
tests/dependency_contracts/ -- they would have been dead. Loading the file
directly bypasses the package __init__, and form_widgets itself imports only
lxml (which IS in the base image), so this file genuinely runs on every PR.

The alternative -- moving the helper into src/utils/ -- was rejected because
vendored mcmetadata code currently imports nothing from src/, and that
boundary is worth keeping.
"""

import importlib.util
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "mcmetadata" / "form_widgets.py"
)
_spec = importlib.util.spec_from_file_location("_form_widgets_under_test", _MODULE_PATH)
_form_widgets = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_form_widgets)
strip_form_widgets = _form_widgets.strip_form_widgets


class TestStripFormWidgets:
    def test_select_options_are_removed(self):
        html = (
            "<html><body><p>Real article text goes here.</p>"
            '<form><select id="country"><option>United States</option>'
            "<option>Canada</option></select></form></body></html>"
        )
        cleaned = strip_form_widgets(html)
        assert "United States" not in cleaned
        assert "Canada" not in cleaned
        assert "Real article text goes here." in cleaned

    def test_select_with_no_enclosing_form_is_also_removed(self):
        """kill_tags=["select"] exists specifically for this -- forms=True
        alone only catches a <select> inside a <form> ancestor."""
        html = (
            "<html><body><p>Real article text.</p>"
            '<select id="bare"><option>Option A</option></select>'
            "</body></html>"
        )
        cleaned = strip_form_widgets(html)
        assert "Option A" not in cleaned
        assert "Real article text." in cleaned

    def test_the_real_country_dropdown_shape_is_removed(self):
        """The actual production case: a long option list that outweighs a
        short real article body under a largest-block heuristic."""
        options = "".join(
            f"<option value='{i}'>Country Name {i}, Republic of</option>"
            for i in range(150)
        )
        html = (
            "<html><body>"
            "<article><p>Clayton's Greyhounds turned away the challenge "
            "from the swimming Blue Jays Tuesday.</p></article>"
            '<div class="subscription-modal"><form>'
            f'<select id="field-postal-country-super-purchase">{options}</select>'
            "</form></div></body></html>"
        )
        cleaned = strip_form_widgets(html)
        assert "Country Name" not in cleaned
        assert "Clayton" in cleaned
        # The dropdown was the overwhelming majority of the raw text; after
        # stripping, what remains must be dominated by the real article.
        assert len(cleaned) < len(html) / 2

    def test_meta_and_script_tags_survive(self):
        """Deliberately narrow: unlike content.py's everything_cleaner, this
        must not touch meta/script/style/link tags other extractors depend on
        (structured-data authorship, JSON-LD, canonical URLs)."""
        html = (
            '<html><head><meta name="author" content="Jane Smith">'
            '<link rel="canonical" href="https://example.com/x">'
            "<script>var x = 1;</script></head>"
            '<body><p>Real text.</p><form><input type="text"></form>'
            "</body></html>"
        )
        cleaned = strip_form_widgets(html)
        assert 'content="Jane Smith"' in cleaned
        assert "var x = 1;" in cleaned
        assert "canonical" in cleaned

    def test_html_with_no_form_or_select_is_returned_unchanged(self):
        """The cheap short-circuit: no lxml round-trip when there is nothing
        to strip, which is the common case."""
        html = "<html><body><p>Just an ordinary article.</p></body></html>"
        assert strip_form_widgets(html) == html

    def test_malformed_html_falls_through_safely(self):
        """A defensive cleanup pass must never be the reason extraction fails
        outright on a document lxml cannot parse."""
        result = strip_form_widgets("<not even <valid <html at all")
        assert result is not None

    def test_empty_and_none_input(self):
        assert strip_form_widgets("") == ""
        assert strip_form_widgets(None) is None
