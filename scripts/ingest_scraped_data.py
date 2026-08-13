"""
Neo4j Ingestion Pipeline for Vehicle Collateral Risk Engine
Consumes resolved records from the ingestion queue and writes them into
the Neo4j property graph.

Node types created:
  - Vehicle      (normalizedPlate, make, model, year, plateCategory, countyCode)
  - Registration (normalizedPlate)
  - ChassisNumber(normalizedChassis)
  - AuctionListing(listingId)
  - Lender       (lenderId, name, type)

Relationships:
  - (Registration)-[:REGISTERED_AS]->(Vehicle)
  - (ChassisNumber)-[:IDENTIFIES]->(Vehicle)
  - (AuctionListing)-[:FOR_VEHICLE]->(Vehicle)
  - (Lender)-[:LENT_AGAINST]->(Vehicle)

Usage:
    python ingest_scraped_data.py --mode test
    python ingest_scraped_data.py --mode batch --limit 200
    python ingest_scraped_data.py --mode count
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from neo4j import GraphDatabase, Driver, ManagedTransaction
import structlog

log = structlog.get_logger(__name__)

# ─── Neo4j Config ──────────────────────────────────────────────────────

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "riskengine2026"
NEO4J_DATABASE = "riskengine"

# ─── Cypher Statements ─────────────────────────────────────────────────

SCHEMA_CYPHER = [
    """CREATE CONSTRAINT vehicle_plate_unique IF NOT EXISTS
       FOR (v:Vehicle) REQUIRE v.normalizedPlate IS UNIQUE""",
    """CREATE CONSTRAINT vehicle_chassis_unique IF NOT EXISTS
       FOR (v:Vehicle) REQUIRE v.normalizedChassis IS UNIQUE""",
    """CREATE CONSTRAINT registration_plate_unique IF NOT EXISTS
       FOR (r:Registration) REQUIRE r.normalizedPlate IS UNIQUE""",
    """CREATE CONSTRAINT chassis_number_unique IF NOT EXISTS
       FOR (c:ChassisNumber) REQUIRE c.normalizedChassis IS UNIQUE""",
    """CREATE CONSTRAINT lender_id_unique IF NOT EXISTS
       FOR (l:Lender) REQUIRE l.lenderId IS UNIQUE""",
    """CREATE CONSTRAINT auction_id_unique IF NOT EXISTS
       FOR (a:AuctionListing) REQUIRE a.listingId IS UNIQUE""",
]

MERGE_VEHICLE_CYPHER = """
MERGE (v:Vehicle {normalizedPlate: $normalizedPlate})
SET v.make           = COALESCE($make, v.make),
    v.model          = COALESCE($model, v.model),
    v.year           = COALESCE($year, v.year),
    v.plateCategory  = COALESCE($plateCategory, v.plateCategory),
    v.countyCode     = COALESCE($countyCode, v.countyCode),
    v.rawPlate       = COALESCE($rawPlate, v.rawPlate),
    v.normalizedChassis = COALESCE($chassis, v.normalizedChassis),
    v.updatedAt      = datetime()
"""

MERGE_REGISTRATION_CYPHER = """
MERGE (r:Registration {normalizedPlate: $normalizedPlate})
ON CREATE SET r.createdAt = datetime()
MERGE (v:Vehicle {normalizedPlate: $normalizedPlate})
MERGE (r)-[:REGISTERED_AS]->(v)
"""

MERGE_CHASSIS_CYPHER = """
MERGE (c:ChassisNumber {normalizedChassis: $normalizedChassis})
ON CREATE SET c.createdAt = datetime()
MERGE (v:Vehicle {normalizedPlate: $normalizedPlate})
MERGE (c)-[:IDENTIFIES]->(v)
"""

MERGE_AUCTION_CYPHER = """
MERGE (a:AuctionListing {listingId: $listingId})
SET a.auctionHouse   = COALESCE($auctionHouse, a.auctionHouse),
    a.listedDate     = COALESCE($listedDate, a.listedDate),
    a.reservePrice   = COALESCE($reservePrice, a.reservePrice),
    a.updatedAt      = datetime()
MERGE (v:Vehicle {normalizedPlate: $normalizedPlate})
MERGE (a)-[:FOR_VEHICLE]->(v)
"""

MERGE_LENDER_CYPHER = """
MERGE (l:Lender {lenderId: $lenderId})
SET l.name   = COALESCE($name, l.name),
    l.type   = COALESCE($lenderType, l.type),
    l.updatedAt = datetime()
MERGE (v:Vehicle {normalizedPlate: $normalizedPlate})
MERGE (l)-[:LENT_AGAINST]->(v)
"""

COUNT_VEHICLES_CYPHER = """
MATCH (v:Vehicle) RETURN count(v) AS cnt
"""

# ─── Neo4j Client ──────────────────────────────────────────────────────

class Neo4jIngestClient:
    """Thin wrapper over neo4j-driver for the vehicle ingestion pipeline."""

    def __init__(
        self,
        uri: str = NEO4J_URI,
        user: str = NEO4J_USER,
        password: str = NEO4J_PASSWORD,
        database: str = NEO4J_DATABASE,
    ):
        self._uri = uri
        self._database = database
        self._driver: Optional[Driver] = None
        try:
            self._driver = GraphDatabase.driver(
                uri,
                auth=(user, password),
                max_connection_pool_size=50,
                connection_acquisition_timeout=10_000,
                max_transaction_retry_time=15_000,
            )
            log.info("neo4j_driver_created", uri=uri)
        except Exception as exc:
            log.error("neo4j_driver_create_failed", uri=uri, error=str(exc))
            raise

    # ── Connection management ───────────────────────────────────────

    def close(self) -> None:
        if self._driver:
            self._driver.close()
            self._driver = None
            log.info("neo4j_driver_closed")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ── Health check ────────────────────────────────────────────────

    def health_check(self) -> Dict[str, Any]:
        """Test connectivity; return {connected, version}."""
        try:
            with self._driver.session(database=self._database) as session:
                result = session.run("CALL dbms.components() YIELD name, versions RETURN name, versions")
                record = result.single()
                return {
                    "connected": True,
                    "name": record["name"] if record else None,
                    "versions": record["versions"] if record else [],
                }
        except Exception as exc:
            log.error("neo4j_health_check_failed", error=str(exc))
            return {"connected": False, "error": str(exc)}

    # ── Schema ──────────────────────────────────────────────────────

    def initialise_schema(self) -> None:
        """Create constraints/indexes (idempotent)."""
        with self._driver.session(database=self._database) as session:
            for stmt in SCHEMA_CYPHER:
                try:
                    session.run(stmt)
                except Exception as exc:
                    # Constraint may already exist
                    log.warning("schema_statement_warning", stmt=stmt[:60], error=str(exc))
        log.info("schema_initialised")

    # ── Single-record ingestion ─────────────────────────────────────

    def ingest_vehicle(self, payload: Dict[str, Any]) -> None:
        """Ingest one scraped vehicle record into Neo4j.

        Expected payload keys (all optional except normalizedPlate):
          normalizedPlate, rawPlate, make, model, year,
          plateCategory, countyCode, chassis,
          auctionListingId, auctionHouse, listedDate, reservePrice,
          lenderId, lenderName, lenderType
        """
        plate = payload.get("normalizedPlate", "")
        if not plate:
            log.warning("skip_no_plate", payload=payload)
            return

        with self._driver.session(database=self._database) as session:
            # Vehicle node
            session.run(MERGE_VEHICLE_CYPHER, {
                "normalizedPlate": plate,
                "rawPlate": payload.get("rawPlate", ""),
                "make": payload.get("make", ""),
                "model": payload.get("model", ""),
                "year": payload.get("year"),
                "plateCategory": payload.get("plateCategory", ""),
                "countyCode": payload.get("countyCode", ""),
                "chassis": payload.get("chassis", ""),
            })

            # Registration node + relationship
            session.run(MERGE_REGISTRATION_CYPHER, {
                "normalizedPlate": plate,
            })

            # ChassisNumber node (if present)
            chassis = payload.get("chassis", "")
            if chassis:
                session.run(MERGE_CHASSIS_CYPHER, {
                    "normalizedChassis": chassis,
                    "normalizedPlate": plate,
                })

            # AuctionListing (if present)
            listing_id = payload.get("auctionListingId")
            if listing_id:
                session.run(MERGE_AUCTION_CYPHER, {
                    "listingId": listing_id,
                    "auctionHouse": payload.get("auctionHouse", ""),
                    "listedDate": payload.get("listedDate"),
                    "reservePrice": payload.get("reservePrice"),
                    "normalizedPlate": plate,
                })

            # Lender (if present)
            lender_id = payload.get("lenderId")
            if lender_id:
                session.run(MERGE_LENDER_CYPHER, {
                    "lenderId": lender_id,
                    "name": payload.get("lenderName", ""),
                    "lenderType": payload.get("lenderType", ""),
                    "normalizedPlate": plate,
                })

        log.info("vehicle_ingested", plate=plate)

    # ── Batch ingestion ─────────────────────────────────────────────

    def ingest_batch(self, records: List[Dict[str, Any]]) -> Dict[str, int]:
        """Ingest a list of resolved records. Returns {success, skipped, errors}."""
        success = 0
        skipped = 0
        errors = 0

        for rec in records:
            payload = rec.get("payload", rec)
            plate = payload.get("normalizedPlate", "")
            if not plate:
                skipped += 1
                continue
            try:
                self.ingest_vehicle(payload)
                success += 1
            except Exception as exc:
                errors += 1
                log.error("batch_ingest_error", plate=plate, error=str(exc))

        log.info("batch_ingested", success=success, skipped=skipped, errors=errors)
        return {"success": success, "skipped": skipped, "errors": errors}

    # ── Counts ──────────────────────────────────────────────────────

    def count_vehicles(self) -> int:
        """Return total Vehicle node count."""
        with self._driver.session(database=self._database) as session:
            result = session.run(COUNT_VEHICLES_CYPHER)
            record = result.single()
            return record["cnt"] if record else 0


# ─── Pipeline: Queue → Neo4j ───────────────────────────────────────────

def run_ingestion_loop(limit: int = 200) -> Dict[str, int]:
    """Dequeue resolved records from SQLite queue and ingest into Neo4j."""
    # Import here to avoid circular imports at module level
    sys.path.insert(0, "/home/z/my-project/scripts")
    from queue import dequeue_for_neo4j, mark_ingested, mark_error

    records = dequeue_for_neo4j(limit=limit)
    if not records:
        log.info("no_resolved_records_to_ingest")
        return {"success": 0, "skipped": 0, "errors": 0}

    with Neo4jIngestClient() as client:
        result = client.ingest_batch(records)
        # Mark successfully ingested
        successful_ids = [r["id"] for r in records[:result["success"]]]
        if successful_ids:
            mark_ingested(successful_ids)

    return result


# ─── CLI ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )

    parser = argparse.ArgumentParser(description="Neo4j Ingestion Pipeline")
    parser.add_argument("--mode", choices=["test", "batch", "count"], default="test")
    parser.add_argument("--limit", type=int, default=200, help="Max records to process in batch mode")
    args = parser.parse_args()

    if args.mode == "test":
        print("Testing Neo4j connectivity...")
        client = Neo4jIngestClient()
        health = client.health_check()
        client.close()
        print(json.dumps(health, indent=2, default=str))
        if health.get("connected"):
            print("Neo4j connection OK")
        else:
            print("Neo4j connection FAILED", file=sys.stderr)
            sys.exit(1)

    elif args.mode == "count":
        client = Neo4jIngestClient()
        cnt = client.count_vehicles()
        client.close()
        print(f"Vehicle nodes in Neo4j: {cnt}")

    elif args.mode == "batch":
        result = run_ingestion_loop(limit=args.limit)
        print(json.dumps(result, indent=2))
