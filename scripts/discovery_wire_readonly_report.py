#!/usr/bin/env python3
"""
Read-only discovery-stage wire filter report for Dec 2025 & Jan 2026.
- Wire URL patterns availability (wire_services, if present)
- Daily candidate_links status='wire' counts
- Candidate_links status breakdown and wire percentage
"""

import sys
sys.path.insert(0, '/app')

from sqlalchemy import text
from src.models.database import DatabaseManager

def main():
    db = DatabaseManager()
    with db.get_session() as session:
        print("=== Wire URL Patterns (wire_services table) ===")
        try:
            count = session.execute(text("""
                SELECT COUNT(*) FROM wire_services
                WHERE active = true AND pattern_type = 'url'
            """)).scalar()
            print(f"Active wire URL patterns: {count}")
            sample = session.execute(text("""
                SELECT service_name, pattern, case_sensitive, priority
                FROM wire_services
                WHERE active = true AND pattern_type = 'url'
                ORDER BY priority, service_name
                LIMIT 10
            """)).fetchall()
            if sample:
                print("Sample patterns (top 10):")
                for svc, patt, cs, pri in sample:
                    cs_flag = 'cs' if cs else 'ci'
                    print(f"  [{pri:>2}] {svc} ({cs_flag}): {patt}")
            else:
                print("No sample patterns returned (table empty or filtered).")
        except Exception as e:
            print(f"wire_services query unavailable: {e}")

        print("\n=== Daily candidate_links status='wire' (2025-12-01..2026-01-31) ===")
        daily_wire = session.execute(text("""
            SELECT DATE(discovered_at) AS date, COUNT(*) AS wire_count
            FROM candidate_links
            WHERE status = 'wire'
              AND discovered_at >= '2025-12-01'
              AND discovered_at <  '2026-02-01'
            GROUP BY DATE(discovered_at)
            ORDER BY date
        """
        )).fetchall()
        for d, c in daily_wire:
            print(f"{d}: {c} wire URLs")

        print("\n=== Candidate Links Status Breakdown (2025-12..2026-01) ===")
        status_totals = session.execute(text("""
            SELECT status, COUNT(*) AS cnt
            FROM candidate_links
            WHERE discovered_at >= '2025-12-01'
              AND discovered_at <  '2026-02-01'
            GROUP BY status
            ORDER BY cnt DESC
        """
        )).fetchall()
        for status, cnt in status_totals:
            print(f"{status}: {cnt}")

        discovered_total = session.execute(text("""
            SELECT COUNT(*) FROM candidate_links
            WHERE discovered_at >= '2025-12-01' AND discovered_at < '2026-02-01'
        """
        )).scalar()
        wire_total = session.execute(text("""
            SELECT COUNT(*) FROM candidate_links
            WHERE status = 'wire'
              AND discovered_at >= '2025-12-01' AND discovered_at < '2026-02-01'
        """
        )).scalar()
        pct = (100.0 * wire_total / discovered_total) if discovered_total else 0.0
        print("\n=== Summary ===")
        print(f"Total discovered: {discovered_total}")
        print(f"Total wire-filtered at discovery: {wire_total}")
        print(f"Wire filter rate: {pct:.1f}% of discovered URLs")

if __name__ == '__main__':
    main()
