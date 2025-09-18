"""Database utilities for SQLite backend with idempotent operations."""

import hashlib
import logging
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from typing import Optional, Dict, Any, List
import uuid

from .models import Base, CandidateLink, Article, MLResult, Location, Job

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages database connections and operations."""
    
    def __init__(self, database_url: str = "sqlite:///data/mizzou.db"):
        self.database_url = database_url
        self.engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False} if "sqlite" in database_url else {},
            echo=False
        )
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()
    
    def close(self):
        """Close database connection."""
        self.session.close()
        self.engine.dispose()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def calculate_content_hash(content: str) -> str:
    """Calculate SHA256 hash of content for deduplication."""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def upsert_candidate_link(session, url: str, source: str, **kwargs) -> CandidateLink:
    """Insert or update candidate link (idempotent by URL)."""
    # Check if link already exists
    existing = session.query(CandidateLink).filter_by(url=url).first()
    
    if existing:
        # Update existing record with new data
        for key, value in kwargs.items():
            if hasattr(existing, key) and value is not None:
                setattr(existing, key, value)
        session.commit()
        logger.debug(f"Updated existing candidate link: {url}")
        return existing
    else:
        # Create new record
        link = CandidateLink(
            url=url,
            source=source,
            **kwargs
        )
        session.add(link)
        session.commit()
        logger.info(f"Created new candidate link: {url}")
        return link


def upsert_article(session, candidate_id: str, text: str, **kwargs) -> Article:
    """Insert or update article (idempotent by candidate_id + text_hash)."""
    text_hash = calculate_content_hash(text)
    
    # Check if article already exists
    existing = session.query(Article).filter_by(
        candidate_id=candidate_id,
        text_hash=text_hash
    ).first()
    
    if existing:
        # Update existing record
        for key, value in kwargs.items():
            if hasattr(existing, key) and value is not None:
                setattr(existing, key, value)
        session.commit()
        logger.debug(f"Updated existing article for candidate: {candidate_id}")
        return existing
    else:
        # Create new record
        article = Article(
            candidate_id=candidate_id,
            text=text,
            text_hash=text_hash,
            text_excerpt=text[:500] if text else None,
            **kwargs
        )
        session.add(article)
        session.commit()
        logger.info(f"Created new article for candidate: {candidate_id}")
        return article


def save_ml_results(session, article_id: str, model_version: str, 
                   model_type: str, results: List[Dict[str, Any]], 
                   job_id: Optional[str] = None) -> List[MLResult]:
    """Save ML results for an article."""
    ml_records = []
    
    for result in results:
        ml_result = MLResult(
            article_id=article_id,
            model_version=model_version,
            model_type=model_type,
            label=result.get('label'),
            score=result.get('score'),
            confidence=result.get('confidence'),
            job_id=job_id,
            details=result
        )
        session.add(ml_result)
        ml_records.append(ml_result)
    
    session.commit()
    logger.info(f"Saved {len(ml_records)} ML results for article: {article_id}")
    return ml_records


def save_locations(session, article_id: str, entities: List[Dict[str, Any]], 
                  ner_model_version: str = None) -> List[Location]:
    """Save location entities for an article."""
    location_records = []
    
    for entity in entities:
        location = Location(
            article_id=article_id,
            entity_text=entity.get('text'),
            entity_type=entity.get('label'),
            confidence=entity.get('confidence'),
            geocoded_lat=entity.get('lat'),
            geocoded_lon=entity.get('lon'),
            geocoded_place=entity.get('place'),
            geocoding_source=entity.get('geocoding_source'),
            ner_model_version=ner_model_version
        )
        session.add(location)
        location_records.append(location)
    
    session.commit()
    logger.info(f"Saved {len(location_records)} locations for article: {article_id}")
    return location_records


def create_job_record(session, job_type: str, job_name: str = None, 
                     params: Dict[str, Any] = None, **kwargs) -> Job:
    """Create a new job record for tracking execution."""
    job = Job(
        job_type=job_type,
        job_name=job_name,
        params=params or {},
        **kwargs
    )
    session.add(job)
    session.commit()
    logger.info(f"Created job record: {job.id} ({job_type})")
    return job


def finish_job_record(session, job_id: str, exit_status: str, 
                     metrics: Dict[str, Any] = None) -> Job:
    """Mark job as finished with final metrics."""
    job = session.query(Job).filter_by(id=job_id).first()
    if job:
        job.finished_at = pd.Timestamp.utcnow()
        job.exit_status = exit_status
        
        # Update metrics
        if metrics:
            for key, value in metrics.items():
                if hasattr(job, key):
                    setattr(job, key, value)
        
        session.commit()
        logger.info(f"Finished job: {job_id} with status: {exit_status}")
    return job


# Pandas integration for bulk operations

def read_candidate_links(engine, filters: Dict[str, Any] = None) -> pd.DataFrame:
    """Read candidate links as DataFrame with optional filters."""
    query = "SELECT * FROM candidate_links"
    
    if filters:
        conditions = []
        for key, value in filters.items():
            if isinstance(value, str):
                conditions.append(f"{key} = '{value}'")
            else:
                conditions.append(f"{key} = {value}")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
    
    return pd.read_sql(query, engine)


def read_articles(engine, filters: Dict[str, Any] = None) -> pd.DataFrame:
    """Read articles as DataFrame with optional filters."""
    query = """
    SELECT a.*, cl.url, cl.source 
    FROM articles a 
    JOIN candidate_links cl ON a.candidate_id = cl.id
    """
    
    if filters:
        conditions = []
        for key, value in filters.items():
            if isinstance(value, str):
                conditions.append(f"a.{key} = '{value}'")
            else:
                conditions.append(f"a.{key} = {value}")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
    
    return pd.read_sql(query, engine)


def bulk_insert_candidate_links(engine, df: pd.DataFrame, 
                               if_exists: str = 'append') -> int:
    """Bulk insert candidate links from DataFrame."""
    # Ensure required columns
    required_cols = ['url', 'source']
    if not all(col in df.columns for col in required_cols):
        raise ValueError(f"DataFrame must contain columns: {required_cols}")
    
    # Add default values for missing columns
    if 'id' not in df.columns:
        df['id'] = [str(uuid.uuid4()) for _ in range(len(df))]
    if 'status' not in df.columns:
        df['status'] = 'new'
    if 'discovered_at' not in df.columns:
        df['discovered_at'] = pd.Timestamp.utcnow()
    
    # Write to database
    rows_inserted = df.to_sql(
        'candidate_links', 
        engine, 
        if_exists=if_exists, 
        index=False,
        method='multi'
    )
    
    logger.info(f"Bulk inserted {rows_inserted} candidate links")
    return rows_inserted


def export_to_parquet(engine, table_name: str, output_path: str, 
                     filters: Dict[str, Any] = None) -> str:
    """Export table data to Parquet for archival."""
    query = f"SELECT * FROM {table_name}"
    
    if filters:
        conditions = []
        for key, value in filters.items():
            if isinstance(value, str):
                conditions.append(f"{key} = '{value}'")
            else:
                conditions.append(f"{key} = {value}")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
    
    df = pd.read_sql(query, engine)
    df.to_parquet(output_path, compression='snappy')
    
    logger.info(f"Exported {len(df)} rows from {table_name} to {output_path}")
    return output_path