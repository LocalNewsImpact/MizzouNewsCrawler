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
