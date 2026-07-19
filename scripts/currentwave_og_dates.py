"""
Fetch each currentwave.news URL, extract og:image:url, parse the Screenshot
timestamp embedded in the filename, and export to CSV.
"""

import csv
import re
import urllib.request
import os

URLS = [
    "https://currentwave.news/articles/2191/view/troop-g-s-fifth-traffic-fatality-of-2026",
    "https://currentwave.news/articles/2182/view/winona-4th-and-5th-grade-basketball-season-begins",
    "https://currentwave.news/articles/2170/view/mdc-hosts-several-hunter-education-skills-sessions-in-the-ozarks-in-march",
    "https://currentwave.news/articles/2179/view/from-accident-to-homicide-trio-charged-in-2018-drowning-of-robbie-crites",
    "https://currentwave.news/articles/2199/view/mdc-reminds-people-to-be-bearwise-about-black-bears-as-black-bears-search-for-food-in-spring-intentionally-feeding-them-puts-people-and-property-at-risk-and-can-lead-to-the-bear-s-death",
    "https://currentwave.news/articles/2183/view/a-note-from-the-shannon-county-sheriff",
    "https://currentwave.news/articles/2180/view/new-lawsuit-in-shannon-county-claims-royal-oak-plant-caused-environmental-contamination",
    "https://currentwave.news/articles/2169/view/snakehead-fish-spotlighted-during-national-invasive-species-awareness-week",
    "https://currentwave.news/articles/2192/view/shannondale-community-clothing-sale",
    "https://currentwave.news/articles/2190/view/missouri-house-honors-legacy-of-community-pillar-michelle-martin",
    "https://currentwave.news/articles/2197/view/summersville-man-charged-after-elk-poaching-investigation-at-peck-ranch",
    "https://currentwave.news/articles/2203/view/blast-from-the-past",
    "https://currentwave.news/articles/2181/view/modot-opens-final-comment-period-for-longrange-plans",
]

OUTPUT = os.path.join(os.path.dirname(__file__), "currentwave_og_dates.csv")

# Matches Screenshot YYYY-MM-DD (URL-encoded space = %20 or literal space)
DATE_RE = re.compile(r'Screenshot[%20 ]+(\d{4}-\d{2}-\d{2})', re.IGNORECASE)
OG_IMG_RE = re.compile(r'<meta\s+property="og:image:url"\s+content="([^"]+)"', re.IGNORECASE)

results = []

for url in URLS:
    slug = url.split("/view/")[-1]
    article_id = url.split("/articles/")[1].split("/")[0]
    row = {"article_id": article_id, "slug": slug, "url": url,
           "og_image_url": "", "extracted_date": "", "note": ""}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        m = OG_IMG_RE.search(html)
        if m:
            og_url = m.group(1)
            row["og_image_url"] = og_url
            dm = DATE_RE.search(og_url)
            if dm:
                row["extracted_date"] = dm.group(1)
            else:
                row["note"] = "no Screenshot date in og:image:url"
        else:
            row["note"] = "no og:image:url found"
    except Exception as e:
        row["note"] = f"fetch error: {e}"

    print(f"  [{article_id}] {row['extracted_date'] or row['note']}")
    results.append(row)

with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["article_id", "slug", "extracted_date", "og_image_url", "note", "url"])
    writer.writeheader()
    writer.writerows(results)

print(f"\nSaved: {OUTPUT}")
