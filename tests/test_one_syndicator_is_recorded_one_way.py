"""The same syndicator, written down two ways, is two syndicators.

`articles.wire` holds 14,681 values that are a service name and 6,373
that are a bare domain, because `canonical_cross_domain` records the host
the canonical pointed at while every other method records a name. The
Columbia Missourian is `Columbia Missourian` on the rows a byline found
and `columbiamissourian.com` on the 600 a canonical found.

The review console's service filter groups by value, so it offers the
same newsroom twice and each option finds part of its work.
"""

from src.cli.commands.wire_signal_alignment import _renamed

NAMES = {
    "columbiamissourian.com": "Columbia Missourian",
    "komu.com": "KOMU",
    "kbia.org": "KBIA",
}


def test_a_host_becomes_the_name_the_source_record_uses():
    assert _renamed('["columbiamissourian.com"]', NAMES) == ["Columbia Missourian"]


def test_a_row_already_named_is_left_alone():
    """Returns None rather than an identical list, so an article recorded
    correctly is not rewritten and not counted as changed."""
    assert _renamed('["The Associated Press"]', NAMES) is None


def test_a_host_with_no_source_record_is_left_alone():
    """tvinsider.com and fooddrinklife.com are real syndicators nobody
    has a record for. Inventing a display name here would put a publisher
    in the corpus that no source row backs."""
    assert _renamed('["tvinsider.com"]', NAMES) is None


def test_both_spellings_on_one_row_collapse_to_one():
    """A row naming both the host and the name is one syndicator, not
    two -- and it is exactly the row that proves they are the same."""
    assert _renamed('["komu.com", "KOMU"]', NAMES) == ["KOMU"]


def test_the_other_services_on_a_row_survive():
    assert _renamed('["kbia.org", "NPR"]', NAMES) == ["KBIA", "NPR"]


def test_order_is_kept():
    """The first service named is the one the queue shows, so reordering
    would change what a reviewer sees for no reason."""
    assert _renamed('["NPR", "kbia.org"]', NAMES) == ["NPR", "KBIA"]


def test_a_shape_that_is_not_a_list_is_left_alone():
    """`wire` holds `{}` on 18,940 rows and a bare string on others."""
    assert _renamed("{}", NAMES) is None
    assert _renamed('"kbia.org"', NAMES) is None
    assert _renamed(None, NAMES) is None
    assert _renamed("not json", NAMES) is None
