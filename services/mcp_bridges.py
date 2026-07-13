"""MCP bridge registry — observes tool servers agents call through MCP."""
from __future__ import annotations

import asyncio
import random
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MCPBridge:
    id: str
    name: str
    transport: str  # stdio | sse | websocket | http
    endpoint: str
    status: str = "connected"  # connected | connecting | disconnected | error
    version: str = "2024-11-05"
    tools: List[MCPTool] = field(default_factory=list)
    last_ping_ms: float = 0.0
    last_ping_at: str = ""
    total_calls: int = 0
    total_errors: int = 0
    total_bytes: int = 0
    avg_latency_ms: float = 0.0
    last_error: str = ""
    tags: List[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "transport": self.transport,
            "endpoint": self.endpoint,
            "status": self.status,
            "version": self.version,
            "tools": [t.to_dict() for t in self.tools],
            "tool_count": len(self.tools),
            "last_ping_ms": self.last_ping_ms,
            "last_ping_at": self.last_ping_at,
            "total_calls": self.total_calls,
            "total_errors": self.total_errors,
            "total_bytes": self.total_bytes,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "error_rate": round(self.total_errors / self.total_calls, 4) if self.total_calls else 0.0,
            "last_error": self.last_error,
            "tags": self.tags,
            "description": self.description,
        }


class MCPBridgeRegistry:
    """Tracks MCP servers/bridges and simulates tool invocations for observability."""

    def __init__(self):
        self._bridges: Dict[str, MCPBridge] = {}
        self._seed()

    def _seed(self):
        self._bridges = {
            "mcp-sqlite": MCPBridge(
                id="mcp-sqlite",
                name="SQLite CRM Bridge",
                transport="stdio",
                endpoint="stdio://oneserv-sqlite-mcp",
                status="connected",
                description="Read/write customer CRM, billing ledger, and interaction audits.",
                tags=["data", "crm", "local"],
                tools=[
                    MCPTool("crm_get_profile", "Fetch CRM profile by customer_id",
                            {"type": "object", "properties": {"customer_id": {"type": "integer"}}}),
                    MCPTool("billing_get_ledger", "Fetch outstanding balance and invoice status",
                            {"type": "object", "properties": {"customer_id": {"type": "integer"}}}),
                    MCPTool("telemetry_get_usage", "Fetch 30-day product telemetry",
                            {"type": "object", "properties": {"customer_id": {"type": "integer"}}}),
                    MCPTool("audit_write_trace", "Append an interaction audit trace",
                            {"type": "object", "properties": {"interaction_id": {"type": "integer"}, "message": {"type": "string"}}}),
                ],
                last_ping_at=_utc_now(),
                last_ping_ms=12.0,
            ),
            "mcp-filesystem": MCPBridge(
                id="mcp-filesystem",
                name="Filesystem Bridge",
                transport="stdio",
                endpoint="stdio://oneserv-fs-mcp",
                status="connected",
                description="Sandbox file I/O for outreach drafts and compliance artifacts.",
                tags=["files", "local"],
                tools=[
                    MCPTool("fs_read", "Read a workspace file",
                            {"type": "object", "properties": {"path": {"type": "string"}}}),
                    MCPTool("fs_write", "Write artifact content",
                            {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}}),
                    MCPTool("fs_list", "List directory entries",
                            {"type": "object", "properties": {"path": {"type": "string"}}}),
                ],
                last_ping_at=_utc_now(),
                last_ping_ms=8.0,
            ),
            "mcp-web": MCPBridge(
                id="mcp-web",
                name="Web Fetch Bridge",
                transport="sse",
                endpoint="https://mcp.oneserv.local/web/sse",
                status="connected",
                description="Fetch public policy pages and status endpoints for QA context.",
                tags=["web", "remote"],
                tools=[
                    MCPTool("web_fetch", "HTTP GET a URL and return text",
                            {"type": "object", "properties": {"url": {"type": "string"}}}),
                    MCPTool("web_search", "Search internal knowledge base",
                            {"type": "object", "properties": {"query": {"type": "string"}}}),
                ],
                last_ping_at=_utc_now(),
                last_ping_ms=45.0,
            ),
            "mcp-slack": MCPBridge(
                id="mcp-slack",
                name="Slack Notify Bridge",
                transport="http",
                endpoint="https://mcp.oneserv.local/slack",
                status="disconnected",
                description="Optional outbound notifications to ops channels (HITL alerts).",
                tags=["notify", "remote", "optional"],
                tools=[
                    MCPTool("slack_post", "Post a message to a channel",
                            {"type": "object", "properties": {
                                "channel": {"type": "string"},
                                "text": {"type": "string"},
                            }}),
                ],
                last_ping_at=_utc_now(),
                last_ping_ms=0.0,
                last_error="Bridge not started — optional notification path",
            ),
            "mcp-billing-api": MCPBridge(
                id="mcp-billing-api",
                name="Billing API Bridge",
                transport="websocket",
                endpoint="wss://mcp.oneserv.local/billing",
                status="connected",
                description="Ledger mutations for refunds/waivers after Gate 2 approval.",
                tags=["billing", "write", "remote"],
                tools=[
                    MCPTool("ledger_waive", "Write off outstanding balance",
                            {"type": "object", "properties": {
                                "customer_id": {"type": "integer"},
                                "amount": {"type": "number"},
                                "reason": {"type": "string"},
                            }}),
                    MCPTool("ledger_status", "Get live invoice status",
                            {"type": "object", "properties": {"customer_id": {"type": "integer"}}}),
                ],
                last_ping_at=_utc_now(),
                last_ping_ms=28.0,
            ),
        }

    def list_bridges(self) -> List[dict]:
        return [b.to_dict() for b in self._bridges.values()]

    def get_bridge(self, bridge_id: str) -> Optional[MCPBridge]:
        return self._bridges.get(bridge_id)

    def list_all_tools(self) -> List[dict]:
        tools = []
        for b in self._bridges.values():
            for t in b.tools:
                tools.append({
                    "bridge_id": b.id,
                    "bridge_name": b.name,
                    "bridge_status": b.status,
                    "tool_name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                })
        return tools

    def set_status(self, bridge_id: str, status: str) -> dict:
        bridge = self._bridges.get(bridge_id)
        if not bridge:
            raise ValueError(f"Unknown bridge: {bridge_id}")
        if status not in ("connected", "connecting", "disconnected", "error"):
            raise ValueError(f"Invalid status: {status}")
        bridge.status = status
        if status == "connected":
            bridge.last_error = ""
        elif status == "disconnected":
            bridge.last_error = bridge.last_error or "Manually disconnected"
        return bridge.to_dict()

    async def ping(self, bridge_id: str) -> dict:
        bridge = self._bridges.get(bridge_id)
        if not bridge:
            raise ValueError(f"Unknown bridge: {bridge_id}")

        if bridge.status == "disconnected":
            return {
                "bridge_id": bridge_id,
                "ok": False,
                "status": bridge.status,
                "latency_ms": 0,
                "message": bridge.last_error or "Disconnected",
                "checked_at": _utc_now(),
            }

        bridge.status = "connecting"
        start = time.perf_counter()
        # Simulate transport latency by type
        base = {"stdio": 0.01, "sse": 0.04, "http": 0.05, "websocket": 0.03}.get(bridge.transport, 0.03)
        await asyncio.sleep(base + random.uniform(0, 0.02))
        latency = (time.perf_counter() - start) * 1000

        # Rare flaky remote
        if bridge.transport in ("sse", "http", "websocket") and random.random() < 0.05:
            bridge.status = "error"
            bridge.last_error = "Upstream MCP handshake timeout"
            bridge.last_ping_ms = latency
            bridge.last_ping_at = _utc_now()
            return {
                "bridge_id": bridge_id,
                "ok": False,
                "status": bridge.status,
                "latency_ms": round(latency, 1),
                "message": bridge.last_error,
                "checked_at": bridge.last_ping_at,
            }

        bridge.status = "connected"
        bridge.last_error = ""
        bridge.last_ping_ms = round(latency, 1)
        bridge.last_ping_at = _utc_now()
        return {
            "bridge_id": bridge_id,
            "ok": True,
            "status": bridge.status,
            "latency_ms": bridge.last_ping_ms,
            "message": "Healthy",
            "checked_at": bridge.last_ping_at,
        }

    async def ping_all(self) -> List[dict]:
        results = []
        for bid in list(self._bridges.keys()):
            results.append(await self.ping(bid))
        return results

    async def call_tool(
        self,
        bridge_id: str,
        tool_name: str,
        arguments: Optional[dict] = None,
        agent_id: str = "system",
        interaction_id: Optional[int] = None,
    ) -> dict:
        """Simulate an MCP tools/call and return structured result + metrics."""
        bridge = self._bridges.get(bridge_id)
        if not bridge:
            raise ValueError(f"Unknown bridge: {bridge_id}")

        tool = next((t for t in bridge.tools if t.name == tool_name), None)
        if not tool:
            raise ValueError(f"Tool '{tool_name}' not found on bridge '{bridge_id}'")

        call_id = f"mcp_{uuid.uuid4().hex[:12]}"
        arguments = arguments or {}
        started = _utc_now()
        start = time.perf_counter()

        if bridge.status in ("disconnected", "error"):
            latency = 0.0
            bridge.total_calls += 1
            bridge.total_errors += 1
            return {
                "call_id": call_id,
                "bridge_id": bridge_id,
                "tool_name": tool_name,
                "agent_id": agent_id,
                "interaction_id": interaction_id,
                "arguments": arguments,
                "ok": False,
                "status": "error",
                "latency_ms": latency,
                "result": None,
                "error": f"Bridge {bridge_id} is {bridge.status}",
                "started_at": started,
                "finished_at": _utc_now(),
            }

        # Simulated work
        base = {"stdio": 0.03, "sse": 0.08, "http": 0.1, "websocket": 0.06}.get(bridge.transport, 0.05)
        await asyncio.sleep(base + random.uniform(0, 0.04))
        latency = (time.perf_counter() - start) * 1000

        # Synthetic result payloads by tool family
        result_payload = self._simulate_tool_result(tool_name, arguments)
        ok = True
        error = None
        if random.random() < 0.02:
            ok = False
            error = "MCP tool handler raised ToolError: transient failure"
            result_payload = None

        bridge.total_calls += 1
        if not ok:
            bridge.total_errors += 1
            bridge.last_error = error or ""
        payload_size = len(str(result_payload or error or ""))
        bridge.total_bytes += payload_size
        if bridge.avg_latency_ms <= 0:
            bridge.avg_latency_ms = latency
        else:
            bridge.avg_latency_ms = bridge.avg_latency_ms * 0.7 + latency * 0.3

        return {
            "call_id": call_id,
            "bridge_id": bridge_id,
            "bridge_name": bridge.name,
            "tool_name": tool_name,
            "agent_id": agent_id,
            "interaction_id": interaction_id,
            "arguments": arguments,
            "ok": ok,
            "status": "ok" if ok else "error",
            "latency_ms": round(latency, 1),
            "result": result_payload,
            "error": error,
            "bytes": payload_size,
            "started_at": started,
            "finished_at": _utc_now(),
        }

    def _simulate_tool_result(self, tool_name: str, arguments: dict) -> Any:
        if tool_name == "crm_get_profile":
            return {"customer_id": arguments.get("customer_id"), "source": "mcp-sqlite", "ok": True}
        if tool_name == "billing_get_ledger":
            return {"customer_id": arguments.get("customer_id"), "ledger": "ok", "source": "mcp-sqlite"}
        if tool_name == "telemetry_get_usage":
            return {"customer_id": arguments.get("customer_id"), "window": "30d", "source": "mcp-sqlite"}
        if tool_name == "audit_write_trace":
            return {"written": True, "interaction_id": arguments.get("interaction_id")}
        if tool_name == "fs_write":
            return {"path": arguments.get("path"), "bytes_written": len(str(arguments.get("content", "")))}
        if tool_name == "fs_read":
            return {"path": arguments.get("path"), "content": "(artifact stub)"}
        if tool_name == "fs_list":
            return {"path": arguments.get("path", "."), "entries": ["outreach.md", "qa_report.md"]}
        if tool_name == "web_fetch":
            return {"url": arguments.get("url"), "status": 200, "chars": 4200}
        if tool_name == "web_search":
            return {"query": arguments.get("query"), "hits": 3}
        if tool_name == "slack_post":
            return {"channel": arguments.get("channel"), "ts": _utc_now()}
        if tool_name == "ledger_waive":
            return {
                "customer_id": arguments.get("customer_id"),
                "amount": arguments.get("amount"),
                "status": "waived",
            }
        if tool_name == "ledger_status":
            return {"customer_id": arguments.get("customer_id"), "status": "OK"}
        return {"ok": True, "tool": tool_name, "args": arguments}

    def summary(self) -> dict:
        bridges = list(self._bridges.values())
        connected = sum(1 for b in bridges if b.status == "connected")
        tools = sum(len(b.tools) for b in bridges)
        total_calls = sum(b.total_calls for b in bridges)
        total_errors = sum(b.total_errors for b in bridges)
        avg_lat = 0.0
        lats = [b.avg_latency_ms for b in bridges if b.avg_latency_ms > 0]
        if lats:
            avg_lat = sum(lats) / len(lats)
        return {
            "bridge_count": len(bridges),
            "connected_count": connected,
            "tool_count": tools,
            "total_calls": total_calls,
            "total_errors": total_errors,
            "error_rate": round(total_errors / total_calls, 4) if total_calls else 0.0,
            "avg_latency_ms": round(avg_lat, 1),
        }


# Agent → preferred MCP bridges for pipeline steps
AGENT_MCP_ROUTES = {
    "assembler": [
        ("mcp-sqlite", "crm_get_profile"),
        ("mcp-sqlite", "billing_get_ledger"),
        ("mcp-sqlite", "telemetry_get_usage"),
    ],
    "proactive": [
        ("mcp-sqlite", "crm_get_profile"),
        ("mcp-filesystem", "fs_write"),
        ("mcp-web", "web_search"),
    ],
    "diagnostics": [
        ("mcp-sqlite", "billing_get_ledger"),
        ("mcp-billing-api", "ledger_status"),
        ("mcp-filesystem", "fs_write"),
    ],
    "qa_compliance": [
        ("mcp-filesystem", "fs_read"),
        ("mcp-web", "web_fetch"),
        ("mcp-sqlite", "audit_write_trace"),
    ],
}


mcp_registry = MCPBridgeRegistry()
