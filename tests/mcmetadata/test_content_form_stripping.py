"""from_html() strips <form>/<select> markup before any extractor runs.

Found 2026-07-29 on real emissourian.com/missourian.com (TownNews) captures:
a swim-meet recap's real body was two lede sentences plus a JS-required
paywall notice (~170 chars, itself below MINIMUM_CONTENT_LENGTH), while a
`<select id="field-postal-country-super-purchase">` from an unrelated
subscription-checkout modal elsewhere on the page held 5,308 chars of
concatenated country names. trafilatura's "pick the largest/densest text
block" heuristic chose the dropdown. All four <select> elements on that page
were subscription-form fields -- zero were legitimate content -- and the
same widget, byte-identical, was the stored body for at least three
different articles across two domains (clayton-wins-home-swim-dual,
pumpkin-palooza-set-for-saturday, st-clair-man-pleads-guilty-to-kidnapping).
"""

from src.mcmetadata import content as mc_content
from src.mcmetadata import extract


class TestStripFormWidgets:
    """The narrow cleaner itself."""

    def test_select_options_are_removed(self):
        html = (
            "<html><body><p>Real article text goes here.</p>"
            '<form><select id="country"><option>United States</option>'
            "<option>Canada</option></select></form></body></html>"
        )
        cleaned = mc_content._strip_form_widgets(html)
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
        cleaned = mc_content._strip_form_widgets(html)
        assert "Option A" not in cleaned
        assert "Real article text." in cleaned

    def test_meta_and_script_tags_survive(self):
        """Deliberately narrow: unlike everything_cleaner, this must not
        touch meta/script/style/link tags other extractors depend on."""
        html = (
            '<html><head><meta name="author" content="Jane Smith">'
            "<script>var x = 1;</script></head>"
            '<body><p>Real text.</p><form><input type="text"></form>'
            "</body></html>"
        )
        cleaned = mc_content._strip_form_widgets(html)
        assert 'content="Jane Smith"' in cleaned
        assert "var x = 1;" in cleaned

    def test_html_with_no_form_or_select_is_returned_unchanged(self):
        """The cheap short-circuit: no lxml round-trip when there's nothing
        to strip."""
        html = "<html><body><p>Just an ordinary article.</p></body></html>"
        assert mc_content._strip_form_widgets(html) == html

    def test_malformed_html_falls_through_safely(self):
        """A defensive cleanup pass must never be the reason extraction
        fails outright on a document lxml can't parse."""
        html = "<not even <valid <html at all"
        result = mc_content._strip_form_widgets(html)
        assert result is not None

    def test_empty_and_none_input(self):
        assert mc_content._strip_form_widgets("") == ""
        assert mc_content._strip_form_widgets(None) is None


class TestFromHtmlEndToEnd:
    """The actual bug: a subscription-form country dropdown beats a short
    real article body under trafilatura's largest-block heuristic."""

    # Trimmed, real shape of the emissourian.com capture: a genuine short
    # lede, a JS-required paywall notice (an existing BOILERPLATE_MARKERS
    # phrase), and a subscription-checkout country <select> holding far more
    # raw text than the real content.
    REAL_LEDE = (
        "Clayton's Greyhounds turned away the challenge from the swimming "
        "Blue Jays Tuesday. Clayton picked up a dual victory in its home "
        "pool against Washington, 117-34."
    )
    PAYWALL_NOTICE = (
        "Javascript is required for you to be able to read premium "
        "content. Please enable it in your browser settings."
    )

    def _country_options(self, n=150):
        return "".join(
            f"<option>Country Name {i}, Republic of</option>" for i in range(n)
        )

    def _page(self):
        return f"""
        <html><head><title>Clayton wins home swim dual over Washington</title>
        <meta name="author" content="Arron Hustead"></head>
        <body>
        <article>
        <p>{self.REAL_LEDE}</p>
        <p>{self.PAYWALL_NOTICE}</p>
        </article>
        <div class="subscription-modal">
          <form>
            <select id="field-postal-country-super-purchase">
              {self._country_options()}
            </select>
          </form>
        </div>
        </body></html>
        """

    def test_dropdown_no_longer_wins_over_the_real_article(self):
        """The actual mechanism was verified directly against the real
        emissourian.com capture (raw HTML pulled from the archive), where
        disabling _strip_form_widgets reproduces production's exact bad
        output -- text_content becomes the 5,308-char country list. That
        real-HTML repro isn't included here (trafilatura's density scoring on
        a hand-built synthetic page doesn't reliably replicate its behavior
        on real production markup, and pinning to that exact behavior would
        make this test as fragile as the bug it guards against). This test
        instead pins the property that must hold regardless of the
        underlying library's internals: once the dropdown is stripped before
        extraction, its content cannot appear in the result."""
        html = self._page()
        result = extract("https://www.emissourian.com/sports/x.html", html)
        text = result.get("text_content") or ""
        assert "Country Name" not in text
        assert "Clayton" in text
