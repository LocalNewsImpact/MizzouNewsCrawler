#!/usr/bin/env python3
"""Test manual OpenStreetMap API calls to debug gazetteer issues."""

import requests
import time
from pathlib import Path
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from src.models.database import DatabaseManager
from sqlalchemy import text


def test_nominatim_geocoding():
    """Test Nominatim geocoding for Columbia, MO."""
    print("🌍 Testing Nominatim geocoding...")

    # Test addresses from our failed sources
    test_addresses = [
        "Columbia, MO",
        "Columbia, Missouri",
        "Columbia Daily Tribune, Columbia, MO",
        "Constitution-Tribune, Chillicothe, MO",
    ]

    for address in test_addresses:
        print(f"\n📍 Testing address: {address}")

        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": address, "format": "jsonv2", "limit": 1}
        headers = {"User-Agent": "mizzou-gazetteer/1.0 (contact: dev@example.com)"}

        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            print(f"  Status: {r.status_code}")

            if r.status_code == 200:
                data = r.json()
                if data:
                    lat = float(data[0]["lat"])
                    lon = float(data[0]["lon"])
                    print(f"  ✅ Found: {lat:.4f}, {lon:.4f}")
                    print(f"  Display name: {data[0]['display_name']}")
                    return (
                        lat,
                        lon,
                    )  # Return first successful geocoding for overpass test
                else:
                    print("  ❌ No results")
            else:
                print(f"  ❌ HTTP error: {r.status_code}")
        except Exception as e:
            print(f"  ❌ Error: {e}")

        time.sleep(1)  # Be respectful

    return None, None


def test_overpass_api(lat, lon):
    """Test Overpass API with the geocoded coordinates."""
    if not lat or not lon:
        print("\n⚠️  Skipping Overpass test - no valid coordinates")
        return

    print(f"\n🔍 Testing Overpass API for {lat:.4f}, {lon:.4f}")
    print("📡 Using sample query for schools...")

    overpass_url = "https://overpass-api.de/api/interpreter"
    radius_m = 32186  # 20 miles in meters

    # Simple query for schools
    query = f"""
    [out:json][timeout:60];
    (
      node["amenity"="school"](around:{radius_m},{lat},{lon});
      way["amenity"="school"](around:{radius_m},{lat},{lon});
    );
    out center tags;
    """

    try:
        print(f"  Query radius: {radius_m}m (20 miles)")
        print(f"  URL: {overpass_url}")

        r = requests.post(overpass_url, data={"data": query}, timeout=60)
        print(f"  Status: {r.status_code}")

        if r.status_code == 200:
            data = r.json()
            elements = data.get("elements", [])
            print(f"  ✅ Found {len(elements)} school elements")

            # Show a few examples
            for i, elem in enumerate(elements[:3]):
                name = elem.get("tags", {}).get("name", "unnamed")
                elem_lat = elem.get("lat") or elem.get("center", {}).get("lat", "?")
                elem_lon = elem.get("lon") or elem.get("center", {}).get("lon", "?")
                print(f"    [{i + 1}] {name} at {elem_lat}, {elem_lon}")

            if elements:
                print(
                    f"  🎯 API is working! Found {len(elements)} schools near Columbia, MO"
                )
            else:
                print(
                    "  ⚠️  API responded but found 0 schools (unexpected for Columbia, MO)"
                )
        else:
            print(f"  ❌ HTTP error: {r.status_code}")
            print(f"  Response: {r.text[:200]}...")

    except Exception as e:
        print(f"  ❌ Error: {e}")


def test_source_location():
    """Test getting source location from database."""
    print("\n📊 Testing source location from database...")

    db = DatabaseManager()

    with db.engine.connect() as conn:
        result = conn.execute(
            text(
                """
            SELECT canonical_name, city, county, state
            FROM sources 
            WHERE canonical_name = 'Columbia Daily Tribune'
        """
            )
        )

        row = result.fetchone()
        if row:
            print(f"  Found: {row.canonical_name}")
            print(f"  Location: {row.city}, {row.county}, {row.state}")

            # Test geocoding this exact location
            address = f"{row.city}, {row.state}"
            print(f"\n🎯 Testing specific address: {address}")

            url = "https://nominatim.openstreetmap.org/search"
            params = {"q": address, "format": "jsonv2", "limit": 1}
            headers = {"User-Agent": "mizzou-gazetteer/1.0 (contact: dev@example.com)"}

            try:
                r = requests.get(url, params=params, headers=headers, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    if data:
                        lat = float(data[0]["lat"])
                        lon = float(data[0]["lon"])
                        print(f"  ✅ Geocoded: {lat:.4f}, {lon:.4f}")
                        return lat, lon
                    else:
                        print("  ❌ No geocoding results")
                else:
                    print(f"  ❌ Geocoding failed: {r.status_code}")
            except Exception as e:
                print(f"  ❌ Geocoding error: {e}")
        else:
            print("  ❌ Columbia Daily Tribune not found in database")

    return None, None


if __name__ == "__main__":
    print("🧪 Manual OpenStreetMap API Testing")
    print("=" * 50)

    # Test 1: Nominatim geocoding
    lat, lon = test_nominatim_geocoding()

    # Test 2: Overpass API
    if lat and lon:
        test_overpass_api(lat, lon)

    # Test 3: Source-specific location
    source_lat, source_lon = test_source_location()
    if source_lat and source_lon and (source_lat != lat or source_lon != lon):
        print("\n🔄 Testing Overpass with source-specific coordinates...")
        test_overpass_api(source_lat, source_lon)

    print("\n✅ Manual API testing completed")
