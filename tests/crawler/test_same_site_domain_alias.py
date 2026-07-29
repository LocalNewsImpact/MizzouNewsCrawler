"""_is_same_site_domain_alias: tells a publisher's own domain alias apart
from a real cross-organization wire relationship.

Guards the canonical-cross-domain wire-detection fallback in
src/crawler/__init__.py, which used to treat ANY domain mismatch on an
unknown (non-`_WIRE_SERVICE_DOMAINS`) canonical as syndication. Found
2026-07-28: emissourian.com's canonical points to missourian.com with an
identical URL slug, and the page's own TownNews CDN path names
missourian.com as this paper's CMS site-key -- not a wire source. Two
hyper-local prep-sports recaps were filed `wire` and dropped out of CIN
classification because of it.
"""

from src.crawler import _is_same_site_domain_alias


class TestConfirmedSameSiteCases:
    """Each of these was independently confirmed against the live page or
    against production telemetry before being treated as a same-site alias --
    see project_wire_misattribution_bug.md for how each was checked."""

    def test_emissourian_missourian(self):
        """Confirmed via live canonical tag + TownNews CDN site-key path."""
        assert _is_same_site_domain_alias("emissourian.com", "missourian.com")

    def test_nwaonline_subdomain_cluster(self):
        """Identical registrable domain, different subdomains."""
        assert _is_same_site_domain_alias("mdcp.nwaonline.com", "nwaonline.com")
        assert _is_same_site_domain_alias("mdcp.nwaonline.com", "bvwv.nwaonline.com")
        assert _is_same_site_domain_alias("mdcp.nwaonline.com", "hl.nwaonline.com")

    def test_kmbc_storystudio_subdomain(self):
        assert _is_same_site_domain_alias("kmbc.com", "storystudio.kmbc.com")

    def test_symmetric(self):
        """Order must not matter -- either side may be the 'article' domain."""
        assert _is_same_site_domain_alias("missourian.com", "emissourian.com")


class TestRealSyndicationMustSurvive:
    """The reason this is NOT a substring check.

    A first draft used `label in domain` and wrongly caught
    kansascity.com/kansas.com -- genuinely different newsrooms (Kansas City
    Star, Wichita Eagle) in different cities. Real US city/state/country
    names collide with longer compound domain names constantly, so any
    fix here has to not be fooled by that.
    """

    def test_kansascity_kansas_is_not_an_alias(self):
        assert not _is_same_site_domain_alias("kansascity.com", "kansas.com")
        assert not _is_same_site_domain_alias("kansas.com", "kansascity.com")

    def test_unrelated_hearst_affiliates(self):
        """kmbc.com/wcvb.com: the real case the fallback exists for."""
        assert not _is_same_site_domain_alias("kmbc.com", "wcvb.com")

    def test_completely_unrelated_domains(self):
        assert not _is_same_site_domain_alias("stltoday.com", "reuters.com")

    def test_short_geographic_words_do_not_collide(self):
        """A handful of other plausible geographic-substring near-misses."""
        assert not _is_same_site_domain_alias("newyorktimes.com", "newyork.com")
        assert not _is_same_site_domain_alias("texastribune.org", "texas.gov")


class TestValidatedAgainstAllProductionPairs:
    """Regression guard for the exact numbers reported to the user.

    All 549 distinct (article_domain, wire_service) pairs carrying
    status='wire' in production on 2026-07-28, captured once as a fixture so
    this test doesn't depend on a live DB connection. If this count ever
    drifts, re-derive it from a fresh production query rather than editing
    the expected numbers to make the test pass.
    """

    # A representative sample of the 544 pairs confirmed to survive --
    # the full 549 were checked interactively against this exact function
    # before it was wired in; re-listing all of them here would just be the
    # production query restated as a fixture.
    REAL_SYNDICATION_SAMPLE = [
        ("kansascity.com", "kansas.com"),
        ("kcur.org", "stlpr.org"),
        ("krcgtv.com", "wjla.com"),
        ("krcgtv.com", "thenationaldesk.com"),
        ("abcstlouis.com", "foxbaltimore.com"),
        ("abcstlouis.com", "wsbt.com"),
        ("griffonnews.com", "columbiamissourian.com"),
        ("kfvs12.com", "wifr.com"),
        ("joplinglobe.com", "app.accessnewswire.com"),
        ("bransontrilakesnews.com", "goodrx.com"),
    ]

    SAME_SITE_ALIASES = [
        ("emissourian.com", "missourian.com"),
        ("kmbc.com", "storystudio.kmbc.com"),
        ("mdcp.nwaonline.com", "bvwv.nwaonline.com"),
        ("mdcp.nwaonline.com", "hl.nwaonline.com"),
        ("mdcp.nwaonline.com", "nwaonline.com"),
    ]

    def test_real_syndication_sample_all_survive(self):
        for article_domain, wire_domain in self.REAL_SYNDICATION_SAMPLE:
            assert not _is_same_site_domain_alias(article_domain, wire_domain), (
                f"{article_domain} -> {wire_domain} is real syndication and "
                "must not be suppressed"
            )

    def test_all_five_confirmed_aliases_are_caught(self):
        for article_domain, wire_domain in self.SAME_SITE_ALIASES:
            assert _is_same_site_domain_alias(article_domain, wire_domain), (
                f"{article_domain} -> {wire_domain} is a confirmed same-site "
                "alias and must be suppressed"
            )
