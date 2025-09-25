"""
Telemetry system for byline cleaning transformations.

Captures detailed information about the cleaning process for ML training data
and performance analysis.
"""

import json
import sqlite3
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from src.config import DATABASE_URL


class BylineCleaningTelemetry:
    """Comprehensive telemetry collection for byline cleaning operations."""
    
    def __init__(self, enable_telemetry: bool = True):
        """
        Initialize telemetry collector.
        
        Args:
            enable_telemetry: Whether to actually collect and store telemetry
        """
        self.enable_telemetry = enable_telemetry
        self.session_id = str(uuid.uuid4())
        self.step_counter = 0
        
        # Current cleaning session data
        self.current_session: Optional[Dict[str, Any]] = None
        self.transformation_steps: List[Dict[str, Any]] = []
        
    def start_cleaning_session(
        self,
        raw_byline: str,
        article_id: Optional[str] = None,
        candidate_link_id: Optional[str] = None,
        source_id: Optional[str] = None,
        source_name: Optional[str] = None,
        source_canonical_name: Optional[str] = None
    ) -> str:
        """
        Start a new byline cleaning session.
        
        Returns:
            telemetry_id: Unique identifier for this cleaning session
        """
        if not self.enable_telemetry:
            return str(uuid.uuid4())
            
        telemetry_id = str(uuid.uuid4())
        start_time = time.time()
        
        self.current_session = {
            'telemetry_id': telemetry_id,
            'article_id': article_id,
            'candidate_link_id': candidate_link_id,
            'source_id': source_id,
            'source_name': source_name,
            'source_canonical_name': source_canonical_name,
            'raw_byline': raw_byline,
            'raw_byline_length': len(raw_byline) if raw_byline else 0,
            'raw_byline_words': len(raw_byline.split()) if raw_byline else 0,
            'start_time': start_time,
            'extraction_timestamp': datetime.now(),
            'has_wire_service': False,
            'has_email': False,
            'has_title': False,
            'has_organization': False,
            'source_name_removed': False,
            'duplicates_removed_count': 0,
            'cleaning_errors': [],
            'parsing_warnings': [],
            'confidence_score': 0.0
        }
        
        self.transformation_steps = []
        self.step_counter = 0
        
        return telemetry_id
        
    def log_transformation_step(
        self,
        step_name: str,
        input_text: str,
        output_text: str,
        transformation_type: str = "processing",
        removed_content: Optional[str] = None,
        added_content: Optional[str] = None,
        confidence_delta: float = 0.0,
        notes: Optional[str] = None
    ):
        """Log a single transformation step in the cleaning process."""
        if not self.enable_telemetry or not self.current_session:
            return
            
        self.step_counter += 1
        step_start_time = time.time()
        
        step_data = {
            'id': str(uuid.uuid4()),
            'telemetry_id': self.current_session['telemetry_id'],
            'step_number': self.step_counter,
            'step_name': step_name,
            'input_text': input_text,
            'output_text': output_text,
            'transformation_type': transformation_type,
            'removed_content': removed_content,
            'added_content': added_content,
            'confidence_delta': confidence_delta,
            'processing_time_ms': (time.time() - step_start_time) * 1000,
            'notes': notes,
            'timestamp': datetime.now()
        }
        
        self.transformation_steps.append(step_data)
        
        # Update session metadata based on transformation
        if step_name == "email_removal" and removed_content:
            self.current_session['has_email'] = True
            
        if step_name == "source_removal" and removed_content:
            self.current_session['source_name_removed'] = True
            
        if step_name == "wire_service_detection" and "wire service" in str(notes).lower():
            self.current_session['has_wire_service'] = True
            
        if step_name == "duplicate_removal" and removed_content:
            # Count removed duplicates
            if removed_content:
                removed_count = len([item for item in removed_content.split(',') if item.strip()])
                self.current_session['duplicates_removed_count'] += removed_count
                
        # Update running confidence score
        self.current_session['confidence_score'] += confidence_delta
        
    def log_error(self, error_message: str, error_type: str = "processing"):
        """Log an error during cleaning."""
        if not self.enable_telemetry or not self.current_session:
            return
            
        error_data = {
            'type': error_type,
            'message': error_message,
            'timestamp': datetime.now().isoformat(),
            'step': self.step_counter
        }
        
        self.current_session['cleaning_errors'].append(error_data)
        
    def log_warning(self, warning_message: str, warning_type: str = "parsing"):
        """Log a warning during cleaning."""
        if not self.enable_telemetry or not self.current_session:
            return
            
        warning_data = {
            'type': warning_type,
            'message': warning_message,
            'timestamp': datetime.now().isoformat(),
            'step': self.step_counter
        }
        
        self.current_session['parsing_warnings'].append(warning_data)
        
    def finalize_cleaning_session(
        self,
        final_authors: List[str],
        cleaning_method: str = "standard",
        likely_valid_authors: Optional[bool] = None,
        likely_noise: Optional[bool] = None,
        requires_manual_review: Optional[bool] = None
    ):
        """
        Finalize the cleaning session and store telemetry data.
        
        Args:
            final_authors: List of final cleaned author names
            cleaning_method: Method used for cleaning
            likely_valid_authors: Whether authors appear to be valid
            likely_noise: Whether result appears to be noise
            requires_manual_review: Whether result needs manual review
        """
        if not self.enable_telemetry or not self.current_session:
            return
            
        # Calculate final metrics
        total_time = (time.time() - self.current_session['start_time']) * 1000
        
        # Update session with final data
        self.current_session.update({
            'cleaning_method': cleaning_method,
            'final_authors_json': json.dumps(final_authors),
            'final_authors_count': len(final_authors),
            'final_authors_display': ', '.join(final_authors),
            'processing_time_ms': total_time,
            'likely_valid_authors': likely_valid_authors,
            'likely_noise': likely_noise,
            'requires_manual_review': requires_manual_review,
            'cleaning_errors': json.dumps(self.current_session['cleaning_errors']),
            'parsing_warnings': json.dumps(self.current_session['parsing_warnings'])
        })
        
        # Store the session data
        self._store_telemetry_data()
        
        # Reset for next session
        self.current_session = None
        self.transformation_steps = []
        self.step_counter = 0
        
    def _store_telemetry_data(self):
        """Store the current session telemetry data to database."""
        if not self.current_session:
            return
            
        try:
            # Convert DATABASE_URL to file path
            db_path = DATABASE_URL.replace('sqlite:///', '')
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Insert main telemetry record
            cursor.execute("""
                INSERT INTO byline_cleaning_telemetry (
                    id, article_id, candidate_link_id, source_id, source_name,
                    raw_byline, raw_byline_length, raw_byline_words,
                    extraction_timestamp, cleaning_method, source_canonical_name,
                    final_authors_json, final_authors_count, final_authors_display,
                    confidence_score, processing_time_ms, has_wire_service,
                    has_email, has_title, has_organization, source_name_removed,
                    duplicates_removed_count, likely_valid_authors, likely_noise,
                    requires_manual_review, cleaning_errors, parsing_warnings
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                self.current_session['telemetry_id'],
                self.current_session.get('article_id'),
                self.current_session.get('candidate_link_id'),
                self.current_session.get('source_id'),
                self.current_session.get('source_name'),
                self.current_session['raw_byline'],
                self.current_session['raw_byline_length'],
                self.current_session['raw_byline_words'],
                self.current_session['extraction_timestamp'],
                self.current_session.get('cleaning_method'),
                self.current_session.get('source_canonical_name'),
                self.current_session.get('final_authors_json'),
                self.current_session.get('final_authors_count'),
                self.current_session.get('final_authors_display'),
                self.current_session['confidence_score'],
                self.current_session.get('processing_time_ms'),
                self.current_session['has_wire_service'],
                self.current_session['has_email'],
                self.current_session['has_title'],
                self.current_session['has_organization'],
                self.current_session['source_name_removed'],
                self.current_session['duplicates_removed_count'],
                self.current_session.get('likely_valid_authors'),
                self.current_session.get('likely_noise'),
                self.current_session.get('requires_manual_review'),
                self.current_session.get('cleaning_errors'),
                self.current_session.get('parsing_warnings')
            ))
            
            # Insert transformation steps
            for step in self.transformation_steps:
                cursor.execute("""
                    INSERT INTO byline_transformation_steps (
                        id, telemetry_id, step_number, step_name, input_text,
                        output_text, transformation_type, removed_content,
                        added_content, confidence_delta, processing_time_ms,
                        notes, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    step['id'],
                    step['telemetry_id'],
                    step['step_number'],
                    step['step_name'],
                    step['input_text'],
                    step['output_text'],
                    step['transformation_type'],
                    step.get('removed_content'),
                    step.get('added_content'),
                    step['confidence_delta'],
                    step['processing_time_ms'],
                    step.get('notes'),
                    step['timestamp']
                ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"Warning: Failed to store telemetry data: {e}")
            # Don't fail the cleaning process due to telemetry issues
            
    def get_session_summary(self) -> Optional[Dict[str, Any]]:
        """Get a summary of the current cleaning session."""
        if not self.current_session:
            return None
            
        return {
            'telemetry_id': self.current_session['telemetry_id'],
            'raw_byline': self.current_session['raw_byline'],
            'steps_completed': self.step_counter,
            'confidence_score': self.current_session['confidence_score'],
            'has_errors': len(self.current_session['cleaning_errors']) > 0,
            'has_warnings': len(self.current_session['parsing_warnings']) > 0
        }


# Global telemetry instance for easy use
telemetry = BylineCleaningTelemetry()