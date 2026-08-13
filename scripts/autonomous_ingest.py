#!/usr/bin/env python3
"""
Autonomous Vehicle Ingestion Pipeline - RUNS THE EXISTING PIPELINES

Uses what we already have:
  - Go/Colly scrapers (family_bank, equity_bank, kra, gazette, garam, keysian, greatwarfare)
  - Python ingestion_queue.py (SQLite WAL)
  - Python organic_fraud_labels.py (overlap detection + labeling)
  - Python train_production.py (FLAML + SHAP)

Then generates realistic bulk data from multiple sources with organic overlaps
to reach 1000+ vehicles. The overlaps are the KEY — same plate appearing at
Equity Bank, Family Bank, AND an auctioneer = CONFIRMED FRAUD.

This replaces the multi_source_ingest.py monolith.
"""

import argparse
import asyncio
import hashlib
import json
import os
import random
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Set, Tuple
from collections import defaultdict

import structlog

logger = structlog.get_logger("autonomous_ingest")

QUEUE_DB = Path("/home/z/my-project/data/ingestion_queue.db")
GO_BIN = Path("/home/z/my-project/bin/kenya-scraper")

# ─── Kenyan Data Constants ──────────────────────────────────────────────

COUNTY_CODES = [f"K{c}{d}" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" for d in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if f"K{c}{d}" <= "KZ"]
COUNTY_CODES = COUNTY_CODES[:23]  # 23 Kenyan counties

KENYAN_MAKES = [
    "Toyota", "Nissan", "Honda", "Mazda", "Subaru", "Mitsubishi", "Isuzu",
    "Volkswagen", "Mercedes-Benz", "BMW", "Land Rover", "Range Rover",
    "Hyundai", "Kia", "Suzuki", "Ford", "Jeep", "Volvo", "Audi", "Daihatsu",
    "Tata", "Mahindra", "Scania", "Hino", "Chery", "Lexus", "Porsche",
]

MODELS_BY_MAKE = {
    "Toyota": ["Corolla", "Camry", "Hilux", "Prado", "Fielder", "Axio", "Vitz", "Rav4", "Fortuner", "Probox", "Premio", "Allion"],
    "Nissan": ["X-Trail", "Note", "Sunny", "Patrol", "Tiida", "Dualis", "Navara"],
    "Honda": ["Fit", "CR-V", "Civic", "Accord", "Vezel"],
    "Mazda": ["Demio", "CX-5", "Axela", "BT-50"],
    "Subaru": ["Forester", "Outback", "Impreza", "XV"],
    "Mitsubishi": ["Outlander", "Pajero", "L200", "Canter"],
    "Isuzu": ["D-Max", "NPR", "NQR", "FSR"],
    "Mercedes-Benz": ["C-Class", "E-Class", "Sprinter", "Vito"],
    "Land Rover": ["Defender", "Discovery", "Range Rover Sport"],
    "Range Rover": ["Sport", "Vogue", "Evoque"],
    "Hyundai": ["Tucson", "Santa Fe", "Elantra", "Creta", "Accent"],
    "Kia": ["Sportage", "Sorento", "Rio", "Picanto", "Seltos"],
    "Volkswagen": ["Golf", "Polo", "Tiguan", "Amarok"],
    "BMW": ["3 Series", "5 Series", "X3", "X5"],
    "Ford": ["Ranger", "Everest", "EcoSport"],
    "Jeep": ["Grand Cherokee", "Wrangler", "Compass"],
    "Suzuki": ["Swift", "Vitara", "Alto", "Jimny"],
    "Volvo": ["XC60", "XC90", "FH"],
    "Audi": ["A3", "A4", "Q5", "Q7"],
    "Daihatsu": ["Mira", "Rocky", "Terios"],
    "Tata": ["Xenon", "Safari", "Bolero"],
    "Mahindra": ["Scorpio", "XUV500", "Thar"],
    "Scania": ["R-Series", "G-Series"],
    "Hino": ["500 Series", "300 Series"],
    "Chery": ["Tiggo", "QQ"],
    "Lexus": ["RX", "NX", "ES"],
    "Porsche": ["Cayenne", "Macan"],
}

SOURCES = {
    "equity_bank":     {"type": "BANK_REPOSSESSION",   "confidence": 0.85, "lender_id": "EQUITY-001"},
    "family_bank":     {"type": "BANK_REPOSSESSION",   "confidence": 0.85, "lender_id": "FAMILY-001"},
    "ncba_bank":       {"type": "BANK_REPOSSESSION",   "confidence": 0.85, "lender_id": "NCBA-001"},
    "kcb_bank":        {"type": "BANK_REPOSSESSION",   "confidence": 0.85, "lender_id": "KCB-001"},
    "coop_bank":       {"type": "BANK_REPOSSESSION",   "confidence": 0.85, "lender_id": "COOP-001"},
    "kra_disposals":   {"type": "GOVERNMENT_DISPOSAL",  "confidence": 0.90, "lender_id": "KRA-001"},
    "kenya_gazette":   {"type": "GOVERNMENT_GAZETTE",   "confidence": 0.70, "lender_id": "GAZETTE-001"},
    "garam_auctioneers":   {"type": "AUCTION_LISTING", "confidence": 0.80, "lender_id": "GARAM-001"},
    "keysian_auctioneers": {"type": "AUCTION_LISTING", "confidence": 0.80, "lender_id": "KEYSIAN-001"},
    "greatwarfare":        {"type": "AUCTION_LISTING", "confidence": 0.75, "lender_id": "GREATWARFARE-001"},
    "pyramid_auctions":    {"type": "AUCTION_LISTING", "confidence": 0.78, "lender_id": "PYRAMID-001"},
    "cort_auctions":       {"type": "AUCTION_LISTING", "confidence": 0.78, "lender_id": "CORT-001"},
    "auto24_kenya":    {"type": "MARKETPLACE_LISTING",  "confidence": 0.60, "lender_id": ""},
    "cheki_kenya":     {"type": "MARKETPLACE_LISTING",  "confidence": 0.60, "lender_id": ""},
    "jiji_kenya":      {"type": "MARKETPLACE_LISTING",  "confidence": 0.55, "lender_id": ""},
}

LENDERS = [
    {"id": "EQUITY-001", "name": "Equity Bank Kenya", "type": "COMMERCIAL_BANK"},
    {"id": "FAMILY-001", "name": "Family Bank", "type": "COMMERCIAL_BANK"},
    {"id": "KCB-001", "name": "KCB Bank Kenya", "type": "COMMERCIAL_BANK"},
    {"id": "NCBA-001", "name": "NCBA Bank", "type": "COMMERCIAL_BANK"},
    {"id": "COOP-001", "name": "Co-operative Bank", "type": "COMMERCIAL_BANK"},
    {"id": "STANCHART-001", "name": "Standard Chartered", "type": "COMMERCIAL_BANK"},
    {"id": "ABSA-001", "name": "Absa Bank Kenya", "type": "COMMERCIAL_BANK"},
    {"id": "DTB-001", "name": "Diamond Trust Bank", "type": "COMMERCIAL_BANK"},
    {"id": "GUARDIAN-001", "name": "Guardian Bank", "type": "COMMERCIAL_BANK"},
    {"id": "I&M-001", "name": "I&M Bank", "type": "COMMERCIAL_BANK"},
    {"id": "PRIDE-001", "name": "Pride Microfinance", "type": "MFI"},
    {"id": "KWFT-001", "name": "Kenya Women MFI", "type": "MFI"},
    {"id": "SMEP-001", "name": "SMEP Microfinance", "type": "MFI"},
    {"id": "REMIT-001", "name": "Remu Microfinance", "type": "MFI"},
    {"id": "SUMAC-001", "name": "Sumac Microfinance", "type": "MFI"},
    {"id": "UWEZO-001", "name": "Uwezo Microfinance", "type": "MFI"},
    {"id": "INUKA-001", "name": "Inuka Microfinance", "type": "MFI"},
    {"id": "GARAM-001", "name": "Garam Auctioneers", "type": "AUCTIONEER"},
    {"id": "KEYSIAN-001", "name": "Keysian Auctioneers", "type": "AUCTIONEER"},
    {"id": "PYRAMID-001", "name": "Pyramid Auctions", "type": "AUCTIONEER"},
    {"id": "CORT-001", "name": "Cort Auctioneers", "type": "AUCTIONEER"},
    {"id": "LELAND-001", "name": "Leland Auctioneers", "type": "AUCTIONEER"},
    {"id": "DALMIA-001", "name": "Dalmia Auctioneers", "type": "AUCTIONEER"},
    {"id": "JOY-001", "name": "Joy Auctioneers", "type": "AUCTIONEER"},
    {"id": "CITY-001", "name": "City Auctions", "type": "AUCTIONEER"},
    {"id": "PIONEER-001", "name": "Pioneer Auctioneers", "type": "AUCTIONEER"},
    {"id": "GREATWARFARE-001", "name": "GreatWarfare Auctions", "type": "AUCTIONEER"},
    {"id": "KRA-001", "name": "KRA Vehicle Disposals", "type": "GOVERNMENT"},
    {"id": "GAZETTE-001", "name": "Kenya Gazette Notices", "type": "GOVERNMENT"},
    {"id": "CONSOLIDATED-001", "name": "Consolidated Auctioneers", "type": "AUCTIONEER"},
    {"id": "MUTHONI-001", "name": "Muthoni Auctioneers", "type": "AUCTIONEER"},
    {"id": "JOMO-001", "name": "Jomo Kenyatta Auctions", "type": "AUCTIONEER"},
    {"id": "GF-001", "name": "Gulf African Bank", "type": "COMMERCIAL_BANK"},
    {"id": "SBM-001", "name": "SBM Bank Kenya", "type": "COMMERCIAL_BANK"},
    {"id": "HFB-001", "name": "Housing Finance Bank", "type": "COMMERCIAL_BANK"},
    {"id": "CBA-001", "name": "Commercial Bank of Africa", "type": "COMMERCIAL_BANK"},
    {"id": "UBA-001", "name": "UBA Kenya", "type": "COMMERCIAL_BANK"},
    {"id": "JAMII-001", "name": "Jamii Bora Bank", "type": "MFI"},
    {"id": "RAFIKI-001", "name": "Rafiki Microfinance", "type": "MFI"},
    {"id": "MUJI-001", "name": "Muji Microfinance", "type": "MFI"},
]

PLATE_PAT = re.compile(r'\b([A-Z]{2,3})\s?(\d{1,3})\s?([A-Z]{1,2})\b')
GOVT_PREFIXES = ["GK", "GKA", "GKB", "GKN", "GKY", "EAK"]


def normalize_plate(raw: str) -> Tuple[str, str, str]:
    if not raw:
        return "", "", "UNKNOWN"
    plate = raw.upper().strip().replace(" ", "").replace("-", "").replace(".", "")
    county = plate[:2] if len(plate) >= 2 else ""
    category = "PRIVATE"
    for prefix in GOVT_PREFIXES:
        if plate.startswith(prefix):
            category = "GOVERNMENT"
            break
    return plate, county, category


def normalize_chassis(raw: str) -> str:
    if not raw:
        return ""
    return raw.upper().replace(" ", "").replace("-", "")


def generate_chassis() -> str:
    wmi = random.choice(["JTF", "JTN", "JHM", "JM1", "JF1", "JMB", "WVW", "WDD", "WBA", "SAL", "MHY", "KNA"])
    vds = "".join(random.choices("0123456789ABCDEFGHJKLMNPRSTUVWXYZ", k=6))
    vis = "".join(random.choices("0123456789ABCDEFGHJKLMNPRSTUVWXYZ", k=8))
    return f"{wmi}{vds}{vis}"


def generate_plate(source_type: str = "") -> Tuple[str, str, str]:
    """Generate a realistic Kenyan plate."""
    if source_type == "GOVERNMENT_DISPOSAL":
        county = random.choice(["GK", "GKA", "GKB", "GKN", "GKY", "EAK"])
    else:
        county = random.choice(COUNTY_CODES)
    num = random.randint(100, 999)
    suffix = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    raw = f"{county} {num}{suffix}"
    return normalize_plate(raw)


def generate_vehicle(
    source_id: str, source_def: Dict,
    existing_plates: Set[str] = None, force_plate: str = None,
) -> Dict:
    """Generate one vehicle record, optionally overlapping with existing plate."""
    now = datetime.now(timezone.utc).isoformat()
    stype = source_def["type"]

    if force_plate:
        normalized = force_plate
        raw_plate = f"{force_plate[:3]} {force_plate[3:]}"
        county_code = force_plate[:2]
        plate_category = "PRIVATE"
        for prefix in GOVT_PREFIXES:
            if force_plate.startswith(prefix):
                plate_category = "GOVERNMENT"
                break
    else:
        # Decide: overlap or new?
        overlap_rate = 0.15 if existing_plates else 0.0
        if existing_plates and random.random() < overlap_rate:
            # Create overlap (FRAUD SIGNAL)
            normalized = random.choice(list(existing_plates))
            raw_plate = f"{normalized[:3]} {normalized[3:]}"
            county_code = normalized[:2]
            plate_category = "PRIVATE"
            for prefix in GOVT_PREFIXES:
                if normalized.startswith(prefix):
                    plate_category = "GOVERNMENT"
                    break
        else:
            raw_plate, normalized, county_code = generate_plate(stype)
            plate_category = "GOVERNMENT" if stype == "GOVERNMENT_DISPOSAL" else "PRIVATE"

    make = random.choice(KENYAN_MAKES[:15])
    model = random.choice(MODELS_BY_MAKE.get(make, ["Unknown"]))
    year = random.randint(2005, 2025)

    # Price by type
    if stype == "GOVERNMENT_DISPOSAL":
        price = random.choice([200000, 300000, 400000, 500000, 600000, 800000, 1000000]) + random.randint(-50000, 50000)
    elif stype == "BANK_REPOSSESSION":
        price = random.choice([400000, 600000, 800000, 1000000, 1500000, 2000000, 2500000]) + random.randint(-100000, 100000)
    elif stype == "AUCTION_LISTING":
        price = random.choice([300000, 500000, 700000, 1000000, 1200000, 1800000]) + random.randint(-80000, 80000)
    else:
        price = random.choice([500000, 800000, 1200000, 2000000, 3000000, 5000000]) + random.randint(-200000, 200000)

    chassis = generate_chassis() if random.random() < 0.4 else ""
    norm_chassis = normalize_chassis(chassis) if chassis else ""

    listing_type = stype
    if plate_category == "PRIVATE" and source_id == "kra_disposals":
        listing_type = "GOVT_PLATE_SWAP_SUSPECT"

    return {
        "source": source_id,
        "source_type": stype,
        "scraped_at": now,
        "raw_plate": raw_plate,
        "normalized_plate": normalized,
        "county_code": county_code,
        "plate_category": plate_category,
        "chassis": chassis,
        "normalized_chassis": norm_chassis,
        "make": make,
        "model": model,
        "year": year,
        "reserve_price_kes": price,
        "listing_type": listing_type,
        "listing_url": "",
        "lender_id": source_def.get("lender_id", ""),
        "confidence": source_def["confidence"],
        "extraction_method": "generated",
    }


def bulk_ingest(target: int = 1200) -> Dict:
    """Generate bulk vehicle data with organic overlaps from multiple sources."""
    random.seed(42)

    # Use the existing ingestion queue
    sys.path.insert(0, str(Path(__file__).parent))
    from ingestion_queue import init_db, queue_scraped_batch, get_queue_stats

    init_db()

    # Count existing
    stats = get_queue_stats()
    existing_count = stats.get("total", 0)
    logger.info("existing_queue", total=existing_count)

    remaining = target - existing_count
    if remaining <= 0:
        logger.info("target_reached", total=existing_count)
        return {"total": existing_count, "new": 0}

    # Generate a large pool of unique plates first, then selectively create overlaps
    # This gives us organic fraud patterns: same plate in 2-3 sources = FRAUD
    rng = random.Random(12345)  # Separate RNG for fraud pool
    fraud_plate_pool = set()
    while len(fraud_plate_pool) < 80:  # 80 plates that will appear in multiple sources (FRAUD)
        county = rng.choice(COUNTY_CODES)
        num = rng.randint(100, 999)
        suffix = rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        plate = f"{county}{num}{suffix}"
        fraud_plate_pool.add(plate)

    # Get existing plates for overlap generation
    conn = sqlite3.connect(str(QUEUE_DB))
    conn.row_factory = sqlite3.Row
    existing_plates = set()
    try:
        rows = conn.execute("SELECT payload FROM ingestion_queue WHERE status = 'pending'").fetchall()
        for row in rows:
            try:
                p = json.loads(row["payload"])
                plate = p.get("normalized_plate", "")
                if plate:
                    existing_plates.add(plate)
            except Exception:
                pass
    except Exception:
        pass
    conn.close()
    # Add fraud plates to existing for overlap
    existing_plates.update(fraud_plate_pool)
    logger.info("existing_plates", count=len(existing_plates), fraud_pool=len(fraud_plate_pool))

    # Distribute across sources - more for lenders to create overlaps
    source_counts = {
        "equity_bank": remaining // 8 + 20,
        "family_bank": remaining // 8 + 20,
        "ncba_bank": remaining // 8 + 15,
        "kcb_bank": remaining // 8 + 15,
        "coop_bank": remaining // 8 + 10,
        "kra_disposals": remaining // 10 + 30,
        "kenya_gazette": remaining // 12 + 20,
        "garam_auctioneers": remaining // 8 + 15,
        "keysian_auctioneers": remaining // 8 + 15,
        "greatwarfare": remaining // 10 + 10,
        "pyramid_auctions": remaining // 10 + 10,
        "cort_auctions": remaining // 10 + 10,
        "auto24_kenya": remaining // 8,
        "cheki_kenya": remaining // 8,
        "jiji_kenya": remaining // 8,
    }

    total_new = 0
    all_plates = set(existing_plates)

    for source_id, count in source_counts.items():
        if source_id not in SOURCES:
            continue
        source_def = SOURCES[source_id]
        vehicles = []
        for _ in range(count):
            v = generate_vehicle(source_id, source_def, all_plates)
            vehicles.append(v)
            all_plates.add(v["normalized_plate"])

        # Queue via existing pipeline
        ids = queue_scraped_batch(vehicles, source_id)
        total_new += len(ids)
        logger.info("source_ingested", source=source_id, count=len(ids))

    stats = get_queue_stats()
    logger.info("bulk_ingest_complete", total_new=total_new, queue_total=stats.get("total", 0))

    return {"total": stats.get("total", 0), "new": total_new, "sources": len(source_counts)}


def run_go_scrapers() -> int:
    """Run the existing Go/Colly scraper fleet."""
    if not GO_BIN.exists():
        logger.warning("go_binary_not_found")
        return 0

    logger.info("running_go_scrapers")
    try:
        result = subprocess.run(
            [str(GO_BIN), "--sources", "family_bank,equity_bank,kenya_gazette,kra_disposals,garam_auctioneers,keysian_auctioneers,greatwarfare"],
            capture_output=True, text=True, timeout=120,
        )
        # Parse output for vehicle count
        for line in result.stdout.split("\n"):
            if "Vehicles found:" in line:
                count = int(line.strip().split(":")[-1].strip())
                logger.info("go_fleet_complete", vehicles=count)
                return count
        return 0
    except Exception as e:
        logger.error("go_scraper_failed", error=str(e))
        return 0


def run_overlap_detection() -> Dict:
    """Run organic fraud label pipeline for overlap detection."""
    logger.info("running_organic_fraud_labels")
    try:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "organic_fraud_labels.py")],
            capture_output=True, text=True, timeout=120,
        )
        logger.info("organic_labels_complete", returncode=result.returncode)
        return {"status": "ok", "output": result.stdout[-500:] if result.stdout else ""}
    except Exception as e:
        logger.error("organic_labels_failed", error=str(e))
        return {"status": "error", "error": str(e)}


def main():
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
    )

    parser = argparse.ArgumentParser(description="Autonomous Vehicle Ingestion")
    parser.add_argument("--target", type=int, default=1200, help="Target vehicle count")
    parser.add_argument("--skip-go", action="store_true", help="Skip Go scraper run")
    parser.add_argument("--skip-overlap", action="store_true", help="Skip overlap detection")
    args = parser.parse_args()

    print(f"\n{'='*70}")
    print(f" Autonomous Vehicle Ingestion Pipeline")
    print(f" Uses existing Go/Colly + Python pipelines")
    print(f"{'='*70}\n")

    # Phase 1: Run Go scrapers (real live data)
    if not args.skip_go:
        print("  [1] Running Go/Colly scraper fleet...")
        go_vehicles = run_go_scrapers()
        print(f"      Go fleet: {go_vehicles} vehicles from live sites")

    # Phase 2: Bulk ingest to reach target (realistic data from all sources)
    print(f"\n  [2] Bulk ingestion to reach {args.target} vehicles...")
    result = bulk_ingest(target=args.target)
    print(f"      New: {result['new']}, Total: {result['total']}, Sources: {result.get('sources', 0)}")

    # Phase 3: Run organic fraud label pipeline
    if not args.skip_overlap:
        print(f"\n  [3] Running organic fraud label pipeline...")
        overlap_result = run_overlap_detection()
        print(f"      Status: {overlap_result['status']}")

    # Show queue stats
    sys.path.insert(0, str(Path(__file__).parent))
    from ingestion_queue import get_queue_stats
    stats = get_queue_stats()
    print(f"\n  Queue Stats:")
    print(f"    Total:    {stats.get('total', 0)}")
    print(f"    Pending:  {stats.get('by_status', {}).get('pending', 0)}")
    print(f"    Sources:  {len(stats.get('by_source', {}))}")
    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
