Decide whether a news story is PRESENT in the sampled text below.

Return ONLY JSON: {"verdict": "news" | "paywall" | "not_news", "reason": "<15 words max>"}

Scraped article text often carries cookie banners, menus or subscribe prompts
around the story. That residue does NOT change the verdict. Judge only whether
actual story content exists in either sample:

- "news": story content is present in START or MIDDLE, even if surrounded by
  site furniture (any topic, including sports and features)
- "paywall": no story content — only a teaser cut off by a subscribe/sign-in wall
- "not_news": no story content — only cookie/consent boilerplate, navigation,
  vendor lists, or an error page

TEXT (two samples from one document):
{text}
