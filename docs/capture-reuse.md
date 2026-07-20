# Capture once, parse many

Extraction falls back through several methods until an article's fields are
satisfied. Those fallbacks are **parsing** attempts — they are not a reason to
fetch the page again. One capture, many parsers.

## What it looked like before

Every parser in the chain already accepted HTML and skipped its own fetch when
given it (`_extract_with_mcmetadata`, `_extract_with_newspaper`,
`_extract_with_beautifulsoup`), but nothing handed a capture forward:

- The BeautifulSoup fallback was guarded on `html_for_methods` and then passed
  `html` — the untouched `extract_content` parameter, `None` for every
  production call — so it re-fetched even when the guard had just confirmed a
  capture existed.
- No method wrote its fetched HTML back, so nothing downstream could reuse it.

A single article commonly cost three HTTP fetches of the same URL, and on
Selenium-first (bot-protected) domains the HTTP parsers would re-fetch over the
network *after* the browser had already rendered the page — extra exposure on
exactly the hosts where that is most dangerous.

Measured against the real `extract_content` with the network stubbed:

| scenario | before | after |
| --- | --- | --- |
| HTTP chain, parsers falling back | 3 fetches | 1 fetch |
| chain ending in a Selenium fallback | 4 fetches | 2 fetches |

Selenium still fetches when it runs: rendering the page is the reason to call
it. The redundant HTTP re-fetches are what disappear.

## The rule

`ContentExtractor._capture_for_parsing()` decides what the next parser works
from:

1. **A Selenium capture wins.** It is the same page after JavaScript, which is
   strictly more of the article than an HTTP response.
2. **Otherwise reuse what's in hand** — a caller-supplied capture (e.g. a
   preemptive AMP fetch), else the most recent one fetched.
3. **Never reuse while bot protection is flagged.** The capture may be a
   challenge page rather than the article, and letting the next method fetch
   for itself is exactly the escape hatch that recovers from it.

## Why parsers may disagree without this

Beyond the request cost, separate fetches mean parsers can be reading different
bytes for the same article — a page that changed between requests, or one
served differently to a different client. Comparing extractor output under
those conditions measures the fetches as much as the parsers, which is the same
trap `scripts/extraction_quality_report.py` warns about for re-fetch
comparisons.

## Turning it off

`EXTRACTION_REUSE_CAPTURE=false` restores per-method fetching without a
rebuild. It exists because this changes behavior on the core extraction path;
if a publisher turns out to need a fresh fetch per parser, the switch buys time
to investigate.

## Verifying it holds

With the raw HTML archive (`docs/raw-html-archive.md`), capture-once is
observable rather than assumed: an extraction that fetched once produces one
capture, so the archived object is the article's input by construction rather
than by selection.
