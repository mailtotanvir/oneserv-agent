import asyncio
import json
import database
from services.adapters import get_agent_adapter
from services.agents import assembler, proactive, diagnostics, qa_compliance

class OneServOrchestrator:
    def __init__(self):
        self.adapter = get_agent_adapter()

    async def initiate_pipeline(self, customer_id: int, event_type: str) -> int:
        """Start swarm customer lifecycle pipeline"""
        interaction_id = database.create_interaction(customer_id, event_type)
        database.insert_trace(interaction_id, "SYSTEM", f"Initialized multi-agent customer lifecycle pipeline. Case ID: {interaction_id}")
        
        # 1. PROFILE CONTEXT ASSEMBLY
        database.insert_trace(interaction_id, "SYSTEM", "Requesting Context Assembler Agent to compile Customer 360 profile...")
        raw_cust = database.get_assembled_customer_360(customer_id)
        
        system_instruction_asm = assembler.get_system_prompt()
        prompt_asm = f"Compile unified profile for Customer ID {customer_id}"
        
        assembled_profile = await self.adapter.execute_task(
            prompt=prompt_asm,
            system_instruction=system_instruction_asm,
            context_artifacts={"raw_customer": raw_cust, "customer_id": customer_id},
            interaction_id=interaction_id,
        )
        
        database.update_interaction_artifacts(interaction_id, {"assembled_profile": assembled_profile})
        database.insert_trace(interaction_id, "ASSEMBLER", "Consolidated profile generated successfully from fragmented tables.")
        
        # Determine Path depending on Event Type
        if "Churn" in event_type or "Inactivity" in event_type:
            # Route to Proactive Retention outreach
            database.insert_trace(interaction_id, "SYSTEM", "Telemetry shift detected. Delegating case to Proactive Outreach Specialist...")
            await self.execute_proactive_campaign_draft(interaction_id, raw_cust, event_type)
            database.update_interaction_status(interaction_id, "PENDING_CAMPAIGN_APPROVAL")
            database.insert_trace(interaction_id, "SUPERVISOR", "🚦 Campaign paused at Gate 1. Awaiting human operator sign-off.")
            
        elif "Payment" in event_type or "Dispute" in event_type:
            # Route to Diagnostics/Billing resolution
            database.insert_trace(interaction_id, "SYSTEM", "Billing dispute/payment failed event caught. Routing to Diagnostics Specialist...")
            await self.execute_diagnostics_resolution(interaction_id, raw_cust)
            database.update_interaction_status(interaction_id, "PENDING_REFUND_APPROVAL")
            database.insert_trace(interaction_id, "SUPERVISOR", "🚦 Financial adjustment paused at Gate 2. Awaiting supervisor audit sign-off.")
            
        else:
            # Happy path (Standard inquiry check-in)
            database.insert_trace(interaction_id, "SUPERVISOR", "Standard customer event. Running automated QA compliance check...")
            await self.execute_qa_audit(interaction_id, "All accounts verified active.")
            database.update_interaction_status(interaction_id, "COMPLETED")
            database.insert_trace(interaction_id, "SYSTEM", "Pipeline completed successfully.")
            
        return interaction_id

    async def execute_proactive_campaign_draft(self, interaction_id: int, raw_cust: dict, event_type: str):
        system_instruction_pro = proactive.get_system_prompt()
        prompt_pro = f"Draft proactive campaign for {raw_cust['crm']['name']} facing {event_type}"
        
        outreach = await self.adapter.execute_task(
            prompt=prompt_pro,
            system_instruction=system_instruction_pro,
            context_artifacts={
                "customer_name": raw_cust["crm"]["name"],
                "event_type": event_type,
                "customer_id": raw_cust["crm"]["id"],
            },
            interaction_id=interaction_id,
        )
        database.update_interaction_artifacts(interaction_id, {"proposed_outreach": outreach})
        database.insert_trace(interaction_id, "PROACTIVE", "Proactive retention campaign drafted.")

    async def execute_diagnostics_resolution(self, interaction_id: int, raw_cust: dict):
        system_instruction_diag = diagnostics.get_system_prompt()
        prompt_diag = f"Propose billing resolution for {raw_cust['crm']['name']}"
        balance = raw_cust["billing"].get("outstanding_balance", 0.0)
        
        outreach = await self.adapter.execute_task(
            prompt=prompt_diag,
            system_instruction=system_instruction_diag,
            context_artifacts={
                "customer_name": raw_cust["crm"]["name"],
                "balance": balance,
                "customer_id": raw_cust["crm"]["id"],
            },
            interaction_id=interaction_id,
        )
        database.update_interaction_artifacts(interaction_id, {"proposed_outreach": outreach})
        database.insert_trace(interaction_id, "DIAGNOSTICS", "Settlement proposal and billing balance adjustment generated.")

    async def execute_qa_audit(self, interaction_id: int, outreach_content: str):
        database.insert_trace(interaction_id, "SYSTEM", "Running outbound QA Compliance check against corporate guidelines...")
        system_instruction_qa = qa_compliance.get_system_prompt()
        
        audit_report = await self.adapter.execute_task(
            prompt="Audit proposed support communication copy",
            system_instruction=system_instruction_qa,
            context_artifacts={"proposed_outreach": outreach_content},
            interaction_id=interaction_id,
        )
        
        # Parse compliance pass
        compliance_pass = 1 if "PASSED" in audit_report else 0
        database.update_interaction_artifacts(interaction_id, {
            "proposed_outreach": f"{outreach_content}\n\n{audit_report}",
            "compliance_pass": compliance_pass
        })
        database.insert_trace(interaction_id, "QA", f"Audit check concluded. Pass rating: {compliance_pass == 1}")

    async def process_campaign_gate(self, interaction_id: int, decision: str, operator_comments: str = ""):
        """Process Gate 1 Sign-Off"""
        details = database.get_interaction_details(interaction_id)
        customer_id = details["interaction"]["customer_id"]
        event_type = details["interaction"]["event_type"]
        raw_cust = database.get_assembled_customer_360(customer_id)
        
        if decision == "APPROVED":
            database.insert_trace(interaction_id, "OPERATOR", f"APPROVED campaign strategy. Notes: {operator_comments}")
            # Progress to QA audit
            await self.execute_qa_audit(interaction_id, details["interaction"]["proposed_outreach"])
            database.update_interaction_status(interaction_id, "COMPLETED")
            database.insert_trace(interaction_id, "SYSTEM", "Campaign dispatched to customer. Lifecycle pipeline completed successfully.")
        else:
            database.insert_trace(interaction_id, "OPERATOR", f"REJECTED campaign proposal with revisions: {operator_comments}")
            database.update_interaction_status(interaction_id, "PLANNING")
            # Loopback: Trigger re-generation appending operator notes
            database.insert_trace(interaction_id, "SYSTEM", "Looping back to Proactive Specialist with revisions...")
            
            system_instruction_pro = proactive.get_system_prompt()
            prompt_pro = f"Revise proactive outreach draft for {raw_cust['crm']['name']} considering feedback: {operator_comments}"
            
            revised_outreach = await self.adapter.execute_task(
                prompt=prompt_pro,
                system_instruction=system_instruction_pro,
                context_artifacts={
                    "customer_name": raw_cust["crm"]["name"],
                    "event_type": event_type,
                    "customer_id": raw_cust["crm"]["id"],
                },
                interaction_id=interaction_id,
            )
            database.update_interaction_artifacts(interaction_id, {
                "proposed_outreach": revised_outreach,
                "audit_comments": operator_comments
            })
            database.update_interaction_status(interaction_id, "PENDING_CAMPAIGN_APPROVAL")
            database.insert_trace(interaction_id, "SUPERVISOR", "🚦 Revised campaign re-drafted. Re-paused at Gate 1 for review.")

    async def process_refund_gate(self, interaction_id: int, decision: str, operator_comments: str = ""):
        """Process Gate 2 Sign-Off"""
        details = database.get_interaction_details(interaction_id)
        customer_id = details["interaction"]["customer_id"]
        raw_cust = database.get_assembled_customer_360(customer_id)
        
        if decision == "APPROVED":
            database.insert_trace(interaction_id, "OPERATOR", f"APPROVED refund and account waiver adjustments. Notes: {operator_comments}")
            # Settle invoice balance in database
            conn = database.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE billing_ledgers SET outstanding_balance = 0.00, last_invoice_status = 'PAID' WHERE customer_id = ?", (customer_id,))
            conn.commit()
            conn.close()
            database.insert_trace(interaction_id, "SYSTEM", "Database ledger updated: Invoice marked as PAID. Balance written off.")
            
            # Progress to QA compliance check
            await self.execute_qa_audit(interaction_id, details["interaction"]["proposed_outreach"])
            database.update_interaction_status(interaction_id, "COMPLETED")
            database.insert_trace(interaction_id, "SYSTEM", "Waiver adjustment closed. Lifecycle pipeline completed successfully.")
        else:
            database.insert_trace(interaction_id, "OPERATOR", f"REJECTED refund proposal with comments: {operator_comments}")
            database.update_interaction_status(interaction_id, "PLANNING")
            # Loopback: Trigger re-generation of resolution based on supervisor notes
            database.insert_trace(interaction_id, "SYSTEM", "Looping back to Diagnostics Specialist with revisions...")
            
            system_instruction_diag = diagnostics.get_system_prompt()
            prompt_diag = f"Revise billing waiver proposal considering supervisor notes: {operator_comments}"
            balance = raw_cust["billing"].get("outstanding_balance", 0.0)
            
            revised_outreach = await self.adapter.execute_task(
                prompt=prompt_diag,
                system_instruction=system_instruction_diag,
                context_artifacts={
                    "customer_name": raw_cust["crm"]["name"],
                    "balance": balance,
                    "customer_id": raw_cust["crm"]["id"],
                },
                interaction_id=interaction_id,
            )
            database.update_interaction_artifacts(interaction_id, {
                "proposed_outreach": revised_outreach,
                "audit_comments": operator_comments
            })
            database.update_interaction_status(interaction_id, "PENDING_REFUND_APPROVAL")
            database.insert_trace(interaction_id, "SUPERVISOR", "🚦 Revised settlement re-drafted. Re-paused at Gate 2 for review.")
