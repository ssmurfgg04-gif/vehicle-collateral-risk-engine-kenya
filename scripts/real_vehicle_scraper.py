"""
Real Vehicle Scraper — Kenya Vehicle Collateral Risk Engine

Hybrid pipeline:
  - httpx/BeautifulSoup for static HTML sites (Family Bank)
  - Playwright for JS-rendered sites (all others)
  - Proper deduplication by normalized plate
  - Cross-lender overlap detection (REAL fraud signal)
  - Writes to shared SQLite queue

This is the REAL data pipeline. No synthetic data.
"""

import asyncio
import json
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import structlog

logger = structlog.get_logger("real_scraper")

# ─── Kenyan Vehicle Patterns ──────────────────────────────────────────

PLATE_PATTERN = re.compile(r'\b([A-Z]{2,3})\s?(\d{1,3})\s?([A-Z]{1,2})\b')
CHASSIS_PATTERN = re.compile(r'\b([A-HJ-NPR-Z0-9]{17})\b')
KES_PATTERN = re.compile(r'(?:KES|KSh|Ksh\.?)\s?([\d,]+)')

GOVT_PREFIXES = ["GK", "GKA", "GKB", "GKN", "GKY"]

KENYAN_MAKES = [
    "Mercedes-Benz", "Land Rover", "Range Rover", "Mercedes",
    "Mitsubishi", "Chevrolet", "Volkswagen", "Peugeot",
    "Toyota", "Nissan", "Isuzu", "Honda", "Mazda", "Subaru", "Hyundai",
    "Kia", "Suzuki", "Jeep", "Ford", "Volvo", "Audi", "Daihatsu",
    "Chery", "Lexus", "Porsche", "Tata", "Mahindra", "Scania",
    "Hino", "FAW", "MAN", "Iveco", "Ashok Leyland",
]

# Build make/model pattern
MAKE_PATTERN = "|".join(re.escape(m) for m in sorted(KENYAN_MAKES, key=len, reverse=True))
LISTING_RE = re.compile(
    rf'({MAKE_PATTERN})[\s\-]+([\w\-/\.]+)(?:\s*\((\d{{4}})\))?'
)

# ─── Source Definitions ───────────────────────────────────────────────

SOURCES = {
    # ── BANKS ──
    "family_bank": {
        "name": "Family Bank Kenya",
        "urls": [
            "https://www.familybank.co.ke/?post_type=vehicles",
            "https://www.familybank.co.ke/?post_type=vehicles&page=2",
            "https://www.familybank.co.ke/?post_type=vehicles&page=3",
        ],
        "listing_type": "BANK_REPOSSESSION",
        "confidence": 0.85,
        "js_rendered": False,
        "delay": 3,
    },
    "coop_bank": {
        "name": "Co-operative Bank",
        "urls": [
            "https://vehiclesales.co-opbank.co.ke",
            "https://vehiclesales.co-opbank.co.ke/page/2",
            "https://vehiclesales.co-opbank.co.ke/page/3",
        ],
        "listing_type": "BANK_REPOSSESSION",
        "confidence": 0.85,
        "js_rendered": True,
        "delay": 3,
    },
    "equity_bank": {
        "name": "Equity Bank",
        "urls": [
            "https://equitybank.co.ke/vehicle-logbook-loans",
            "https://equitybank.co.ke/personal-borrowing/asset-finance",
        ],
        "listing_type": "BANK_REPOSSESSION",
        "confidence": 0.85,
        "js_rendered": True,
        "delay": 3,
    },
    "kcb_bank": {
        "name": "KCB Bank",
        "urls": [
            "https://kcbgroup.com/ke/personal/borrow/asset-finance",
            "https://kcbgroup.com/ke/personal/borrow",
        ],
        "listing_type": "BANK_REPOSSESSION",
        "confidence": 0.85,
        "js_rendered": True,
        "delay": 3,
    },
    # ── AUCTIONEERS ──
    "garam": {
        "name": "Garam Auctioneers",
        "urls": [
            "https://garam.co.ke/index.php/component/content/article/96-auction-motor-vehicle",
            "https://garam.co.ke/index.php/auctions/motor-vehicles",
            "https://garam.co.ke",
        ],
        "listing_type": "AUCTION_LISTING",
        "confidence": 0.80,
        "js_rendered": True,
        "delay": 3,
    },
    "keysian": {
        "name": "Keysian Auctioneers",
        "urls": [
            "https://keysianauctioneers.co.ke",
            "https://keysianauctioneers.co.ke/vehicle-auctions",
        ],
        "listing_type": "AUCTION_LISTING",
        "confidence": 0.80,
        "js_rendered": True,
        "delay": 3,
    },
    "phillips": {
        "name": "Phillips Auctioneers",
        "urls": [
            "https://phillipsauctioneers.co.ke/upcoming-auctions/",
            "https://phillipsauctioneers.co.ke/live-auction/",
            "https://phillipsauctioneers.co.ke",
        ],
        "listing_type": "AUCTION_LISTING",
        "confidence": 0.80,
        "js_rendered": True,
        "delay": 3,
    },
    "westminster": {
        "name": "Westminster Auctioneers",
        "urls": [
            "https://www.westminster.co.ke",
        ],
        "listing_type": "AUCTION_LISTING",
        "confidence": 0.80,
        "js_rendered": True,
        "delay": 3,
    },
    "mogo": {
        "name": "Mogo Vehicle Auctions",
        "urls": [
            "https://cars.mogo.co.ke/auction",
            "https://cars.mogo.co.ke",
        ],
        "listing_type": "MFI_REPOSSESSION",
        "confidence": 0.80,
        "js_rendered": True,
        "delay": 3,
    },
    "bank_repossessed": {
        "name": "Bank Repossessed Cars Kenya",
        "urls": [
            "https://bankrepossessedcarskenya.com",
        ],
        "listing_type": "BANK_REPOSSESSION",
        "confidence": 0.80,
        "js_rendered": True,
        "delay": 3,
    },
    # ── MORE BANKS & MFIs ──
    "ncba_bank": {
        "name": "NCBA Bank Vehicle Listings",
        "urls": [
            "https://ke.ncbagroup.com/personal/borrow/asset-finance",
            "https://ncba.co.ke",
        ],
        "listing_type": "BANK_REPOSSESSION",
        "confidence": 0.85,
        "js_rendered": True,
        "delay": 3,
    },
    "stanbic_bank": {
        "name": "Stanbic Bank Vehicle Finance",
        "urls": [
            "https://ke.stanbicbank.co.ke/personal/borrow/vehicle-and-asset-finance",
            "https://ke.stanbicbank.co.ke",
        ],
        "listing_type": "BANK_REPOSSESSION",
        "confidence": 0.85,
        "js_rendered": True,
        "delay": 3,
    },
    "dtb_bank": {
        "name": "DTB Bank Vehicle Loans",
        "urls": [
            "https://dtbafrica.com/ke/personal/vehicle-loan",
            "https://dtbafrica.com/ke",
        ],
        "listing_type": "BANK_REPOSSESSION",
        "confidence": 0.85,
        "js_rendered": True,
        "delay": 3,
    },
    # ── MORE AUCTIONEERS ──
    "pyramid_auctioneers": {
        "name": "Pyramid Auctioneers",
        "urls": [
            "https://pyramidauctioneers.co.ke",
        ],
        "listing_type": "AUCTION_LISTING",
        "confidence": 0.80,
        "js_rendered": True,
        "delay": 3,
    },
    "leakey_auctioneers": {
        "name": "Leakey Auctioneers",
        "urls": [
            "https://leakeys.co.ke",
            "https://leakeys.co.ke/auctions",
        ],
        "listing_type": "AUCTION_LISTING",
        "confidence": 0.80,
        "js_rendered": True,
        "delay": 3,
    },
    "cascade_auctioneers": {
        "name": "Cascade Auctioneers",
        "urls": [
            "https://cascadeauctions.co.ke",
        ],
        "listing_type": "AUCTION_LISTING",
        "confidence": 0.80,
        "js_rendered": True,
        "delay": 3,
    },
    "jomo_auctioneers": {
        "name": "Jomo Auctioneers",
        "urls": [
            "https://jomoauct.co.ke",
        ],
        "listing_type": "AUCTION_LISTING",
        "confidence": 0.80,
        "js_rendered": True,
        "delay": 3,
    },
    # ── GOVERNMENT ──
    "kenya_gazette": {
        "name": "Kenya Gazette Notices",
        "urls": [
            "https://gazettes.africa/go/kenya",
        ],
        "listing_type": "GOVERNMENT_GAZETTE",
        "confidence": 0.70,
        "js_rendered": True,
        "delay": 10,
    },
    "kra_disposals": {
        "name": "KRA Government Disposals",
        "urls": [
            "https://www.kra.go.ke/public-notices",
            "https://www.kra.go.ke/services/customs-and-border-control",
        ],
        "listing_type": "GOVERNMENT_DISPOSAL",
        "confidence": 0.90,
        "js_rendered": True,
        "delay": 10,
    },
}


# ─── Plate Normalization ──────────────────────────────────────────────

def normalize_plate(raw: str) -> Tuple[str, str, str]:
    """Normalize a Kenyan registration plate with OCR corrections.
    Returns: (normalized, county_code, category)
    """
    if not raw:
        return "", "", "UNKNOWN"

    plate = raw.upper()
    for ch in " -.":
        plate = plate.replace(ch, "")

    match = PLATE_PATTERN.search(raw)
    county = ""
    if match:
        county = match.group(1)
        num = match.group(2)
        suffix = match.group(3)
        num_fixed = num.replace("O", "0").replace("I", "1").replace("Q", "0")
        plate = county + num_fixed + suffix
    elif len(plate) >= 2:
        county = plate[:2]

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


# ─── Vehicle Extraction ───────────────────────────────────────────────

def extract_vehicles(text: str, url: str, source_id: str) -> List[Dict]:
    """Extract vehicles from HTML/text content using regex patterns."""
    vehicles = []
    seen_plates: Set[str] = set()

    plates = PLATE_PATTERN.findall(text)
    chassis_matches = CHASSIS_PATTERN.findall(text)
    kes_matches = KES_PATTERN.findall(text)
    make_model_matches = LISTING_RE.findall(text)

    # Parse KES amounts
    amounts = []
    for m in kes_matches:
        clean = m.replace(",", "")
        try:
            amounts.append(int(clean))
        except ValueError:
            pass

    source_conf = SOURCES.get(source_id, {})

    for i, plate_match in enumerate(plates):
        county, num, suffix = plate_match
        raw_plate = f"{county} {num}{suffix}"
        normalized, county_code, plate_category = normalize_plate(raw_plate)

        if normalized in seen_plates:
            continue
        seen_plates.add(normalized)

        # Skip obviously wrong plates (too short, no digits, etc.)
        if len(normalized) < 5 or len(normalized) > 8:
            continue

        make = ""
        model = ""
        year = 0
        price = None

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
        norm_chassis = ""
        if i < len(chassis_matches):
            chassis = chassis_matches[i]
            norm_chassis = normalize_chassis(chassis)

        confidence = source_conf.get("confidence", 0.5)
        if raw_plate and make:
            confidence = min(confidence + 0.1, 1.0)

        # Determine listing type based on source
        listing_type = source_conf.get("listing_type", "UNKNOWN")
        if plate_category == "GOVERNMENT" and source_id in ["kra_disposals", "kenya_gazette"]:
            listing_type = "GOVERNMENT_DISPOSAL"
        elif plate_category == "PRIVATE" and source_id in ["kra_disposals"]:
            listing_type = "GOVT_PLATE_SWAP_SUSPECT"

        v = {
            "source": source_id,
            "source_name": source_conf.get("name", source_id),
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "raw_plate": raw_plate,
            "normalized_plate": normalized,
            "county_code": county_code,
            "plate_category": plate_category,
            "chassis": chassis,
            "normalized_chassis": norm_chassis,
            "make": make,
            "model": model,
            "listing_type": listing_type,
            "listing_url": url,
            "confidence": round(confidence, 2),
            "extraction_method": "real_scraper",
        }
        if year:
            v["year"] = year
        if price:
            v["reserve_price_kes"] = price

        vehicles.append(v)

    return vehicles


# ─── Static HTML Scraper (httpx + BeautifulSoup) ─────────────────────

async def scrape_static(url: str, source_id: str) -> List[Dict]:
    """Scrape a static HTML page using httpx."""
    import httpx

    try:
        async with httpx.AsyncClient(
            verify=False,
            timeout=15,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-KE,en;q=0.9",
            }
        ) as client:
            resp = await client.get(url)

            if resp.status_code != 200:
                logger.warn("static_scrape_failed", url=url, status=resp.status_code)
                return []

            vehicles = extract_vehicles(resp.text, url, source_id)
            logger.info("static_scrape_ok", url=url, vehicles=len(vehicles), size=len(resp.text))
            return vehicles

    except Exception as e:
        logger.error("static_scrape_error", url=url, error=str(e))
        return []


# ─── JS-Rendered Scraper (Playwright) ────────────────────────────────

async def scrape_js(url: str, source_id: str, wait_seconds: int = 5) -> List[Dict]:
    """Scrape a JS-rendered page using Playwright."""
    from playwright.async_api import async_playwright

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="en-KE",
            )
            page = await context.new_page()

            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
                # Wait for dynamic content to load
                await page.wait_for_timeout(wait_seconds * 1000)

                # Try scrolling to load lazy content
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)

                # Get the fully rendered HTML
                html = await page.content()

                vehicles = extract_vehicles(html, url, source_id)
                logger.info("js_scrape_ok", url=url, vehicles=len(vehicles), size=len(html))
                return vehicles

            except Exception as e:
                logger.error("js_page_error", url=url, error=str(e))
                return []
            finally:
                await browser.close()

    except Exception as e:
        logger.error("js_scrape_error", url=url, error=str(e))
        return []


# ─── Crawl4AI Scraper (for hard sites) ───────────────────────────────

async def scrape_crawl4ai(url: str, source_id: str) -> List[Dict]:
    """Scrape using Crawl4AI for sites that need stealth/anti-bot."""
    try:
        from crawl4ai import AsyncWebCrawler

        async with AsyncWebCrawler(
            verbose=False,
            headless=True,
            use_managed_browser=True,
        ) as crawler:
            result = await crawler.arun(url=url)

            if result.success:
                # Crawl4AI returns clean markdown
                text = result.markdown or result.cleaned_html or ""
                vehicles = extract_vehicles(text, url, source_id)
                logger.info("crawl4ai_ok", url=url, vehicles=len(vehicles))
                return vehicles
            else:
                logger.warn("crawl4ai_failed", url=url, error=result.error_message)
                return []

    except ImportError:
        logger.warn("crawl4ai_not_available")
        return []
    except Exception as e:
        logger.error("crawl4ai_error", url=url, error=str(e))
        return []


# ─── SQLite Queue ─────────────────────────────────────────────────────

class VehicleQueue:
    """SQLite-backed queue shared with Python pipeline and Go scrapers."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_table()

    def _ensure_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                ingested_at TEXT,
                error TEXT
            )
        """)
        self.conn.commit()

    def enqueue(self, vehicle: Dict, source: str) -> int:
        """Add a vehicle to the queue. Returns the row ID."""
        payload = json.dumps(vehicle, default=str)
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            "INSERT INTO ingestion_queue (payload, status, source, created_at) VALUES (?, 'pending', ?, ?)",
            (payload, source, now)
        )
        self.conn.commit()
        return cursor.lastrowid

    def enqueue_batch(self, vehicles: List[Dict], source: str) -> int:
        """Add multiple vehicles. Returns count inserted."""
        now = datetime.now(timezone.utc).isoformat()
        count = 0
        for v in vehicles:
            payload = json.dumps(v, default=str)
            self.conn.execute(
                "INSERT INTO ingestion_queue (payload, status, source, created_at) VALUES (?, 'pending', ?, ?)",
                (payload, source, now)
            )
            count += 1
        self.conn.commit()
        return count

    def get_all_plates(self) -> Dict[str, Set[str]]:
        """Get all normalized plates grouped by source."""
        plate_to_sources = defaultdict(set)
        cursor = self.conn.execute(
            "SELECT payload, source FROM ingestion_queue WHERE status != 'synthetic'"
        )
        for row in cursor:
            try:
                data = json.loads(row[0])
                plate = data.get("normalized_plate", "")
                source = row[1]
                if plate:
                    plate_to_sources[plate].add(source)
            except:
                pass
        return plate_to_sources

    def count_by_source(self) -> Dict[str, int]:
        cursor = self.conn.execute(
            "SELECT source, COUNT(*) FROM ingestion_queue GROUP BY source ORDER BY COUNT(*) DESC"
        )
        return dict(cursor.fetchall())

    def count_unique_plates(self) -> int:
        cursor = self.conn.execute(
            "SELECT COUNT(DISTINCT json_extract(payload, '$.normalized_plate')) FROM ingestion_queue"
        )
        return cursor.fetchone()[0]

    def clear_synthetic(self):
        """Remove any synthetic/fake data from the queue."""
        cursor = self.conn.execute(
            "DELETE FROM ingestion_queue WHERE source = 'synthetic' OR source = 'seed'"
        )
        self.conn.commit()
        return cursor.rowcount

    def close(self):
        self.conn.close()


# ─── Cross-Lender Overlap Detection (REAL FRAUD) ────────────────────

def detect_cross_lender_overlap(queue: VehicleQueue) -> List[Dict]:
    """Detect vehicles appearing across multiple lenders — the REAL fraud signal.

    Loan stacking fraud: same plate pledged to 2+ lenders within 14 days.
    """
    plate_to_sources = queue.get_all_plates()

    overlaps = []
    for plate, sources in plate_to_sources.items():
        if len(sources) >= 2:
            overlaps.append({
                "normalized_plate": plate,
                "sources": sorted(sources),
                "source_count": len(sources),
                "fraud_type": "CROSS_LENDER_OVERLAP",
                "severity": "HIGH" if len(sources) >= 3 else "MEDIUM",
                "description": f"Plate {plate} found at {len(sources)} lenders: {', '.join(sorted(sources))}",
            })

    return sorted(overlaps, key=lambda x: -x["source_count"])


# ─── Main Pipeline ────────────────────────────────────────────────────

async def scrape_source(source_id: str, config: Dict) -> Tuple[str, List[Dict]]:
    """Scrape a single source and return vehicles."""
    all_vehicles = []
    js_rendered = config.get("js_rendered", False)
    delay = config.get("delay", 3)

    for url in config["urls"]:
        logger.info("scraping", source=source_id, url=url, js=js_rendered)

        if js_rendered:
            # Try Playwright first
            vehicles = await scrape_js(url, source_id, wait_seconds=delay)

            # If Playwright fails or returns 0, try Crawl4AI
            if not vehicles:
                logger.info("try_crawl4ai_fallback", source=source_id, url=url)
                vehicles = await scrape_crawl4ai(url, source_id)
        else:
            # Static HTML
            vehicles = await scrape_static(url, source_id)

        all_vehicles.extend(vehicles)

        # Rate limiting between URLs
        await asyncio.sleep(delay)

    # Deduplicate by normalized plate within this source
    seen = set()
    deduped = []
    for v in all_vehicles:
        plate = v.get("normalized_plate", "")
        if plate and plate not in seen:
            seen.add(plate)
            deduped.append(v)

    return source_id, deduped


async def run_pipeline(queue_path: str = "", sources_to_scrape: List[str] = None):
    """Run the full scraping pipeline."""
    if not queue_path:
        queue_path = "/home/z/my-project/data/ingestion_queue.db"

    queue = VehicleQueue(queue_path)

    # Clear any synthetic data
    cleared = queue.clear_synthetic()
    if cleared:
        logger.info("cleared_synthetic_data", count=cleared)

    # Determine which sources to scrape
    if sources_to_scrape:
        sources = {k: v for k, v in SOURCES.items() if k in sources_to_scrape}
    else:
        sources = SOURCES

    print(f"\n{'═' * 70}")
    print(f" Kenya Vehicle Risk Engine — Real Data Pipeline")
    print(f"{'═' * 70}")
    print(f"  Sources: {len(sources)}")
    print(f"  Queue: {queue_path}")
    print(f"  Method: httpx (static) + Playwright (JS) + Crawl4AI (stealth)")
    print(f"{'═' * 70}\n")

    # Scrape all sources concurrently (with rate limiting per source)
    tasks = []
    for source_id, config in sources.items():
        tasks.append(scrape_source(source_id, config))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
    total_vehicles = 0
    total_queued = 0
    all_vehicles_by_source: Dict[str, List[Dict]] = {}

    print(f"\n{'═' * 70}")
    print(f" Scraping Results")
    print(f"{'═' * 70}")

    for result in results:
        if isinstance(result, Exception):
            logger.error("source_failed", error=str(result))
            continue

        source_id, vehicles = result
        all_vehicles_by_source[source_id] = vehicles
        total_vehicles += len(vehicles)

        # Queue to SQLite
        if vehicles:
            queued = queue.enqueue_batch(vehicles, source_id)
            total_queued += queued

        source_name = SOURCES[source_id]["name"]
        print(f"  {source_name:30s} {len(vehicles):4d} vehicles")

    print(f"\n  {'TOTAL':30s} {total_vehicles:4d} vehicles")
    print(f"  {'Queued to SQLite':30s} {total_queued:4d}")

    # ─── Cross-Lender Overlap Detection ─────────────────────────────
    overlaps = detect_cross_lender_overlap(queue)

    print(f"\n{'═' * 70}")
    print(f" Cross-Lender Overlap (REAL Fraud Signal)")
    print(f"{'═' * 70}")

    if overlaps:
        print(f"  ⚠ Found {len(overlaps)} plates across 2+ lenders!")
        for o in overlaps[:30]:
            print(f"    {o['severity']:6s} | {o['normalized_plate']:10s} | {o['source_count']} lenders: {', '.join(o['sources'])}")
    else:
        print(f"  ❌ Zero cross-lender overlap — no real fraud signal yet")
        print(f"  → Need more sources, more time-series data, or more scrapes")

    # ─── Queue Stats ─────────────────────────────────────────────────
    by_source = queue.count_by_source()
    unique_plates = queue.count_unique_plates()

    print(f"\n{'═' * 70}")
    print(f" Queue Summary")
    print(f"{'═' * 70}")
    print(f"  Unique normalized plates: {unique_plates}")
    print(f"  Sources in queue:")
    for src, count in by_source.items():
        print(f"    {src:30s} {count:4d}")

    # ─── Save Overlaps ───────────────────────────────────────────────
    if overlaps:
        overlap_path = "/home/z/my-project/data/cross_lender_overlaps.json"
        with open(overlap_path, "w") as f:
            json.dump(overlaps, f, indent=2, default=str)
        print(f"\n  Overlaps saved to: {overlap_path}")

    # Save scrape summary
    summary = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "total_vehicles": total_vehicles,
        "total_queued": total_queued,
        "unique_plates": unique_plates,
        "cross_lender_overlaps": len(overlaps),
        "per_source": {k: len(v) for k, v in all_vehicles_by_source.items()},
    }
    summary_path = "/home/z/my-project/data/scrape_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    queue.close()

    print(f"\n  Summary saved to: {summary_path}")
    print(f"{'═' * 70}\n")

    return summary


# ─── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Real Vehicle Scraper — Kenya")
    parser.add_argument("--sources", default="", help="Comma-separated source IDs (default: all)")
    parser.add_argument("--queue", default="", help="SQLite queue path")
    parser.add_argument("--list", action="store_true", help="List available sources")
    args = parser.parse_args()

    if args.list:
        print("\nAvailable sources:")
        for sid, conf in SOURCES.items():
            js = "JS" if conf["js_rendered"] else "static"
            print(f"  {sid:20s} {conf['name']:30s} [{js}] {len(conf['urls'])} URLs")
        sys.exit(0)

    sources_list = [s.strip() for s in args.sources.split(",") if s.strip()] or None

    asyncio.run(run_pipeline(queue_path=args.queue, sources_to_scrape=sources_list))
