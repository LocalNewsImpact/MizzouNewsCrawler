"""
Integration example: Enhanced wire filtering for MizzouNewsCrawler pipeline.

This shows how to integrate OSM-based geographic filtering into the existing
phase 5 wire filtering logic.
"""

import logging
from pathlib import Path
from typing import List, Tuple

import pandas as pd
import spacy

logger = logging.getLogger(__name__)


class PublisherGeoFilter:
    """Simplified geographic filtering for wire articles."""

    def __init__(self, publishers_csv: str = "sources/publinks.csv"):
        self.publishers_df = pd.read_csv(publishers_csv)
        self.nlp = spacy.load("en_core_web_sm")
        self.publisher_gazetteers = {}
        self._load_publisher_data()

    def _load_publisher_data(self):
        """Load publisher geographic coverage data."""
        for _, row in self.publishers_df.iterrows():
            publisher_id = str(row["host_id"])

            # Create basic gazetteer from publisher location data
            gazetteer = {
                "primary_locations": [
                    row["name"].split()[0],  # First word of publisher name
                    row.get("county", ""),
                    row.get("city", ""),
                ],
                "coverage_keywords": [
                    f"{row.get('county', '')} County",
                    "Missouri",  # State-level coverage
                    "local",
                    "area",
                    "region",
                ],
            }

            # Remove empty strings
            gazetteer["primary_locations"] = [
                loc for loc in gazetteer["primary_locations"] if loc.strip()
            ]

            self.publisher_gazetteers[publisher_id] = gazetteer

    def has_local_geographic_signals(
        self, text: str, publisher_id: str
    ) -> Tuple[bool, List[str]]:
        """Check if text contains locally relevant geographic references."""
        if publisher_id not in self.publisher_gazetteers:
            return False, []

        gazetteer = self.publisher_gazetteers[publisher_id]
        doc = self.nlp(text.lower())

        # Extract named entities (locations, organizations)
        entities = [
            ent.text for ent in doc.ents if ent.label_ in [
                "GPE", "LOC", "ORG"]]

        # Check for matches with publisher's coverage area
        local_matches = []
        text_lower = text.lower()

        # Check primary locations
        for location in gazetteer["primary_locations"]:
            if location.lower() in text_lower:
                local_matches.append(location)

        # Check coverage keywords
        for keyword in gazetteer["coverage_keywords"]:
            if keyword.lower() in text_lower:
                local_matches.append(keyword)

        # Check NER entities against known locations
        for entity in entities:
            for location in gazetteer["primary_locations"]:
                if (
                    location.lower() in entity.lower()
                    or entity.lower() in location.lower()
                ):
                    local_matches.append(entity)

        return len(local_matches) > 0, list(set(local_matches))


def enhanced_local_wire_classification(
    df: pd.DataFrame, geo_filter: PublisherGeoFilter
) -> pd.DataFrame:
    """Enhanced local_wire classification using geographic signals."""

    for idx, row in df.iterrows():
        publisher_id = str(row["host_id"])
        article_text = f"{row.get('title', '')} {row.get('news', '')}"

        # Get existing local_wire value (from current logic)
        existing_local_wire = int(row.get("local_wire", 0))

        # Check for geographic local signals
        has_geo_signals, locations = geo_filter.has_local_geographic_signals(
            article_text, publisher_id
        )

        # Enhanced local_wire: original logic OR geographic signals
        enhanced_local_wire = max(
            existing_local_wire,
            1 if has_geo_signals else 0)

        # Update row with enhanced data
        df.at[idx, "local_wire"] = enhanced_local_wire
        df.at[idx, "has_geographic_signals"] = has_geo_signals
        df.at[idx, "detected_locations"] = "; ".join(
            locations) if locations else ""

        # Add reasoning for local_wire classification
        reasons = []
        if existing_local_wire:
            reasons.append("institutional_signals")
        if has_geo_signals:
            reasons.append("geographic_signals")

        df.at[idx, "local_wire_reasoning"] = "; ".join(reasons)

    return df


def integrate_with_existing_pipeline():
    """Show how to integrate enhanced filtering into existing pipeline."""

    # This would be added to the wire filtering phase (phase 5)
    def enhanced_wire_filtering_phase(df: pd.DataFrame) -> pd.DataFrame:
        """Enhanced version of existing wire filtering logic."""

        # 1. Apply existing wire detection logic first
        # ... existing logic that sets 'wire' column ...

        # 2. Apply existing local_wire logic
        # ... existing logic that creates basic local_wire classification ...

        # 3. Apply enhanced geographic filtering
        try:
            geo_filter = PublisherGeoFilter("sources/publinks.csv")
            df = enhanced_local_wire_classification(df, geo_filter)
            logger.info("Enhanced geographic filtering applied successfully")
        except Exception as e:
            logger.warning(
                f"Geographic filtering failed, using basic logic: {e}")

        return df

    return enhanced_wire_filtering_phase


# Example of how this would work with the existing phase 7 logic
def updated_phase_7_logic():
    """Updated phase 7 to use enhanced local_wire classification."""

    # The existing wire filtering logic in phase 7 would remain the same:
    # - Non-wire articles (wire=0) → ML classification
    # - Locally relevant wire articles (wire=1 & local_wire=1) → ML classification
    # - Pure wire articles (wire=1 & local_wire=0) → Skip ML

    # But now local_wire would be more accurate due to geographic signals
    pass


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)

    # Create sample data
    sample_df = pd.DataFrame(
        {
            "host_id": [1, 1, 2],
            "title": [
                "Columbia City Council approves new budget",
                "Breaking: Major earthquake hits California",
                "Local high school wins state championship",
            ],
            "news": [
                "The Columbia City Council voted unanimously to approve the fiscal year budget...",
                "A 7.1 magnitude earthquake struck near Los Angeles this morning...",
                "The Kansas City area team defeated their rivals in the championship game...",
            ],
            "wire": [0, 1, 0],
            # Original logic didn't detect local relevance
            "local_wire": [0, 0, 0],
        }
    )

    # Create sample publisher data
    sample_publishers = pd.DataFrame(
        {
            "host_id": [1, 2],
            "name": ["Columbia Daily Tribune", "Kansas City Star"],
            "county": ["Boone", "Jackson"],
            "city": ["Columbia", "Kansas City"],
        }
    )

    # Ensure directory exists
    Path("sources").mkdir(exist_ok=True)
    sample_publishers.to_csv("sources/publinks.csv", index=False)

    # Test enhanced filtering
    geo_filter = PublisherGeoFilter()
    result_df = enhanced_local_wire_classification(sample_df, geo_filter)

    print("Enhanced local_wire classification results:")
    print(
        result_df[
            [
                "title",
                "wire",
                "local_wire",
                "has_geographic_signals",
                "detected_locations",
            ]
        ]
    )
