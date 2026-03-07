/**
 * DevPlane Dashboard — SPA routing, API client, and UI logic.
 */

const API = {
    async get(url) {
        const res = await fetch(url);
        return res.json();
    },
    async post(url, body) {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        return res.json();
    },
    async put(url, body) {
        const res = await fetch(url, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        return res.json();
    },
};

// ─── SPA Router ─────────────────────────────────────────────────────────────

let currentPage = 'dashboard';

function navigate(page) {
    currentPage = page;
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

    const pageEl = document.getElementById(`page-${page}`);
    const navEl = document.querySelector(`[data-page="${page}"]`);
    if (pageEl) pageEl.classList.add('active');
    if (navEl) navEl.classList.add('active');

    document.getElementById('pageTitle').textContent = {
        dashboard: 'Dashboard',
        chains: 'Chain Builder',
        providers: 'Providers',
        credits: 'Credits & Budgets',
        projects: 'Projects',
        history: 'Run History',
    }[page] || 'Dashboard';

    // Load page-specific data
    const loaders = {
        dashboard: loadDashboard,
        providers: loadProviders,
        credits: loadCredits,
        chains: loadChains,
        projects: loadProjects,
        history: loadHistory,
        infra: loadInfra,
        memory: loadMemory,
    };
    if (loaders[page]) loaders[page]();
}

// ─── Dashboard Page ─────────────────────────────────────────────────────────

async function loadDashboard() {
    try {
        const [health, credits] = await Promise.all([
            API.get('/api/health'),
            API.get('/api/credits/summary'),
        ]);

        document.getElementById('stat-providers').textContent = health.providers_active;
        document.getElementById('stat-runs').textContent = health.total_runs;
        document.getElementById('stat-uptime').textContent = formatUptime(health.uptime_seconds);
        document.getElementById('stat-slack').textContent = health.slack_connected ? 'Connected' : 'Offline';
        document.getElementById('slack-dot').className = `dot ${health.slack_connected ? '' : 'offline'}`;

        updateBudgetBars(credits);
    } catch (e) {
        console.error('Dashboard load error:', e);
    }
}

function updateBudgetBars(credits) {
    setBudgetBar('daily', credits.total_today, credits.budget_daily);
    setBudgetBar('weekly', credits.total_this_week, credits.budget_weekly);
    setBudgetBar('monthly', credits.total_this_month, credits.budget_monthly);
}

function setBudgetBar(period, spent, budget) {
    const pct = budget > 0 ? Math.min((spent / budget) * 100, 100) : 0;
    const fill = document.getElementById(`budget-fill-${period}`);
    const value = document.getElementById(`budget-value-${period}`);
    if (fill) {
        fill.style.width = `${pct}%`;
        fill.className = `budget-bar-fill ${pct > 90 ? 'danger' : pct > 70 ? 'warning' : ''}`;
    }
    if (value) value.textContent = `$${spent.toFixed(2)} / $${budget.toFixed(2)}`;
}

// ─── Providers Page ─────────────────────────────────────────────────────────

async function loadProviders() {
    const providers = await API.get('/api/providers');
    const container = document.getElementById('providers-list');
    container.innerHTML = providers.map(p => `
        <div class="provider-card" id="prov-${p.id}">
            <div class="provider-icon">${getProviderEmoji(p.name)}</div>
            <div class="provider-info">
                <div class="name">${p.display_name}</div>
                <div class="key-status">${p.has_key ? `Key: ${p.api_key_masked}` : 'No API key configured'}</div>
            </div>
            <div class="provider-actions">
                <button class="btn btn-sm btn-outline" onclick="showKeyInput(${p.id})">
                    ${p.has_key ? '🔑 Update Key' : '➕ Add Key'}
                </button>
                ${p.has_key ? `<button class="btn btn-sm btn-primary" onclick="testProvider(${p.id})">⚡ Test</button>` : ''}
                <label class="toggle">
                    <input type="checkbox" ${p.enabled ? 'checked' : ''} onchange="toggleProvider(${p.id}, this.checked)">
                    <span class="slider"></span>
                </label>
            </div>
        </div>
        <div id="key-input-${p.id}" style="display:none; padding: 12px 0;">
            <div style="display:flex; gap:12px; align-items:center;">
                <input type="password" id="key-val-${p.id}" placeholder="Enter API key..." style="flex:1">
                <button class="btn btn-sm btn-success" onclick="saveProviderKey(${p.id})">Save</button>
            </div>
        </div>
    `).join('');
}

function getProviderEmoji(name) {
    return {
        openrouter: '🌐', groq: '⚡', deepseek: '🧠', cerebras: '🔬',
        gemini: '♊', fireworks_ai: '🎆', togetherai: '🤝', openai: '🤖',
    }[name] || '🔮';
}

function showKeyInput(id) {
    const el = document.getElementById(`key-input-${id}`);
    el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

async function saveProviderKey(id) {
    const key = document.getElementById(`key-val-${id}`).value;
    if (!key) return;
    await API.put(`/api/providers/${id}`, { api_key: key, enabled: true });
    loadProviders();
}

async function toggleProvider(id, enabled) {
    await API.put(`/api/providers/${id}`, { enabled });
}

async function testProvider(id) {
    const card = document.getElementById(`prov-${id}`);
    const btn = card.querySelector('.btn-primary');
    btn.textContent = '⏳ Testing...';
    btn.disabled = true;
    try {
        const result = await API.post(`/api/providers/${id}/test`);
        btn.textContent = result.success ? '✅ Works!' : '❌ Failed';
        setTimeout(() => { btn.textContent = '⚡ Test'; btn.disabled = false; }, 3000);
    } catch {
        btn.textContent = '❌ Error';
        setTimeout(() => { btn.textContent = '⚡ Test'; btn.disabled = false; }, 3000);
    }
}

// ─── Credits Page ───────────────────────────────────────────────────────────

async function loadCredits() {
    const credits = await API.get('/api/credits/summary');
    updateBudgetBars(credits);

    const providerBody = document.getElementById('provider-spending-body');
    if (providerBody) {
        const allProviders = Object.keys({ ...credits.by_provider, ...credits.provider_limits });
        providerBody.innerHTML = [...new Set(allProviders)].map(name => {
            const spent = credits.by_provider[name] || 0;
            const limit = credits.provider_limits[name] || 0;
            return `<tr>
                <td>${name}</td>
                <td>$${spent.toFixed(4)}</td>
                <td>${limit > 0 ? `$${limit.toFixed(2)}` : 'Unlimited'}</td>
                <td>${limit > 0 ? `${((spent / limit) * 100).toFixed(1)}%` : '—'}</td>
            </tr>`;
        }).join('');
    }
}

// ─── Chains Page ────────────────────────────────────────────────────────────

async function loadChains() {
    try {
        const [chains, health] = await Promise.all([
            API.get('/api/chains'),
            API.get('/api/health'),
        ]);

        if (chains.length > 0) {
            const chain = await API.get(`/api/chains/${chains[0].id}`);

            // Set toggle state based on DB
            const isAgent = !chain.tournament_mode;
            const toggle = document.getElementById('mode-toggle-agent');
            if (toggle) toggle.checked = isAgent;

            if (isAgent) {
                const vis = document.getElementById('chain-vis');
                if (vis) {
                    vis.innerHTML = `
                        <div class="chain-node" style="border-color:var(--accent)">
                            <div class="node-icon">🧠</div>
                            <div class="node-label">LangGraph Agent</div>
                            <div class="node-model">Persistent</div>
                        </div>
                        <div class="chain-arrow">⇄</div>
                        <div class="chain-node">
                            <div class="node-icon">🛠️</div>
                            <div class="node-label">Tools</div>
                            <div class="node-model">System</div>
                        </div>
                    `;
                }
            } else {
                renderChainVis(chain.steps || []);
            }

            // Load tiers
            const projects = await API.get('/api/projects');
            if (projects.length > 0) {
                const tiers = await API.get(`/api/chains/tiers/${projects[0].id}`);
                renderTiers(tiers);

                if (isAgent) {
                    const tContainer = document.getElementById('tiers-container');
                    if (tContainer) {
                        tContainer.style.opacity = '0.3';
                        tContainer.style.pointerEvents = 'none';
                    }
                }
            }
        }
    } catch (e) {
        console.error('Chains load error:', e);
    }
}

function renderChainVis(steps) {
    const container = document.getElementById('chain-vis');
    if (!container) return;
    container.innerHTML = steps.map((s, i) => `
        <div class="chain-node" id="node-${s.step_type}">
            <div class="node-icon">${stepIcon(s.step_type)}</div>
            <div class="node-label">${s.label || s.step_type}</div>
            <div class="node-model">${s.model_slug || 'Per tier'}</div>
        </div>
        ${i < steps.length - 1 ? '<div class="chain-arrow">→</div>' : ''}
    `).join('');
}

function stepIcon(type) {
    return { planner: '📋', executor: '⚙️', reviewer: '✅', judge: '🏆' }[type] || '🔗';
}

function renderTiers(tiers) {
    const container = document.getElementById('tiers-container');
    if (!container) return;
    container.innerHTML = tiers.map(t => `
        <div class="tier-card tier-${t.level}">
            <div class="tier-header">${t.level} tier</div>
            <div class="tier-model-row"><span class="role">Planner</span><span class="model">${t.planner_model || 'Not set'}</span></div>
            <div class="tier-model-row"><span class="role">Executor</span><span class="model">${t.executor_model || 'Not set'}</span></div>
            <div class="tier-model-row"><span class="role">Reviewer</span><span class="model">${t.reviewer_model || 'Not set'}</span></div>
            <div class="tier-model-row"><span class="role">Judge</span><span class="model">${t.judge_model || 'Not set'}</span></div>
            <div class="tier-model-row"><span class="role">Max Cost</span><span class="model">$${t.max_cost_per_run}</span></div>
        </div>
    `).join('');
}

async function toggleAgentMode(isAgent) {
    // Agent Mode = tournament_mode: false
    // Toggle affects the active project's active chain
    try {
        const projects = await API.get('/api/projects');
        if (projects.length === 0) return;
        const chainId = projects[0].active_chain_id;

        await API.put(`/api/chains/${chainId}`, {
            tournament_mode: !isAgent
        });

        // Update UI vis
        const vis = document.getElementById('chain-vis');
        if (isAgent) {
            vis.innerHTML = `
                <div class="chain-node" style="border-color:var(--accent)">
                    <div class="node-icon">🧠</div>
                    <div class="node-label">LangGraph Agent</div>
                    <div class="node-model">Persistent</div>
                </div>
                <div class="chain-arrow">⇄</div>
                <div class="chain-node">
                    <div class="node-icon">🛠️</div>
                    <div class="node-label">Tools</div>
                    <div class="node-model">System</div>
                </div>
            `;
            document.getElementById('tiers-container').style.opacity = '0.3';
            document.getElementById('tiers-container').style.pointerEvents = 'none';
        } else {
            document.getElementById('tiers-container').style.opacity = '1';
            document.getElementById('tiers-container').style.pointerEvents = 'auto';
            loadChains(); // reload standard vis
        }

    } catch (e) {
        console.error("Failed to toggle mode:", e);
    }
}

// ─── Projects Page ──────────────────────────────────────────────────────────

async function loadProjects() {
    const projects = await API.get('/api/projects');
    const container = document.getElementById('projects-list');
    if (!container) return;
    container.innerHTML = projects.map(p => `
        <div class="card">
            <div class="card-header">
                <h3>${p.name} ${p.is_default ? '<span class="badge badge-success">Default</span>' : ''}</h3>
            </div>
            <p style="color:var(--text-muted);font-size:13px;margin-bottom:12px">${p.description || 'No description'}</p>
            <div style="display:flex;gap:16px;font-size:12px;color:var(--text-dim)">
                <span>Daily: $${p.daily_budget}</span>
                <span>Weekly: $${p.weekly_budget}</span>
                <span>Monthly: $${p.monthly_budget}</span>
            </div>
        </div>
    `).join('');
}

// ─── Infrastructure Page ────────────────────────────────────────────────────

async function loadInfra() {
    try {
        const [status, droplets, workspaces] = await Promise.all([
            API.get('/api/infra/status'),
            API.get('/api/infra/droplets'),
            API.get('/api/infra/workspaces')
        ]);

        document.getElementById('stat-active-droplets').textContent = status.active_droplets;
        document.getElementById('stat-active-ws').textContent = status.active_workspaces;
        document.getElementById('stat-infra-cost').textContent = '$' + (status.cost_per_hour || 0).toFixed(4) + '/hr';
        document.getElementById('stat-do-status').textContent = status.configured ? `✅ ${status.region}` : '❌ Missing Token';
        document.getElementById('stat-do-status').style.color = status.configured ? 'var(--accent)' : 'var(--danger)';

        // Render Droplets
        const dBody = document.getElementById('droplets-body');
        if (dBody) {
            dBody.innerHTML = droplets.length ? droplets.map(d => `
                <tr>
                    <td>${d.name}</td>
                    <td>${d.size || d.size_slug || 'Unknown'}</td>
                    <td><span class="badge ${d.status === 'active' ? 'badge-success' : 'badge-warning'}">${d.status}</span></td>
                    <td>${d.public_ip || d.vpc_ip || 'Assigning...'}</td>
                    <td>$${(d.cost_per_hour || 0).toFixed(4)}</td>
                    <td>
                        <button class="btn btn-sm btn-danger" onclick="destroyDroplet(${d.droplet_id || d.id})">🗑️</button>
                    </td>
                </tr>
            `).join('') : `<tr><td colspan="6" style="color:var(--text-dim)">No active droplets</td></tr>`;
        }

        // Render Workspaces
        const wsList = document.getElementById('workspaces-list');
        if (wsList) {
            wsList.innerHTML = workspaces.length ? workspaces.map(w => `
                <div style="background:var(--bg-card); padding:12px; border-radius:8px; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <strong>${w.template}</strong><br>
                        <span style="font-size:12px; color:var(--text-dim)">
                            Status: <span style="color:${w.status === 'running' ? 'var(--success)' : 'var(--warning)'}">${w.status}</span>
                            ${w.connect_url ? `| <a href="${w.connect_url}" target="_blank" style="color:var(--accent)">Connect ↗</a>` : ''}
                        </span>
                    </div>
                    <button class="btn btn-sm btn-danger" onclick="destroyWorkspace('${w.workspace_id}')">Stop</button>
                </div>
            `).join('') : `<div style="color:var(--text-dim); font-size:14px;">No active workspaces.</div>`;
        }

    } catch (e) {
        console.error('Infra load error:', e);
    }
}

async function spinUpVM() {
    const btn = document.getElementById('btn-spin-up');
    btn.textContent = '⏳ Launching...';
    btn.disabled = true;

    try {
        const type = document.getElementById('vm-type').value;
        const size = document.getElementById('vm-size').value;
        const ttl = parseInt(document.getElementById('vm-ttl').value) || 0;

        let endpoint = '/api/infra/droplets';
        let body = { size, droplet_type: type, ttl_minutes: ttl };

        if (type === 'worker') {
            endpoint = '/api/infra/workers';
            body = { size, ttl_minutes: ttl || 30 };
        } else if (type === 'gpu') {
            endpoint = '/api/infra/gpu';
            body = { gpu_size: 'gpu-h100x1-80gb' };
        }

        await API.post(endpoint, body);
        setTimeout(() => { btn.textContent = '✅ Launched!'; loadInfra(); }, 1000);
    } catch (e) {
        btn.textContent = '❌ Error';
        console.error(e);
    } finally {
        setTimeout(() => { btn.textContent = '🚀 Launch'; btn.disabled = false; }, 3000);
    }
}

async function destroyDroplet(id) {
    if (!confirm('Destroy this droplet permanently?')) return;
    await API.post(`/api/infra/droplets/${id}`, { _method: 'DELETE' }); // Fetch wrapper limitation hack => normally use API.delete
    fetch(`/api/infra/droplets/${id}`, { method: 'DELETE' }).then(() => loadInfra());
}

async function launchWorkspace() {
    const btn = document.getElementById('btn-launch-ws');
    btn.textContent = '⏳ Launching...';
    btn.disabled = true;

    try {
        const template = document.getElementById('ws-template').value;
        const res = await API.post('/api/infra/workspaces', { template });

        if (res.workspace_id) {
            alert(`Workspace launched!\n\nAdmin Password: ${res.admin_password}\nUser Password: ${res.user_password}\n\nPlease save this! It will be available in ~5 minutes.`);
            loadInfra();
            btn.textContent = '✅ Launched!';
        } else {
            throw new Error(res.error || 'Failed to lunch');
        }
    } catch (e) {
        btn.textContent = '❌ Error';
        console.error(e);
    } finally {
        setTimeout(() => { btn.textContent = '🖥️ Launch Workspace'; btn.disabled = false; }, 3000);
    }
}

async function destroyWorkspace(id) {
    if (!confirm('Destroy this workspace permanently?')) return;
    fetch(`/api/infra/workspaces/${id}`, { method: 'DELETE' }).then(() => loadInfra());
}

// ─── Memory & Optimizer Page ────────────────────────────────────────────────

async function loadMemory() {
    try {
        const [stats, history, insights] = await Promise.all([
            API.get('/api/memory/stats'),
            API.get('/api/memory/history?limit=5'),
            API.get('/api/optimizer/insights')
        ]);

        document.getElementById('stat-memories').textContent = stats.total_memories;
        document.getElementById('stat-qdrant').textContent = stats.qdrant_connected ? '✅ Active' : '❌ Disabled';
        document.getElementById('stat-optimizer').textContent = insights.total_model_entries;

        // Render History
        const histContainer = document.getElementById('memory-history');
        if (histContainer) {
            histContainer.innerHTML = history.length ? history.map(h => `
                <div style="background:var(--bg-card); padding:12px; border-radius:8px; margin-bottom:8px; font-size:13px;">
                    <strong style="color:var(--accent)">${h.role === 'user' ? '👤 User:' : '🤖 Assistant:'}</strong>
                    <span style="color:var(--text-dim); font-size:11px; float:right;">${h.created_at}</span>
                    <div style="margin-top:6px; color:var(--text-main)">${truncate(h.content, 200)}</div>
                </div>
            `).join('') : '<div style="color:var(--text-dim); font-size:14px;">No memory yet. Run some chains!</div>';
        }

        // Render Insights
        const iBody = document.getElementById('insights-body');
        if (iBody) {
            iBody.innerHTML = insights.all_models?.length ? insights.all_models.map(m => `
                <tr>
                    <td><strong style="color:var(--accent)">${m.model_slug}</strong></td>
                    <td><span class="badge">${m.step_type}</span></td>
                    <td>$${(m.avg_cost || 0).toFixed(6)}</td>
                    <td>${(m.avg_duration_ms / 1000).toFixed(1)}s</td>
                    <td>
                        <div style="background:var(--bg-elevated);width:60px;height:6px;border-radius:3px;display:inline-block;vertical-align:middle;margin-right:8px">
                            <div style="background:var(--accent);height:100%;border-radius:3px;width:${(m.avg_quality * 100)}%"></div>
                        </div>
                        ${(m.avg_quality * 100).toFixed(0)}%
                    </td>
                    <td>${m.total_runs}</td>
                </tr>
            `).join('') : `<tr><td colspan="6" style="color:var(--text-dim)">No performance data yet.</td></tr>`;
        }
    } catch (e) {
        console.error('Memory load error:', e);
    }
}

async function searchMemory() {
    const input = document.getElementById('memory-search-input').value;
    if (!input) return;

    const resContainer = document.getElementById('memory-results');
    resContainer.innerHTML = '<span style="color:var(--text-dim)">Searching vectors...</span>';

    try {
        const results = await API.get(`/api/memory/search?q=${encodeURIComponent(input)}`);

        resContainer.innerHTML = results.length ? results.map(r => `
            <div style="background:var(--bg-card); padding:12px; border-radius:8px; margin-bottom:8px; font-size:13px; border-left: 2px solid var(--accent);">
                <span class="badge badge-success" style="float:right; transform:scale(0.8)">${r.source || 'sqlite'}</span>
                <div style="color:var(--text-main); line-height:1.5">${truncate(r.content, 300)}</div>
            </div>
        `).join('') : '<div style="color:var(--text-dim)">No matching context found.</div>';
    } catch (e) {
        resContainer.innerHTML = `<span style="color:var(--danger)">Search failed: ${e.message}</span>`;
    }
}

async function clearMemory() {
    if (!confirm('Clear all AI memory and context history for this project?')) return;
    await API.post('/api/memory/clear');
    loadMemory();
}

// ─── Chain Runner ───────────────────────────────────────────────────────────

async function runChain() {
    const input = document.getElementById('prompt-input');
    const prompt = input.value.trim();
    if (!prompt) return;

    const output = document.getElementById('run-output');
    output.textContent = '🚀 Initializing agent/chain...';
    output.classList.remove('has-content');

    // Reset chain visualization
    document.querySelectorAll('.chain-node').forEach(n => {
        n.classList.remove('running', 'complete', 'error');
    });

    try {
        const response = await fetch('/api/chains/run/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt })
        });

        if (!response.ok) {
            output.textContent = `❌ Error: ${response.statusText}`;
            return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        let finalContent = "";

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            const lines = chunk.split('\n');

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = JSON.parse(line.substring(6));

                    if (data.step === 'agent') {
                        if (data.status === 'running') {
                            output.textContent = `🧠 Agent Thinking... (${data.data.model})`;
                        } else if (data.status === 'complete' && data.data.partial) {
                            finalContent = data.data.partial + "...";
                            output.textContent = `📝 Writing... \n\n${finalContent}`;
                        }
                    } else if (data.step === 'tools') {
                        output.textContent = `🛠️ Using tools: ${data.data.tools.join(', ')}\n\n${finalContent}`;
                    } else if (data.step === 'final') {
                        const result = data.data;
                        output.textContent = `🏆 Winner/Agent: ${result.winning_tier?.toUpperCase() || 'N/A'}\nCost: $${(result.total_cost || 0).toFixed(4)}\n\n${result.final_output}`;
                        output.classList.add('has-content');
                        document.querySelectorAll('.chain-node').forEach(n => n.classList.add('complete'));

                        // Break early if we get the final response
                        break;
                    } else if (data.step !== 'heartbeat') {
                        // Standard chain step updates
                        const node = document.getElementById(`node-${data.step}`);
                        if (node) {
                            if (data.status === 'running') node.classList.add('running');
                            if (data.status === 'complete') {
                                node.classList.remove('running');
                                node.classList.add('complete');
                            }
                            if (data.status === 'error') {
                                node.classList.remove('running');
                                node.classList.add('error');
                            }
                        }
                    }
                }
            }
        }

        // Refresh dashboard data
        loadDashboard();
    } catch (e) {
        output.textContent = `❌ Error: ${e.message}`;
    }
}

// ─── Utilities ──────────────────────────────────────────────────────────────

function formatUptime(seconds) {
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
    return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function truncate(str, len) {
    return str && str.length > len ? str.substring(0, len) + '...' : str || '';
}

// ─── Init ───────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.nav-item').forEach(el => {
        el.addEventListener('click', () => navigate(el.dataset.page));
    });

    // Enter key to run chain
    const promptInput = document.getElementById('prompt-input');
    if (promptInput) {
        promptInput.addEventListener('keypress', e => {
            if (e.key === 'Enter') runChain();
        });
    }

    navigate('dashboard');
});
