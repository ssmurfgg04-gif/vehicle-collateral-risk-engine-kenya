#!/usr/bin/env python3
"""
Autonomous ingestion scheduler - runs ingestion at fixed times daily.
Since crontab is not available, this uses Python's sched module.

Runs at 6AM, 12PM, 6PM EAT (3AM, 9AM, 3PM UTC).
Also runs immediately on startup to ensure data is fresh.
"""

import sched
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

EAT = timezone(timedelta(hours=3))
SCHEDULE_HOURS_UTC = [3, 9, 15]  # 6AM, 12PM, 6PM EAT
SCRIPT = "/home/z/my-project/scripts/cron_ingest.sh"

def run_ingestion():
    """Run the ingestion script."""
    now = datetime.now(timezone.utc)
    print(f"[{now.isoformat()}] Running autonomous ingestion...")
    try:
        result = subprocess.run(
            ["bash", SCRIPT],
            capture_output=True, text=True, timeout=600,
        )
        print(f"  Return code: {result.returncode}")
        if result.returncode != 0:
            print(f"  Error: {result.stderr[-500:]}")
    except Exception as e:
        print(f"  Failed: {e}")

def schedule_next(scheduler):
    """Schedule the next ingestion run."""
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    next_run = None
    for hour in SCHEDULE_HOURS_UTC:
        candidate = today + timedelta(hours=hour)
        if candidate > now:
            next_run = candidate
            break
    
    if next_run is None:
        # Schedule for tomorrow's first slot
        next_run = today + timedelta(days=1, hours=SCHEDULE_HOURS_UTC[0])
    
    delay = (next_run - now).total_seconds()
    print(f"  Next ingestion at {next_run.isoformat()} (in {delay/3600:.1f} hours)")
    scheduler.enter(delay, 1, run_and_reschedule, (scheduler,))

def run_and_reschedule(scheduler):
    """Run ingestion and schedule next."""
    run_ingestion()
    schedule_next(scheduler)

def main():
    print("=" * 50)
    print(" Autonomous Ingestion Scheduler")
    print(f" Schedule: 6AM, 12PM, 6PM EAT daily")
    print("=" * 50)
    
    # Run immediately on startup
    print("\n[Initial] Running ingestion immediately...")
    run_ingestion()
    
    # Set up recurring schedule
    scheduler = sched.scheduler(time.time, time.sleep)
    schedule_next(scheduler)
    
    print("\nScheduler running. Press Ctrl+C to stop.")
    try:
        scheduler.run()
    except KeyboardInterrupt:
        print("\nScheduler stopped.")

if __name__ == "__main__":
    main()
