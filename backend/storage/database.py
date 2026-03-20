"""
SQLite storage — only stores AI-generated content.

Service registry data (services, specs, versions, traffic) now comes from
the APIPlatform API via backend.api_platform_client.
"""
import json
import aiosqlite
from datetime import datetime
from typing import Optional, List, Dict
from pathlib import Path


DB_PATH = Path(__file__).parent.parent / "service_assist.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS service_docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id TEXT NOT NULL,
                version TEXT NOT NULL,
                doc_json TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                UNIQUE(service_id, version)
            );

            CREATE TABLE IF NOT EXISTS change_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id TEXT NOT NULL,
                from_version TEXT NOT NULL,
                to_version TEXT NOT NULL,
                changelog_json TEXT NOT NULL,
                generated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS gap_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id TEXT NOT NULL,
                report_json TEXT NOT NULL,
                generated_at TEXT NOT NULL
            );
        """)
        await db.commit()


# ── Service docs ──────────────────────────────────────────────────────────────

async def save_service_doc(service_id: str, version: str, doc_json: str):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO service_docs (service_id, version, doc_json, generated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(service_id, version) DO UPDATE SET
                doc_json=excluded.doc_json,
                generated_at=excluded.generated_at
        """, (service_id, version, doc_json, now))
        await db.commit()


async def get_service_doc(service_id: str, version: str) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""
            SELECT * FROM service_docs WHERE service_id=? AND version=?
        """, (service_id, version))
        row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["doc"] = json.loads(d["doc_json"])
        return d


async def list_doc_versions(service_id: str) -> List[str]:
    """Return versions that have generated docs for a service."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT version FROM service_docs WHERE service_id=? ORDER BY generated_at DESC
        """, (service_id,))
        rows = await cur.fetchall()
        return [r[0] for r in rows]


async def get_doc_status(service_ids: List[str]) -> Dict[str, Dict]:
    """Return doc count and last generated_at for a list of service IDs."""
    if not service_ids:
        return {}
    placeholders = ",".join("?" * len(service_ids))
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(f"""
            SELECT service_id,
                   COUNT(*) as doc_count,
                   MAX(generated_at) as last_generated_at
            FROM service_docs
            WHERE service_id IN ({placeholders})
            GROUP BY service_id
        """, service_ids)
        rows = await cur.fetchall()
        return {r[0]: {"doc_count": r[1], "last_generated_at": r[2]} for r in rows}


# ── Change logs ───────────────────────────────────────────────────────────────

async def save_change_log(service_id: str, from_v: str, to_v: str, changelog_json: str):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO change_logs (service_id, from_version, to_version, changelog_json, generated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (service_id, from_v, to_v, changelog_json, now))
        await db.commit()


async def get_change_log(service_id: str, from_v: str, to_v: str) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""
            SELECT * FROM change_logs
            WHERE service_id=? AND from_version=? AND to_version=?
            ORDER BY generated_at DESC LIMIT 1
        """, (service_id, from_v, to_v))
        row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["changelog"] = json.loads(d["changelog_json"])
        return d


# ── Gap reports ───────────────────────────────────────────────────────────────

async def save_gap_report(service_id: str, report_json: str):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO gap_reports (service_id, report_json, generated_at)
            VALUES (?, ?, ?)
        """, (service_id, report_json, now))
        await db.commit()
