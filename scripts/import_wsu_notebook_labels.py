#!/usr/bin/env python3
"""Bring the WSU notebook's CIN labels into the application database.

The Washington State CIN pass ran in a notebook that predated this
application. Its output — 485 classified stories — lives in a spreadsheet,
and the WSU dataset in production holds only 4 articles, none of them from
that pass. Nothing joins the two: zero of the 485 URLs exist in the corpus.

What the spreadsheet is
-----------------------
Two sheets from ``murrow_stories_labeled with random sample human check``:

``predictedlabel1`` / ``ALTpredictedlabel``
    Drawn from exactly this application's ten-label CIN vocabulary, all ten
    values present and no strays — the notebook ran the same model. They map
    onto ``primary_label`` / ``alternate_label`` with no translation. No
    confidence figures were recorded, so the confidence columns stay NULL.

``Category 1`` / ``Category 2``
    A *different*, hand-typed codebook used for the 45-row human check, with
    typos (``Civic informaiton``, ``Enviornment``) and finer categories
    (``Economic opportunities``, ``Political information``) that have no
    counterpart here. These are evidence about the labels, not labels, so
    they go to metadata with their spellings normalised.

``inputtext``
    The exact string the notebook classified. It is body only — it begins
    with the headline in 20 of 485 rows — and its apostrophes were stripped.
    Production feeds the classifier ``title + "\\n\\n" + body`` truncated at
    512 tokens, and 345 of 485 bodies exceed that window, so the notebook's
    tokens are not the tokens this application would produce. Storing it
    verbatim is what lets a re-run separate input construction from model
    drift; without it the comparison conflates the two.

``news``
    The fuller raw body, written to BOTH ``articles.text`` and
    ``articles.content``. The two columns are documented as cleaned body and
    raw capture, but in this corpus they are the same string: 3,000 of 3,000
    sampled labeled articles have them byte-identical, and `content` holds
    plain text rather than markup. Writing only ``text`` silently excludes the
    article from enrichment, whose candidate query requires
    ``coalesce(a.content, '') <> ''`` -- the 474 rows from the first pass were
    the only text-without-content articles in a corpus of 85,365.

    Median 3,474 chars against inputtext's 3,206,
    mojibake in 382 of 485 rows from a UTF-8 → latin-1 → UTF-8 → mac-roman
    round trip. ``ftfy`` unwinds it and restores the apostrophes that
    inputtext lost, taking 131 rows with usable apostrophes to 429.

Attribution goes through the URL host, never ORG
------------------------------------------------
``ORG`` carries ``MNN:`` and ``MNNN:`` for the same outlet, three spellings
of KNKX, and a trailing space on ``Range``. The host is unambiguous. Two
hosts are prior domain names of sources already in the dataset — the
Snohomish outlets renamed on 2025-12-18 — so those fold onto the existing
source rows rather than creating duplicates:

    lynnwoodtoday.com -> mylynnwoodnews.com
    mltnews.com       -> mymltnews.com

Nine hosts are not publishers (``drive.google.com`` and friends, plus rows
where a headline was pasted into the URL column) and are skipped.

Why candidate_links rows are created
------------------------------------
``articles.candidate_link_id`` is NOT NULL with an FK to ``candidate_links``,
and the source attribution this dataset needs (``source_id`` and its
denormalised city/county) lives on the candidate link, not the article. An
article cannot exist without one. They are written with
``discovered_by='manual-import'``, matching the 717 rows already imported
that way.

Labels live in two places, and both must be written
---------------------------------------------------
``article_labels`` is the versioned store — one row per
``(article_id, label_version)``, carrying the model version, the confidences
and the full prediction set. ``articles.primary_label`` is a denormalised copy
for querying. Writing only the copy leaves the label invisible to everything
that reads the versioned store, including ``analyze``'s own change report,
which outer-joins ``article_labels`` to compute the diff: a re-run against a
corpus with only the copy populated reports every old label as empty and every
new one as a change, so the comparison silently measures nothing.

So the import writes both, and the label row is upserted on
``uq_article_label_version`` independently of whether the article was newly
inserted. A second run therefore repairs missing label rows instead of doing
nothing, which is what an import of a curated set needs — the article is
keyed on its URL and cannot be inserted twice.

Syndication is kept, not collapsed
----------------------------------
38 headlines appear more than once and 33 of those span multiple hosts: the
Snohomish trio runs the same story the same day, and the Columbian and TDN
share Columbia River coverage. Each outlet's publication is a unit of this
study, so every copy is imported as its own article. Only literally identical
URLs are dropped — ``uq_articles_url`` forbids two rows on one URL — which
costs 5 rows.

Two consequences follow, both deliberate. ``text_hash`` is populated because
nothing marks duplicates from it; it is read only by the content cleaners, for
telemetry.

And ``wire_check_status`` is set to ``local`` explicitly. It cannot be left
alone: the column is ``NOT NULL DEFAULT 'pending'``, and ``pending`` is the one
value that blocks enrichment, which selects on
``wire_check_status IN ('complete', 'local')``. Omitting it would therefore
have stranded all 474 rows short of the geo-classification this import exists
to reach, while leaving them queued for the MediaCloud check that identical
cross-publisher text is most likely to call wire.

``local`` is the existing value for "determined not to be wire". Here the
determination rests on WSU's curation of the URL set rather than on a lookup,
so ``wire_check_metadata`` records that, and the claim stays auditable instead
of being indistinguishable from a check that ran.

Usage:
  python scripts/import_wsu_notebook_labels.py --file labeled.json --dry-run
  python scripts/import_wsu_notebook_labels.py --file labeled.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from collections import Counter
from datetime import datetime
from typing import Any

import ftfy
from sqlalchemy import text

from src.models.database import DatabaseManager

DATASET_SLUG = "WSU-Washington-State"

LABEL_VERSION = "wsu-notebook-2026-02"
LABEL_MODEL_VERSION = "productionmodel"
EXTRACTION_VERSION = "manual-import-v1"

# NOT NULL DEFAULT 'pending', and 'pending' blocks enrichment. See the module
# docstring: for a curated corpus the determination is curation, not a lookup.
WIRE_CHECK_STATUS = "local"
WIRE_CHECK_AUTHORITY = "wsu-curated-url-set"
DISCOVERED_BY = "manual-import"

# Two Snohomish outlets moved domains after 2025-12-17. Rows carrying an old
# domain belong to the source row that holds the new one.
HOST_RENAMES = {
    "lynnwoodtoday.com": "mylynnwoodnews.com",
    "mltnews.com": "mymltnews.com",
}

# NEVER FETCH THESE. Both old domains are gone, not merely renamed:
# lynnwoodtoday.com left the publisher's control and now serves gambling spam,
# and mltnews.com does not resolve. The stored URL stays as written because it
# is the provenance -- the address the story was published at and the notebook
# classified -- so the article instead carries a marker saying the address is
# dead, and the candidate link is never a fetch candidate.
RETIRED_DOMAINS = {
    "lynnwoodtoday.com": "left the publisher's control; now serves gambling spam",
    "mltnews.com": "does not resolve",
}

# Hosts that are file stores, search engines and CDNs rather than publishers.
NON_PUBLISHER_HOSTS = frozenset(
    {
        "bing.com",
        "cdn2.creativecirclemedia.com",
        "drive.google.com",
        "google.com",
        "msn.com",
        "we.tl",
    }
)

# This application's CIN vocabulary. A label outside it is a data error, not
# something to coerce — the notebook used the same model, so a mismatch means
# the wrong column was read.
CIN_LABELS = frozenset(
    {
        "Civic Life",
        "Civic information",
        "Economic Development",
        "Education",
        "Emergencies and Public Safety",
        "Environment and Planning",
        "Health",
        "Political life",
        "Sports",
        "Transportation Systems",
    }
)

# The human-check codebook as typed, folded to one spelling per concept. The
# values are that codebook's own terms, deliberately not translated into the
# CIN vocabulary: "Health and welfare" and "Health" are not the same category,
# and pretending otherwise would manufacture agreement.
HUMAN_CHECK_SPELLINGS = {
    "civic informaiton": "Civic information",
    "civic informatiom": "Civic information",
    "civic information": "Civic information",
    "civici information": "Civic information",
    "civic life": "Civic life",
    "economic development": "Economic development",
    "economic opportunities": "Economic opportunities",
    "emergencies and risks": "Emergencies and risks",
    "enviornment": "Environment",
    "environment": "Environment",
    "health and welfare": "Health and welfare",
    "political information": "Political information",
    "political life": "Political life",
    "sports": "Sports",
    "transportation": "Transportation",
}

_URL_RE = re.compile(r"https?://([^/]+)(.*)$", re.IGNORECASE)


def repair_text(value: Any) -> str:
    """Unwind the spreadsheet's double mis-decoding.

    The round trip is UTF-8 → latin-1 → UTF-8 → mac-roman, which turns one
    right single quote into six characters. Unwinding it by hand fails on long
    fields: a single character outside mac-roman anywhere in the body makes the
    whole-string re-encode raise, and the field is left half-repaired. ftfy
    works run by run, so one bad character costs one run rather than the
    document.
    """
    if value is None:
        return ""
    s = str(value)
    if not s or s == "None":
        return ""
    return ftfy.fix_text(s, normalization="NFC")


def normalise_url(value: Any) -> tuple[str, str] | None:
    """Return ``(url_to_store, lookup_host)`` for a real article URL, else None.

    The stored URL keeps the host exactly as written, ``www`` included. For a
    live host, rewriting it would both break a re-fetch — an old domain's path
    need not exist on the new one — and guarantee a second row per story when
    discovery finds the form we chose to discard. For the two retired domains
    the reason is different and stronger: their paths cannot be rewritten onto
    the successor because nobody can check them, and the address as written is
    the story's provenance. Those rows are marked instead; see
    ``RETIRED_DOMAINS``.

    Only fragments, query strings and a trailing slash are dropped, so the
    same story submitted twice with different tracking parameters collides on
    ``uq_articles_url`` instead of landing twice.

    The second element is the key for attribution only: lowercased, ``www``
    stripped, and the 2025-12-18 renames applied so an old-domain row resolves
    to the source that now owns it.
    """
    if value is None:
        return None
    raw = str(value).strip()
    if not raw.lower().startswith("http"):
        return None
    raw = raw.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    match = _URL_RE.match(raw)
    if not match:
        return None
    lookup = match.group(1).lower()
    if lookup.startswith("www."):
        lookup = lookup[4:]
    return raw, HOST_RENAMES.get(lookup, lookup)


def parse_date(value: Any) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw or raw == "None":
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def text_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:32]


def human_check(row: dict[str, Any]) -> dict[str, str] | None:
    """Normalise the 45-row human check, or None where it was not done."""
    out = {}
    for column, key in (("Category 1", "primary"), ("Category 2", "alternate")):
        raw = str(row.get(column) or "").strip()
        if not raw or raw == "None":
            continue
        folded = HUMAN_CHECK_SPELLINGS.get(raw.lower())
        # An unrecognised spelling is kept verbatim rather than dropped, so a
        # new typo shows up in the data instead of vanishing silently.
        out[key] = folded or raw
        if folded is None:
            out.setdefault("unrecognised", "")
            out["unrecognised"] = f"{out['unrecognised']}{column}={raw};"
    return out or None


def media(row: dict[str, Any]) -> dict[str, str] | None:
    """PHOTO/VIDEO/AUDIO have no columns here, so they are kept as metadata."""
    out = {}
    for column in ("PHOTO", "VIDEO", "AUDIO"):
        raw = str(row.get(column) or "").strip()
        if raw and raw != "None":
            out[column.lower()] = raw
    return out or None


def author(row: dict[str, Any]) -> str | None:
    """FIRST/LAST name the Murrow fellow who wrote the story."""
    parts = [repair_text(row.get(part)).strip() for part in ("FIRST", "LAST")]
    name = " ".join(p for p in parts if p)
    return name or None


def build_records(rows: list[dict[str, Any]], hosts: dict[str, dict[str, Any]]):
    """Turn spreadsheet rows into (candidate_link, article) pairs.

    Returns the pairs plus a per-reason skip tally, so a run reports what it
    declined rather than only what it wrote.
    """
    records: list[tuple[dict[str, Any], dict[str, Any]]] = []
    skipped: Counter[str] = Counter()
    seen_urls: set[str] = set()

    for row in rows:
        parsed = normalise_url(row.get("URL"))
        if parsed is None:
            skipped["url not parseable"] += 1
            continue
        url, host = parsed
        if host in NON_PUBLISHER_HOSTS:
            skipped[f"not a publisher: {host}"] += 1
            continue
        source = hosts.get(host)
        if source is None:
            skipped[f"host not a dataset source: {host}"] += 1
            continue
        if url in seen_urls:
            skipped["duplicate URL within the file"] += 1
            continue

        primary = str(row.get("predictedlabel1") or "").strip()
        alternate = str(row.get("ALTpredictedlabel") or "").strip()
        if primary and primary not in CIN_LABELS:
            skipped[f"label outside the vocabulary: {primary}"] += 1
            continue
        if alternate and alternate not in CIN_LABELS:
            skipped[f"label outside the vocabulary: {alternate}"] += 1
            continue

        # news is the fuller body; inputtext covers the 15 rows that lack it.
        body = repair_text(row.get("news")) or repair_text(row.get("inputtext"))
        if not body:
            skipped["no body text"] += 1
            continue

        seen_urls.add(url)
        link_id = str(uuid.uuid4())
        article_id = str(uuid.uuid4())
        published = parse_date(row.get("DATE"))

        notebook: dict[str, Any] = {
            "uniqueid": str(row.get("UNIQUEID") or "").strip() or None,
            "org_as_written": repair_text(row.get("ORG")).strip() or None,
            "url_as_written": str(row.get("URL") or "").strip(),
            # Verbatim. This is the string the notebook classified; repairing
            # it would destroy the thing the A/B needs to measure.
            "inputtext": str(row.get("inputtext") or ""),
            "human_check": human_check(row),
            "media": media(row),
        }
        # `host` is the attribution key, already mapped to the live successor,
        # so the marker has to test the host the URL is actually stored on.
        stored_host = url.split("//", 1)[-1].split("/", 1)[0].lower()
        if stored_host.startswith("www."):
            stored_host = stored_host[4:]
        if stored_host in RETIRED_DOMAINS:
            # Read by anything that might otherwise fetch this address.
            notebook["retired_domain"] = {
                "host": stored_host,
                "reason": RETIRED_DOMAINS[stored_host],
                "do_not_fetch": True,
            }

        link = {
            "id": link_id,
            "url": url,
            # candidate_links.source carries the publisher name, not the host.
            "source": source["canonical_name"] or host,
            "host": host,
            "status": "extracted",
            "discovered_by": DISCOVERED_BY,
            "publish_date": published,
            "source_id": source["id"],
            "source_name": source["canonical_name"] or None,
            "source_city": source["city"] or None,
            "source_county": source["county"] or None,
            "source_type": source["type"] or None,
            "dataset_id": source["dataset_id"],
            "meta": json.dumps({"wsu_notebook_import": True}),
        }
        article = {
            "id": article_id,
            "candidate_link_id": link_id,
            "url": url,
            "title": repair_text(row.get("Text Headline")).strip() or None,
            "author": author(row),
            "publish_date": published,
            "text": body,
            # Both, deliberately. Enrichment selects on `content`; the
            # classifier prefers `text`. See the module docstring.
            "content": body,
            "text_hash": text_hash(body),
            "status": "labeled",
            "wire_check_status": WIRE_CHECK_STATUS,
            "wire_check_metadata": json.dumps(
                {"authority": WIRE_CHECK_AUTHORITY, "mediacloud_lookup": False}
            ),
            "primary_label": primary or None,
            "alternate_label": alternate or None,
            "label_version": LABEL_VERSION,
            "label_model_version": LABEL_MODEL_VERSION,
            "extraction_version": EXTRACTION_VERSION,
            "dataset_id": source["dataset_id"],
            "metadata": json.dumps({"wsu_notebook": notebook}),
        }
        records.append((link, article))

    return records, skipped


def load_hosts(session, dataset_slug: str) -> dict[str, dict[str, Any]]:
    """Map every host in the dataset to the source row that owns it.

    Both the bare host and its www form are keyed, because the dataset stores
    some sources with the prefix and the spreadsheet never carries it.
    """
    rows = session.execute(
        text("""
            SELECT s.host, s.id, s.canonical_name, s.city, s.county, s.type,
                   d.id AS dataset_id
              FROM sources s
              JOIN dataset_sources ds ON ds.source_id = s.id
              JOIN datasets d ON d.id = ds.dataset_id
             WHERE d.slug = :slug
        """),
        {"slug": dataset_slug},
    ).mappings()

    hosts: dict[str, dict[str, Any]] = {}
    for row in rows:
        record = dict(row)
        host = (record["host"] or "").lower()
        if host.startswith("www."):
            host = host[4:]
        hosts[host] = record
    return hosts


INSERT_LINK = text("""
INSERT INTO candidate_links
    (id, url, source, status, discovered_by, discovered_at, publish_date,
     source_id, source_name, source_city, source_county, source_type,
     dataset_id, meta, created_at)
VALUES
    (:id, :url, :source, :status, :discovered_by, NOW(), :publish_date,
     :source_id, :source_name, :source_city, :source_county, :source_type,
     :dataset_id, CAST(:meta AS json), NOW())
ON CONFLICT (url) DO NOTHING
RETURNING id
""")

# text_length is omitted on purpose: it is a generated column that the
# database derives from text, and naming it in the column list is an error.
INSERT_ARTICLE = text("""
INSERT INTO articles
    (id, candidate_link_id, url, title, author, publish_date, text, content,
     text_hash, status, wire_check_status, wire_check_metadata,
     primary_label, alternate_label,
     label_version, label_model_version, labels_updated_at,
     extraction_version, extracted_at, dataset_id, metadata, created_at)
VALUES
    (:id, :candidate_link_id, :url, :title, :author, :publish_date, :text,
     :content, :text_hash, :status, :wire_check_status,
     CAST(:wire_check_metadata AS json), :primary_label, :alternate_label,
     :label_version, :label_model_version, NOW(),
     :extraction_version, NOW(), :dataset_id, CAST(:metadata AS json), NOW())
ON CONFLICT (url) DO NOTHING
RETURNING id
""")

# The versioned label store. Upserted rather than skipped on conflict: a
# re-run's job is to repair a label row the first pass failed to write.
UPSERT_LABEL = text("""
INSERT INTO article_labels
    (id, article_id, label_version, model_version, model_path,
     primary_label, primary_label_confidence,
     alternate_label, alternate_label_confidence, applied_at, meta)
VALUES
    (:id, :article_id, :label_version, :model_version, :model_path,
     :primary_label, NULL, :alternate_label, NULL, NOW(),
     CAST(:meta AS json))
ON CONFLICT (article_id, label_version) DO UPDATE SET
    primary_label = EXCLUDED.primary_label,
    alternate_label = EXCLUDED.alternate_label,
    model_version = EXCLUDED.model_version,
    applied_at = EXCLUDED.applied_at,
    meta = EXCLUDED.meta
RETURNING id
""")

# The article may already exist from an earlier run, and its id is needed to
# anchor the label row. The URL is the only key both runs agree on.
ARTICLE_ID_FOR_URL = text("SELECT id FROM articles WHERE url = :url")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file", required=True, help="JSON array of the labeled sheet's rows"
    )
    parser.add_argument("--dataset", default=DATASET_SLUG)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--limit", type=int, default=0, help="stop after this many records"
    )
    args = parser.parse_args()

    with open(args.file, encoding="utf-8") as handle:
        rows = json.load(handle)
    print(f"read {len(rows)} rows from {args.file}")

    db = DatabaseManager()
    with db.get_session() as session:
        hosts = load_hosts(session, args.dataset)
        if not hosts:
            print(f"ERROR: dataset {args.dataset} has no sources")
            return 1
        print(f"dataset {args.dataset}: {len(hosts)} hosts")

        records, skipped = build_records(rows, hosts)
        if args.limit:
            records = records[: args.limit]

        print(f"\n{len(records)} records ready, {sum(skipped.values())} skipped")
        for reason, count in skipped.most_common():
            print(f"  skipped {count:4}  {reason}")

        by_host = Counter(link["host"] for link, _ in records)
        print(f"\nacross {len(by_host)} publishers:")
        for host, count in by_host.most_common():
            print(f"  {count:4}  {host}")

        labels = Counter(article["primary_label"] for _, article in records)
        print("\nprimary label distribution:")
        for label, count in labels.most_common():
            print(f"  {count:4}  {label}")

        checked = sum(
            1
            for _, a in records
            if json.loads(a["metadata"])["wsu_notebook"]["human_check"]
        )
        print(f"\n{checked} records carry a human check")

        if args.dry_run:
            print("\n--dry-run: nothing written")
            return 0

        written_links = written_articles = written_labels = 0
        missing = 0
        for link, article in records:
            if session.execute(INSERT_LINK, link).first() is not None:
                written_links += 1
            if session.execute(INSERT_ARTICLE, article).first() is not None:
                written_articles += 1
                article_id = article["id"]
            else:
                # The article already exists from an earlier run. Its own id was
                # generated then, not now, so the label has to be anchored to
                # the stored row rather than to this pass's UUID.
                found = session.execute(
                    ARTICLE_ID_FOR_URL, {"url": article["url"]}
                ).first()
                if found is None:
                    missing += 1
                    continue
                article_id = found[0]
            session.execute(
                UPSERT_LABEL,
                {
                    "id": str(uuid.uuid4()),
                    "article_id": article_id,
                    "label_version": LABEL_VERSION,
                    "model_version": LABEL_MODEL_VERSION,
                    "model_path": None,
                    "primary_label": article["primary_label"],
                    "alternate_label": article["alternate_label"],
                    "meta": json.dumps({"source": "wsu-notebook-import"}),
                },
            )
            written_labels += 1
        session.commit()
        print(
            f"\nwrote {written_links} candidate_links, "
            f"{written_articles} articles, {written_labels} label rows"
        )
        if missing:
            print(f"WARNING: {missing} records had neither a new nor a stored article")
    return 0


if __name__ == "__main__":
    sys.exit(main())
