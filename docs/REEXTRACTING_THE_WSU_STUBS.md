# Re-extracting the WSU short bodies

46 of the 478 articles in `WSU-Washington-State` hold something other than a
story. They divide into three populations with different remedies, and only one
of the three is a paywall.

## What the 46 are

| # | population | n | host(s) | credential |
|---|---|---|---|---|
| A | paywall teaser, explicit notice | 19 | ptleader.com | **wired** (`simplecirc`) |
| B | no body at all, TownNews/BLOX | 7 | chinookobserver 6, wenatcheeworld 1 | secret exists, **not wired** |
| C | page furniture captured instead of the story | 6 | tdn 2, rangemedia 2, mymltnews 1, wenatcheeworld 1 | tdn wired; rest need none |
| D | broadcast video page, no prose exists | 10 | khq.com | n/a |
| E | radio piece, web summary is the whole text | 2 | knkx.org | n/a |
| F | photo cutline from an e-edition | 2 | pendoreillerivervalley.com | wired (`etype`) |

**A** is unambiguous. 19 of 20 ptleader bodies end on the literal string
`item is available in full to subscribers.`, at 202–242 characters — lede plus
notice. The subscription is already wired, which makes this the largest
recoverable group and the cheapest.

**B** never got a body: the notebook wrote `nan`. Both hosts are TownNews/BLOX,
the same platform as `tdn.com`, whose `auth_config` (login_url plus four
selectors and a `success_text`) is a working template for theirs.

**C** is not a paywall at all, which matters because the remedy is different.
What was captured: RANGE's membership appeal ("RANGE is a reader-supported
publication…"), a `tdn.com` US-state dropdown, a `tdn.com` country dropdown, a
wenatcheeworld email-notification widget with its `{{subject}}` template
variable unrendered, and a `mymltnews.com` teaser truncated on an ellipsis. All
six pages are freely readable. The notebook's extractor took the wrong block.
Our stack has semantic boilerplate detection and a candidate cascade it did not,
so these are the highest-confidence recoveries in the set and need no
credential.

**D** is 10 `/video_` pages on khq.com, uniformly. Five held `nan`; five held a
one-sentence blurb restating the headline. There is no article to recover — the
story is the video. The blurbs should not have been enriched: the 85-character
one is the sole source of the Quincy→Illinois point, because "Quincy" with no
state and no other geography has no in-story evidence to disambiguate it, and
Quincy, Washington (GEOID 5357115, Columbia Basin canal country) is what the
story is actually about.

**E** and **F** are marginal. knkx's two rows are real prose that ends "Click
'Listen' above to hear this story" — the web summary is all the web page has.
pendoreillerivervalley is an eType e-edition, where the prose lives in a page
image, so a cutline may be all the HTML holds.

## The rework queue cannot do the fetch

`src/pipeline/rework.py` selects a link to fetch with:

    AND cl.status = 'article'
    AND NOT EXISTS (SELECT 1 FROM articles a WHERE a.candidate_link_id = cl.id)

Every one of the 46 has an article, so enqueuing their links selects nothing.
This is not a gap to configure around. `link_status_repair.py` states the
invariant directly: "Both extraction selectors require `status = 'article'` AND
no article row, so a link with an article is never re-extracted whatever it
says." Re-fetching a URL whose article exists is something the pipeline
deliberately cannot do.

Deleting the articles to make the links fetchable is the wrong trade for group
A: those 19 carry the notebook's CIN labels, which are the study's original
measurement, plus the verbatim `inputtext` the drift comparison depends on. It
is defensible only for group D, whose labels are `Civic Life` artifacts the
model returned when handed `nan`.

## The process that does work

Split the fetch from the carry. The queue handles everything after the body.

1. **Fetch and patch the body.** No supported path exists; this is the piece
   that has to be built or done out of band. It updates `articles.text` and
   `articles.content` on the existing row, leaving `id`, `candidate_link_id`,
   `metadata.wsu_notebook` and the `wsu-notebook-2026-02` label row untouched.
2. **Set `articles.status = 'cleaned'`.** That is what the classify stage reads
   (`SELECTS['classify'] = ('article', ('cleaned', 'local'))`).
3. **Enqueue `pipeline_rework(record_type='article', stage='classify')`.**
   `articles_in` has no has-an-article exclusion, so articles enqueue cleanly
   where links do not.
4. **Submit the existing entry point**, which needs nothing supplied by hand:

       argo submit -n production --from cronworkflow/news-housekeeping

   `FOLLOWS` carries classify → enrich, so one submit re-labels on the new text
   and then re-runs geography. Budget two runs: settlement happens at the start
   of a step, so rows closed by a run's own work show closed on the next.

This is the design working as documented — "put a record in the right status and
the pipeline carries it" — for every stage except the fetch.

## Expected yield

| group | n | likelihood | blocked on |
|---|---|---|---|
| C furniture | 6 | **high** | the fetch path only |
| A ptleader | 19 | **high** | the fetch path; simplecirc login verified live |
| B BLOX | 7 | medium-high | `auth_config` built from tdn's, verified live |
| F eType | 2 | low | prose may not be in the HTML |
| E knkx | 2 | none to gain | summary is the whole web text |
| D khq video | 10 | none | no prose exists |

**32 of 46 are worth attempting**, and 25 of those 32 sit behind credentials we
already hold. The 10 khq video pages should instead be retracted to
`not_article` for consistency — five already are — which also withdraws the
Quincy→Illinois point and the three Moses Lake points taken from one-sentence
blurbs.

Two cautions carried from earlier work. Authenticated extraction is paused
overall, so nothing in A, B or F runs until that is lifted. And a login config
cannot be validated by fake-driver tests: publishers commonly present two login
forms and the obvious one is wrong, so B's `auth_config` has to be checked
against the live site before its seven articles can be counted on.
