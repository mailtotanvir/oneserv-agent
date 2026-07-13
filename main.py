import os
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks, status
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database
from services.orchestrator import OneServOrchestrator
from services.providers import provider_registry
from services.mcp_bridges import mcp_registry
from services import observability
from config import config

app = FastAPI(
    title=config.APP_NAME,
    version=config.VERSION,
    description="Customer Lifecycle Swarm · Multi-Provider & MCP Observability Control Plane",
)

static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

orchestrator = OneServOrchestrator()


# ── Request schemas ──────────────────────────────────────────────────────────

class TriggerEventRequest(BaseModel):
    customer_id: int
    event_type: str


class GateDecisionRequest(BaseModel):
    interaction_id: int
    decision: str  # APPROVED or REJECTED
    comments: Optional[str] = ""


class BindAgentRequest(BaseModel):
    agent_id: str
    provider_id: str


class BridgeStatusRequest(BaseModel):
    status: str  # connected | disconnected | error | connecting


class MCPCallRequest(BaseModel):
    bridge_id: str
    tool_name: str
    arguments: Optional[dict] = None
    agent_id: str = "operator"


# ── Customer lifecycle APIs ──────────────────────────────────────────────────

@app.get("/api/customers")
async def get_customers():
    res = []
    for c_id in [101, 102, 103]:
        profile = database.get_assembled_customer_360(c_id)
        if profile:
            res.append(profile)
    return res


@app.get("/api/customer/{customer_id}")
async def get_customer_details(customer_id: int):
    profile = database.get_assembled_customer_360(customer_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Customer not found.")
    return profile


@app.get("/api/interactions")
async def list_interactions():
    return database.get_all_interactions()


@app.get("/api/interaction/{interaction_id}")
async def get_interaction(interaction_id: int):
    details = database.get_interaction_details(interaction_id)
    if not details:
        raise HTTPException(status_code=404, detail="Case interaction log not found.")
    return details


@app.post("/api/trigger", status_code=status.HTTP_201_CREATED)
async def trigger_swarm_pipeline(payload: TriggerEventRequest, background_tasks: BackgroundTasks):
    profile = database.get_assembled_customer_360(payload.customer_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Customer not found.")

    # FastAPI awaits async callables added to BackgroundTasks
    background_tasks.add_task(
        orchestrator.initiate_pipeline,
        payload.customer_id,
        payload.event_type,
    )
    observability.log_event(
        "pipeline_trigger",
        f"Swarm pipeline triggered for customer {payload.customer_id}: {payload.event_type}",
        source="api",
        metadata={"customer_id": payload.customer_id, "event_type": payload.event_type},
    )
    return {
        "message": "Swarm pipeline initiated.",
        "customer_id": payload.customer_id,
        "event_type": payload.event_type,
    }


@app.post("/api/gate/decision")
async def submit_gate_decision(payload: GateDecisionRequest, background_tasks: BackgroundTasks):
    details = database.get_interaction_details(payload.interaction_id)
    if not details:
        raise HTTPException(status_code=404, detail="Interaction case not found.")

    case_status = details["interaction"]["status"]

    if case_status == "PENDING_CAMPAIGN_APPROVAL":
        background_tasks.add_task(
            orchestrator.process_campaign_gate,
            payload.interaction_id,
            payload.decision,
            payload.comments,
        )
        return {"message": f"Gate 1 Campaign decision '{payload.decision}' processed."}

    if case_status == "PENDING_REFUND_APPROVAL":
        background_tasks.add_task(
            orchestrator.process_refund_gate,
            payload.interaction_id,
            payload.decision,
            payload.comments,
        )
        return {"message": f"Gate 2 Refund decision '{payload.decision}' processed."}

    raise HTTPException(
        status_code=400,
        detail=f"No manual action required. Current status: {case_status}",
    )


# ── Observability: multi-provider agents ─────────────────────────────────────

@app.get("/api/observability/summary")
async def observability_summary():
    return {
        "providers": provider_registry.summary(),
        "mcp": mcp_registry.summary(),
        "invocations": observability.invocation_stats(),
        "mcp_calls": observability.mcp_stats(),
        "version": config.VERSION,
        "provider_mode": config.PROVIDER_MODE,
    }


@app.get("/api/providers")
async def list_providers():
    return {
        "providers": provider_registry.list_providers(),
        "summary": provider_registry.summary(),
    }


@app.get("/api/providers/{provider_id}")
async def get_provider(provider_id: str):
    p = provider_registry.get_provider(provider_id)
    if not p:
        raise HTTPException(status_code=404, detail="Provider not found")
    return p.to_dict()


@app.post("/api/providers/{provider_id}/health")
async def ping_provider(provider_id: str):
    try:
        result = await provider_registry.health_ping(provider_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    observability.log_event(
        "provider_health",
        f"Health check {provider_id}: {result['status']} ({result['latency_ms']}ms)",
        source=provider_id,
        severity="warn" if not result["ok"] else "info",
        metadata=result,
    )
    return result


@app.post("/api/providers/health")
async def ping_all_providers():
    return await provider_registry.health_ping_all()


@app.get("/api/agents")
async def list_agents():
    return {
        "agents": provider_registry.list_agent_bindings(),
        "count": len(provider_registry.list_agent_bindings()),
    }


@app.post("/api/agents/bind")
async def bind_agent(payload: BindAgentRequest):
    try:
        binding = provider_registry.bind_agent(payload.agent_id, payload.provider_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    observability.log_event(
        "agent_bind",
        f"Bound agent {payload.agent_id} → provider {payload.provider_id}",
        source="control-plane",
        metadata=binding,
    )
    return binding


@app.get("/api/observability/invocations")
async def list_invocations(limit: int = 50, agent_id: Optional[str] = None):
    return observability.list_agent_invocations(limit=min(limit, 200), agent_id=agent_id)


# ── Observability: MCP bridges ───────────────────────────────────────────────

@app.get("/api/mcp/bridges")
async def list_mcp_bridges():
    return {
        "bridges": mcp_registry.list_bridges(),
        "summary": mcp_registry.summary(),
    }


@app.get("/api/mcp/bridges/{bridge_id}")
async def get_mcp_bridge(bridge_id: str):
    b = mcp_registry.get_bridge(bridge_id)
    if not b:
        raise HTTPException(status_code=404, detail="Bridge not found")
    return b.to_dict()


@app.post("/api/mcp/bridges/{bridge_id}/ping")
async def ping_mcp_bridge(bridge_id: str):
    try:
        result = await mcp_registry.ping(bridge_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    observability.log_event(
        "mcp_ping",
        f"MCP ping {bridge_id}: {result['status']} ({result['latency_ms']}ms)",
        source=bridge_id,
        severity="warn" if not result["ok"] else "info",
        metadata=result,
    )
    return result


@app.post("/api/mcp/bridges/ping")
async def ping_all_mcp_bridges():
    return await mcp_registry.ping_all()


@app.post("/api/mcp/bridges/{bridge_id}/status")
async def set_mcp_bridge_status(bridge_id: str, payload: BridgeStatusRequest):
    try:
        return mcp_registry.set_status(bridge_id, payload.status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/mcp/tools")
async def list_mcp_tools():
    return {"tools": mcp_registry.list_all_tools()}


@app.post("/api/mcp/call")
async def call_mcp_tool(payload: MCPCallRequest):
    try:
        result = await mcp_registry.call_tool(
            bridge_id=payload.bridge_id,
            tool_name=payload.tool_name,
            arguments=payload.arguments or {},
            agent_id=payload.agent_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    observability.record_mcp_call(result)
    return result


@app.get("/api/observability/mcp-calls")
async def list_mcp_call_history(limit: int = 50, bridge_id: Optional[str] = None):
    return observability.list_mcp_calls(limit=min(limit, 200), bridge_id=bridge_id)


@app.get("/api/observability/events")
async def list_obs_events(limit: int = 100, event_type: Optional[str] = None):
    return observability.list_events(limit=min(limit, 300), event_type=event_type)


# Serve UI last so /api routes win
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


if __name__ == "__main__":
    database.init_db()
    observability.init_observability_tables()
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
