#!/usr/bin/env python3
import argparse
import json
import os
import statistics
from pathlib import Path
from typing import Any, Dict, List, Tuple


def read_json(path: Path) -> Any:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        with open(path) as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    pass
    except Exception:
        pass
    return rows


def summarize_extraction_diag(data: Dict[str, Any]) -> Dict[str, Any]:
    results = data.get("results") or []
    total = len(results)
    successes = sum(1 for r in results if r.get("is_success"))
    failures = total - successes
    by_status: Dict[str, int] = {}
    for r in results:
        sc = str(r.get("http_status_code") or "")
        if sc:
            by_status[sc] = by_status.get(sc, 0) + 1
    methods_attempted: Dict[str, int] = {}
    successful_method: Dict[str, int] = {}
    errors: Dict[str, int] = {}
    for r in results:
        for m in (r.get("methods_attempted") or []):
            methods_attempted[m] = methods_attempted.get(m, 0) + 1
        if r.get("successful_method"):
            successful_method[r["successful_method"]] = successful_method.get(r["successful_method"], 0) + 1
        if r.get("error"):
            et = r.get("error", "")
            if et:
                # bucket by error type prefix if present
                errors[et] = errors.get(et, 0) + 1
    return {
        "total": total,
        "successes": successes,
        "failures": failures,
        "http_status": sorted(by_status.items(), key=lambda x: (-x[1], x[0]))[:10],
        "methods_attempted": sorted(methods_attempted.items(), key=lambda x: (-x[1], x[0]))[:10],
        "successful_method": sorted(successful_method.items(), key=lambda x: (-x[1], x[0]))[:10],
        "top_errors": sorted(errors.items(), key=lambda x: (-x[1], x[0]))[:10],
    }


def summarize_amp_diag(data: Dict[str, Any]) -> Dict[str, Any]:
    results = data.get("results") or []
    total = len(results)
    ok = [r for r in results if str(r.get("status")) == "200"]
    titles = [r.get("title", "") for r in ok]
    lengths = [int(r.get("text_len") or 0) for r in ok]
    stats = {}
    if lengths:
        stats = {
            "min": min(lengths),
            "max": max(lengths),
            "avg": round(statistics.mean(lengths), 1),
            "median": statistics.median(lengths),
        }
    return {
        "total": total,
        "http200": len(ok),
        "text_stats": stats,
    }


def summarize_probe_jsonl(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(rows)
    by_server: Dict[str, int] = {}
    by_code: Dict[str, int] = {}
    challenges = 0
    sample_entries: List[Dict[str, Any]] = []
    for r in rows:
        sv = (r.get("server") or "").lower()
        if sv:
            by_server[sv] = by_server.get(sv, 0) + 1
        code = str(r.get("http_code") or "")
        if code:
            by_code[code] = by_code.get(code, 0) + 1
        if r.get("challenge"):
            challenges += 1
        if len(sample_entries) < 5:
            out = r.get("out") or {}
            sample_entries.append({
                "url": r.get("url"),
                "http_code": r.get("http_code"),
                "server": (r.get("server") or "").strip(),
                "png": out.get("png"),
                "html": out.get("html"),
                "headers": out.get("headers"),
            })
    return {
        "total": total,
        "servers": sorted(by_server.items(), key=lambda x: (-x[1], x[0]))[:10],
        "http_status": sorted(by_code.items(), key=lambda x: (-x[1], x[0]))[:10],
        "challenge_true": challenges,
        "entries": sample_entries,
    }


def render_html(sections: List[Tuple[str, Dict[str, Any]]]) -> str:
    def table(title: str, kvs: List[Tuple[str, Any]]) -> str:
        rows = "\n".join(
            f"<tr><td class=key>{k}</td><td class=val>{v}</td></tr>" for k, v in kvs
        )
        return f"<h3>{title}</h3><table>{rows}</table>"

    css = """
body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 20px; }
h2 { margin-top: 30px; }
table { border-collapse: collapse; margin: 10px 0; }
td { border: 1px solid #ddd; padding: 6px 10px; vertical-align: top; }
td.key { font-weight: 600; background: #fafafa; width: 220px; }
td.val { width: 600px; }
code { background: #f5f5f5; padding: 2px 4px; }
"""
    parts = [f"<html><head><meta charset='utf-8'><style>{css}</style><title>Diagnostics Report</title></head><body>"]
    parts.append("<h1>Diagnostics Report</h1>")
    for title, summary in sections:
        parts.append(f"<h2>{title}</h2>")
        # Summary block (flatten lists)
        flat_summary: List[Tuple[str, Any]] = []
        for k, v in summary.items():
            if k == "entries":
                continue
            if isinstance(v, list):
                v = ", ".join([f"{a}:{b}" for a, b in v]) or "(none)"
            flat_summary.append((k, v))
        parts.append(table("Summary", flat_summary))

        # Entries block for probe JSONL
        if isinstance(summary.get("entries"), list) and summary.get("entries"):
            rows = "\n".join(
                f"<tr><td><code>{e.get('url') or ''}</code></td><td>{e.get('http_code') or ''}</td><td>{e.get('server') or ''}</td><td><code>{e.get('png') or ''}</code></td><td><code>{e.get('html') or ''}</code></td><td><code>{e.get('headers') or ''}</code></td></tr>"
                for e in summary["entries"]
            )
            parts.append(
                "<h3>Sample Entries</h3><table><tr><td class=key>URL</td><td class=key>Status</td><td class=key>Server</td><td class=key>Screenshot</td><td class=key>HTML</td><td class=key>Headers</td></tr>" + rows + "</table>"
            )
    parts.append("</body></html>")
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser(description="Render human-readable diagnostics from JSON/JSONL outputs")
    ap.add_argument("--input", action="append", required=True, help="Input file(s): JSON or JSONL")
    ap.add_argument("--out", default="reports/diag_report.html", help="Output HTML path")
    args = ap.parse_args()

    sections: List[Tuple[str, Dict[str, Any]]] = []
    for path in args.input:
        p = Path(path)
        if not p.exists():
            sections.append((f"{p}", {"error": "file not found"}))
            continue
        title = p.name
        if p.suffix.lower() == ".jsonl":
            rows = read_jsonl(p)
            sections.append((title, summarize_probe_jsonl(rows)))
        else:
            data = read_json(p) or {}
            if "results" in (data or {}):
                # try to detect AMP vs extractor diag by keys present
                sample = (data.get("results") or [{}])[0]
                if "text_len" in sample or "amp_url" in sample:
                    sections.append((title, summarize_amp_diag(data)))
                else:
                    sections.append((title, summarize_extraction_diag(data)))
            else:
                sections.append((title, {"note": "unrecognized JSON payload"}))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    html = render_html(sections)
    out.write_text(html, encoding="utf-8")
    print(f"Wrote HTML report to {out}")

    # Also print concise console summary
    for title, summary in sections:
        print(f"\n== {title} ==")
        for k, v in summary.items():
            if isinstance(v, list):
                # Skip verbose entries list in console
                if k == "entries":
                    v = f"{len(v)} entries"
                else:
                    try:
                        v = ", ".join([f"{a}:{b}" for a, b in v]) or "(none)"
                    except Exception:
                        v = f"{len(v)} items"
            print(f"- {k}: {v}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
