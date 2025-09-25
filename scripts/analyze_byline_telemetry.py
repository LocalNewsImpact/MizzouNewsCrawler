#!/usr/bin/env python3
"""
Byline cleaning telemetry analysis and ML training data export tools.

This script provides comprehensive analysis of byline cleaning effectiveness
and exports datasets for ML model training.
"""

import json
import logging
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List

import pandas as pd


logger = logging.getLogger(__name__)

# Add the parent directory to the path to import src modules
sys.path.append(str(Path(__file__).parent.parent))

from src.config import DATABASE_URL


class BylineTelemetryAnalyzer:
    """Comprehensive analysis of byline cleaning telemetry data."""
    
    def __init__(self):
        """Initialize the analyzer."""
        # Convert DATABASE_URL to file path
        self.db_path = DATABASE_URL.replace('sqlite:///', '')
        
    def get_cleaning_summary(self, days: int = 7) -> Dict:
        """Get overall cleaning performance summary."""
        conn = sqlite3.connect(self.db_path)
        
        # Get date filter
        start_date = datetime.now() - timedelta(days=days)
        
        query = """
            SELECT 
                COUNT(*) as total_cleanings,
                AVG(confidence_score) as avg_confidence,
                AVG(processing_time_ms) as avg_processing_time,
                AVG(final_authors_count) as avg_authors_per_byline,
                SUM(CASE WHEN likely_valid_authors = 1 THEN 1 ELSE 0 END) as valid_results,
                SUM(CASE WHEN likely_noise = 1 THEN 1 ELSE 0 END) as noise_results,
                SUM(CASE WHEN requires_manual_review = 1 THEN 1 ELSE 0 END) as review_needed,
                SUM(CASE WHEN has_wire_service = 1 THEN 1 ELSE 0 END) as wire_services,
                SUM(CASE WHEN source_name_removed = 1 THEN 1 ELSE 0 END) as source_removals,
                SUM(duplicates_removed_count) as total_duplicates_removed,
                COUNT(DISTINCT source_name) as unique_sources
            FROM byline_cleaning_telemetry 
            WHERE extraction_timestamp > ?
        """
        
        cursor = conn.execute(query, (start_date,))
        result = cursor.fetchone()
        
        if result[0] == 0:  # No data
            return {"message": f"No cleaning data found for last {days} days"}
        
        summary = {
            "period_days": days,
            "total_cleanings": result[0],
            "avg_confidence_score": round(result[1] or 0, 3),
            "avg_processing_time_ms": round(result[2] or 0, 2),
            "avg_authors_per_byline": round(result[3] or 0, 2),
            "valid_results": result[4],
            "noise_results": result[5],
            "review_needed": result[6],
            "wire_services_detected": result[7],
            "source_names_removed": result[8],
            "total_duplicates_removed": result[9],
            "unique_sources": result[10],
            "success_rate": round((result[4] / result[0]) * 100, 1) if result[0] > 0 else 0,
            "noise_rate": round((result[5] / result[0]) * 100, 1) if result[0] > 0 else 0
        }
        
        conn.close()
        return summary
        
    def get_source_performance(self, limit: int = 20) -> List[Dict]:
        """Get cleaning performance by source."""
        conn = sqlite3.connect(self.db_path)
        
        query = """
            SELECT 
                source_name,
                COUNT(*) as cleaning_count,
                AVG(confidence_score) as avg_confidence,
                AVG(processing_time_ms) as avg_processing_time,
                AVG(final_authors_count) as avg_authors,
                SUM(CASE WHEN likely_valid_authors = 1 THEN 1 ELSE 0 END) as valid_count,
                SUM(CASE WHEN likely_noise = 1 THEN 1 ELSE 0 END) as noise_count,
                SUM(CASE WHEN requires_manual_review = 1 THEN 1 ELSE 0 END) as review_count,
                SUM(CASE WHEN source_name_removed = 1 THEN 1 ELSE 0 END) as removal_count,
                AVG(raw_byline_length) as avg_input_length
            FROM byline_cleaning_telemetry 
            WHERE source_name IS NOT NULL
            GROUP BY source_name
            ORDER BY cleaning_count DESC
            LIMIT ?
        """
        
        cursor = conn.execute(query, (limit,))
        results = cursor.fetchall()
        
        source_stats = []
        for row in results:
            total = row[1]
            source_stats.append({
                "source_name": row[0],
                "cleaning_count": total,
                "avg_confidence": round(row[2] or 0, 3),
                "avg_processing_time_ms": round(row[3] or 0, 2),
                "avg_authors": round(row[4] or 0, 2),
                "success_rate": round((row[5] / total) * 100, 1) if total > 0 else 0,
                "noise_rate": round((row[6] / total) * 100, 1) if total > 0 else 0,
                "review_rate": round((row[7] / total) * 100, 1) if total > 0 else 0,
                "source_removal_rate": round((row[8] / total) * 100, 1) if total > 0 else 0,
                "avg_input_length": round(row[9] or 0, 1)
            })
        
        conn.close()
        return source_stats
        
    def get_transformation_patterns(self, limit: int = 50) -> List[Dict]:
        """Get common transformation patterns for analysis."""
        conn = sqlite3.connect(self.db_path)
        
        query = """
            SELECT 
                bct.raw_byline,
                bct.final_authors_display,
                bct.source_name,
                bct.confidence_score,
                bct.final_authors_count,
                bct.cleaning_method,
                bct.likely_valid_authors,
                COUNT(*) as frequency
            FROM byline_cleaning_telemetry bct
            WHERE bct.raw_byline IS NOT NULL 
            AND bct.final_authors_display IS NOT NULL
            AND bct.raw_byline != bct.final_authors_display
            GROUP BY bct.raw_byline, bct.final_authors_display, bct.source_name
            ORDER BY frequency DESC, bct.confidence_score DESC
            LIMIT ?
        """
        
        cursor = conn.execute(query, (limit,))
        results = cursor.fetchall()
        
        patterns = []
        for row in results:
            patterns.append({
                "raw_byline": row[0],
                "cleaned_result": row[1],
                "source_name": row[2],
                "confidence_score": row[3],
                "authors_count": row[4],
                "cleaning_method": row[5],
                "likely_valid": bool(row[6]),
                "frequency": row[7]
            })
        
        conn.close()
        return patterns
        
    def export_ml_training_data(
        self, 
        output_file: str, 
        min_confidence: float = 0.3,
        include_features: bool = True
    ) -> Dict:
        """Export data suitable for ML training."""
        conn = sqlite3.connect(self.db_path)
        
        # Get training data with features
        query = """
            SELECT 
                bct.raw_byline,
                bct.final_authors_json,
                bct.source_name,
                bct.confidence_score,
                bct.raw_byline_length,
                bct.raw_byline_words,
                bct.final_authors_count,
                bct.has_wire_service,
                bct.has_email,
                bct.has_title,
                bct.has_organization,
                bct.source_name_removed,
                bct.duplicates_removed_count,
                bct.processing_time_ms,
                bct.likely_valid_authors,
                bct.likely_noise,
                bct.requires_manual_review,
                bct.cleaning_method
            FROM byline_cleaning_telemetry bct
            WHERE bct.confidence_score >= ?
            AND bct.raw_byline IS NOT NULL
            AND bct.final_authors_json IS NOT NULL
            ORDER BY bct.extraction_timestamp DESC
        """
        
        df = pd.read_sql_query(query, conn, params=(min_confidence,))
        
        if include_features:
            # Add engineered features
            df['input_length_category'] = pd.cut(
                df['raw_byline_length'], 
                bins=[0, 20, 50, 100, float('inf')], 
                labels=['short', 'medium', 'long', 'very_long']
            )
            
            df['words_per_author'] = df['raw_byline_words'] / (df['final_authors_count'] + 1)
            
            df['complexity_score'] = (
                df['raw_byline_length'] / 50 + 
                df['raw_byline_words'] / 10 +
                df['has_email'].astype(int) * 0.2 +
                df['has_organization'].astype(int) * 0.3
            )
            
            # Parse final authors JSON for analysis
            df['author_names'] = df['final_authors_json'].apply(
                lambda x: json.loads(x) if x else []
            )
            df['has_multiple_authors'] = df['author_names'].apply(len) > 1
            df['avg_name_length'] = df['author_names'].apply(
                lambda names: sum(len(name) for name in names) / len(names) if names else 0
            )
        
        # Export to CSV
        df.to_csv(output_file, index=False)
        
        conn.close()
        
        return {
            "records_exported": len(df),
            "output_file": output_file,
            "confidence_threshold": min_confidence,
            "columns": list(df.columns),
            "feature_engineering": include_features
        }
        
    def get_error_analysis(self) -> Dict:
        """Analyze cleaning errors and warnings."""
        conn = sqlite3.connect(self.db_path)
        
        # Get error statistics
        query = """
            SELECT 
                COUNT(*) as total_with_errors,
                cleaning_errors,
                parsing_warnings
            FROM byline_cleaning_telemetry 
            WHERE cleaning_errors != '[]' OR parsing_warnings != '[]'
        """
        
        cursor = conn.execute(query)
        results = cursor.fetchall()
        
        error_analysis = {
            "total_sessions_with_issues": 0,
            "common_errors": [],
            "common_warnings": [],
            "error_patterns": {}
        }
        
        all_errors = []
        all_warnings = []
        
        for row in results:
            error_analysis["total_sessions_with_issues"] += 1
            
            if row[1] and row[1] != '[]':
                try:
                    errors = json.loads(row[1])
                    all_errors.extend(
                        [err.get('message', '') for err in errors]
                    )
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.debug("Failed to parse telemetry errors: %s", exc)

            if row[2] and row[2] != '[]':
                try:
                    warnings = json.loads(row[2])
                    all_warnings.extend(
                        [warn.get('message', '') for warn in warnings]
                    )
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.debug("Failed to parse telemetry warnings: %s", exc)
        
        # Count error frequencies
        from collections import Counter
        error_counts = Counter(all_errors)
        warning_counts = Counter(all_warnings)
        
        error_analysis["common_errors"] = [
            {"message": msg, "count": count} 
            for msg, count in error_counts.most_common(10)
        ]
        error_analysis["common_warnings"] = [
            {"message": msg, "count": count} 
            for msg, count in warning_counts.most_common(10)
        ]
        
        conn.close()
        return error_analysis
        
    def generate_training_report(self, output_dir: str = "telemetry_reports") -> str:
        """Generate comprehensive training data report."""
        Path(output_dir).mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = f"{output_dir}/byline_training_report_{timestamp}.md"
        
        # Gather all analysis data
        summary = self.get_cleaning_summary(days=30)
        source_performance = self.get_source_performance(limit=10)
        patterns = self.get_transformation_patterns(limit=20)
        errors = self.get_error_analysis()
        
        # Generate report
        with open(report_file, 'w') as f:
            f.write("# Byline Cleaning Training Data Report\\n")
            f.write(f"Generated: {datetime.now().isoformat()}\\n\\n")
            
            f.write("## Executive Summary\\n")
            f.write(f"- **Total Cleanings (30 days)**: {summary.get('total_cleanings', 0):,}\\n")
            f.write(f"- **Success Rate**: {summary.get('success_rate', 0)}%\\n")
            f.write(f"- **Average Confidence**: {summary.get('avg_confidence_score', 0)}\\n")
            f.write(f"- **Unique Sources**: {summary.get('unique_sources', 0)}\\n\\n")
            
            f.write("## Performance Metrics\\n")
            f.write("| Metric | Value |\\n")
            f.write("|--------|-------|\\n")
            for key, value in summary.items():
                f.write(f"| {key.replace('_', ' ').title()} | {value} |\\n")
            f.write("\\n")
            
            f.write("## Top Sources by Volume\\n")
            f.write("| Source | Cleanings | Success Rate | Avg Confidence |\\n")
            f.write("|--------|-----------|--------------|----------------|\\n")
            for source in source_performance:
                f.write(
                    f"| {source['source_name']} | {source['cleaning_count']} | "
                    f"{source['success_rate']}% | {source['avg_confidence']} |\\n"
                )
            f.write("\\n")
            
            f.write("## Common Transformation Patterns\\n")
            for i, pattern in enumerate(patterns[:10], 1):
                f.write(f"### Pattern {i} (freq: {pattern['frequency']})\\n")
                f.write(f"**Input**: `{pattern['raw_byline']}`\\n")
                f.write(f"**Output**: `{pattern['cleaned_result']}`\\n")
                f.write(f"**Source**: {pattern['source_name']}\\n")
                f.write(f"**Confidence**: {pattern['confidence_score']}\\n\\n")
            
            f.write("## Error Analysis\\n")
            f.write(f"Sessions with issues: {errors['total_sessions_with_issues']}\\n\\n")
            
            if errors['common_errors']:
                f.write("### Most Common Errors\\n")
                for error in errors['common_errors']:
                    f.write(f"- {error['message']} ({error['count']} times)\\n")
                f.write("\\n")
                
            if errors['common_warnings']:
                f.write("### Most Common Warnings\\n")
                for warning in errors['common_warnings']:
                    f.write(f"- {warning['message']} ({warning['count']} times)\\n")
        
        return report_file


def main():
    """Main analysis interface."""
    if len(sys.argv) < 2:
        print("Usage: python byline_telemetry_analysis.py <command> [options]")
        print("Commands:")
        print("  summary [days]          - Show cleaning performance summary")
        print("  sources [limit]         - Show source performance stats") 
        print("  patterns [limit]        - Show transformation patterns")
        print("  export <file> [min_conf] - Export ML training data")
        print("  errors                  - Show error analysis")
        print("  report [output_dir]     - Generate comprehensive report")
        return
    
    analyzer = BylineTelemetryAnalyzer()
    command = sys.argv[1]
    
    if command == "summary":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        summary = analyzer.get_cleaning_summary(days)
        print(f"\\n📊 Byline Cleaning Summary ({days} days)")
        print("=" * 50)
        for key, value in summary.items():
            print(f"{key.replace('_', ' ').title()}: {value}")
            
    elif command == "sources":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        sources = analyzer.get_source_performance(limit)
        print(f"\\n🏢 Source Performance (Top {limit})")
        print("=" * 60)
        for source in sources:
            print(f"\\n{source['source_name']}")
            print(f"  Cleanings: {source['cleaning_count']}")
            print(f"  Success Rate: {source['success_rate']}%")
            print(f"  Avg Confidence: {source['avg_confidence']}")
            print(f"  Avg Processing Time: {source['avg_processing_time_ms']}ms")
            
    elif command == "patterns":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 50
        patterns = analyzer.get_transformation_patterns(limit)
        print(f"\\n🔄 Transformation Patterns (Top {limit})")
        print("=" * 70)
        for i, pattern in enumerate(patterns, 1):
            print(f"\\n{i}. Frequency: {pattern['frequency']}")
            print(f"   Input:  '{pattern['raw_byline']}'")
            print(f"   Output: '{pattern['cleaned_result']}'")
            print(f"   Source: {pattern['source_name']}")
            print(f"   Confidence: {pattern['confidence_score']}")
            
    elif command == "export":
        if len(sys.argv) < 3:
            print("Error: export command requires output filename")
            return
        output_file = sys.argv[2]
        min_confidence = float(sys.argv[3]) if len(sys.argv) > 3 else 0.3
        
        result = analyzer.export_ml_training_data(output_file, min_confidence)
        print("\\n💾 ML Training Data Export")
        print("=" * 40)
        for key, value in result.items():
            print(f"{key.replace('_', ' ').title()}: {value}")
            
    elif command == "errors":
        errors = analyzer.get_error_analysis()
        print("\\n⚠️  Error Analysis")
        print("=" * 30)
        print(f"Sessions with issues: {errors['total_sessions_with_issues']}")
        
        if errors['common_errors']:
            print("\\nMost Common Errors:")
            for error in errors['common_errors']:
                print(f"  - {error['message']} ({error['count']} times)")
                
        if errors['common_warnings']:
            print("\\nMost Common Warnings:")
            for warning in errors['common_warnings']:
                print(f"  - {warning['message']} ({warning['count']} times)")
                
    elif command == "report":
        output_dir = sys.argv[2] if len(sys.argv) > 2 else "telemetry_reports"
        report_file = analyzer.generate_training_report(output_dir)
        print("\\n📋 Comprehensive Report Generated")
        print("=" * 40)
        print(f"Report saved to: {report_file}")
        
    else:
        print(f"Unknown command: {command}")


if __name__ == "__main__":
    main()