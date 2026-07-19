#!/usr/bin/env python3
"""Extraction-quality comparison harness.

Compares a ground-truth "cleaned" corpus (e.g. a manually-cleaned CIEP export)
against what an extractor actually produced, so extractor changes can be
measured against real records instead of assumptions.

Comparison source (``--source``):

* ``bq-content`` (default) / ``bq-text``: join the corpus to
  ``mizzou_analytics.articles`` on URL and compare the ground-truth text to the
  stored ``content`` (raw extractor output) or ``text`` (auto-cleaned) column.
  Fast, one BigQuery scan.

  This is the ONLY sound comparison source, because the stored columns are the
  product of the REAL extraction path — fetched through the production Squid
  proxy with the pipeline's fingerprinting / UA rotation / Selenium fallback.

  Do NOT add a "re-fetch the URL locally and run extractor X" mode: a naive
  local request bypasses the proxy and bot handling, so on bot-protected sites
  it returns challenge/blocked pages, not articles — producing garbage
  comparisons. To A/B a CANDIDATE extractor (e.g. trafilatura), deploy it,
  let the Argo pipeline re-crawl through the proxy so its output lands in
  ``articles``, then re-run this script with ``--source bq-content``.

Metrics reported (aggregate + per-host + worst cases):
  - match rate (corpus URLs found in the source)
  - size ratio  extractor_len / clean_len  (>1 = kept extra text/boilerplate)
  - text similarity (token-set Jaccard on mojibake-fixed, normalized text)
  - overshoot / undershoot counts, grouped by host (finds problem CMSs)
  - recurring leading/trailing fragments present in the extractor output but
    absent from the clean text — i.e. candidate boilerplate strings

Ground truth quality note: manually-cleaned corpora are uneven; some records
retain boilerplate the cleaner missed. Use ``--min-clean-len`` and eyeball the
worst cases before treating any single number as gospel.

Cost: the BQ modes scan the ``content``/``text`` columns of the articles table
once (~$0.003 at ~700MB). Live re-extraction makes one HTTP request per URL.

Example:
  python scripts/extraction_quality_report.py \
    --corpus /path/mo_march_cleaned.csv --url-col url --text-col text \
    --source bq-content --sample 300 --out report.md
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from typing import Optional

# ftfy repairs export mojibake (â€™ -> ') so length/similarity aren't skewed by
# encoding artifacts rather than real extraction differences.
try:
    import ftfy

    def _demojibake(s: str) -> str:
        return ftfy.fix_text(s or "")

except Exception:  # pragma: no cover - ftfy is a normal dep, guard for safety

    def _demojibake(s: str) -> str:
        return s or ""


_WS = re.compile(r"\s+")


def _norm(s: Optional[str]) -> str:
    """Mojibake-fix + collapse whitespace for fair comparison."""
    return _WS.sub(" ", _demojibake(s or "")).strip()


def _host(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url or "").split("/")[0]


def _tokens(s: str) -> set:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _percentiles(values: list[float], ps=(10, 50, 90)) -> dict[int, float]:
    if not values:
        return dict.fromkeys(ps, 0.0)
    s = sorted(values)
    out = {}
    for p in ps:
        idx = min(len(s) - 1, int(round((p / 100) * (len(s) - 1))))
        out[p] = s[idx]
    return out


def load_corpus(path: str, url_col: str, text_col: str) -> dict[str, str]:
    import pandas as pd

    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    for col in (url_col, text_col):
        if col not in df.columns:
            raise SystemExit(f"column {col!r} not in corpus; have {list(df.columns)}")
    out: dict[str, str] = {}
    for url, text in zip(df[url_col], df[text_col], strict=False):
        if url.startswith("http") and text and url not in out:
            out[url] = text
    return out


def fetch_bq(urls: list[str], column: str, project: str) -> dict[str, str]:
    """Return {url: <column value>} from the articles table for the given URLs."""
    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    out: dict[str, str] = {}
    for i in range(0, len(urls), 400):  # keep IN-lists sane
        batch = urls[i : i + 400]
        q = (
            f"SELECT url, {column} AS val "
            f"FROM `{project}.mizzou_analytics.articles` "
            "WHERE url IN UNNEST(@urls)"
        )
        job = client.query(
            q,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[bigquery.ArrayQueryParameter("urls", "STRING", batch)]
            ),
        )
        for row in job:
            if row["url"] not in out and row["val"]:
                out[row["url"]] = row["val"]
    return out


def compare(
    clean: dict[str, str],
    extracted: dict[str, str],
    overshoot: float,
    undershoot: float,
) -> dict:
    pairs = []
    for url, ct in clean.items():
        ex = extracted.get(url)
        if ex is None:
            continue
        c, e = _norm(ct), _norm(ex)
        if not c or not e:
            continue
        ratio = len(e) / len(c)
        pairs.append(
            {
                "url": url,
                "host": _host(url),
                "clean_len": len(c),
                "ex_len": len(e),
                "ratio": ratio,
                "sim": _jaccard(c, e),
                "clean": c,
                "ex": e,
            }
        )

    over = [p for p in pairs if p["ratio"] > overshoot]
    under = [p for p in pairs if p["ratio"] < undershoot]

    # Per-host overshoot concentration (which CMSs leak boilerplate)
    host_over = Counter(p["host"] for p in over)

    # Candidate boilerplate: recurring leading/trailing fragments present in the
    # extractor output but not the clean text.
    frag_counter: Counter = Counter()
    for p in over:
        c, e = p["clean"], p["ex"]
        if c[:40] not in e:
            frag_counter[e[:80]] += 1  # leading junk before the body starts
        tail = e[-80:]
        if tail.strip() and c[-40:] not in e[-200:]:
            frag_counter[tail] += 1  # trailing junk after the body ends

    return {
        "n": len(pairs),
        "matched_urls": len(extracted),
        "corpus_urls": len(clean),
        "ratio_pct": _percentiles([p["ratio"] for p in pairs]),
        "sim_pct": _percentiles([p["sim"] for p in pairs]),
        "overshoot": over,
        "undershoot": under,
        "host_over": host_over,
        "fragments": frag_counter,
        "pairs": pairs,
    }


def render(r: dict, source: str, worst: int) -> str:
    L = []
    L.append(f"# Extraction quality report — source: `{source}`\n")
    L.append(
        f"- corpus URLs: {r['corpus_urls']}  |  matched in source: "
        f"{r['matched_urls']}  |  compared pairs: {r['n']}"
    )
    rp, sp = r["ratio_pct"], r["sim_pct"]
    L.append(
        f"- size ratio (extractor/clean): p10 {rp[10]:.2f}  "
        f"median {rp[50]:.2f}  p90 {rp[90]:.2f}   (>1 = kept extra text)"
    )
    L.append(
        f"- token similarity to clean: p10 {sp[10]:.2f}  "
        f"median {sp[50]:.2f}  p90 {sp[90]:.2f}"
    )
    L.append(
        f"- overshoot (ratio high): {len(r['overshoot'])}  |  "
        f"undershoot (missing body): {len(r['undershoot'])}\n"
    )
    if r["host_over"]:
        L.append("## Overshoot concentrated by host (boilerplate-leaking CMSs)")
        for host, n in r["host_over"].most_common(15):
            L.append(f"  - {n:3d}  {host}")
        L.append("")
    if r["fragments"]:
        L.append(
            "## Recurring candidate-boilerplate fragments (in extractor, not clean)"
        )
        for frag, n in r["fragments"].most_common(15):
            if n > 1:
                L.append(f"  - {n:3d}x  {frag!r}")
        L.append("")
    L.append(f"## Worst {worst} overshoot cases")
    for p in sorted(r["overshoot"], key=lambda x: -x["ex_len"])[:worst]:
        L.append(f"\n### {p['host']}  ratio={p['ratio']:.2f} sim={p['sim']:.2f}")
        L.append(f"  URL: {p['url']}")
        L.append(f"  extractor head: {p['ex'][:160]}")
        L.append(f"  clean head:     {p['clean'][:160]}")
        L.append(f"  extractor tail: ...{p['ex'][-160:]}")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", required=True, help="ground-truth cleaned CSV")
    ap.add_argument("--url-col", default="url")
    ap.add_argument("--text-col", default="text", help="the cleaned/ground-truth text")
    ap.add_argument(
        "--source",
        default="bq-content",
        choices=["bq-content", "bq-text"],
        help="which stored extractor column to compare (both reflect the real "
        "proxied pipeline; see module docstring on A/B-ing a candidate)",
    )
    ap.add_argument("--sample", type=int, default=300, help="0 = all corpus URLs")
    ap.add_argument("--project", default="mizzou-news-crawler")
    ap.add_argument("--overshoot", type=float, default=1.3)
    ap.add_argument("--undershoot", type=float, default=0.6)
    ap.add_argument("--min-clean-len", type=int, default=200)
    ap.add_argument("--worst", type=int, default=10)
    ap.add_argument("--out", help="write markdown report here (else stdout)")
    args = ap.parse_args()

    clean = load_corpus(args.corpus, args.url_col, args.text_col)
    clean = {u: t for u, t in clean.items() if len(_norm(t)) >= args.min_clean_len}
    urls = list(clean)
    if args.sample:
        urls = urls[: args.sample]
        clean = {u: clean[u] for u in urls}

    column = "content" if args.source == "bq-content" else "text"
    extracted = fetch_bq(urls, column, args.project)

    result = compare(clean, extracted, args.overshoot, args.undershoot)
    report = render(result, args.source, args.worst)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(report)
        print(f"wrote {args.out}  ({result['n']} pairs compared)")
    else:
        print(report)


if __name__ == "__main__":
    main()
