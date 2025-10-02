#!/usr/bin/env python
"""Re-run publish-date extraction on a saved evaluation sample.

Reads the baseline artifact (default:
artifacts/publish_date_fallback_eval.json) for its list of URLs, runs
`ContentExtractor` against each, and writes a new artifact containing
comparable fields for before/after analysis.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from src.crawler import ContentExtractor


def load_baseline(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError("Baseline artifact missing 'results' array")
    return results


def build_record(entry: dict, extracted: dict, error: str | None) -> dict:
    url = entry.get("url") or extracted.get("url")
    parsed = urlparse(url or "")
    content = extracted.get("content") if extracted else ""
    metadata = extracted.get("metadata") if extracted else None
    publish_date = extracted.get("publish_date") if extracted else None

    return {
        "article_id": entry.get("article_id"),
        "url": url,
        "host": entry.get("host") or parsed.netloc,
        "content_length": len(content or ""),
        "publish_date_found": bool(publish_date),
        "publish_date": publish_date,
        "extraction_method_publish_date": (
            (metadata or {})
            .get("extraction_methods", {})
            .get("publish_date", "none")
        ),
        "fallback_metadata": (metadata or {})
        .get("fallbacks", {})
        .get("publish_date"),
        "metadata": metadata,
        "error": error,
    }


def run_evaluation(
    baseline_path: Path,
    output_path: Path,
    *,
    limit: int | None = None,
    timeout: int = 20,
) -> dict:
    entries = load_baseline(baseline_path)
    if limit is not None:
        entries = entries[:limit]

    extractor = ContentExtractor(timeout=timeout)

    results: list[dict] = []
    for idx, entry in enumerate(entries, start=1):
        url = entry.get("url")
        if not url:
            results.append(build_record(entry, {}, "missing URL"))
            continue

        try:
            extracted = extractor.extract_content(url)
            record = build_record(entry, extracted, None)
        except Exception as exc:  # noqa: BLE001 - capture for artifact
            record = build_record(entry, {}, str(exc))

        results.append(record)
        progress = f"[{idx}/{len(entries)}] {url}"
        status = "OK" if not record["error"] else f"ERROR: {record['error']}"
        print(f"{progress} -> {status}")

    artifact = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "sample_size": len(entries),
        "results": results,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(artifact, handle, indent=2)

    return artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("artifacts/publish_date_fallback_eval.json"),
        help="Path to baseline artifact JSON",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/publish_date_fallback_eval_new.json"),
        help="Destination path for the new artifact",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optionally limit the number of URLs processed",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="Per-request timeout supplied to ContentExtractor",
    )
    args = parser.parse_args(argv)

    try:
        run_evaluation(
            baseline_path=args.input,
            output_path=args.output,
            limit=args.limit,
            timeout=args.timeout,
        )
    except Exception as exc:  # noqa: BLE001 - surface meaningful error code
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
