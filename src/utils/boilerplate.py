"""What is furniture and what is an article.

One definition, shared by everything that needs to tell reporting apart from the
scaffolding around it: the content cleaner, which removes furniture, and
telemetry, which decides whether an extraction actually captured a story.

Two ideas, in order:

1. **Vocabulary.** Some text is furniture wherever it appears. A phrase that a
   human cleaner removed from articles on many different publishers is site
   plumbing, not one newsroom's prose. That list is derived, not guessed — see
   BOILERPLATE_MARKERS.
2. **Shape.** What survives is then judged on whether it reads like writing:
   function-word density, capitalisation, and how much of the vocabulary belongs
   to websites rather than to the world.

Neither alone is enough, and the failures of each are what motivate the other —
recorded at each threshold below so the next person can retune against fresh
data rather than taste.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

# DERIVED, NOT GUESSED. Produced by diffing 15,656 hand-cleaned articles against
# the same records as extracted (BigQuery mizzou_analytics.articles, joined on
# url), keeping only segments the cleaner removed on FOUR OR MORE distinct
# hosts. That host count is the test of whether a phrase is site furniture or
# one publisher's prose.
#
# An earlier hand-written list of plausible-sounding paywall phrases scored 2%
# recall against labelled data. These are what the corpus actually contains, and
# the counts are why they matter: "Please enable it in your browser settings"
# appeared 953 times, "Login to continue reading" 548 times across 16 hosts.
#
# Datelines ("KANSAS CITY, Mo.") and photo credits survive that diff too, but
# they are article content being MOVED to another field rather than discarded,
# so they are deliberately absent here.
#
# Phrase-level on purpose: bare words like "subscribe" appear inside real
# articles ("subscribers to the service said..."); whole prompts do not.
BOILERPLATE_MARKERS: tuple[str, ...] = (
    # paywall / registration walls
    "javascript is required for you to be able to read premium content",
    "please enable it in your browser settings",
    "login to continue reading",
    "sign up for complimentary access",
    "please log in to continue",
    "need an account?",
    "this item is available in full to subscribers",
    "non-subscribers",
    "click here to see your options for becoming a subscriber",
    "otherwise, click here to view your options for subscribing",
    "print and web subscribers",
    "subscribe now!",
    # consent / advertising furniture
    "we use cookies to help our site function properly",
    "featured local savings",
    # comment-policy block (ships as many short lines, hence the fragments)
    "please avoid obscene, vulgar, lewd",
    "racist or sexually-oriented language",
    "threats of harming another",
    "person will not be tolerated",
    "don't knowingly lie about anyone",
    "no racism, sexism or any sort of -ism",
    "that is degrading to another person",
    "use the 'report' link on",
    "each comment to let us know of abusive posts",
    "we'd love to hear eyewitness",
    "accounts, the history behind an article",
    # recirculation
    "previous post",
    "next post",
    # site navigation chrome. Mined separately from the cleaned/raw diff, which
    # could not see these: nav text survived on BOTH sides of that comparison,
    # so it never appeared as something a cleaner had removed. Found instead by
    # cross-host repetition across the stored corpus, where "skip to main
    # content" occurs on 46 distinct publishers and 985 articles — no newsroom
    # writes that. 2,879 of 94,459 stored articles (3.0%) carry one of these.
    "skip to main content",
    "toggle navigation",
    "main menu",
    "advanced search",
    "e-edition",
    "photo galleries",
)

# Words belonging to the plumbing of a website rather than to a story. Unlike
# the phrases above these are single words, so they are counted as a RATE rather
# than matched: an article may mention a subscriber once, while a registration
# form says "account", "password" and "e-mail" every other line.
UTILITY_WORDS = re.compile(
    r"\b(subscribe|subscriber|account|password|login|log in|sign up|e-?mail|"
    r"cookies|advertisement|newsletter|click here|browser)\b",
    re.IGNORECASE,
)

# Function words. Their density is what separates written English from a
# scraped control.
FUNCTION_WORDS = frozenset(
    "the a an and or but of to in on for with is are was were said he she it "
    "that this from at by as has have had not".split()
)

_SEGMENT_SPLIT = re.compile(r"[\n\r]+|(?<=[.!?])\s+")

# --------------------------------------------------------------------------
# Thresholds, with the measurements that chose them
# --------------------------------------------------------------------------

# Function-word density below which text is a list, a form or a menu.
# Measured on 1,036 labelled production extractions: median 0.137 for bodies
# flagged as boilerplate/paywall against 0.286 for the rest.
#     < 0.12 -> 38% of flagged bodies caught,  2.5% collateral
#     < 0.16 -> 64% caught,                    4.9% collateral
# The known false positive is agate — sports scores, election returns, real
# estate transfers — legitimate local copy carrying almost no function words.
MIN_PROSE_DENSITY = 0.14

# Capitalisation above which text is a run of proper nouns rather than prose.
# Density alone is fooled by the corpus's most common non-article: a country
# dropdown scraped from a registration form (5,308 chars, byte-identical across
# four hosts) scores 0.21 on density because "United States of America" is full
# of function words. Median capitalisation was 0.664 for flagged bodies against
# 0.217 for the rest — a cleaner 3x separation than density's 2x.
MAX_CAPITALIZATION = 0.60

# Utility words per 100 words, above which the text is site plumbing.
# The sharpest of the three: median 4.13 for flagged bodies against 0.00 for the
# rest — most real articles contain none of these words at all. Adding it took
# recall from 39% to 85%.
MAX_UTILITY_WORD_RATE = 3.0


# --------------------------------------------------------------------------
# Measures
# --------------------------------------------------------------------------


def segments(text: str) -> list[str]:
    """Split into lines and sentences — the unit boilerplate travels in."""
    if not text:
        return []
    return [s.strip() for s in _SEGMENT_SPLIT.split(text) if s and s.strip()]


def is_boilerplate_segment(segment: str) -> bool:
    """Whether a single line or sentence is known furniture."""
    lowered = segment.lower()
    return any(marker in lowered for marker in BOILERPLATE_MARKERS)


# A navigation menu is not one segment, it is a RUN of them. Extractors emit
# nav bars one item per line — "Home", "Categories", "Classifieds", "Columns" —
# so every item is a 1-word segment and no per-segment rule reaches it. What
# gives a menu away is the run: many consecutive short, capitalised fragments
# with no sentence punctuation between them.
#
# Calibrated against 23 hand-marked articles: at these settings the rule removes
# 32.7% of a marked article's text against 1.4% of an unmarked one — a 23:1
# ratio. Looser settings (shorter runs, longer fragments) gain little and cost
# collateral; see the sweep in the commit message.
MENU_ITEM_MAX_WORDS = 4
MENU_RUN_MIN_ITEMS = 6
# A menu label is mostly capitalised and carries almost no function words.
_MENU_MIN_CAPS = 0.6
_MENU_MAX_FUNCTION = 0.34


def _is_menu_item(segment: str) -> bool:
    """Whether a segment looks like one entry in a navigation menu."""
    words = segment.split()
    if not (1 <= len(words) <= MENU_ITEM_MAX_WORDS):
        return False
    if segment.rstrip().endswith((".", "!", "?")):
        return False  # a sentence, however short
    letters = re.findall(r"[A-Za-z][A-Za-z']*", segment)
    if not letters:
        return False
    caps = sum(1 for w in letters if w[0].isupper()) / len(letters)
    if caps < _MENU_MIN_CAPS:
        return False
    fn = sum(1 for w in letters if w.lower() in FUNCTION_WORDS) / len(letters)
    return fn <= _MENU_MAX_FUNCTION


def _drop_menu_runs(segs: list[str]) -> list[str]:
    """Drop runs of consecutive menu items from an already-split segment list.

    Deliberately requires a RUN. A single capitalised fragment is far too weak a
    signal on its own — "Mayor John Smith" would qualify — but six of them in a
    row with no sentence between is a nav bar, not writing.

    Takes and returns a LIST rather than text on purpose. Re-joining to a string
    between passes destroys the line boundaries that segmentation produced, and
    a later phrase match then applies to a segment that has swallowed the whole
    article — which deleted entire stories before a test caught it.
    """
    flags = [_is_menu_item(s) for s in segs]
    kept: list[str] = []
    i = 0
    while i < len(segs):
        if flags[i]:
            j = i
            while j < len(segs) and flags[j]:
                j += 1
            if j - i < MENU_RUN_MIN_ITEMS:
                kept.extend(segs[i:j])  # too short to be a menu; keep it
            i = j
        else:
            kept.append(segs[i])
            i += 1
    return kept


def strip_menu_runs(body: str) -> str:
    """Text-in, text-out wrapper over _drop_menu_runs, for callers and tests."""
    if not body:
        return ""
    return " ".join(_drop_menu_runs(segments(body))).strip()


def strip_boilerplate(body: str) -> str:
    """Remove the segments of a body that are walls or furniture.

    Segment-level rather than whole-body, so a single "subscribe today" line at
    the foot of a real story removes that line and keeps the story. A whole-body
    keyword test cannot do this — it would discard the article too.
    """
    if not body:
        return ""
    # Both passes share ONE segment list. Menus go first — they are structural
    # and would otherwise survive, because each item is a one-word segment that
    # no phrase or shape test reaches alone — but the list is never re-joined
    # between passes, or the phrase pass would match against a segment that had
    # swallowed the article.
    segs = _drop_menu_runs(segments(body))
    kept = [s for s in segs if not is_boilerplate_segment(s)]
    return " ".join(kept).strip()


def prose_density(text: str) -> float:
    """Share of words that are function words — how much this reads as writing."""
    words = re.findall(r"[a-zA-Z']+", text.lower())
    if not words:
        return 0.0
    return sum(1 for w in words if w in FUNCTION_WORDS) / len(words)


def capitalization_ratio(text: str) -> float:
    """Share of words beginning with a capital.

    Reporting is mostly lowercase; a scraped list of proper nouns — countries,
    place names, section menus — is mostly not.
    """
    words = re.findall(r"[A-Za-z][A-Za-z']*", text)
    if not words:
        return 0.0
    return sum(1 for w in words if w[0].isupper()) / len(words)


def utility_word_rate(text: str) -> float:
    """Website-plumbing words per 100 words.

    Shape misses text that reads like writing but is about the site rather than
    the world — registration prompts, newsletter pitches, cookie notices.
    """
    words = re.findall(r"[a-zA-Z']+", text)
    if not words:
        return 0.0
    return 100 * len(UTILITY_WORDS.findall(text)) / len(words)


def looks_like_article(body: str | None) -> bool:
    """Whether a body is a story rather than a wall, a form or a menu.

    Content-first: a paywall prompt fails however many characters it runs to,
    because what is measured is the writing that survives the strip, not the
    byte count of whatever the page returned.

    There is deliberately no word-count floor. One was measured and was actively
    harmful: a >=60-word floor caught 2% of flagged bodies while failing 13.7%
    of good ones, because local news genuinely runs short.
    """
    if not body or not body.strip():
        return False
    stripped = strip_boilerplate(body)
    if prose_density(stripped) < MIN_PROSE_DENSITY:
        return False  # a list or a menu, not writing
    if capitalization_ratio(stripped) > MAX_CAPITALIZATION:
        return False  # a run of proper nouns: a dropdown, a section index
    return utility_word_rate(stripped) <= MAX_UTILITY_WORD_RATE


def looks_like_furniture(text: str) -> bool:
    """Whether a candidate block is furniture — the inverse question.

    Used by the content cleaner to decide whether a block it is considering for
    removal really is scaffolding. Deliberately NOT `not looks_like_article(...)`:
    that would call anything short furniture, and a two-sentence paragraph in the
    middle of a story is not. This asks for positive evidence of scaffolding.
    """
    if not text or not text.strip():
        return False
    if is_boilerplate_segment(text):
        return True
    if utility_word_rate(text) > MAX_UTILITY_WORD_RATE:
        return True
    return capitalization_ratio(text) > MAX_CAPITALIZATION


# Paywall/registration prompts specifically, as opposed to the consent banners
# and comment-policy blocks that BOILERPLATE_MARKERS also covers. Same
# derivation discipline: phrase-level, because bare words like "subscribe"
# occur inside real reporting ("subscribers to the service said...") while
# whole prompts do not.
#
# Split out from BOILERPLATE_MARKERS because the two answer different
# questions. That list asks "should this segment be stripped?"; this one asks
# "is the page a wall instead of a story?" -- which decides whether a browser
# would help (it would not; the wall is served to browsers too) and whether the
# record should be filed as paywalled rather than retried.
# Moved here verbatim from content_cleaner_balanced.py so the cleaner and the
# capture gate read ONE list instead of drifting apart. The cleaner strips
# these; note it deliberately includes newsletter asks ("subscribe to our
# newsletter"), which are furniture but NOT walls -- a newsletter prompt sits
# beside a readable story.
SUBSCRIPTION_MARKERS: tuple[str, ...] = (
    "subscribe to our newsletter",
    "sign up for updates",
    "get daily updates",
    "subscribe now",
    "join our mailing list",
    "email updates",
    "available in full to subscribers",
    "this item is available in full to subscribers",
    "to continue reading please log in or subscribe",
    "to continue reading please login or subscribe",
    "please log in to continue reading",
    "please login to continue reading",
    "need an account print subscribers",
)

# The wall-specific subset, plus prompts observed in production that the
# stripping list does not carry (greenfieldvedette.com serves "This content is
# for subscribers only"). Newsletter asks are excluded on purpose: they are
# furniture on a readable page, not a wall in place of one.
PAYWALL_MARKERS: tuple[str, ...] = tuple(
    dict.fromkeys(
        (
            "available in full to subscribers",
            "this item is available in full to subscribers",
            "to continue reading please log in or subscribe",
            "to continue reading please login or subscribe",
            "please log in to continue reading",
            "please login to continue reading",
            "need an account print subscribers",
            # observed in production, absent from the stripping list
            "this content is for subscribers only",
            "login to continue reading",
            "please log in to continue",
            "sign up for complimentary access",
            "click here to see your options for becoming a subscriber",
            "otherwise, click here to view your options for subscribing",
            "click here to start your free trial",
            "subscribe to continue reading",
            "to continue reading, please subscribe",
            "start your free trial",
            "for subscribers only",
        )
    )
)


def looks_like_paywall(text: str | None) -> str | None:
    """The paywall prompt a body contains, or None.

    Returns the matched phrase rather than a bool so callers can record WHICH
    prompt fired -- the same reasoning as capture-quality telemetry: a verdict
    you cannot audit is a verdict you cannot tune.

    Matches on the raw body, NOT the stripped one: strip_boilerplate removes
    these very phrases, so checking after the strip would find nothing.
    """
    if not text:
        return None
    lowered = text.lower()
    for marker in PAYWALL_MARKERS:
        if marker in lowered:
            return marker
    return None
