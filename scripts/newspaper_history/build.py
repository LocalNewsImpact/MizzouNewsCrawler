"""Build the river, county family-tree and event-map feeds in one run.

    python scripts/newspaper_history/build.py                # build + check
    python scripts/newspaper_history/build.py --publish      # ... then upload all three
    python scripts/newspaper_history/build.py --push-inputs  # upload edited inputs

The inputs are other people's data and a reviewer's notes, and this repository
is public: they live in a private bucket (INPUTS) and are fetched into
paths.IN, which git ignores, when they are missing.

Each step reads what the one before wrote (paths.OUT). The order is fixed:
exports.py rewrites the river and tree feeds as named tables, and the map is
built from those tables, so every feed comes from one set of papers and events.
check.py stops the run before anything is uploaded if any two disagree.

Publishing uploads the three feeds to the bucket the datadesk visuals read.
The visuals are then re-pinned together (README.md), so no page shows a
newer history than the others.
"""

import argparse
import runpy
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS = ["lineage.py", "tree.py", "river.py", "exports.py", "mapfeed.py", "check.py"]
BUCKET = "gs://mizzou-news-maps-data/visuals"
INPUTS = "gs://mizzou-news-maps-data/newspaper_history/inputs"
INPUT_FILES = [
    "shsmo_missouri_titles.csv",
    "loc_links.csv",
    "registry_founded.csv",
    "datadesk_merged_events.csv",
]
FEEDS = [
    "missouri_newspaper_river.json",
    "missouri_newspaper_family_trees.json",
    "missouri_newspaper_event_map.json",
]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--publish", action="store_true", help="upload the three feeds")
    ap.add_argument(
        "--push-inputs", action="store_true", help="upload the inputs after an edit"
    )
    args = ap.parse_args()
    sys.path.insert(0, str(HERE))
    from paths import IN

    IN.mkdir(parents=True, exist_ok=True)
    if args.push_inputs:
        for name in INPUT_FILES:
            subprocess.run(
                ["gcloud", "storage", "cp", str(IN / name), f"{INPUTS}/{name}"],
                check=True,
            )
        return
    for name in INPUT_FILES:
        if not (IN / name).exists():
            subprocess.run(
                ["gcloud", "storage", "cp", f"{INPUTS}/{name}", str(IN / name)],
                check=True,
            )
    for step in STEPS:
        print(f"== {step}", flush=True)
        runpy.run_path(str(HERE / step), run_name="__main__")
    if args.publish:
        from paths import OUT

        for feed in FEEDS:
            subprocess.run(
                ["gcloud", "storage", "cp", str(OUT / feed), f"{BUCKET}/{feed}"],
                check=True,
            )


if __name__ == "__main__":
    main()
