"""Persistence + query layer for provider / agent / MCP observability events."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import config


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_observability_tables():
    conn = _conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS agent_invocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invocation_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            model TEXT,
            interaction_id INTEGER,
            status TEXT NOT NULL,
            latency_ms REAL,
            tokens INTEGER DEFAULT 0,
            prompt_preview TEXT,
            response_preview TEXT,
            error TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mcp_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            call_id TEXT NOT NULL,
            bridge_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            agent_id TEXT,
            interaction_id INTEGER,
            status TEXT NOT NULL,
            latency_ms REAL,
            arguments_json TEXT,
            result_preview TEXT,
            error TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS observability_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            severity TEXT DEFAULT 'info',
            source TEXT,
            message TEXT NOT NULL,
            metadata_json TEXT,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_inv_started ON agent_invocations(started_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mcp_started ON mcp_calls(started_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_obs_created ON observability_events(created_at DESC)")

    conn.commit()
    conn.close()


def log_event(
    event_type: str,
    message: str,
    source: str = "system",
    severity: str = "info",
    metadata: Optional[dict] = None,
):
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO observability_events
           (event_type, severity, source, message, metadata_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (event_type, severity, source, message, json.dumps(metadata or {}), _utc_now()),
    )
    conn.commit()
    conn.close()


def record_agent_invocation(record: dict) -> int:
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO agent_invocations
           (invocation_id, agent_id, provider_id, model, interaction_id, status,
            latency_ms, tokens, prompt_preview, response_preview, error, started_at, finished_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            record.get("invocation_id"),
            record.get("agent_id"),
            record.get("provider_id"),
            record.get("model"),
            record.get("interaction_id"),
            record.get("status", "ok"),
            record.get("latency_ms"),
            record.get("tokens", 0),
            (record.get("prompt_preview") or "")[:500],
            (record.get("response_preview") or "")[:500],
            record.get("error"),
            record.get("started_at") or _utc_now(),
            record.get("finished_at") or _utc_now(),
        ),
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()

    log_event(
        event_type="agent_invocation",
        source=record.get("agent_id", "agent"),
        severity="error" if record.get("status") == "error" else "info",
        message=(
            f"{record.get('agent_id')} via {record.get('provider_id')} "
            f"→ {record.get('status')} ({record.get('latency_ms')}ms)"
        ),
        metadata={
            "invocation_id": record.get("invocation_id"),
            "provider_id": record.get("provider_id"),
            "interaction_id": record.get("interaction_id"),
            "tokens": record.get("tokens", 0),
        },
    )
    return row_id


def record_mcp_call(record: dict) -> int:
    conn = _conn()
    cur = conn.cursor()
    result_preview = record.get("result")
    if result_preview is not None and not isinstance(result_preview, str):
        result_preview = json.dumps(result_preview)[:500]
    elif result_preview:
        result_preview = str(result_preview)[:500]

    cur.execute(
        """INSERT INTO mcp_calls
           (call_id, bridge_id, tool_name, agent_id, interaction_id, status,
            latency_ms, arguments_json, result_preview, error, started_at, finished_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            record.get("call_id"),
            record.get("bridge_id"),
            record.get("tool_name"),
            record.get("agent_id"),
            record.get("interaction_id"),
            record.get("status", "ok"),
            record.get("latency_ms"),
            json.dumps(record.get("arguments") or {}),
            result_preview,
            record.get("error"),
            record.get("started_at") or _utc_now(),
            record.get("finished_at") or _utc_now(),
        ),
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()

    log_event(
        event_type="mcp_call",
        source=record.get("bridge_id", "mcp"),
        severity="error" if record.get("status") == "error" else "info",
        message=(
            f"MCP {record.get('bridge_id')}.{record.get('tool_name')} "
            f"by {record.get('agent_id')} → {record.get('status')} ({record.get('latency_ms')}ms)"
        ),
        metadata={
            "call_id": record.get("call_id"),
            "agent_id": record.get("agent_id"),
            "interaction_id": record.get("interaction_id"),
        },
    )
    return row_id


def list_agent_invocations(limit: int = 50, agent_id: Optional[str] = None) -> List[dict]:
    conn = _conn()
    cur = conn.cursor()
    if agent_id:
        cur.execute(
            "SELECT * FROM agent_invocations WHERE agent_id = ? ORDER BY id DESC LIMIT ?",
            (agent_id, limit),
        )
    else:
        cur.execute("SELECT * FROM agent_invocations ORDER BY id DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def list_mcp_calls(limit: int = 50, bridge_id: Optional[str] = None) -> List[dict]:
    conn = _conn()
    cur = conn.cursor()
    if bridge_id:
        cur.execute(
            "SELECT * FROM mcp_calls WHERE bridge_id = ? ORDER BY id DESC LIMIT ?",
            (bridge_id, limit),
        )
    else:
        cur.execute("SELECT * FROM mcp_calls ORDER BY id DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def list_events(limit: int = 100, event_type: Optional[str] = None) -> List[dict]:
    conn = _conn()
    cur = conn.cursor()
    if event_type:
        cur.execute(
            "SELECT * FROM observability_events WHERE event_type = ? ORDER BY id DESC LIMIT ?",
            (event_type, limit),
        )
    else:
        cur.execute("SELECT * FROM observability_events ORDER BY id DESC LIMIT ?", (limit,))
    rows = []
    for r in cur.fetchall():
        d = dict(r)
        try:
            d["metadata"] = json.loads(d.pop("metadata_json") or "{}")
        except json.JSONDecodeError:
            d["metadata"] = {}
        rows.append(d)
    conn.close()
    return rows


def invocation_stats() -> dict:
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM agent_invocations")
    total = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM agent_invocations WHERE status = 'error'")
    errors = cur.fetchone()["c"]
    cur.execute("SELECT AVG(latency_ms) AS a, SUM(tokens) AS t FROM agent_invocations")
    row = cur.fetchone()
    cur.execute(
        """SELECT agent_id, COUNT(*) AS c, AVG(latency_ms) AS avg_lat
           FROM agent_invocations GROUP BY agent_id ORDER BY c DESC"""
    )
    by_agent = [dict(r) for r in cur.fetchall()]
    cur.execute(
        """SELECT provider_id, COUNT(*) AS c, AVG(latency_ms) AS avg_lat
           FROM agent_invocations GROUP BY provider_id ORDER BY c DESC"""
    )
    by_provider = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {
        "total_invocations": total,
        "error_count": errors,
        "error_rate": round(errors / total, 4) if total else 0.0,
        "avg_latency_ms": round(row["a"] or 0, 1),
        "total_tokens": int(row["t"] or 0),
        "by_agent": by_agent,
        "by_provider": by_provider,
    }


def mcp_stats() -> dict:
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM mcp_calls")
    total = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM mcp_calls WHERE status = 'error'")
    errors = cur.fetchone()["c"]
    cur.execute("SELECT AVG(latency_ms) AS a FROM mcp_calls")
    avg = cur.fetchone()["a"] or 0
    cur.execute(
        """SELECT bridge_id, tool_name, COUNT(*) AS c, AVG(latency_ms) AS avg_lat
           FROM mcp_calls GROUP BY bridge_id, tool_name ORDER BY c DESC LIMIT 20"""
    )
    by_tool = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {
        "total_calls": total,
        "error_count": errors,
        "error_rate": round(errors / total, 4) if total else 0.0,
        "avg_latency_ms": round(avg, 1),
        "by_tool": by_tool,
    }


# Ensure tables exist on import
init_observability_tables()
