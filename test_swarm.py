import unittest
import os
import asyncio
from config import config

# Set test DB path in TEMP to avoid WSL/9p file locks
TEST_DB_PATH = os.path.join(os.environ.get("TEMP", "/tmp"), "test_oneserv.db")
config.DB_PATH = TEST_DB_PATH

import database
from services import observability
from services.orchestrator import OneServOrchestrator

class TestCustomerSwarm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
        database.init_db()
        observability.init_observability_tables()
        cls.orchestrator = OneServOrchestrator()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

    def test_01_profile_assembler_db_join(self):
        """Verify that joining database registers retrieves unified customer details."""
        cust_profile = database.get_assembled_customer_360(102)
        self.assertEqual(cust_profile["crm"]["name"], "TechStart Inc")
        self.assertEqual(cust_profile["crm"]["tier"], "Growth")
        self.assertEqual(cust_profile["telemetry"]["daily_active_days"], 4)
        self.assertEqual(cust_profile["calculated_health_status"], "Churn-Risk")

    def test_02_pipeline_gating_on_churn_risk(self):
        """Verify initiating a churn risk alert pauses at Gate 1 (Campaign approval)."""
        interaction_id = asyncio.run(
            self.orchestrator.initiate_pipeline(102, "Churn Threat: Usage Drop 80%")
        )
        self.assertIsNotNone(interaction_id)
        
        details = database.get_interaction_details(interaction_id)
        self.assertEqual(details["interaction"]["status"], "PENDING_CAMPAIGN_APPROVAL")
        self.assertIn("subscription invoice credit", details["interaction"]["proposed_outreach"])

    def test_03_pipeline_gating_on_billing_dispute(self):
        """Verify initiating a billing dispute alert pauses at Gate 2 (Refund approval)."""
        interaction_id = asyncio.run(
            self.orchestrator.initiate_pipeline(103, "Failed Payment Dispute")
        )
        self.assertIsNotNone(interaction_id)
        
        details = database.get_interaction_details(interaction_id)
        self.assertEqual(details["interaction"]["status"], "PENDING_REFUND_APPROVAL")
        self.assertIn("waiver adjustment", details["interaction"]["proposed_outreach"])

    def test_04_hitl_refund_gate_approval_and_settlement(self):
        """Verify approving Gate 2 settles database invoice ledger balances."""
        interaction_id = asyncio.run(
            self.orchestrator.initiate_pipeline(103, "Failed Payment Dispute")
        )
        
        # Approve Gate 2
        asyncio.run(
            self.orchestrator.process_refund_gate(interaction_id, "APPROVED", "Supervisor manual override.")
        )
        
        # Check database balance is settled
        cust_profile = database.get_assembled_customer_360(103)
        self.assertEqual(cust_profile["billing"]["outstanding_balance"], 0.00)
        self.assertEqual(cust_profile["billing"]["last_invoice_status"], "PAID")
        
        details = database.get_interaction_details(interaction_id)
        self.assertEqual(details["interaction"]["status"], "COMPLETED")
        self.assertEqual(details["interaction"]["compliance_pass"], 1)

if __name__ == "__main__":
    unittest.main()
