"""A team is not a byline, and a station is not its network.

`ABC 17 News Team` is KMIZ in Columbia crediting its own newsroom. It reached
the corpus whole, and in a table of bylines read as the station's most
prolific reporter. Worse, "abc" is a wire-service token, so the same credit
filed 31 of the station's own stories -- city council, road conditions, a barn
fire -- as ABC News copy.
"""

import pytest

from src.utils.byline_cleaner import BylineCleaner

PUBLICATIONS = {"ABC 17 KMIZ News", "KSPR/KY3", "KPLR11/Fox 2 Now", "KHQA"}


@pytest.fixture
def cleaner(monkeypatch):
    """Fixed publication and organisation lists: the live ones read the
    crawler database, which CI does not have."""
    cleaner = BylineCleaner(enable_telemetry=False)
    monkeypatch.setattr(cleaner, "get_publication_names", lambda *a, **k: PUBLICATIONS)
    monkeypatch.setattr(cleaner, "get_organization_names", lambda *a, **k: set())
    return cleaner


def clean(cleaner, byline, source=None):
    if source is None:
        return cleaner.clean_byline(byline), list(cleaner._detected_wire_services)
    return (
        cleaner.clean_byline(byline, source_canonical_name=source),
        list(cleaner._detected_wire_services),
    )


class TestAStationIsNotItsNetwork:
    @pytest.mark.parametrize(
        "byline", ["ABC 17 News Team", "By ABC 17 News Team", "ABC 17"]
    )
    def test_on_its_own_site_it_is_not_wire(self, cleaner, byline):
        _, wire = clean(cleaner, byline, "ABC 17 KMIZ News")
        assert wire == []

    def test_the_station_is_matched_however_it_is_spaced(self, cleaner):
        """ "FOX 2" in the byline, "Fox 2 Now" in our sources table."""
        _, wire = clean(cleaner, "FOX 2 Digital Team", "KPLR11/Fox 2 Now")
        assert wire == []

    def test_another_stations_copy_is_still_wire(self, cleaner):
        """FOX 8 is not KY3. Copy from elsewhere stays copy from elsewhere."""
        _, wire = clean(cleaner, "FOX 8 Staff", "KSPR/KY3")
        assert wire != []

    def test_the_network_itself_is_still_wire(self, cleaner):
        _, wire = clean(cleaner, "ABC News", "KSPR/KY3")
        assert wire == ["ABC News"]

    def test_its_reporters_keep_their_bylines(self, cleaner):
        authors, _ = clean(
            cleaner, "Mitchell Kaminski, ABC 17 News", "ABC 17 KMIZ News"
        )
        assert authors == ["Mitchell Kaminski"]


class TestATeamIsNotAByline:
    @pytest.mark.parametrize(
        "byline, source",
        [
            ("ABC 17 News Team", "ABC 17 KMIZ News"),
            ("ABC 17 News Team", None),
            ("FOX 8 Staff", "KSPR/KY3"),
            ("Khqa Desk.", "KHQA"),
            ("NPR Washington Desk", "KSPR/KY3"),
            ("CNN Newsource Staff", "KSPR/KY3"),
        ],
    )
    def test_a_team_credit_leaves_no_author(self, cleaner, byline, source):
        authors, _ = clean(cleaner, byline, source)
        assert authors == []

    def test_the_wire_it_names_is_still_read(self, cleaner):
        """Dropped from the authors, not from the text: the credit is also
        the evidence that the story is CNN copy."""
        _, wire = clean(cleaner, "CNN Newsource Staff", "KSPR/KY3")
        assert wire == ["CNN NewsSource"]

    @pytest.mark.parametrize(
        "author",
        [
            "Sarah Motter",
            "Marcus Officer",
            "Liaudwin Seaberry Jr.",
            "Cole B. Lee",
            "Christopher Replogle",
            # A wire token as a surname: "fox" is in WIRE_SERVICES.
            "Madeline Fox",
        ],
    )
    def test_a_person_is_still_a_name(self, cleaner, author):
        assert cleaner._identify_part_type(author) == "name"
        assert clean(cleaner, author, "KSPR/KY3")[0] == [author]

    def test_a_full_stop_does_not_hide_the_desk(self, cleaner):
        assert cleaner._identify_part_type("Khqa Desk.") == "title"

    def test_a_staff_writer_keeps_the_writer(self, cleaner):
        authors, _ = clean(cleaner, "Jane Doe, Staff Writer", "Columbia Missourian")
        assert authors == ["Jane Doe"]


class TestTheQueueAndTheApplyReadAlike:
    """The queue shows a name as `split_names` reads it; a decision about it
    has to reach every string the queue read it out of. "ABC 17" was dropped
    on 2026-09-24 and applied to no article, because the articles carry
    "ABC 17 News Team" and the apply compared against the untrimmed part."""

    def test_a_decision_reaches_the_string_the_name_was_read_from(self):
        from src.services.byline_review import replace_name

        assert replace_name("ABC 17 News Team", "ABC 17", []) == ""

    def test_the_co_author_is_kept(self):
        from src.services.byline_review import replace_name

        assert (
            replace_name("Sarah Motter, ABC 17 News Team", "ABC 17", [])
            == "Sarah Motter"
        )

    def test_a_string_without_the_name_is_left_alone(self):
        from src.services.byline_review import replace_name

        assert replace_name("Ryan Shiner", "ABC 17", []) is None


class TestTheQueueAsksTheCleaner:
    """One judgement of what is a person, made in the cleaner."""

    def test_a_desk_is_not_a_person(self):
        from src.services.byline_review import NOT_A_PERSON, review_rows

        (row,) = review_rows([("Khqa Desk.", "khqa.com", "Sinclair", 1)])
        assert NOT_A_PERSON in row.signals

    @pytest.mark.parametrize("name", ["Marcus Officer", "Madeline Fox", "Sarah Motter"])
    def test_a_person_raises_nothing(self, name):
        from src.services.byline_review import review_rows

        (row,) = review_rows([(name, "kctv5.com", "Gray", 3)])
        assert row.signals == ()
