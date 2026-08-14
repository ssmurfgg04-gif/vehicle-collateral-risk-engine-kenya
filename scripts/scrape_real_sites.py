#!/usr/bin/env python3
"""
REAL vehicle scraper using Crawl4AI for JS-heavy Kenyan sites.
Hits the actual live sites and extracts REAL vehicle data.
Writes everything to the shared SQLite ingestion queue.
"""

import asyncio
import json
import os
import re
import sys
import sqlite3
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List

import structlog

log = structlog.get_logger("real_scraper")

# ─── Kenyan Plate/Vehicle Patterns ────────────────────────────────────────
PLATE_RE = re.compile(r'\b([A-Z]{2,3})\s?(\d{1,3})\s?([A-Z]{1,2})\b')
CHASSIS_RE = re.compile(r'\b([A-HJ-NPR-Z0-9]{17})\b')
KES_RE = re.compile(r'(?:KES|KSh|Ksh\.?)\s?([\d,]+)')
GOVT_PREFIXES = ["GK", "GKA", "GKB", "GKN", "GKY"]

KENYAN_MAKES = [
    "Mercedes-Benz", "Land Rover", "Range Rover", "Mercedes",
    "Mitsubishi", "Chevrolet", "Volkswagen", "Peugeot",
    "Toyota", "Nissan", "Isuzu", "Honda", "Mazda", "Subaru", "Hyundai",
    "Kia", "Suzuki", "Jeep", "Ford", "Volvo", "Audi", "Dai0hatsu",
    "Chery", "Lexus", "Porsche", "Tata", "Mahindra", "Scania",
    "Hino", "FAW", "MAN", "Iveco",
]
MAKE_PATTERN = "|".join(re.escape(m) for m in KENYAN_MAKES)
LISTING_RE = re.compile(rf'({MAKE_PATTERN})[\s\-]+([\w\-/\.]+)(?:\s*\((\d{{4}})\))?')

# ─── Real Source URLs ──────────────────────────────────────────────────────
SOURCES = {
    "family_bank": {
        "urls": [
            "https://www.familybank.co.ke/?post_type=vehicles",
            "https://www.familybank.co.ke/?post_type=vehicles&page=2",
            "https://www.familybank.co.ke/?post_type=vehicles&page=3",
            "https://www.familybank.co.ke/?post_type=vehicles&page=4",
            "https://www.familybank.co.ke/vehicle-finance",
            "https://www.familybank.co.ke/vehicle-finance/page=2",
        ],
        "js": False,
        "delay": 3,
        "type": "BANK_REPOSSESSION",
        "confidence": 0.85,
    },
    "equity_bank": {
        "urls": [
            "https://equitybank.co.ke/vehicle-logbook-loans",
            "https://ke.equitybankgroup.com/vehicle-loans",
            "https://equitybank.co.ke/personal-banking/loans/asset-finance",
        ],
        "js": True,
        "delay": 4,
        "type": "BANK_REPOSSESSION",
        "confidence": 0.85,
    },
    "garam_auctioneers": {
        "urls": [
            "https://garamauctioneers.co.ke",
            "https://garamauctioneers.co.ke/vehicle-auctions",
            "https://garamauctioneers.co.ke/auctions",
        ],
        "js": True,
        "delay": 4,
        "type": "AUCTION_LISTING",
        "confidence": 0.80,
    },
    "keysian_auctioneers": {
        "urls": [
            "https://keysianauctioneers.co.ke",
            "https://keysianauctioneers.co.ke/vehicle-auctions",
        ],
        "js": True,
        "delay": 4,
        "type": "AUCTION_LISTING",
        "confidence": 0.80,
    },
    "greatwarfare": {
        "urls": [
            "https://greatwarfare.co.ke",
            "https://greatwarfare.co.ke/auctions",
        ],
        "js": True,
        "delay": 4,
        "type": "AUCTION_LISTING",
        "confidence": 0.75,
    },
    "kra_disposals": {
        "urls": [
            "https://www.kra.go.ke/public-notices",
            "https://www.kra.go.ke/services/customs-and-border-control",
        ],
        "js": True,
        "delay": 10,
        "type": "GOVERNMENT_DISPOSAL",
        "confidence": 0.90,
    },
    "kenya_gazette": {
        "urls": [
            "https://gazettes.africa/go/kenya",
        ],
        "js": True,
        "delay": 10,
        "type": "GOVERNMENT_GAZETTE",
        "confidence": 0.70,
    },
    "kcb_bank": {
        "urls": [
            "https://kcbgroup.com/loans/asset-finance",
        ],
        "js": True,
        "delay": 4,
        "type": "BANK_REPOSSESSION",
        "confidence": 0.85,
    },
    "cooperative_bank": {
        "urls": [
            "https://co-opbank.co.ke/personal-banking/loans/asset-finance",
        ],
        "js": True,
        "delay": 4,
        "type": "BANK_REPOSSESSION",
        "confidence": 0.85,
    },
}


def normalize_plate(raw: str) -> tuple:
    if not raw:
        return "", "", "UNKNOWN"
    plate = raw.upper().replace(" ", "").replace("-", "").replace(".", "")
    match = PLATE_RE.search(raw)
    county = ""
    if match:
        county = match.group(1)
        num = match.group(2).replace("O", "0").replace("I", "1").replace("Q", "0")
        suffix = match.group(3)
        plate = county + num + suffix
    elif len(plate) >= 2:
        county = plate[:2]
    cat = "PRIVATE"
    for p in GOVT_PREFIXES:
        if plate.startswith(p):
            cat = "GOVERNMENT"
            break
    return plate, county, cat


def normalize_chassis(raw: str) -> str:
    if not raw:
        return ""
    return raw.upper().replace(" ", "").replace("-", "")


def extract_vehicles(text: str, url: str, source_id: str) -> List[Dict]:
    """Extract real vehicles from page text."""
    vehicles = []
    seen = set()
    plates = PLATE_RE.findall(text)
    chassis_matches = CHASSIS_RE.findall(text)
    kes_matches = KES_RE.findall(text)
    amounts = []
    for m in kes_matches:
        try:
            amounts.append(int(m.replace(",", "")))
        except ValueError:
            pass
    make_model_matches = LISTING_RE.findall(text)

    src_conf = SOURCES.get(source_id, {}).get("confidence", 0.5)
    src_type = SOURCES.get(source_id, {}).get("type", "UNKNOWN")

    for i, plate_match in enumerate(plates):
        county, num, suffix = plate_match
        raw_plate = f"{county} {num}{suffix}"
        norm, county_code, plate_cat = normalize_plate(raw_plate)
        if norm in seen:
            continue
        seen.add(norm)

        make, model, year, price = "", "", 0, None
        if i < len(make_model_matches):
            make = make_model_matches[i][0]
            model = make_model_matches[i][1]
            if len(make_model_matches[i]) >= 3 and make_model_matches[i][2]:
                try:
                    y = int(make_model_matches[i][2])
                    if 1990 <= y <= 2026:
                        year = y
                except ValueError:
                    pass
        if i < len(amounts):
            price = amounts[i]
        chassis = ""
        norm_ch = ""
        if i < len(chassis_matches):
            chassis = chassis_matches[i]
            norm_ch = normalize_chassis(chassis)

        v = {
            "source": source_id,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "raw_plate": raw_plate,
            "normalized_plate": norm,
            "county_code": county_code,
            "plate_category": plate_cat,
            "chassis": chassis,
            "normalized_chassis": norm_ch,
            "make": make,
            "model": model,
            "listing_type": src_type,
            "listing_url": url,
            "confidence": src_conf,
            "extraction_method": "crawl4ai",
        }
        if year:
            v["year"] = year
        if price:
            v["reserve_price_kes"] = price
        vehicles.append(v)
    return vehicles


def queue_vehicles(vehicles: List[Dict], source: str) -> int:
    """Write vehicles to the shared SQLite ingestion queue."""
    db_path = "/home/z/my-project/data/ingestion_queue.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ingestion_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            source TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    now = datetime.now(timezone.utc).isoformat()
    values = [(json.dumps(v, ensure_ascii=False), "pending", v.get("source", source), now) for v in vehicles]
    conn.executemany(
        "INSERT INTO ingestion_queue (payload, status, source, created_at) VALUES (?, ?, ?, ?)",
        values
    )
    conn.commit()
    conn.close()
    return len(values)


async def crawl_url(url: str, js_rendered: bool = False) -> Dict:
    """Crawl a URL using Crawl4AI."""
    try:
        from crawl4ai import AsyncWebCrawler

        async with AsyncWebCrawler(
            headless=True,
            verbose=False,
        ) as crawler:
            result = await crawler.arun(
                url=url,
                js_only=js_rendered,
                word_count_threshold=5,
                wait_for="networkidle" if js_rendered else None,
                magic=True,
            )
            if result.success:
                return {
                    "url": url,
                    "status": "SUCCESS",
                    "markdown": result.markdown or "",
                    "cleaned_html": result.cleaned_html or "",
                    "size": len(result.markdown or "") + len(result.cleaned_html or ""),
                }
            else:
                return {"url": url, "status": "FAILED", "error": result.error_message}
    except Exception as e:
        return {"url": url, "status": "ERROR", "error": str(e)}


async def main():
    print()
    print("=" * 70)
    print(" Crawl4AI Real Scraper — Live Kenyan Vehicle Sites")
    print("=" * 70)
    print()

    all_vehicles = []
    all_results = []
    total_queued = 0

    for source_id, source_info in SOURCES.items():
        urls = source_info["urls"]
        js = source_info["js"]
        delay = source_info["delay"]
        print(f"  [{source_id}] {len(urls)} URLs (JS={'YES' if js else 'NO'})")

        source_vehicles = []
        for url in urls:
            print(f"    → {url}")
            result = await crawl_url(url, js_rendered=js)
            all_results.append(result)

            if result["status"] == "SUCCESS":
                # Combine markdown + cleaned HTML for parsing
                text = result.get("markdown", "") + "\n" + result.get("cleaned_html", "")
                vehicles = extract_vehicles(text, url, source_id)
                source_vehicles.extend(vehicles)
                print(f"      ✓ {len(vehicles)} vehicles from {result.get('size', 0)} chars")
            else:
                print(f"      ✗ {result.get('error', 'unknown error')}")

            await asyncio.sleep(delay)

        all_vehicles.extend(source_vehicles)
        
        # Queue immediately
        if source_vehicles:
            queued = queue_vehicles(source_vehicles, source_id)
            total_queued += queued
            print(f"    Queued {queued} vehicles from {source_id}")
        else:
            print(f"    No vehicles found for {source_id}")
        print()

    # Save all vehicles JSON
    data_dir = Path("/home/z/my-project/scripts/scrapers/data")
    data_dir.mkdir(parents=True, exist_ok=True)
    out_file = data_dir / f"real_scraped_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_file, "w") as f:
        json.dump(all_vehicles, f, indent=2, ensure_ascii=False)

    # Summary
    print("=" * 70)
    print(" Real Scraping Results")
    print("=" * 70)
    print(f"  Total vehicles:  {len(all_vehicles)}")
    print(f"  Total queued:    {total_queued}")
    unique_plates = set(v["normalized_plate"] for v in all_vehicles)
    print(f"  Unique plates:   {len(unique_plates)}")
    sources_with_data = set(v["source"] for v in all_vehicles)
    print(f"  Active sources:  {len(sources_with_data)}")
    print(f"  Output:          {out_file}")
    print()

    # Per-source breakdown
    print("  Per-Source:")
    by_source = {}
    for v in all_vehicles:
        s = v["source"]
        by_source[s] = by_source.get(s, 0) + 1
    for s, c in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"    {s:30s} {c:4d} vehicles")

    # Sample vehicles
    if all_vehicles:
        print()
        print("  Sample REAL vehicles:")
        for v in all_vehicles[:10]:
            price_str = f"KES {v.get('reserve_price_kes', 'N/A')}" if v.get("reserve_price_kes") else "no price"
            print(f"    {v.get('raw_plate', '?'):12s} {v.get('make', ''):15s} {v.get('model', ''):15s} {price_str}  [{v['source']}]")


if __name__ == "__main__":
    asyncio.run(main())
