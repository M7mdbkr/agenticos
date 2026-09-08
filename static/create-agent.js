// ─────────────────────────────────────────────────────────────────
// Create Agent Page — AI-powered agent creation
// ─────────────────────────────────────────────────────────────────

async function createAgentPage() {
  const vaultNotes = await api('/vault/notes').catch(() => []);
  const existing = (state.agents || []).map(a => a.name.toLowerCase()).join(', ');

  return shell(html`
    <div class="create-agent-page">
      <div class="page-head">
        <p class="eyebrow">AGENT STUDIO</p>
        <h1>Create a new agent</h1>
        <p>Describe what you need in plain words. The AI will build the agent and set up its memory automatically.</p>
      </div>

      <div class="ca-layout">
        <!-- Left: description form -->
        <section class="ca-form-panel">
          <div class="panel">
            <p class="eyebrow">STEP 1 — WHAT DOES THIS AGENT DO?</p>
            <textarea id="ca-description"
              placeholder="e.g. A research assistant that finds AI news every morning and summarizes it for me..."></textarea>
            <div class="ca-hints">
              <span>Be specific about:</span>
              <button type="button" onclick="insertHint('What it does')">What it does</button>
              <button type="button" onclick="insertHint('Who it helps')">Who it helps</button>
              <button type="button" onclick="insertHint('When it acts')">When it acts</button>
              <button type="button" onclick="insertHint('What tools it uses')">Tools it uses</button>
            </div>
          </div>

          <div class="panel">
            <p class="eyebrow">STEP 2 — YOUR CONTEXT (OPTIONAL)</p>
            <textarea id="ca-context" placeholder="Any specific context, tone, rules, or preferences for this agent..."></textarea>
            <p class="muted">Examples: "speaks in Arabic", "very formal", "always checks with me before sending emails"</p>
          </div>

          <div class="panel">
            <p class="eyebrow">STEP 3 — CHOOSE A MODEL</p>
            <div class="ca-model-grid">
              <label class="ca-model-card selected">
                <input type="radio" name="ca-model" value="ollama" checked>
                <div class="ca-model-inner">
                  <strong>🆓 Ollama (Free)</strong>
                  <span>qwen2.5:7b · runs locally · no API costs</span>
                </div>
              </label>
              <label class="ca-model-card">
                <input type="radio" name="ca-model" value="openai-codex">
                <div class="ca-model-inner">
                  <strong>🤖 Claude Code</strong>
                  <span>Best for complex coding agents</span>
                </div>
              </label>
              <label class="ca-model-card">
                <input type="radio" name="ca-model" value="claude-code">
                <div class="ca-model-inner">
                  <strong>⚡ Codex CLI</strong>
                  <span>Fast, lightweight coding</span>
                </div>
              </label>
            </div>
          </div>

          <div class="ca-preview" id="ca-preview" style="display:none">
            <div class="panel">
              <p class="eyebrow">AGENT PREVIEW</p>
              <div id="ca-preview-content"></div>
            </div>
          </div>

          <div class="ca-actions">
            <button class="button" onclick="previewAgent()">👁 Preview agent</button>
            <button class="button primary" onclick="buildAgent()">🚀 Build &amp; activate agent</button>
          </div>
        </section>

        <!-- Right: vault memory preview -->
        <aside class="ca-memory-panel">
          <div class="panel">
            <p class="eyebrow">VAULT MEMORY — WHAT GETS CREATED</p>
            <div id="ca-vault-preview">
              <div class="ca-vault-item">
                <span class="ca-vault-icon">📄</span>
                <div>
                  <strong id="ca-name-preview">New Agent.md</strong>
                  <p class="muted">Role definition, personality, goals, boundaries</p>
                </div>
              </div>
              <div class="ca-vault-item">
                <span class="ca-vault-icon">🧠</span>
                <div>
                  <strong>Memory Log</strong>
                  <p class="muted">Every action the agent takes is logged here</p>
                </div>
              </div>
              <div class="ca-vault-item">
                <span class="ca-vault-icon">📋</span>
                <div>
                  <strong>Tasks</strong>
                  <p class="muted">Agent-specific task backlog</p>
                </div>
              </div>
            </div>
          </div>

          <div class="panel">
            <p class="eyebrow">EXISTING AGENTS</p>
            <div id="ca-existing-list">
              ${(state.agents||[]).map(a => `<div class="ca-existing-item">
                <span class="pill ${a.enabled?'green':'rose'}">${a.enabled?'active':'paused'}</span>
                <strong>${esc(a.name)}</strong>
                <span class="muted">${esc(a.model_provider)}/${esc(a.model_id)}</span>
              </div>`).join('') || '<p class="muted">No agents yet</p>'}
            </div>
          </div>
        </aside>
      </div>
    </div>
  `);
}

// ── Hint buttons ──────────────────────────────────────────────────

function insertHint(type) {
  const el = $('#ca-description');
  const hints = {
    'What it does': 'This agent monitors ',
    'Who it helps': 'It helps Mohammad with ',
    'When it acts': 'It runs every ',
    'What tools it uses': 'It has access to '
  };
  el.value += (el.value ? ' ' : '') + hints[type];
  el.focus();
}

// ── Preview ───────────────────────────────────────────────────────

async function previewAgent() {
  const desc = $('#ca-description')?.value?.trim();
  if (!desc) { toast('Describe the agent first'); return; }
  const preview = $('#ca-preview');
  const content = $('#ca-preview-content');
  if (!preview || !content) return;
  preview.style.display = 'block';
  content.innerHTML = '<div class="loading-dots">Thinking…</div>';
  try {
    const res = await api('/agents/create-preview', {
      method: 'POST',
      body: JSON.stringify({ description: desc })
    });
    content.innerHTML = `<div class="ca-agent-card">
      <h3>${esc(res.name||'New Agent')}</h3>
      <p class="muted">${esc(res.purpose||desc)}</p>
      <div class="ca-agent-tags">
        ${(res.tags||[]).map(t=>`<span class="pill">${esc(t)}</span>`).join('')}
      </div>
    </div>`;
    const nameEl = $('#ca-name-preview');
    if (nameEl) nameEl.textContent = (res.name||'New Agent') + '.md';
  } catch(e) {
    content.innerHTML = `<p class="rose">Preview unavailable: ${esc(e.message)}</p>`;
  }
}

// ── Build agent ───────────────────────────────────────────────────

async function buildAgent() {
  const desc = $('#ca-description')?.value?.trim();
  if (!desc) { toast('Describe the agent first'); return; }
  const context = $('#ca-context')?.value?.trim() || '';
  const model = document.querySelector('input[name="ca-model"]:checked')?.value || 'ollama';

  const btn = document.querySelector('.ca-actions .button.primary');
  if (btn) { btn.disabled = true; btn.textContent = 'Building…'; }

  try {
    const res = await api('/agents', {
      method: 'POST',
      body: JSON.stringify({
        description: desc,
        context: context,
        model_provider: model,
        model_id: model === 'ollama' ? 'qwen2.5:7b' : undefined
      })
    });
    toast(`Agent "${res.name}" created and ready`);
    await go('agents');
  } catch(e) {
    toast('Failed: ' + e.message);
    if (btn) { btn.disabled = false; btn.textContent = '🚀 Build & activate agent'; }
  }
}

// ── Load create agent page ─────────────────────────────────────────
async function loadCreateAgent() {
  const form = $('#ca-form-section');
  if (!form) return;
  // Radio card selection
  document.querySelectorAll('.ca-model-card input[type=radio]').forEach(r => {
    r.addEventListener('change', () => {
      document.querySelectorAll('.ca-model-card').forEach(c => c.classList.remove('selected'));
      r.closest('.ca-model-card').classList.add('selected');
    });
  });
  // Live name preview
  const descInput = $('#ca-description');
  if (descInput) {
    descInput.addEventListener('input', () => {
      const name = generateName(descInput.value);
      const nameEl = $('#ca-name-preview');
      if (nameEl) nameEl.textContent = name + '.md';
    });
  }
}

function generateName(desc) {
  if (!desc) return 'New Agent';
  const words = desc.trim().split(/\s+/).filter(w => w.length > 3);
  return words.slice(0, 3).map(w => w.replace(/[^a-zA-Z]/g,'')).map(w => w.charAt(0).toUpperCase() + w.slice(1)).join('') || 'Agent';
}
