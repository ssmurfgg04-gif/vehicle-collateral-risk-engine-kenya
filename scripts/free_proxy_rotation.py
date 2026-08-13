"""
Free Proxy Rotation for Kenya Vehicle Collateral Risk Engine

Replaces Bright Data (paid) with a free proxy rotation system:

  1. Free Proxy Lists (no signup required):
     - free-proxy-list.net (rotating datacenter proxies)
     - proxyscrape.com API (free tier: 1000 proxies/day)
     - geonode.com/free-proxy-list (filtered by country)
     
  2. WebShare (free tier, requires signup):
     - 10 free proxies, rotating
     - Signup via temp-mail if needed
     
  3. Tor Network (for government sites):
     - Built-in SOCKS5 proxy
     - Slower but reliable for sensitive sources (KRA, Gazette)

  4. Direct Connection (fallback):
     - For Kenyan sites that don't block non-proxy traffic

Proxy selection strategy:
  - Government sites (KRA, Gazette) → Tor (slowest but most reliable)
  - Bank sites (Equity, KCB, Family) → Free rotating proxies
  - Auctioneers → Direct or datacenter proxy
  - On proxy failure → try next proxy, then fallback to direct

Usage:
    python free_proxy_rotation.py                          # Fetch and test proxies
    python free_proxy_rotation.py --source kra_disposals   # Get proxy for a source
    python free_proxy_rotation.py --test-all               # Test all cached proxies
    python free_proxy_rotation.py --install-tor             # Install Tor
"""

import argparse
import asyncio
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

import structlog

logger = structlog.get_logger("free_proxy_rotation")

# ─── Proxy Data Classes ───────────────────────────────────────────────

@dataclass
class Proxy:
    """A single proxy with metadata and health tracking."""
    host: str
    port: int
    protocol: str  # http, https, socks5, socks4
    country: str = ""
    anonymity: str = ""  # transparent, anonymous, elite
    latency_ms: int = 0
    success_count: int = 0
    fail_count: int = 0
    last_checked: str = ""
    last_success: str = ""
    source: str = ""  # Where we got this proxy
    alive: bool = True

    @property
    def url(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}"

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.0

    def to_dict(self) -> Dict:
        return {
            "host": self.host,
            "port": self.port,
            "protocol": self.protocol,
            "country": self.country,
            "anonymity": self.anonymity,
            "latency_ms": self.latency_ms,
            "success_rate": self.success_rate,
            "alive": self.alive,
            "source": self.source,
        }


# ─── Cache File ───────────────────────────────────────────────────────

CACHE_DIR = Path("/home/z/my-project/data/proxies")
CACHE_FILE = CACHE_DIR / "proxy_cache.json"


def load_cache() -> List[Proxy]:
    """Load proxy cache from disk."""
    if not CACHE_FILE.exists():
        return []
    try:
        with open(CACHE_FILE) as f:
            data = json.load(f)
        proxies = []
        for p in data.get("proxies", []):
            proxies.append(Proxy(
                host=p["host"], port=p["port"], protocol=p.get("protocol", "http"),
                country=p.get("country", ""), anonymity=p.get("anonymity", ""),
                latency_ms=p.get("latency_ms", 0),
                success_count=p.get("success_count", 0),
                fail_count=p.get("fail_count", 0),
                last_checked=p.get("last_checked", ""),
                last_success=p.get("last_success", ""),
                source=p.get("source", ""), alive=p.get("alive", True),
            ))
        logger.info("cache_loaded", count=len(proxies))
        return proxies
    except Exception as e:
        logger.warning("cache_load_failed", error# Proxy rotation: round-robin with health tracking
        self._rotation_index = 0
        self._source_proxy_map = {}  # source_id → preferred proxy type

        # Source-specific proxy strategy
        self._source_strategy = {
            # Government sites → Tor (most reliable, slowest)
            "kra_disposals": {"preferred": "socks5", "fallback": "http", "use_tor": True},
            "kenya_gazette": {"preferred": "socks5", "fallback": "http", "use_tor": True},
            # Bank sites → HTTP/HTTPS proxies
            "equity_bank": {"preferred": "http", "fallback": "direct", "use_tor": False},
            "family_bank": {"preferred": "http", "fallback": "direct", "use_tor": False},
            "kcb_bank": {"preferred": "http", "fallback": "direct", "use_tor": False},
            "ncba_bank": {"preferred": "http", "fallback": "direct", "use_tor": False},
            "coop_bank": {"preferred": "http", "fallback": "direct", "use_tor": False},
            # Auctioneers → Direct or datacenter
            "garam_auctioneers": {"preferred": "direct", "fallback": "http", "use_tor": False},
        }

    async def initialize(self):
        """Load cache and fetch fresh proxies if needed."""
        self._proxies = load_cache()

        # If cache is stale (> 1 hour) or empty, fetch fresh
        if not self._proxies or self._is_cache_stale():
            await self.fetch_proxies()

        logger.info("rotation_initialized",
                    total_proxies=len(self._proxies),
                    alive=sum(1 for p in self._proxies if p.alive))

    async def fetch_proxies(self):
        """Fetch proxies from all free sources."""
        all_proxies = []

        # Source 1: ProxyScrape (no signup, 1000/day)
        proxies = await self._fetch_proxyscrape()
        all_proxies.extend(proxies)
        logger.info("fetched_proxyscrape", count=len(proxies))

        # Source 2: Geonode (filtered, no signup)
        proxies = await self._fetch_geonode()
        all_proxies.extend(proxies)
        logger.info("fetched_geonode", count=len(proxies))

        # Source 3: Free-Proxy-List (no signup)
        proxies = await self._fetch_free_proxy_list()
        all_proxies.extend(proxies)
        logger.info("fetched_free_proxy_list", count=len(proxies))

        # Merge with existing cache (keep health data)
        existing_hosts = {(p.host, p.port) for p in self._proxies}
        for p in all_proxies:
            if (p.host, p.port) not in existing_hosts:
                self._proxies.append(p)
                existing_hosts.add((p.host, p.port))

        # Save updated cache
        save_cache(self._proxies)
        logger.info("proxy_pool_updated", total=len(self._proxies))

    def get_proxy(self, source_id: str = "") -> Optional[str]:
        """Get the best proxy for a given source.
        
        Strategy:
          1. Check source-specific strategy (Tor for govt, HTTP for banks)
          2. Select best proxy by health score
          3. Fall back to direct connection if no healthy proxy
        """
        strategy = self._source_strategy.get(source_id, {
            "preferred": "http", "fallback": "direct", "use_tor": False
        })

        # If source needs Tor, check if available
        if strategy.get("use_tor") and self._tor_available:
            return "socks5://127.0.0.1:9050"

        # Get healthy proxies matching preferred protocol
        preferred = strategy.get("preferred", "http")
        candidates = [
            p for p in self._proxies
            if p.alive and p.protocol == preferred and p.success_rate > 0.3
        ]

        if not candidates:
            # Try any healthy proxy
            candidates = [p for p in self._proxies if p.alive and p.success_rate > 0.2]

        if not candidates:
            # No healthy proxies — check fallback
            if strategy.get("fallback") == "direct":
                logger.info("no_proxy_fallback_direct", source=source_id)
                return None  # Direct connection
            return None

        # Round-robin with health weighting
        # Sort by success rate (descending), then latency (ascending)
        candidates.sort(key=lambda p: (-p.success_rate, p.latency_ms))
        
        # Pick from top 3 candidates randomly (avoids always hitting same proxy)
        top_n = min(3, len(candidates))
        selected = random.choice(candidates[:top_n])

        logger.info("proxy_selected",
                   source=source_id,
                   proxy=f"{selected.host}:{selected.port}",
                   protocol=selected.protocol,
                   success_rate=f"{selected.success_rate:.2f}",
                   latency_ms=selected.latency_ms)

        return selected.url

    def mark_success(self, proxy_url: str, latency_ms: int = 0):
        """Mark a proxy as successful for health tracking."""
        for p in self._proxies:
            if p.url == proxy_url:
                p.success_count += 1
                p.last_success = datetime.utcnow().isoformat()
                if latency_ms:
                    p.latency_ms = latency_ms
                break
        save_cache(self._proxies)

    def mark_failure(self, proxy_url: str):
        """Mark a proxy as failed."""
        for p in self._proxies:
            if p.url == proxy_url:
                p.fail_count += 1
                if p.fail_count > 5 and p.success_rate < 0.2:
                    p.alive = False
                    logger.warning("proxy_dead", proxy=p.url)
                break
        save_cache(self._proxies)

    async def test_proxy(self, proxy: Proxy, test_url: str = "https://www.kra.go.ke") -> bool:
        """Test if a proxy is working by making a request to a Kenyan site."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                start = time.time()
                async with session.get(
                    test_url,
                    proxy=proxy.url,
                    timeout=aiohttp.ClientTimeout(total=15),
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                ) as resp:
                    latency = int((time.time() - start) * 1000)
                    if resp.status == 200:
                        proxy.success_count += 1
                        proxy.latency_ms = latency
                        proxy.last_success = datetime.utcnow().isoformat()
                        proxy.last_checked = datetime.utcnow().isoformat()
                        proxy.alive = True
                        return True
                    else:
                        proxy.fail_count += 1
                        proxy.last_checked = datetime.utcnow().isoformat()
                        return False
        except Exception:
            proxy.fail_count += 1
            proxy.last_checked = datetime.utcnow().isoformat()
            return False

    async def test_all(self) -> Dict:
        """Test all cached proxies and return health summary."""
        if not self._proxies:
            return {"total": 0, "alive": 0, "dead": 0}

        logger.info("testing_all_proxies", count=len(self._proxies))
        alive_count = 0

        for proxy in self._proxies:
            is_alive = await self.test_proxy(proxy)
            if is_alive:
                alive_count += 1

        dead_count = len(self._proxies) - alive_count
        save_cache(self._proxies)

        summary = {
            "total": len(self._proxies),
            "alive": alive_count,
            "dead": dead_count,
            "by_protocol": defaultdict(int),
            "by_source": defaultdict(int),
        }
        for p in self._proxies:
            if p.alive:
                summary["by_protocol"][p.protocol] += 1
                summary["by_source"][p.source] += 1

        logger.info("test_complete", **{k: v for k, v in summary.items() if k != "by_protocol"})
        return summary

    def _is_cache_stale(self) -> bool:
        """Check if the proxy cache is older than 1 hour."""
        if not CACHE_FILE.exists():
            return True
        try:
            with open(CACHE_FILE) as f:
                data = json.load(f)
            cached_at = data.get("cached_at", "")
            if not cached_at:
                return True
            age = datetime.utcnow() - datetime.fromisoformat(cached_at)
            return age > timedelta(hours=1)
        except Exception:
            return True

    async def _fetch_proxyscrape(self) -> List[Proxy]:
        """Fetch proxies from ProxyScrape (free, no signup)."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                url = "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        return []
                    text = await resp.text()
                    proxies = []
                    for line in text.strip().split("\n"):
                        line = line.strip()
                        if ":" in line:
                            parts = line.split(":")
                            if len(parts) >= 2:
                                try:
                                    proxies.append(Proxy(
                                        host=parts[0], port=int(parts[1]),
                                        protocol="http", source="proxyscrape",
                                    ))
                                except ValueError:
                                    continue
                    return proxies
        except Exception as e:
            logger.warning("proxyscrape_failed", error=str(e))
            return []

    async def _fetch_geonode(self) -> List[Proxy]:
        """Fetch proxies from Geonode (free, no signup, country-filtered)."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                url = "https://proxylist.geonode.com/free-proxy-list?limit=50&page=1&sort_by=lastChecked&sort_type=desc&protocols=http%2Chttps"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    proxies = []
                    for p in data.get("data", []):
                        try:
                            proxies.append(Proxy(
                                host=p["ip"], port=int(p["port"]),
                                protocol=p.get("protocols", ["http"])[0],
                                country=p.get("country", ""),
                                anonymity=p.get("anonymityLevel", ""),
                                source="geonode",
                            ))
                        except (KeyError, ValueError, IndexError):
                            continue
                    return proxies
        except Exception as e:
            logger.warning("geonode_failed", error=str(e))
            return []

    async def _fetch_free_proxy_list(self) -> List[Proxy]:
        """Fetch proxies from free-proxy-list.net (no signup)."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                url = "https://free-proxy-list.net/"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        return []
                    text = await resp.text()
                    # Parse the table — look for IP:port patterns
                    pattern = re.compile(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{2,5})')
                    proxies = []
                    for match in pattern.finditer(text):
                        host, port = match.group(1), int(match.group(2))
                        # Basic validation
                        if not host.startswith(("10.", "192.168.", "172.")):
                            proxies.append(Proxy(
                                host=host, port=port,
                                protocol="http", source="free_proxy_list",
                            ))
                    return proxies[:100]  # Limit to 100
        except Exception as e:
            logger.warning("free_proxy_list_failed", error=str(e))
            return []


# ─── Tor Installation ─────────────────────────────────────────────────

def install_tor():
    """Install and configure Tor for SOCKS5 proxy access."""
    print("Installing Tor for SOCKS5 proxy access...")
    print("  (Government sites like KRA and Gazette work best through Tor)")

    # Install Tor
    subprocess.run(["apt-get", "install", "-y", "tor"], check=False, capture_output=True)

    # Configure Tor for our use case
    torrc = """
# Kenya Risk Engine — Tor Configuration
SocksPort 9050
ControlPort 9051
CookieAuthentication 1

# Exit through specific countries for better reliability
# Kenya is not available, so use nearby African countries
ExitNodes {za},{ug},{tz}
StrictNodes 0

# Circuit build timeout (faster for scraping)
CircuitBuildTimeout 30
CircuitStreamTimeout 30

# New circuit every 10 minutes (rotate IP)
MaxCircuitDirtiness 600
"""
    torrc_path = "/etc/tor/torrc.d/kenya-risk-engine.conf"
    try:
        os.makedirs(os.path.dirname(torrc_path), exist_ok=True)
        with open(torrc_path, "w") as f:
            f.write(torrc)
        print(f"  Tor config written to {torrc_path}")
    except PermissionError:
        print("  (Need sudo for Tor config — using default config)")

    # Restart Tor
    subprocess.run(["systemctl", "restart", "tor"], check=False, capture_output=True)

    # Wait for Tor to start
    time.sleep(3)

    # Test Tor connection
    try:
        import urllib.request
        proxy_handler = urllib.request.ProxyHandler({
            'http': 'socks5://127.0.0.1:9050',
            'https': 'socks5://127.0.0.1:9050',
        })
        opener = urllib.request.build_opener(proxy_handler)
        # Check Tor via check.torproject.org
        resp = opener.open("https://check.torproject.org/", timeout=15)
        if "Congratulations" in resp.read().decode():
            print("  Tor is working! SOCKS5 proxy: socks5://127.0.0.1:9050")
        else:
            print("  Tor is running but not being used as exit node")
    except Exception as e:
        print(f"  Tor test failed: {e}")
        print("  You may need to start Tor manually: sudo systemctl start tor")


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

    parser = argparse.ArgumentParser(description="Free Proxy Rotation")
    parser.add_argument("--source", type=str, default="",
                        help="Source ID to get proxy for")
    parser.add_argument("--test-all", action="store_true",
                        help="Test all cached proxies")
    parser.add_argument("--install-tor", action="store_true",
                        help="Install and configure Tor")
    parser.add_argument("--fetch", action="store_true",
                        help="Fetch fresh proxies")
    args = parser.parse_args()

    if args.install_tor:
        install_tor()
        return

    print(f"\n{'='*70}")
    print(f" Free Proxy Rotation — Bright Data Alternative")
    print(f" Sources: ProxyScrape + Geonode + Free-Proxy-List + Tor")
    print(f"{'='*70}\n")

    rotation = ProxyRotation()

    if args.test_all:
        asyncio.run(rotation.initialize())
        summary = asyncio.run(rotation.test_all())
        print(f"  Total proxies:   {summary['total']}")
        print(f"  Alive:           {summary['alive']}")
        print(f"  Dead:            {summary['dead']}")
        for proto, count in summary.get("by_protocol", {}).items():
            print(f"    {proto}: {count} alive")

    elif args.fetch:
        asyncio.run(rotation.initialize())
        print(f"  Proxies available: {len(rotation._proxies)}")
        print(f"  Alive: {sum(1 for p in rotation._proxies if p.alive)}")

    elif args.source:
        asyncio.run(rotation.initialize())
        proxy = rotation.get_proxy(args.source)
        if proxy:
            print(f"  Proxy for {args.source}: {proxy}")
        else:
            print(f"  No proxy available for {args.source} — using direct connection")

    else:
        # Default: initialize and show summary
        asyncio.run(rotation.initialize())
        alive = sum(1 for p in rotation._proxies if p.alive)
        print(f"  Cached proxies:   {len(rotation._proxies)}")
        print(f"  Alive:            {alive}")
        print(f"  Tor available:    {rotation._tor_available}")

        # Show per-source proxy strategy
        print(f"\n  Per-Source Strategy:")
        for source, strategy in rotation._source_strategy.items():
            tor_flag = " (via Tor)" if strategy.get("use_tor") else ""
            print(f"    {source:25s} → {strategy['preferred']}{tor_flag}")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
