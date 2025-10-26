#!/usr/bin/env python3
"""Inspect database schema for BigQuery export."""

from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()

with db.engine.connect() as conn:
    # Get articles table schema
    result = conn.execute(text(
        "SELECT column_name, data_type "
        "FROM information_schema.columns "
        "WHERE table_name = 'articles' "
        "ORDER BY ordinal_position"
    ))
    print('ARTICLES TABLE COLUMNS:')
    for row in result:
        print(f'  {row[0]}: {row[1]}')
    
    print('\nCANDIDATE_LINKS TABLE COLUMNS:')
    result = conn.execute(text(
        "SELECT column_name, data_type "
        "FROM information_schema.columns "
        "WHERE table_name = 'candidate_links' "
        "ORDER BY ordinal_position"
    ))
    for row in result:
        print(f'  {row[0]}: {row[1]}')
    
    print('\nSOURCES TABLE COLUMNS:')
    result = conn.execute(text(
        "SELECT column_name, data_type "
        "FROM information_schema.columns "
        "WHERE table_name = 'sources' "
        "ORDER BY ordinal_position"
    ))
    for row in result:
        print(f'  {row[0]}: {row[1]}')
    
    print('\nSample query test:')
    result = conn.execute(text(
        "SELECT a.id, a.url, cl.source_id, cl.source_name "
        "FROM articles a "
        "LEFT JOIN candidate_links cl ON a.candidate_link_id = cl.id "
        "LIMIT 1"
    ))
    for row in result:
        print(f'  Found article: {row[0]} from {row[3]}')
