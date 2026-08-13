"""
SQLite Ingestion Queue for Vehicle Collateral Risk Engine
Sync + Async interface with WAL-mode SQLite.

Status flow: pending → resolved → ingested
  - pending:  queued by scraper, awaiting entity resolution (Splink)
  - resolved: entity-resolved by Splink, awaiting Neo4j graph ingestion
  - ingested: fully ingested into Neo4j graph DB
  - error:    processing failed (error column populated)

Table: ingestion_queue
  id          INTEGER PRIMARY KEY AUTOINCREMENT
  payload     TEXT   (JSON blob of scraped vehicle data)
  status      TEXT   CHECK(status IN ('pending','resolved','ingested','error'))
  source      TEXT   (scraper name: e.g. 'gazette', 'auction', 'ntsa')
  created_at  TEXT   ISO-8601
  resolved_at TEXT   ISO-8601 nullable
  ingested_at TEXT   ISO-8601 nullable
  error       TEXT   nullable error message

Usage:
    python queue.py --action init
    python queue.py --action stats
"""

from __future__ import annotations

import json
import sqlite3
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import structlog

log = structlog.get_logger(__name__)

# ─── Config ────────────────────────────────────────────────────────────

DB_PATH = Path("/home/z/my-project/data/ingestion_queue.db")

VALID_STATUSES = ("pending", "resolved", "ingested", "error")

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ingestion_queue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    payload     TEXT NOT NULL,
    status      TEXT NOT NULL CHECK(status IN ('pending','resolved','ingested','error')) DEFAULT 'pending',
    source      TEXT NOT NULL DEFAULT 'unknown',
    created_at  TEXT NOT NULL,
    resolved_at TEXT,
    ingested_at TEXT,
    error       TEXT
);

CREATE INDEX IF NOT EXISTS idx_queue_status    ON ingestion_queue(status);
CREATE INDEX IF NOT EXISTS idx_queue_source    ON ingestion_queue(source);
CREATE INDEX IF NOT EXISTS idx_queue_created   ON ingestion_queue(created_at);
"""

# ─── Helpers ───────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    """Open a sync SQLite connection with WAL mode."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


# ─── Schema Init ───────────────────────────────────────────────────────

def init_db() -> None:
    """Initialise the ingestion_queue table and indexes (idempotent)."""
    conn = _connect()
    try:
        conn.executescript(CREATE_TABLE_SQL)
        conn.commit()
        log.info("queue_db_initialised", path=str(DB_PATH))
    finally:
        conn.close()


async def init_db_async() -> None:
    """Async version of init_db (runs sync in thread pool)."""
    await asyncio.to_thread(init_db)
    log.info("queue_db_initialised_async", path=str(DB_PATH))


# ─── Enqueue (pending) ─────────────────────────────────────────────────

def queue_scraped_vehicle(payload: Dict[str, Any], source: str = "unknown") -> int:
    """Insert a single scraped vehicle record as status='pending'. Returns row id."""
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO ingestion_queue (payload, status, source, created_at) VALUES (?, 'pending', ?, ?)",
            (json.dumps(payload, default=str), source, _now_iso()),
        )
        conn.commit()
        row_id = cur.lastrowid
        log.info("vehicle_queued", id=row_id, source=source)
        return row_id  # type: ignore[return-value]
    finally:
        conn.close()


def queue_scraped_batch(records: Sequence[Dict[str, Any]], source: str = "unknown") -> List[int]:
    """Bulk-insert scraped vehicles. Returns list of row ids."""
    if not records:
        return []
    conn = _connect()
    try:
        now = _now_iso()
        ids: List[int] = []
        for rec in records:
            cur = conn.execute(
                "INSERT INTO ingestion_queue (payload, status, source, created_at) VALUES (?, 'pending', ?, ?)",
                (json.dumps(rec, default=str), source, now),
            )
            ids.append(cur.lastrowid)
        conn.commit()
        log.info("batch_queued", count=len(ids), source=source, first_id=ids[0], last_id=ids[-1])
        return ids
    finally:
        conn.close()


async def queue_scraped_vehicle_async(payload: Dict[str, Any], source: str = "unknown") -> int:
    """Async version of queue_scraped_vehicle."""
    return await asyncio.to_thread(queue_scraped_vehicle, payload, source)


async def queue_scraped_batch_async(records: Sequence[Dict[str, Any]], source: str = "unknown") -> List[int]:
    """Async version of queue_scraped_batch."""
    return await asyncio.to_thread(queue_scraped_batch, records, source)


# ─── Dequeue ───────────────────────────────────────────────────────────

def dequeue_for_splink(limit: int = 100) -> List[Dict[str, Any]]:
    """Fetch up to `limit` pending records for Splink entity resolution."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, payload, source, created_at FROM ingestion_queue WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
        result = [dict(r) for r in rows]
        for r in result:
            r["payload"] = json.loads(r["payload"])
        log.info("dequeued_for_splink", count=len(result))
        return result
    finally:
        conn.close()


def dequeue_for_neo4j(limit: int = 100) -> List[Dict[str, Any]]:
    """Fetch up to `limit` resolved records for Neo4j ingestion."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, payload, source, created_at, resolved_at FROM ingestion_queue WHERE status = 'resolved' ORDER BY resolved_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
        result = [dict(r) for r in rows]
        for r in result:
            r["payload"] = json.loads(r["payload"])
        log.info("dequeued_for_neo4j", count=len(result))
        return result
    finally:
        conn.close()


async def dequeue_for_splink_async(limit: int = 100) -> List[Dict[str, Any]]:
    """Async version of dequeue_for_splink."""
    return await asyncio.to_thread(dequeue_for_splink, limit)


async def dequeue_for_neo4j_async(limit: int = 100) -> List[Dict[str, Any]]:
    """Async version of dequeue_for_neo4j."""
    return await asyncio.to_thread(dequeue_for_neo4j, limit)


# ─── Status Updates ────────────────────────────────────────────────────

def mark_resolved(ids: List[int]) -> int:
    """Transition records from pending → resolved."""
    if not ids:
        return 0
    conn = _connect()
    try:
        now = _now_iso()
        placeholders = ",".join("?" for _ in ids)
        cur = conn.execute(
            f"UPDATE ingestion_queue SET status = 'resolved', resolved_at = ? WHERE id IN ({placeholders}) AND status = 'pending'",
            [now, *ids],
        )
        conn.commit()
        log.info("marked_resolved", count=cur.rowcount, ids=ids)
        return cur.rowcount
    finally:
        conn.close()


def mark_ingested(ids: List[int]) -> int:
    """Transition records from resolved → ingested."""
    if not ids:
        return 0
    conn = _connect()
    try:
        now = _now_iso()
        placeholders = ",".join("?" for _ in ids)
        cur = conn.execute(
            f"UPDATE ingestion_queue SET status = 'ingested', ingested_at = ? WHERE id IN ({placeholders}) AND status = 'resolved'",
            [now, *ids],
        )
        conn.commit()
        log.info("marked_ingested", count=cur.rowcount, ids=ids)
        return cur.rowcount
    finally:
        conn.close()


def mark_error(id: int, error_msg: str) -> None:
    """Mark a single record as error."""
    conn = _connect()
    try:
        conn.execute(
            "UPDATE ingestion_queue SET status = 'error', error = ? WHERE id = ?",
            (error_msg, id),
        )
        conn.commit()
        log.error("marked_error", id=id, error=error_msg)
    finally:
        conn.close()


async def mark_resolved_async(ids: List[int]) -> int:
    """Async version of mark_resolved."""
    return await asyncio.to_thread(mark_resolved, ids)


async def mark_ingested_async(ids: List[int]) -> int:
    """Async version of mark_ingested."""
    return await asyncio.to_thread(mark_ingested, ids)


async def mark_error_async(id: int, error_msg: str) -> None:
    """Async version of mark_error."""
    await asyncio.to_thread(mark_error, id, error_msg)


# ─── Stats ─────────────────────────────────────────────────────────────

def get_queue_stats() -> Dict[str, Any]:
    """Return counts by status and by source."""
    conn = _connect()
    try:
        status_rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM ingestion_queue GROUP BY status"
        ).fetchall()
        status_counts = {r["status"]: r["cnt"] for r in status_rows}
        for s in VALID_STATUSES:
            status_counts.setdefault(s, 0)

        source_rows = conn.execute(
            "SELECT source, COUNT(*) as cnt FROM ingestion_queue GROUP BY source"
        ).fetchall()
        source_counts = {r["source"]: r["cnt"] for r in source_rows}

        total = conn.execute("SELECT COUNT(*) as cnt FROM ingestion_queue").fetchone()["cnt"]

        oldest_row = conn.execute(
            "SELECT created_at FROM ingestion_queue WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        oldest_pending = oldest_row["created_at"] if oldest_row else None

        stats = {
            "total": total,
            "by_status": status_counts,
            "by_source": source_counts,
            "oldest_pending": oldest_pending,
        }
        log.info("queue_stats", **stats)
        return stats
    finally:
        conn.close()


async def get_queue_stats_async() -> Dict[str, Any]:
    """Async version of get_queue_stats."""
    return await asyncio.to_thread(get_queue_stats)


# ─── CLI ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )

    parser = argparse.ArgumentParser(description="Ingestion Queue Manager")
    parser.add_argument("--action", choices=["init", "stats"], default="stats")
    args = parser.parse_args()

    if args.action == "init":
        init_db()
        print("Queue DB initialised.")
    elif args.action == "stats":
        init_db()  # ensure table exists
        stats = get_queue_stats()
        print(json.dumps(stats, indent=2, default=str))
