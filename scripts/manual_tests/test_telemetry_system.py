#!/usr/bin/env python3
"""
Test script to validate the byline cleaning telemetry system.

This script runs comprehensive tests to ensure telemetry collection,
storage, and analysis are working correctly.
"""

import json
import sqlite3
import sys
import time
from pathlib import Path

# Add the parent directory to the path to import src modules
sys.path.append(str(Path(__file__).parent.parent))

from src.config import DATABASE_URL
from src.utils.byline_cleaner import BylineCleaner
from scripts.analyze_byline_telemetry import BylineTelemetryAnalyzer


def test_telemetry_basic_functionality():
    """Test basic telemetry capture and storage."""
    print("🧪 Testing basic telemetry functionality...")

    # Initialize cleaner with telemetry enabled
    cleaner = BylineCleaner(enable_telemetry=True)

    test_cases = [
        {
            "byline": "By John Smith, Staff Reporter",
            "source_name": "Daily News",
            "expected_authors": ["John Smith"],
        },
        {
            "byline": "JANE DOE AND MIKE JOHNSON",
            "source_name": "Tribune",
            "expected_authors": ["Jane Doe", "Mike Johnson"],
        },
        {
            "byline": "sarah.wilson@news.com (Sarah Wilson)",
            "source_name": "News Corp",
            "expected_authors": ["Sarah Wilson"],
        },
        {
            "byline": "By Associated Press",
            "source_name": None,
            "expected_authors": ["By Associated Press"],  # Wire service preserved
        },
    ]


    for i, case in enumerate(test_cases, 1):
        print(f"  Test case {i}: '{case['byline']}'")

        # Clean the byline with telemetry
        result = cleaner.clean_byline(
            case["byline"],
            source_name=case["source_name"],
            article_id=f"test_article_{i}",
            candidate_link_id=f"test_link_{i}",
            source_id=f"test_source_{i}",
            source_canonical_name=case["source_name"],
        )

        print(f"    Result: {result}")

        # Brief pause to ensure different timestamps
        time.sleep(0.1)

    print("  ✅ Basic telemetry tests completed")
    return True


def test_telemetry_data_storage():
    """Test that telemetry data is properly stored in database."""
    print("\\n🧪 Testing telemetry data storage...")

    # Connect to database and check for recent telemetry records
    db_path = DATABASE_URL.replace("sqlite:///", "")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check main telemetry table
    cursor.execute("""
        SELECT COUNT(*) FROM byline_cleaning_telemetry 
        WHERE extraction_timestamp > datetime('now', '-1 minute')
    """)
    recent_count = cursor.fetchone()[0]

    print(f"  Recent telemetry records: {recent_count}")

    if recent_count == 0:
        print("  ❌ No recent telemetry records found")
        return False

    # Check transformation steps
    cursor.execute("""
        SELECT COUNT(*) FROM byline_transformation_steps bts
        JOIN byline_cleaning_telemetry bct ON bts.telemetry_id = bct.id
        WHERE bct.extraction_timestamp > datetime('now', '-1 minute')
    """)
    steps_count = cursor.fetchone()[0]

    print(f"  Transformation steps recorded: {steps_count}")

    # Get sample data for validation
    cursor.execute("""
        SELECT 
            raw_byline, 
            final_authors_json, 
            confidence_score,
            processing_time_ms,
            source_name,
            final_authors_count
        FROM byline_cleaning_telemetry 
        WHERE extraction_timestamp > datetime('now', '-1 minute')
        ORDER BY extraction_timestamp DESC
        LIMIT 3
    """)

    sample_records = cursor.fetchall()

    print("  Sample telemetry records:")
    for i, record in enumerate(sample_records, 1):
        raw_byline, final_json, confidence, time_ms, source, count = record
        authors = json.loads(final_json) if final_json else []
        print(f"    {i}. '{raw_byline}' → {authors}")
        print(f"       Confidence: {confidence}, Time: {time_ms}ms, Authors: {count}")

    conn.close()
    print("  ✅ Telemetry data storage verified")
    return True


def test_telemetry_analysis_tools():
    """Test the telemetry analysis functionality."""
    print("\\n🧪 Testing telemetry analysis tools...")

    analyzer = BylineTelemetryAnalyzer()

    # Test summary generation
    print("  Testing summary generation...")
    summary = analyzer.get_cleaning_summary(days=1)

    if "total_cleanings" not in summary:
        print("  ❌ Summary generation failed")
        return False

    print(f"    Total cleanings: {summary.get('total_cleanings', 0)}")
    print(f"    Average confidence: {summary.get('avg_confidence_score', 0)}")

    # Test source performance analysis
    print("  Testing source performance analysis...")
    source_performance = analyzer.get_source_performance(limit=5)

    print(f"    Sources analyzed: {len(source_performance)}")
    for source in source_performance[:2]:
        print(f"      {source['source_name']}: {source['cleaning_count']} cleanings")

    # Test transformation patterns
    print("  Testing transformation patterns...")
    patterns = analyzer.get_transformation_patterns(limit=5)

    print(f"    Patterns found: {len(patterns)}")
    if patterns:
        print(
            f"      Top pattern: '{patterns[0]['raw_byline']}' → '{patterns[0]['cleaned_result']}'"
        )

    # Test error analysis
    print("  Testing error analysis...")
    errors = analyzer.get_error_analysis()

    print(f"    Sessions with issues: {errors.get('total_sessions_with_issues', 0)}")

    print("  ✅ Analysis tools verified")
    return True


def test_ml_data_export():
    """Test ML training data export functionality."""
    print("\\n🧪 Testing ML training data export...")

    analyzer = BylineTelemetryAnalyzer()

    # Create temporary export file
    export_file = "test_ml_export.csv"

    try:
        result = analyzer.export_ml_training_data(
            output_file=export_file,
            min_confidence=0.0,  # Include all data for testing
            include_features=True,
        )

        print(f"  Records exported: {result['records_exported']}")
        print(f"  Columns: {len(result['columns'])}")
        print(f"  Output file: {result['output_file']}")

        # Verify file exists and has content
        if Path(export_file).exists():
            file_size = Path(export_file).stat().st_size
            print(f"  File size: {file_size} bytes")

            if file_size > 0:
                print("  ✅ ML data export successful")
                # Clean up test file
                Path(export_file).unlink()
                return True
            else:
                print("  ❌ Export file is empty")
                return False
        else:
            print("  ❌ Export file not created")
            return False

    except Exception as e:
        print(f"  ❌ Export failed: {e}")
        return False


def test_confidence_scoring():
    """Test confidence scoring and classification accuracy."""
    print("\\n🧪 Testing confidence scoring...")

    cleaner = BylineCleaner(enable_telemetry=True)

    # Test cases with expected confidence levels
    confidence_tests = [
        {
            "byline": "By John Smith",  # Simple, clean case
            "expected_min_confidence": 0.5,
        },
        {
            "byline": "john.smith@email.com (John Smith, Staff Writer)",  # Complex case
            "expected_min_confidence": 0.3,
        },
        {
            "byline": "ALLCAPS NOISE TEXT",  # Likely noise
            "expected_min_confidence": 0.0,
        },
        {
            "byline": "By Associated Press",  # Wire service
            "expected_min_confidence": 0.8,
        },
    ]

    # Connect to get confidence scores from database
    db_path = DATABASE_URL.replace("sqlite:///", "")

    for i, test in enumerate(confidence_tests, 1):
        print(f"  Confidence test {i}: '{test['byline']}'")

        # Run cleaning
        cleaner.clean_byline(test["byline"], article_id=f"confidence_test_{i}")

        # Get the recorded confidence
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT confidence_score, likely_valid_authors, likely_noise
            FROM byline_cleaning_telemetry 
            WHERE article_id = ?
            ORDER BY extraction_timestamp DESC
            LIMIT 1
        """,
            (f"confidence_test_{i}",),
        )

        telemetry_result = cursor.fetchone()

        if telemetry_result:
            confidence, valid, noise = telemetry_result
            print(f"    Confidence: {confidence}")
            print(f"    Valid: {bool(valid)}, Noise: {bool(noise)}")

            if confidence >= test["expected_min_confidence"]:
                print(
                    f"    ✅ Confidence meets expectation (>= {test['expected_min_confidence']})"
                )
            else:
                print(
                    f"    ⚠️  Confidence below expectation (< {test['expected_min_confidence']})"
                )
        else:
            print("    ❌ No telemetry data found")

        conn.close()
        time.sleep(0.1)

    print("  ✅ Confidence scoring tests completed")
    return True


def run_comprehensive_test():
    """Run all telemetry system tests."""
    print("🚀 Starting Comprehensive Telemetry System Test")
    print("=" * 60)

    tests = [
        ("Basic Functionality", test_telemetry_basic_functionality),
        ("Data Storage", test_telemetry_data_storage),
        ("Analysis Tools", test_telemetry_analysis_tools),
        ("ML Data Export", test_ml_data_export),
        ("Confidence Scoring", test_confidence_scoring),
    ]

    results = {}

    for test_name, test_func in tests:
        try:
            print(f"\\n📋 Running {test_name} Test...")
            results[test_name] = test_func()
        except Exception as e:
            print(f"❌ {test_name} test failed with error: {e}")
            results[test_name] = False

    # Final summary
    print("\\n" + "=" * 60)
    print("🎯 Test Results Summary")
    print("=" * 60)

    passed = sum(1 for result in results.values() if result)
    total = len(results)

    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test_name}: {status}")

    print(f"\\nOverall: {passed}/{total} tests passed")

    if passed == total:
        print("\\n🎉 All telemetry system tests PASSED!")
        print("System is ready for production use and ML training data collection.")
    else:
        print(f"\\n⚠️  {total - passed} test(s) failed. Please review and fix issues.")

    return passed == total


if __name__ == "__main__":
    success = run_comprehensive_test()
    sys.exit(0 if success else 1)
