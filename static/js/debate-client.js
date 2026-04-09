/**
 * Agent Debate System - Frontend API Client
 * M2: Frontend/Backend Integration
 */

const API_BASE = 'https://productivity-rec-com-villas.trycloudflare.com';

// ============== API Client ==============

async function apiRequest(endpoint, options = {}) {
    const url = `${API_BASE}${endpoint}`;
    const response = await fetch(url, {
        headers: {
            'Content-Type': 'application/json',
            ...options.headers
        },
        ...options
    });
    
    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(error.detail || `HTTP ${response.status}`);
    }
    
    return response.json();
}

// ============== Debate API ==============

async function createDebate(debateData) {
    return apiRequest('/debates', {
        method: 'POST',
        body: JSON.stringify(debateData)
    });
}

async function getDebate(debateId) {
    return apiRequest(`/debates/${debateId}`);
}

async function listDebates(limit = 10) {
    return apiRequest(`/debates?limit=${limit}`);
}

async function startDebate(debateId, hostId) {
    return apiRequest(`/debates/${debateId}/start`, {
        method: 'POST',
        body: JSON.stringify({ host_id: hostId })
    });
}

async function finalizeDebate(debateId, hostId) {
    return apiRequest(`/debates/${debateId}/finalize`, {
        method: 'POST',
        body: JSON.stringify({ host_id: hostId })
    });
}

// ============== Participant API ==============

async function joinDebate(token, name, participantType = 'human') {
    return apiRequest('/debates/join', {
        method: 'POST',
        body: JSON.stringify({
            token,
            name,
            participant_type: participantType
        })
    });
}

// ============== Turn API ==============

async function submitTurn(debateId, participantId, content) {
    return apiRequest(`/debates/${debateId}/turns?participant_id=${participantId}`, {
        method: 'POST',
        body: JSON.stringify({ content })
    });
}

async function listTurns(debateId) {
    return apiRequest(`/debates/${debateId}/turns`);
}

// ============== Score API ==============

async function submitScore(debateId, judgeId, scoreData) {
    return apiRequest(`/debates/${debateId}/scores`, {
        method: 'POST',
        body: JSON.stringify(scoreData),
        headers: { 'X-Judge-ID': judgeId }
    });
}

async function listScores(debateId) {
    return apiRequest(`/debates/${debateId}/scores`);
}

// ============== Invite Token API ==============

async function createInviteToken(debateId, tokenData, createdBy) {
    return apiRequest(`/debates/${debateId}/invite-tokens`, {
        method: 'POST',
        body: JSON.stringify({
            ...tokenData,
            created_by: createdBy
        })
    });
}

async function listInviteTokens(debateId) {
    return apiRequest(`/debates/${debateId}/invite-tokens`);
}

// ============== Results API ==============

async function getResults(debateId) {
    return apiRequest(`/debates/${debateId}/results`);
}

// ============== Debate Log API ==============

async function getDebateLog(debateId) {
    return apiRequest(`/debates/${debateId}/log`);
}

async function exportDebate(debateId) {
    const response = await fetch(`${API_BASE}/debates/${debateId}/export`);
    if (!response.ok) {
        throw new Error(`Export failed: HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `debate_${debateId}.json`;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);
}

// ============== UI Helpers ==============

function showError(message) {
    const errorDiv = document.getElementById('error-message');
    if (errorDiv) {
        errorDiv.textContent = message;
        errorDiv.style.display = 'block';
        setTimeout(() => errorDiv.style.display = 'none', 5000);
    } else {
        alert(message);
    }
}

function showSuccess(message) {
    const successDiv = document.getElementById('success-message');
    if (successDiv) {
        successDiv.textContent = message;
        successDiv.style.display = 'block';
        setTimeout(() => successDiv.style.display = 'none', 3000);
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDate(dateString) {
    return new Date(dateString).toLocaleString();
}

function getStatusBadge(status) {
    const colors = {
        'pending': { bg: '#fef3c7', text: '#92400e' },
        'opening': { bg: '#dbeafe', text: '#1e40af' },
        'rebuttal_1': { bg: '#fce7f3', text: '#9d174d' },
        'rebuttal_2': { bg: '#fce7f3', text: '#9d174d' },
        'cross_exam': { bg: '#e0e7ff', text: '#3730a3' },
        'closing': { bg: '#f3e8ff', text: '#6b21a8' },
        'judging': { bg: '#f3e8ff', text: '#6b21a8' },
        'complete': { bg: '#d1fae5', text: '#065f46' },
        'cancelled': { bg: '#fee2e2', text: '#991b1b' }
    };
    const c = colors[status] || { bg: '#f3f4f6', text: '#374151' };
    return `<span style="background: ${c.bg}; color: ${c.text}; padding: 0.25rem 0.75rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 500; text-transform: uppercase;">${status}</span>`;
}

// ============== Debate Room State ==============

let currentDebate = null;
let currentParticipant = null;
let refreshInterval = null;

// ============== Debate Room UI ==============

async function loadDebateRoom(debateId) {
    try {
        currentDebate = await getDebate(debateId);
        renderDebateRoom();
        
        // Auto-refresh for live updates
        if (refreshInterval) clearInterval(refreshInterval);
        refreshInterval = setInterval(() => refreshDebate(debateId), 3000);
        
    } catch (error) {
        showError(`Failed to load debate: ${error.message}`);
    }
}

async function refreshDebate(debateId) {
    try {
        const debate = await getDebate(debateId);
        if (JSON.stringify(debate) !== JSON.stringify(currentDebate)) {
            currentDebate = debate;
            renderDebateRoom();
        }
    } catch (error) {
        console.error('Refresh error:', error);
    }
}

function renderDebateRoom() {
    if (!currentDebate) return;
    
    const container = document.getElementById('debate-room');
    if (!container) return;
    
    const d = currentDebate;
    
    container.innerHTML = `
        <div class="debate-header">
            <h2>${escapeHtml(d.title)}</h2>
            <p>${escapeHtml(d.proposition)}</p>
            <div class="debate-meta">
                ${getStatusBadge(d.status)}
                <span>Created: ${formatDate(d.created_at)}</span>
                <span>Phase: ${d.current_phase}</span>
            </div>
        </div>
        
        <div class="debate-participants">
            <h3>Participants (${d.participants.length})</h3>
            <div class="participants-grid">
                ${d.participants.map(p => `
                    <div class="participant-card ${p.side}">
                        <strong>${escapeHtml(p.name)}</strong>
                        <span class="side-badge ${p.side}">${p.side}</span>
                        <small>${p.participant_type}</small>
                    </div>
                `).join('')}
            </div>
        </div>
        
        <div class="debate-turns">
            <h3>Turns (${d.turns.length})</h3>
            <div class="turns-list">
                ${d.turns.map(t => `
                    <div class="turn-item ${t.phase}">
                        <div class="turn-header">
                            <strong>${escapeHtml(t.participant_name)}</strong>
                            <span class="turn-phase">${t.phase}</span>
                            <small>${formatDate(t.submitted_at)}</small>
                        </div>
                        <div class="turn-content">${escapeHtml(t.content)}</div>
                        ${t.char_limit_violation ? '<span class="violation">⚠️ Character limit exceeded</span>' : ''}
                    </div>
                `).join('')}
            </div>
        </div>
        
        ${renderActionPanel()}
        
        ${renderDebateLogPanel()}
        
        ${renderExportPanel()}
    `;
}

function renderDebateLogPanel() {
    if (!currentDebate) return '';
    
    return `
        <div class="debate-log-section">
            <h3>Debate Log <button class="btn btn-secondary" onclick="DebateClient.loadDebateLog()">Refresh Log</button></h3>
            <div id="debate-log-content" class="log-list">
                <p>Click "Refresh Log" to load debate events</p>
            </div>
        </div>
    `;
}

function renderExportPanel() {
    if (!currentDebate) return '';
    
    return `
        <div class="export-section">
            <h3>Export</h3>
            <button class="btn btn-secondary" onclick="DebateClient.exportDebateFlow()">Export JSON</button>
        </div>
    `;
}

async function loadDebateLog() {
    if (!currentDebate) return;
    
    try {
        const logData = await getDebateLog(currentDebate.id);
        const logContainer = document.getElementById('debate-log-content');
        
        if (!logData.log || logData.log.length === 0) {
            logContainer.innerHTML = '<p>No events yet</p>';
            return;
        }
        
        logContainer.innerHTML = logData.log.map(entry => `
            <div class="log-item ${entry.event_type}">
                <div class="log-header">
                    <span class="log-timestamp">${formatDate(entry.timestamp)}</span>
                    <span class="log-event">${entry.event_type}</span>
                    <span class="log-actor">${escapeHtml(entry.actor || 'system')}</span>
                </div>
                <div class="log-data">
                    ${Object.entries(entry.data || {}).map(([k, v]) => 
                        `<span class="log-field">${k}: ${typeof v === 'object' ? JSON.stringify(v) : escapeHtml(String(v))}</span>`
                    ).join('')}
                </div>
            </div>
        `).join('');
        
    } catch (error) {
        showError(`Failed to load log: ${error.message}`);
    }
}

async function exportDebateFlow() {
    if (!currentDebate) {
        showError('No debate loaded');
        return;
    }
    
    try {
        await exportDebate(currentDebate.id);
        showSuccess('Debate exported!');
    } catch (error) {
        showError(`Export failed: ${error.message}`);
    }
}

function renderActionPanel() {
    if (!currentDebate || !currentParticipant) return '';
    
    const d = currentDebate;
    const p = currentParticipant;
    
    // Host controls
    if (d.created_by === p.id && d.status === 'pending') {
        return `
            <div class="action-panel">
                <h3>Host Controls</h3>
                <button class="btn btn-primary" onclick="startDebateFlow()">Start Debate</button>
                <button class="btn btn-secondary" onclick="showInviteTokens()">Manage Invite Tokens</button>
            </div>
        `;
    }
    
    // Host finalize control
    if (d.created_by === p.id && d.status === 'judging') {
        return `
            <div class="action-panel">
                <h3>Host Controls</h3>
                <button class="btn btn-primary" onclick="finalizeDebateFlow()">Finalize Debate</button>
            </div>
        `;
    }
    
    // Waiting for debate to start (PRO/CON participants)
    if ((p.side === 'pro' || p.side === 'con') && d.status === 'pending') {
        return `
            <div class="action-panel">
                <h3>⏳ Waiting for Host to Start</h3>
                <p style="color: #6b7280; font-size: 0.9375rem;">The debate hasn't started yet. Share the invite tokens with other participants, then the host will click <strong>Start Debate</strong> when everyone is ready.</p>
                <p style="margin-top: 0.75rem; color: #6b7280; font-size: 0.875rem;">Your side: <strong style="text-transform: uppercase;">${p.side}</strong></p>
            </div>
        `;
    }

    // Waiting for debate to start (spectators)
    if (p.side === 'spectator' || !p.side) {
        return `
            <div class="action-panel">
                <h3>👀 Spectator Mode</h3>
                <p style="color: #6b7280; font-size: 0.9375rem;">You are watching this debate as a spectator. Arguments will appear below once the debate begins.</p>
            </div>
        `;
    }
    
    // Debater turn submission
    if ((p.side === 'pro' || p.side === 'con') && 
        ['opening', 'rebuttal_1', 'rebuttal_2', 'cross_exam', 'closing'].includes(d.status)) {
        return `
            <div class="action-panel">
                <h3>Your Turn</h3>
                <textarea id="turn-content" placeholder="Enter your argument..." maxlength="${d.max_turn_length}"></textarea>
                <small id="char-count">0 / ${d.max_turn_length} characters</small>
                <button class="btn btn-primary" onclick="submitTurnFlow()">Submit Turn</button>
            </div>
        `;
    }
    
    // Judge scoring
    if (p.side === 'judge' && d.status === 'judging') {
        return `
            <div class="action-panel">
                <h3>Submit Scores</h3>
                ${renderJudgeScoringForm()}
            </div>
        `;
    }
    
    return '';
}

function renderJudgeScoringForm() {
    if (!currentDebate) return '';
    
    const debaters = currentDebate.participants.filter(p => p.side === 'pro' || p.side === 'con');
    
    return debaters.map(d => `
        <div class="score-form" data-participant-id="${d.id}">
            <h4>${escapeHtml(d.name)} (${d.side})</h4>
            <div class="score-inputs">
                <label>Argument Quality (0-10): <input type="number" class="score-arg" min="0" max="10" step="0.5" value="7"></label>
                <label>Evidence Quality (0-10): <input type="number" class="score-evi" min="0" max="10" step="0.5" value="7"></label>
                <label>Rebuttal Strength (0-10): <input type="number" class="score-reb" min="0" max="10" step="0.5" value="7"></label>
                <label>Clarity (0-10): <input type="number" class="score-cla" min="0" max="10" step="0.5" value="7"></label>
                <label>Compliance (0-10): <input type="number" class="score-com" min="0" max="10" step="0.5" value="7"></label>
            </div>
            <textarea class="score-rationale" placeholder="Rationale for scoring..."></textarea>
        </div>
    `).join('') + `
        <button class="btn btn-primary" onclick="submitScoresFlow()">Submit All Scores</button>
    `;
}

// ============== Flow Functions ==============

async function startDebateFlow() {
    if (!currentDebate || !currentParticipant) {
        showError('No debate or participant loaded');
        return;
    }
    
    // Verify this participant is the host
    if (currentDebate.created_by !== currentParticipant.id) {
        showError('Only the host can start the debate');
        return;
    }
    
    try {
        const result = await startDebate(currentDebate.id, currentParticipant.id);
        showSuccess('Debate started!');
        currentDebate = result;
        renderDebateRoom();
    } catch (error) {
        showError(`Failed to start: ${error.message}`);
    }
}

async function finalizeDebateFlow() {
    if (!currentDebate || !currentParticipant) return;
    
    try {
        const result = await finalizeDebate(currentDebate.id, currentParticipant.id);
        showSuccess(`Debate finalized! Winner: ${result.winner_side}`);
        loadDebateRoom(currentDebate.id);
        showResults(result);
    } catch (error) {
        showError(`Failed to finalize: ${error.message}`);
    }
}

async function submitTurnFlow() {
    if (!currentDebate || !currentParticipant) return;
    
    const content = document.getElementById('turn-content').value.trim();
    if (!content) {
        showError('Please enter content for your turn');
        return;
    }
    
    try {
        await submitTurn(currentDebate.id, currentParticipant.id, content);
        showSuccess('Turn submitted!');
        document.getElementById('turn-content').value = '';
        loadDebateRoom(currentDebate.id);
    } catch (error) {
        showError(`Failed to submit: ${error.message}`);
    }
}

async function submitScoresFlow() {
    if (!currentDebate || !currentParticipant) return;
    
    const scoreForms = document.querySelectorAll('.score-form');
    
    for (const form of scoreForms) {
        const participantId = form.dataset.participantId;
        const scoreData = {
            participant_id: participantId,
            argument_quality: parseFloat(form.querySelector('.score-arg').value),
            evidence_quality: parseFloat(form.querySelector('.score-evi').value),
            rebuttal_strength: parseFloat(form.querySelector('.score-reb').value),
            clarity: parseFloat(form.querySelector('.score-cla').value),
            compliance: parseFloat(form.querySelector('.score-com').value),
            rationale: form.querySelector('.score-rationale').value
        };
        
        try {
            await submitScore(currentDebate.id, currentParticipant.id, scoreData);
        } catch (error) {
            showError(`Failed to submit score for ${participantId}: ${error.message}`);
            return;
        }
    }
    
    showSuccess('All scores submitted!');
    loadDebateRoom(currentDebate.id);
}

function showResults(debate) {
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.innerHTML = `
        <div class="modal-content">
            <h2>Debate Results</h2>
            <div class="winner-announcement">
                <h3>Winner: ${debate.winner_side ? debate.winner_side.toUpperCase() : 'TIE'}</h3>
                <p>Confidence: ${(debate.confidence_score * 100).toFixed(1)}%</p>
            </div>
            <button class="btn btn-secondary" onclick="this.closest('.modal').remove()">Close</button>
        </div>
    `;
    document.body.appendChild(modal);
}

// ============== Join Flow ==============

async function joinDebateFlow() {
    const token = document.getElementById('join-token').value.trim();
    const name = document.getElementById('join-name').value.trim();
    
    if (!token || !name) {
        showError('Please enter both token and name');
        return;
    }
    
    try {
        const result = await joinDebate(token, name);
        currentParticipant = {
            id: result.participant_id,
            name: name
        };
        showSuccess('Joined successfully!');
        loadDebateRoom(result.debate_id);
    } catch (error) {
        showError(`Failed to join: ${error.message}`);
    }
}

// ============== Create Debate Flow ==============

async function createDebateFlow() {
    const title = document.getElementById('create-title').value.trim();
    const proposition = document.getElementById('create-proposition').value.trim();
    const createdBy = document.getElementById('create-host').value.trim() || 'anonymous';
    
    if (!title || !proposition) {
        showError('Please enter both title and proposition');
        return;
    }
    
    try {
        const debate = await createDebate({
            title,
            proposition,
            created_by: createdBy,
            max_turn_length: parseInt(document.getElementById('create-max-length').value) || 1000,
            is_public: false
        });
        
        currentParticipant = { id: createdBy, name: 'Host' };
        showSuccess('Debate created!');
        
        // Create invite tokens for all sides
        await createInviteToken(debate.id, { side: 'pro', max_uses: 2 }, createdBy);
        await createInviteToken(debate.id, { side: 'con', max_uses: 2 }, createdBy);
        await createInviteToken(debate.id, { side: 'judge', max_uses: 1 }, createdBy);
        
        loadDebateRoom(debate.id);
        showInviteTokens();
        
    } catch (error) {
        showError(`Failed to create: ${error.message}`);
    }
}

async function showInviteTokens() {
    if (!currentDebate) return;
    
    try {
        const tokens = await listInviteTokens(currentDebate.id);
        
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h2>Invite Tokens</h2>
                <p>Share these tokens with participants:</p>
                <div class="tokens-list">
                    ${tokens.map(t => `
                        <div class="token-item">
                            <strong>${t.side.toUpperCase()}</strong>
                            <code>${t.token_preview}...</code>
                            <small>Uses: ${t.used_count}/${t.max_uses}</small>
                        </div>
                    `).join('')}
                </div>
                <button class="btn btn-secondary" onclick="this.closest('.modal').remove()">Close</button>
            </div>
        `;
        document.body.appendChild(modal);
        
    } catch (error) {
        showError(`Failed to load tokens: ${error.message}`);
    }
}

// Export for use in other scripts
window.DebateClient = {
    createDebate,
    getDebate,
    listDebates,
    startDebate,
    finalizeDebate,
    joinDebate,
    submitTurn,
    listTurns,
    submitScore,
    listScores,
    createInviteToken,
    listInviteTokens,
    getResults,
    getDebateLog,
    exportDebate,
    loadDebateRoom,
    createDebateFlow,
    joinDebateFlow,
    startDebateFlow,
    finalizeDebateFlow,
    submitTurnFlow,
    submitScoresFlow,
    loadDebateLog,
    exportDebateFlow
};
