"""The give-up path against a real PostgreSQL: `jsonb_set`, `RETURNING` after
`UPDATE`, and the link restore all have semantics a mock cannot check.

Seeds an article whose link was rewound with two tries already spent, spends
the third, and reads back what every stage will see.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from src.pipeline import refetch
from src.pipeline.rework import ABANDONED, MAX_ATTEMPTS

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL")
    or "postgresql" not in os.getenv("TEST_DATABASE_URL", ""),
    reason="PostgreSQL test database not configured",
)
def test_the_third_failed_try_retires_the_link_and_keeps_the_record():
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    suffix = uuid.uuid4().hex[:8]
    source_id, link_id, article_id = (
        str(uuid.uuid4()),
        f"gu-link-{suffix}",
        f"gu-art-{suffix}",
    )
    note = {
        "refetch": {
            "by": "t",
            "reason": "r",
            "previous_link_status": "extracted",
            "attempts": MAX_ATTEMPTS - 1,
        }
    }
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO sources (id, host, host_norm) VALUES (:id, :h, :h)"),
            {"id": source_id, "h": f"{suffix}.example"},
        )
        conn.execute(
            text(
                "INSERT INTO candidate_links (id, url, source, source_id, status, discovered_at) "
                "VALUES (:id, :url, 't', :sid, :st, now())"
            ),
            {
                "id": link_id,
                "url": f"https://{suffix}.example/",
                "sid": source_id,
                "st": refetch.REFETCH,
            },
        )
        conn.execute(
            text(
                "INSERT INTO articles (id, candidate_link_id, url, status, wire_check_status, title, "
                "author, text, raw, metadata, created_at, extracted_at, enrichment_attempts) VALUES "
                "(:id, :lid, :url, 'text_unavailable', 'local', 'Headline', 'Jane Doe', 'old body', "
                "'old body', CAST(:meta AS json), now(), now(), 0)"
            ),
            {
                "id": article_id,
                "lid": link_id,
                "url": f"https://{suffix}.example/story",
                "meta": json.dumps(note),
            },
        )
    try:
        with engine.begin() as conn:
            gave_up = refetch.spend_attempt(conn, [link_id])
        assert gave_up == {link_id}
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT a.status, a.title, a.author, a.text, a.metadata, cl.status "
                    "FROM articles a JOIN candidate_links cl ON cl.id = a.candidate_link_id "
                    "WHERE a.id = :id"
                ),
                {"id": article_id},
            ).one()
        meta = row[4] if isinstance(row[4], dict) else json.loads(row[4])
        assert row[0] == refetch.TEXT_UNAVAILABLE
        assert (row[1], row[2], row[3]) == (
            "Headline",
            "Jane Doe",
            "old body",
        ), "the record survives"
        assert meta["refetch"]["attempts"] == MAX_ATTEMPTS
        assert meta["refetch"]["outcome"] == ABANDONED
        assert meta["refetch"]["by"] == "t", "sibling keys survive jsonb_set"
        assert (
            row[5] == "extracted"
        ), "the link got back the status it had before the rewind"
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM articles WHERE id = :id"), {"id": article_id}
            )
            conn.execute(
                text("DELETE FROM candidate_links WHERE id = :id"), {"id": link_id}
            )
            conn.execute(text("DELETE FROM sources WHERE id = :id"), {"id": source_id})


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL")
    or "postgresql" not in os.getenv("TEST_DATABASE_URL", ""),
    reason="PostgreSQL test database not configured",
)
def test_a_404_does_not_undo_the_404():
    """Giving up after a 404 keeps the link at 404: that answer is better than
    the one it had before the rewind."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    suffix = uuid.uuid4().hex[:8]
    source_id, link_id, article_id = (
        str(uuid.uuid4()),
        f"g4-link-{suffix}",
        f"g4-art-{suffix}",
    )
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO sources (id, host, host_norm) VALUES (:id, :h, :h)"),
            {"id": source_id, "h": f"{suffix}.example"},
        )
        conn.execute(
            text(
                "INSERT INTO candidate_links (id, url, source, source_id, status, discovered_at) "
                "VALUES (:id, :url, 't', :sid, '404', now())"
            ),
            {"id": link_id, "url": f"https://{suffix}.example/", "sid": source_id},
        )
        conn.execute(
            text(
                "INSERT INTO articles (id, candidate_link_id, url, status, wire_check_status, title, "
                "metadata, created_at, extracted_at, enrichment_attempts) VALUES "
                "(:id, :lid, :url, 'labeled', 'local', 'H', CAST(:meta AS json), now(), now(), 0)"
            ),
            {
                "id": article_id,
                "lid": link_id,
                "url": f"https://{suffix}.example/s",
                "meta": json.dumps({"refetch": {"previous_link_status": "extracted"}}),
            },
        )
    try:
        with engine.begin() as conn:
            assert refetch.give_up(conn, [link_id], outcome="404") == 1
            row = conn.execute(
                text(
                    "SELECT a.status, cl.status FROM articles a "
                    "JOIN candidate_links cl ON cl.id = a.candidate_link_id WHERE a.id = :id"
                ),
                {"id": article_id},
            ).one()
        assert row == (refetch.TEXT_UNAVAILABLE, "404")
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM articles WHERE id = :id"), {"id": article_id}
            )
            conn.execute(
                text("DELETE FROM candidate_links WHERE id = :id"), {"id": link_id}
            )
            conn.execute(text("DELETE FROM sources WHERE id = :id"), {"id": source_id})
