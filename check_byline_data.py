"""Check data availability for byline analysis."""

from sqlalchemy import text
from src.models.database import DatabaseManager


def check_data():
    """Check what data we have for analysis."""
    
    db = DatabaseManager()
    session = db.session
    
    # Check articles with authors
    print("Checking articles with authors...")
    result = session.execute(text("""
        SELECT COUNT(*) as total,
               COUNT(CASE WHEN author IS NOT NULL AND author != '' THEN 1 END) as with_author
        FROM articles
    """))
    row = result.fetchone()
    print(f"Total articles: {row[0]}")
    print(f"Articles with author: {row[1]}")
    print()
    
    # Check candidate_links with counties
    print("Checking candidate_links with counties...")
    result = session.execute(text("""
        SELECT COUNT(*) as total,
               COUNT(CASE WHEN source_county IS NOT NULL AND source_county != '' THEN 1 END) as with_county
        FROM candidate_links
    """))
    row = result.fetchone()
    print(f"Total candidate_links: {row[0]}")
    print(f"Links with county: {row[1]}")
    print()
    
    # Check joined data
    print("Checking articles with authors AND county info...")
    result = session.execute(text("""
        SELECT COUNT(*) as count,
               COUNT(DISTINCT cl.source_county) as distinct_counties,
               COUNT(DISTINCT a.author) as distinct_authors
        FROM articles a
        JOIN candidate_links cl ON a.candidate_link_id = cl.id
        WHERE a.author IS NOT NULL 
          AND a.author != ''
          AND cl.source_county IS NOT NULL
          AND cl.source_county != ''
    """))
    row = result.fetchone()
    print(f"Articles with author AND county: {row[0]}")
    print(f"Distinct counties: {row[1]}")
    print(f"Distinct authors: {row[2]}")
    print()
    
    # Sample some counties
    print("Sample counties:")
    result = session.execute(text("""
        SELECT DISTINCT cl.source_county, COUNT(*) as article_count
        FROM articles a
        JOIN candidate_links cl ON a.candidate_link_id = cl.id
        WHERE a.author IS NOT NULL 
          AND a.author != ''
          AND cl.source_county IS NOT NULL
          AND cl.source_county != ''
        GROUP BY cl.source_county
        ORDER BY article_count DESC
        LIMIT 10
    """))
    for row in result.fetchall():
        print(f"  {row[0]}: {row[1]} articles")
    print()
    
    # Check author distribution
    print("Authors appearing in multiple counties:")
    
    # Use appropriate aggregate function based on database dialect
    dialect = session.bind.dialect.name
    if dialect == 'sqlite':
        agg_func = "GROUP_CONCAT(county, ', ')"
    else:
        agg_func = "STRING_AGG(county, ', ')"
    
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
        )
        SELECT 
            author,
            COUNT(DISTINCT county) as county_count,
            {agg_func} as counties
        FROM author_counties
        GROUP BY author
        HAVING COUNT(DISTINCT county) > 1
        ORDER BY county_count DESC
        LIMIT 10
    """
    result = session.execute(text(query))
    rows = result.fetchall()
    if rows:
        for row in rows:
            print(f"  {row[0]}: {row[1]} counties ({row[2]})")
    else:
        print("  No authors found in multiple counties!")


if __name__ == "__main__":
    check_data()
