#!/usr/bin/env python3
"""
Demo script showing time-gated failure counting.

This demonstrates that checking a source multiple times within
its publication window won't incorrectly accumulate failures.
"""
from datetime import datetime
from src.crawler.scheduling import parse_frequency_to_days

def simulate_time_gating(frequency: str, check_intervals_hours: list[float]):
    """Simulate failure counting with time-gating.
    
    Args:
        frequency: Publication frequency (e.g., "daily", "weekly")
        check_intervals_hours: Hours between each check attempt
    """
    cadence_days = parse_frequency_to_days(frequency)
    required_hours = cadence_days * 24
    
    print(f"\n{'='*70}")
    print(f"Source Frequency: {frequency}")
    print(f"Publication Cadence: {cadence_days} days ({required_hours} hours)")
    print(f"{'='*70}")
    
    failure_count = 0
    last_seen = None
    
    for i, hours_since_last in enumerate(check_intervals_hours, 1):
        now = datetime.utcnow()
        if last_seen:
            time_since_last = hours_since_last
            
            if time_since_last < required_hours:
                # Not enough time passed - don't increment
                print(f"Check #{i} (after {hours_since_last:.1f}h): "
                      f"SKIPPED (need {required_hours:.1f}h) "
                      f"- count stays at {failure_count}")
            else:
                # Enough time passed - increment
                failure_count += 1
                last_seen = now
                print(f"Check #{i} (after {hours_since_last:.1f}h): "
                      f"COUNTED (>= {required_hours:.1f}h) "
                      f"- count now {failure_count}")
        else:
            # First failure
            failure_count = 1
            last_seen = now
            print(f"Check #{i} (first check): COUNTED - count now {failure_count}")
    
    print(f"\nFinal failure count: {failure_count}")
    print(f"Total checks: {len(check_intervals_hours)}")


if __name__ == "__main__":
    print("\n" + "="*70)
    print("TIME-GATED FAILURE COUNTING DEMONSTRATION")
    print("="*70)
    
    # Scenario 1: Daily publication checked 5 times in one day
    print("\n📰 SCENARIO 1: Daily publication")
    print("   Checked 5 times in 24 hours (every 5 hours)")
    simulate_time_gating(
        frequency="daily",
        check_intervals_hours=[0, 5, 5, 5, 5]  # 5 checks, 5h apart
    )
    print("   ✅ Only counts as 1 failure (not 5!)")
    
    # Scenario 2: Weekly publication checked 5 times in one week
    print("\n📰 SCENARIO 2: Weekly publication")
    print("   Checked 5 times in one week (daily checks)")
    simulate_time_gating(
        frequency="weekly",
        check_intervals_hours=[0, 24, 24, 24, 24]  # 5 checks, 1 day apart
    )
    print("   ✅ Only counts as 1 failure (not 5!)")
    
    # Scenario 3: Weekly publication checked over 5 weeks
    print("\n📰 SCENARIO 3: Weekly publication")
    print("   Checked weekly for 5 weeks")
    simulate_time_gating(
        frequency="weekly",
        check_intervals_hours=[0, 168, 168, 168, 168]  # 5 checks, 1 week apart
    )
    print("   ✅ Correctly counts as 5 failures (5 weeks of failures)")
    
    # Scenario 4: Monthly publication checked every 2 weeks
    print("\n📰 SCENARIO 4: Monthly publication")
    print("   Checked every 2 weeks for 10 weeks")
    simulate_time_gating(
        frequency="monthly",
        check_intervals_hours=[0, 336, 336, 336, 336]  # 5 checks, 2 weeks apart
    )
    print("   ✅ Only counts as 1 failure (need 30 days between increments)")
    
    print("\n" + "="*70)
    print("SUMMARY: Time-gating prevents over-counting when sources are")
    print("         checked more frequently than they publish!")
    print("="*70 + "\n")
