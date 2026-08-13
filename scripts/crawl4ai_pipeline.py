"""
Crawl4AI Integration for Kenya Gazette PDF → Structured Extraction

Replaces the Tesseract OCR + spaCy NER pipeline with Crawl4AI's native
PDF → structured markdown/JSON extraction. Crawl4AI handles:
  - PDF rendering and text extraction
  - Anti-bot detection built-in
  - Structured markdown/JSON output
  - JavaScript-rendered pages (for gazette search portals)
  - Headless browser with stealth mode

This is Apache 2.0 licensed (crawl4ai) — no commercial restrictions.

Architecture:
  Kenya Gazette PDF → Crawl4AI → structured JSON → vehicle parser → SQLite queue

Usage:
    python crawl4ai_pipeline.py                              # Full pipeline
    python crawl4ai_pipeline.py --source gazette              # Kenya Gazette only
    python crawl4ai_pipeline.py --source kra                  # KRA notices only
    python crawl4ai_pipeline.py --source all                  # All sources
    python crawl4ai_pipeline.py --url https://gazettes.africa/go/kenya  # Single URL
    python crawl4ai_pipeline.py --install                     # Install crawl4ai + deps
"""

import argparse
import json
import os
import re
import sys
import time
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from collections import defaultdict

import structlog

logger = structlog.get_logger("crawl4ai_pipeline")

# ─── Kenyan Vehicle Patterns ──────────────────────────────────────────

# Kenyan plate: KXX NNNL (e.g., KDA 123J, KCX 387A, GK 123A)
PLATE_PATTERN = re.compile(r'\b([A-Z]{2,3})\s?(\d{1,3})\s?([A-Z]{1,2})\b')

# ISO 3779 chassis/VIN: 17 chars, no I/O/Q
CHASSIS_PATTERN = re.compile(r'\b([A-HJ-NPR-Z0-9]{17})\b')

# Kenyan Shilling amounts
KES_PATTERN = re.compile(r'(?:KES|KSh|Ksh\.?)\s?([\d,]+)')

# Government plate prefixes
GOVT_PREFIXES = ["GK", "GKA", "GKB", "GKN", "GKY"]

# Kenyan vehicle makes
KENYAN_MAKES = [
    "Mercedes-Benz", "Land Rover", "Range Rover", "Mercedes",
    "Mitsubishi", "Chevrolet", "Volkswagen", "Peugeot",
    "Toyota", "Nissan", "Isuzu", "Honda", "Mazda", "Subaru", "Hyundai",
    "Kia", "Suzuki", "Jeep", "Ford", "Volvo", "Audi", "Daihatsu",
    "Chery", "Lexus", "Porsche", "Tata", "Mahindra", "Scania",
    "Hino", "FAW", "MAN", "Iveco",
]

# ─── Source Definitions ───────────────────────────────────────────────

SOURCES = {
    "gazette": {
        "name": "Kenya Gazette Notices",
        "urls": [
            "https://gazettes.africa/go/kenya",
            "https://gazettes.africa.go.ke/notices",
        ],
        "type": "GOVERNMENT_GAZETTE",
        "confidence": 0.7,
        "js_rendered": True,
        "delay": 10,
    },
    "kra": {
        "name": "KRA Government Disposals",
        "urls": [
            "https://www.kra.go.ke/public-notices",
            "https://www.kra.go.ke/services/customs-and-border-control",
        ],
        "type": "GOVERNMENT_DISPOSAL",
        "confidence": 0.9,
        "js_rendered": False,
        "delay": 12,
    },
    "equity_bank": {
        "name": "Equity Bank Vehicle Listings",
        "urls": [
            "https://equitybank.co.ke/vehicle-logbook-loans",
            "https://ke.equitybankgroup.com/vehicle-loans",
        ],
        "type": "BANK_REPOSSESSION",
        "confidence": 0.85,
        "js_rendered": False,
        "delay": 3,
    },
    "family_bank": {
        "name": "Family Bank Vehicle Listings",
        "urls": [
            "https://www.familybank.co.ke/?post_type=vehicles",
            "https://www.familybank.co.ke/vehicle-finance",
        ],
        "type": "BANK_REPOSSESSION",
        "confidence": 0.85,
        "js_rendered": False,
        "delay": 3,
    },
}


# ─── Plate Normalization ──────────────────────────────────────────────

def normalize_plate(raw: str) -> tuple:
    """Normalize a Kenyan registration plate with OCR corrections.
    Returns: (normalized, county_code, category)
    """
    if not raw:
        return "", "", "UNKNOWN"

    plate = raw.upper()
    for ch in " -.":
        plate = plate.replace(ch, "")

    # OCR corrections in numeric positions: O→0, I→1, Q→0
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

    # Detect government plates
    category = "PRIVATE"
    for prefix in GOVT_PREFIXES:
        if plate.startswith(prefix):
            category = "GOVERNMENT"
            break

    return plate, county, category


def normalize_chassis(raw: str) -> str:
    """Normalize a chassis/VIN number."""
    if not raw:
        return ""
    return raw.upper().replace(" ", "").replace("-", "")


# ─── Vehicle Extraction from Structured Text ─────────────────────────

def extract_vehicles_from_text(text: str, url: str, source_id: str) -> List[Dict]:
    """Extract vehicles from Crawl4AI-processed structured text.
    
    Crawl4AI returns clean markdown or structured JSON from PDFs/pages.
    We parse vehicle information from this structured output.
    """
    vehicles = []
    seen_plates = set()

    plates = PLATE_PATTERN.findall(text)
    chassis_matches = CHASSIS_PATTERN.findall(text)
    kes_matches = KES_PATTERN.findall(text)

    # Parse KES amounts
    amounts = []
    for m in kes_matches:
        clean = m.replace(",", "")
        try:
            amounts.append(int(clean))
        except ValueError:
            pass

    # Build make/model pattern
    make_pattern = "|".join(re.escape(m) for m in KENYAN_MAKES)
    listing_re = re.compile(
        rf'({make_pattern})[\s\-]+([\w\-/\.]+)(?:\s*\((\d{{4}}\))?'
    )
    make_model_matches = listing_re.findall(text)

    for i, plate_match in enumerate(plates):
        county, num, suffix = plate_match
        raw_plate = f"{county} {num}{suffix}"
        normalized, county_code, plate_category = normalize_plate(raw_plate)

        if normalized in seen_plates:
            continue
        seen_plates.add(normalized)

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

        source_conf = SOURCES.get(source_id, {})
        confidence = source_conf.get("confidence", 0.5)

        v = {
            "source": source_id,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "raw_plate": raw_plate,
            "normalized_plate": normalized,
            "county_code": county_code,
            "plate_category": plate_category,
            "chassis": chassis,
            "normalized_chassis": norm_chassis,
            "make": make,
            "model": model,
            "listing_type": source_conf.get("type", "UNKNOWN"),
            "listing_url": url,
            "confidence": confidence,
            "extraction_method": "crawl4ai",
        }
        if year:
            v["year"] = year
        if price:
            v["reserve_price_kes"] = price

        vehicles.append(v)

    return vehicles


# ─── Crawl4AI Scraper ─────────────────────────────────────────────────

async def crawl_with_crawl4ai(url: str, js_rendered: bool = False) -> Dict:
    """Crawl a URL using Crawl4AI for structured extraction.
    
    Crawl4AI handles:
      - JavaScript rendering (for gazette portals)
      - Anti-bot detection (stealth mode)
      - PDF → structured text extraction
      - CSS selector-based extraction
      - Screenshot capture for visual debugging
    """
    try:
        from crawl4ai import AsyncWebCrawler
        from crawl4ai.async_crawler_strategy import AsyncCrawlerStrategy
    except ImportError:
        logger.error("crawl4ai_not_installed", 
                     hint="pip install crawl4ai  # Apache 2.0, no commercial restrictions")
        return {"url": url, "status": "ERROR", "error": "crawl4ai not installed"}

    try:
        async with AsyncWebCrawler(
            verbose=True,
            headless=True,
            # Anti-detection settings
            use_managed_browser=True,  # Stealth browser
            # Proxy support (uses free_proxy_rotation if configured)
            proxy=os.environ.get("CRAWL4AI_PROXY", ""),
        ) as crawler:
            result = await crawler.arun(
                url=url,
                # JavaScript rendering for dynamic pages
                js_only=js_rendered,
                # Extract structured content
                word_count_threshold=5,
                # CSS selector for vehicle listing containers
                css_selector=".notice, .listing, .vehicle, article, .content",
                # Wait for dynamic content
                wait_for="networkidle" if js_rendered else None,
                # Screenshot for debugging
                screenshot=False,
                # Magic mode: auto-detect best extraction strategy
                magic=True,
            )

            if result.success:
                return {
                    "url": url,
                    "status": "SUCCESS",
                    "markdown": result.markdown,
                    "cleaned_html": result.cleaned_html,
                    "media": result.media,
                    "links": result.links,
                    "metadata": result.metadata,
                    "extracted_content": result.extracted_content,
                }
            else:
                return {
                    "url": url,
                    "status": "FAILED",
                    "error": result.error_message,
                }

    except Exception as e:
        logger.error("crawl_failed", url=url, error=str(e))
        return {"url": url, "status": "ERROR", "error": str(e)}


# ─── Pipeline Runner ──────────────────────────────────────────────────

async def run_pipeline(
    source_id: str = "all",
    single_url: Optional[str] = None,
    output_dir: str = "/home/z/my-project/scripts/scrapers/data",
) -> Dict:
    """Run the full Crawl4AI extraction pipeline."""
    start = time.time()

    all_vehicles = []
    results = []

    if single_url:
        # Single URL mode
        logger.info("crawling_single_url", url=single_url)
        crawl_result = await crawl_with_crawl4ai(single_url, js_rendered=True)

        if crawl_result["status"] == "SUCCESS":
            text = crawl_result.get("markdown", "") or crawl_result.get("extracted_content", "")
            vehicles = extract_vehicles_from_text(text, single_url, "manual")
            all_vehicles.extend(vehicles)
        results.append(crawl_result)

    else:
        # Source-based mode
        sources_to_run = SOURCES.keys() if source_id == "all" else [source_id]

        for sid in sources_to_run:
            if sid not in SOURCES:
                logger.warning("unknown_source", source=sid)
                continue

            source = SOURCES[sid]
            logger.info("crawling_source", source=sid, urls=len(source["urls"]))

            for url in source["urls"]:
                crawl_result = await crawl_with_crawl4ai(
                    url,
                    js_rendered=source.get("js_rendered", False),
                )

                if crawl_result["status"] == "SUCCESS":
                    text = crawl_result.get("markdown", "") or crawl_result.get("extracted_content", "")
                    vehicles = extract_vehicles_from_text(text, url, sid)
                    all_vehicles.extend(vehicles)
                    logger.info("extracted_vehicles", url=url, count=len(vehicles))
                else:
                    logger.warning("crawl_failed", url=url, error=crawl_result.get("error"))

                results.append(crawl_result)

                # Rate limiting between requests
                delay = source.get("delay", 5)
                logger.info("rate_limiting", delay_seconds=delay)
                await asyncio.sleep(delay)

    elapsed = time.time() - start

    # Save results
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    result_file = output_path / f"crawl4ai_results_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(result_file, "w") as f:
        json.dump({
            "engine": "crawl4ai",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": elapsed,
            "total_vehicles": len(all_vehicles),
            "vehicles": all_vehicles,
            "crawl_results": [{"url": r.get("url"), "status": r.get("status")} for r in results],
        }, f, indent=2)

    # Queue to SQLite for downstream processing
    queued = 0
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "ingestion_queue", str(Path(__file__).parent / "ingestion_queue.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        if all_vehicles:
            count, err = mod.enqueue_batch(all_vehicles, "crawl4ai_pipeline")
            if err:
                logger.error("queue_failed", error=str(err))
            else:
                queued = count
                logger.info("vehicles_queued", count=count)
    except Exception as e:
        logger.warning("queue_unavailable", error=str(e))

    logger.info("pipeline_complete",
                vehicles=len(all_vehicles),
                queued=queued,
                elapsed=f"{elapsed:.1f}s")

    return {
        "total_vehicles": len(all_vehicles),
        "queued": queued,
        "elapsed_seconds": elapsed,
        "results_file": str(result_file),
    }


def install_dependencies():
    """Install Crawl4AI and its dependencies."""
    import subprocess

    print("Installing Crawl4AI (Apache 2.0 — no commercial restrictions)...")
    packages = [
        "crawl4ai",          # Main package
        "playwright",        # Browser automation (Crawl4AI dependency)
        "beautifulsoup4",    # HTML parsing
        "lxml",              # Fast XML/HTML processing
    ]

    for pkg in packages:
        print(f"  Installing {pkg}...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", pkg], check=False)

    # Install Playwright browsers
    print("  Installing Playwright browsers (chromium)...")
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)

    print("\nCrawl4AI installation complete!")
    print("  Test: python crawl4ai_pipeline.py --url https://gazettes.africa/go/kenya")


# ─── Main ────────────────────────────────────────────────────────────

def main():
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
    )

    parser = argparse.ArgumentParser(description="Crawl4AI Pipeline for Kenya Gazette + KRA")
    parser.add_argument("--source", choices=["gazette", "kra", "equity_bank", "family_bank", "all"],
                        default="all", help="Source to crawl")
    parser.add_argument("--url", type=str, help="Single URL to crawl")
    parser.add_argument("--install", action="store_true", help="Install Crawl4AI + dependencies")
    parser.add_argument("--output-dir", type=str,
                        default="/home/z/my-project/scripts/scrapers/data")
    args = parser.parse_args()

    if args.install:
        install_dependencies()
        return

    print(f"\n{'='*70}")
    print(f" Crawl4AI Pipeline — Kenya Gazette + KRA + Banks")
    print(f" Replaces Tesseract OCR + spaCy NER with structured extraction")
    print(f"{'='*70}\n")

    result = asyncio.run(run_pipeline(
        source_id=args.source,
        single_url=args.url,
        output_dir=args.output_dir,
    ))

    print(f"\n  Results:")
    print(f"    Vehicles found:    {result['total_vehicles']}")
    print(f"    Queued to SQLite:  {result['queued']}")
    print(f"    Elapsed:           {result['elapsed_seconds']:.1f}s")
    print(f"    Results file:      {result['results_file']}")
    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
