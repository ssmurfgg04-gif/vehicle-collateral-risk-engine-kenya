"""
Loan Stacking Fraud Detector — Kenya Vehicle Collateral Risk Engine

This is the REAL fraud signal:
  - Same plate appears at 2+ lenders within a 14-day window
  - Same plate moves from bank repossession → auctioneer sale
  - Same plate appears at multiple auctioneers simultaneously

Architecture:
  1. Scrape all sources → save as timestamped snapshot
  2. Compare with previous snapshots to detect NEW appearances
  3. Flag plates that:
     a. Appear at 2+ different source types (bank + auctioneer)
     b. Appear at 2+ lenders within 14 days
     c. Disappear from one source and appear at another (moved)
  4. Generate fraud labels with evidence
  5. Train model on REAL fraud labels only

Usage:
    python loan_stacking_detector.py                    # Run detection on current data
    python loan_stacking_detector.py --scrape-first     # Scrape then detect
    python loan_stacking_detector.py --history          # Show full detection history
"""

import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional

import structlog

logger = structlog.get_logger("loan_stacking_detector")

DB_PATH = "/home/z/my-project/data/ingestion_queue.db"
SNAPSHOTS_DIR = "/home/z/my-project/data/plate_snapshots"
FRAUD_CASES_PATH = "/home/z/my-project/data/fraud_cases.json"

# ─── Snapshot Management ──────────────────────────────────────────────

def save_snapshot(vehicles: List[Dict], timestamp: str = None):
    """Save a timestamped snapshot of all plates by source."""
    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
    
    if not timestamp:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    
    # Group by source
    by_source: Dict[str, List[Dict]] = defaultdict(list)
    for v in vehicles:
        by_source[v.get("source", "unknown")].append(v)
    
    snapshot = {
        "timestamp": timestamp,
        "total_vehicles": len(vehicles),
        "total_unique_plates": len(set(v.get("normalized_plate", "") for v in vehicles)),
        "sources": {src: {
            "vehicle_count": len(vehicles_list),
            "plates": [v.get("normalized_plate", "") for v in vehicles_list],
        } for src, vehicles_list in by_source.items()},
    }
    
    path = os.path.join(SNAPSHOTS_DIR, f"snapshot_{timestamp}.json")
    with open(path, "w") as f:
        json.dump(snapshot, f, indent=2, default=str)
    
    logger.info("snapshot_saved", path=path, vehicles=len(vehicles))
    return path


def load_snapshots() -> List[Dict]:
    """Load all snapshots ordered by timestamp."""
    if not os.path.exists(SNAPSHOTS_DIR):
        return []
    
    snapshots = []
    for fname in sorted(os.listdir(SNAPSHOTS_DIR)):
        if fname.startswith("snapshot_") and fname.endswith(".json"):
            path = os.path.join(SNAPSHOTS_DIR, fname)
            with open(path) as f:
                snapshots.append(json.load(f))
    
    return snapshots


# ─── Plate Tracking Database ──────────────────────────────────────────

class PlateTracker:
    """SQLite-backed plate appearance tracker for time-series fraud detection."""
    
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_tables()
    
    def _ensure_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS plate_appearances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                normalized_plate TEXT NOT NULL,
                source TEXT NOT NULL,
                source_name TEXT,
                listing_type TEXT,
                make TEXT,
                model TEXT,
                reserve_price_kes INTEGER,
                listing_url TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                still_active INTEGER DEFAULT 1,
                UNIQUE(normalized_plate, source)
            );
            
            CREATE TABLE IF NOT EXISTS fraud_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                normalized_plate TEXT NOT NULL,
                fraud_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                sources TEXT NOT NULL,
                evidence TEXT,
                first_detected_at TEXT NOT NULL,
                last_updated_at TEXT NOT NULL,
                status TEXT DEFAULT 'ACTIVE'
            );
            
            CREATE INDEX IF NOT EXISTS idx_plate ON plate_appearances(normalized_plate);
            CREATE INDEX IF NOT EXISTS idx_source ON plate_appearances(source);
            CREATE INDEX IF NOT EXISTS idx_fraud_plate ON fraud_cases(normalized_plate);
        """)
        self.conn.commit()
    
    def update_appearances(self, vehicles: List[Dict]):
        """Update plate appearances from a fresh scrape."""
        now = datetime.now(timezone.utc).isoformat()
        
        # Mark all existing appearances as inactive
        self.conn.execute("UPDATE plate_appearances SET still_active = 0")
        
        inserted = 0
        updated = 0
        
        for v in vehicles:
            plate = v.get("normalized_plate", "")
            source = v.get("source", "")
            
            if not plate or not source:
                continue
            
            # Check if this plate+source already exists
            existing = self.conn.execute(
                "SELECT id, first_seen_at FROM plate_appearances WHERE normalized_plate = ? AND source = ?",
                (plate, source)
            ).fetchone()
            
            if existing:
                # Update: keep first_seen_at, update last_seen_at, mark active
                self.conn.execute(
                    "UPDATE plate_appearances SET last_seen_at = ?, still_active = 1, make = ?, model = ?, reserve_price_kes = ?, listing_url = ? WHERE id = ?",
                    (now, v.get("make", ""), v.get("model", ""), v.get("reserve_price_kes"), v.get("listing_url", ""), existing[0])
                )
                updated += 1
            else:
                # New appearance
                self.conn.execute(
                    """INSERT INTO plate_appearances 
                    (normalized_plate, source, source_name, listing_type, make, model, reserve_price_kes, listing_url, first_seen_at, last_seen_at, still_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                    (plate, source, v.get("source_name", source), v.get("listing_type", ""),
                     v.get("make", ""), v.get("model", ""), v.get("reserve_price_kes"),
                     v.get("listing_url", ""), now, now)
                )
                inserted += 1
        
        self.conn.commit()
        logger.info("appearances_updated", inserted=inserted, updated=updated)
        return inserted, updated
    
    def detect_fraud(self) -> List[Dict]:
        """Detect loan stacking fraud — same plate at 2+ lenders."""
        fraud_cases = []
        
        # Get all plates with multiple source appearances
        cursor = self.conn.execute("""
            SELECT normalized_plate, 
                   GROUP_CONCAT(source) as sources,
                   GROUP_CONCAT(source_name) as source_names,
                   GROUP_CONCAT(listing_type) as listing_types,
                   GROUP_CONCAT(make) as makes,
                   COUNT(DISTINCT source) as source_count,
                   MIN(first_seen_at) as first_seen,
                   MAX(last_seen_at) as last_seen
            FROM plate_appearances
            WHERE still_active = 1
            GROUP BY normalized_plate
            HAVING COUNT(DISTINCT source) >= 2
            ORDER BY source_count DESC
        """)
        
        for row in cursor:
            plate, sources_str, source_names_str, listing_types_str, makes_str, source_count, first_seen, last_seen = row
            
            sources = sources_str.split(",") if sources_str else []
            source_names = source_names_str.split(",") if source_names_str else []
            listing_types = listing_types_str.split(",") if listing_types_str else []
            makes_list = makes_str.split(",") if makes_str else []
            
            # Determine fraud type and severity
            source_set = set(sources)
            bank_sources = source_set & {"family_bank", "coop_bank", "equity_bank", "kcb_bank", "ncba_bank", "stanbic_bank", "dtb_bank"}
            auctioneer_sources = source_set & {"garam", "keysian", "phillips", "westminster", "mogo", "bank_repossessed"}
            govt_sources = source_set & {"kenya_gazette", "kra_disposals"}
            
            fraud_type = "CROSS_LENDER_OVERLAP"
            severity = "MEDIUM"
            description = ""
            
            if bank_sources and auctioneer_sources:
                fraud_type = "BANK_TO_AUCTIONEEER"
                severity = "HIGH"
                description = f"Plate {plate} listed at bank ({', '.join(bank_sources)}) AND auctioneer ({', '.join(auctioneer_sources)}). Possible double-pledging or forced sale without discharge."
            elif len(bank_sources) >= 2:
                fraud_type = "MULTI_BANK_PLEDGE"
                severity = "CRITICAL"
                description = f"Plate {plate} pledged at {len(bank_sources)} banks: {', '.join(bank_sources)}. Classic loan stacking — same collateral, multiple loans."
            elif len(auctioneer_sources) >= 2:
                fraud_type = "MULTI_AUCTIONEEER_LISTING"
                severity = "HIGH"
                description = f"Plate {plate} listed at {len(auctioneer_sources)} auctioneers: {', '.join(auctioneer_sources)}. Same vehicle being sold through multiple channels."
            elif govt_sources and bank_sources:
                fraud_type = "GOVT_VEHICLE_BANK_PLEDGE"
                severity = "CRITICAL"
                description = f"Government vehicle {plate} pledged at bank. Govt asset used as private collateral — major fraud."
            else:
                description = f"Plate {plate} found at {source_count} sources: {', '.join(source_names)}"
            
            # Check time window
            try:
                first_dt = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
                last_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                days_apart = (last_dt - first_dt).days
            except:
                days_apart = 0
            
            if days_apart <= 14:
                severity = "CRITICAL"  # Within 14-day window = active fraud
            
            case = {
                "normalized_plate": plate,
                "fraud_type": fraud_type,
                "severity": severity,
                "source_count": source_count,
                "sources": sources,
                "source_names": source_names,
                "listing_types": listing_types,
                "makes": makes_list,
                "first_seen": first_seen,
                "last_seen": last_seen,
                "days_apart": days_apart,
                "description": description,
                "detected_at": datetime.now(timezone.utc).isoformat(),
            }
            
            fraud_cases.append(case)
            
            # Save to database
            self.conn.execute(
                """INSERT OR REPLACE INTO fraud_cases 
                (normalized_plate, fraud_type, severity, sources, evidence, first_detected_at, last_updated_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE')""",
                (plate, fraud_type, severity, sources_str,
                 json.dumps(case, default=str),
                 datetime.now(timezone.utc).isoformat(),
                 datetime.now(timezone.utc).isoformat())
            )
        
        self.conn.commit()
        return fraud_cases
    
    def get_all_vehicles(self) -> List[Dict]:
        """Get all vehicles from the ingestion queue."""
        cursor = self.conn.execute(
            "SELECT payload, source FROM ingestion_queue"
        )
        vehicles = []
        for row in cursor:
            try:
                data = json.loads(row[0])
                data["source"] = row[1]
                vehicles.append(data)
            except:
                pass
        return vehicles
    
    def get_appearance_stats(self) -> Dict:
        """Get statistics about plate appearances."""
        stats = {}
        
        stats["total_appearances"] = self.conn.execute(
            "SELECT COUNT(*) FROM plate_appearances"
        ).fetchone()[0]
        
        stats["unique_plates"] = self.conn.execute(
            "SELECT COUNT(DISTINCT normalized_plate) FROM plate_appearances"
        ).fetchone()[0]
        
        stats["active_appearances"] = self.conn.execute(
            "SELECT COUNT(*) FROM plate_appearances WHERE still_active = 1"
        ).fetchone()[0]
        
        stats["multi_source_plates"] = self.conn.execute("""
            SELECT COUNT(*) FROM (
                SELECT normalized_plate FROM plate_appearances 
                WHERE still_active = 1 
                GROUP BY normalized_plate 
                HAVING COUNT(DISTINCT source) >= 2
            )
        """).fetchone()[0]
        
        stats["sources"] = dict(self.conn.execute(
            "SELECT source, COUNT(*) FROM plate_appearances WHERE still_active = 1 GROUP BY source ORDER BY COUNT(*) DESC"
        ).fetchall())
        
        stats["fraud_cases"] = self.conn.execute(
            "SELECT COUNT(*) FROM fraud_cases WHERE status = 'ACTIVE'"
        ).fetchone()[0]
        
        return stats
    
    def close(self):
        self.conn.close()


# ─── Main Detection Pipeline ──────────────────────────────────────────

def run_detection(scrape_first: bool = False, show_history: bool = False):
    """Run the loan stacking fraud detection pipeline."""
    
    tracker = PlateTracker()
    
    if show_history:
        snapshots = load_snapshots()
        if snapshots:
            print(f"\n{'═' * 70}")
            print(f" Detection History ({len(snapshots)} snapshots)")
            print(f"{'═' * 70}")
            for snap in snapshots:
                print(f"  {snap['timestamp']}: {snap['total_unique_plates']} plates from {len(snap['sources'])} sources")
                for src, info in snap['sources'].items():
                    print(f"    {src}: {info['vehicle_count']} vehicles")
        else:
            print("No snapshots found yet.")
        tracker.close()
        return
    
    # Get vehicles from queue
    vehicles = tracker.get_all_vehicles()
    
    if not vehicles:
        print("No vehicles in queue. Run the scraper first.")
        tracker.close()
        return
    
    # Update plate appearances
    print(f"\n{'═' * 70}")
    print(f" Loan Stacking Fraud Detector")
    print(f"{'═' * 70}")
    print(f"  Vehicles in queue: {len(vehicles)}")
    
    inserted, updated = tracker.update_appearances(vehicles)
    print(f"  New appearances: {inserted}")
    print(f"  Updated appearances: {updated}")
    
    # Save snapshot
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    save_snapshot(vehicles, timestamp)
    
    # Detect fraud
    fraud_cases = tracker.detect_fraud()
    
    # Stats
    stats = tracker.get_appearance_stats()
    
    print(f"\n{'═' * 70}")
    print(f" Plate Appearance Stats")
    print(f"{'═' * 70}")
    print(f"  Total appearances: {stats['total_appearances']}")
    print(f"  Unique plates: {stats['unique_plates']}")
    print(f"  Active appearances: {stats['active_appearances']}")
    print(f"  Multi-source plates: {stats['multi_source_plates']}")
    print(f"  Active fraud cases: {stats['fraud_cases']}")
    print(f"\n  Per-source active plates:")
    for src, count in stats['sources'].items():
        print(f"    {src:30s} {count:4d}")
    
    # Fraud results
    print(f"\n{'═' * 70}")
    print(f" Fraud Detection Results")
    print(f"{'═' * 70}")
    
    if fraud_cases:
        print(f"\n  ⚠ FOUND {len(fraud_cases)} FRAUD CASES!")
        print(f"\n  {'Plate':12s} {'Type':25s} {'Severity':10s} {'Sources':30s} {'Days':5s}")
        print(f"  {'─' * 12} {'─' * 25} {'─' * 10} {'─' * 30} {'─' * 5}")
        
        for case in sorted(fraud_cases, key=lambda x: (
            {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}.get(x["severity"], 3),
            -x["source_count"]
        )):
            print(f"  {case['normalized_plate']:12s} {case['fraud_type']:25s} {case['severity']:10s} {','.join(case['sources'])[:30]:30s} {case['days_apart']:5d}")
        
        print(f"\n  Details:")
        for case in fraud_cases[:10]:
            print(f"\n    [{case['severity']}] {case['normalized_plate']}")
            print(f"    {case['description']}")
            if case.get('makes'):
                print(f"    Makes: {', '.join(m for m in case['makes'] if m)}")
    else:
        print(f"\n  ❌ No cross-lender overlap detected yet.")
        print(f"\n  Why:")
        print(f"    • Current data has {stats['unique_plates']} unique plates across {len(stats['sources'])} sources")
        print(f"    • Each plate only appears at ONE source")
        print(f"    • Need TIME-SERIES data: scrape daily to catch plates moving between lenders")
        print(f"\n  What creates overlap:")
        print(f"    1. Bank repossesses vehicle → sends to auctioneer → plate appears at BOTH")
        print(f"    2. Vehicle pledged at 2 banks simultaneously → loan stacking fraud")
        print(f"    3. Same plate at 2 auctioneers → double-selling")
        print(f"\n  Next steps:")
        print(f"    • Set up 6-hour cron scraping → build time-series data")
        print(f"    • Each scrape compares with previous → detects NEW appearances")
        print(f"    • Overlap emerges naturally as vehicles move through the system")
    
    # Save fraud cases
    with open(FRAUD_CASES_PATH, "w") as f:
        json.dump(fraud_cases, f, indent=2, default=str)
    print(f"\n  Fraud cases saved to: {FRAUD_CASES_PATH}")
    
    print(f"{'═' * 70}\n")
    
    tracker.close()
    return fraud_cases


# ─── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Loan Stacking Fraud Detector")
    parser.add_argument("--scrape-first", action="store_true", help="Scrape before detecting")
    parser.add_argument("--history", action="store_true", help="Show detection history")
    args = parser.parse_args()
    
    if args.scrape_first:
        # Run scraper first
        import asyncio
        from real_vehicle_scraper import run_pipeline
        asyncio.run(run_pipeline())
    
    run_detection(scrape_first=args.scrape_first, show_history=args.history)
