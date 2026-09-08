/* Classic script: load before app.js; route tasks/schedules, then call bindPlanning(). */
const Planning = (() => {
  const statuses = [['todo', 'To do'], ['in_progress', 'In progress'], ['done', 'Done']];
  const priorities = [['low', 'Low'], ['normal', 'Normal'], ['high', 'High']];
  const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const filters = {tasks: {agent: '*', status: '*'}, schedules: {agent: '*'}};
  const rows = kind => state.resources[kind] || [];
  const label = (pairs, value) => pairs.find(([key]) => key === value)?.[1] || value;
  const owner = slug => agent(slug)?.name || slug || 'Unassigned';
  const action = (name, text, id = '', primary = false) => `<button type="button" class="planning-button${primary ? ' planning-primary' : ''}" data-plan-action="${esc(name)}" data-plan-id="${esc(id)}">${esc(text)}</button>`;
  const options = (pairs, selected) => pairs.map(([value, text]) => `<option value="${esc(value)}"${value === selected ? ' selected' : ''}>${esc(text)}</option>`).join('');
  const withCurrent = (pairs, value) => value && !pairs.some(([key]) => key === value) ? [...pairs, [value, value]] : pairs;
  function agentOptions(value, filtering = false, kind = 'tasks') {
    let pairs = [[filtering ? '*' : '', filtering ? 'All agents' : 'Unassigned'], ...state.agents.map(a => [a.slug, a.name])];
    if (filtering) {
      pairs.push(['', 'Unassigned']);
      rows(kind).forEach(item => { if (item.agent && !pairs.some(([key]) => key === item.agent)) pairs.push([item.agent, owner(item.agent)]); });
    }
    return options(withCurrent(pairs, value), value);
  }
  function dateLabel(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return value || 'No due date';
    const date = new Date(`${value}T12:00:00Z`);
    return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('en-GB', {day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC'}).format(date);
  }
  function structured(item) {
    return ['daily', 'weekly', 'once'].includes(item.frequency) && /^([01]\d|2[0-3]):[0-5]\d$/.test(item.time || '') && item.timezone &&
      (item.frequency !== 'weekly' || (Array.isArray(item.weekdays) && item.weekdays.length && item.weekdays.every(d => Number.isInteger(d) && d >= 1 && d <= 7))) &&
      (item.frequency !== 'once' || /^\d{4}-\d{2}-\d{2}$/.test(item.date || ''));
  }
  function timing(item) {
    if (!structured(item)) return item.schedule || 'Custom timing not specified';
    const when = item.frequency === 'daily' ? 'Every day' : item.frequency === 'once' ? dateLabel(item.date) : item.weekdays.map(d => days[d - 1]).join(', ');
    return `${when} · ${item.time} · ${item.timezone}`;
  }
  async function read(kind) {
    const list = await api(`/resources/${kind}`);
    if (!Array.isArray(list)) throw Error('The server did not return a resource list.');
    state.resources[kind] = list;
    return list;
  }
  function visible(kind) {
    const filter = filters[kind];
    return rows(kind).filter(item => (filter.agent === '*' || (item.agent || '') === filter.agent) &&
      (kind !== 'tasks' || filter.status === '*' || (item.status || 'todo') === filter.status));
  }
  function toolbar(kind) {
    const filter = filters[kind];
    const taskStatuses = rows(kind).reduce((pairs, item) => withCurrent(pairs, item.status), [['*', 'All statuses'], ...statuses]);
    return `<div class="planning-toolbar"><label>Agent<select data-plan-filter="agent">${agentOptions(filter.agent, true, kind)}</select></label>
      ${kind === 'tasks' ? `<label>Status<select data-plan-filter="status">${options(taskStatuses, filter.status)}</select></label>` : ''}
      <p data-plan-count></p></div>`;
  }
  function empty(kind, filtered) {
    return `<div class="planning-empty"><p class="planning-kicker">${filtered ? 'A LITTLE SPACE' : 'A FRESH PAGE'}</p>
      <h2>${filtered ? 'Nothing in this view.' : kind === 'tasks' ? 'What’s on your mind?' : 'Make room for a routine.'}</h2>
      <p>${filtered ? 'Try another agent or clear your filters.' : kind === 'tasks' ? 'Add a small next step, give it an owner, and take it from there.' : 'Choose a time and write down the intention. It stays a plan, not an automatic action.'}</p>
      ${action(filtered ? 'clear' : 'new', filtered ? 'Clear filters' : kind === 'tasks' ? 'Add your first to-do' : 'Write a schedule draft', '', true)}</div>`;
  }
  function taskList(list) {
    return `<ul class="planning-list">${[...list].sort((a, b) => Number(a.status === 'done') - Number(b.status === 'done') || String(a.due_date || '9999').localeCompare(String(b.due_date || '9999'))).map(item => `<li class="planning-task${item.status === 'done' ? ' planning-done' : ''}">
      <button type="button" class="planning-check" data-plan-action="complete" data-plan-id="${esc(item.id)}" aria-pressed="${item.status === 'done'}" aria-label="${esc(`${item.status === 'done' ? 'Reopen' : 'Complete'}: ${item.name || 'Untitled to-do'}`)}">${item.status === 'done' ? '✓' : '<span aria-hidden="true"></span>'}</button>
      <div class="planning-item-body"><h3>${esc(item.name || 'Untitled to-do')}</h3><div class="planning-meta"><span>${esc(owner(item.agent))}</span><span>${esc(label(statuses, item.status || 'todo'))}</span>
      ${item.due_date ? `<span>Due ${esc(dateLabel(item.due_date))}</span>` : ''}${item.priority && item.priority !== 'normal' ? `<span class="planning-priority">${esc(label(priorities, item.priority))} priority</span>` : ''}</div>
      ${item.notes ? `<p class="planning-excerpt">${esc(item.notes)}</p>` : ''}</div>
      <div class="planning-row-actions">${action('edit', 'Edit', item.id)}${action('delete', 'Delete', item.id)}</div></li>`).join('')}</ul>`;
  }
  function scheduleList(list) {
    return `<ul class="planning-list">${list.map(item => `<li class="planning-schedule"><div class="planning-item-body"><div class="planning-item-heading"><h3>${esc(item.name || 'Untitled schedule')}</h3><span class="planning-badge">Saved plan</span></div>
      <p class="planning-timing">${esc(timing(item))}</p><div class="planning-meta"><span>${esc(owner(item.agent))}</span><span>Does not run automatically</span></div>
      ${item.prompt ? `<p class="planning-excerpt">${esc(item.prompt)}</p>` : ''}</div><div class="planning-row-actions">${action('edit', 'Edit draft', item.id)}${action('delete', 'Delete', item.id)}</div></li>`).join('')}</ul>`;
  }
  function glance(list) {
    const recurring = list.filter(item => structured(item) && item.frequency !== 'once');
    return `<section class="planning-glance" aria-label="Recurring draft weekday overview"><div class="planning-section-heading"><h2>A week, at a glance</h2><span>Plans, not a run queue</span></div>
      <p class="planning-help">Daily and weekly drafts in their saved time zones. One-off dates and custom timing stay in the list below.</p>
      <ol class="planning-week">${days.map((day, index) => {
        const items = recurring.filter(item => item.frequency === 'daily' || item.weekdays.includes(index + 1)).sort((a, b) => a.time.localeCompare(b.time));
        return `<li><h3>${day}<span>${items.length}</span></h3>${items.length ? items.slice(0, 2).map(item => `<p><time>${esc(item.time)}</time><span>${esc(item.name || 'Untitled')}</span></p>`).join('') : '<p class="planning-day-empty">—</p>'}${items.length > 2 ? `<small>+${items.length - 2} more in list</small>` : ''}</li>`;
      }).join('')}</ol></section>`;
  }
  function paint(root) {
    const kind = root.dataset.planning, list = visible(kind), total = rows(kind).length;
    root.querySelector('[data-plan-count]').textContent = `${list.length} of ${total} ${kind === 'tasks' ? 'to-dos' : 'saved plans'}${kind === 'tasks' ? ` · ${rows(kind).filter(item => item.status === 'done').length} done` : ''}`;
    root.querySelector('[data-plan-list]').innerHTML = list.length ? (kind === 'tasks' ? taskList(list) : scheduleList(list)) : empty(kind, total > 0);
    if (kind === 'schedules') root.querySelector('[data-plan-glance]').innerHTML = glance(list);
  }
  const field = (name, text, value = '', type = 'text', required = false) => `<label>${esc(text)}<input name="${esc(name)}" type="${type}" value="${esc(value)}"${required ? ' required' : ''}${type === 'text' ? ' maxlength="200"' : ''}></label>`;
  function editor(kind, item = {}) {
    const task = kind === 'tasks', legacy = !task && item.id && !structured(item);
    return `<form class="planning-form" data-plan-form data-plan-id="${esc(item.id || '')}"><p class="planning-kicker">${item.id ? 'MAKE AN ADJUSTMENT' : 'ONE SMALL STEP'}</p>
      <div class="planning-section-heading"><h2>${item.id ? task ? 'Edit to-do' : 'Edit draft' : task ? 'A new to-do' : 'A new schedule'}</h2>${item.id ? action('new', 'Cancel') : ''}</div>
      <p class="planning-help">${task ? 'Keep the next step clear and manageable. Assigning an agent is a label, not an instruction to run.' : 'Save an intention for later. Nothing is sent to an agent or added to cron.'}</p>
      <fieldset class="planning-fields">${field('name', task ? 'What needs doing?' : 'Name this plan', item.name || '', 'text', true)}
      <label>Agent<select name="agent">${agentOptions(item.agent || '')}</select></label>
      ${task ? `<div class="planning-form-pair"><label>Status<select name="status">${options(withCurrent(statuses, item.status), item.status || 'todo')}</select></label><label>Priority<select name="priority">${options(withCurrent(priorities, item.priority), item.priority || 'normal')}</select></label></div>
        ${field('due_date', 'Due date · optional', item.due_date || '', 'date')}<label>Notes<textarea name="notes" rows="4" maxlength="12000">${esc(item.notes || '')}</textarea></label>` : `
        ${legacy ? `<div class="planning-legacy"><p>Existing timing: <strong>${esc(item.schedule || 'Not specified')}</strong></p><label class="planning-choice"><input type="checkbox" data-plan-replace> Replace with daily, weekly, or one-off timing</label><p class="planning-help">Leave unchecked to keep the existing timing unchanged.</p></div>` : ''}
        <fieldset class="planning-timing-fields" data-plan-timing${legacy ? ' hidden disabled' : ''}><legend>When would you like it?</legend>
          <label>Repeats<select name="frequency">${options([['daily', 'Every day'], ['weekly', 'Each week'], ['once', 'Just once']], structured(item) ? item.frequency : 'daily')}</select></label>
          <fieldset class="planning-weekday-fields" data-plan-weekdays><legend>On these days</legend><div class="planning-day-choices">${days.map((day, i) => `<label class="planning-choice"><input type="checkbox" name="weekdays" value="${i + 1}"${(Array.isArray(item.weekdays) ? item.weekdays : [1]).includes(i + 1) ? ' checked' : ''}><span>${day}</span></label>`).join('')}</div></fieldset>
          <div data-plan-date>${field('date', 'Date', item.date || '', 'date')}</div>${field('time', 'Local time', item.time || '09:00', 'time', true)}
          ${field('timezone', 'Time zone', item.timezone || 'Asia/Riyadh', 'text', true)}<p class="planning-help">Use an IANA zone, such as Asia/Riyadh or Europe/London. No time-zone conversion is applied to this draft.</p>
        </fieldset><label>Instruction to save<textarea name="prompt" rows="4" maxlength="12000" required>${esc(item.prompt || '')}</textarea></label>`}
      <p class="planning-form-error" data-plan-form-error role="alert" hidden></p><button type="submit" class="planning-button planning-primary">${item.id ? 'Save changes' : task ? 'Add to-do' : 'Save draft'}</button>
      </fieldset>${!task ? '<p class="planning-save-note">Saved plans do not run automatically. All schedule saves set enabled to false.</p>' : ''}</form>`;
  }
  function syncTiming(form) {
    const timingFields = form.querySelector('[data-plan-timing]');
    if (!timingFields) return;
    const replace = form.querySelector('[data-plan-replace]');
    timingFields.hidden = timingFields.disabled = Boolean(replace && !replace.checked);
    const frequency = form.elements.frequency.value;
    const weekdays = form.querySelector('[data-plan-weekdays]');
    weekdays.hidden = weekdays.disabled = frequency !== 'weekly';
    form.querySelector('[data-plan-date]').hidden = frequency !== 'once';
    form.elements.date.disabled = frequency !== 'once';
    form.elements.date.required = frequency === 'once';
  }
  function openEditor(root, item = {}, focus = true) {
    root.querySelector('[data-plan-editor]').innerHTML = editor(root.dataset.planning, item);
    const form = root.querySelector('[data-plan-form]');
    syncTiming(form);
    if (focus) form.elements.name.focus();
  }
  function canDiscard(root) {
    return !root.querySelector('[data-plan-form]')?.dataset.dirty || confirm('Discard the unsaved changes in this editor?');
  }
  function feedback(root, text, error = false) {
    const node = root.querySelector('[data-plan-feedback]');
    node.textContent = text;
    node.hidden = false;
    node.setAttribute('role', error ? 'alert' : 'status');
    node.classList.toggle('planning-error', error);
  }
  async function page(kind) {
    await read(kind);
    const task = kind === 'tasks';
    return shell(`<section class="planning-page" data-planning="${kind}" aria-label="${task ? 'To-do list' : 'Schedule drafts'}">${head('YOUR PLANNING DESK', task ? 'To-do' : 'Schedules', task ? 'A little structure for what matters next.' : 'A thoughtful rhythm, ready when you are.', `<div class="planning-head-actions">${action('refresh', 'Refresh')}${action('new', task ? '+ Add to-do' : '+ New draft', '', true)}</div>`)}
      ${!task ? '<aside class="planning-notice"><strong>Saved plans do not run automatically.</strong><p>There is no scheduler connected. These are local drafts only: no agent runs, reminders, or cron jobs are created.</p></aside>' : ''}
      <div class="planning-feedback" data-plan-feedback role="status" aria-live="polite" hidden></div>${toolbar(kind)}${!task ? '<div data-plan-glance></div>' : ''}
      <div class="planning-layout"><section class="planning-ledger" aria-label="${task ? 'Your to-dos' : 'Saved schedule drafts'}"><div class="planning-section-heading"><h2>${task ? 'The next small steps' : 'Your saved plans'}</h2><span>${task ? 'One at a time' : 'Drafts only'}</span></div><div data-plan-list></div></section>
      <aside class="planning-editor" data-plan-editor aria-label="${task ? 'To-do editor' : 'Schedule editor'}"></aside></div></section>`);
  }
  // PATCH sends only changed fields; the existing API merges them, retaining unknown metadata.
  async function commit(root, item, data, deleting = false) {
    const kind = root.dataset.planning, path = `/resources/${kind}${item.id ? '/' + encodeURIComponent(item.id) : ''}`;
    const payload = item.id ? Object.fromEntries(Object.entries(data).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(item[key]))) : data;
    const controls = [...root.querySelectorAll('button, input, select, textarea')].map(node => [node, node.disabled]);
    root.dataset.busy = 'true'; controls.forEach(([node]) => { node.disabled = true; });
    try {
      const saved = await api(path, {method: deleting ? 'DELETE' : item.id ? 'PATCH' : 'POST', ...(deleting ? {} : {body: JSON.stringify(payload)})});
      const list = await read(kind), id = item.id || saved?.id, record = list.find(row => row.id === id);
      if (deleting ? Boolean(record) : !id || !record || Object.entries(payload).some(([key, value]) => JSON.stringify(record[key]) !== JSON.stringify(value))) throw Error('The saved change could not be confirmed.');
      if (!root.isConnected) return;
      paint(root);
      const form = root.querySelector('[data-plan-form]');
      if (!item.id || form.dataset.planId === item.id) openEditor(root, {}, false);
      feedback(root, deleting ? 'Deleted from your local plans.' : kind === 'tasks' ? 'To-do saved.' : 'Draft saved. Nothing will run automatically.');
    } catch (error) {
      if (root.isConnected) {
        root.dataset.uncertain = 'true';
        feedback(root, `${error.message} The write may have reached the server. Use Refresh to check saved records before making another change. Your editor is still here.`, true);
      }
    } finally {
      delete root.dataset.busy;
      controls.forEach(([node, disabled]) => { node.disabled = disabled; });
    }
  }
  function formData(form, kind) {
    const values = Object.fromEntries(new FormData(form));
    const data = {name: values.name.trim(), agent: values.agent};
    if (!data.name) throw Error('Give this plan a name.');
    if (kind === 'tasks') return {...data, status: values.status, priority: values.priority, due_date: values.due_date, notes: values.notes, ...(!form.dataset.planId ? {enabled: true} : {})};
    Object.assign(data, {prompt: values.prompt.trim(), enabled: false});
    if (!data.prompt) throw Error('Add an instruction to save with this draft.');
    if (form.querySelector('[data-plan-timing]').disabled) return data;
    const weekdays = [...form.querySelectorAll('input[name="weekdays"]:checked')].map(input => Number(input.value));
    if (values.frequency === 'weekly' && !weekdays.length) throw Error('Choose at least one weekday.');
    const timezone = values.timezone.trim();
    try { new Intl.DateTimeFormat('en', {timeZone: timezone}).format(); } catch { throw Error('Enter a valid IANA time zone, for example Asia/Riyadh.'); }
    Object.assign(data, {frequency: values.frequency, time: values.time, timezone, date: values.frequency === 'once' ? values.date : '', weekdays: values.frequency === 'weekly' ? weekdays : []});
    data.schedule = timing(data);
    return data;
  }
  function bindPage() {
    const root = document.querySelector('.planning-page[data-planning]');
    if (!root || root.dataset.bound) return;
    root.dataset.bound = 'true'; paint(root); openEditor(root, {}, false);
    root.addEventListener('input', event => {
      const form = event.target.closest('[data-plan-form]');
      if (form) form.dataset.dirty = 'true';
    });
    root.addEventListener('change', event => {
      if (event.target.dataset.planFilter) { filters[root.dataset.planning][event.target.dataset.planFilter] = event.target.value; paint(root); }
      const form = event.target.closest('[data-plan-form]');
      if (form) { form.dataset.dirty = 'true'; syncTiming(form); }
    });
    root.addEventListener('click', async event => {
      const button = event.target.closest('[data-plan-action]');
      if (!button || root.dataset.busy) return;
      const kind = root.dataset.planning, intent = button.dataset.planAction;
      if (intent === 'refresh') {
        if (!canDiscard(root)) return;
        root.dataset.busy = 'true'; button.disabled = true;
        try {
          await read(kind);
          if (!root.isConnected) return;
          delete root.dataset.uncertain;
          root.querySelector('.planning-toolbar').outerHTML = toolbar(kind);
          paint(root); openEditor(root, {}, false); feedback(root, 'Saved records refreshed.');
        } catch (error) { feedback(root, error.message, true); }
        finally { delete root.dataset.busy; button.disabled = false; }
        return;
      }
      if (root.dataset.uncertain) return feedback(root, 'Refresh saved records before making another change.', true);
      if (intent === 'clear') {
        filters[kind] = kind === 'tasks' ? {agent: '*', status: '*'} : {agent: '*'};
        root.querySelector('.planning-toolbar').outerHTML = toolbar(kind); paint(root); return;
      }
      if (intent === 'new') { if (canDiscard(root)) openEditor(root); return; }
      const item = rows(kind).find(row => row.id === button.dataset.planId);
      if (!item) return feedback(root, 'This record is no longer available. Refresh the page.', true);
      if (intent === 'edit') { if (canDiscard(root)) openEditor(root, item); return; }
      const editingThisItem = root.querySelector('[data-plan-form]').dataset.planId === item.id;
      if (editingThisItem && !canDiscard(root)) return;
      if (intent === 'delete' && confirm(`Delete “${item.name || 'Untitled'}”? This removes the local record and cannot be undone.`)) await commit(root, item, {}, true);
      if (intent === 'complete' && kind === 'tasks') await commit(root, item, {status: item.status === 'done' ? 'todo' : 'done'});
    });
    root.addEventListener('submit', async event => {
      const form = event.target.closest('[data-plan-form]');
      if (!form) return;
      event.preventDefault();
      if (root.dataset.busy) return;
      if (root.dataset.uncertain) return feedback(root, 'Refresh saved records before retrying this save.', true);
      const errorNode = form.querySelector('[data-plan-form-error]'); errorNode.hidden = true;
      try {
        const item = rows(root.dataset.planning).find(row => row.id === form.dataset.planId) || {};
        if (form.dataset.planId && !item.id) throw Error('This record no longer exists. Refresh before saving.');
        await commit(root, item, formData(form, root.dataset.planning));
      } catch (error) { errorNode.textContent = error.message; errorNode.hidden = false; }
    });
  }
  return {page, bind: bindPage};
})();

async function tasksPage() { return Planning.page('tasks'); }
async function schedulesPage() { return Planning.page('schedules'); }
function bindPlanning() { Planning.bind(); }
