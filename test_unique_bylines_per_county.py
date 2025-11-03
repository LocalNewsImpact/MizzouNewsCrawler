"""Test script to count unique bylines per county.

This script finds bylines that appear ONLY in articles from a specific county,
not in any other county.
"""

from sqlalchemy import text
from src.models.database import DatabaseManager


def test_unique_bylines_query():
    """Test the query to find unique bylines per county."""
    
    # Connect to database
    db = DatabaseManager()
    session = db.session
    
    # Detect database dialect and use appropriate aggregate function
    dialect = session.bind.dialect.name
    if dialect == 'sqlite':
        agg_func = "GROUP_CONCAT(author, ', ')"
        print("Testing with SQLite...")
    else:
        agg_func = "STRING_AGG(author, ', ' ORDER BY author)"
        print("Testing with PostgreSQL...")
    
    # Build query with appropriate aggregate function
    query = f"""
    WITH author_counties AS (
        SELECT DISTINCT
            a.author,
            cl.source_county as county
        FROM articles a
        JOIN candidate_links cl ON a.candidate_link_id = cl.id
        WHERE a.author IS NOT NULL 
          AND a.author != ''
          AND cl.source_county IS NOT NULL
          AND cl.source_county != ''
    ),
    author_county_counts AS (
        SELECT 
            author,
            COUNT(DISTINCT county) as county_count,
            MAX(county) as only_county
        FROM author_counties
        GROUP BY author
        HAVING COUNT(DISTINCT county) = 1
    )
    SELECT 
        only_county as county,
        COUNT(*) as unique_author_count,
        {agg_func} as unique_authors
    FROM author_county_counts
    GROUP BY only_county
    ORDER BY unique_author_count DESC, county;
    """
    
    print("=" * 80)
    result = session.execute(text(query))
    rows = result.fetchall()
    
    if not rows:
        print("No results found. This might mean:")
        print("- No articles with authors in the database")
        print("- No county information on candidate_links")
        print("- All authors appear in multiple counties")
        return
    
    print(f"\nFound {len(rows)} counties with unique bylines:\n")
    
    total_unique = 0
    for row in rows:
        county = row[0]
        count = row[1]
        authors = row[2]
        total_unique += count
        
        print(f"{county}: {count} unique authors")
        if count <= 10:  # Show author names for counties with <= 10 unique authors
            print(f"  Authors: {authors}")
        print()
    
    print(f"Total unique authors across all counties: {total_unique}")
    
    print("\n" + "=" * 80)
    print("\nBigQuery version:")
    print("=" * 80)
    
    # BigQuery version (adjust field names)
    bigquery_query = """
    WITH author_counties AS (
        SELECT DISTINCT
            authors,
            county
        FROM `your-project.your_dataset.articles`
        WHERE authors IS NOT NULL 
          AND authors != ''
          AND county IS NOT NULL
          AND county != ''
    ),
    author_county_counts AS (
        SELECT 
            authors,
            COUNT(DISTINCT county) as county_count,
            MAX(county) as only_county
        FROM author_counties
        GROUP BY authors
        HAVING COUNT(DISTINCT county) = 1
    )
    SELECT 
        only_county as county,
        COUNT(*) as unique_author_count,
        STRING_AGG(authors, ', ') as unique_authors
    FROM author_county_counts
    GROUP BY only_county
    ORDER BY unique_author_count DESC, county;
    """
    
    print(bigquery_query)
    
    print("\n" + "=" * 80)
    print("\nSimpler BigQuery version (just counts, no author names):")
    print("=" * 80)
    
    simple_bigquery_query = """
    WITH author_counties AS (
        SELECT DISTINCT
            authors,
            county
        FROM `your-project.your_dataset.articles`
        WHERE authors IS NOT NULL 
          AND authors != ''
          AND county IS NOT NULL
          AND county != ''
    ),
    author_county_counts AS (
        SELECT 
            authors,
            COUNT(DISTINCT county) as county_count,
            MAX(county) as only_county
        FROM author_counties
        GROUP BY authors
        HAVING COUNT(DISTINCT county) = 1
    )
    SELECT 
        only_county as county,
        COUNT(*) as unique_author_count
    FROM author_county_counts
    GROUP BY only_county
    ORDER BY unique_author_count DESC, county;
    """
    
    print(simple_bigquery_query)


if __name__ == "__main__":
    test_unique_bylines_query()
