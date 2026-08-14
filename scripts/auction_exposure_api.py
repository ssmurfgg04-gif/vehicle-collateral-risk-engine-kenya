"""
Auction Exposure Detector — Kenya Vehicle Collateral Risk Engine

PRODUCT: We index repossessed and auction-listed vehicles from Kenyan sources.
         If a vehicle in your loan application has appeared at auction in the
         last 90 days, that's a red flag. Reject or investigate.

THIS IS NOT LOAN STACKING DETECTION.
  - Loan stacking = same plate pledged at 3 lenders simultaneously (BEFORE repossession)
  - We cannot detect that — we don't have MFI loan application data or eCitizen caveats
  - What we CAN detect: a vehicle is already in the repossession/auction pipeline
  - That's still valuable: don't lend against a vehicle that's already being auctioned

To detect REAL loan stacking, you would need:
  1. MFI loan origination API hooks (which plates are being pledged RIGHT NOW)
  2. eCitizen caveat/encumbrance data (registered interests on logbooks)
  3. NTSA logbook transfer history (recent ownership changes)
  None of these are publicly scrapable.

Usage:
    python auction_exposure_api.py                          # Check all plates
    python auction_exposure_api.py --plate KDA123J          # Check single plate
    python auction_exposure_api.py --serve                  # Start HTTP API server
"""

import json
import os
import sqlite3
import sys
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set

import structlog

logger = structlog.get_logger("auction_exposure")

DB_PATH = "/home/z/my-project/data/ingestion_queue.db"
EXPOSURE_DB_PATH = "/home/z/my-project/data/auction_exposure.db"

# ─── Lender Classification ────────────────────────────────────────────

# Banks that originate loans (the "demand side" — if we had their data)
LOAN_ORIGINATORS = {
    "family_bank", "coop_bank", "equity_bank", "kcb_bank",
    "ncba_bank", "stanbic_bank", "dtb_bank",
}

# Auctioneers that sell repossessed vehicles (the "supply side" — what we track)
AUCTION_SOURCES = {
    "garam", "keysian", "phillips", "westminster", "mogo",
    "bank_repossessed",
}

# Government sources (authoritative disposals)
GOVERNMENT_SOURCES = {
    "kenya_gazette", "kra_disposals",
}

# All sources we scrape = repossession/auction pipeline
# This is the AFTERMATH, not the crime.
ALL_SCRAPED_SOURCES = LOAN_ORIGINATORS | AUCTION_SOURCES | GOVERNMENT_SOURCES


# ─── Auction Exposure Database ────────────────────────────────────────

class AuctionExposureDB:
    """
    Database for tracking auction exposure.
    
    Key concept: A vehicle is "auction exposed" if it has appeared on any
    repossession/auction listing site. This means:
      - The vehicle has already been seized by a lender, OR
      - The vehicle is being sold through an auctioneer, OR
      - The vehicle was disposed by the government
    
    If an MFI is considering a loan application with this vehicle as collateral,
    and the vehicle is auction-exposed, they should REJECT or INVESTIGATE.
    """
    
    def __init__(self, db_path: str = EXPOSURE_DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_tables()
    
    def _ensure_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS auction_exposures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                normalized_plate TEXT NOT NULL,
                raw_plate TEXT,
                source TEXT NOT NULL,
                source_name TEXT,
                source_type TEXT NOT NULL,  -- 'bank_repossession', 'auctioneer', 'government'
                make TEXT,
                model TEXT,
                year INTEGER,
                reserve_price_kes INTEGER,
                listing_type TEXT,
                listing_url TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                still_active INTEGER DEFAULT 1,
                days_listed INTEGER DEFAULT 0,
                UNIQUE(normalized_plate, source)
            );
            
            CREATE TABLE IF NOT EXISTS plate_summary (
                normalized_plate TEXT PRIMARY KEY,
                exposure_count INTEGER DEFAULT 0,
                source_count INTEGER DEFAULT 0,
                source_types TEXT,           -- JSON array of source types
                sources TEXT,                -- JSON array of source IDs
                first_seen_at TEXT,
                last_seen_at TEXT,
                max_price_kes INTEGER,
                is_currently_active INTEGER DEFAULT 1,
                risk_level TEXT DEFAULT 'LOW',     -- LOW, MEDIUM, HIGH, CRITICAL
                risk_reasons TEXT                    -- JSON array of risk reasons
            );
            
            CREATE INDEX IF NOT EXISTS idx_exposure_plate ON auction_exposures(normalized_plate);
            CREATE INDEX IF NOT EXISTS idx_exposure_active ON auction_exposures(still_active);
            CREATE INDEX IF NOT EXISTS idx_summary_risk ON plate_summary(risk_level);
        """)
        self.conn.commit()
    
    def update_from_queue(self):
        """Load vehicles from the ingestion queue and update exposures."""
        queue = sqlite3.connect(DB_PATH)
        cursor = queue.execute(
            "SELECT payload, source FROM ingestion_queue"
        )
        
        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        updated = 0
        
        for row in cursor:
            try:
                data = json.loads(row[0])
            except:
                continue
            
            plate = data.get("normalized_plate", "")
            source = row[1]
            
            if not plate or not source:
                continue
            
            # Classify source type
            if source in LOAN_ORIGINATORS:
                source_type = "bank_repossession"
            elif source in AUCTION_SOURCES:
                source_type = "auctioneer"
            elif source in GOVERNMENT_SOURCES:
                source_type = "government"
            else:
                source_type = "unknown"
            
            # Check if already exists
            existing = self.conn.execute(
                "SELECT id, first_seen_at FROM auction_exposures WHERE normalized_plate = ? AND source = ?",
                (plate, source)
            ).fetchone()
            
            if existing:
                self.conn.execute(
                    """UPDATE auction_exposures SET 
                    last_seen_at = ?, still_active = 1, 
                    make = ?, model = ?, year = ?, reserve_price_kes = ?, listing_url = ?
                    WHERE id = ?""",
                    (now, data.get("make", ""), data.get("model", ""), data.get("year", 0),
                     data.get("reserve_price_kes"), data.get("listing_url", ""), existing[0])
                )
                updated += 1
            else:
                self.conn.execute(
                    """INSERT INTO auction_exposures 
                    (normalized_plate, raw_plate, source, source_name, source_type,
                     make, model, year, reserve_price_kes, listing_type, listing_url,
                     first_seen_at, last_seen_at, still_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                    (plate, data.get("raw_plate", plate), source, data.get("source_name", source),
                     source_type, data.get("make", ""), data.get("model", ""), data.get("year", 0),
                     data.get("reserve_price_kes"), data.get("listing_type", ""),
                     data.get("listing_url", ""), now, now)
                )
                inserted += 1
        
        queue.close()
        
        # Mark stale entries as inactive
        self.conn.execute(
            "UPDATE auction_exposures SET still_active = 0 WHERE last_seen_at < ?",
            ((datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),)
        )
        
        self.conn.commit()
        self._update_summaries()
        
        logger.info("exposures_updated", inserted=inserted, updated=updated)
        return inserted, updated
    
    def _update_summaries(self):
        """Update plate summary table with risk levels."""
        now = datetime.now(timezone.utc)
        
        # Clear old summaries
        self.conn.execute("DELETE FROM plate_summary")
        
        # Build new summaries
        cursor = self.conn.execute("""
            SELECT normalized_plate,
                   COUNT(*) as exposure_count,
                   COUNT(DISTINCT source) as source_count,
                   GROUP_CONCAT(DISTINCT source_type) as source_types,
                   GROUP_CONCAT(DISTINCT source) as sources,
                   MIN(first_seen_at) as first_seen,
                   MAX(last_seen_at) as last_seen,
                   MAX(reserve_price_kes) as max_price,
                   SUM(still_active) as active_count
            FROM auction_exposures
            GROUP BY normalized_plate
        """)
        
        for row in cursor:
            plate, exp_count, src_count, src_types_str, sources_str, first_seen, last_seen, max_price, active_count = row
            
            src_types = src_types_str.split(",") if src_types_str else []
            sources = sources_str.split(",") if sources_str else []
            
            # ─── Risk Assessment ──────────────────────────────────────
            # This is NOT fraud detection. This is auction exposure risk.
            # 
            # HIGH risk: plate is currently active at auctioneer (for sale NOW)
            # MEDIUM risk: plate was at auction in last 30 days
            # LOW risk: plate was at auction 30+ days ago (may have been sold)
            # CRITICAL: plate at bank repossession AND auctioneer simultaneously
            #           (this is normal pipeline, NOT fraud — but worth flagging)
            
            risk_level = "LOW"
            risk_reasons = []
            
            # Currently active at auctioneer = HIGH risk for new loans
            auctioneer_active = any(s in AUCTION_SOURCES for s in sources) and active_count > 0
            if auctioneer_active:
                risk_level = "HIGH"
                risk_reasons.append("Vehicle currently listed at auctioneer — do not accept as collateral")
            
            # At bank repossession AND auctioneer simultaneously
            bank_sources = [s for s in sources if s in LOAN_ORIGINATORS]
            auctioneer_sources = [s for s in sources if s in AUCTION_SOURCES]
            if bank_sources and auctioneer_sources and active_count > 0:
                risk_level = "CRITICAL"
                risk_reasons.append(f"Vehicle in repossession pipeline: bank ({', '.join(bank_sources)}) → auctioneer ({', '.join(auctioneer_sources)})")
            
            # Government disposal = medium risk (may lack proper discharge)
            govt_sources = [s for s in sources if s in GOVERNMENT_SOURCES]
            if govt_sources:
                if risk_level == "LOW":
                    risk_level = "MEDIUM"
                risk_reasons.append(f"Government disposal — may lack proper discharge certificate ({', '.join(govt_sources)})")
            
            # Multiple auctioneers = medium risk
            if len(auctioneer_sources) >= 2:
                if risk_level == "LOW":
                    risk_level = "MEDIUM"
                risk_reasons.append(f"Listed at {len(auctioneer_sources)} auctioneers: {', '.join(auctioneer_sources)}")
            
            # Time-based: recent exposure = higher risk
            try:
                last_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                days_since = (now - last_dt).days
                if days_since <= 7 and risk_level == "LOW":
                    risk_level = "MEDIUM"
                    risk_reasons.append(f"Recently at auction ({days_since} days ago)")
            except:
                pass
            
            if not risk_reasons:
                risk_reasons.append("Vehicle appeared in repossession/auction listings")
            
            self.conn.execute(
                """INSERT OR REPLACE INTO plate_summary 
                (normalized_plate, exposure_count, source_count, source_types, sources,
                 first_seen_at, last_seen_at, max_price_kes, is_currently_active,
                 risk_level, risk_reasons)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (plate, exp_count, src_count,
                 json.dumps(src_types), json.dumps(sources),
                 first_seen, last_seen, max_price, 1 if active_count > 0 else 0,
                 risk_level, json.dumps(risk_reasons))
            )
        
        self.conn.commit()
    
    def check_plate(self, plate: str) -> Optional[Dict]:
        """Check if a plate is auction-exposed. Returns exposure info or None."""
        # Normalize plate
        plate = plate.upper().replace(" ", "").replace("-", "")
        
        # Check summary
        row = self.conn.execute(
            "SELECT * FROM plate_summary WHERE normalized_plate = ?",
            (plate,)
        ).fetchone()
        
        if not row:
            return None
        
        cols = [d[0] for d in self.conn.execute(
            "SELECT * FROM plate_summary WHERE normalized_plate = ?", (plate,)
        ).description]
        
        result = dict(zip(cols, row))
        
        # Get detailed exposures
        details = []
        cursor = self.conn.execute(
            """SELECT source, source_name, source_type, make, model, year,
                      reserve_price_kes, listing_type, listing_url,
                      first_seen_at, last_seen_at, still_active
               FROM auction_exposures WHERE normalized_plate = ?
               ORDER BY last_seen_at DESC""",
            (plate,)
        )
        
        for d in cursor:
            details.append({
                "source": d[0],
                "source_name": d[1],
                "source_type": d[2],
                "make": d[3],
                "model": d[4],
                "year": d[5],
                "reserve_price_kes": d[6],
                "listing_type": d[7],
                "listing_url": d[8],
                "first_seen_at": d[9],
                "last_seen_at": d[10],
                "still_active": bool(d[11]),
            })
        
        result["exposures"] = details
        
        # Parse JSON fields
        try:
            result["source_types"] = json.loads(result.get("source_types", "[]"))
            result["sources"] = json.loads(result.get("sources", "[]"))
            result["risk_reasons"] = json.loads(result.get("risk_reasons", "[]"))
        except:
            pass
        
        return result
    
    def get_stats(self) -> Dict:
        """Get overall statistics."""
        stats = {}
        
        stats["total_plates"] = self.conn.execute(
            "SELECT COUNT(*) FROM plate_summary"
        ).fetchone()[0]
        
        stats["active_plates"] = self.conn.execute(
            "SELECT COUNT(*) FROM plate_summary WHERE is_currently_active = 1"
        ).fetchone()[0]
        
        stats["by_risk"] = dict(self.conn.execute(
            "SELECT risk_level, COUNT(*) FROM plate_summary GROUP BY risk_level ORDER BY COUNT(*) DESC"
        ).fetchall())
        
        stats["by_source_type"] = dict(self.conn.execute(
            "SELECT source_type, COUNT(*) FROM auction_exposures WHERE still_active = 1 GROUP BY source_type"
        ).fetchall())
        
        stats["by_source"] = dict(self.conn.execute(
            "SELECT source, COUNT(*) FROM auction_exposures WHERE still_active = 1 GROUP BY source ORDER BY COUNT(*) DESC"
        ).fetchall())
        
        return stats
    
    def close(self):
        self.conn.close()


# ─── HTTP API ─────────────────────────────────────────────────────────

def serve_api(host: str = "0.0.0.0", port: int = 8000):
    """Start HTTP API server for auction exposure checks."""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from urllib.parse import urlparse, parse_qs
    import threading
    
    db = AuctionExposureDB()
    
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            
            if parsed.path == "/check":
                # /check?plate=KDA123J
                params = parse_qs(parsed.query)
                plate = params.get("plate", [""])[0]
                
                if not plate:
                    self._json_response({"error": "Missing plate parameter. Usage: /check?plate=KDA123J"}, 400)
                    return
                
                result = db.check_plate(plate)
                
                if result:
                    self._json_response({
                        "plate": plate,
                        "auction_exposed": True,
                        "risk_level": result["risk_level"],
                        "risk_reasons": result["risk_reasons"],
                        "sources": result["sources"],
                        "exposure_count": result["exposure_count"],
                        "details": result["exposures"],
                        "recommendation": "REJECT" if result["risk_level"] in ("HIGH", "CRITICAL") else "INVESTIGATE" if result["risk_level"] == "MEDIUM" else "PROCEED_WITH_CAUTION",
                    })
                else:
                    self._json_response({
                        "plate": plate,
                        "auction_exposed": False,
                        "risk_level": "NONE",
                        "recommendation": "PROCEED",
                        "note": "Plate not found in repossession/auction database",
                    })
            
            elif parsed.path == "/stats":
                stats = db.get_stats()
                self._json_response(stats)
            
            elif parsed.path == "/health":
                self._json_response({"status": "ok", "product": "auction_exposure_detector"})
            
            else:
                self._json_response({
                    "endpoints": {
                        "/check?plate=XXX": "Check if a plate is auction-exposed",
                        "/stats": "Get overall statistics",
                        "/health": "Health check",
                    },
                    "product": "Kenya Vehicle Auction Exposure Detector",
                    "disclaimer": "This detects auction exposure, NOT loan stacking. Loan stacking requires MFI loan origination data.",
                })
        
        def _json_response(self, data, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data, indent=2, default=str).encode())
        
        def log_message(self, format, *args):
            pass  # Suppress request logs
    
    server = HTTPServer((host, port), Handler)
    print(f"\n{'═' * 70}")
    print(f" Auction Exposure API")
    print(f"{'═' * 70}")
    print(f"  Listening: http://{host}:{port}")
    print(f"  Endpoints:")
    print(f"    GET /check?plate=KDA123J  — Check if plate is auction-exposed")
    print(f"    GET /stats                 — Overall statistics")
    print(f"    GET /health                — Health check")
    print(f"\n  PRODUCT: Auction Exposure Detector")
    print(f"  NOT: Loan Stacking Detector")
    print(f"  We track repossessed/auction-listed vehicles.")
    print(f"  If your collateral appears here, it's already in the pipeline.")
    print(f"{'═' * 70}\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        db.close()


# ─── Main ─────────────────────────────────────────────────────────────

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Auction Exposure Detector — Kenya")
    parser.add_argument("--plate", default="", help="Check a single plate")
    parser.add_argument("--serve", action="store_true", help="Start HTTP API server")
    parser.add_argument("--port", type=int, default=8000, help="API port (default: 8000)")
    parser.add_argument("--stats", action="store_true", help="Show statistics")
    args = parser.parse_args()
    
    db = AuctionExposureDB()
    
    # Update from queue
    print("Updating auction exposures from queue...")
    inserted, updated = db.update_from_queue()
    print(f"  Inserted: {inserted}, Updated: {updated}")
    
    if args.plate:
        # Check single plate
        result = db.check_plate(args.plate)
        print(f"\n{'═' * 70}")
        print(f" Plate Check: {args.plate}")
        print(f"{'═' * 70}")
        
        if result:
            print(f"  Auction Exposed: YES")
            print(f"  Risk Level: {result['risk_level']}")
            print(f"  Sources: {result.get('sources', [])}")
            for reason in result.get("risk_reasons", []):
                print(f"  ⚠ {reason}")
            
            if result["risk_level"] in ("HIGH", "CRITICAL"):
                print(f"\n  → RECOMMENDATION: REJECT this vehicle as loan collateral")
            elif result["risk_level"] == "MEDIUM":
                print(f"\n  → RECOMMENDATION: INVESTIGATE before accepting as collateral")
            else:
                print(f"\n  → RECOMMENDATION: Proceed with caution")
            
            if result.get("exposures"):
                print(f"\n  Exposure Details:")
                for exp in result["exposures"]:
                    price_str = f"KES {exp['reserve_price_kes']:,}" if exp.get("reserve_price_kes") else "no price"
                    active = "ACTIVE" if exp.get("still_active") else "expired"
                    print(f"    {exp['source_name']:30s} {exp.get('make', ''):15s} {price_str:15s} [{active}]")
        else:
            print(f"  Auction Exposed: NO")
            print(f"  → This plate is NOT in our repossession/auction database")
            print(f"  → PROCEED: Vehicle has no known auction exposure")
        
        print(f"{'═' * 70}")
    
    elif args.stats:
        stats = db.get_stats()
        print(f"\n{'═' * 70}")
        print(f" Auction Exposure Statistics")
        print(f"{'═' * 70}")
        print(f"  Total plates tracked: {stats['total_plates']}")
        print(f"  Currently active: {stats['active_plates']}")
        print(f"\n  By Risk Level:")
        for level, count in stats.get("by_risk", {}).items():
            print(f"    {level:10s} {count:4d}")
        print(f"\n  By Source:")
        for source, count in stats.get("by_source", {}).items():
            print(f"    {source:30s} {count:4d}")
        print(f"{'═' * 70}")
    
    elif args.serve:
        db.close()
        serve_api(port=args.port)
        return
    
    else:
        # Default: show summary
        stats = db.get_stats()
        print(f"\n{'═' * 70}")
        print(f" Kenya Vehicle Auction Exposure Detector")
        print(f"{'═' * 70}")
        print(f"  Total plates: {stats['total_plates']}")
        print(f"  Active: {stats['active_plates']}")
        print(f"  By Risk: {stats.get('by_risk', {})}")
        print(f"\n  PRODUCT POSITIONING:")
        print(f"    We track repossessed and auction-listed vehicles.")
        print(f"    If your collateral appears in our database, it's already")
        print(f"    been flagged by another lender or is in auction.")
        print(f"    Reject or investigate.")
        print(f"\n  WHAT THIS IS NOT:")
        print(f"    This is NOT loan stacking detection.")
        print(f"    Loan stacking requires MFI loan origination data")
        print(f"    (which plates are being pledged as collateral RIGHT NOW).")
        print(f"    We only see the AFTERMATH (repossession/auction).")
        print(f"\n  TO DETECT REAL LOAN STACKING:")
        print(f"    1. MFI loan application API hooks")
        print(f"    2. eCitizen caveat/encumbrance data")
        print(f"    3. NTSA logbook transfer history")
        print(f"    None of these are publicly scrapable.")
        print(f"{'═' * 70}")
    
    db.close()


if __name__ == "__main__":
    main()
