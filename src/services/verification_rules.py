"""The verification rules that are repaired, and what they were.

The rules themselves live in `verification_patterns`, a table, and are
edited by migration. These are the specific repairs migration
q2r3s4t5u6v7 applies, held here rather than inside it so a test can read
them: `tests/alembic/__init__.py` shadows the alembic package when the
whole suite runs, so a migration module cannot be imported from a test.

Four of the 46 active rules carry regexes that do not compile --
`/(entertainment`, `obituar(y`, `/(us-world-news`, `/(weather` -- and
have therefore never matched a URL. Repairing one turns it on, and three
of the four should stay off; the migration's own docstring carries the
measurements that decide which.
"""

#: `pattern_type`, the repaired regex, and whether the rule may run.
#: `None` means the rule's active flag is left as it is.
REPAIRS: tuple[tuple[str, str, bool | None], ...] = (
    # Excluding a forecast without excluding a story about the weather
    # needs more than a URL. Repaired, left off.
    ("weather", r"/(weather|forecast|radar|stormtrack|doppler)/", False),
    # A person's death reported as news is journalism, and 147 of 754
    # reviewed obituaries were exactly that. Repaired, left off.
    ("obituary", r"/(obituary|obituaries)/", False),
    # Narrowed to the one token that earns it: 2,739 of 2,740 fetched
    # `/world/` articles were classified `wire`. `politics`, `washington`
    # and `national-news` are gone, and the bare `world` is bounded --
    # Kansas City hosts the 2026 World Cup, and `/world` unbounded
    # matches Worlds of Fun and a world record broken by a Nixa
    # 10-year-old.
    ("us_world_news", r"/(world|us-world-news)/", True),
    # Not broken, over-matching: `/feed` unbounded rejects
    # `/feeding-the-hungry` and `/feed-seed-grain`.
    ("feed", r"/(feed|feeds)(/|$)", None),
)

#: What each was, so a downgrade restores the state it found rather than
#: a tidied version of it -- three of these do not compile, and that is
#: the point.
ORIGINALS: tuple[tuple[str, str, bool | None], ...] = (
    ("weather", r"/(weather", True),
    ("obituary", r"obituar(y", True),
    ("us_world_news", r"/(us-world-news", True),
    ("feed", r"/feed", None),
)

#: Deleted rather than repaired: no status exists for entertainment, so
#: the rule can only write `not_article`, which is false of an
#: entertainment story.
DELETED: tuple[str, ...] = ("entertainment",)
