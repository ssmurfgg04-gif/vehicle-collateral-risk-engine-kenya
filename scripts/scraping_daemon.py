"""
Scraping Daemon — Runs every 6 hours using APScheduler.

Usage:
    python scraping_daemon.py          # Start daemon (runs forever)
    python scraping_daemon.py --once   # Run once and exit
    python scraping_daemon.py --test   # Run with 1-minute interval for testing
"""

import argparse
import asyncio
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone

SOURCES = "family_bank,coop_bank,garam,keysian,phillips,westminster,mogo"
SCRIPTS_DIR = "/home/z/my-project/scripts"
LOGS_DIR = "/home/z/my-project/logs"

os.makedirs(LOGS_DIR, exist_ok=True)

def run_scrape_cycle():
    """Run one scrape + detect cycle."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    print(f"\n{'═' * 60}")
    print(f" Scrape cycle: {timestamp}")
    print(f"{'═' * 60}")
    
    # Run scraper
    print("▶ Scraping all sources...")
    result = subprocess.run(
        [sys.executable, f"{SCRIPTS_DIR}/real_vehicle_scraper.py",
         "--sources", SOURCES],
        capture_output=True, text=True, timeout=300
    )
    print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
    if result.returncode != 0:
        print(f"⚠ Scraper error: {result.stderr[-500:]}")
    
    # Run fraud detection
    print("▶ Running fraud detection...")
    result = subprocess.run(
        [sys.executable, f"{SCRIPTS_DIR}/loan_stacking_detector.py"],
        capture_output=True, text=True, timeout=60
    )
    print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
    
    print(f"✓ Cycle complete at {datetime.now(timezone.utc).isoformat()}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--test", action="store_true", help="1-minute interval for testing")
    args = parser.parse_args()
    
    if args.once:
        run_scrape_cycle()
        return
    
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError:
        # Fallback to simple loop
        print("APScheduler not available, using simple loop...")
        interval = 60 if args.test else 21600  # 1 min test, 6 hours production
        while True:
            run_scrape_cycle()
            print(f"Sleeping {interval}s until next cycle...")
            import time
            time.sleep(interval)
        return
    
    interval_minutes = 1 if args.test else 360  # 1 min test, 6 hours production
    
    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_scrape_cycle,
        IntervalTrigger(minutes=interval_minutes),
        id='scrape_cycle',
        name='Kenya Vehicle Scrape Cycle',
        misfire_grace_time=300
    )
    
    print(f"Starting scraping daemon (interval: {interval_minutes} minutes)")
    print("Press Ctrl+C to stop")
    
    # Run first cycle immediately
    run_scrape_cycle()
    
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("Daemon stopped.")

if __name__ == "__main__":
    main()
