"""Replay today's write-path cleaning against March's hand-cleaned corpus.

We have no raw HTML for March, so this cannot test the HTML-level fixes from
2026-07-30 (form/select-widget stripping, candidate-block selection). What it
CAN test: the text-level cleaning stack every article passes through in
`extraction.py` (ROT47 decode -> BalancedBoundaryContentCleaner, per-host
learned patterns -> excise_furniture_lines, vocabulary/concept removal) --
replayed on the same raw text those hand-cleaned articles started from, then
diffed against the human result.

Ground truth: ~/Library/.../CIEP/MO MARCH Final 51826.csv -- 15,653 rows,
`text` is hand-corrected (bylines and body both). This is the exact corpus
BOILERPLATE_MARKERS (src/utils/boilerplate.py) was derived from, so a match
partly measures "did we correctly re-encode what we already learned from this
set" rather than pure held-out generalization -- see the module docstring
there. The genuinely new signal is on rules NOT built from this corpus: the
paywall gate's bidirectional window and the bare-entitlement fix.

Raw baseline: mizzou_analytics.articles.text in BigQuery, joined on url.
Pulled once (~300MB, one query) rather than 15,653 individual lookups.

Two phases, run in different places -- the BigQuery client isn't in the
crawler/work-queue image, and DatabaseManager's Cloud SQL connector only
resolves correctly inside the cluster:

    # 1. Locally (has BigQuery creds): pull the raw baseline once.
    python scripts/march_cleaning_comparison.py fetch-raw \
        --raw-cache /tmp/march_raw.csv

    # 2. Decode leftover ROT47 in the ground truth itself (writes a NEW file;
    #    the original CIEP CSV is never touched). Only needs decode_rot47_segments,
    #    runs anywhere.
    python scripts/march_cleaning_comparison.py fix-ground-truth \
        --out /tmp/march_ground_truth_fixed.csv

    # 3. Copy the fixed ground truth and march_raw.csv into a pod with DB
    #    access, then there, pointing --march-csv at the FIXED file:
    python scripts/march_cleaning_comparison.py --march-csv /tmp/march_ground_truth_fixed.csv \
        compare --raw-cache /tmp/march_raw.csv --out exports/march_cleaning_comparison.csv
"""

from __future__ import annotations

import argparse
import csv
import difflib
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MARCH_CSV = Path(
    "~/Library/Mobile Documents/com~apple~CloudDocs/Documents/Mizzou/CIEP/"
    "MO MARCH Final 51826.csv"
).expanduser()

MATCH_RATIO = 0.98
CLOSE_RATIO = 0.90

RAW_CACHE_FIELDS = ["id", "url", "text"]


def load_ground_truth(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            url = row.get("url", "").strip()
            if url:
                rows[url] = row
    return rows


def cmd_fetch_raw(args: argparse.Namespace) -> int:
    """Phase 1 (run locally, needs BigQuery creds). No DB, no cleaner import."""
    from google.cloud import bigquery

    print(f"Loading ground truth from {args.march_csv} ...")
    ground_truth = load_ground_truth(args.march_csv)
    urls = set(ground_truth)
    print(f"  {len(urls)} hand-cleaned rows")

    print("Querying mizzou_analytics.articles (id, url, text) ...")
    client = bigquery.Client()
    query = "SELECT id, url, text FROM `mizzou_analytics.articles`"

    out_path = Path(args.raw_cache)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    matched = 0
    with out_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=RAW_CACHE_FIELDS)
        writer.writeheader()
        for row in client.query(query).result():
            if row.url in urls:
                writer.writerow({"id": row.id, "url": row.url, "text": row.text})
                matched += 1

    print(f"Matched {matched}/{len(urls)} URLs. Raw cache written to {out_path}")
    if matched < len(urls):
        print(
            f"  {len(urls) - matched} March URLs had no BigQuery row (will be "
            f"skipped at compare time)"
        )
    return 0


def cmd_fix_ground_truth(args: argparse.Namespace) -> int:
    """Decode leftover ROT47 in the hand-cleaned corpus itself.

    March was hand-cleaned before this decoder existed. TownNews/Lee sites
    serve premium paragraphs ROT47-encoded rather than withheld, so a human
    cleaner reading the rendered page saw the free preview and never noticed
    ciphertext starting mid-article -- 1,093 of 15,653 rows (7.0%) still carry
    it, concentrated on the TownNews-family hosts already known for this
    (columbiamissourian.com 90%, missourian.com 92%, joplinglobe.com 82%,
    newspressnow.com 88%, stltoday.com 30%, comobuz.com 50%).

    This is a standalone, auditable correction to the ground truth -- not
    something folded into the comparison step, which stays a plain diff
    against whatever file this produces. Writes a NEW file; the original
    CIEP CSV is never modified.
    """
    from src.pipeline.text_cleaning import decode_rot47_segments

    def decode_capture(raw: str | None) -> str:
        if not raw:
            return raw or ""
        return decode_rot47_segments(raw) or raw

    print(f"Reading {args.march_csv} ...")
    with args.march_csv.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        rows = list(reader)
    print(f"  {len(rows)} rows")

    changed = 0
    by_host: Counter[str] = Counter()
    for row in rows:
        original = row.get("text") or ""
        decoded = decode_capture(original)
        if decoded != original:
            row["text"] = decoded
            changed += 1
            by_host[row.get("host", "")] += 1

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Decoded {changed}/{len(rows)} rows ({100 * changed / len(rows):.1f}%)")
    print("By host:")
    for host, n in by_host.most_common(20):
        print(f"  {host:35} {n:5}")
    print()
    print(f"Corrected ground truth written to {out_path}")
    print(f"Original file untouched: {args.march_csv}")
    return 0


def classify(ratio: float, replayed_len: int, hand_len: int) -> str:
    if ratio >= MATCH_RATIO:
        return "MATCH"
    if ratio >= CLOSE_RATIO:
        return "CLOSE"
    if replayed_len > hand_len:
        return "UNDER_CLEANED"
    if replayed_len < hand_len:
        return "OVER_CLEANED"
    return "DIVERGENT"


def cmd_compare(args: argparse.Namespace) -> int:
    """Phase 2 (run inside the cluster, needs DatabaseManager/Cloud SQL)."""
    from src.models.database import DatabaseManager
    from src.pipeline.text_cleaning import decode_rot47_segments
    from src.utils.boilerplate import excise_furniture_lines
    from src.utils.content_cleaner_balanced import BalancedBoundaryContentCleaner

    def decode_capture(raw: str | None) -> str:
        if not raw:
            return raw or ""
        return decode_rot47_segments(raw) or raw

    print(f"Loading ground truth from {args.march_csv} ...")
    ground_truth = load_ground_truth(args.march_csv)
    if args.limit:
        ground_truth = dict(list(ground_truth.items())[: args.limit])
    print(f"  {len(ground_truth)} hand-cleaned rows")

    print(f"Loading raw cache from {args.raw_cache} ...")
    raw_by_url: dict[str, dict] = {}
    with Path(args.raw_cache).open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            raw_by_url[row["url"]] = row
    print(f"  {len(raw_by_url)} raw rows")

    db = DatabaseManager()
    cleaner = BalancedBoundaryContentCleaner(enable_telemetry=False, db=db)

    bucket_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    host_bucket: dict[str, Counter[str]] = defaultdict(Counter)
    missing = 0
    total = 0

    # Streamed, not accumulated: buffering all 15k rows' three full-text
    # copies in memory OOM-killed the 512Mi work-queue pod at ~7,500 rows.
    # This bounds memory to one row at a time.
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "url",
        "host",
        "title",
        "bucket",
        "ratio",
        "raw_len",
        "cleaned_len",
        "hand_len",
        "furniture_kinds",
        "raw_text",
        "our_cleaned_text",
        "hand_cleaned_text",
    ]
    with out_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()

        for i, (url, gt_row) in enumerate(ground_truth.items()):
            raw = raw_by_url.get(url)
            if raw is None:
                missing += 1
                continue

            hand_text = (gt_row.get("text") or "").strip()
            host = gt_row.get("host") or urlparse(url).netloc

            decoded = decode_capture(raw["text"])
            stripped, _meta = cleaner.process_single_article(
                text=decoded,
                domain=host,
                article_id=raw["id"],
                dry_run=True,
            )
            cleaned, kinds = excise_furniture_lines(stripped)
            cleaned = cleaned.strip()

            ratio = difflib.SequenceMatcher(None, cleaned, hand_text).ratio()
            bucket = classify(ratio, len(cleaned), len(hand_text))

            bucket_counts[bucket] += 1
            host_bucket[host][bucket] += 1
            for k in kinds:
                kind_counts[k] += 1
            total += 1

            writer.writerow(
                {
                    "url": url,
                    "host": host,
                    "title": gt_row.get("title", ""),
                    "bucket": bucket,
                    "ratio": round(ratio, 4),
                    "raw_len": len(raw["text"] or ""),
                    "cleaned_len": len(cleaned),
                    "hand_len": len(hand_text),
                    "furniture_kinds": ",".join(sorted(kinds)),
                    "raw_text": decoded,
                    "our_cleaned_text": cleaned,
                    "hand_cleaned_text": hand_text,
                }
            )

            if (i + 1) % 500 == 0:
                print(f"  ...{i + 1}/{len(ground_truth)}")

    if total == 0:
        print(
            "No rows compared -- nothing matched between ground truth and " "raw cache."
        )
        return 1

    print()
    print(f"Compared {total} rows ({missing} had no raw-cache match, skipped)")
    print()
    print("Bucket distribution:")
    for bucket, count in bucket_counts.most_common():
        print(f"  {bucket:15} {count:6}  ({100 * count / total:.1f}%)")
    print()
    print("Furniture kinds removed (rows firing each, may overlap):")
    for kind, count in kind_counts.most_common():
        print(f"  {kind:15} {count:6}")
    print()
    print("Worst hosts by non-MATCH rate (min 5 articles):")
    host_rates = []
    for host, counts in host_bucket.items():
        n = sum(counts.values())
        if n < 5:
            continue
        non_match = n - counts.get("MATCH", 0)
        host_rates.append((non_match / n, n, host))
    host_rates.sort(reverse=True)
    for rate, n, host in host_rates[:20]:
        print(f"  {host:35} {rate * 100:5.1f}% non-match  (n={n})")

    print()
    print(f"Per-row detail written to {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--march-csv", type=Path, default=MARCH_CSV, help="Hand-cleaned ground truth"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch-raw", help="Pull the raw baseline from BigQuery")
    p_fetch.add_argument("--raw-cache", required=True)
    p_fetch.set_defaults(func=cmd_fetch_raw)

    p_fix = sub.add_parser(
        "fix-ground-truth", help="Decode leftover ROT47 in the hand-cleaned corpus"
    )
    p_fix.add_argument("--out", required=True)
    p_fix.set_defaults(func=cmd_fix_ground_truth)

    p_compare = sub.add_parser(
        "compare", help="Replay cleaning and diff vs hand-cleaned"
    )
    p_compare.add_argument("--raw-cache", required=True)
    p_compare.add_argument("--out", default="exports/march_cleaning_comparison.csv")
    p_compare.add_argument("--limit", type=int, default=None)
    p_compare.set_defaults(func=cmd_compare)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
