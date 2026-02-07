import argparse
import json
import sys
import ssl
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from typing import List, Dict

from html.parser import HTMLParser


class AMPExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_h1 = False
        self.in_article = False
        self.title = ""
        self.text_parts: List[str] = []
        self.publish_date = ""
        self.is_amp = False
        self.amp_link: str = ""

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "html":
            # AMP pages typically have <html amp> or <html ⚡>
            attrs_dict = dict(attrs)
            if "amp" in attrs_dict or any(k == "amp" for k, _ in attrs):
                self.is_amp = True
        if tag.lower() == "link":
            # Discover canonical AMP link
            attrs_dict = dict(attrs)
            rel = (attrs_dict.get("rel") or "").lower()
            href = attrs_dict.get("href") or ""
            if "amphtml" in rel and href:
                self.amp_link = href
        if tag.lower() == "h1":
            self.in_h1 = True
        if tag.lower() == "article":
            self.in_article = True
        if tag.lower() == "time":
            attrs_dict = dict(attrs)
            self.publish_date = attrs_dict.get("datetime", "")

    def handle_endtag(self, tag):
        if tag.lower() == "h1":
            self.in_h1 = False
        if tag.lower() == "article":
            self.in_article = False

    def handle_data(self, data):
        if self.in_h1:
            self.title += data.strip()
        if self.in_article:
            s = data.strip()
            if s:
                self.text_parts.append(s)

    def result(self) -> Dict[str, str]:
        return {
            "is_amp": self.is_amp,
            "amp_link": self.amp_link,
            "title": self.title.strip(),
            "publish_date": self.publish_date,
            "text": "\n".join(self.text_parts).strip(),
        }


def discover_amp_url(html: str) -> str:
    parser = AMPExtractor()
    parser.feed(html)
    return parser.amp_link


def fetch(url: str) -> Dict[str, str]:
    # Basic fetch with a newspaper-like UA
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    ctx = ssl.create_default_context()
    with urlopen(req, context=ctx) as resp:
        status = resp.getcode()
        headers = {k.lower(): v for k, v in resp.headers.items()}
        body = resp.read().decode("utf-8", errors="replace")
    return {"status": str(status), "headers": headers, "body": body}


def extract_amp(urls: List[str]) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    for u in urls:
        try:
            # Fetch original page and discover AMP link
            base = fetch(u)
            amp_u = discover_amp_url(base["body"]) or ""
            amp_res: Dict[str, str] = {}
            amp_parsed: Dict[str, str] = {}
            if amp_u:
                amp_res = fetch(amp_u)
                parser = AMPExtractor()
                parser.feed(amp_res["body"])
                amp_parsed = parser.result()
            results.append(
                {
                    "input_url": u,
                    "original_status": base["status"],
                    "original_server": (base["headers"].get("server", "") if isinstance(base.get("headers"), dict) else ""),
                    "amp_url": amp_u,
                    "status": amp_res.get("status") if amp_u else None,
                    "server": (amp_res.get("headers", {}).get("server") if amp_u else None),
                    "content_type": (amp_res.get("headers", {}).get("content-type") if amp_u else None),
                    "is_amp": bool(amp_parsed.get("is_amp")) if amp_u else False,
                    "title": amp_parsed.get("title", "") if amp_u else "",
                    "publish_date": amp_parsed.get("publish_date", "") if amp_u else "",
                    "text_len": len(amp_parsed.get("text", "")) if amp_u else 0,
                    "no_amp": not bool(amp_u),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "input_url": u,
                    "amp_url": "",
                    "error": str(exc),
                }
            )
    return results


def main():
    ap = argparse.ArgumentParser(description="Try AMP fallback extraction for paywalled articles")
    ap.add_argument("--file", help="File containing article URLs (one per line)")
    ap.add_argument("--url", action="append", help="Single URL (can repeat)")
    ap.add_argument("--out", default="tmp/amp_extract_results.json", help="Output JSON file")
    args = ap.parse_args()

    urls: List[str] = []
    if args.file:
        try:
            with open(args.file) as f:
                urls.extend([ln.strip() for ln in f if ln.strip()])
        except Exception as exc:
            print(f"Error reading file: {exc}", file=sys.stderr)
    if args.url:
        urls.extend(args.url)

    if not urls:
        print("Provide --file or at least one --url", file=sys.stderr)
        return 2

    results = extract_amp(urls)

    # Save JSON
    try:
        import os
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
    except Exception:
        pass
    with open(args.out, "w") as f:
        json.dump({"results": results}, f, indent=2)

    # Print concise summary
    print("\nAMP Fallback Summary:\n")
    for r in results:
        if "error" in r:
            print(f"- ERROR {r['input_url']} → {r['amp_url']}: {r['error']}")
            continue
        if r.get("no_amp"):
            print(f"- NO AMP {r['input_url']} (original {r['original_status']})")
            continue
        ok = "OK" if str(r.get("status")) == "200" else f"HTTP {r.get('status')}"
        print(f"- {ok} {r['input_url']} → {r['amp_url']} | title='{r['title']}' | text_len={r['text_len']} | is_amp={r['is_amp']}")
    print(f"\nSaved: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
