import sys
import json
from datetime import datetime
from typing import Dict, Any, List, Tuple


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r") as f:
        return json.load(f)


def counts_to_total(counts: List[List[Any]]) -> int:
    total = 0
    for item in counts:
        # item may be [status, count]
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            try:
                total += int(item[1])
            except (TypeError, ValueError):
                pass
    return total


def counts_lookup(counts: List[List[Any]], status: str) -> int:
    for item in counts:
        if isinstance(item, (list, tuple)) and len(item) >= 2 and item[0] == status:
            try:
                return int(item[1])
            except (TypeError, ValueError):
                return 0
    return 0


def to_markdown(data: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Domain Discovery & Extraction (last 60 days)")
    lines.append("")
    gen_at = data.get("generated_at") or datetime.utcnow().isoformat()
    lines.append(f"Generated at: {gen_at}")
    domains = data.get("domains", [])
    if domains:
        lines.append(f"Domains: {', '.join(domains)}")
    hosts_resolved = data.get("hosts_resolved", [])
    if hosts_resolved:
        lines.append(f"Resolved hosts: {', '.join(hosts_resolved)}")
    lines.append("")

    per_host: Dict[str, Any] = data.get("per_host", {})
    for host in hosts_resolved or per_host.keys():
        host_data = per_host.get(host, {})
        counts: List[List[Any]] = host_data.get("counts", [])
        article_not_extracted = int(host_data.get("article_not_extracted", 0) or 0)
        # Try both keys for discovered counts
        discovered_status_count = int(host_data.get("discovered_status_count", host_data.get("discovered_count", 0)) or 0)
        discovered_total = int(host_data.get("discovered_total", counts_to_total(counts)) or 0)

        lines.append(f"## {host}")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("| - | - |")
        lines.append(f"| discovered_total | {discovered_total} |")
        lines.append(f"| discovered_status_count | {discovered_status_count} |")
        lines.append(f"| article_not_extracted | {article_not_extracted} |")

        lines.append("")
        lines.append("### Status Counts")
        lines.append("| status | count |")
        lines.append("| - | - |")
        for item in counts:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                try:
                    cnt = int(item[1])
                except (TypeError, ValueError):
                    cnt = 0
                st = str(item[0])
                lines.append(f"| {st} | {cnt} |")

        sample = host_data.get("sample_article_not_extracted", [])
        if sample:
            lines.append("")
            lines.append("### Sample Article Candidates Not Yet Extracted")
            for row in sample:
                cid = row.get("candidate_id")
                url = row.get("url")
                discovered_at = row.get("discovered_at")
                lines.append(f"- [{cid}] {url} (discovered_at: {discovered_at})")
        lines.append("")

    return "\n".join(lines)


def main(in_json: str, out_md: str):
    data = load_json(in_json)
    md = to_markdown(data)
    with open(out_md, "w") as f:
        f.write(md)
    print(f"Wrote Markdown: {out_md}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/domain_diag_to_md.py <input_json> <output_md>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
