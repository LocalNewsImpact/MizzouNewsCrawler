"""Finding the `sources` row for a host, whatever spelling it is stored under.

TWO PATHS CREATE A SOURCE ROW on the fly -- `bot_sensitivity_manager` recording
a bot encounter, and `discovery` pausing a host it cannot crawl. Both looked the
row up with:

    SELECT id FROM sources WHERE host = :host OR host_norm = :host_norm

passing `host.lower()` as `host_norm`. That never strips `www.`, so a host seen
as `www.ptleader.com` did not match the loaded `ptleader.com` row and a SECOND
row was inserted carrying only id, host, host_norm and a bot sensitivity.

Neither path writes `dataset_sources` -- only `cli.commands.load_sources` does --
so every twin is invisible to every report that reads through a dataset. Five of
them were in production on 2026-09-23:

    rangemedia.co               twin of www.rangemedia.co       (WSU, 25 stories)
    warrensburgstarjournal.com  twin of www.warrensburgstar...  (Mizzou, 1,113)
    www.chinookobserver.com     twin of chinookobserver.com     (WSU, 6)
    www.discoverourcoast.com    twin of discoverourcoast.com    (WSU, 1)
    www.ptleader.com            twin of ptleader.com            (WSU, 425)

Which of the pair is the twin depends only on which spelling the CSV loader
registered first.

`host_norm` IS NOT A NORMALISED HOST and cannot be computed from `host`. In
production it holds three different things: the www-stripped host
(`www.elsberrydemocrat.com` -> `elsberrydemocrat.com`), a different domain the
publication also answers on (`ky3.com` -> `kspr.com`, `www.firstalert4.com` ->
`www.kmov.com`), and values with the dots eaten (`abcstlouis.com` ->
`abcstlouiscom`). So it is matched against, never derived -- deriving it is what
made the old lookup wrong.
"""


def host_spellings(host: str) -> list[str]:
    """Every spelling of one host that names the same site, exact first.

    The spelling as given leads, so a caller that wants the row for exactly the
    host it was handed can prefer the first hit. `www.` is the only prefix
    folded: a subdomain is a different site, and `news.example.com` must not
    collapse into `example.com`.

    An empty or whitespace-only host has no spellings, so a caller gets an empty
    list rather than a query matching every row with an empty host.
    """
    cleaned = (host or "").strip()
    lowered = cleaned.lower()
    bare = lowered.removeprefix("www.")
    if not bare:
        return []
    # dict.fromkeys rather than a set: the order carries the preference.
    return list(dict.fromkeys([cleaned, lowered, bare, f"www.{bare}"]))


def find_source_sql(host: str, select: str = "id") -> tuple[str, dict]:
    """`(sql, params)` returning at most one source row for this host.

    `select` is the column list to read -- `id`, or `bot_sensitivity`, or
    anything else the caller needs off the row. It is interpolated into the
    statement, so it is the CALLER'S OWN LITERAL and never a host, a value read
    back from the database, or anything else that came from outside.

    Matched on `host` AND `host_norm` because a site can be recorded under
    either -- the Washington Missourian is `www.missourian.com` with a
    `host_norm` of `www.emissourian.com`.

    Compared column-to-parameter with no function applied to the column, so an
    index on either can be used; production holds no mixed-case host, and
    `host_spellings` supplies the lowered forms anyway.

    Ordered so that the spelling as given wins when both spellings exist as
    separate rows. Without it the row returned would depend on the table's
    physical order, and a bot encounter on one spelling could be recorded
    against the other.

    Returns `("", {})` for a host with no spellings; the caller must treat that
    as "no match" and NOT run a query.
    """
    spellings = host_spellings(host)
    if not spellings:
        return "", {}
    names = [f"h{index}" for index in range(len(spellings))]
    placeholders = ", ".join(f":{name}" for name in names)
    sql = (
        f"SELECT {select} FROM sources "
        f"WHERE host IN ({placeholders}) OR host_norm IN ({placeholders}) "
        "ORDER BY CASE WHEN host = :h0 THEN 0 WHEN host_norm = :h0 THEN 1 "
        "ELSE 2 END "
        "LIMIT 1"
    )
    return sql, dict(zip(names, spellings, strict=True))
