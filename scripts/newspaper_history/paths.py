"""Where the newspaper-history pipeline reads and writes.

IN holds the inputs a person curates (the parsed SHSMO catalogue, Library of
Congress links, founding dates, datadesk merger events). OUT is the build: the
lineages and the feeds for the river, the county family trees and the event
map. GEO is datadesk's Census geometry, the same files the map draws, so a
county or town the feed names is one the page can find.
"""

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
IN = REPO / "src" / "lookups" / "newspaper_history"
OUT = Path(
    os.environ.get("NEWSPAPER_HISTORY_OUT", REPO / "build" / "newspaper_history")
)
REGISTRY = REPO / "src" / "lookups" / "mo_outlet_registry.csv"
GEO = (
    Path(os.environ.get("DATADESK_DIR", REPO.parent.parent / "datadesk"))
    / "static"
    / "geo"
)

OUT.mkdir(parents=True, exist_ok=True)
