# The Blue Book lists the newspapers

The Missouri secretary of state's *Official Manual* ("Blue Book") 2025–2026
carries a directory of the state's newspapers, compiled with the Missouri Press
Association. It names, for almost every paper, a publisher and an editor — which
no other source we hold does.

Source: `9_Information.pdf`, printed pages 837–851 (PDF pages 7–21).
<https://www.sos.mo.gov/cmsimages/bluebook/2025-2026/9_Information.pdf>

**Nothing here has been written to the production database.** These files are
reference data for a decision that has not been taken.

## What is in the repository

| File | What it holds |
| --- | --- |
| `src/lookups/mo_bluebook_newspapers_2025_2026.json` | 199 newspapers, full structure including every named role |
| `src/lookups/mo_bluebook_newspapers_2025_2026.csv` | the same, flattened to one row per paper |
| `tools/parse_mo_bluebook.py` | the extractor, so the listing can be re-read when the next edition is published |
| `src/lookups/mo_bluebook_missing_from_ours.csv` | 61 papers in the book that the Mizzou dataset does not carry |
| `src/lookups/mo_bluebook_missing_url_check.csv` | whether each of those 40 sites is live |
| `src/lookups/mo_bluebook_not_in_the_book.csv` | 84 of our sources the book does not list |
| `src/lookups/mo_bluebook_diff_name_mismatch.csv` | 58 papers we hold under a different name |
| `src/lookups/mo_bluebook_diff_url_mismatch.csv` | 8 papers we hold under a different host |
| `src/lookups/mo_bluebook_shared_ownership.csv` | 121 groups of papers sharing a person, site, phone or address |

## Reading the listing

Two columns a page, which `pdftotext -layout` interleaves into one line. Each
page is therefore cropped into halves and read separately. Three things bite:

- The **running header splits across the crop**, leaving `MISSOURI INFORMA` on
  one side and `ATION — NEWSPAPERS OF MISSOURI 837` on the other. Neither is a
  whole header any more, so both halves are filtered by name.
- A **name too long for the column runs on to a second line**
  (`CRANE CHRONICLE/STONE COUNTY` + `REPUBLICAN`), and an **address whose ZIP
  will not fit** drops the ZIP to an indented line of its own. Left alone that
  ZIP reads as a newspaper called `65066`.
- The crop column must be 218pt, not the half-width 216. At 216 a single
  character of the left column bleeds into the right on four pages, which turned
  `Belton` into a line starting `e` — not a city, so `NORTH CASS HERALD` was
  recorded in Belle.

## How it compares with the Mizzou dataset

Against the 213 sources in `Mizzou-Missouri-State`:

| | Count |
| --- | --- |
| Blue Book newspapers | 199 |
| …with a website printed | 176 |
| Matched to one of our sources by host | 130 |
| Matched by name but under a different host | 8 |
| In the book, not in our data | 61 |
| In our data, not in the book | 84 |

The 84 we hold and the book does not are not errors: the book lists newspapers,
and the dataset also carries broadcasters, digital natives and college papers.

### The 61 we do not carry

21 print no website at all. Of the 40 that do, checked from a laptop:

| Verdict | Count |
| --- | --- |
| Live, HTTP 200 | 29 |
| Live, redirects to another domain | 2 |
| Refuses this client (403) | 3 |
| HTTP error | 3 |
| Does not resolve | 2 |
| Connection refused | 1 |

Dead: `www.cc-scrnews.com` (Crane Chronicle) and `northmissouriannews.com`
(Princeton Post-Telegraph) have no DNS record.

`LAWSON REVIEW` prints `www.facebook.com` as its website, which is a finding
about the paper rather than a broken link.

The check says dead-or-alive, not crawlable. It ran from a laptop, so a site
that blocks datacentre ranges looks healthier here than it will to the crawler,
and the three 403s may be either.

## Shared ownership we do not record

This is what the book adds that nothing else we hold does. A shared **publisher**
is the strongest signal — it is the role that owns — and 19 of the 32 shared
publishers span papers we file under different owners, or under none.

| Publisher | Papers | What we record |
| --- | --- | --- |
| Scott Hoskins | 6 | five different owners: Better Newspapers, CherryRoad, Ellinghouse, Paxton, Ste. Genevieve Media |
| Mike Sue Scott | 5 | four: Feeney Chris, NEMOnews, Sentinel Printing, Wilson Robert |
| Tim Schmidt | 5 | four: CherryRoad, The Missourian Publishing Company, Tim Schmidt, Westplex Media |
| Dennis Warden | 3 | two: Voss Jerrilynn, Warden Publishing Group |
| James White | 3 | two: Benton County Enterprise, Clinton Daily Democrat |
| Karen Fioretti | 3 | two: Lancaster Management, Melton Publishing |
| Frank Mercer | 3 | none — no source of ours carries any of them |
| Ann Blunt | 2 | two: Carpenter Media, Phillips Media |
| Jamila Khalil | 2 | two: CherryRoad, Phillips Media |
| Mike Scott | 2 | two: Cheffey Mark & Patty, Williams Communications |

Two of those we record are people's names rather than companies — `Tim Schmidt`,
`Wilson Robert`, `Feeney Chris`, `Voss, Jerrilynn`, `Cheffey Mark & Patty`. The
owner column is carrying an individual where the book names them as the
publisher of several papers.

A **shared website** is the same finding from the other side: one domain serving
several mastheads.

| Domain | Papers | In our data |
| --- | --- | --- |
| `mainstreetnewsgroup.com` | 4 | 0 |
| `myleaderpaper.com` | 4 | 4, all as Leader Publications Inc. |
| `bentoncountyenterprise.com` | 3 | 3 |
| `mlmcounties.com` | 3 | 0 |
| `enterprisecourier.com`, `monroe-ralls.com`, `theodessan.net`, `lincolnnewsnow.com` | 2 each | 0 |

`mainstreetnewsgroup.com` is one operation publishing the Carrollton Democrat,
Glasgow Missourian, Higginsville Advance and Lexington News under Frank Mercer,
and we hold none of it. We do hold `lafayettemonews.com` as the Higginsville
Advance, which the book does not name — one of the 8 host mismatches.

## What has not been done

- Nothing is written to `sources`. No owner has been corrected from this, no
  source added, no URL changed.
- The 8 host mismatches are not resolved. Each needs a judgement about which
  host is current, and `BOONE COUNTY JOURNAL` (we hold it as a path under
  `columbiamissourian.com`, the book gives `www.bocojo.com`) is the awkward one.
- The 58 name differences are mostly ours carrying a fuller or older masthead
  (`Booneville Daily News` against the book's `BOONVILLE NEWS`). They are listed,
  not judged.
