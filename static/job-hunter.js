/* Job Hunter page. Classic script loaded before app.js; uses its helpers (api, esc, toast, shell, head, modal) at call time. */
const JobHunterPage = (() => {
  const ui = {tab: 'matches', status: null, profile: null, jobs: [], chat: [], results: null, filter: '', busy: false};
  const STATUS_COLORS = {new: 'blue', notified: 'blue', interested: 'purple', drafted: 'orange', applied: 'green',
    interview: 'green', assessment: 'orange', offer: 'green', rejected: 'red', skipped: '', closed: ''};
  const TRACKED = ['drafted', 'applied', 'interview', 'assessment', 'offer', 'rejected'];
  const list = v => (v || []).join(', ');
  const ago = iso => {
    if (!iso) return 'never';
    const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (mins < -1) return `in ${fmtMins(-mins)}`;
    if (mins < 1) return 'just now';
    return `${fmtMins(mins)} ago`;
  };
  const fmtMins = m => m < 60 ? `${m} min` : m < 2880 ? `${Math.round(m / 60)} h` : `${Math.round(m / 1440)} days`;
  const btn = (action, label, id = '', cls = 'ghost small') =>
    `<button type="button" class="button ${cls}" data-jh="${esc(action)}" data-id="${esc(id)}">${label}</button>`;

  async function load() {
    const [status, profile, jobs] = await Promise.all([
      api('/jobhunter/status'), api('/jobhunter/profile'),
      api('/jobhunter/jobs?limit=300' + (ui.filter ? '&q=' + encodeURIComponent(ui.filter) : ''))]);
    Object.assign(ui, {status, profile, jobs});
  }

  // ── sections ───────────────────────────────────────────────────────────
  function checklist() {
    const s = ui.status;
    const steps = [
      [s.ready, 'Tell it what you want', 'Add target roles, skills and locations in Settings.'],
      [s.email.configured, 'Connect your email', 'So it can send you results, read replies and take commands.'],
      [s.running || s.service, 'Start the agent', 'It then searches every few hours and checks your inbox every few minutes.'],
    ];
    if (steps.every(x => x[0])) return '';
    return `<section class="panel jh-setup"><div class="panel-head"><div><h2>Get started</h2><p>Three steps and it runs on its own.</p></div></div>
      <ol class="jh-steps">${steps.map(([done, title, text]) => `<li class="${done ? 'done' : ''}"><span>${done ? '✓' : '•'}</span><div><strong>${title}</strong><p>${text}</p></div></li>`).join('')}</ol></section>`;
  }

  function metrics() {
    const c = ui.status.counts;
    const open = c.new + c.notified + c.interested;
    const tiles = [['blue', open, 'Open matches'], ['green', c.applied, 'Applied'],
      ['orange', c.interview + c.assessment + c.offer, 'Interviews & offers'], ['red', ui.status.drafts.length, 'Waiting for your OK']];
    return `<div class="grid four jh-metrics">${tiles.map(([color, n, label]) => `<div class="metric ${color}"><strong>${n}</strong><span>${label}</span></div>`).join('')}</div>`;
  }

  function statusLine() {
    const s = ui.status;
    const state = s.paused ? '<span class="pill orange">Paused</span>' : s.running ? '<span class="pill green">Running</span>'
      : s.service ? '<span class="pill green">Running as background service</span>' : '<span class="pill">Stopped</span>';
    const email = s.email.configured ? `<span class="pill green">✉ ${esc(s.email.address)}</span>` : '<span class="pill red">Email not connected</span>';
    const run = s.last_run;
    const errors = run && Object.keys(run.errors || {}).length ? `<div class="jh-muted">⚠ ${Object.entries(run.errors).map(([k, v]) => `${esc(k)}: ${esc(v)}`).join(' · ')}</div>` : '';
    return `<div class="jh-statusline">${state} ${email}
      <span class="jh-muted">Last search ${ago(s.last_search_at)}${s.next_search_at ? ' · next ' + ago(s.next_search_at) : ''} · inbox checked ${ago(s.last_inbox_at)}${run ? ` · ${run.fetched} postings checked, ${run.matches} new matches` : ''}</span>
      ${s.last_error ? `<div class="jh-muted">⚠ ${esc(s.last_error)}</div>` : ''}${errors}</div>`;
  }

  function jobCard(j, showStatus = true) {
    const score = j.score >= 75 ? 'green' : j.score >= 50 ? 'blue' : '';
    const sources = (j.sources && j.sources.length ? j.sources : [j.source]).join(', ');
    const draftFor = ui.status.drafts.find(d => d.job_id === j.id);
    const actions = [];
    if (j.url) actions.push(`<a class="button ghost small" href="${esc(j.url)}" target="_blank" rel="noopener noreferrer">Open ↗</a>`);
    if (['new', 'notified', 'interested', 'drafted'].includes(j.status)) actions.push(btn('apply', j.apply_email ? '✉ Apply by email' : '📝 Prepare application', j.id, 'primary small'));
    if (draftFor) actions.push(btn('draft', 'Review & send', draftFor.id, 'primary small'));
    if (['new', 'notified'].includes(j.status)) actions.push(btn('save', 'Save', j.id));
    if (['new', 'notified', 'interested', 'drafted'].includes(j.status)) actions.push(btn('applied', 'I applied', j.id));
    if (['applied', 'interview', 'assessment'].includes(j.status)) actions.push(btn('followup', 'Follow up', j.id));
    if (j.last_inbound_from) actions.push(btn('reply', 'Reply to them', j.id));
    actions.push(btn('details', 'Details', j.id));
    if (!['skipped', 'closed'].includes(j.status)) actions.push(btn('skip', 'Skip', j.id));
    return `<article class="jh-job" data-job="${esc(j.id)}">
      <div class="jh-job-top"><span class="pill ${score}">${j.score}%</span>${showStatus ? `<span class="pill ${STATUS_COLORS[j.status] || ''}">${esc(j.status)}</span>` : ''}<span class="jh-id">${esc(j.id)}</span></div>
      <h3>${esc(j.title)}</h3>
      <p class="jh-company">${esc(j.company || 'Unknown company')}${j.location ? ' · ' + esc(j.location) : ''}${j.salary ? ' · ' + esc(j.salary) : ''}</p>
      <p class="jh-muted">${esc(sources)}${j.posted_at ? ' · posted ' + ago(j.posted_at) : ''}${j.applied_at ? ' · applied ' + ago(j.applied_at) : ''}</p>
      ${j.reasons && j.reasons.length ? `<p class="jh-reasons">${esc(j.reasons.slice(0, 4).join(' · '))}</p>` : ''}
      <div class="jh-actions">${actions.join('')}</div></article>`;
  }

  function matchesTab() {
    const open = ui.jobs.filter(j => ['new', 'notified', 'interested'].includes(j.status) && j.score >= ui.profile.min_score);
    const results = ui.results ? `<section class="section-gap"><h2 class="section-title">Search results (${ui.results.results.length})</h2>
      ${Object.keys(ui.results.errors || {}).length ? `<div class="notice">Some sites failed: ${esc(Object.entries(ui.results.errors).map(([k, v]) => k + ': ' + v).join(' · '))}</div>` : ''}
      <div class="jh-jobs">${ui.results.results.map(j => jobCard(j)).join('') || '<div class="empty">No matches for that search.</div>'}</div></section>` : '';
    return `<section class="panel"><form id="jh-search" class="jh-searchform">
        <input name="query" placeholder="Search every site now — e.g. network engineer" required>
        <input name="location" placeholder="Where? e.g. Riyadh, Remote">
        <button class="button primary" ${ui.busy ? 'disabled' : ''}>${ui.busy ? 'Searching…' : 'Search'}</button></form>
        <form id="jh-track" class="jh-searchform"><input name="url" placeholder="Found a job yourself? Paste its link to track it" type="url"><button class="button ghost">Track</button></form>
      </section>${results}
      <section class="section-gap"><div class="jh-listhead"><h2 class="section-title">Best open matches (${open.length})</h2>
        <input id="jh-filter" placeholder="Filter by title, company, place" value="${esc(ui.filter)}"></div>
        <div class="jh-jobs">${open.map(j => jobCard(j, false)).join('') || `<div class="empty"><strong>No open matches yet</strong><p>${ui.status.ready ? 'Press “Run search now”, or wait for the next scheduled search.' : 'Add your target roles in Settings first.'}</p></div>`}</div></section>`;
  }

  function draftCard(d) {
    const job = ui.jobs.find(j => j.id === d.job_id) || {title: d.job_id, company: ''};
    return `<article class="jh-draft"><div class="jh-job-top"><span class="pill orange">${esc(d.kind)}</span><span class="jh-id">${esc(d.job_id)}</span></div>
      <h3>${esc(job.title)}${job.company ? ' — ' + esc(job.company) : ''}</h3>
      <p class="jh-muted">To ${esc(d.to_addr)} · ${d.attach_cv ? 'CV attached' : 'no attachment'}</p>
      <div class="jh-actions">${btn('draft', 'Review & send', d.id, 'primary small')}${btn('cancel', 'Cancel', d.job_id)}</div></article>`;
  }

  function applicationsTab() {
    const drafts = ui.status.drafts;
    const tracked = ui.jobs.filter(j => TRACKED.includes(j.status)).sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''));
    const due = ui.status.followups_due;
    return `${drafts.length ? `<section class="panel"><div class="panel-head"><div><h2>Waiting for your OK (${drafts.length})</h2><p>Nothing is sent to an employer until you press Send (or reply “send &lt;id&gt;” by email).</p></div></div><div class="jh-jobs">${drafts.map(draftCard).join('')}</div></section>` : ''}
      ${due.length ? `<section class="panel section-gap"><div class="panel-head"><div><h2>Follow-ups due (${due.length})</h2><p>No reply after ${ui.profile.follow_up_days} days.</p></div></div><div class="jh-jobs">${due.map(j => jobCard(j)).join('')}</div></section>` : ''}
      <section class="section-gap"><h2 class="section-title">Your applications (${tracked.length})</h2>
      <div class="jh-jobs">${tracked.map(j => jobCard(j)).join('') || '<div class="empty"><strong>No applications yet</strong><p>Prepare one from Matches, or reply “apply 1” to a digest email.</p></div>'}</div></section>`;
  }

  function askTab() {
    return `<section class="panel"><div class="panel-head"><div><h2>Ask or command the agent</h2><p>Same commands as email and Telegram: <code>jobs</code>, <code>apply 7K2QX</code>, <code>search data analyst in Riyadh</code>, <code>status</code>, <code>help</code> — or ask a question.</p></div></div>
      <div class="jh-chat" id="jh-chat">${ui.chat.map(m => `<div class="jh-msg ${m.role}"><pre>${esc(m.text)}</pre></div>`).join('') || '<p class="jh-muted">Try “status” or “jobs”.</p>'}</div>
      <form id="jh-ask" class="jh-searchform"><input name="text" placeholder="Type a command or question" autocomplete="off" required><button class="button primary">Send</button></form></section>`;
  }

  async function activityTab() {
    const data = await api('/jobhunter/activity');
    const mail = data.mail.filter(m => m.kind !== 'ignored' && m.kind !== 'own');
    return `<div class="grid two"><section class="panel"><div class="panel-head"><h2>Email</h2></div>
      ${mail.map(m => `<div class="jh-logrow"><span class="pill ${m.direction === 'in' ? 'blue' : 'green'}">${m.direction === 'in' ? '↓' : '↑'} ${esc(m.kind)}${m.classification ? ' · ' + esc(m.classification) : ''}</span><div><strong>${esc(m.subject || '(no subject)')}</strong><p class="jh-muted">${esc(m.direction === 'in' ? m.from_addr : m.to_addr)} · ${ago(m.created_at)}</p></div></div>`).join('') || '<p class="jh-muted">No email yet.</p>'}</section>
      <section class="panel"><div class="panel-head"><h2>Agent log</h2></div>
      ${data.events.map(e => `<div class="jh-logrow"><span class="pill ${e.kind === 'error' || e.kind === 'security' ? 'red' : ''}">${esc(e.kind)}</span><div><strong>${esc(e.message)}</strong><p class="jh-muted">${ago(e.created_at)}</p></div></div>`).join('') || '<p class="jh-muted">Nothing yet.</p>'}</section></div>`;
  }

  function field(name, label, value, type = 'text', extra = '') {
    return `<div><label for="jh-${name}">${label}</label><input id="jh-${name}" name="${name}" type="${type}" value="${esc(value ?? '')}" ${extra}></div>`;
  }
  function check(name, label, value) {
    return `<label class="jh-check"><input type="checkbox" name="${name}" ${value ? 'checked' : ''}> ${label}</label>`;
  }

  function settingsTab() {
    const p = ui.profile, s = ui.status;
    const sources = s.sources.map(src => `<label class="jh-source ${src.configured ? '' : 'off'}"><input type="checkbox" name="source:${esc(src.name)}" ${src.wanted ? 'checked' : ''}>
      <span><strong>${esc(src.label)}</strong><small>${esc(src.covers || '')}${src.configured ? '' : ` — needs ${esc(src.needs.join(' + '))} in .env`}${src.last_error ? ` — ⚠ ${esc(src.last_error)}` : src.last_count != null ? ` — ${src.last_count} last run` : ''}</small></span></label>`).join('');
    return `<form id="jh-profile">
      <section class="panel"><div class="panel-head"><div><h2>What you're looking for</h2><p>Comma-separated lists. Scores explain every point, so you can tune these.</p></div></div>
        <div class="form-row">${field('roles', 'Target roles', list(p.roles), 'text', 'placeholder="software engineer, IT support, network engineer"')}${field('skills', 'Your skills', list(p.skills), 'text', 'placeholder="python, sql, networking, linux"')}</div>
        <div class="form-row">${field('locations', 'Locations', list(p.locations), 'text', 'placeholder="Saudi Arabia, Riyadh, Remote"')}${field('exclude', 'Never show titles containing', list(p.exclude), 'text', 'placeholder="sales, senior, 10+ years"')}</div>
        <div class="form-row"><div><label for="jh-level">Level</label><select id="jh-level" name="level">${['entry', 'mid', 'senior', 'any'].map(l => `<option ${p.level === l ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
          ${field('min_score', 'Email me jobs scoring at least (%)', p.min_score, 'number', 'min="0" max="100"')}</div>
        ${check('remote_ok', 'Remote jobs are fine', p.remote_ok)}${check('strict_location', 'Hide everything outside my locations', p.strict_location)}
      </section>
      <section class="panel section-gap"><div class="panel-head"><div><h2>About you (used in cover letters — keep it true)</h2></div></div>
        <div class="form-row">${field('name', 'Full name', p.name)}${field('phone', 'Phone', p.phone)}</div>
        ${field('headline', 'Headline', p.headline, 'text', 'placeholder="Computer Engineering graduate, Taif University"')}
        <label for="jh-summary">Short summary</label><textarea id="jh-summary" name="summary" placeholder="2–3 sentences about your real experience">${esc(p.summary)}</textarea>
        <label>CV to attach to email applications</label><div class="jh-cv"><span class="pill ${s.cv ? 'green' : ''}">${s.cv ? esc(s.cv) : 'No CV yet'}</span><input type="file" id="jh-cv-file" accept=".pdf,.doc,.docx,.odt,.rtf,.txt"></div>
      </section>
      <section class="panel section-gap"><div class="panel-head"><div><h2>Where to search</h2><p>JSearch and SerpAPI read Google for Jobs (LinkedIn, Indeed, Bayt, Glassdoor, company sites…) — add a key to .env to switch them on.</p></div></div>
        <div class="jh-sources">${sources}</div>
        <div class="form-row">${field('greenhouse_boards', 'Greenhouse company boards', list(p.greenhouse_boards), 'text', 'placeholder="e.g. careem, stripe"')}${field('lever_boards', 'Lever company boards', list(p.lever_boards), 'text', 'placeholder="e.g. tamara"')}</div>
        ${field('rss_feeds', 'Extra RSS job feeds', list(p.rss_feeds), 'text', 'placeholder="https://…/jobs.rss"')}
      </section>
      <section class="panel section-gap"><div class="panel-head"><div><h2>Rhythm & notifications</h2></div></div>
        <div class="form-row">${field('search_every_minutes', 'Search every (minutes)', p.search_every_minutes, 'number', 'min="30"')}${field('inbox_every_minutes', 'Check inbox every (minutes)', p.inbox_every_minutes, 'number', 'min="2"')}</div>
        <div class="form-row">${field('daily_summary_hour', 'Daily report at hour (0–23, −1 = off)', p.daily_summary_hour, 'number', 'min="-1" max="23"')}${field('follow_up_days', 'Suggest follow-up after (days)', p.follow_up_days, 'number', 'min="1"')}</div>
        <div class="form-row">${field('digest_max', 'Jobs per email', p.digest_max, 'number', 'min="1" max="50"')}${field('telegram_chat_id', 'Telegram chat ID (for /jobs commands)', p.telegram_chat_id, 'text', `placeholder="${s.telegram.token_set ? 'see the Telegram page' : 'connect Telegram first'}"`)}</div>
        ${check('notify_email', 'Email me', p.notify_email)}${check('notify_telegram', 'Telegram me', p.notify_telegram)}${check('notify_desktop', 'Laptop notifications', p.notify_desktop)}
        ${check('notify_when_empty', 'Tell me even when nothing new was found', p.notify_when_empty)}${check('open_browser_on_apply', 'Open the job page on my laptop when I prepare a website application', p.open_browser_on_apply)}
        <div class="form-row"><div><label for="jh-brain">Writing brain (cover letters & questions)</label><select id="jh-brain" name="brain">${[['none', 'Templates only'], ['ollama', 'Ollama (local, free)'], ['claude-code', 'Claude Code subscription'], ['codex-cli', 'Codex CLI subscription']].map(([v, l]) => `<option value="${v}" ${p.brain === v ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
          ${field('brain_model', 'Model (optional)', p.brain_model, 'text', 'placeholder="qwen2.5:7b / default"')}</div>
      </section>
      <div class="jh-save"><button class="button primary">Save settings</button></div>
    </form>
    <form id="jh-email" class="panel section-gap"><div class="panel-head"><div><h2>Email connection</h2><p>For Gmail: turn on 2-Step Verification, create an <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener noreferrer">App Password</a> and paste the 16 letters. Saved only in your local <code>.env</code>.</p></div>
      ${s.email.configured ? `<span class="pill green">Connected</span>` : '<span class="pill red">Not connected</span>'}</div>
      <div class="form-row">${field('address', 'Mailbox the agent uses', s.email.address, 'email', 'required placeholder="you@gmail.com"')}${field('password', 'App password', '', 'password', `placeholder="${s.email.password_set ? '•••• saved — leave empty to keep' : '16-letter app password'}" autocomplete="new-password"`)}</div>
      ${field('owner_emails', 'Send updates to / accept commands from', list(ui.status.owners), 'text', 'placeholder="your personal address (defaults to the mailbox)"')}
      <details><summary class="jh-muted">Other providers (IMAP/SMTP servers)</summary><div class="form-row">${field('imap_host', 'IMAP server', s.email.imap_host || '')}${field('smtp_host', 'SMTP server', s.email.smtp_host || '')}</div>${field('smtp_port', 'SMTP port (465 or 587)', '', 'number')}</details>
      <div class="jh-actions"><button class="button primary">Connect & test</button>${s.email.configured ? btn('testmail', 'Send me a test email') : ''}</div>
    </form>`;
  }

  // ── page ───────────────────────────────────────────────────────────────
  async function body() {
    const s = ui.status;
    const tabs = [['matches', 'Matches'], ['applications', 'Applications'], ['ask', 'Ask'], ['activity', 'Activity'], ['settings', 'Settings']];
    const content = ui.tab === 'matches' ? matchesTab() : ui.tab === 'applications' ? applicationsTab() : ui.tab === 'ask' ? askTab()
      : ui.tab === 'activity' ? await activityTab() : settingsTab();
    const agentBtn = s.running ? btn('stop', 'Stop agent', '', 'ghost') : s.service ? '' : btn('start', '▶ Start agent', '', 'primary');
    return head('JOB HUNTER', 'Finds jobs on every site and emails you.',
        'Searches LinkedIn, remote boards, company career pages and your job-alert emails, scores each posting against your profile, answers your emails and tracks employer replies. Nothing is sent to an employer until you approve it.',
        `<div class="page-actions">${agentBtn}${btn('run', ui.busy ? 'Searching…' : '⟳ Run search now', '', 'dark')}${s.email.configured ? btn('inbox', '✉ Check inbox', '', 'dark') : ''}${btn(s.paused ? 'resume' : 'pause', s.paused ? 'Resume' : 'Pause', '', 'ghost')}</div>`)
      + checklist() + metrics() + statusLine()
      + `<div class="agent-tabs jh-tabs">${tabs.map(([id, label]) => `<button type="button" class="tab-btn ${ui.tab === id ? 'active' : ''}" data-jh="tab" data-id="${id}">${label}${id === 'applications' && s.drafts.length ? ` <span class="pill orange">${s.drafts.length}</span>` : ''}</button>`).join('')}</div>`
      + `<div id="jh-tab">${content}</div>`;
  }

  async function render() {
    await load();
    return shell(`<div id="jh-root">${await body()}</div>`);
  }

  async function refresh(reload = true) {
    if (reload) await load();
    const root = document.getElementById('jh-root');
    if (!root) return;
    root.innerHTML = await body();
    bind();
  }

  function showMessage(title, message, draftId) {
    modal(title, 'JOB HUNTER', `<pre class="jh-pre">${esc(message)}</pre>${draftId ? `<div class="jh-actions">${btn('draft', 'Review & send', draftId, 'primary')}</div>` : ''}`);
    document.querySelectorAll('#modal [data-jh="draft"]').forEach(b => b.onclick = e => { e.preventDefault(); openDraft(b.dataset.id); });
  }

  function openDraft(id) {
    const d = ui.status.drafts.find(x => x.id === id);
    if (!d) return toast('That draft is gone — refresh the page');
    modal(`Review ${d.kind}`, 'WAITING FOR YOUR OK', `<div id="jh-draft-form">
      <label>To</label><input id="jhd-to" value="${esc(d.to_addr)}"><label>Subject</label><input id="jhd-subject" value="${esc(d.subject)}">
      <label>Message</label><textarea id="jhd-body" rows="14">${esc(d.body)}</textarea>
      <p class="jh-muted">${d.attach_cv ? `Your CV (${esc(ui.status.cv || 'file')}) will be attached.` : 'No attachment.'}</p>
      <div class="jh-actions"><button type="button" class="button primary" id="jhd-send">Send now</button><button type="button" class="button ghost" id="jhd-save">Save changes</button><button type="button" class="button ghost" id="jhd-cancel">Discard</button></div></div>`);
    const save = () => api(`/jobhunter/drafts/${d.id}`, {method: 'POST', body: JSON.stringify({to_addr: $('#jhd-to').value, subject: $('#jhd-subject').value, body: $('#jhd-body').value})});
    $('#jhd-save').onclick = async () => { try { await save(); toast('Saved'); await refresh(); } catch (e) { toast(e.message); } };
    $('#jhd-send').onclick = async () => {
      if (!confirm(`Send this ${d.kind} to ${$('#jhd-to').value}?`)) return;
      try { await save(); const r = await api(`/jobhunter/jobs/${d.job_id}/send`, {method: 'POST', body: '{}'}); $('#modal').close(); toast(r.message.split('\n')[0]); await refresh(); } catch (e) { toast(e.message); }
    };
    $('#jhd-cancel').onclick = async () => { try { await api(`/jobhunter/jobs/${d.job_id}/cancel`, {method: 'POST', body: '{}'}); $('#modal').close(); toast('Discarded'); await refresh(); } catch (e) { toast(e.message); } };
  }

  async function jobAction(action, id) {
    if (action === 'details') {
      const j = await api(`/jobhunter/jobs/${id}`);
      return modal(j.title, `${j.company || ''} · ${j.id}`.toUpperCase(), `<p class="jh-muted">${esc(j.location)} · ${esc((j.sources || []).join(', '))} · match ${j.score}%</p>
        ${j.url ? `<p><a href="${esc(j.url)}" target="_blank" rel="noopener noreferrer">${esc(j.url)}</a></p>` : ''}${j.apply_email ? `<p>✉ ${esc(j.apply_email)}</p>` : ''}
        <p class="jh-reasons">${esc((j.reasons || []).join(' · '))}</p><pre class="jh-pre">${esc(j.description || 'No description yet — open the link for the full posting.')}</pre>
        ${j.cover_letter ? `<h3>Cover letter</h3><pre class="jh-pre">${esc(j.cover_letter)}</pre>` : ''}`);
    }
    let payload = {};
    if (action === 'reply') {
      const text = prompt('What should the reply say? (I add the greeting and signature)');
      if (!text) return;
      payload = {text};
    }
    const r = await api(`/jobhunter/jobs/${id}/${action}`, {method: 'POST', body: JSON.stringify(payload)});
    await refresh();
    const draft = ui.status.drafts.find(d => d.job_id === id);
    if (['apply', 'followup', 'reply'].includes(action)) showMessage(action === 'apply' ? 'Application ready' : 'Draft ready', r.message, draft && draft.id);
    else toast(r.message.split('\n')[0]);
  }

  async function waitForRun(previous) {
    for (let i = 0; i < 60; i++) {
      await new Promise(res => setTimeout(res, 5000));
      if (state.current !== 'hunter') return;
      const s = await api('/jobhunter/status');
      const finished = s.last_run && s.last_run.finished_at;
      if (finished && finished !== previous) {
        ui.busy = false;
        toast(`Search done: ${s.last_run.fetched} postings, ${s.last_run.matches} new matches`);
        return refresh();
      }
    }
    ui.busy = false;
    refresh();
  }

  async function onClick(e) {
    const b = e.target.closest('[data-jh]');
    if (!b || !document.getElementById('jh-root')?.contains(b)) return;
    const {jh: action, id} = b.dataset;
    try {
      if (action === 'tab') { ui.tab = id; return refresh(false); }
      if (action === 'start' || action === 'stop') { await api(`/jobhunter/${action}`, {method: 'POST', body: '{}'}); toast(action === 'start' ? 'Agent started' : 'Agent stopped'); return refresh(); }
      if (action === 'pause' || action === 'resume') { await api('/jobhunter/profile', {method: 'POST', body: JSON.stringify({paused: action === 'pause'})}); return refresh(); }
      if (action === 'run') {
        if (ui.busy) return;
        const previous = ui.status.last_run && ui.status.last_run.finished_at;
        await api('/jobhunter/run', {method: 'POST', body: '{}'});
        ui.busy = true; toast('Searching every site… results will appear here and in your email');
        refresh(false); return waitForRun(previous);
      }
      if (action === 'inbox') { b.disabled = true; const r = await api('/jobhunter/inbox', {method: 'POST', body: '{}'}); toast(r.error || `Read ${r.checked || 0} new emails`); return refresh(); }
      if (action === 'testmail') { await api('/jobhunter/email/test', {method: 'POST', body: '{}'}); return toast('Test email sent — reply “status” to it'); }
      if (action === 'draft') return openDraft(id);
      if (action === 'cancel') { await api(`/jobhunter/jobs/${id}/cancel`, {method: 'POST', body: '{}'}); toast('Discarded'); return refresh(); }
      return await jobAction(action, id);
    } catch (err) { toast(err.message); }
  }

  function profilePayload(form) {
    const fd = new FormData(form), data = {sources: {}};
    for (const [key, value] of fd.entries()) {
      if (key.startsWith('source:')) continue;
      data[key] = value;
    }
    form.querySelectorAll('input[type=checkbox]').forEach(c => {
      if (c.name.startsWith('source:')) data.sources[c.name.slice(7)] = c.checked; else data[c.name] = c.checked;
    });
    return data;
  }

  function bind() {
    const root = document.getElementById('jh-root');
    if (!root) return;
    root.onclick = onClick;
    const filter = document.getElementById('jh-filter');
    if (filter) filter.onchange = async () => { ui.filter = filter.value.trim(); await refresh(); };
    const search = document.getElementById('jh-search');
    if (search) search.onsubmit = async e => {
      e.preventDefault();
      const fd = new FormData(search);
      ui.busy = true; await refresh(false);
      try { ui.results = await api('/jobhunter/search', {method: 'POST', body: JSON.stringify({query: fd.get('query'), location: fd.get('location')})}); }
      catch (err) { toast(err.message); }
      ui.busy = false; await refresh();
    };
    const track = document.getElementById('jh-track');
    if (track) track.onsubmit = async e => {
      e.preventDefault();
      try { const r = await api('/jobhunter/jobs', {method: 'POST', body: JSON.stringify({url: new FormData(track).get('url')})}); toast(r.message); await refresh(); }
      catch (err) { toast(err.message); }
    };
    const ask = document.getElementById('jh-ask');
    if (ask) ask.onsubmit = async e => {
      e.preventDefault();
      const input = ask.querySelector('input'), text = input.value.trim();
      if (!text) return;
      ui.chat.push({role: 'user', text}); input.value = '';
      await refresh(false);
      try { const r = await api('/jobhunter/ask', {method: 'POST', body: JSON.stringify({text})}); ui.chat.push({role: 'agent', text: r.reply}); }
      catch (err) { ui.chat.push({role: 'agent', text: '⚠ ' + err.message}); }
      await refresh();
      const chat = document.getElementById('jh-chat'); if (chat) chat.scrollTop = chat.scrollHeight;
      document.querySelector('#jh-ask input')?.focus();
    };
    const profile = document.getElementById('jh-profile');
    if (profile) profile.onsubmit = async e => {
      e.preventDefault();
      try { await api('/jobhunter/profile', {method: 'POST', body: JSON.stringify(profilePayload(profile))}); toast('Settings saved'); await refresh(); }
      catch (err) { toast(err.message); }
    };
    const cv = document.getElementById('jh-cv-file');
    if (cv) cv.onchange = async () => {
      const file = cv.files[0]; if (!file) return;
      try {
        const r = await fetch('/api/jobhunter/cv', {method: 'POST', headers: {'X-Filename': file.name, 'Content-Type': 'application/octet-stream'}, body: file});
        const data = await r.json(); if (!r.ok) throw Error(data.error || 'Upload failed');
        toast(`CV saved: ${data.cv}`); await refresh();
      } catch (err) { toast(err.message); }
    };
    const email = document.getElementById('jh-email');
    if (email) email.onsubmit = async e => {
      e.preventDefault();
      const data = Object.fromEntries(new FormData(email).entries());
      const submit = email.querySelector('button.primary'); submit.disabled = true; submit.textContent = 'Testing…';
      try { await api('/jobhunter/email', {method: 'POST', body: JSON.stringify(data)}); toast('Email connected'); await refresh(); }
      catch (err) { toast(err.message); submit.disabled = false; submit.textContent = 'Connect & test'; }
    };
  }

  return {render, bind};
})();
