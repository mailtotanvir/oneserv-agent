let customers = [];
let activeCustomerId = 101;
let activeInteractionId = null;
let pollInterval = null;

// Initial Load
document.addEventListener("DOMContentLoaded", () => {
    loadCustomers();
    loadInteractions();
    
    // Periodically poll for status updates
    setInterval(() => {
        loadInteractions();
        if (activeInteractionId) {
            pollActiveCase();
        }
    }, 2000);
});

// Load Customer Registry
async function loadCustomers() {
    try {
        const res = await fetch("/api/customers");
        customers = await res.json();
        
        // Build Customer List Buttons
        const listDiv = document.getElementById("customer-list");
        listDiv.innerHTML = "";
        
        customers.forEach(cust => {
            const btn = document.createElement("button");
            btn.className = `customer-btn ${cust.crm.id === activeCustomerId ? 'active' : ''}`;
            btn.innerText = `${cust.crm.name} (${cust.calculated_health_status})`;
            btn.onclick = () => selectCustomer(cust.crm.id);
            listDiv.appendChild(btn);
        });
        
        // Display active customer details
        displaySelectedCustomer();
    } catch (err) {
        console.error("Error loading customers:", err);
    }
}

// Select active customer
function selectCustomer(id) {
    activeCustomerId = id;
    document.querySelectorAll(".customer-btn").forEach((btn, idx) => {
        btn.classList.toggle("active", customers[idx].crm.id === id);
    });
    displaySelectedCustomer();
}

// Show selected profile in detail views
function displaySelectedCustomer() {
    const cust = customers.find(c => c.crm.id === activeCustomerId);
    if (!cust) return;
    
    document.getElementById("details-tier").innerText = cust.crm.tier;
    document.getElementById("details-balance").innerText = `$${cust.billing.outstanding_balance.toFixed(2)}`;
    document.getElementById("details-invoice-status").innerText = cust.billing.last_invoice_status;
    document.getElementById("details-usage").innerText = `${cust.telemetry.daily_active_days} / 30 Active Days`;
    
    // Switch invoice class indicators
    const statusPill = document.getElementById("details-invoice-status");
    if (cust.billing.last_invoice_status === "FAILED") {
        statusPill.style.color = "var(--accent-red)";
    } else {
        statusPill.style.color = "var(--accent-green)";
    }
    
    // Fill the inspector profile tab
    document.getElementById("tab-spec").innerHTML = `
<h3>👤 Compiled Customer 360 Information</h3>
<br>
<strong>CRM Accounts Profile:</strong>
- Name: ${cust.crm.name}
- Email: ${cust.crm.email}
- Tier: ${cust.crm.tier}
- Account Status: ${cust.crm.status}
- Signup Date: ${cust.crm.signup_date}

<strong>Ledger Balances:</strong>
- Outstanding Invoice: $${cust.billing.outstanding_balance.toFixed(2)}
- Payment Method: ${cust.billing.payment_method}
- Last Status Check: ${cust.billing.last_invoice_status}

<strong>Operational Telemetry (30d):</strong>
- Daily Logins: ${cust.telemetry.daily_active_days} days
- API Transits: ${cust.telemetry.api_calls_30d} requests
- Active Tickets: ${cust.telemetry.support_tickets_30d} items

<strong>Computed Health Index Score:</strong>
- Score: ${cust.calculated_health_score} / 100 (${cust.calculated_health_status})
`;
}

// Load Intervention History List
async function loadInteractions() {
    try {
        const res = await fetch("/api/interactions");
        const history = await res.json();
        
        // Update executive dashboard summary stats
        document.getElementById("metric-interventions").innerText = history.length;
        
        const compliancePasses = history.filter(h => h.compliance_pass === 1).length;
        const complianceRate = history.length > 0 ? Math.round((compliancePasses / history.length) * 100) : 100;
        document.getElementById("metric-compliance").innerText = `${complianceRate}%`;
        
        // Rebuild table rows
        const tbody = document.getElementById("history-rows");
        tbody.innerHTML = "";
        
        if (history.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted)">No historic interventions logged.</td></tr>`;
            return;
        }
        
        history.forEach(item => {
            const tr = document.createElement("tr");
            tr.style.cursor = "pointer";
            tr.onclick = () => {
                activeInteractionId = item.id;
                pollActiveCase();
            };
            
            const isCompliance = item.compliance_pass === 1 
                ? `<span class="pill success">PASSED</span>` 
                : (item.status === "COMPLETED" ? `<span class="pill danger">FAILED</span>` : `<span class="pill">PENDING</span>`);
                
            const statusClass = item.status === "COMPLETED" ? "success" : (item.status.startsWith("PENDING") ? "danger" : "status-pill");
            
            tr.innerHTML = `
                <td>#${item.id}</td>
                <td><strong>${item.customer_name}</strong></td>
                <td>${item.event_type}</td>
                <td><span class="pill ${statusClass}">${item.status}</span></td>
                <td>${isCompliance}</td>
                <td>${new Date(item.created_at).toLocaleTimeString()}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error("Error loading interactions:", err);
    }
}

// Trigger Simulated Event
async function triggerEvent(eventType) {
    try {
        const res = await fetch("/api/trigger", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                customer_id: activeCustomerId,
                event_type: eventType
            })
        });
        
        const data = await res.json();
        
        // Find latest interaction to start polling immediately
        setTimeout(async () => {
            const histRes = await fetch("/api/interactions");
            const hist = await histRes.json();
            if (hist.length > 0) {
                activeInteractionId = hist[0].id;
                pollActiveCase();
            }
        }, 300);
        
    } catch (err) {
        console.error("Error triggering event:", err);
    }
}

// Poll active pipeline details
async function pollActiveCase() {
    if (!activeInteractionId) return;
    
    try {
        const res = await fetch(`/api/interaction/${activeInteractionId}`);
        if (res.status === 404) {
            activeInteractionId = null;
            return;
        }
        const data = await res.json();
        const interaction = data.interaction;
        const traces = data.traces;
        
        // 1. Update stepper
        updateStepper(interaction.status);
        
        // 2. Load console trace logs
        const consoleDiv = document.getElementById("terminal-logs");
        consoleDiv.innerHTML = "";
        traces.forEach(t => {
            const timeStr = new Date(t.timestamp).toLocaleTimeString();
            const div = document.createElement("div");
            div.className = `terminal-line ${t.sender.toLowerCase()}`;
            div.innerText = `[${timeStr}] [${t.sender}] ${t.message}`;
            consoleDiv.appendChild(div);
        });
        consoleDiv.scrollTop = consoleDiv.scrollHeight;
        
        // 3. Load tab proposed outreach
        const outreachTab = document.getElementById("tab-outreach");
        if (interaction.proposed_outreach) {
            outreachTab.innerText = interaction.proposed_outreach;
        } else {
            outreachTab.innerHTML = `<div class="empty-state">No proposed communication draft yet. Triggering pipeline...</div>`;
        }
        
        // 4. Update tab assembled details
        if (interaction.assembled_profile) {
            document.getElementById("tab-spec").innerText = interaction.assembled_profile;
        }
        
        // 5. Check HITL overlays
        const hitlPanel = document.getElementById("hitl-panel");
        const hitlTitle = document.getElementById("hitl-title");
        
        if (interaction.status === "PENDING_CAMPAIGN_APPROVAL") {
            hitlPanel.classList.remove("hidden");
            hitlTitle.innerText = "🚦 HITL Campaign Review Required (Gate 1)";
        } else if (interaction.status === "PENDING_REFUND_APPROVAL") {
            hitlPanel.classList.remove("hidden");
            hitlTitle.innerText = "🚦 HITL Financial Waiver Audit Required (Gate 2)";
        } else {
            hitlPanel.classList.add("hidden");
        }
        
    } catch (err) {
        console.error("Error polling case details:", err);
    }
}

// Update UI progress indicator
function updateStepper(status) {
    document.getElementById("active-status-pill").innerText = status;
    
    const steps = ["step-planning", "step-g1", "step-g2", "step-completed"];
    const lines = ["line-planning", "line-g1", "line-g2"];
    
    steps.forEach(s => document.getElementById(s).className = "step-item");
    lines.forEach(l => document.getElementById(l).className = "step-line");
    
    if (status === "PLANNING") {
        document.getElementById("step-planning").className = "step-item active";
    } else if (status === "PENDING_CAMPAIGN_APPROVAL") {
        document.getElementById("step-planning").className = "step-item completed";
        document.getElementById("line-planning").className = "step-line completed";
        document.getElementById("step-g1").className = "step-item active";
    } else if (status === "PENDING_REFUND_APPROVAL") {
        document.getElementById("step-planning").className = "step-item completed";
        document.getElementById("line-planning").className = "step-line completed";
        document.getElementById("step-g1").className = "step-item completed";
        document.getElementById("line-g1").className = "step-line completed";
        document.getElementById("step-g2").className = "step-item active";
    } else if (status === "COMPLETED") {
        document.getElementById("step-planning").className = "step-item completed";
        document.getElementById("line-planning").className = "step-line completed";
        document.getElementById("step-g1").className = "step-item completed";
        document.getElementById("line-g1").className = "step-line completed";
        document.getElementById("step-g2").className = "step-item completed";
        document.getElementById("line-g2").className = "step-line completed";
        document.getElementById("step-completed").className = "step-item completed";
    }
}

// Switch tabs inside asset inspector
function switchTab(tabId) {
    document.querySelectorAll(".tab-btn").forEach(btn => btn.classList.remove("active"));
    document.querySelectorAll(".tab-pane").forEach(pane => pane.classList.remove("active"));
    
    if (tabId === "tab-spec") {
        document.getElementById("tab-btn-spec").classList.add("active");
        document.getElementById("tab-spec").classList.add("active");
    } else if (tabId === "tab-outreach") {
        document.getElementById("tab-btn-outreach").classList.add("active");
        document.getElementById("tab-outreach").classList.add("active");
    }
}

// Submit Human-in-the-Loop override decisions
async function submitHITL(decision) {
    if (!activeInteractionId) return;
    
    const comments = document.getElementById("hitl-feedback").value;
    
    try {
        const res = await fetch("/api/gate/decision", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                interaction_id: activeInteractionId,
                decision: decision,
                comments: comments
            })
        });
        
        document.getElementById("hitl-feedback").value = "";
        document.getElementById("hitl-panel").classList.add("hidden");
        
        // Reload customers to capture database balance settles instantly
        setTimeout(loadCustomers, 500);
        
    } catch (err) {
        console.error("Error submitting gate decision:", err);
    }
}
