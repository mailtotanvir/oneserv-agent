import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List
import os

import database
from services.orchestrator import OneServOrchestrator
from config import config

app = FastAPI(
    title=config.APP_NAME,
    version=config.VERSION,
    description="Customer Lifecycle Swarm Nervous System Controller"
)

# Mount frontend static folders
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

# Orchestrator instance
orchestrator = OneServOrchestrator()

# Request schemas
class TriggerEventRequest(BaseModel):
    customer_id: int
    event_type: str

class GateDecisionRequest(BaseModel):
    interaction_id: int
    decision: str  # APPROVED or REJECTED
    comments: Optional[str] = ""

# Endpoints
@app.get("/api/customers")
async def get_customers():
    # Return all seeded profiles with their active computed health
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
    # Verify customer exists
    profile = database.get_assembled_customer_360(payload.customer_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Customer not found.")
        
    # Trigger orchestrator in a thread so API is responsive and non-blocking
    background_tasks.add_task(
        orchestrator.initiate_pipeline,
        payload.customer_id,
        payload.event_type
    )
    return {"message": "Swarm pipeline initiated.", "customer_id": payload.customer_id, "event_type": payload.event_type}

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
            payload.comments
        )
        return {"message": f"Gate 1 Campaign decision '{payload.decision}' processed."}
        
    elif case_status == "PENDING_REFUND_APPROVAL":
        background_tasks.add_task(
            orchestrator.process_refund_gate,
            payload.interaction_id,
            payload.decision,
            payload.comments
        )
        return {"message": f"Gate 2 Refund decision '{payload.decision}' processed."}
        
    raise HTTPException(status_code=400, detail=f"No manual action required. Current status: {case_status}")

# Serve UI static index
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    database.init_db()
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
