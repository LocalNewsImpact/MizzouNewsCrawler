Site Diagnostics Report - 2026-02-05 14:29:47 UTC

[newstribune.com]
- Discovered: 281 | Verified: 280 | Extracted: 0 | Wire-suppressed: 0
- Candidate status top: article:280, not_article:1
- Final status top: article:280, not_article:1
- Article HTTP: status=200 len=143323ms=933
- Article WAF hints: cloudflare, blocked, bot
- Extraction paragraphs: 23
- WAF hints: bot, cloudflare
- HTTP sample codes: 200, 200, 200, 200, 404, 404, 404
- Recent URLs: https://www.newstribune.com/news/2026/feb/04/lolich-hero-of-1968-world-series-for-tigers-dies-at-85, https://www.newstribune.com/news/2026/feb/04/curling-opens-competition-at-winter-olympics, https://www.newstribune.com/news/2026/feb/04/vonn-doing-jumps-in-rehab-with-torn-acl
- Possible causes: Verified articles but extraction failed; WAF/anti-bot detected: bot, cloudflare; robots.txt blocks all; No obvious feed endpoints detected
- Suggested fixes: Run extraction diagnostics from extraction pod; adjust bot protection handling; tune rate limits; Use extraction pod for site-access tests; adjust headers/proxies; consider TLS fingerprint alignment; Respect robots; if misconfigured, contact site or adjust discovery to permitted paths; Add sitemap-based discovery or scrape section pages with article detectors

[republicmonitor.com]
- Discovered: 33 | Verified: 0 | Extracted: 6 | Wire-suppressed: 5
- Candidate status top: paused:27, wire:5, extracted:1
- Article status top: wire:5, labeled:1
- Final status top: paused:27, wire:5, labeled:1
- HTTP sample codes: 200, 200, 200, 404, 404, 403, 404
- Recent URLs: https://republicmonitor.com/stories/roziers-food-centre-feb-4-feb-10-sale-ad,169737, https://republicmonitor.com/stories/missouri-public-schools-want-protections-in-open-enrollment-legislation,169741, https://republicmonitor.com/stories/missouri-senate-changes-its-rules-to-make-it-harder-to-cut-off-debate,169740
- Possible causes: Discovery present but verification found no articles; URLs suppressed by wire filters; robots.txt blocks all; No obvious feed endpoints detected
- Suggested fixes: Tune StorySniffer and verification patterns; add allowlist for article paths; Review wire URL patterns and exclude local-only paths; Respect robots; if misconfigured, contact site or adjust discovery to permitted paths; Add sitemap-based discovery or scrape section pages with article detectors

[kq2.com]
- Discovered: 26 | Verified: 0 | Extracted: 26 | Wire-suppressed: 14
- Candidate status top: wire:17, extracted:8, obituary:1
- Article status top: wire:14, labeled:11, obituary:1
- Final status top: wire:14, labeled:11, obituary:1
- WAF hints: bot
- HTTP sample codes: 200, 200, 200, 200, 404, 404, 404
- Recent URLs: https://kq2.com/news/savannah-mom-looking-to-help-students-in-need/article_1dfae12b-2730-4793-a51e-d5335a4e59b4.html, https://kq2.com/news/st-joseph-broadcaster-retires-after-45-year-career/article_c368af3e-e1c6-5d71-a38d-2f5913025a57.html, https://kq2.com/news/one-dead-in-single-vehicle-crash-in-atchison-county/article_5b6745de-eb42-51ca-9c23-79f458ba0f45.html
- Possible causes: Discovery present but verification found no articles; URLs suppressed by wire filters; WAF/anti-bot detected: bot; robots.txt blocks all; No obvious feed endpoints detected
- Suggested fixes: Tune StorySniffer and verification patterns; add allowlist for article paths; Review wire URL patterns and exclude local-only paths; Use extraction pod for site-access tests; adjust headers/proxies; consider TLS fingerprint alignment; Respect robots; if misconfigured, contact site or adjust discovery to permitted paths; Add sitemap-based discovery or scrape section pages with article detectors

[jamesporttricountyweekly.com]
- Discovered: 15 | Verified: 0 | Extracted: 0 | Wire-suppressed: 0
- Candidate status top: not_article:15
- Final status top: not_article:15
- WAF hints: bot
- HTTP sample codes: 200, 200, 200, 200, 404, 404, 404
- Recent URLs: https://www.jamesporttricountyweekly.com/articles/12374, https://www.jamesporttricountyweekly.com/articles/12375, https://www.jamesporttricountyweekly.com/articles/12376
- Possible causes: Discovery present but verification found no articles; WAF/anti-bot detected: bot; robots.txt blocks all
- Suggested fixes: Tune StorySniffer and verification patterns; add allowlist for article paths; Use extraction pod for site-access tests; adjust headers/proxies; consider TLS fingerprint alignment; Respect robots; if misconfigured, contact site or adjust discovery to permitted paths

[comobuz.com]
- Discovered: 14 | Verified: 0 | Extracted: 9 | Wire-suppressed: 4
- Candidate status top: extracted:9, wire:4, not_article:1
- Article status top: labeled:9
- Final status top: labeled:9, wire:4, not_article:1
- WAF hints: bot
- HTTP sample codes: 200, 200, 200, 200, 404, 404, 404
- Recent URLs: https://comobuz.com/lifestyles/entertainment/are-these-the-6-most-iconic-super-bowl-halftime-shows/article_4c5753ef-1a8e-52d6-8d17-6cc6e8bb8fef.html, https://comobuz.com/news/national/millennials-want-homes-but-won-t-give-up-coffee-concerts-or-travel-to-get-one/article_91c2e364-75df-5368-bb17-0463f1142342.html, https://comobuz.com/news/national/february-mortgage-outlook-at-least-mortgage-rates-are-calm/article_b5e2f7a0-01be-513a-95fe-e8540c9c37c0.html
- Possible causes: Discovery present but verification found no articles; URLs suppressed by wire filters; WAF/anti-bot detected: bot; robots.txt blocks all; No obvious feed endpoints detected
- Suggested fixes: Tune StorySniffer and verification patterns; add allowlist for article paths; Review wire URL patterns and exclude local-only paths; Use extraction pod for site-access tests; adjust headers/proxies; consider TLS fingerprint alignment; Respect robots; if misconfigured, contact site or adjust discovery to permitted paths; Add sitemap-based discovery or scrape section pages with article detectors

[lamardemocrat.com]
- Discovered: 15 | Verified: 0 | Extracted: 0 | Wire-suppressed: 0
- Candidate status top: not_article:14, extracted:1
- Final status top: not_article:14, extracted:1
- WAF hints: bot
- HTTP sample codes: 200, 200, 200, 200, 404, 404, 404
- Recent URLs: https://www.lamardemocrat.com/articles/24801, https://www.lamardemocrat.com/articles/24802, https://www.lamardemocrat.com/articles/24803
- Possible causes: Discovery present but verification found no articles; WAF/anti-bot detected: bot; robots.txt blocks all
- Suggested fixes: Tune StorySniffer and verification patterns; add allowlist for article paths; Use extraction pod for site-access tests; adjust headers/proxies; consider TLS fingerprint alignment; Respect robots; if misconfigured, contact site or adjust discovery to permitted paths

[griffonnews.com]
- Discovered: 69 | Verified: 0 | Extracted: 28 | Wire-suppressed: 29
- Candidate status top: wire:57, not_article:8, opinion:4
- Article status top: labeled:28
- Final status top: wire:29, labeled:28, not_article:8, opinion:4
- WAF hints: bot
- HTTP sample codes: 200, 200, 200, 200, 404, 404, 404
- Recent URLs: https://www.griffonnews.com/news/nation/state-prosecutor-sturla-henriksboe-spoke-at-the-opening-of-the-trial/image_6c9923a3-2a29-5f45-b2ec-3974cbf116c9.html, https://www.griffonnews.com/news/nation/marius-borg-hoiby-faces-38-charges-including-four-of-rape/image_2d63efd6-b743-5bfe-bd2f-3aff5bf16c9d.html, https://www.griffonnews.com/news/nation/experts-say-it-is-crucial-for-more-older-people-to-stay-in-work-longer-in/image_5b06ff89-c0a3-52b1-8a00-1274ed870240.html
- Possible causes: Discovery present but verification found no articles; URLs suppressed by wire filters; WAF/anti-bot detected: bot; robots.txt blocks all; No obvious feed endpoints detected
- Suggested fixes: Tune StorySniffer and verification patterns; add allowlist for article paths; Review wire URL patterns and exclude local-only paths; Use extraction pod for site-access tests; adjust headers/proxies; consider TLS fingerprint alignment; Respect robots; if misconfigured, contact site or adjust discovery to permitted paths; Add sitemap-based discovery or scrape section pages with article detectors

[greenfieldvedette.com]
- Discovered: 15 | Verified: 0 | Extracted: 0 | Wire-suppressed: 0
- Candidate status top: not_article:14, extracted:1
- Final status top: not_article:14, extracted:1
- WAF hints: bot
- HTTP sample codes: 200, 200, 200, 200, 404, 404, 404
- Recent URLs: https://www.greenfieldvedette.com/articles/6079, https://www.greenfieldvedette.com/articles/6080, https://www.greenfieldvedette.com/articles/6081
- Possible causes: Discovery present but verification found no articles; WAF/anti-bot detected: bot; robots.txt blocks all
- Suggested fixes: Tune StorySniffer and verification patterns; add allowlist for article paths; Use extraction pod for site-access tests; adjust headers/proxies; consider TLS fingerprint alignment; Respect robots; if misconfigured, contact site or adjust discovery to permitted paths

[missouribusinessalert.com]
- Discovered: 11 | Verified: 0 | Extracted: 11 | Wire-suppressed: 7
- Candidate status top: wire:9, extracted:2
- Article status top: wire:7, labeled:4
- Final status top: wire:7, labeled:4
- WAF hints: bot
- HTTP sample codes: 200, 200, 200, 200, 404, 404, 404
- Recent URLs: https://missouribusinessalert.com/government/democrats-question-250k-budget-earmark-for-former-missouri-governor-s-foundation/article_7f46009e-3537-4016-9337-6ed00db35358.html, https://missouribusinessalert.com/series/missouri-minute-cannabis-companies-sue-smoke-shops-cardinals-royals-ink-mlb-broadcast-deal/article_ca129ffe-fe7a-4479-b267-95ac6bba367c.html, https://missouribusinessalert.com/news/new-tax-policy-may-impact-taxpayers-what-to-know-before-filing-your-taxes/article_31d298a4-2714-5990-9588-959fdb368e48.html
- Possible causes: Discovery present but verification found no articles; URLs suppressed by wire filters; WAF/anti-bot detected: bot; robots.txt blocks all; No obvious feed endpoints detected
- Suggested fixes: Tune StorySniffer and verification patterns; add allowlist for article paths; Review wire URL patterns and exclude local-only paths; Use extraction pod for site-access tests; adjust headers/proxies; consider TLS fingerprint alignment; Respect robots; if misconfigured, contact site or adjust discovery to permitted paths; Add sitemap-based discovery or scrape section pages with article detectors
