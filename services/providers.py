"""Multi-provider agent registry with live health telemetry."""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import config


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProviderConfig:
    id: str
    name: str
    kind: str  # openai | anthropic | xai | mock | custom
    model: str
    status: str = "online"  # online | degraded | offline | unconfigured
    base_latency_ms: int = 350
    error_rate: float = 0.0
    region: str = "us-east-1"
    capabilities: List[str] = field(default_factory=list)
    last_health_check: str = ""
    total_requests: int = 0
    total_errors: int = 0
    total_tokens: int = 0
    avg_latency_ms: float = 0.0
    last_error: str = ""
    api_key_configured: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        # Never expose secrets
        return d


class ProviderRegistry:
    """In-memory multi-provider control plane."""

    def __init__(self):
        self._providers: Dict[str, ProviderConfig] = {}
        self._agent_bindings: Dict[str, str] = {}
        self._seed()

    def _seed(self):
        openai_ok = bool(config.OPENAI_API_KEY)
        anthropic_ok = bool(config.ANTHROPIC_API_KEY)
        xai_ok = bool(getattr(config, "XAI_API_KEY", "") or "")

        self._providers = {
            "mock": ProviderConfig(
                id="mock",
                name="Mock Simulator",
                kind="mock",
                model="mock-v1",
                status="online",
                base_latency_ms=120,
                error_rate=0.0,
                region="local",
                capabilities=["chat", "tools", "streaming"],
                last_health_check=_utc_now(),
                api_key_configured=True,
            ),
            "openai": ProviderConfig(
                id="openai",
                name="OpenAI",
                kind="openai",
                model=getattr(config, "OPENAI_MODEL", "gpt-4o-mini"),
                status="online" if openai_ok else "unconfigured",
                base_latency_ms=480,
                error_rate=0.02,
                region="us-east-1",
                capabilities=["chat", "tools", "vision", "streaming"],
                last_health_check=_utc_now(),
                api_key_configured=openai_ok,
            ),
            "anthropic": ProviderConfig(
                id="anthropic",
                name="Anthropic",
                kind="anthropic",
                model=getattr(config, "ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
                status="online" if anthropic_ok else "unconfigured",
                base_latency_ms=520,
                error_rate=0.015,
                region="us-west-2",
                capabilities=["chat", "tools", "long-context", "streaming"],
                last_health_check=_utc_now(),
                api_key_configured=anthropic_ok,
            ),
            "xai": ProviderConfig(
                id="xai",
                name="xAI Grok",
                kind="xai",
                model=getattr(config, "XAI_MODEL", "grok-3-mini"),
                status="online" if xai_ok else "unconfigured",
                base_latency_ms=400,
                error_rate=0.01,
                region="us-central-1",
                capabilities=["chat", "tools", "streaming", "realtime"],
                last_health_check=_utc_now(),
                api_key_configured=xai_ok,
            ),
        }

        # Default agent → provider bindings
        mode = (config.PROVIDER_MODE or "mock").lower()
        default = mode if mode in self._providers else "mock"
        # Prefer mock when key-backed providers are unconfigured
        if default != "mock" and self._providers[default].status == "unconfigured":
            default = "mock"

        self._agent_bindings = {
            "assembler": default,
            "proactive": default,
            "diagnostics": default,
            "qa_compliance": default,
        }

        # Demo multi-provider mix when mock mode: show diversified bindings
        if mode == "mock" or mode == "multi":
            self._agent_bindings = {
                "assembler": "mock",
                "proactive": "openai" if openai_ok else "mock",
                "diagnostics": "anthropic" if anthropic_ok else "mock",
                "qa_compliance": "xai" if xai_ok else "mock",
            }
            # Even without keys, surface multi-provider routing via simulated mode
            if mode == "multi" or mode == "mock":
                self._agent_bindings = {
                    "assembler": "mock",
                    "proactive": "openai",
                    "diagnostics": "anthropic",
                    "qa_compliance": "xai",
                }
                # Mark unconfigured providers as degraded-sim so they still execute via mock fallback
                for pid in ("openai", "anthropic", "xai"):
                    p = self._providers[pid]
                    if not p.api_key_configured:
                        p.status = "simulated"
                        p.capabilities = list(set(p.capabilities + ["simulated-fallback"]))

    def list_providers(self) -> List[dict]:
        return [p.to_dict() for p in self._providers.values()]

    def get_provider(self, provider_id: str) -> Optional[ProviderConfig]:
        return self._providers.get(provider_id)

    def list_agent_bindings(self) -> List[dict]:
        agents = []
        for agent_id, provider_id in self._agent_bindings.items():
            provider = self._providers.get(provider_id)
            agents.append({
                "agent_id": agent_id,
                "agent_name": agent_id.replace("_", " ").title(),
                "provider_id": provider_id,
                "provider_name": provider.name if provider else provider_id,
                "provider_status": provider.status if provider else "unknown",
                "model": provider.model if provider else "n/a",
            })
        return agents

    def bind_agent(self, agent_id: str, provider_id: str) -> dict:
        if provider_id not in self._providers:
            raise ValueError(f"Unknown provider: {provider_id}")
        if agent_id not in self._agent_bindings:
            raise ValueError(f"Unknown agent: {agent_id}")
        self._agent_bindings[agent_id] = provider_id
        return next(a for a in self.list_agent_bindings() if a["agent_id"] == agent_id)

    def resolve_provider_for_agent(self, agent_id: str) -> ProviderConfig:
        pid = self._agent_bindings.get(agent_id, "mock")
        provider = self._providers.get(pid) or self._providers["mock"]
        # Fallback to mock when unconfigured real keys
        if provider.status == "unconfigured":
            return self._providers["mock"]
        return provider

    def record_invocation(
        self,
        provider_id: str,
        latency_ms: float,
        tokens: int = 0,
        error: Optional[str] = None,
    ):
        provider = self._providers.get(provider_id)
        if not provider:
            return
        provider.total_requests += 1
        provider.total_tokens += tokens
        provider.last_health_check = _utc_now()
        # EMA latency
        if provider.avg_latency_ms <= 0:
            provider.avg_latency_ms = latency_ms
        else:
            provider.avg_latency_ms = (provider.avg_latency_ms * 0.7) + (latency_ms * 0.3)
        if error:
            provider.total_errors += 1
            provider.last_error = error
            if provider.total_requests > 0 and (provider.total_errors / provider.total_requests) > 0.25:
                provider.status = "degraded"
        elif provider.status in ("degraded", "offline") and provider.api_key_configured:
            provider.status = "online"
        elif provider.status == "simulated":
            pass  # keep simulated

    async def health_ping(self, provider_id: str) -> dict:
        provider = self._providers.get(provider_id)
        if not provider:
            raise ValueError(f"Unknown provider: {provider_id}")

        start = time.perf_counter()
        await asyncio.sleep(provider.base_latency_ms / 1000.0 * 0.25)
        latency = (time.perf_counter() - start) * 1000

        if provider.status == "unconfigured":
            provider.last_health_check = _utc_now()
            return {
                "provider_id": provider_id,
                "ok": False,
                "status": provider.status,
                "latency_ms": round(latency, 1),
                "message": "API key not configured — simulated mode only",
                "checked_at": provider.last_health_check,
            }

        # Light jitter / occasional degrade simulation
        if random.random() < provider.error_rate:
            provider.status = "degraded"
            provider.last_error = "Intermittent upstream timeout"
            ok = False
            msg = provider.last_error
        else:
            if provider.status not in ("simulated",):
                provider.status = "online"
            ok = True
            msg = "Healthy"
            provider.last_error = ""

        provider.last_health_check = _utc_now()
        provider.avg_latency_ms = (
            latency if provider.avg_latency_ms <= 0 else (provider.avg_latency_ms * 0.8 + latency * 0.2)
        )
        return {
            "provider_id": provider_id,
            "ok": ok,
            "status": provider.status,
            "latency_ms": round(latency, 1),
            "message": msg,
            "checked_at": provider.last_health_check,
        }

    async def health_ping_all(self) -> List[dict]:
        results = []
        for pid in list(self._providers.keys()):
            results.append(await self.health_ping(pid))
        return results

    def summary(self) -> dict:
        providers = list(self._providers.values())
        online = sum(1 for p in providers if p.status in ("online", "simulated"))
        total_req = sum(p.total_requests for p in providers)
        total_err = sum(p.total_errors for p in providers)
        total_tok = sum(p.total_tokens for p in providers)
        avg_lat = 0.0
        latencies = [p.avg_latency_ms for p in providers if p.avg_latency_ms > 0]
        if latencies:
            avg_lat = sum(latencies) / len(latencies)
        return {
            "provider_count": len(providers),
            "online_count": online,
            "total_requests": total_req,
            "total_errors": total_err,
            "error_rate": round(total_err / total_req, 4) if total_req else 0.0,
            "total_tokens": total_tok,
            "avg_latency_ms": round(avg_lat, 1),
            "agent_count": len(self._agent_bindings),
            "active_mode": config.PROVIDER_MODE,
        }


# Singleton
provider_registry = ProviderRegistry()
