const brainLabels={'codex-cli':'Codex','claude-code':'Claude Code'};
const agentUI={active:'ceo',messages:{},drafts:{},busy:new Set(),errors:{},brains:{}};

function openAgent(slug){agentUI.active=slug;return go('agent-panel')}
function brainOptions(selected){return `<option value="" ${!brainLabels[selected]?'selected':''}>Choose a brain</option>`+Object.entries(brainLabels).map(([value,label])=>`<option value="${value}" ${selected===value?'selected':''}>${label}</option>`).join('')}
function brainNote(provider){const info=agentUI.brains[provider];return info?.authenticated?'Signed in · account limits apply':info?.note||'Sign-in status not checked'}
function chatMessages(slug){
  const messages=agentUI.messages[slug]||[];
  return messages.length?messages.map(m=>`<article class="agent-chat-message ${m.role==='user'?'from-user':'from-agent'}"><span>${m.role==='user'?'You':esc(agent(slug)?.name||slug)}</span><div dir="auto">${esc(m.content)}</div></article>`).join(''):`<div class="agent-chat-empty"><p class="eyebrow">A CONVERSATION, NOT A COMMAND LINE</p><h2>What would you like to work on?</h2><p>Ask a question, work through an idea, or draft something together. This conversation stays in ${esc(agent(slug)?.name||slug)}’s workspace.</p></div>`;
}
function brainSettings(a){
  return `<form data-brain-form="${esc(a.slug)}"><label for="brain-${esc(a.slug)}">AI brain</label><select id="brain-${esc(a.slug)}" name="provider" required>${brainOptions(a.model_provider)}</select><p class="agent-small" data-brain-note>${esc(brainNote(a.model_provider))}</p><label for="brain-model-${esc(a.slug)}">Model <span class="muted">(optional)</span></label><input id="brain-model-${esc(a.slug)}" name="model" value="${esc(brainLabels[a.model_provider]&&a.model_id!=='default'?a.model_id:'')}" placeholder="Provider default" maxlength="120"><button class="button" type="submit">Save brain</button><p class="agent-small" role="status" data-brain-result></p></form>`;
}
async function unifiedAgentsPage(){
  agentUI.brains=await api('/brains');
  if(!agent(agentUI.active))agentUI.active=state.agents[0]?.slug;
  const a=agent(agentUI.active);
  if(!a)return shell(head('AGENTS','No agents yet.','Add an agent to start a conversation.',`<button class="button primary" data-page="agents">Agent directory</button>`));
  agentUI.messages[a.slug]=await api(`/agents/${encodeURIComponent(a.slug)}/messages`);
  const busy=agentUI.busy.has(a.slug);
  const tasks=(await api('/resources/tasks')).filter(t=>t.agent===a.slug&&t.status!=='done');
  return shell(`<div class="agent-workspace">${head('YOUR TEAM','One desk. Your whole team.','Separate conversations, with Claude Code or Codex behind each one.',`<button class="button" data-page="agents">Manage agents</button>`)}
    <div class="agent-workspace-tabs" role="tablist" aria-label="Agent conversations">${state.agents.map(x=>`<button id="agent-tab-${esc(x.slug)}" role="tab" aria-selected="${x.slug===a.slug}" aria-controls="active-agent-chat" tabindex="${x.slug===a.slug?'0':'-1'}" data-select-agent="${esc(x.slug)}"><span class="agent-initial">${esc(x.name[0])}</span><span>${esc(x.name)}<small>${esc(brainLabels[x.model_provider]||'Choose a brain')}${agentUI.busy.has(x.slug)?' · replying':''}</small></span></button>`).join('')}</div>
    <div class="agent-workspace-grid" id="active-agent-chat" role="tabpanel" aria-labelledby="agent-tab-${esc(a.slug)}">
      <section class="agent-chat-window"><header class="agent-chat-header"><div><h2>${esc(a.name)}</h2><p>${esc(a.purpose)}</p></div><span class="pill">${esc(brainLabels[a.model_provider]||'Not configured')} · chat & drafts</span></header>
        <div class="agent-chat-log" id="agent-chat-log" role="log" aria-live="polite" aria-label="Conversation">${chatMessages(a.slug)}</div>
        <form class="agent-chat-compose" data-agent-composer="${esc(a.slug)}"><label for="agent-chat-input">Message ${esc(a.name)}</label><textarea id="agent-chat-input" name="content" rows="3" maxlength="20000" required placeholder="Talk naturally. English or Arabic…" ${busy?'disabled':''}>${esc(agentUI.drafts[a.slug]||'')}</textarea><div class="agent-compose-footer"><span class="agent-small">Your chat history is saved locally. Messages go to the selected AI provider.</span><button class="button primary" type="submit" ${busy?'disabled':''}>${busy?'Replying…':'Send message'}</button></div><p class="agent-chat-error" role="status">${esc(agentUI.errors[a.slug]||'')}</p></form>
      </section>
      <aside class="agent-workspace-inspector"><section class="panel"><p class="eyebrow">THIS AGENT’S BRAIN</p>${brainSettings(a)}</section>
        <section class="panel"><div class="panel-head"><h2>To do</h2><button class="button small" data-page="tasks">View list</button></div>${tasks.length?tasks.slice(0,4).map(t=>`<div class="agent-task-preview">${esc(t.name)}<small>${esc(t.status||'todo')}</small></div>`).join(''):'<p class="muted">No open to-dos assigned yet.</p>'}<button class="button" data-page="schedules">Plan a schedule</button></section>
        <p class="agent-small">Chat and drafting are enabled here. Browser control, email sending, and scheduled execution are not connected to this chat. No automatic actions or provider fallback.</p>
      </aside>
    </div></div>`);
}
async function brainsPage(){
  agentUI.brains=await api('/brains');
  return shell(head('AI BRAINS','Choose who you think with.','Uses your existing CLI sign-ins. No API-key setup; subscription limits still apply.')+`<div class="resource-grid">${state.agents.map(a=>`<section class="panel"><h2>${esc(a.name)}</h2>${brainSettings(a)}</section>`).join('')}</div><p class="notice section-gap">Switching brains preserves this agent’s locally saved chat history. It will be sent to the new provider on your next message. No separately billed API fallback is enabled.</p>`);
}
function bindAgentWorkspace(){
  $$('[data-select-agent]').forEach(button=>{
    button.onclick=()=>openAgent(button.dataset.selectAgent);
    button.onkeydown=event=>{
      const tabs=$$('[data-select-agent]');let index=tabs.indexOf(button);
      if(event.key==='ArrowRight')index=(index+1)%tabs.length;
      else if(event.key==='ArrowLeft')index=(index-1+tabs.length)%tabs.length;
      else if(event.key==='Home')index=0;
      else if(event.key==='End')index=tabs.length-1;
      else return;
      event.preventDefault();const slug=tabs[index].dataset.selectAgent;
      openAgent(slug).then(()=>document.getElementById(`agent-tab-${slug}`)?.focus());
    };
  });
  $$('[data-brain-form]').forEach(form=>{
    const provider=form.elements.namedItem('provider');
    provider.onchange=()=>{form.querySelector('[data-brain-note]').textContent=brainNote(provider.value);form.elements.namedItem('model').value=''};
    form.onsubmit=async event=>{
      event.preventDefault();const button=form.querySelector('button'),result=form.querySelector('[data-brain-result]');
      button.disabled=true;result.textContent='Saving…';
      const slug=form.dataset.brainForm;
      try{
        if(agentUI.busy.has(slug))throw Error('Wait for this agent’s reply before switching its brain.');
        const saved=await api(`/agents/${encodeURIComponent(slug)}`,{method:'PATCH',body:JSON.stringify({model_provider:provider.value,model_id:form.elements.namedItem('model').value.trim()||'default'})});
        state.agents=state.agents.map(a=>a.slug===slug?saved:a);
        const check=await api('/agents');
        if(!check.some(a=>a.slug===slug&&a.model_provider===saved.model_provider&&a.model_id===saved.model_id))throw Error('Could not confirm the saved brain. Refresh and check.');
        result.textContent='Saved. Your next message uses '+brainLabels[saved.model_provider]+'.';
        if(state.current==='agent-panel')await go('agent-panel');
      }catch(error){result.textContent=error.message}finally{button.disabled=false}
    };
  });
  const form=$('[data-agent-composer]');
  if(!form)return;
  const slug=form.dataset.agentComposer,input=form.elements.namedItem('content');
  input.oninput=()=>{agentUI.drafts[slug]=input.value};
  form.onsubmit=async event=>{
    event.preventDefault();if(agentUI.busy.has(slug))return;
    const content=input.value.trim();if(!content)return;
    agentUI.drafts[slug]=content;agentUI.busy.add(slug);agentUI.errors[slug]='';
    const button=form.querySelector('button');button.disabled=true;input.disabled=true;button.textContent='Replying…';form.querySelector('[role="status"]').textContent='';
    try{
      const response=await api(`/agents/${encodeURIComponent(slug)}/messages`,{method:'POST',body:JSON.stringify({content})});
      const saved=await api(`/agents/${encodeURIComponent(slug)}/messages`);
      if(!saved.some(m=>m.id===response.assistant.id))throw Error('Reply received but could not confirm its saved history. Refresh before retrying.');
      agentUI.messages[slug]=saved;agentUI.drafts[slug]='';
    }catch(error){agentUI.errors[slug]=error.message}
    finally{
      agentUI.busy.delete(slug);
      if(state.current==='agent-panel'&&agentUI.active===slug){await go('agent-panel');const log=$('#agent-chat-log');if(log)log.scrollTop=log.scrollHeight;$('#agent-chat-input')?.focus()}
      else toast(agentUI.errors[slug]||`${agent(slug)?.name||slug} replied`);
    }
  };
  const log=$('#agent-chat-log');if(log)log.scrollTop=log.scrollHeight;
}
