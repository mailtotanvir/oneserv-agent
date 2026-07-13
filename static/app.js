/* oneserv-agent — Multi-Provider & MCP Observability + Lifecycle Swarm */

let customers = [];
let activeCustomerId = 101;
let activeInteractionId = null;
let providersCache = [];
let currentView = "observe";

// ── Boot ────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
    loadCustomers();
    loadInteractions();
    refreshObservability();

    setInterval(() => {
        if (currentView === "observe") {
            refreshObservability();
        } else {
            loadInteractions();
            if (activeInteractionId) pollActiveCase();
        }
    }, 2000);
});

function switchView(view) {
    currentView = view;
    document.querySelectorAll(".view-tab").forEach((t) => {
        t.classList.toggle("active", t.dataset.view === view);
    });
    document.getElementById("view-observe").classList.toggle("active", view === "observe");
    document.getElementById("view-swarm").classList.toggle("active", view === "swarm");
    if (view === "observe") refreshObservability();
    if (view === "swarm") {
        loadCustomers();
        loadInteractions();
    }
}

// ── Observability ───────────────────────────────────────────────────────────

async function refreshObservability() {
    try {
        const [summary, providers, agents, bridges, tools, inv, mcpCalls, events] =
            await Promise.all([
                fetch("/api/observability/summary").then((r) => r.json()),
                fetch("/api/providers").then((r) => r.json()),
                fetch("/api/agents").then((r) => r.json()),
                fetch("/api/mcp/bridges").then((r) => r.json()),
                fetch("/api/mcp/tools").then((r) => r.json()),
                fetch("/api/observability/invocations?limit=40").then((r) => r.json()),
                fetch("/api/observability/mcp-calls?limit=40").then((r) => r.json()),
                fetch("/api/observability/events?limit=80").then((r) => r.json()),
            ]);

        renderObsMetrics(summary);
        providersCache = providers.providers || [];
        renderProviders(providersCache);
        renderAgents(agents.agents || [], providersCache);
        renderBridges(bridges.bridges || []);
        renderTools(tools.tools || []);
        renderInvocations(inv || []);
        renderMcpCalls(mcpCalls || []);
        renderObsEvents(events || []);

        const mode = summary.provider_mode || "multi";
        document.getElementById("mode-pill").textContent = `mode: ${mode}`;
        document.getElementById("header-status").textContent = "Control Plane: ONLINE";
    } catch (err) {
        console.error("Observability refresh failed:", err);
        document.getElementById("header-status").textContent = "Control Plane: DEGRADED";
    }
}

function renderObsMetrics(summary) {
    const p = summary.providers || {};
    const m = summary.mcp || {};
    const inv = summary.invocations || {};
    const mc = summary.mcp_calls || {};

    document.getElementById("m-providers").textContent =
        `${p.online_count ?? 0}/${p.provider_count ?? 0}`;
    document.getElementById("m-providers-sub").textContent =
        `avg ${p.avg_latency_ms ?? 0} ms · ${p.total_requests ?? 0} reqs`;

    document.getElementById("m-invocations").textContent = inv.total_invocations ?? 0;
    document.getElementById("m-invocations-sub").textContent =
        `avg ${inv.avg_latency_ms ?? 0} ms · ${inv.total_tokens ?? 0} tokens`;

    document.getElementById("m-bridges").textContent =
        `${m.connected_count ?? 0}/${m.bridge_count ?? 0}`;
    document.getElementById("m-bridges-sub").textContent =
        `${m.tool_count ?? 0} tools exposed`;

    document.getElementById("m-mcp-calls").textContent = mc.total_calls ?? 0;
    const errPct = ((mc.error_rate || 0) * 100).toFixed(1);
    document.getElementById("m-mcp-calls-sub").textContent =
        `error rate ${errPct}% · avg ${mc.avg_latency_ms ?? 0} ms`;

    document.getElementById("mcp-pill").textContent =
        `${m.connected_count ?? 0} connected`;
}

function statusClass(status) {
    return (status || "offline").toLowerCase();
}

function renderProviders(list) {
    const el = document.getElementById("provider-list");
    if (!list.length) {
        el.innerHTML = `<div class="empty-state">No providers registered.</div>`;
        return;
    }
    el.innerHTML = list
        .map((p) => {
            const lat = p.avg_latency_ms || 0;
            const barW = Math.min(60, Math.max(4, lat / 12));
            const errRate =
                p.total_requests > 0
                    ? ((p.total_errors / p.total_requests) * 100).toFixed(1)
                    : "0.0";
            const caps = (p.capabilities || [])
                .slice(0, 4)
                .map((c) => `<span class="cap-tag">${c}</span>`)
                .join("");
            return `
            <div class="entity-row">
                <div class="entity-main">
                    <div class="entity-title">
                        <span class="status-dot ${statusClass(p.status)}"></span>
                        ${escapeHtml(p.name)}
                        <span class="pill ${p.status === "online" || p.status === "simulated" ? "success" : p.status === "degraded" ? "warn" : "danger"}">${escapeHtml(p.status)}</span>
                    </div>
                    <div class="entity-meta">
                        <span>${escapeHtml(p.model)}</span>
                        <span>${escapeHtml(p.region)}</span>
                        <span><span class="latency-bar" style="width:${barW}px"></span>${lat.toFixed(0)} ms</span>
                        <span>${p.total_requests} req · ${errRate}% err · ${p.total_tokens} tok</span>
                    </div>
                    <div class="cap-tags">${caps}</div>
                </div>
                <div class="entity-actions">
                    <button class="btn-xs" onclick="pingProvider('${p.id}')">Health</button>
                </div>
            </div>`;
        })
        .join("");
}

function renderAgents(agents, providers) {
    const el = document.getElementById("agent-list");
    if (!agents.length) {
        el.innerHTML = `<div class="empty-state">No agents bound.</div>`;
        return;
    }
    const opts = providers
        .map(
            (p) =>
                `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)} (${escapeHtml(p.status)})</option>`
        )
        .join("");

    el.innerHTML = agents
        .map((a) => {
            return `
            <div class="agent-bind-row">
                <div class="entity-main">
                    <div class="entity-title">
                        <span class="status-dot ${statusClass(a.provider_status)}"></span>
                        ${escapeHtml(a.agent_name)}
                    </div>
                    <div class="entity-meta">
                        <span>id: ${escapeHtml(a.agent_id)}</span>
                        <span>model: ${escapeHtml(a.model)}</span>
                        <span class="pill info">${escapeHtml(a.provider_id)}</span>
                    </div>
                </div>
                <select data-agent="${escapeHtml(a.agent_id)}" onchange="bindAgent(this)">
                    ${opts.replace(
                        `value="${a.provider_id}"`,
                        `value="${a.provider_id}" selected`
                    )}
                </select>
            </div>`;
        })
        .join("");
}

function renderBridges(bridges) {
    const el = document.getElementById("bridge-list");
    if (!bridges.length) {
        el.innerHTML = `<div class="empty-state">No MCP bridges.</div>`;
        return;
    }
    el.innerHTML = bridges
        .map((b) => {
            const errRate = ((b.error_rate || 0) * 100).toFixed(1);
            const tags = (b.tags || [])
                .map((t) => `<span class="cap-tag">${escapeHtml(t)}</span>`)
                .join("");
            const toggleBtn =
                b.status === "connected"
                    ? `<button class="btn-xs danger" onclick="setBridgeStatus('${b.id}','disconnected')">Disconnect</button>`
                    : `<button class="btn-xs success" onclick="setBridgeStatus('${b.id}','connected')">Connect</button>`;
            return `
            <div class="entity-row">
                <div class="entity-main">
                    <div class="entity-title">
                        <span class="status-dot ${statusClass(b.status)}"></span>
                        ${escapeHtml(b.name)}
                        <span class="pill ${b.status === "connected" ? "success" : b.status === "error" ? "danger" : "warn"}">${escapeHtml(b.status)}</span>
                    </div>
                    <div class="entity-meta">
                        <span>${escapeHtml(b.transport)}</span>
                        <span>${escapeHtml(b.endpoint)}</span>
                        <span>${b.tool_count} tools</span>
                        <span>ping ${b.last_ping_ms || 0} ms · ${b.total_calls} calls · ${errRate}% err</span>
                    </div>
                    <div class="entity-meta" style="margin-top:2px">${escapeHtml(b.description || "")}</div>
                    <div class="cap-tags">${tags}</div>
                </div>
                <div class="entity-actions">
                    <button class="btn-xs" onclick="pingBridge('${b.id}')">Ping</button>
                    ${toggleBtn}
                </div>
            </div>`;
        })
        .join("");
}

function renderTools(tools) {
    const tbody = document.getElementById("tool-rows");
    if (!tools.length) {
        tbody.innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--text-muted)">No tools exposed.</td></tr>`;
        return;
    }
    tbody.innerHTML = tools
        .map((t) => {
            const st =
                t.bridge_status === "connected"
                    ? `<span class="pill success">ready</span>`
                    : `<span class="pill danger">${escapeHtml(t.bridge_status)}</span>`;
            const disabled = t.bridge_status !== "connected" ? "disabled" : "";
            return `
            <tr>
                <td><strong>${escapeHtml(t.bridge_name)}</strong></td>
                <td><code style="font-size:0.72rem">${escapeHtml(t.tool_name)}</code></td>
                <td>${st}</td>
                <td><button class="btn-xs" ${disabled} onclick="callTool('${escapeHtml(t.bridge_id)}','${escapeHtml(t.tool_name)}')">Call</button></td>
            </tr>`;
        })
        .join("");
}

function renderInvocations(rows) {
    const tbody = document.getElementById("invocation-rows");
    if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-muted)">No agent invocations yet. Run traffic or a swarm pipeline.</td></tr>`;
        return;
    }
    tbody.innerHTML = rows
        .map((r) => {
            const t = r.started_at ? new Date(r.started_at).toLocaleTimeString() : "—";
            const st =
                r.status === "ok" || r.status === "success"
                    ? `<span class="pill success">ok</span>`
                    : `<span class="pill danger">${escapeHtml(r.status)}</span>`;
            return `
            <tr>
                <td>${t}</td>
                <td><strong>${escapeHtml(r.agent_id)}</strong></td>
                <td>${escapeHtml(r.provider_id)}</td>
                <td style="font-family:JetBrains Mono,monospace;font-size:0.68rem">${escapeHtml(r.model || "—")}</td>
                <td>${(r.latency_ms ?? 0).toFixed(0)} ms</td>
                <td>${r.tokens ?? 0}</td>
                <td>${st}</td>
            </tr>`;
        })
        .join("");
}

function renderMcpCalls(rows) {
    const tbody = document.getElementById("mcp-call-rows");
    if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">No MCP tool calls yet.</td></tr>`;
        return;
    }
    tbody.innerHTML = rows
        .map((r) => {
            const t = r.started_at ? new Date(r.started_at).toLocaleTimeString() : "—";
            const st =
                r.status === "ok"
                    ? `<span class="pill success">ok</span>`
                    : `<span class="pill danger">${escapeHtml(r.status)}</span>`;
            return `
            <tr>
                <td>${t}</td>
                <td>${escapeHtml(r.bridge_id)}</td>
                <td><code style="font-size:0.72rem">${escapeHtml(r.tool_name)}</code></td>
                <td>${escapeHtml(r.agent_id || "—")}</td>
                <td>${(r.latency_ms ?? 0).toFixed(0)} ms</td>
                <td>${st}</td>
            </tr>`;
        })
        .join("");
}

function renderObsEvents(events) {
    const el = document.getElementById("obs-events");
    if (!events.length) {
        el.innerHTML = `<div class="terminal-line system">Waiting for provider / MCP activity…</div>`;
        return;
    }
    // Events are newest-first; show chronological in terminal
    const ordered = [...events].reverse();
    el.innerHTML = ordered
        .map((e) => {
            const t = e.created_at ? new Date(e.created_at).toLocaleTimeString() : "";
            const cls = (e.event_type || e.severity || "system").toLowerCase();
            return `<div class="terminal-line ${cls}">[${t}] [${escapeHtml(e.source || "sys")}] ${escapeHtml(e.message)}</div>`;
        })
        .join("");
    el.scrollTop = el.scrollHeight;
}

// ── Control actions ─────────────────────────────────────────────────────────

async function pingProvider(id) {
    try {
        await fetch(`/api/providers/${id}/health`, { method: "POST" });
        refreshObservability();
    } catch (e) {
        console.error(e);
    }
}

async function healthCheckAll() {
    try {
        await fetch("/api/providers/health", { method: "POST" });
        refreshObservability();
    } catch (e) {
        console.error(e);
    }
}

async function pingBridge(id) {
    try {
        await fetch(`/api/mcp/bridges/${id}/ping`, { method: "POST" });
        refreshObservability();
    } catch (e) {
        console.error(e);
    }
}

async function pingAllBridges() {
    try {
        await fetch("/api/mcp/bridges/ping", { method: "POST" });
        refreshObservability();
    } catch (e) {
        console.error(e);
    }
}

async function setBridgeStatus(id, status) {
    try {
        await fetch(`/api/mcp/bridges/${id}/status`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status }),
        });
        refreshObservability();
    } catch (e) {
        console.error(e);
    }
}

async function bindAgent(selectEl) {
    const agent_id = selectEl.dataset.agent;
    const provider_id = selectEl.value;
    try {
        await fetch("/api/agents/bind", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ agent_id, provider_id }),
        });
        refreshObservability();
    } catch (e) {
        console.error(e);
    }
}

async function callTool(bridge_id, tool_name) {
    const args = {};
    if (tool_name.includes("customer") || ["crm_get_profile", "billing_get_ledger", "telemetry_get_usage", "ledger_status"].includes(tool_name)) {
        args.customer_id = activeCustomerId || 101;
    }
    if (tool_name === "fs_list") args.path = "artifacts";
    if (tool_name === "fs_read") args.path = "artifacts/sample.md";
    if (tool_name === "web_search") args.query = "compliance policy";
    if (tool_name === "web_fetch") args.url = "https://policy.oneserv.local/compliance";
    if (tool_name === "slack_post") {
        args.channel = "#ops";
        args.text = "Manual MCP probe from dashboard";
    }
    try {
        await fetch("/api/mcp/call", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                bridge_id,
                tool_name,
                arguments: args,
                agent_id: "operator",
            }),
        });
        refreshObservability();
    } catch (e) {
        console.error(e);
    }
}

async function simulateTraffic() {
    // Trigger a short lifecycle pipeline so agent + MCP telemetry floods in
    try {
        await fetch("/api/trigger", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                customer_id: activeCustomerId || 101,
                event_type: "Churn Threat: Usage Drop 80%",
            }),
        });
        // Also poke a couple of MCP tools directly
        await callTool("mcp-sqlite", "crm_get_profile");
        setTimeout(refreshObservability, 800);
        setTimeout(refreshObservability, 2000);
        setTimeout(refreshObservability, 4000);
    } catch (e) {
        console.error(e);
    }
}

function escapeHtml(str) {
    if (str == null) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

// ── Lifecycle swarm (existing) ──────────────────────────────────────────────

async function loadCustomers() {
    try {
        const res = await fetch("/api/customers");
        customers = await res.json();

        const listDiv = document.getElementById("customer-list");
        if (!listDiv) return;
        listDiv.innerHTML = "";

        customers.forEach((cust) => {
            const btn = document.createElement("button");
            btn.className = `customer-btn ${cust.crm.id === activeCustomerId ? "active" : ""}`;
            btn.innerText = `${cust.crm.name} (${cust.calculated_health_status})`;
            btn.onclick = () => selectCustomer(cust.crm.id);
            listDiv.appendChild(btn);
        });

        displaySelectedCustomer();
    } catch (err) {
        console.error("Error loading customers:", err);
    }
}

function selectCustomer(id) {
    activeCustomerId = id;
    document.querySelectorAll(".customer-btn").forEach((btn, idx) => {
        btn.classList.toggle("active", customers[idx]?.crm?.id === id);
    });
    displaySelectedCustomer();
}

function displaySelectedCustomer() {
    const cust = customers.find((c) => c.crm.id === activeCustomerId);
    if (!cust) return;

    document.getElementById("details-tier").innerText = cust.crm.tier;
    document.getElementById("details-balance").innerText = `$${cust.billing.outstanding_balance.toFixed(2)}`;
    document.getElementById("details-invoice-status").innerText = cust.billing.last_invoice_status;
    document.getElementById("details-usage").innerText = `${cust.telemetry.daily_active_days} / 30 Active Days`;

    const statusPill = document.getElementById("details-invoice-status");
    statusPill.style.color =
        cust.billing.last_invoice_status === "FAILED" ? "var(--accent-red)" : "var(--accent-green)";

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

async function loadInteractions() {
    try {
        const res = await fetch("/api/interactions");
        const history = await res.json();

        document.getElementById("metric-interventions").innerText = history.length;

        const compliancePasses = history.filter((h) => h.compliance_pass === 1).length;
        const complianceRate =
            history.length > 0 ? Math.round((compliancePasses / history.length) * 100) : 100;
        document.getElementById("metric-compliance").innerText = `${complianceRate}%`;

        const tbody = document.getElementById("history-rows");
        tbody.innerHTML = "";

        if (history.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted)">No historic interventions logged.</td></tr>`;
            return;
        }

        history.forEach((item) => {
            const tr = document.createElement("tr");
            tr.style.cursor = "pointer";
            tr.onclick = () => {
                activeInteractionId = item.id;
                pollActiveCase();
            };

            const isCompliance =
                item.compliance_pass === 1
                    ? `<span class="pill success">PASSED</span>`
                    : item.status === "COMPLETED"
                      ? `<span class="pill danger">FAILED</span>`
                      : `<span class="pill">PENDING</span>`;

            const statusClass =
                item.status === "COMPLETED"
                    ? "success"
                    : item.status.startsWith("PENDING")
                      ? "danger"
                      : "status-pill";

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

async function triggerEvent(eventType) {
    try {
        await fetch("/api/trigger", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                customer_id: activeCustomerId,
                event_type: eventType,
            }),
        });

        setTimeout(async () => {
            const histRes = await fetch("/api/interactions");
            const hist = await histRes.json();
            if (hist.length > 0) {
                activeInteractionId = hist[0].id;
                pollActiveCase();
            }
        }, 400);
    } catch (err) {
        console.error("Error triggering event:", err);
    }
}

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

        updateStepper(interaction.status);

        const consoleDiv = document.getElementById("terminal-logs");
        consoleDiv.innerHTML = "";
        traces.forEach((t) => {
            const timeStr = new Date(t.timestamp).toLocaleTimeString();
            const div = document.createElement("div");
            div.className = `terminal-line ${t.sender.toLowerCase()}`;
            div.innerText = `[${timeStr}] [${t.sender}] ${t.message}`;
            consoleDiv.appendChild(div);
        });
        consoleDiv.scrollTop = consoleDiv.scrollHeight;

        const outreachTab = document.getElementById("tab-outreach");
        if (interaction.proposed_outreach) {
            outreachTab.innerText = interaction.proposed_outreach;
        } else {
            outreachTab.innerHTML = `<div class="empty-state">No proposed communication draft yet. Triggering pipeline...</div>`;
        }

        if (interaction.assembled_profile) {
            document.getElementById("tab-spec").innerText = interaction.assembled_profile;
        }

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

function updateStepper(status) {
    document.getElementById("active-status-pill").innerText = status;

    const steps = ["step-planning", "step-g1", "step-g2", "step-completed"];
    const lines = ["line-planning", "line-g1", "line-g2"];

    steps.forEach((s) => (document.getElementById(s).className = "step-item"));
    lines.forEach((l) => (document.getElementById(l).className = "step-line"));

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

function switchTab(tabId) {
    document.querySelectorAll(".tab-btn").forEach((btn) => btn.classList.remove("active"));
    document.querySelectorAll(".tab-pane").forEach((pane) => pane.classList.remove("active"));

    if (tabId === "tab-spec") {
        document.getElementById("tab-btn-spec").classList.add("active");
        document.getElementById("tab-spec").classList.add("active");
    } else if (tabId === "tab-outreach") {
        document.getElementById("tab-btn-outreach").classList.add("active");
        document.getElementById("tab-outreach").classList.add("active");
    }
}

async function submitHITL(decision) {
    if (!activeInteractionId) return;

    const comments = document.getElementById("hitl-feedback").value;

    try {
        await fetch("/api/gate/decision", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                interaction_id: activeInteractionId,
                decision: decision,
                comments: comments,
            }),
        });

        document.getElementById("hitl-feedback").value = "";
        document.getElementById("hitl-panel").classList.add("hidden");
        setTimeout(loadCustomers, 500);
    } catch (err) {
        console.error("Error submitting gate decision:", err);
    }
}
