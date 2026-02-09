#!/usr/bin/env python3
"""Query MediaCloud for likely wire stories based on duplicated headlines.

Reads the CSV of extraction results with an `media_cloud_candidate` column
and submits each marked headline to the MediaCloud search API. Responses are
rate-limited to two requests per minute to stay within the documented quota.

Usage example:
    python scripts/run_mediacloud_headline_check.py \
        --input exports/articles_extracted_20251205_media_cloud.csv \
        --output exports/articles_extracted_20251205_media_cloud_results.csv \
        --token 28deb19bd48a9030a0f657bdd85b93ec4a84f77e

Alternatively set the `MEDIACLOUD_API_TOKEN` environment variable instead of
passing `--token` explicitly.
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.services.wire_detection import (
    APIResponseError,
    DEFAULT_RATE_PER_MINUTE,
    DetectionResult,
    MCException,
    MediaCloudArticle,
    MediaCloudDetector,
    MissingDependencyError,
    normalize_host,
    parse_iso8601,
)


LOG = logging.getLogger(__name__)


@dataclass
class ArticleRecord:
    article_id: str
    source: str
    url: str
    title: str
    extracted_at: Optional[datetime]
    marker: str

    @property
    def host(self) -> str:
        return normalize_host(self.url)


def load_candidates(path: str) -> list[ArticleRecord]:
    records: list[ArticleRecord] = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required_fields = {"media_cloud_candidate", "article_id", "source", "url", "title", "extracted_at_utc"}
        missing = required_fields - set(reader.fieldnames or [])
        if missing:
            raise RuntimeError(f"Input CSV '{path}' missing fields: {', '.join(sorted(missing))}")
        for row in reader:
            marker = (row.get("media_cloud_candidate") or "").strip().lower()
            if marker != "x":
                continue
            extracted_at = parse_iso8601(row.get("extracted_at_utc", ""))
            records.append(
                ArticleRecord(
                    article_id=row.get("article_id", "").strip(),
                    source=row.get("source", "").strip(),
                    url=row.get("url", "").strip(),
                    title=row.get("title", "").strip(),
                    extracted_at=extracted_at,
                    marker=marker,
                )
            )
    return records


def write_results(path: str, rows: list[dict], fieldnames: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO if not args.verbose else logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")

    token = args.token or os.getenv("MEDIACLOUD_API_TOKEN")
    if not token:
        LOG.error(
            "No MediaCloud API token provided. Use --token or set MEDIACLOUD_API_TOKEN."
        )
        return 1

    try:
        detector = MediaCloudDetector.from_token(token, rate_per_minute=args.rate, logger=LOG)
        user_info = detector.search_api.user_profile()
        LOG.info(
            "Authenticated as MediaCloud user '%s' (roles=%s)",
            user_info.get("username"),
            user_info.get("roles"),
        )
    except MissingDependencyError as exc:
        LOG.error("%s", exc)
        return 1
    except MCException as exc:
        LOG.error("Failed to initialize MediaCloud API client: %s", exc)
        return 1
    except APIResponseError as exc:
        LOG.error("Failed to authenticate against MediaCloud API: %s", exc)
        return 1

    candidates = load_candidates(args.input)
    if not candidates:
        LOG.warning("No candidates marked with 'x' found in %s", args.input)
        return 0

    LOG.info(
        "Loaded %d candidate headlines; rate limiting to %.2f calls/minute",
        len(candidates),
        args.rate,
    )

    results: list[dict] = []
    fieldnames = [
        "article_id",
        "source",
        "title",
        "url",
        "extracted_at_utc",
        "query",
        "media_cloud_story_count",
        "media_cloud_matched_story_count",
        "media_cloud_unique_hosts",
        "media_cloud_story_ids",
        "status",
    ]

    for idx, candidate in enumerate(candidates, start=1):
        LOG.info("[%d/%d] Processing '%s'", idx, len(candidates), candidate.title)
        detector_article = MediaCloudArticle(
            article_id=candidate.article_id,
            source=candidate.source,
            url=candidate.url,
            title=candidate.title,
            extracted_at=candidate.extracted_at,
        )
        detection: DetectionResult = detector.detect(detector_article)

        results.append(
            {
                "article_id": candidate.article_id,
                "source": candidate.source,
                "title": candidate.title,
                "url": candidate.url,
                "extracted_at_utc": candidate.extracted_at.isoformat() if candidate.extracted_at else "",
                "query": detection.query,
                "media_cloud_story_count": detection.story_count,
                "media_cloud_matched_story_count": detection.matched_story_count,
                "media_cloud_unique_hosts": "|".join(detection.matched_hosts),
                "media_cloud_story_ids": "|".join(detection.matched_story_ids),
                "status": detection.status,
            }
        )

        if detection.matched_hosts:
            LOG.info(
                "Matched %d other hosts: %s",
                len(detection.matched_hosts),
                ", ".join(detection.matched_hosts),
            )
        if args.limit and idx >= args.limit:
            LOG.info("Reached iteration limit of %d; stopping early", args.limit)
            break

    write_results(args.output, results, fieldnames)
    LOG.info("Wrote %d rows to %s", len(results), args.output)
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check MediaCloud for duplicated headlines.")
    parser.add_argument("--input", default="exports/articles_extracted_20251205_media_cloud.csv", help="Path to candidate CSV (default: %(default)s)")
    parser.add_argument("--output", default="exports/articles_extracted_20251205_media_cloud_results.csv", help="Where to write MediaCloud results (default: %(default)s)")
    parser.add_argument("--token", help="MediaCloud API token (or set MEDIACLOUD_API_TOKEN env var)")
    parser.add_argument("--rate", type=float, default=DEFAULT_RATE_PER_MINUTE, help="Maximum API calls per minute (default: %(default)s)")
    parser.add_argument("--limit", type=int, help="Only process the first N candidates (useful for testing)")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    return parser


if __name__ == "__main__":
    parser = build_arg_parser()
    sys.exit(run(parser.parse_args()))
