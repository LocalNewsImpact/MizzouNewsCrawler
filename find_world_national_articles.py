#!/usr/bin/env python3
"""Find articles with /world/ or /national/ URLs that should be wire."""
from src.models.database import DatabaseManager
from src.models import Article, CandidateLink
from sqlalchemy import or_

db = DatabaseManager()
session = db.session

# Find articles with /world/ or /national/ URLs that aren't wire
articles = (
    session.query(Article)
    .join(CandidateLink)
    .filter(Article.status.notin_(['wire', 'wire_service']))
    .filter(or_(
        Article.url.like('%/world/%'),
        Article.url.like('%/national/%')
    ))
    .limit(50)
    .all()
)

print(f"Found {len(articles)} articles with /world/ or /national/ URLs not marked as wire\n")

for a in articles:
    print(f"Status: {a.status}")
    print(f"URL: {a.url}")
    print(f"Title: {a.title[:80] if a.title else 'No title'}")
    print(f"Author: {a.author or 'No author'}")
    # Check last 150 chars for copyright
    if a.content:
        closing = a.content[-150:]
        if 'Copyright' in closing or '©' in closing:
            print(f"Closing: ...{closing[-100:]}")
    print("-" * 80)
