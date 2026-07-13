import sqlite3
import os
import json
from datetime import datetime
from config import config

def get_db_connection():
    conn = sqlite3.connect(config.DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. CRM Profiles Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS crm_profiles (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            tier TEXT NOT NULL,
            status TEXT NOT NULL,
            signup_date TEXT NOT NULL
        )
    """)
    
    # 2. Billing Ledgers Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS billing_ledgers (
            customer_id INTEGER PRIMARY KEY,
            outstanding_balance REAL NOT NULL,
            last_invoice_status TEXT NOT NULL,
            payment_method TEXT NOT NULL,
            FOREIGN KEY (customer_id) REFERENCES crm_profiles(id)
        )
    """)
    
    # 3. Product Telemetry Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS product_telemetry (
            customer_id INTEGER PRIMARY KEY,
            api_calls_30d INTEGER NOT NULL,
            daily_active_days INTEGER NOT NULL,
            support_tickets_30d INTEGER NOT NULL,
            FOREIGN KEY (customer_id) REFERENCES crm_profiles(id)
        )
    """)
    
    # 4. Swarm Interactions (Cases) Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            status TEXT NOT NULL,
            assembled_profile TEXT,
            proposed_outreach TEXT,
            audit_comments TEXT,
            compliance_pass INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (customer_id) REFERENCES crm_profiles(id)
        )
    """)
    
    # 5. Swarm Step Trace Logs
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS interaction_traces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            interaction_id INTEGER NOT NULL,
            sender TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (interaction_id) REFERENCES interactions(id) ON DELETE CASCADE
        )
    """)
    
    conn.commit()
    
    # Seeding Mock Customer Profiles if empty
    cursor.execute("SELECT COUNT(*) FROM crm_profiles")
    if cursor.fetchone()[0] == 0:
        # Seed Customers
        cursor.execute("INSERT INTO crm_profiles VALUES (101, 'Acme Corp', 'contact@acme.com', 'Enterprise', 'Active', '2025-01-15')")
        cursor.execute("INSERT INTO crm_profiles VALUES (102, 'TechStart Inc', 'ceo@techstart.io', 'Growth', 'Active', '2025-05-10')")
        cursor.execute("INSERT INTO crm_profiles VALUES (103, 'John Doe', 'john.doe@gmail.com', 'Free', 'Active', '2026-02-01')")
        
        # Seed Billing Ledgers
        cursor.execute("INSERT INTO billing_ledgers VALUES (101, 0.00, 'PAID', 'ACH Credit')")
        cursor.execute("INSERT INTO billing_ledgers VALUES (102, 0.00, 'PAID', 'Visa *4421')")
        cursor.execute("INSERT INTO billing_ledgers VALUES (103, 150.00, 'FAILED', 'Mastercard *8892')")
        
        # Seed Telemetry
        cursor.execute("INSERT INTO product_telemetry VALUES (101, 85000, 28, 0)")
        cursor.execute("INSERT INTO product_telemetry VALUES (102, 1200, 4, 3)")
        cursor.execute("INSERT INTO product_telemetry VALUES (103, 50, 1, 2)")
        
        conn.commit()
        
    conn.close()

# Database Helper Queries
def create_interaction(customer_id: int, event_type: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute(
        "INSERT INTO interactions (customer_id, event_type, status, created_at) VALUES (?, ?, 'PLANNING', ?)",
        (customer_id, event_type, now)
    )
    interaction_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return interaction_id

def update_interaction_status(interaction_id: int, status: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE interactions SET status = ? WHERE id = ?", (status, interaction_id))
    conn.commit()
    conn.close()

def update_interaction_artifacts(interaction_id: int, fields: dict):
    conn = get_db_connection()
    cursor = conn.cursor()
    for key, value in fields.items():
        cursor.execute(f"UPDATE interactions SET {key} = ? WHERE id = ?", (value, interaction_id))
    conn.commit()
    conn.close()

def insert_trace(interaction_id: int, sender: str, message: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute(
        "INSERT INTO interaction_traces (interaction_id, sender, message, timestamp) VALUES (?, ?, ?, ?)",
        (interaction_id, sender, message, now)
    )
    conn.commit()
    conn.close()

def get_assembled_customer_360(customer_id: int) -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM crm_profiles WHERE id = ?", (customer_id,))
    crm = cursor.fetchone()
    if not crm:
        conn.close()
        return {}
        
    cursor.execute("SELECT * FROM billing_ledgers WHERE customer_id = ?", (customer_id,))
    billing = cursor.fetchone()
    
    cursor.execute("SELECT * FROM product_telemetry WHERE customer_id = ?", (customer_id,))
    telemetry = cursor.fetchone()
    
    conn.close()
    
    # Calculate automated health score
    health_score = 100
    status_label = "Happy"
    
    if telemetry:
        # Heavily penalize support tickets and inactive usage
        health_score -= (telemetry["support_tickets_30d"] * 10)
        health_score -= (30 - telemetry["daily_active_days"]) * 2
        
    if billing and billing["last_invoice_status"] == "FAILED":
        health_score -= 30
        
    health_score = max(5, min(100, health_score))
    if health_score < 40:
        status_label = "Churn-Risk"
    elif health_score < 75:
        status_label = "Neutral"
        
    return {
        "crm": dict(crm),
        "billing": dict(billing) if billing else {},
        "telemetry": dict(telemetry) if telemetry else {},
        "calculated_health_score": health_score,
        "calculated_health_status": status_label
    }

def get_interaction_details(interaction_id: int) -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM interactions WHERE id = ?", (interaction_id,))
    interaction = cursor.fetchone()
    if not interaction:
        conn.close()
        return {}
        
    cursor.execute("SELECT * FROM interaction_traces WHERE interaction_id = ? ORDER BY id ASC", (interaction_id,))
    traces = [dict(r) for r in cursor.fetchall()]
    
    conn.close()
    
    return {
        "interaction": dict(interaction),
        "traces": traces
    }

def get_all_interactions():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT i.*, c.name as customer_name 
        FROM interactions i 
        JOIN crm_profiles c ON i.customer_id = c.id 
        ORDER BY i.id DESC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

# Run init_db automatically on import
init_db()

# Observability tables share the same SQLite file
try:
    from services import observability as _obs
    _obs.init_observability_tables()
except Exception:
    pass
