Site Diagnostics Report - 2026-02-07 02:28:19 UTC

[newstribune.com]
- Discovered: 274 | Verified: 273 | Extracted: 0 | Wire-suppressed: 0
- Candidate status top: article:273, not_article:1
- Final status top: article:273, not_article:1
- Article HTTP: status=200 len=146517ms=387
- Article WAF hints: cloudflare, blocked, bot
- Extraction paragraphs: 39
- WAF hints: bot, cloudflare
- HTTP sample codes: 200, 200, 200, 200, 404, 404, 404
- Recent URLs: https://www.newstribune.com/news/2026/feb/06/musk-vows-to-put-data-centers-in-space-run-them, https://www.newstribune.com/news/2026/feb/06/lamonte-mclemore-founding-member-of-the-5th, https://www.newstribune.com/news/2026/feb/06/sheriff-holding-out-hope-that-guthries-missing
- Possible causes: Verified articles but extraction failed; WAF/anti-bot detected: bot, cloudflare; robots.txt reports block-all (informational); No obvious feed endpoints detected
- Suggested fixes: Run extraction diagnostics from extraction pod; adjust bot protection handling; tune rate limits; Use extraction pod for site-access tests; adjust headers/proxies; consider TLS fingerprint alignment; Use sitemap-based discovery or section pages + article detectors (robots-agnostic)
