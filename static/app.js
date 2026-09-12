const state={agents:[],health:null,current:'overview',resources:{},news:[],actions:[],uploads:[],audit:[]};
const groups=[
 ['Command center',[['overview','⌂','Overview'],['ceo','◉','CEO workspace'],['inbox','◨','Inbox'],['approvals','✓','Approvals']]],
 ['Agents',[['agent-panel','◎','All agents'],['job','▤','Job application'],['dad','✉','Dad’s email'],['tech-news','◫','Tech news']]],
 ['Operations',[['tasks','☷','Tasks'],['delegations','⇄','Delegations'],['activity','◈','Activity'],['files','⇧','Files'],['browsers','◇','Agent browsers'],['schedules','◷','Schedules']]],
 ['System',[['models','◌','Models'],['tools','⌁','Tools'],['skills','✦','Skills'],['email_accounts','@','Email accounts'],['connectors','⇄','Connectors'],['job_sources','⌖','Job sources'],['telegram','✈','Telegram'],['n8n','⇔','n8n automation'],['audit','≡','Audit log']]],
 ['Build',[['projects','▱','Projects & repos'],['report','§','Engineering report']]]
];
const resourceMeta={
 tools:{title:'Tools',desc:'Capabilities agents may use. Adding a record does not install executable code.',fields:[['name','Name'],['description','Description'],['agent','Agent scope'],['enabled','Enabled','checkbox']]},
 skills:{title:'Skills',desc:'Reusable workflow guidance assigned to agents. Skill records are policy metadata, not executable uploads.',fields:[['name','Name'],['description','Description'],['agent','Agent scope'],['enabled','Enabled','checkbox']]},
 email_accounts:{title:'Email accounts',desc:'Register multiple inboxes and ownership rules. OAuth secrets stay in the provider/Hermes credential store.',fields:[['name','Account label'],['address','Email address'],['provider','Provider'],['agent','Allowed agent'],['enabled','Connection enabled','checkbox']]},
 connectors:{title:'Connectors',desc:'Obsidian, Notion, Gmail, Telegram, WhatsApp and other integration definitions.',fields:[['name','Name'],['kind','Type'],['description','Scope / notes'],['enabled','Enabled','checkbox']]},
 job_sources:{title:'Job sources',desc:'Websites, Telegram channels, WhatsApp channels, RSS feeds, and career pages to review for new roles.',fields:[['name','Source name'],['kind','website / telegram / whatsapp / rss'],['url','URL or channel reference'],['notes','Notes'],['enabled','Enabled','checkbox']]},
 n8n_webhooks:{title:'n8n Webhooks',desc:'Outgoing webhooks to n8n for notifications (e.g., Telegram) when an action is approved.',fields:[['name','Name'],['url','Webhook URL'],['agent_slug','Agent (optional routing)'],['enabled','Enabled','checkbox']]},
 tasks:{title:'Tasks',desc:'Structured work owned by one agent.',fields:[['name','Task'],['agent','Owner agent'],['status','Status'],['notes','Notes'],['enabled','Active','checkbox']]},
 schedules:{title:'Schedules',desc:'Routine definitions. These remain inactive until explicitly enabled in Hermes cron.',fields:[['name','Schedule name'],['agent','Agent'],['schedule','When'],['prompt','Instruction'],['enabled','Enabled','checkbox']]},
 projects:{title:'Projects & repositories',desc:'Organize work and repository references. Linking a repo never executes it.',fields:[['name','Name'],['kind','project / repository'],['url','Repository or reference URL'],['notes','Notes'],['enabled','Active','checkbox']]}
};
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path,options={}){const r=await fetch('/api'+path,{headers:options.body instanceof FormData?{}:{'Content-Type':'application/json'},...options});let data;try{data=await r.json()}catch{data={error:'Invalid server response'}}if(!r.ok)throw Error(data.error||'Request failed');return data}
function toast(msg){const t=$('#toast');t.textContent=msg;t.classList.add('show');clearTimeout(toast.t);toast.t=setTimeout(()=>t.classList.remove('show'),3500)}

// ── Text-to-Speech & Speech-to-Text ─────────────────────────────────────────
let _ttsUtterance=null;
function tts(text,lang='en-US'){window.speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(text);u.lang=lang;u.rate=1.0;u.pitch=1.0;_ttsUtterance=u;window.speechSynthesis.speak(u);return u}
function ttsStop(){window.speechSynthesis.cancel()}
function ttsSpeaking(){return window.speechSynthesis.speaking}

let _recognition=null;
function sttStart(lang='en-US',onResult,onError){
  if(!('webkitSpeechRecognition' in window)&&!('SpeechRecognition' in window)){onError&&onError('Speech recognition not supported in this browser');return}
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  _recognition=new SR();_recognition.lang=lang;_recognition.continuous=false;_recognition.interimResults=false;
  _recognition.onresult=e=>{const t=e.results[0][0].transcript;onResult(t,e.results[0][0].confidence)};
  _recognition.onerror=e=>{_recognition=null;onError&&onError(e.error)};
  _recognition.onend=()=>{_recognition=null};
  _recognition.start();
}
function sttStop(){if(_recognition){_recognition.stop();_recognition=null}}

// ── Overview command-center bindings ────────────────────────────────────────
async function loadCeoMessages(){
  if(!$('#ov-ceo-messages'))return;
  try{
    const msgs=await api('/agents/ceo/messages');
    const recent=(msgs||[]).slice(-8);
    $('#ov-ceo-messages').innerHTML=recent.length?recent.map(m=>`<div class="ov-msg ${m.role}"><span>${m.role==='user'?'You':esc(agent('ceo')?.name||'CEO')}</span><p>${esc(m.content.slice(0,120))}</p></div>`).join(''):'<p class="ov-chat-empty">No messages yet.</p>';
    const container=$('#ov-ceo-messages');
    container.scrollTop=container.scrollHeight;
  }catch(e){$('#ov-ceo-messages').innerHTML='<p class="ov-chat-empty">Could not load messages.</p>';}
}
// ── Page Agent ────────────────────────────────────────────────────────────────
let _paOpen = false;
let _paPinned = false;

function _paAppend(role, text) {
  const container = $('#page-agent-messages');
  const div = document.createElement('div');
  div.className = `page-agent-msg ${role}`;
  div.textContent = text;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function _paApplyEdit(css) {
  let style = $('#page-agent-dynamic-style');
  if (!style) {
    style = document.createElement('style');
    style.id = 'page-agent-dynamic-style';
    document.head.appendChild(style);
  }
  style.textContent = css;
}

async function _paSend(instruction) {
  _paAppend('user', instruction);
  const input = $('#page-agent-input');
  input.value = '';
  const pageHTML = document.body.innerHTML.substring(0, 2000);
  try {
    const res = await api('/page-agent/edit', {
      method: 'POST',
      body: JSON.stringify({ instruction, pageHTML })
    });
    if (res.css) {
      _paApplyEdit(res.css);
      _paAppend('ai', res.description || 'Applied changes to the page.');
    } else if (res.error) {
      _paAppend('ai', `Could not edit: ${res.error}`);
    } else {
      _paAppend('ai', res.message || 'Done.');
    }
  } catch(e) {
    _paAppend('ai', `Error: ${e.message}`);
  }
}

function initPageAgent() {
  const wrap = $('#page-agent');
  const toggle = $('#page-agent-toggle');
  const pin = $('#page-agent-pin');
  const close = $('#page-agent-close');
  const input = $('#page-agent-input');
  const sendBtn = $('#page-agent-send');
  toggle.onclick = () => {
    _paOpen = !_paOpen;
    wrap.style.display = _paOpen ? 'flex' : 'none';
    toggle.textContent = _paOpen ? '✕' : '🤖';
    if (_paOpen) input.focus();
  };
  close.onclick = () => { _paOpen = false; wrap.style.display = 'none'; toggle.textContent = '🤖'; };
  pin.onclick = () => { _paPinned = !_paPinned; pin.style.color = _paPinned ? 'var(--accent)' : ''; };
  const doSend = () => { const v = input.value.trim(); if (!v) return; _paSend(v); };
  sendBtn.onclick = doSend;
  input.onkeydown = e => { if (e.key === 'Enter') doSend(); };
}

async function bindOverview(){
  // Tab switching
  $$('[data-ov-tab]').forEach(btn=>{
    btn.onclick=()=>{
      $$('[data-ov-tab]').forEach(b=>b.classList.remove('active'));
      btn.classList.add('active');
      const tab=btn.dataset.ovTab;
      $$('.overview-tab-content').forEach(p=>p.style.display='none');
      $(`#ov-tab-${tab}`).style.display='block';
    };
  });
  // CEO chat form
  const ceoForm=$('#ov-ceo-form');
  if(ceoForm){
    ceoForm.onsubmit=async e=>{
      e.preventDefault();
      const input=$('#ov-ceo-input');
      const val=input.value.trim();
      if(!val)return;
      input.value='';
      const btn=ceoForm.querySelector('button[type="submit"]');
      btn.disabled=true;btn.textContent='…';
      try{
        await api('/agents/ceo/messages',{method:'POST',body:JSON.stringify({content:val})});
        await loadCeoMessages();
      }catch(err){toast(err.message);}
      finally{btn.disabled=false;btn.textContent='Send';}
    };
    // STT on CEO chat
    const sttBtn=$('#ov-stt-btn');
    if(sttBtn){
      sttBtn.onclick=()=>sttStart('en-US',t=>{$('#ov-ceo-input').value=(($('#ov-ceo-input').value+' '+t).trim())},e=>toast('STT: '+e));
    }
  }
  // Load CEO messages on mount
  await loadCeoMessages();
  // Task toggle
  $$('[data-task-toggle]').forEach(btn=>{
    btn.onclick=async()=>{
      const id=btn.dataset.taskToggle;
      const tasks=state.resources['tasks']||[];
      const task=tasks.find(t=>t.id===id);
      if(!task)return;
      const newStatus=task.status==='done'?'todo':'done';
      try{
        await api(`/resources/tasks/${id}`,{method:'PATCH',body:JSON.stringify({status:newStatus})});
        task.status=newStatus;
        if(state.current==='overview'){$('#content').innerHTML=overview();bindOverview();}
      }catch(e){toast(e.message);}
    };
  });
  // Delegation assign button
  $$('[data-ov-assign]').forEach(btn=>{
    btn.onclick=()=>{
      const id=btn.dataset.ovAssign;
      api(`/delegations/${id}`,{method:'PATCH',body:JSON.stringify({status:'in_progress'})}).then(()=>{
        toast('Opening agent…');go('agent-panel');
      }).catch(e=>toast(e.message));
    };
  });
  // Quick action buttons
  $$('.qa-btn').forEach(btn=>{
    btn.onclick=()=>go(btn.dataset.page);
  });
  // Quick-create agent
  if($('#overview-create-agent')){
    $('#overview-create-agent').onclick=quickAgentModal;
  }
  // Team cards
  $$('.ov-team-card').forEach(card=>{
    card.onclick=()=>go(card.dataset.openAgent);
    card.style.cursor='pointer';
  });
  // Agent pills
  $$('.ov-agent-pill').forEach(pill=>{
    pill.onclick=()=>go(pill.dataset.openAgent);
  });
}
let tgState={sessions:[],pendingMessages:[],linkedChatId:null};
async function telegramPage(){
  const [status,sessions]=await Promise.all([api('/telegram/status'),api('/telegram/sessions')]);
  tgState.sessions=sessions||[];
  const tokenSet=status.bot_token_set;
  const polling=status.polling;
  const rows=tgState.sessions.map(s=>`<div class="row"><span class="agent-mark">✈</span><div class="row-main"><h3>${esc(s.chat_id)}</h3><p>Linked to @${esc(s.agent_slug)}</p></div><button class="button small danger" data-tg-unlink="${esc(s.chat_id)}">Unlink</button></div>`).join('');
  return shell(head('TELEGRAM','Chat with your agents from anywhere.','Text, voice messages, and real-time replies via a Telegram bot.',`<button class="button" id="tg-check">Check for messages</button>`)+`<div class="grid two">
    <section class="panel"><div class="panel-head"><h2>Bot status</h2><span class="pill ${tokenSet?'green':'rose'}">${tokenSet?(polling?'Polling':'Stopped'):'No token'}</span></div>
      ${tokenSet?`<div class="status-line"><span>Polling</span><strong>${polling?'Active':'Stopped'}</strong></div>
      <div class="status-line"><span>Linked chats</span><strong>${tgState.sessions.length}</strong></div>
      <p class="muted">Send any message to your bot to link your Telegram chat to an agent.</p>`:
      `<div class="notice"><strong>No bot token configured.</strong> Enter your bot token below to enable Telegram.</div>
      <form id="tg-token-form" class="tg-token-form">
        <div class="field-row">
          <input id="tg-token-input" type="password" placeholder="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ" style="flex:1" required>
          <button type="submit" class="button primary">Connect bot</button>
        </div>
        <p class="muted" style="margin-top:8px">Need a bot? Open Telegram and chat with <a href="https://t.me/BotFather" target="_blank">@BotFather</a> → /newbot</p>
      </form>`}
    </section>
    <section class="panel"><div class="panel-head"><h2>Linked chats</h2></div>
      ${rows||'<p class="muted">No chats linked yet. Message your bot to start.</p>'}
    </section></div>
    <section class="panel section-gap"><div class="panel-head"><h2>Voice messages</h2></div>
      <p class="muted">Voice messages sent to the bot are transcribed using your browser's speech recognition and sent to the linked agent. The agent's reply is sent back as text.</p>
      <p class="muted">Requires: Chrome/Edge/Safari with microphone permission. No external service needed.</p>
    </section>`);
  if(!tokenSet){
    const form=document.getElementById('tg-token-form');
    if(form)form.onsubmit=async e=>{e.preventDefault();const inp=document.getElementById('tg-token-input');const btn=form.querySelector('button[type=submit]');const tok=inp.value.trim();if(!tok)return;btn.disabled=true;btn.textContent='Connecting…';try{const r=await api('/telegram/configure',{method:'POST',body:JSON.stringify({token:tok})});toast('Bot connected as @'+r.bot_username);await go('telegram')}catch(err){toast('Failed: '+err.message);btn.disabled=false;btn.textContent='Connect bot'}};
  }
}
async function telegramCheck(){
  const data=await api('/telegram/pending');
  if(!data.messages||!data.messages.length)return toast('No new Telegram messages');
  for(const msg of data.messages){
    const chatId=String(msg.chat_id);
    let linked=tgState.sessions.find(s=>s.chat_id===chatId);
    if(!linked){
      // Auto-register if not linked, assign to CEO
      try{await api('/telegram/link',{method:'POST',body:JSON.stringify({chat_id:chatId,agent_slug:'ceo'})});linked={chat_id:chatId,agent_slug:'ceo'};tgState.sessions.push(linked);toast(`New chat ${chatId} linked to CEO`)}catch(e){toast('Could not link Telegram chat');continue}
    }
    if(msg.text){
      try{const reply=await api(`/agents/${linked.agent_slug}/messages`,{method:'POST',body:JSON.stringify({content:msg.text})});const response=reply.assistant||reply;if(response.content)await api('/telegram/forward',{method:'POST',body:JSON.stringify({chat_id:chatId,agent_slug:linked.agent_slug,text:response.content})});toast(`${linked.agent_slug} replied to Telegram`)}catch(e){toast('Agent reply failed: '+e.message)}
    } else if(msg.voice_file_id){
      toast('Voice message received — add bot token and restart to enable transcription');
    }
  }
  await go('telegram');
}
function head(kicker,title,desc,action=''){return `<div class="page-head"><div><p class="eyebrow">${esc(kicker)}</p><h1>${esc(title)}</h1><p>${esc(desc)}</p></div>${action}</div>`}
function shell(html){return `<div class="content-wrap">${html}<div class="footer-note"><span>Personal OS · local-first</span><span>External actions stay approval-gated.</span></div></div>`}
function nav(){const pending=state.actions.filter(a=>a.status==='pending').length;$('#nav').innerHTML=groups.map(([g,items])=>`<div class="nav-group">${g}</div>${items.map(([id,icon,label])=>`<button class="nav-item ${state.current===id?'active':''}" data-page="${id}"><span class="nav-icon">${icon}</span><span class="nav-label">${label}</span>${id==='approvals'&&pending?`<span class="nav-badge">${pending}</span>`:''}</button>`).join('')}`).join('');$$('[data-page]').forEach(b=>b.onclick=()=>go(b.dataset.page))}
async function loadBase(){const [health,agents,actions,n8nWebhooks,tasks,schedules]=await Promise.all([api('/health'),api('/agents'),api('/actions'),api('/n8n/webhooks'),api('/resources/tasks'),api('/resources/schedules')]);Object.assign(state,{health,agents,actions});state.resources['n8n_webhooks']=n8nWebhooks;state.resources['tasks']=tasks||[];state.resources['schedules']=schedules||[];$('#runtime-status').textContent=health.runtime==='hermes'?'Hermes safe runtime enabled':'Offline-safe runtime';nav()}
async function go(page){state.current=page;location.hash=page;$('#sidebar').classList.remove('open');const labels=groups.flatMap(g=>g[1]).find(x=>x[0]===page);$('#page-title').textContent=labels?.[2]||'Agent';nav();$('#content').innerHTML=shell('<div class="empty">Loading workspace…</div>');try{await render()}catch(e){$('#content').innerHTML=shell(head('ERROR','This page could not load.',e.message)+`<div class="notice">Check that the Python server is still running.</div>`)}window.scrollTo(0,0)}
function agent(slug){return state.agents.find(a=>a.slug===slug)}
function overview(){
  const pending=state.actions.filter(a=>a.status==='pending').length;
  const tasks=(state.resources['tasks']||[]);
  const doneTasks=tasks.filter(t=>t.status==='done').length;
  const openTasks=tasks.filter(t=>t.status!=='done').length;
  const delegations=(state.resources['delegations']||[]).filter(d=>d.status==='pending');
  const uploads=state.uploads||[];
  const whCount=(state.resources['n8n_webhooks']||[]).filter(w=>w.enabled).length;
  const now=new Date();
  const greeting=now.getHours()<12?'Good morning':now.getHours()<17?'Good afternoon':'Good evening';
  const dateStr=now.toLocaleDateString('en-US',{weekday:'long',month:'long',day:'numeric'});
  const quickActions=[
    ['ceo','◉','Talk to CEO'],['job','▤','Find jobs'],['tasks','☷','View tasks'],['schedules','◷','Schedules'],['delegations','⇄','Delegations'],['telegram','✈','Telegram']
  ];
  const agents=[
    ['ceo','CEO','◉','CEO Agent','Handles delegations, strategic decisions, and coordinates your team.'],
    ['job','JOB','▤','Job Agent','Searches for roles, tailors your CV, and submits applications.'],
    ['dad','DAD','✉',"Dad's Email",'Handles website support, correspondence, and follow-up emails.'],
    ['tech-news','NEWS','◫','Tech News','Curates AI and tech stories, generates TikTok scripts.']
  ];
  return `<div class="overview-page">
  <div class="overview-hero">
    <div class="overview-greeting">
      <h1>${greeting}, Mohammad.</h1>
      <p>${dateStr} &nbsp;·&nbsp; <span class="overview-status">Personal OS running</span></p>
    </div>
    <div class="overview-quick-actions">
      ${quickActions.map(([id,icon,label])=>`<button class="qa-btn" data-page="${id}"><span class="qa-icon">${icon}</span><span>${label}</span></button>`).join('')}
      <button class="qa-btn qa-create" id="overview-create-agent"><span class="qa-icon">＋</span><span>Create agent</span></button>
    </div>
  </div>
  <div class="overview-body">
    <div class="overview-main">
      <div class="overview-tabs" id="overview-tabs">
        <button class="ov-tab active" data-ov-tab="tasks">Tasks</button>
        <button class="ov-tab" data-ov-tab="delegations">Delegations</button>
        <button class="ov-tab" data-ov-tab="team">Team</button>
      </div>
      <div class="overview-tab-content" id="ov-tab-tasks">
        <div class="overview-section-head">
          <h2>To-do list</h2>
          <button class="ov-add-btn" data-page="tasks">＋ Add task</button>
        </div>
        ${tasks.length?`<div class="ov-task-list">
          ${tasks.slice(0,8).map(t=>`<div class="ov-task-item ${t.status==='done'?'done':''}">
            <span class="ov-task-check ${t.status==='done'?'checked':''}" data-task-toggle="${t.id}">${t.status==='done'?'✓':'○'}</span>
            <div class="ov-task-body">
              <span class="ov-task-name">${esc(t.name||'Untitled')}</span>
              <span class="ov-task-meta">@${esc(t.agent||'unassigned')} · ${esc(t.status||'todo')}${t.due_date?' · Due '+t.due_date:''}</span>
            </div>
            <span class="ov-task-priority ${esc(t.priority||'normal')}">${esc(t.priority||'normal')}</span>
          </div>`).join('')}
        </div>
        ${openTasks>8?`<p class="ov-more">+${openTasks-8} more tasks · <button data-page="tasks">View all</button></p>`:''}
        `:`<div class="ov-empty"><p>No tasks yet.</p><button class="ov-add-btn" data-page="tasks">＋ Add your first to-do</button></div>`}
        <div class="ov-stats-row">
          <div class="ov-stat"><strong>${openTasks}</strong><span>Open</span></div>
          <div class="ov-stat"><strong>${doneTasks}</strong><span>Done</span></div>
          <div class="ov-stat"><strong>${tasks.length}</strong><span>Total</span></div>
        </div>
      </div>
      <div class="overview-tab-content" id="ov-tab-delegations" style="display:none">
        <div class="overview-section-head">
          <h2>CEO Delegations</h2>
          <button class="ov-add-btn" data-page="delegations">View all</button>
        </div>
        ${delegations.length?`<div class="ov-delegation-list">
          ${delegations.map(d=>`<div class="ov-delegation-item">
            <span class="ov-delegation-badge">@${esc(d.target_agent)}</span>
            <div class="ov-delegation-body">
              <p>${esc(d.instruction||d.task_type||'')}</p>
              <span class="ov-delegation-meta">${esc(d.status)} · ${esc(d.created_at)}</span>
            </div>
            <button class="ov-assign-btn" data-ov-assign="${d.id}">Assign →</button>
          </div>`).join('')}
        </div>`:`<div class="ov-empty"><p>No pending delegations.</p><p class="ov-hint">Ask the CEO to assign work — try: <em>@job find me a job in Saudi Arabia</em></p></div>`}
      </div>
      <div class="overview-tab-content" id="ov-tab-team" style="display:none">
        <div class="overview-section-head"><h2>Your team</h2></div>
        <div class="ov-team-grid">
          ${agents.map(([slug,short,name,desc])=>`<div class="ov-team-card" data-open-agent="${slug}">
            <div class="ov-team-icon">${short}</div>
            <div class="ov-team-info">
              <h3>${esc(name)}</h3>
              <p>${esc(desc)}</p>
            </div>
            <div class="ov-team-model">
              <span class="pill ${state.agents.find(a=>a.slug===slug)?.free_only?'green':''}">${esc(state.agents.find(a=>a.slug===slug)?.model_provider||'offline')}</span>
            </div>
          </div>`).join('')}
        </div>
      </div>
    </div>
    <div class="overview-sidebar">
      <div class="ov-chat-card" id="ov-ceo-chat">
        <div class="ov-chat-header">
          <span class="ov-chat-title">◉ CEO</span>
          <span class="pill green">Online</span>
        </div>
        <div class="ov-chat-messages" id="ov-ceo-messages"></div>
        <form class="ov-chat-composer" id="ov-ceo-form">
          <input id="ov-ceo-input" placeholder="Ask the CEO anything…" maxlength="2000">
          <div class="ov-chat-actions">
            <button type="button" class="ov-stt-btn" id="ov-stt-btn" title="Voice">🎤</button>
            <button type="submit" class="ov-send-btn">Send</button>
          </div>
        </form>
      </div>
      <div class="ov-metric-stack">
        <div class="ov-metric-card">
          <span class="ov-metric-label">Pending approvals</span>
          <strong class="${pending?'warn':''}">${pending}</strong>
        </div>
        <div class="ov-metric-card">
          <span class="ov-metric-label">n8n webhooks</span>
          <strong>${whCount}</strong>
        </div>
        <div class="ov-metric-card">
          <span class="ov-metric-label">Files uploaded</span>
          <strong>${uploads.length}</strong>
        </div>
        <div class="ov-metric-card">
          <span class="ov-metric-label">Agents active</span>
          <strong>${state.agents.length}</strong>
        </div>
      </div>
      <div class="ov-agents-row">
        ${state.agents.filter(a=>['job','dad','tech-news'].includes(a.slug)).map(a=>`<button class="ov-agent-pill" data-open-agent="${a.slug}"><span>${a.name[0]}</span>${esc(a.name)}</button>`).join('')}
      </div>
    </div>
  </div>
</div>`;
}
async function agentWorkspace(slug){const a=agent(slug);if(!a)return shell(head('AGENT','Not found','This agent does not exist.'));const messages=await api(`/agents/${slug}/messages`);const others=state.agents.filter(x=>x.slug!==slug);return shell(head(`AGENT / ${slug.toUpperCase()}`,a.name,a.purpose,`<button class="button dark" data-browser="${slug}">Open ${esc(a.name)} browser</button>`)+`<div class="chat-shell"><section class="panel chat-panel"><div class="panel-head"><div><h2>Conversation</h2><span class="pill ${a.free_only?'green':''}">${a.free_only?'Free only · ':''}${esc(a.model_provider)} / ${esc(a.model_id)}</span></div><span class="pill">${state.health.runtime}</span></div><div class="messages" id="messages">${messages.length?messages.map(m=>`<div class="message ${esc(m.role)}">${esc(m.content)}${m.target_agent?`<div class="message-meta">Directed to @${esc(m.target_agent)}</div>`:''}</div>`).join(''):'<div class="empty">Start a private conversation in this agent’s room.</div>'}</div><form id="chat-form" class="composer">${slug==='ceo'?`<label>Direct through CEO (optional)</label><select id="chat-target"><option value="">CEO only</option>${others.map(x=>`<option value="${esc(x.slug)}">@${esc(x.slug)} · ${esc(x.name)}</option>`).join('')}</select>`:''}<label>Your message</label><textarea id="chat-text" required placeholder="Describe what you want this agent to do…"></textarea><div class="actions"><button class="button primary">Send</button><button type="button" class="button" data-page="files">Upload context</button></div></form></section><aside class="grid"><section class="panel"><p class="eyebrow">AGENT SETTINGS</p><div class="status-line"><span>Model</span><strong>${esc(a.model_id)}</strong></div><div class="status-line"><span>Provider</span><strong>${esc(a.model_provider)}</strong></div><div class="status-line"><span>Tools</span><strong>${a.tools.length}</strong></div><div class="status-line"><span>Skills</span><strong>${a.skills.length}</strong></div><button class="button" data-edit-agent="${slug}">Edit agent</button></section><section class="panel browser-card"><p class="eyebrow">PRIVATE BROWSER ROOM</p><h2>Persistent Chrome profile</h2><p>Manual sign-in is retained in this agent’s isolated local profile. Cookies are never copied to SQLite or notes.</p><div class="browser-bar"><input id="browser-url" value="https://www.google.com" aria-label="URL"><button class="button" data-browser-url="${slug}">Launch</button></div></section></aside></div>`)}
async function agentPanel(){
  const all=['ceo','job','dad','tech-news'];
  const tabs=state.agents.filter(a=>all.includes(a.slug)).map(a=>`<button class="tab-btn ${a.slug==='ceo'?'active':''}" data-agent-tab="${a.slug}">${esc(a.name)}</button>`).join('');
  const panels=state.agents.filter(a=>all.includes(a.slug)).map(a=>`<div class="agent-tab-panel" id="agent-panel-${a.slug}" style="display:${a.slug==='ceo'?'flex':'none'}">
    <section class="chat-panel">
      <div class="panel-head"><div><h2>${esc(a.name)}</h2><span class="pill ${a.free_only?'green':''}">${a.free_only?'Free only · ':''}${esc(a.model_provider)}/${esc(a.model_id)}</span></div><span class="pill">${state.health?.runtime||'–'}</span></div>
      <div class="messages" id="msgs-${a.slug}"><div class="empty">Loading…</div></div>
      <form class="composer" data-chat-form="${a.slug}"><label>Your message</label><textarea id="chat-${a.slug}" required placeholder="Ask ${esc(a.name)} anything…"></textarea><div class="actions"><button class="button primary" type="submit">Send</button></div></form>
    </section>
    <aside class="agent-sidebar">
      <section class="panel"><p class="eyebrow">AGENT SETTINGS</p><div class="status-line"><span>Model</span><strong>${esc(a.model_id)}</strong></div><div class="status-line"><span>Provider</span><strong>${esc(a.model_provider)}</strong></div><div class="status-line"><span>Free only</span><strong>${a.free_only?'✓ Yes':'✗ No'}</strong></div><div class="status-line"><span>Status</span><strong class="pill ${a.enabled?'green':'rose'}">${a.enabled?'Enabled':'Paused'}</strong></div></section>
      <section class="panel"><p class="eyebrow">LATEST ACTIONS</p><div id="agent-actions-${a.slug}"><div class="empty muted">No actions yet.</div></div></section>
      <button class="button" data-open-agent="${esc(a.slug)}">Open full workspace ↗</button>
    </aside>
  </div>`).join('');
  return shell(head('AGENT PANEL','All your agents, one command center.','Switch tabs to chat with each agent. Every conversation stays separate.',`<button class="button primary" data-open-agent="ceo">＋ New conversation</button>`)+`<div class="agent-tabs">${tabs}</div><div class="agent-panels">${panels}</div>`);
}
async function loadAgentPanel(){
  const all=['ceo','job','dad','tech-news'];
  for(const a of state.agents.filter(a=>all.includes(a.slug))){
    const msgs=await api(`/agents/${a.slug}/messages`);
    $(`#msgs-${a.slug}`).innerHTML=msgs.length?msgs.map(m=>`<div class="message ${esc(m.role)}">${esc(m.content)}${m.target_agent?`<div class="message-meta">Directed to @${esc(m.target_agent)}</div>`:''}</div>`).join(''):'<div class="empty">Start a conversation in this agent\'s room.</div>';
    const acts=state.actions.filter(x=>x.agent_slug===a.slug).slice(0,3);
    $(`#agent-actions-${a.slug}`).innerHTML=acts.length?acts.map(a=>`<div class="status-line"><span>${esc(a.action_type)}</span><span class="pill ${a.status==='pending'?'rose':'green'}">${esc(a.status)}</span></div>`).join(''):'<div class="empty muted">No actions yet.</div>';
    const form=$(`[data-chat-form="${a.slug}"]`);
    if(form)form.onsubmit=async e=>{e.preventDefault();const btn=form.querySelector('button');btn.disabled=true;btn.textContent='Thinking…';try{await api(`/agents/${a.slug}/messages`,{method:'POST',body:JSON.stringify({content:$(`#chat-${a.slug}`).value})});await loadAgentPanel()}catch(err){toast(err.message);btn.disabled=false;btn.textContent='Send'}};
  }
}
function agentsPage(){return shell(head('AGENT DIRECTORY','Every assistant has a room.','Chat separately, choose its model, assign tools and skills, or create a new specialist.',`<button class="button primary" id="add-agent">＋ Add agent</button><button class="button" id="quick-agent-btn">＋ Quick create</button>`)+`<div class="resource-grid">${state.agents.map(a=>`<article class="resource-card"><div class="card-top"><span class="agent-mark">${esc(a.name[0])}</span><span class="pill ${a.enabled?'green':'rose'}">${a.enabled?'Enabled':'Paused'}</span></div><h3>${esc(a.name)}</h3><p>${esc(a.purpose||'')}</p><div class="card-actions"><button class="button small" data-open-agent="${esc(a.slug)}">Open</button><button class="button small" data-edit-agent="${esc(a.slug)}">Edit</button></div></article>`).join('')}</div>`)}
function approvals(){return shell(head('REVIEW DESK','Nothing leaves without you.','Approvals are bound to exact recipients, content, attachments, and action data.')+`${state.actions.length?state.actions.map(a=>`<section class="panel approval section-gap"><div class="panel-head"><div><span class="pill ${a.status==='pending'?'rose':'green'}">${esc(a.status)}</span><h2>${esc(a.action_type.replaceAll('_',' '))}</h2></div><span class="mono">${esc(a.agent_slug)} · ${esc(a.digest.slice(0,12))}</span></div><div class="payload">${esc(JSON.stringify(a.payload,null,2))}</div>${a.status==='pending'?`<div class="actions"><button class="button primary" data-decision="approved" data-action="${a.id}">Approve exact action</button><button class="button danger" data-decision="denied" data-action="${a.id}">Deny</button></div>`:'<p class="muted">Decision recorded. Editing this action would return it to pending.</p>'}</section>`).join(''):'<div class="empty">No actions are waiting. Agents create review cards before any protected operation.</div>'}<section class="panel section-gap"><h2>Create a review item</h2><form id="action-form"><div class="form-row"><div><label>Agent</label><select name="agent_slug">${state.agents.map(a=>`<option value="${a.slug}">${esc(a.name)}</option>`).join('')}</select></div><div><label>Action type</label><select name="action_type"><option>send_email</option><option>submit_application</option><option>publish_content</option><option>deploy_source_change</option><option>account_change</option></select></div></div><label>Exact action details (JSON)</label><textarea name="payload">{"summary":"Review this draft action"}</textarea><button class="button primary">Create approval</button></form></section>`)}
async function resourcePage(kind){const meta=resourceMeta[kind];const list=await api(`/resources/${kind}`);state.resources[kind]=list;return shell(head('SYSTEM DIRECTORY',meta.title,meta.desc,`<button class="button primary" data-add-resource="${kind}">＋ Add ${esc(meta.title.toLowerCase())}</button>`)+`<div class="resource-grid">${list.length?list.map(x=>`<article class="resource-card"><div class="card-top"><h3>${esc(x.name||x.address||'Untitled')}</h3><span class="pill ${x.enabled?'green':'rose'}">${x.enabled?'Enabled':'Disabled'}</span></div><p>${esc(x.description||x.notes||x.prompt||x.url||'No description')}</p><div class="source-kinds">${x.kind?`<span class="pill">${esc(x.kind)}</span>`:''}${x.agent?`<span class="pill">${esc(x.agent)}</span>`:''}</div><div class="actions"><button class="button small" data-edit-resource="${kind}" data-id="${x.id}">Edit</button><button class="button small danger" data-delete-resource="${kind}" data-id="${x.id}">Delete</button></div></article>`).join(''):'<div class="empty">No entries yet. Add the first one.</div>'}</div>`)}
async function filesPage(){state.uploads=await api('/uploads');return shell(head('CONTEXT LIBRARY','Files for your agents.','Upload past applications, CVs, job descriptions, project files, and reference documents. Files stay local.',`<button class="button primary" id="upload-open">⇧ Upload files</button>`)+`<section class="panel"><div class="notice">Maximum 25 MB per file. Uploaded content is untrusted data, never agent instructions. Avoid passwords, API keys, and browser-cookie exports.</div>${state.uploads.length?state.uploads.map(f=>`<div class="row"><span class="agent-mark">⇧</span><div class="row-main"><h3>${esc(f.original_name)}</h3><p>${esc(f.agent_slug)} · ${(f.size/1024).toFixed(1)} KB · SHA-256 ${esc(f.sha256.slice(0,12))}…</p></div><span class="pill green">Local</span></div>`).join(''):'<div class="empty section-gap">No files uploaded yet.</div>'}</section>`)}
function browsersPage(){return shell(head('AGENT BROWSERS','A separate browser room for every agent.','Each launch uses its own persistent Chrome profile, keeping Job, Dad, CEO, and Tech News sessions separate.')+`<div class="resource-grid">${state.agents.map(a=>`<article class="resource-card browser-card"><div class="card-top"><span class="agent-mark">${esc(a.name[0])}</span><span class="pill green">Persistent</span></div><h3>${esc(a.name)}</h3><p>Manual logins remain in this agent’s local Chrome profile.</p><label>Start URL</label><input id="url-${a.slug}" value="${a.slug==='job'?'https://www.linkedin.com/jobs/':'https://www.google.com'}"><div class="actions"><button class="button" data-browser-input="${a.slug}">Launch browser</button></div></article>`).join('')}</div><div class="notice section-gap">Chrome profiles provide session separation, not a hardened security sandbox. Agents cannot automatically bypass CAPTCHAs or a site’s terms.</div>`)}
async function techPage(){state.news=await api('/news');return shell(head('TECH NEWS STUDIO','From a verified link to a short video.','Collect stories, inspect their sources, then generate an editable TikTok script with one button.',`<button class="button primary" id="add-news">＋ Add story</button>`)+`<div class="grid two"><section class="panel"><div class="panel-head"><h2>Story desk</h2><button class="button small" id="fetch-feed">Fetch RSS feed</button></div>${state.news.length?state.news.map(n=>`<article class="news-card"><p class="eyebrow">${esc(n.source)}</p><h3>${esc(n.title)}</h3><p>${esc(n.summary)}</p><a href="${esc(n.url)}" target="_blank" rel="noopener">Open source ↗</a><div class="actions"><button class="button primary small" data-script="${n.id}">Generate TikTok script</button></div><div id="script-${n.id}"></div></article>`).join(''):'<div class="empty">Add a verified story or fetch an RSS feed.</div>'}</section><aside><section class="panel"><h2>Script structure</h2><div class="status-line"><span>1</span><span>Hook</span></div><div class="status-line"><span>2</span><span>What happened</span></div><div class="status-line"><span>3</span><span>Why it matters</span></div><div class="status-line"><span>4</span><span>Call to action</span></div><p class="muted">The offline button uses only the story you provide. A configured model can polish it later while preserving citations.</p></section></aside></div>`)}
function modelsPage(){return shell(head('MODEL ROUTING','Choose the brain for every room.','Each agent has an independent provider/model. The Job Agent can be locked to free/local options.')+`<div class="resource-grid">${state.agents.map(a=>`<article class="resource-card"><p class="eyebrow">${esc(a.slug)}</p><h3>${esc(a.name)}</h3><label>Provider</label><select id="provider-${a.slug}">${['offline','ollama','openai-codex','openrouter','anthropic','nous'].map(x=>`<option ${a.model_provider===x?'selected':''}>${x}</option>`).join('')}</select><label>Model ID</label><input id="model-${a.slug}" value="${esc(a.model_id)}"><label><input style="width:auto" type="checkbox" id="free-${a.slug}" ${a.free_only?'checked':''}> Free/local models only</label><button class="button primary small" data-save-model="${a.slug}">Save model</button></article>`).join('')}</div><div class="notice section-gap">Saving a model does not create credentials or download weights. Use Hermes authentication or install Ollama models separately. The system never silently falls back to a paid provider.</div>`)}
async function n8nPage(){const status=await api('/n8n/status');const webhooks=await api('/n8n/webhooks');state.resources['n8n_webhooks']=webhooks;return shell(head('N8N AUTOMATION','Notify n8n when you approve an action.','When you approve an action, Personal OS sends a POST to each enabled webhook URL. n8n can then send a Telegram message, trigger an email, or run any other workflow.',`<button class="button primary" id="n8n-add-wh">＋ Add webhook</button>`)+`<div class="grid two"><section class="panel"><div class="panel-head"><h2>n8n connection</h2><span class="pill ${status.connected?'green':'rose'}">${status.connected?'Connected':'Disconnected'}</span></div><div class="status-line"><span>Status at</span><strong>${esc(status.base_url)}</strong></div>${status.connected?`<div class="status-line"><span>Version</span><strong>${esc(status.version||'unknown')}</strong></div>`:`<div class="notice">n8n is not running or not reachable. Start it and set N8N_BASE_URL if using a non-default port.</div>`}<button class="button" id="n8n-refresh-status">Refresh status</button></section><section class="panel"><h2>Active webhooks</h2><p class="muted">Each enabled webhook receives a POST with agent, action_type, payload, and digest when you approve an action.</p>${webhooks.length?webhooks.map(w=>`<div class="row"><div class="row-main"><h3>${esc(w.name||'Unnamed')}</h3><p class="mono">${esc(w.url||'')}</p></div><span class="pill ${w.enabled?'green':'rose'}">${w.enabled?'Enabled':'Disabled'}</span><button class="button small" data-test-wh="${w.id}">Test</button><button class="button small danger" data-delete-resource="n8n_webhooks" data-id="${w.id}">Delete</button></div>`).join(''):'<div class="empty">No webhooks registered. Add one to start notifying n8n on approvals.</div>'}</section></div><section class="panel section-gap"><h2>Getting started with n8n</h2><div class="status-line"><span>1</span><span>Import <code>samples/n8n-workflow-telegram-notify.json</code> into your n8n</span></div><div class="status-line"><span>2</span><span>Create a Telegram bot via <strong>@BotFather</strong> and copy your bot token</span></div><div class="status-line"><span>3</span><span>Create a Telegram Chat ID via <strong>@userinfobot</strong> or a group</span></div><div class="status-line"><span>4</span><span>Enable the n8n workflow and copy its webhook URL</span></div><div class="status-line"><span>5</span><span>Add the webhook URL in Personal OS → n8n automation page</span></div><div class="status-line"><span>6</span><span>Approve an action — Telegram receives the notification</span></div></section>`)}
async function auditPage(){state.audit=await api('/audit');return shell(head('AUDIT LOG','Evidence that cannot be quietly rewritten.','Operational events are appended to a SHA-256 hash chain. Corrections create new events.')+`<section class="panel">${state.audit.length?state.audit.map(e=>`<div class="audit-row"><span>#${e.seq}</span><strong>${esc(e.event_type)}</strong><span><span class="mono">${esc(e.event_hash.slice(0,18))}…</span><br>${esc(e.created_at)}</span></div>`).join(''):'<div class="empty">No activity yet.</div>'}</section>`)}
async function activityPage(){const items=await api('/activity');const typeIcon={'message':'◎','action':'⚡'};const typeColor={'message':'blue','action':'yellow'};return shell(head('ACTIVITY FEED','Everything your agents are doing.','Unified stream of messages, actions, approvals, uploads, and system events — newest first.')+`<div class="activity-list">${items.length?items.map(it=>`<div class="activity-item ${typeColor[it.type]||'gray'}"><span class="activity-icon">${typeIcon[it.type]||'•'}</span><div class="activity-body"><span class="activity-agent">${esc(it.agent)}</span><span class="activity-type">${esc(it.type)}</span><span class="activity-detail">${esc(it.detail||it.content||'')}</span></div><span class="activity-time">${esc(it.created_at)}</span></div>`).join(''):'<div class="empty">No activity recorded yet. Start a conversation with an agent.</div>'}</div>`)}
async function connectorsPage(){const status=await api('/connectors/status');const rows=Object.entries(status).map(([name,info])=>`<div class="connector-row"><div class="connector-icon ${info.connected?'green':'rose'}">${info.connected?'✓':'✗'}</div><div class="connector-body"><h3>${esc(name.charAt(0).toUpperCase()+name.slice(1))}</h3><p>${esc(info.note||(info.connected?'Connected':'Not connected'))}</p>${info.vault_path?`<code class="muted">${esc(info.vault_path)}</code>`:''}</div><span class="pill ${info.connected?'green':'rose'}">${info.connected?'Connected':'Disconnected'}</span></div>`).join('');return shell(head('CONNECTORS','Obsidian, Notion, Hermes, and more.','Live status of integrations that move data between your tools and Personal OS.')+`<section class="panel">${rows}</section><section class="panel section-gap"><h2>How it works</h2><div class="status-line"><span>Hermes</span><span>Personal OS backend · always connected</span></div><div class="status-line"><span>Obsidian</span><span>Vault at ~/Documents/Hermes Obsidian/Hermes · filesystem access</span></div><div class="status-line"><span>Notion</span><span>OAuth MCP active in Hermes · REST API needs NOTION_API_KEY</span></div></section>`)}
async function delegationsPage(){
  const [all,pending]=await Promise.all([api('/delegations'),api('/delegations/pending')]);
  const agents=state.agents;
  const byStatus=(items,status)=>items.filter(d=>d.status===status);
  const pendingRows=pending.length?pending.map(d=>`<div class="delegation-card ${d.status}">
    <div class="delegation-target"><span class="pill blue">@${esc(d.target_agent)}</span></div>
    <p class="delegation-instruction">${esc(d.instruction)}</p>
    <div class="delegation-meta"><span>${esc(d.task_type)}</span><span>${esc(d.created_at)}</span></div>
    <div class="delegation-actions">
      <button class="button small primary" data-delegate-do="${d.id}">Assign & start</button>
      <button class="button small" data-delegate-dismiss="${d.id}">Dismiss</button>
    </div>
  </div>`).join(''):'<div class="empty"><strong>No pending tasks</strong><p>CEO will create delegations when you ask it to assign work to agents.</p></div>';
  return shell(head('DELEGATIONS','CEO assigns work to specialists.','Tasks delegated from the CEO to Job, Dad, and Tech News agents — with your approval before anything leaves.')+`<div class="delegations-pending">
    <h2 class="section-title">Pending tasks <span class="pill">${pending.length}</span></h2>
    ${pendingRows}
  </div><div class="delegations-history">
    <h2 class="section-title">All delegations</h2>
    <div class="panel">
      ${all.length?all.slice(0,20).map(d=>`<div class="delegation-row"><span class="pill ${d.status==='done'?'green':d.status==='pending'?'blue':'orange'}">${esc(d.status)}</span><span>@${esc(d.target_agent)}</span><span class="delegation-type">${esc(d.task_type)}</span><span class="muted">${esc(d.created_at)}</span></div>`).join(''):'<p class="muted">No delegations yet.</p>'}
    </div>
  </div>`);
}
function reportPage(){return shell(head('ENGINEERING HANDOFF','Built to be understood.','Architecture, safety boundaries, setup, testing, and continuation decisions are documented in the repository.')+`<div class="grid two"><section class="panel"><h2>Documents</h2><div class="row"><div class="row-main"><h3>Engineering report</h3><p>Architecture, requirements mapping, threat model, data model, limitations, and roadmap.</p></div><a class="button small" href="/docs/ENGINEERING-REPORT.md" target="_blank">Open</a></div><div class="row"><div class="row-main"><h3>README</h3><p>Start, test, backup, Hermes integration, and account setup instructions.</p></div><a class="button small" href="/README.md" target="_blank">Open</a></div></section><aside class="panel"><h2>Implementation status</h2><div class="status-line"><span>Python + SQLite core</span><span class="pill green">Working</span></div><div class="status-line"><span>Agent chats</span><span class="pill green">Offline working</span></div><div class="status-line"><span>n8n integration</span><span class="pill green">Webhook POST on approval</span></div><div class="status-line"><span>Hermes adapter</span><span class="pill yellow">Opt-in</span></div><div class="status-line"><span>External accounts</span><span class="pill rose">Authorization needed</span></div><div class="status-line"><span>Protected external actions</span><span class="pill rose">Disabled</span></div></aside></div>`)}
async function render(){
if(state.current==='overview'){state.uploads=await api('/uploads');$('#content').innerHTML=overview();bindOverview()}else if(state.current==='agents')$('#content').innerHTML=agentsPage();else if(state.current==='agent-panel'){$('#content').innerHTML=await agentPanel();await loadAgentPanel()}else if(['ceo','job','dad'].includes(state.current))$('#content').innerHTML=await agentWorkspace(state.current);else if(state.current==='tech-news')$('#content').innerHTML=await techPage();else if(state.current==='inbox'){$('#content').innerHTML=await inboxPage();bindInbox()}else if(state.current==='approvals')$('#content').innerHTML=approvals();else if(state.current==='n8n')$('#content').innerHTML=await n8nPage();else if(state.current==='activity')$('#content').innerHTML=await activityPage();else if(state.current==='connectors')$('#content').innerHTML=await connectorsPage();else if(state.current==='delegations')$('#content').innerHTML=await delegationsPage();else if(state.current==='tasks'){$('#content').innerHTML=await tasksPage();bindPlanning()}else if(state.current==='schedules'){$('#content').innerHTML=await schedulesPage();bindPlanning()}else if(resourceMeta[state.current])$('#content').innerHTML=await resourcePage(state.current);else if(state.current==='files')$('#content').innerHTML=await filesPage();else if(state.current==='browsers')$('#content').innerHTML=browsersPage();else if(state.current==='models')$('#content').innerHTML=modelsPage();else if(state.current==='audit')$('#content').innerHTML=await auditPage();else if(state.current==='report')$('#content').innerHTML=reportPage();else if(state.current==='telegram')$('#content').innerHTML=await telegramPage();bind()}
function modal(title,kicker,body){$('#modal-title').textContent=title;$('#modal-kicker').textContent=kicker;$('#modal-body').innerHTML=body;$('#modal').showModal()}
function agentForm(a={}){modal(a.slug?'Edit agent':'Add agent','AGENT DIRECTORY',`<form id="agent-form"><label>Name</label><input name="name" required value="${esc(a.name||'')}"><label>Slug</label><input name="slug" ${a.slug?'readonly':''} value="${esc(a.slug||'')}"><label>Purpose</label><textarea name="purpose">${esc(a.purpose||'')}</textarea><div class="form-row"><div><label>Provider</label><input name="model_provider" value="${esc(a.model_provider||'offline')}"></div><div><label>Model ID</label><input name="model_id" value="${esc(a.model_id||'deterministic')}"></div></div><label>Tools (comma-separated)</label><input name="tools" value="${esc((a.tools||[]).join(', '))}"><label>Skills (comma-separated)</label><input name="skills" value="${esc((a.skills||[]).join(', '))}"><label><input style="width:auto" type="checkbox" name="free_only" ${a.free_only?'checked':''}> Free/local only</label><div class="actions"><button class="button primary">Save agent</button></div></form>`);$('#agent-form').onsubmit=async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(e.target));d.tools=d.tools.split(',').map(x=>x.trim()).filter(Boolean);d.skills=d.skills.split(',').map(x=>x.trim()).filter(Boolean);d.free_only=!!e.target.free_only.checked;if(a.slug)await api(`/agents/${a.slug}`,{method:'PATCH',body:JSON.stringify(d)});else await api('/agents',{method:'POST',body:JSON.stringify(d)});$('#modal').close();toast('Agent saved');await go('agents')}}

function quickAgentModal(){
  const brains=[
    ['ollama','Ollama (local, free)'],
    ['claude-code','Claude Code (Anthropic subscription)'],
    ['codex-cli','Codex CLI (ChatGPT subscription)'],
    ['offline','Offline (deterministic)']
  ];
  const html=`<div class="quick-agent-wrap">
    <p class="quick-agent-sub">Give your agent a name and purpose. Slug and brain are set automatically.</p>
    <form id="qa-form">
      <div class="qa-field">
        <label>Agent name <span class="req">*</span></label>
        <input name="name" placeholder="e.g. Research Assistant, Sales Bot" required autofocus>
      </div>
      <div class="qa-field">
        <label>One-line purpose <span class="req">*</span></label>
        <textarea name="purpose" placeholder="e.g. Searches the web for competitive intel and summarises it" rows="2" required></textarea>
      </div>
      <div class="qa-field">
        <label>Brain</label>
        <div class="qa-brains">
          ${brains.map(([v,l])=>`<label class="qa-brain">
            <input type="radio" name="model_provider" value="${v}" ${v==='ollama'?'checked':''}>
            <span>${l}</span>
          </label>`).join('')}
          <div class="qa-model-row" id="qa-model-row" style="display:none">
            <label>Model</label>
            <input name="model_id" id="qa-model-input" placeholder="e.g. qwen2.5:7b">
          </div>
        </div>
      </div>
      <div class="qa-actions">
        <button type="submit" class="btn-primary">Create agent</button>
        <button type="button" class="btn-ghost" onclick="document.getElementById('modal').close()">Cancel</button>
      </div>
    </form>
  </div>`;
  modal('＋ Quick create agent','AGENT DIRECTORY',html);
  const form=$('#qa-form');
  const modelRow=$('#qa-model-row');
  const modelInput=$('#qa-model-input');
  form.querySelectorAll('input[name="model_provider"]').forEach(r=>{
    r.onchange=()=>{
      const show=r.value==='ollama'||r.value==='claude-code'||r.value==='codex-cli';
      modelRow.style.display=show?'block':'none';
      if(r.value==='ollama')modelInput.value='qwen2.5:7b';
      else if(r.value==='claude-code')modelInput.value='default';
      else if(r.value==='codex-cli')modelInput.value='default';
    };
  });
  form.onsubmit=async e=>{
    e.preventDefault();
    const fd=new FormData(e.target);
    const name=fd.get('name').trim();
    if(!name)return;
    const slug=name.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');
    const provider=fd.get('model_provider');
    const model_id=(modelRow.style.display!=='none'&&modelInput.value.trim())?modelInput.value.trim():'deterministic';
    const purpose=fd.get('purpose').trim();
    try{
      await api('/agents',{method:'POST',body:JSON.stringify({name,slug,purpose,model_provider:provider,model_id})});
      $('#modal').close();
      toast('Agent created');
      await go('agents');
    }catch(err){toast(err.message);}
  };
}
function resourceForm(kind,item={}){const m=resourceMeta[kind];modal(item.id?'Edit item':`Add ${m.title}`,'SYSTEM DIRECTORY',`<form id="resource-form">${m.fields.map(([key,label,type])=>type==='checkbox'?`<label><input style="width:auto" type="checkbox" name="${key}" ${item[key]?'checked':''}> ${label}</label>`:`<label>${label}</label>${['description','notes','prompt'].includes(key)?`<textarea name="${key}">${esc(item[key]||'')}</textarea>`:`<input name="${key}" value="${esc(item[key]||'')}">`}`).join('')}<div class="actions"><button class="button primary">Save</button></div></form>`);$('#resource-form').onsubmit=async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(e.target));const cb=m.fields.find(x=>x[2]==='checkbox');if(cb)d[cb[0]]=!!e.target[cb[0]].checked;await api(`/resources/${kind}${item.id?'/'+item.id:''}`,{method:item.id?'PATCH':'POST',body:JSON.stringify(d)});$('#modal').close();toast('Saved');await go(kind)}}
async function launchBrowser(slug,url){await api(`/browser/${slug}/open`,{method:'POST',body:JSON.stringify({url})});toast(`${agent(slug).name} browser opened in its own Chrome profile`)}
// ── Inbox: company replies caught by the email trigger ──────────────────────
const inboxState={items:[],summary:null,filter:'open',open:{}};
const INBOX_CATEGORIES={
 interview_invite:['green','Interview invitation'],
 assessment:['blue','Assessment / test'],
 offer:['green','Offer'],
 rejection:['red','Rejection'],
 document_request:['orange','Documents requested'],
 acknowledgement:['blue','Application acknowledged'],
 recruiter_outreach:['purple','Recruiter outreach'],
 other:['blue','Uncategorised']
};
const INBOX_STATUS={
 new:['orange','Needs triage'],drafted:['blue','Draft ready'],
 awaiting_approval:['orange','Waiting for your approval'],approved:['blue','Approved — awaiting send'],
 sent:['green','Sent (confirmed)'],denied:['red','Denied'],archived:['blue','Archived']
};
const INBOX_OPEN=['new','drafted','awaiting_approval','approved'];
function inboxWhen(value){if(!value)return '';const d=new Date(value);return isNaN(d)?value:d.toLocaleString()}
function inboxPill(map,key){const [tone,label]=map[key]||['blue',key||'—'];return `<span class="pill ${tone}">${esc(label)}</span>`}
async function inboxPage(){
 const [items,summary]=await Promise.all([api('/inbox'),api('/inbox/summary')]);
 inboxState.items=items;inboxState.summary=summary;
 const filtered=inboxState.filter==='open'?items.filter(e=>INBOX_OPEN.includes(e.status))
   :inboxState.filter==='all'?items:items.filter(e=>e.status===inboxState.filter);
 const waiting=items.filter(e=>e.status==='awaiting_approval').length;
 const setup=summary.ingest_configured?'':`<div class="notice section-gap"><strong>The email trigger is not armed yet.</strong> Set <code>AGENTICOS_INGEST_TOKEN</code> in your environment, restart the server, then point the n8n workflow at <code>POST /api/inbox/ingest</code> with the header <code>X-AgenticOS-Token</code>. Full steps are in <code>docs/INBOX-EMAIL-TRIGGER.md</code>.</div>`;
 const filters=[['open',`Open (${items.filter(e=>INBOX_OPEN.includes(e.status)).length})`],['awaiting_approval',`Waiting (${waiting})`],['sent',`Sent (${items.filter(e=>e.status==='sent').length})`],['archived','Archived'],['all',`All (${items.length})`]];
 return shell(head('INBOX','Company replies land here, never in your outbox.',
   'n8n watches the mailbox and posts each reply in. AgenticOS classifies it locally, drafts an answer, and holds it until you approve. Sending happens in n8n, and the reply is only marked sent once it reports back a real message id.')
  +setup
  +`<div class="inbox-filters section-gap">${filters.map(([id,label])=>`<button class="button small ${inboxState.filter===id?'primary':''}" data-inbox-filter="${id}">${esc(label)}</button>`).join('')}</div>`
  +(filtered.length?filtered.map(inboxCard).join(''):`<div class="empty"><strong>Nothing here yet.</strong><p>Replies appear the moment the n8n workflow forwards one. Nothing is ever fetched or sent without you.</p></div>`));
}
function inboxCard(e){
 const expanded=!!inboxState.open[e.id];
 const signals=(e.signals||[]).length?`<p class="muted inbox-signals">Matched: ${(e.signals||[]).map(s=>`<code>${esc(s)}</code>`).join(' · ')}</p>`:'';
 const automated=/no-?reply|donotreply|do-?not-?reply/i.test(e.from_address||'');
 const editable=['new','drafted','denied'].includes(e.status)&&!automated;
 const canDraft=e.status!=='sent'&&e.status!=='archived'&&!automated;
 const body=`<div class="payload inbox-body" dir="auto">${esc(e.body||'(empty message)')}</div>`;
 let controls='';
 if(automated){
  controls=`<p class="muted">Automated sender — a reply to <span class="mono">${esc(e.from_address)}</span> would not reach anyone, so nothing was drafted.</p>
    <div class="actions"><button class="button small" data-inbox-archive="${e.id}">Archive</button></div>`;
 }else if(editable){
  controls=`<div class="actions">
    <button class="button small" data-inbox-draft="${e.id}">Redraft offline</button>
    <button class="button small" data-inbox-model="${e.id}">Improve with local model</button>
    <button class="button primary" data-inbox-queue="${e.id}">Send for approval</button>
    <button class="button small" data-inbox-archive="${e.id}">Archive</button></div>`;
 }else if(e.status==='awaiting_approval'){
  controls=`<div class="actions">
    <button class="button primary" data-inbox-decide="approved" data-action="${esc(e.action_id||'')}">Approve this exact reply</button>
    <button class="button danger" data-inbox-decide="denied" data-action="${esc(e.action_id||'')}">Deny</button></div>
    <p class="muted">Approving hands the exact text above to your n8n workflow. It is marked sent only when n8n reports back the provider's message id.</p>`;
 }else if(e.status==='approved'){
  controls=`<p class="muted">Approved and handed to n8n. Waiting for a delivery confirmation — not sent yet as far as this OS knows.</p>`;
 }else if(e.status==='sent'){
  controls=`<p class="muted">Delivered ${esc(inboxWhen(e.replied_at))} · provider id <span class="mono">${esc(e.provider_message_id)}</span></p>`;
 }
 return `<section class="panel inbox-card section-gap">
  <div class="panel-head">
    <div><p class="eyebrow">${esc(e.company||e.from_address||'unknown sender')}</p>
      <h2>${esc(e.subject||'(no subject)')}</h2>
      <p class="muted">${esc(e.from_name||'')} &lt;${esc(e.from_address)}&gt; · ${esc(inboxWhen(e.received_at))}</p></div>
    <div class="inbox-tags">${inboxPill(INBOX_CATEGORIES,e.category)}${inboxPill(INBOX_STATUS,e.status)}
      <span class="mono">${Math.round((e.confidence||0)*100)}% confident</span></div>
  </div>
  ${signals}
  <button class="button small" data-inbox-toggle="${e.id}">${expanded?'Hide original message':'Show original message'}</button>
  ${expanded?body:''}
  ${canDraft?`<div class="inbox-draft">
    ${e.draft_body?'':`<p class="muted">No reply was drafted — nothing here needs answering. Write one yourself if you disagree.</p>`}
    <label>Reply subject</label><input id="inbox-subject-${e.id}" dir="auto" value="${esc(e.draft_subject)}" ${editable?'':'readonly'}>
    <label>Reply body ${e.draft_source?`<span class="muted">· drafted by ${esc(e.draft_source)}</span>`:''}</label>
    <textarea id="inbox-body-${e.id}" dir="auto" rows="12" ${editable?'':'readonly'}>${esc(e.draft_body)}</textarea>
    <p class="muted">Anything still in [square brackets] is a fact this OS does not know. Fill it in yourself — approval is blocked while a placeholder remains.</p>
  </div>`:''}
  ${controls}
 </section>`;
}
function bindInbox(){
 $$('[data-inbox-filter]').forEach(b=>b.onclick=()=>{inboxState.filter=b.dataset.inboxFilter;go('inbox')});
 $$('[data-inbox-toggle]').forEach(b=>b.onclick=()=>{const id=b.dataset.inboxToggle;inboxState.open[id]=!inboxState.open[id];go('inbox')});
 $$('[data-inbox-draft]').forEach(b=>b.onclick=async()=>{
   b.disabled=true;try{const r=await api(`/inbox/${b.dataset.inboxDraft}/draft`,{method:'POST',body:JSON.stringify({})});toast(r.note||'Offline draft rebuilt');await go('inbox')}
   catch(err){toast(err.message);b.disabled=false}});
 $$('[data-inbox-model]').forEach(b=>b.onclick=async()=>{
   b.disabled=true;b.textContent='Thinking…';
   try{const r=await api(`/inbox/${b.dataset.inboxModel}/draft`,{method:'POST',body:JSON.stringify({use_model:true})});toast(r.note||'Draft improved by the local model');await go('inbox')}
   catch(err){toast(err.message);b.disabled=false;b.textContent='Improve with local model'}});
 $$('[data-inbox-queue]').forEach(b=>b.onclick=async()=>{
   const id=b.dataset.inboxQueue;
   const payload={subject:$(`#inbox-subject-${id}`).value,body:$(`#inbox-body-${id}`).value};
   b.disabled=true;
   try{await api(`/inbox/${id}/queue`,{method:'POST',body:JSON.stringify(payload)});toast('Sent to the review desk — approve it to release the reply');await loadBase();await go('inbox')}
   catch(err){toast(err.message);b.disabled=false}});
 $$('[data-inbox-decide]').forEach(b=>b.onclick=async()=>{
   if(!b.dataset.action)return toast('This reply has no approval card; redraft it first');
   b.disabled=true;
   try{await api(`/actions/${b.dataset.action}/decision`,{method:'POST',body:JSON.stringify({decision:b.dataset.inboxDecide})});
     toast(b.dataset.inboxDecide==='approved'?'Approved — n8n now has the reply':'Denied; nothing was sent');
     await loadBase();await go('inbox')}
   catch(err){toast(err.message);b.disabled=false}});
 $$('[data-inbox-archive]').forEach(b=>b.onclick=async()=>{
   await api(`/inbox/${b.dataset.inboxArchive}/archive`,{method:'POST',body:'{}'});toast('Archived');await go('inbox')});
}

function bind(){$$('[data-page]').forEach(b=>b.onclick=()=>go(b.dataset.page));$$('[data-open-agent]').forEach(b=>b.onclick=()=>go(b.dataset.openAgent));$$('[data-agent-tab]').forEach(b=>b.onclick=e=>{$$('.tab-btn').forEach(btn=>btn.classList.remove('active'));e.target.classList.add('active');const slug=b.dataset.agentTab;$$('.agent-tab-panel').forEach(p=>p.style.display='none');$(`#agent-panel-${slug}`).style.display='flex'});$$('[data-edit-agent]').forEach(b=>b.onclick=()=>agentForm(agent(b.dataset.editAgent)));if($('#add-agent'))$('#add-agent').onclick=()=>agentForm();if($('#quick-agent-btn'))$('#quick-agent-btn').onclick=quickAgentModal;if($('#chat-form'))$('#chat-form').onsubmit=async e=>{e.preventDefault();const btn=e.target.querySelector('button');btn.disabled=true;btn.textContent='Thinking…';try{await api(`/agents/${state.current}/messages`,{method:'POST',body:JSON.stringify({content:$('#chat-text').value,target_agent:$('#chat-target')?.value||null})});await go(state.current)}catch(err){toast(err.message);btn.disabled=false}};if($('#chat-text')){$('#chat-text').parentElement.insertAdjacentHTML('beforeend',`<div class="voice-bar"><button type="button" id="stt-btn" class="icon-button" title="Hold to speak">🎤</button><button type="button" id="tts-btn" class="icon-button" title="Read last reply aloud">🔊</button></div>`);const sttBtn=$('#stt-btn'),ttsBtn=$('#tts-btn'),chatText=$('#chat-text');let sttHold=false;sttBtn.addEventListener('mousedown',()=>{sttHold=true;sttStart('en-US',t=>{chatText.value=(chatText.value+t).trim()},e=>toast('STT: '+e))});sttBtn.addEventListener('mouseup',()=>{sttHold=false;sttStop()});sttBtn.addEventListener('mouseleave',()=>{if(sttHold){sttHold=false;sttStop()}});ttsBtn.onclick=()=>{const last=$('.message.assistant:last-child');if(last)tts(last.textContent);else toast('No reply to read')}}$$('[data-browser]').forEach(b=>b.onclick=()=>launchBrowser(b.dataset.browser,'about:blank'));$$('[data-browser-url]').forEach(b=>b.onclick=()=>launchBrowser(b.dataset.browserUrl,$('#browser-url').value));$$('[data-browser-input]').forEach(b=>b.onclick=()=>launchBrowser(b.dataset.browserInput,$(`#url-${b.dataset.browserInput}`).value));$$('[data-add-resource]').forEach(b=>b.onclick=()=>resourceForm(b.dataset.addResource));$$('[data-edit-resource]').forEach(b=>b.onclick=()=>resourceForm(b.dataset.editResource,state.resources[b.dataset.editResource].find(x=>x.id===b.dataset.id)));$$('[data-delete-resource]').forEach(b=>b.onclick=async()=>{if(confirm('Delete this local record?')){await api(`/resources/${b.dataset.deleteResource}/${b.dataset.id}`,{method:'DELETE'});go(b.dataset.deleteResource)}});$$('[data-save-model]').forEach(b=>b.onclick=async()=>{const s=b.dataset.saveModel;await api(`/agents/${s}`,{method:'PATCH',body:JSON.stringify({model_provider:$(`#provider-${s}`).value,model_id:$(`#model-${s}`).value,free_only:$(`#free-${s}`).checked})});toast('Model routing saved');await go('models')});$$('[data-decision]').forEach(b=>b.onclick=async()=>{await api(`/actions/${b.dataset.action}/decision`,{method:'POST',body:JSON.stringify({decision:b.dataset.decision})});toast(`Action ${b.dataset.decision}`);await go('approvals')});if($('#action-form'))$('#action-form').onsubmit=async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(e.target));try{d.payload=JSON.parse(d.payload)}catch{return toast('Action details must be valid JSON')}await api('/actions',{method:'POST',body:JSON.stringify(d)});toast('Review item created');await go('approvals')};if($('#upload-open'))$('#upload-open').onclick=()=>{modal('Upload context','LOCAL FILES',`<form id="upload-form"><label>Give file to</label><select name="agent_slug">${state.agents.map(a=>`<option value="${a.slug}">${esc(a.name)}</option>`).join('')}</select><label>File (maximum 25 MB)</label><input type="file" name="file" required><div class="actions"><button class="button primary">Upload locally</button></div></form>`);$('#upload-form').onsubmit=async e=>{e.preventDefault();const d=new FormData(e.target);await api('/upload',{method:'POST',body:d});$('#modal').close();toast('File uploaded locally');go('files')}};if($('#add-news'))$('#add-news').onclick=()=>{modal('Add verified story','TECH NEWS',`<form id="news-form"><label>Title</label><input name="title" required><label>Summary</label><textarea name="summary"></textarea><label>Source URL</label><input name="url" type="url" required><div class="actions"><button class="button primary">Add story</button></div></form>`);$('#news-form').onsubmit=async e=>{e.preventDefault();await api('/news',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});$('#modal').close();go('tech-news')}};if($('#fetch-feed'))$('#fetch-feed').onclick=()=>{modal('Fetch RSS or Atom feed','TECH NEWS',`<form id="feed-form"><label>Feed name</label><input name="name" value="Tech feed"><label>Feed URL</label><input name="url" type="url" required placeholder="https://example.com/feed.xml"><div class="actions"><button class="button primary">Fetch now</button></div></form>`);$('#feed-form').onsubmit=async e=>{e.preventDefault();const r=await api('/news/fetch',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});$('#modal').close();toast(`${r.added} stories added`);go('tech-news')}};$$('[data-script]').forEach(b=>b.onclick=async()=>{const s=await api(`/news/${b.dataset.script}/script`,{method:'POST',body:'{}'});$(`#script-${b.dataset.script}`).innerHTML=`<div class="script-output">${esc(s.script)}</div><button class="button small" data-copy-script>Copy script</button>`;$(`#script-${b.dataset.script} [data-copy-script]`).onclick=()=>navigator.clipboard.writeText(s.script).then(()=>toast('Script copied'))});if($('#n8n-add-wh'))$('#n8n-add-wh').onclick=()=>resourceForm('n8n_webhooks');if($('#n8n-refresh-status'))$('#n8n-refresh-status').onclick=()=>go('n8n');$$('[data-test-wh]').forEach(b=>b.onclick=async()=>{const r=await api(`/n8n/webhooks/${b.dataset.testWh}/test`,{method:'POST'});toast(r.ok?`Test OK (${r.status})`:`Test failed: ${r.error}`)});if($('#tg-check'))$('#tg-check').onclick=telegramCheck;$$('[data-tg-unlink]').forEach(b=>b.onclick=async()=>{if(confirm('Unlink this Telegram chat?')){await api(`/telegram/unlink`,{method:'POST',body:JSON.stringify({chat_id:b.dataset.tgUnlink})});await go('telegram')}});$$('[data-delegate-do]').forEach(b=>b.onclick=async()=>{const d=b.dataset.delegateDo;const all=await api('/delegations');const del=all.find(x=>x.id===d);if(!del){toast('Task not found');return}await api(`/delegations/${d}`,{method:'PATCH',body:JSON.stringify({status:'in_progress'})});toast(`Opening @${del.target_agent} with task…`);go(`agent-panel`);setTimeout(()=>openAgent(del.target_agent),300)});$$('[data-delegate-dismiss]').forEach(b=>b.onclick=async()=>{await api(`/delegations/${b.dataset.delegateDismiss}`,{method:'PATCH',body:JSON.stringify({status:'dismissed'})});toast('Task dismissed');await go('delegations')})}
function commandOpen(){const items=groups.flatMap(g=>g[1]);const renderResults=()=>{const q=$('#command-input').value.toLowerCase();$('#command-results').innerHTML=items.filter(x=>x[2].toLowerCase().includes(q)).map(x=>`<button class="command-result" data-command-page="${x[0]}">${x[1]} &nbsp; ${x[2]}</button>`).join('');$$('[data-command-page]').forEach(b=>b.onclick=()=>{$('#command').close();go(b.dataset.commandPage)})};$('#command-input').value='';renderResults();$('#command').showModal();$('#command-input').focus();$('#command-input').oninput=renderResults}
$('#menu-button').onclick=()=>$('#sidebar').classList.toggle('open');$('#command-button').onclick=commandOpen;document.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();commandOpen()}});window.addEventListener('hashchange',()=>{const p=location.hash.slice(1);if(p&&p!==state.current)go(p)});initPageAgent();go(location.hash.slice(1)||'overview');
