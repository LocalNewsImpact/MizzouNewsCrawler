#!/usr/bin/env python
"""Compare publish-date extraction results between two dry-run artifacts.

Usage:
    python tools/compare_publish_date_runs.py <baseline.json> <candidate.json>

The script prints:
    * Overall hit rate (publish_date_found) for both artifacts
    * Host-level counts of successful publish-date detections
    * Newly successful URLs in the candidate artifact (with strategy metadata)
    * Regressions (URLs that used to succeed but now fail)
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path


def load_results(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload.get("results", [])


def success_records(results: Iterable[dict]) -> list[dict]:
    return [record for record in results if record.get("publish_date_found")]


def summarize(label: str, results: list[dict]) -> None:
    total = len(results)
    successes = success_records(results)
    hit_rate = (len(successes) / total * 100) if total else 0.0
    message = f"{label}: {len(successes)}/{total} publish dates found ({hit_rate:.1f}%)"
    print(message)

    by_host = Counter(record.get("host") for record in successes)
    if by_host:
        print("  Successes by host:")
        for host, count in by_host.most_common():
            print(f"    {host}: {count}")
    else:
        print("  No publish dates found.")


def index_by_url(records: Iterable[dict]) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for record in records:
        url = record.get("url")
        if url:
            index[url] = record
    return index


def describe_strategy(record: dict) -> str:
    fallback = (record.get("metadata") or {}).get("fallbacks", {}).get("publish_date")
    if not fallback:
        return "n/a"
    source = fallback.get("source", "unknown")
    strategy = fallback.get("strategy")
    if strategy:
        return f"{source}:{strategy}"
    return source


def list_differences(
    label: str,
    urls: Iterable[str],
    index: dict[str, dict],
    *,
    regressions: bool = False,
) -> None:
    urls = sorted(set(urls))
    if not urls:
        print(f"No {label.lower()}.")
        return

    print(f"{label} ({len(urls)}):")
    for url in urls:
        extra = ""
        if not regressions:
            record = index.get(url, {})
            publish_date = record.get("publish_date")
            extra = f" -> {publish_date}" if publish_date else ""
            extra += f" [{describe_strategy(record)}]"
        else:
            # When reporting regressions, note previous strategy if available.
            record = index.get(url, {})
            fallback = (
                (record.get("metadata") or {}).get("fallbacks", {}).get("publish_date")
            )
            strategy = fallback.get("strategy") if fallback else None
            source = fallback.get("source") if fallback else None
            detail = ":".join(filter(None, [source, strategy])) if source else None
            previous = record.get("publish_date")
            if previous:
                extra = f" (was {previous}"
            else:
                extra = " (was missing"
            extra += f", strategy={detail})" if detail else ")"
        print(f"  {url}{extra}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "baseline",
        type=Path,
        help="Path to baseline artifact JSON",
    )
    parser.add_argument(
        "candidate",
        type=Path,
        help="Path to new run artifact JSON",
    )
    args = parser.parse_args()

    baseline_results = load_results(args.baseline)
    candidate_results = load_results(args.candidate)

    summarize("Baseline", baseline_results)
    summarize("Candidate", candidate_results)
    print("")

    baseline_success = success_records(baseline_results)
    candidate_success = success_records(candidate_results)

    baseline_urls = {
        url
        for record in baseline_success
        for url in [record.get("url")]
        if isinstance(url, str) and url
    }
    candidate_urls = {
        url
        for record in candidate_success
        for url in [record.get("url")]
        if isinstance(url, str) and url
    }

    new_urls = candidate_urls - baseline_urls
    lost_urls = baseline_urls - candidate_urls

    candidate_index = index_by_url(candidate_results)
    baseline_index = index_by_url(baseline_results)

    list_differences("Newly successful URLs", new_urls, candidate_index)
    print("")
    list_differences(
        "Regressions (previously successful, now missing)",
        lost_urls,
        baseline_index,
        regressions=True,
    )


if __name__ == "__main__":
    main()
