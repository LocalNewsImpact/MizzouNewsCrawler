"""The MPA directory writes a description where it has no owner.

"Independently Owned Newspaper" is on 82 of its records. Read as an owner it
reached the newsroom map's tooltip as if it were a name, and it outranked
the Blue Book publisher that does name one.
"""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parent.parent / "scripts" / "build_mo_outlet_registry.py"
)


@pytest.fixture(scope="module")
def builder():
    spec = importlib.util.spec_from_file_location("build_mo_outlet_registry", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "placeholder",
    [
        "Independently Owned Newspaper",
        "Ownership information not listed",
        "  independently owned newspaper ",
    ],
)
def test_a_placeholder_is_no_owner(builder, placeholder):
    assert builder.owner_of(placeholder) == ""


@pytest.mark.parametrize(
    "name", ["James W. Johnston", "CherryRoad Media", "Independent Publishing Co."]
)
def test_a_name_is_kept(builder, name):
    assert builder.owner_of(name) == name


def test_blank_stays_blank(builder):
    assert builder.owner_of(None) == ""
    assert builder.owner_of("") == ""


#: The other lists `load_lists` reads. They are git-ignored raw lookups, so
#: a clean checkout -- the pre-push worktree, CI -- does not have them; the
#: tests give it empty ones with the real headers.
OTHER_LISTS = {
    "mo_bluebook_newspapers_2025_2026.csv": "name,city,cities,host,url,address,"
    "telephone,fax,editorial_email,publisher,editor,other_roles,schedule,affiliation",
    "mo_lni_newspapers_2025.csv": "newspaperName,city,county,fips,ownerName,ownerType,"
    "frequency,daysPublished,totalCirculation,yearAdded,newspaperId",
    "mo_lni_digital_sites_2025.csv": "organization,website,city,county,fips,typeOfOutlet,"
    "profitType,topic,language,yearFounded,publisher,memberInn,memberLion,rucc",
}


def _mpa(tmp_path, **record):
    base = {
        "contact_type": 1,
        "name": "The Independent Courier",
        "website": "",
        "owner": "",
        "county": "Shelby County",
        "address": "",
        "city": "",
        "zip": "",
    }
    path = tmp_path / "mpa.json"
    path.write_text(json.dumps({"records": [{**base, **record}]}))
    return path


def _mpa_entry(builder, path, monkeypatch):
    for name, header in OTHER_LISTS.items():
        (path.parent / name).write_text(header + "\n")
    monkeypatch.setattr(builder, "LOOKUPS", path.parent)
    return next(e for e in builder.load_lists(path) if e["list"] == "mpa")


def test_the_mpa_placeholder_leaves_the_owner_open(builder, tmp_path, monkeypatch):
    """Open, so the Blue Book or LNI publisher can fill it."""
    entry = _mpa_entry(
        builder, _mpa(tmp_path, owner="Independently Owned Newspaper"), monkeypatch
    )
    assert entry["owner"] == ""


def test_a_record_with_no_street_or_town_has_no_address(builder, tmp_path, monkeypatch):
    """ "MO" alone was written as the address and blocked the lists behind it."""
    assert _mpa_entry(builder, _mpa(tmp_path), monkeypatch)["address"] == ""


def test_a_record_with_a_street_keeps_it(builder, tmp_path, monkeypatch):
    entry = _mpa_entry(
        builder,
        _mpa(tmp_path, address="214 N. Grand St.", city="Clarence", zip="63437"),
        monkeypatch,
    )
    assert entry["address"] == "214 N. Grand St., Clarence, MO 63437"


def test_the_production_record_names_and_places_its_outlet():
    """A correction made in `sources` reaches the registry: the Wayne County
    Journal-Banner kept "WayNe" and a Reynolds County town because only the
    owner, county, status and address were taken from production."""
    src = SCRIPT.read_text()
    assert 'o["outlet"] = o.get("_source_name") or o["outlet"]' in src
    assert 'o["city"] = o.get("_source_city") or o["city"]' in src


def _source_outlet(source_id, host):
    return {"source_id": source_id, "host": host, "lists": {"ours"}, "outlet": "Held"}


def _added(host, **extra):
    return {
        "outlet_id": "added-1",
        "outlet": "Added",
        "city": "Crane",
        "county": "Stone",
        "host": host,
        "status": "active",
        "status_basis": "launched August 2026",
        **extra,
    }


def test_an_added_outlet_held_by_a_source_is_that_source(builder):
    """StoneCounty.news was added to the registry, then to `sources` for
    crawling, and the registry drew it twice."""
    outlets = [_source_outlet("src-1", "stonecounty.news")]
    ours = {"stonecounty.news": {"id": "src-1"}}
    builder.attach_added(outlets, [_added("https://stonecounty.news/")], ours)
    assert len(outlets) == 1
    held = outlets[0]
    assert held["source_id"] == "src-1"
    assert "added" in held["lists"]
    assert held["_added_status"] == "active"
    assert held["_added_basis"] == "launched August 2026"


def test_an_added_outlet_nobody_holds_is_its_own(builder):
    outlets = [_source_outlet("src-1", "stonecountyrepublican.com")]
    ours = {"stonecountyrepublican.com": {"id": "src-1"}}
    builder.attach_added(outlets, [_added("stonecounty.news")], ours)
    assert len(outlets) == 2
    assert outlets[1]["_added_id"] == "added-1"
    assert outlets[1]["host"] == "stonecounty.news"


def test_an_added_outlet_without_a_host_is_its_own(builder):
    outlets = []
    builder.attach_added(outlets, [_added("")], {"": {"id": "src-1"}})
    assert len(outlets) == 1
    assert outlets[0]["_added_id"] == "added-1"


def test_a_reviewed_status_on_the_source_is_not_replaced(builder):
    outlets = [
        {**_source_outlet("src-1", "stonecounty.news"), "_added_status": "closed"}
    ]
    builder.attach_added(
        outlets, [_added("stonecounty.news")], {"stonecounty.news": {"id": "src-1"}}
    )
    assert outlets[0]["_added_status"] == "closed"


def test_a_rebuild_is_published_where_datadesk_reads_it(builder, tmp_path, monkeypatch):
    """A rebuild is data: it reaches datadesk through a bucket, not a pull
    request."""
    import sys
    import types

    import google.cloud

    sent = {}

    class Blob:
        def upload_from_filename(self, path, content_type=None):
            sent["path"], sent["type"] = path, content_type

    class Bucket:
        def blob(self, name):
            sent["blob"] = name
            return Blob()

    class Client:
        def bucket(self, name):
            sent["bucket"] = name
            return Bucket()

    # A stub module, never the real one: importing google.cloud.storage here
    # sets it on the package and defeats the sys.modules stub other tests
    # (test_raw_html_archive) rely on.
    stub = types.ModuleType("google.cloud.storage")
    stub.Client = Client
    monkeypatch.setitem(sys.modules, "google.cloud.storage", stub)
    monkeypatch.setattr(google.cloud, "storage", stub, raising=False)
    out = tmp_path / "mo_outlet_registry.csv"
    out.write_text("outlet_id\n")
    assert builder.publish(out) == builder.PUBLISH_TO
    assert sent == {
        "bucket": "mizzou-news-maps-data",
        "blob": "registry/mo_outlet_registry.csv",
        "path": str(out),
        "type": "text/csv",
    }


def test_a_status_copied_from_sources_follows_sources(builder):
    """Five radio stations ruled "not local news" in `sources` stayed
    "retired" in the registry: the last build's copy was carried forward as
    though a reviewer had said it."""
    o = {
        "source_status": "not_local_news",
        "status": "retired",
        "status_basis": "sources table",
    }
    assert builder.standing_status(o)["status"] == "not_local_news"


def test_a_reviewed_status_is_not_overwritten(builder):
    o = {
        "source_status": "retired",
        "status": "replica",
        "status_basis": "replica edition; not an active digital source",
    }
    assert builder.standing_status(o)["status"] == "replica"


def test_an_unreviewed_outlet_takes_the_sources_status(builder):
    o = {"source_status": "active", "status": "", "status_basis": ""}
    assert builder.standing_status(o) == {
        "source_status": "active",
        "status": "active",
        "status_basis": "sources table",
    }


def test_an_outlet_we_do_not_hold_keeps_its_status(builder):
    o = {"source_status": "", "status": "legal", "status_basis": ""}
    assert builder.standing_status(o)["status"] == "legal"


def test_a_source_is_found_at_the_domain_it_moved_from(builder):
    """The Licking News moved to thelickingnews.net; the lists still say .com."""
    licking = {
        "id": "s1",
        "host": "www.thelickingnews.net",
        "previous_hosts": ["www.thelickingnews.com"],
    }
    found = builder.hosts_of_ours([licking])
    assert found["thelickingnews.net"] is licking
    assert found["thelickingnews.com"] is licking


def test_a_domain_held_now_wins_over_one_left_behind(builder):
    left = {"id": "s1", "host": "new.example", "previous_hosts": ["old.example"]}
    holder = {"id": "s2", "host": "old.example", "previous_hosts": []}
    assert builder.hosts_of_ours([left, holder])["old.example"] is holder


def test_the_production_record_gives_its_outlet_its_website():
    """A list naming a paper at a domain it has left must not put that
    domain back on the registry row the source holds."""
    src = SCRIPT.read_text()
    assert 'o["host"] = o.get("_source_host") or o["host"]' in src


@pytest.mark.parametrize(
    "address, parts",
    [
        (
            "427 West Main Street, P.O. Box 299, Savannah, MO 64485",
            ("427 West Main Street", "Savannah", "MO", "64485"),
        ),
        (
            "110 E McPherson St, Kirksville, MO 63501",
            ("110 E McPherson St", "Kirksville", "MO", "63501"),
        ),
        (
            "300 S Main St #1534, Rock Port, MO 64482",
            ("300 S Main St #1534", "Rock Port", "MO", "64482"),
        ),
        ("202 Courtney St, Branson, MO", ("202 Courtney St", "Branson", "MO", "")),
    ],
)
def test_an_address_is_split_for_the_geocoder(builder, address, parts):
    assert builder.split_address(address) == parts


@pytest.mark.parametrize(
    "address",
    [
        "",
        "P.O. Box 218, Hamilton, MO 64644",
        "Main Street, Hamilton, MO 64644",
        "Hamilton MO",
    ],
)
def test_an_address_without_a_street_number_is_not_geocoded(builder, address):
    assert builder.split_address(address) is None


CENSUS_REPLY = (
    '"0","110 E McPherson St, Kirksville, MO, 63501","Match","Exact",'
    '"110 E MCPHERSON ST, KIRKSVILLE, MO, 63501","-92.58,40.19","1","L","29","001","950100","1001"\n'
    '"1","9 Nowhere Rd, Kirksville, MO, 63501","No_Match"\n'
)


def test_geocoding_asks_once_and_caches_every_answer(builder, tmp_path):
    asked = []

    def post(body):
        asked.append(body)
        return CENSUS_REPLY

    path = tmp_path / "geocodes.csv"
    addresses = [
        "110 E McPherson St, Kirksville, MO 63501",
        "9 Nowhere Rd, Kirksville, MO 63501",
        "P.O. Box 5, Kirksville, MO 63501",
    ]
    cache = builder.geocode(addresses, {}, path, post=post)
    assert len(asked) == 1 and "P.O. Box" not in asked[0]
    assert (
        cache[addresses[0]]["lat"] == "40.19"
        and cache[addresses[0]]["county_fips"] == "29001"
    )
    assert cache[addresses[1]]["matched"] == "no"
    # Asked again, nothing is sent: the cache answers, matched or not.
    builder.geocode(addresses, builder.load_geocodes(path), path, post=post)
    assert len(asked) == 1


def test_a_batch_that_fails_caches_nothing(builder, tmp_path):
    """A timed-out batch leaves every address to the one-line geocoder."""

    def post(body):
        raise TimeoutError("read timed out")

    address = "110 E McPherson St, Kirksville, MO 63501"
    cache = builder.geocode([address], {}, tmp_path / "g.csv", post=post)
    assert cache == {} and not (tmp_path / "g.csv").exists()


def test_an_outlet_is_placed_at_its_address(builder):
    cache = {
        "1 Main St, Joplin, MO 64801": {
            "matched": "yes",
            "lat": "37.08",
            "lon": "-94.51",
            "county_fips": "29097",
        }
    }
    o = {
        "address": "1 Main St, Joplin, MO 64801",
        "lat": "37.0752",
        "lon": "-94.5013",
        "location_basis": "town centroid",
        "county_fips": "29097",
        "signals": "",
    }
    builder.place_at_address(o, cache)
    assert (o["lat"], o["lon"], o["location_basis"]) == ("37.08", "-94.51", "address")
    assert o["signals"] == ""


def _placed(builder, town, found_in, **o):
    address = "1 Main St, Somewhere, MO"
    cache = {
        address: {
            "address": address,
            "matched": "yes",
            "lat": "38.6",
            "lon": "-90.4",
            "county_fips": found_in,
            "town": town,
        }
    }
    fips = {("MO", "st louis"): "29189", ("MO", "st louis city"): "29510"}
    o = {"address": address, "signals": "", "location_basis": "town centroid", **o}
    return builder.place_at_address(o, cache, fips)


def test_an_address_in_the_same_town_moves_the_county(builder):
    """KPLR on Ball Drive is in St. Louis County, not the city."""
    o = _placed(
        builder,
        "SAINT LOUIS",
        "29189",
        city="St. Louis",
        county="St. Louis",
        county_fips="29510",
        county_basis="listed",
    )
    assert (o["county_fips"], o["county"], o["county_basis"]) == (
        "29189",
        "St. Louis",
        "address",
    )
    assert o["location_basis"] == "address"
    assert o["signals"] == "county moved from St. Louis by its address"


def test_an_address_in_another_town_is_an_office_elsewhere(builder):
    """The Aurora Advertiser's address is in Neosho: said, not drawn."""
    o = _placed(
        builder,
        "NEOSHO",
        "29145",
        city="Aurora",
        county="Lawrence",
        county_fips="29109",
        lat="36.97",
    )
    assert (o["county_fips"], o["lat"], o["location_basis"]) == (
        "29109",
        "36.97",
        "town centroid",
    )
    assert o["signals"] == "address is in Neosho, not Aurora"


def test_another_town_in_the_same_county_is_drawn(builder):
    """The Leader's office is in Festus, not Arnold: both Jefferson County."""
    o = _placed(
        builder,
        "FESTUS",
        "29099",
        city="Arnold",
        county="Jefferson",
        county_fips="29099",
    )
    assert (o["lat"], o["location_basis"], o["county_fips"]) == (
        "38.6",
        "address",
        "29099",
    )
    assert o["signals"] == "address is in Festus, not Arnold"


def test_a_reviewers_county_is_not_moved(builder):
    o = _placed(
        builder,
        "St. Louis",
        "29189",
        city="St. Louis",
        county="St. Louis city",
        county_fips="29510",
        county_basis="reviewer",
    )
    assert o["county_fips"] == "29510"
    assert o["signals"] == "address is in county 29189"


def test_an_address_out_of_state_does_not_move_the_county(builder):
    o = _placed(
        builder,
        "Fairway",
        "20091",
        city="Fairway",
        county="Jackson",
        county_fips="29095",
    )
    assert o["county_fips"] == "29095"
    assert o["signals"] == "address is in county 20091"


def _match(county, x=-90.6, y=37.1, address="370 N MAIN ST, PIEDMONT, MO, 63957"):
    return {
        "matchedAddress": address,
        "coordinates": {"x": x, "y": y},
        "geographies": {"Counties": [{"GEOID": county}]},
    }


def test_a_tie_in_one_county_is_taken(builder, tmp_path):
    """North and South Main, Piedmont: a batch refuses the tie."""
    address = "370 Main St, Piedmont, MO 63638"
    o = {
        "outlet": "Wayne County Journal Banner",
        "city": "Piedmont",
        "address": address,
    }
    cache = builder.geocode_again(
        [o],
        {},
        tmp_path / "g.csv",
        oneline=lambda a: [_match("29223"), _match("29223", y=37.2)],
        osm=lambda q: pytest.fail("asked OpenStreetMap"),
    )
    hit = cache[address]
    assert (hit["lat"], hit["county_fips"], hit["town"], hit["by"]) == (
        "37.1",
        "29223",
        "PIEDMONT",
        "census",
    )


def test_a_tie_across_counties_is_refused(builder):
    hit = builder._from_census("x", [_match("29223"), _match("29179")])
    assert hit["matched"] == "no"


def test_openstreetmap_places_at_a_building_not_a_road(builder):
    road = [{"addresstype": "road", "lat": "1", "lon": "2", "address": {}}]
    assert builder._from_osm("x", road)["matched"] == "no"
    house = [
        {
            "addresstype": "place",
            "lat": "39.43",
            "lon": "-94.20",
            "address": {
                "country_code": "us",
                "ISO3166-2-lvl4": "US-MO",
                "town": "Lawson",
            },
        }
    ]
    hit = builder._from_osm("x", house)
    assert (hit["lat"], hit["town"], hit["by"]) == ("39.43", "Lawson", "osm")


def test_a_building_found_by_name_must_carry_the_name(builder):
    office = {
        "addresstype": "office",
        "lat": "39.14",
        "lon": "-92.68",
        "address": {"country_code": "us", "ISO3166-2-lvl4": "US-MO", "town": "Fayette"},
    }
    found = builder._from_osm(
        "x", [{**office, "name": "Fayette Advertiser"}], "Fayette Advertiser"
    )
    assert found["matched"] == "yes"
    other = builder._from_osm(
        "x", [{**office, "name": "Fayette City Hall"}], "Fayette Advertiser"
    )
    assert other["matched"] == "no"


def test_what_nobody_can_place_is_asked_once(builder, tmp_path):
    asked = []
    o = {
        "outlet": "Linn County Leader",
        "city": "Marceline",
        "address": "118 N. Main St, Marceline, MO 64658",
    }

    def oneline(a):
        asked.append(a)
        return []

    def osm(q):
        asked.append(q)
        return []

    path = tmp_path / "g.csv"
    cache = builder.geocode_again([o], {}, path, oneline=oneline, osm=osm)
    assert len(asked) == 3  # Census, OpenStreetMap by street, then by name
    builder.geocode_again(
        [o], builder.load_geocodes(path), path, oneline=oneline, osm=osm
    )
    assert len(asked) == 3
    assert cache[o["address"]]["by"] == "none"


def test_an_outlet_found_by_name_is_placed_there(builder):
    o = {
        "outlet": "KBIA",
        "city": "Columbia",
        "address": "",
        "county_fips": "29019",
        "signals": "",
    }
    cache = {
        "name: KBIA, Columbia, MO": {
            "address": "name: KBIA, Columbia, MO",
            "matched": "yes",
            "lat": "38.94",
            "lon": "-92.32",
            "town": "Columbia",
            "county_fips": "",
        }
    }
    builder.place_at_address(o, cache)
    assert (o["lat"], o["location_basis"]) == ("38.94", "named building")


def test_an_unplaced_address_keeps_the_town_centre(builder):
    o = {
        "address": "9 Nowhere Rd, Joplin, MO",
        "lat": "37.0752",
        "lon": "-94.5013",
        "location_basis": "town centroid",
    }
    builder.place_at_address(
        o, {"9 Nowhere Rd, Joplin, MO": {"matched": "no", "lat": ""}}
    )
    assert o["location_basis"] == "town centroid"
