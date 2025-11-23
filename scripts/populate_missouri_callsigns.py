#!/usr/bin/env python3
"""Manually populate local_broadcaster_callsigns with known Missouri callsigns.

Based on analysis of wire_stories_20251122_165127.csv, we know KMIZ is the
primary local broadcaster causing false wire detection. Other Missouri market
stations include KOMU, KRCG, KQFX, and KJLU.
"""

from sqlalchemy import text
from src.models.database import DatabaseManager

# Known Missouri market broadcasters
MISSOURI_BROADCASTERS = [
    {
        "callsign": "KMIZ",
        "market": "Columbia-Jefferson City",
        "type": "TV",
        "notes": "ABC 17 News - Primary false positive source (727 articles)",
    },
    {
        "callsign": "KOMU",
        "market": "Columbia-Jefferson City",
        "type": "TV",
        "notes": "NBC affiliate - Local news source",
    },
    {
        "callsign": "KRCG",
        "market": "Columbia-Jefferson City",
        "type": "TV",
        "notes": "CBS affiliate - Local news source",
    },
    {
        "callsign": "KQFX",
        "market": "Columbia-Jefferson City",
        "type": "TV",
        "notes": "FOX affiliate - Local news source",
    },
    {
        "callsign": "KJLU",
        "market": "Columbia-Jefferson City",
        "type": "TV",
        "notes": "Zimmer Radio - Local broadcaster",
    },
]


def main():
    """Populate the table."""
    print("Populating local_broadcaster_callsigns table")
    print("=" * 80)
    
    db = DatabaseManager()
    with db.get_session() as session:
        for bc in MISSOURI_BROADCASTERS:
            # Check if already exists
            existing = session.execute(
                text("""
                    SELECT id FROM local_broadcaster_callsigns 
                    WHERE callsign = :callsign AND dataset = 'missouri'
                """),
                {"callsign": bc["callsign"]},
            ).first()
            
            if existing:
                print(f"{bc['callsign']}: Already exists (ID: {existing[0]})")
                continue
            
            # Insert new record
            session.execute(
                text("""
                    INSERT INTO local_broadcaster_callsigns 
                    (callsign, dataset, market_name, station_type, notes, created_at, updated_at)
                    VALUES 
                    (:callsign, 'missouri', :market, :type, :notes, NOW(), NOW())
                """),
                {
                    "callsign": bc["callsign"],
                    "market": bc["market"],
                    "type": bc["type"],
                    "notes": bc["notes"],
                },
            )
            print(f"{bc['callsign']}: ✅ Inserted")
        
        session.commit()
    
    print("\n✅ Done!")
    print(f"Populated {len(MISSOURI_BROADCASTERS)} callsigns for Missouri dataset")


if __name__ == "__main__":
    main()
