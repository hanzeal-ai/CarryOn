/* No HTML interpolation of conversation content or external responses. */
const $ = id => document.getElementById(id);
const mobilePreview = new URLSearchParams(location.search).get('mobile') === '1';
const mobileLayout = window.matchMedia(mobilePreview ? 'all' : '(max-width:760px)');
if(mobilePreview){document.body.classList.add('mobile-preview');document.querySelector('link[href$="/style.css"]').media='not all';document.querySelector('link[href$="/mobile.css"]').media='all';}
function setThreadListOpen(open) {
  document.body.classList.toggle('threads-open', open);
  $('toggle-threads').setAttribute('aria-expanded', String(open));
  $('toggle-threads').textContent = open ? '收起会话列表' : '展开会话列表';
}
$('toggle-threads').onclick = () => setThreadListOpen(!document.body.classList.contains('threads-open'));
mobileLayout.addEventListener('change', () => setThreadListOpen(false));
document.addEventListener('keydown', event => {
  if(event.key === 'Escape' && mobileLayout.matches && document.body.classList.contains('threads-open')) {
    setThreadListOpen(false); $('toggle-threads').focus();
  }
});
let independentWorkspace = false, workspaceAccountReady = true;
let enabled = false, selected = null, controllerId = null, threads = [], offset = 0;
let refreshBusy = false, lastHistory = '', listVersion = 0, noticeTimer;
let subscription = null, streamReady = true;
let sideOpen=false, sideSelected=null, sideSignature='',sideHistoryLimit=40;
let sideComposeHistory=null, sideSending=false, sideDraftKey=null, sideJob=null;
const sideDrafts=new Map();
function resetSideComposer(){
  if(sideDraftKey)sideDrafts.set(sideDraftKey,$('side-prompt').value);
  sideDraftKey=sideOpen&&sideSelected?draftScope()+':'+selected+':'+sideSelected:null;
  sideComposeHistory=null;sideJob=null;$('side-prompt').value=sideDrafts.get(sideDraftKey)||'';$('side-send-status').textContent='';updateSideComposer();
}
function canSendSide(){return canWrite()&&sideOpen&&!!sideSelected&&!!sideComposeHistory&&sideComposeHistory.access?.canInteract===true&&sideComposeHistory.access?.nativeReady===true&&['idle','running','waiting'].includes(sideComposeHistory.status?.state)&&!sideSending;}
function updateSideComposer(){
  $('side-prompt').disabled=!canSendSide();$('side-send').disabled=!canSendSide();
  $('side-send').textContent=sideComposeHistory?.status?.state==='running'&&!$('side-prompt').value.trim()?'停止任务':'发送 ↑';
}
$('side-prompt').addEventListener('input',()=>{if(sideDraftKey)sideDrafts.set(sideDraftKey,$('side-prompt').value);updateSideComposer();});
$('side-prompt').addEventListener('keydown',event=>{if(event.key==='Enter'&&(event.metaKey||event.ctrlKey)){event.preventDefault();$('side-composer').requestSubmit();}});
$('side-composer').onsubmit=async event=>{
  event.preventDefault();if(!canSendSide())return;
  const parent=selected,target=sideSelected,scope=draftScope(),key=sideDraftKey,prompt=$('side-prompt').value;
  const current=()=>sideOpen&&selected===parent&&sideSelected===target&&draftScope()===scope;
  const stop=!prompt.trim()&&sideComposeHistory.status?.state==='running';if(!stop&&!prompt.trim())return;
  sideSending=true;updateSideComposer();$('side-send-status').textContent='正在提交…';
  try{
    const job=await client.sideAction(parent,target,stop?'interrupt':'compose',stop?{expectedTurnId:sideComposeHistory.controls.activeTurnId}:{prompt},current);
    if(!current())return;
    sideJob=job.id;
    if(['failed','uncertain'].includes(job.state))throw Error(job.error||'结果待核对，请勿重复发送');
    if(!stop&&$('side-prompt').value===prompt){$('side-prompt').value='';sideDrafts.set(key,'');}
    $('side-send-status').textContent=stop?'停止请求已提交':'已提交，等待同步';
  }catch(error){if(current())$('side-send-status').textContent=error.message;}
  finally{sideSending=false;updateSideComposer();}
};
const historyImageLoader=(thread,parent)=>(id,kind='images')=>api(parent?'/side-chats/'+encodeURIComponent(thread)+'/'+kind+'/'+id+'?parentId='+encodeURIComponent(parent):'/threads/'+encodeURIComponent(thread)+'/'+kind+'/'+id);
const SideTimeline=Timeline.create({runtime:'side-runtime',info:'side-info',source:'side-source'});
function closeSide(){
  sideOpen=false;sideSelected=null;sideSignature='';sideHistoryLimit=40;SideTimeline.reset();
  resetSideComposer();
  $('side-drawer').hidden=true;document.body.classList.remove('side-open');
  $('side-messages').replaceChildren();$('side-select').replaceChildren();$('side-discovery').textContent='';
}
function renderSides(data){
  const chats=data.chats||[];
  const old=$('side-select').value;
  $('side-select').replaceChildren(new Option('选择临时聊天',''),...chats.map(c=>new Option(`${c.title} · ${c.id.slice(-8)} · ${c.label}`,c.id)));
  $('side-select').value=sideSelected||old;
  $('side-discovery').textContent=data.error||(data.scanning?'正在核验已登记的临时聊天，找到后会自动显示。':chats.length?`已确认 ${chats.length} 个临时聊天。`:'未发现可读取的临时聊天。请先在 Codex App 打开；未登记或已过期的聊天可能无法发现。');
  if(sideSelected&&!chats.some(c=>c.id===sideSelected)){
    sideSelected=null;sideSignature='';SideTimeline.reset();$('side-messages').replaceChildren();
    resetSideComposer();
  }
  if(sideSelected){const c=chats.find(c=>c.id===sideSelected);if(c)$('side-runtime').textContent=c.label;}
}
let workspaceView='projects',workspaceProject=null,workspaceProjects=[],workspaceRevision=null;
let workspaceRefreshTimer;
const historyCache=new DisplayHistoryCache(), outgoingMessages=new Map();
function conversationKey(id){return draftScope()+':'+id;}
function renderOutgoing(scroll=false){
  const viewport=$('messages').closest('.mobile-chat-scroll')||$('messages');
  const atBottom=viewport.scrollHeight-viewport.scrollTop-viewport.clientHeight<100;
  $('messages').querySelectorAll('[data-outgoing]').forEach(n=>n.remove());
  for(const item of outgoingMessages.values()){
    if(item.scope!==draftScope()||item.threadId!==selected)continue;
    $('messages').querySelector('[data-state=empty]')?.remove();
    const row=node('article','message user');row.dataset.outgoing=item.id;
    row.append(node('div','text',item.prompt||'图片消息'));
    const labels={sending:'发送中…',preparing:'发送中…',dispatching:'发送中…',failed:'发送失败，请核对请求记录',uncertain:'结果待核对，请勿重复发送'};
    row.append(node('small','outgoing-status',labels[item.state]||(item.kind==='operation:queue-add'?'已排队，等待同步':'已接收，等待同步')));
    if(item.state==='failed'){const dismiss=node('button','quiet','清除提示');dismiss.onclick=()=>{outgoingMessages.delete(conversationKey(item.threadId)+':'+item.id);renderOutgoing();};row.append(dismiss);}
    $('messages').append(row);
  }
  if(scroll||atBottom)viewport.scrollTop=viewport.scrollHeight;
}
function reconcileOutgoing(jobs=[],history=null,scroll=false){
  for(const job of jobs){const key=conversationKey(job.threadId)+':'+job.id;const item=mergeOutgoingMessage(outgoingMessages.get(key),job,true);if(item)outgoingMessages.set(key,item);else outgoingMessages.delete(key);}
  if(history){for(const [key,item]of outgoingMessages){
    if(item.scope!==draftScope()||item.threadId!==history.thread.id)continue;
    const found=(history.timeline||[]).some(entry=>
      ['userMessage','steeringUserMessage'].includes(entry.type)&&
      ((item.clientMessageId&&[entry.nativeId,entry.clientMessageId].includes(item.clientMessageId))||
       (item.kind==='message'&&item.turnId&&entry.turnId===item.turnId)))||
      (history.queue?.messages||[]).some(entry=>item.clientMessageId&&entry.id===item.clientMessageId);
    if(found)outgoingMessages.delete(key);
  }}
  renderOutgoing(scroll);
}
const conversationDrafts=new Map();let activeDraftScope='';
let threadStatuses = {};
let threadFlags = {}, catalogRevision = null;
function updateThreadStatuses(values) {
  threadStatuses = values;
  if(workspaceView==='projects'&&enabled){renderProjects();return;}
  for(const badge of $('threads').querySelectorAll('[data-thread-status]')) {
    const state=values[badge.dataset.threadStatus] || {state:'unknown',label:'状态未知'};
    badge.textContent=state.label;
    badge.className='thread-status '+state.state;
  }
  const ids=threads.slice(0,100).map(t=>t.id);
  const count=state=>ids.filter(id=>values[id]?.state===state).length;
  const unknown=ids.filter(id=>!values[id] || ['loading','unknown'].includes(values[id].state)).length;
  $('thread-status-summary').textContent=enabled ? `已确认 ${count('running')} 个执行中 · ${count('waiting')} 个待处理`+(unknown?` · ${unknown} 个待确认`:'')+(threads.length>100?' · 状态仅订阅前 100 条':'') : '';
  window.MobileUI?.sync();
}
const states = {preparing:'检查会话中',dispatching:'正在投递',accepted:'Codex 已接收',completed:'已完成',failed:'发送失败',uncertain:'结果待确认',acknowledged:'已人工核对',interrupted:'已中断'};

function notice(text) {
  $('notice').textContent = text; $('notice').hidden = false;
  clearTimeout(noticeTimer); noticeTimer = setTimeout(() => $('notice').hidden = true, 6500);
}
const cloudMode = window.CARRYON_CLOUD === true;
const client = new (cloudMode ? CloudConsoleClient : CarryOnClient)({
  onUpdate: receiveUpdate,
  onDisconnect: streamDisconnected,
  onAuthError: () => { historyCache.clear();outgoingMessages.clear(); $('pairing').hidden = false;if(cloudMode){applyStatus({enabled:false,controllerId:null});$('requests-dialog').close();$('connection-requests').replaceChildren();$('account-menu').open=false;} },
  onError: error => notice('实时同步失败：' + error.message)
});
const api = (path, body) => client.request(path, body);
const subagentNavigation=SubagentNavigation.create({request:api,current:()=>selected,scope:draftScope,open:thread=>selectThread(thread.id,thread)});
$('open-subagents').onclick=()=>{$('open-subagents').closest('details').open=false;subagentNavigation.show();};
Timeline.configureSubagents(id=>subagentNavigation.show(id));
function welcomeState(connected){
  const welcome=node('div','welcome');
  welcome.append(node('span','welcome-icon','↗'),node('span','eyebrow',connected?'工作空间已就绪':'等待工作空间连接'),node('h2','',connected?'从一段对话开始':'连接后，继续你的工作'),node('p','',connected?'从会话列表选择一个任务，查看进度或继续对话。':cloudMode?'请确认电脑在线，并在本机开启桥接。':'在 CLI 或桌面端开启桥接，连接正在运行的 Codex。'));
  $('messages').replaceChildren(welcome);
}
function conversationReadOnly(){return composeHistory?.access?.canInteract===false;}
function canInteract(){return canWrite()&&!conversationReadOnly()&&composeHistory?.access?.nativeReady!==false;}
function canWrite(){return streamReady&&enabled&&workspaceAccountReady&&(!cloudMode||client.control===true);}
function applyStatus(status) {
  if(cloudMode){if(client.control!==(status.remoteControl===true))lastHistory='';client.control=status.remoteControl===true;}
  enabled = status.enabled; controllerId = status.controllerId; independentWorkspace = status.protocol === 'codex-app-server'; workspaceAccountReady = status.accountReady !== false;
  $('status').textContent = enabled ? (cloudMode?(client.control?'可远程操作':'只读连接'):'已连接') : '等待连接'; $('status').classList.toggle('on', enabled);
  $('bridge').textContent = '请在 CLI 或桌面端管理桥接';
  $('create').disabled = !canWrite() || (!independentWorkspace && !controllerId);
  $('create').title=!independentWorkspace&&!controllerId?'先在 CLI 或桌面端选择控制会话':'';
  for (const id of ['search','refresh']) $(id).disabled = !enabled;
  $('attach-images').disabled=!canAttach(); $('prompt').disabled = !canInteract() || !selected; $('send').disabled = !canInteract() || !selected;
  $('open-side').disabled=!enabled||!selected;
  $('open-subagents').disabled=!enabled||!selected;
  updateSideComposer();
  $('controller-note').textContent = independentWorkspace ? '在当前独立工作区创建会话。' : controllerId ? '控制会话已选定，新建任务将通过它执行。' : '首次请在 Codex App 中打开专用控制会话。';
  if(enabled&&!selected)welcomeState(true);
  $('prompt').placeholder=enabled?(selected?'发送新的任务…':'请先选择会话'): '请先开启本机桥接';
  if (!enabled) {
    if(selected)conversationDrafts.set(activeDraftScope+':'+selected,{text:$('prompt').value,images:[...attachedImages]});
    clearImages();composeHistory=null;
    threadFlags={};catalogRevision=null;workspaceRevision=null;
    Operations.reset();
    closeSide();
    updateThreadStatuses({});
    Timeline.reset();
    subagentNavigation.reset();
    listVersion++; selected = null; lastHistory = ''; threads = [];
    $('threads').replaceChildren(node('div','empty-small','开启桥接后，查看本机会话。'));
    welcomeState(false);
    $('jobs').replaceChildren(); $('title').textContent = '继续你的工作'; $('cwd').textContent = '从会话列表选择一个会话';
    $('controller').replaceChildren(new Option('开启桥接后选择控制会话',''));
    $('history-source').textContent = ''; $('more').hidden = true;
    $('create-dialog').close();
  }
}
function node(tag, cls, text) { const el = document.createElement(tag); if(cls) el.className=cls; if(text!==undefined) el.textContent=text; return el; }
function renderThreads() {
  if(workspaceView==='projects'){renderProjects();return;}
  const children = threads.map(t => {
    const button = node('button','thread' + (t.id === selected ? ' active' : ''));
    const row=node('div','thread-heading');
    const badge=node('span','thread-status');badge.dataset.threadStatus=t.id;
    const title=node('strong','',t.title || '未命名会话');
    if(t.unread){const unread=node('span','thread-unread');unread.setAttribute('aria-label','有未读消息');title.append(unread);}
    row.append(title,badge);
    button.append(row,node('small','',t.cwd));
    button.onclick = () => selectThread(t.id); return button;
  });
  $('threads').replaceChildren(...(children.length ? children : [node('div','empty-small','没有匹配的会话。')]));
  updateThreadStatuses(threadStatuses);
  const chosen = $('controller').value || controllerId;
  $('controller').replaceChildren(new Option('选择一个已加载的空闲会话',''),...threads.map(t => new Option(t.title || t.id,t.id)));
  if(chosen && !threads.some(t=>t.id===chosen)) $('controller').append(new Option('已选控制会话 · '+chosen.slice(0,8),chosen));
  if(chosen) $('controller').value=chosen;
  window.MobileUI?.sync();
}
function renderProjects(){
  $('threads').replaceChildren(...workspaceProjects.map(project=>{
    const button=node('button','thread project-row');
    const folder=node('span','project-folder','⌘');folder.setAttribute('aria-hidden','true');
    const body=node('span','project-body'),counts=node('span','project-statuses');
    body.append(node('strong','',project.name),node('small','project-path',project.cwd),node('small','project-count',`${project.total} 个会话`));
    for(const [key,label] of [['waiting','待处理'],['running','进行中'],['unread','未读'],['unknown','状态未知']]){
      if(project[key])counts.append(node('span','project-'+key,`${project[key]} ${label}`));
    }
    if(!counts.childNodes.length)counts.append(node('span','','暂无进行中的任务'));
    body.append(counts);const chevron=node('span','row-chevron','›');chevron.setAttribute('aria-hidden','true');button.append(folder,body,chevron);
    button.onclick=()=>{workspaceView='threads';workspaceProject=project.id;$('search').value='';$('project-filter').value='all';loadThreads().catch(e=>notice(e.message));};
    return button;
  }));
  if(!workspaceProjects.length)$('threads').append(node('div','empty-small','没有匹配的项目。'));
  $('thread-status-summary').textContent='项目汇总来自服务端全部会话；未知状态不会计为空闲。';
  window.MobileUI?.sync();
}
const listLoadState={key:null,phase:'idle',error:null};
function viewState(title,{loading=false,detail='',retry=null,symbol='folder'}={}){
  const state=node('div','view-state');state.dataset.state=loading?'loading':retry?'error':'empty';state.setAttribute('role','status');
  if(loading){const spinner=node('span','loading-spinner');spinner.setAttribute('aria-hidden','true');state.append(spinner);}
  else {
    const paths={folder:'M3 7h7l2 2h9v11H3z',chat:'M4 4h16v12H9l-5 4z',search:'M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14m5-2 6 6',offline:'M3 3l18 18M5 10a12 12 0 0 1 14 0M8 14a7 7 0 0 1 8 0M12 19h.01'};
    const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('aria-hidden','true');
    const path=document.createElementNS(icon.namespaceURI,'path');path.setAttribute('d',paths[symbol]||paths.folder);icon.append(path);state.append(icon);
  }
  state.append(node('strong','',title));if(detail)state.append(node('p','',detail));
  if(retry){const button=node('button','quiet','重试');button.onclick=retry;state.append(button);}return state;
}
async function loadThreads(more=false){
  const key=JSON.stringify([draftScope(),workspaceView,workspaceProject,$('search').value,$('project-filter').value]);
  if(more&&listLoadState.phase!=='idle')return;
  const version=++listVersion;
  if(key!==listLoadState.key){offset=0;threads=[];if(workspaceView==='projects')workspaceProjects=[];$('more').hidden=true;}
  const hasRows=(workspaceView==='projects'?workspaceProjects:threads).length>0;
  Object.assign(listLoadState,{key,phase:more?'more':hasRows?'refresh':'initial',error:null});
  $('more').disabled=true;$('more').textContent=more?'正在加载…':'加载更多';
  window.MobileUI?.sync();
  const start=more?offset:0,params='?limit=100&offset='+start+'&search='+encodeURIComponent($('search').value);
  const route=workspaceView==='projects'?'/projects':workspaceView==='activity'?'/activity':'/projects/'+workspaceProject+'/threads';
  try{
    const result=await api(route+params+(workspaceView==='threads'?'&filter='+$('project-filter').value:''));
    if(!enabled||version!==listVersion)return;
    offset=result.nextOffset;$('more').hidden=offset>=result.total;
    $('project-filter-label').hidden=workspaceView!=='threads';
    if(workspaceView==='projects'){workspaceProjects=more?[...workspaceProjects,...result.projects]:result.projects;threads=[];renderProjects();}
    else{threads=more?[...threads,...result.threads]:result.threads;renderThreads();}
  }catch(error){
    if(version===listVersion){listLoadState.error=error.message;if(!mobileLayout.matches)notice(error.message);}
    return;
  }finally{
    if(version===listVersion){listLoadState.phase='idle';$('more').disabled=false;$('more').textContent='加载更多';window.MobileUI?.sync();}
  }
  const totals=await api('/activity?limit=1');if(version!==listVersion)return;
  $('show-activity').textContent='动态'+(totals.total?' · '+totals.total:'');
  window.MobileUI?.sync();
  if(!$('controller').options.length||workspaceView==='projects'){
    const all=await api('/threads?limit=100');if(version!==listVersion)return;
    $('controller').replaceChildren(new Option('选择一个已加载的空闲会话',''),...all.threads.map(t=>new Option(t.title||t.id,t.id)));
    if(controllerId)$('controller').value=controllerId;
  }
  await loadHistory();
}
$('show-projects').onclick=()=>{workspaceView='projects';workspaceProject=null;$('search').value='';loadThreads().catch(e=>notice(e.message));};
$('show-activity').onclick=()=>{workspaceView='activity';workspaceProject=null;$('search').value='';loadThreads().catch(e=>notice(e.message));};
$('project-filter').onchange=()=>loadThreads().catch(e=>notice(e.message));
client.onSubmission=update=>{
  const target=update.threadId||selected,key=conversationKey(target)+':'+update.id;
  const previous=outgoingMessages.get(key);
  const item=update.begin?{...previous,...update,threadId:target,scope:draftScope()}:mergeOutgoingMessage(previous,update);
  if(item)outgoingMessages.set(key,item);else outgoingMessages.delete(key);
  reconcileOutgoing([],historyCache.get(conversationKey(target)),update.state==='sending');
};
let activityNavigationThread=null;
async function selectThread(id, record=null) {
  activityNavigationThread=workspaceView==='activity'?id:null;
  subagentNavigation.reset();
  if(selected)conversationDrafts.set(activeDraftScope+':'+selected,{text:$('prompt').value,images:[...attachedImages]});
  clearImages();
  activeDraftScope=draftScope();
  const draft=conversationDrafts.get(activeDraftScope+':'+id);$('prompt').value=draft?.text||'';attachedImages=draft?.images||[];renderImages();
  if(mobileLayout.matches) { setThreadListOpen(false); $('title').focus({preventScroll:true}); }
  composeHistory=record?.access?{access:{...record.access,nativeReady:false}}:null;updateComposeButton();Operations.reset();
  closeSide();$('open-side').disabled=!enabled;$('open-subagents').disabled=!enabled;
  Timeline.reset();
  selected=id; historyLimit=40; lastHistory=''; delete $('messages').dataset.loaded; renderThreads(); $('attach-images').disabled=!canAttach();$('prompt').disabled=!canInteract(); $('send').disabled=!canInteract();
  const thread=record||threads.find(t=>t.id===id); $('title').textContent=thread?.title || id; $('cwd').textContent=thread?.cwd || '';
  $('prompt').placeholder='发送消息…';
  window.MobileUI?.show('chat');
  const cached=historyCache.get(conversationKey(id));
  if(cached){Timeline.render(cached,$('messages'),historyImageLoader(id));$('history-source').textContent='已显示缓存，正在同步…';}
  else $('messages').replaceChildren(viewState('正在加载会话…',{loading:true}));
  renderOutgoing();
  try { await loadHistory(); } catch(e) { if(selected===id) $('messages').replaceChildren(viewState('加载失败',{detail:e.message,retry:retryHistory,symbol:'offline'})); }
}
function retryHistory(){client.close();loadHistory().catch(e=>notice(e.message));}
let historyLimit=40;
const loadEarlierHistory=async()=>{historyLimit=Math.min(100000,historyLimit+40);await loadHistory();};
Timeline.configureHistory(loadEarlierHistory);
SideTimeline.configureHistory(async()=>{sideHistoryLimit=Math.min(100000,sideHistoryLimit+40);await loadHistory();});
async function loadHistory() {
  subscription = client.subscribe({historyLimit,sideHistoryLimit,threadId: enabled ? selected : null,
    threadIds: enabled ? threads.slice(0,100).map(t => t.id) : [],
    includeSideChats: enabled && sideOpen, sideThreadId: enabled && sideOpen ? sideSelected : null});
}
async function receiveUpdate(data, current) {
  const wasReady=streamReady;streamReady=true;
  const wasEnabled = enabled;
  if(!wasReady || enabled !== data.status.enabled || workspaceAccountReady !== (data.status.accountReady !== false) || controllerId !== data.status.controllerId || cloudMode&&client.control!==(data.status.remoteControl===true)) applyStatus(data.status);
  if(enabled && !wasEnabled) { await loadThreads(); if(!current())return; await loadHistory(); }
  if(!enabled)return;
  if(data.workspaceRevision!==undefined&&workspaceRevision!==data.workspaceRevision){
    const changed=workspaceRevision!==null;workspaceRevision=data.workspaceRevision;
    if(changed){clearTimeout(workspaceRefreshTimer);workspaceRefreshTimer=setTimeout(()=>loadThreads().catch(e=>notice(e.message)),300);}
  }
  if(data.subscription===subscription&&data.threadFlags){
    if(JSON.stringify(data.threadFlags)!==JSON.stringify(threadFlags)){
      threadFlags=data.threadFlags;
      if(selected&&threadFlags[selected]?.archived){
        closeSide();Operations.reset();selected=null;lastHistory='';
        $('messages').replaceChildren(node('div','empty-small','此会话已归档。'));
        clearImages();$('attach-images').disabled=true;$('send').disabled=true;$('prompt').disabled=true;$('open-side').disabled=true;
      }
      renderThreads();
    }
  }
  if(data.catalogRevision!==undefined&&data.catalogRevision!==catalogRevision){
    const changed=catalogRevision!==null;catalogRevision=data.catalogRevision;
    if(changed){clearTimeout(workspaceRefreshTimer);workspaceRefreshTimer=setTimeout(()=>loadThreads().catch(e=>notice(e.message)),300);}
  }
  if(data.subscription===subscription && data.threadStatuses) updateThreadStatuses(data.threadStatuses);
  if(data.jobs){renderJobs(data.jobs);reconcileOutgoing(data.jobs);}
  if(data.threadId !== selected || data.subscription !== subscription)return;
  if(sideOpen&&data.sideChats)renderSides(data.sideChats);
  if(sideOpen&&data.sideThreadId===sideSelected){
    if(data.sideError){sideComposeHistory=null;$('side-source').textContent='同步暂不可用';$('side-runtime').textContent='状态未知';$('side-discovery').textContent=data.sideError;}
    else if(data.sideHistory){sideComposeHistory=data.sideHistory;const signature=JSON.stringify([data.sideHistory.historyRevision,data.sideHistory.queue]);if(signature!==sideSignature){sideSignature=signature;SideTimeline.render(data.sideHistory,$('side-messages'),historyImageLoader(sideSelected,selected)); }}
    const job=data.jobs?.find(job=>job.id===sideJob);if(job)$('side-send-status').textContent=job.error||({accepted:'已接收',completed:'已完成',failed:'发送失败',uncertain:'结果待核对，请勿重复发送',preparing:'正在提交…',dispatching:'正在提交…'}[job.state]||job.state);
    updateSideComposer();
  }
  if(data.error) { Operations.reset();lastHistory='';$('history-source').textContent='同步暂不可用';if(!$('messages').dataset.loaded||$('messages').querySelector('[data-state=loading]'))$('messages').replaceChildren(viewState('加载失败',{detail:data.error,retry:retryHistory,symbol:'offline'}));else notice(data.error);return; }
  if(data.history) {
    historyCache.set(conversationKey(selected),data.history);
    updateCompose(data.history);
    const signature = data.history.historyRevision || JSON.stringify(data.history);
    if(signature !== lastHistory){lastHistory=signature;Timeline.render(data.history,$('messages'),historyImageLoader(data.history.thread.id));Operations.render(data.history,selected,client,notice,canInteract());}
    reconcileOutgoing([],data.history);
    if(activityNavigationThread===selected){const anchor=Timeline.activityAnchor(data.history);if(anchor){Timeline.navigateTo(anchor);activityNavigationThread=null;}}
    if(document.visibilityState==='visible'&&(!mobileLayout.matches||document.body.dataset.mobilePage==='chat')&&data.readSequence)api('/notifications/read',{threadId:selected,sequence:data.readSequence}).catch(()=>{});
  }
}
function streamDisconnected(event) {
  streamReady=false;
  sideComposeHistory=null;updateSideComposer();
  $('status').textContent='重连中';
  $('send').disabled=true;$('attach-images').disabled=true;$('create').disabled=true;
  subagentNavigation.reset();
  composeHistory={access:{...composeHistory?.access,nativeReady:false}};updateComposeButton();Operations.reset();
  lastHistory='';
  if(sideOpen){$('side-runtime').textContent='状态未知';$('side-source').textContent='连接已断开，重连后恢复';}
  updateThreadStatuses({});
  if(event.code===1008){notice('实时连接认证失败，请重新配对');return;}
  if(enabled)notice('实时连接已断开，正在重连…');
}
$('expand-events').onclick=()=>Timeline.setExpanded(true);
$('open-side').onclick=()=>{if(!enabled||!selected)return;sideOpen=true;$('side-drawer').hidden=false;document.body.classList.add('side-open');$('side-discovery').textContent='正在查找临时聊天…';loadHistory();};
$('close-side').onclick=()=>{closeSide();loadHistory();};
$('side-select').onchange=()=>{sideHistoryLimit=40;sideSelected=$('side-select').value||null;sideSignature='';resetSideComposer();SideTimeline.reset();delete $('side-messages').dataset.loaded;$('side-messages').replaceChildren(node('div','empty-small',sideSelected?'正在读取临时聊天…':'请选择临时聊天'));loadHistory();};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&sideOpen){closeSide();loadHistory();}});
$('collapse-events').onclick=()=>Timeline.setExpanded(false);
function renderJobs(jobs) {
  $('jobs').replaceChildren(...jobs.slice(0,6).map(job=> {
    const row=node('div','job'+(['failed','uncertain'].includes(job.state)?' error':''));
    const name=job.kind.startsWith('operation:')?(Operations.labels[job.kind.slice(10)]||'会话操作'):(job.kind==='create'?'新建会话':'发送任务');
    const state=job.kind.startsWith('operation:')&&job.state==='completed'?'原生入口已响应':(states[job.state]||job.state);
    const label=node('div','',name+' · '+state);
    label.append(node('small','',job.error || job.result?.goalPauseError || job.id)); row.append(label);
    if(job.createdThreadId){ const open=node('button','quiet','打开会话');open.onclick=async()=>{await loadThreads();await selectThread(job.createdThreadId);};row.append(open); }
    if(job.state==='uncertain'){ const ack=node('button','quiet','已在 App 核对');ack.disabled=!canWrite();ack.onclick=async()=>{if(confirm('确认已在 Codex App 核对这个请求？这只解除阻塞，不会重发。')){try{await api('/jobs/'+job.id+'/acknowledge',{confirmed:true});await tick();}catch(e){notice(e.message);}}};row.append(ack); }
    return row;
  }));
}
function submit(kind, prompt) {
  return client.submit(kind, kind === 'create' ? controllerId : selected, prompt);
}
$('pairing-form').onsubmit=async event=>{
  event.preventDefault();$('pairing-error').hidden=true;
  $('pair').disabled=true;
  try {
    historyCache.clear();outgoingMessages.clear();
    await client.pair($('token').value,cloudMode?$('login-username').value:undefined);
    if(cloudMode){$('pairing').hidden=true;$('token').value='';}
    if(!cloudMode||client.device)applyStatus(await api('/status'));$('pairing').hidden=true;$('token').value='';
    client.connect();if(enabled)await loadThreads();
  } catch(e){if(!client.token){$('pairing-error').textContent=e.message;$('pairing-error').hidden=false;}else notice(e.message);}
  finally{$('pair').disabled=false;if(cloudMode)client.connect();}
};
$('create').onclick=()=>{$('create-error').textContent='';$('create-dialog').showModal();$('new-prompt').focus();};
for(const id of ['close-dialog','cancel-create']) $(id).onclick=()=>$('create-dialog').close();
$('create-form').onsubmit=async e=>{e.preventDefault();$('submit-create').dataset.pending='true';$('submit-create').disabled=true;try{await submit('create',$('new-prompt').value.trim());$('create-dialog').close();$('new-prompt').value='';}catch(e){$('create-error').textContent=e.message+'；重试会沿用原请求 ID。';}finally{delete $('submit-create').dataset.pending;$('submit-create').disabled=false;window.MobileUI?.sync();}};
let attachedImages=[],imageGeneration=0,imageBusy=false;
function clearImages(){imageGeneration++;attachedImages=[];renderImages();}
function renderImages(){
  const root=$('image-previews');root.replaceChildren();root.hidden=!attachedImages.length;
  for(const item of attachedImages){const card=node('div','image-preview'),img=document.createElement('img');img.src=item.url;img.alt=item.name;
    const remove=node('button','','×');remove.type='button';remove.setAttribute('aria-label','移除图片 '+item.name);remove.disabled=imageBusy;
    remove.onclick=()=>{attachedImages=attachedImages.filter(i=>i!==item);renderImages();updateComposeButton();};card.append(img,remove);root.append(card);}
}
async function prepareImage(file){
  if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>20*1024*1024)throw Error('请选择 20 MB 以内的 PNG、JPEG 或 WebP 图片');
  const bitmap=await createImageBitmap(file);
  try{if(bitmap.width*bitmap.height>40000000)throw Error('图片尺寸过大，请缩小后上传');
    const canvas=document.createElement('canvas'),scale=Math.min(1,1600/Math.max(bitmap.width,bitmap.height));
    canvas.width=Math.max(1,Math.round(bitmap.width*scale));canvas.height=Math.max(1,Math.round(bitmap.height*scale));
    const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(bitmap,0,0,canvas.width,canvas.height);
    let url;for(const quality of [.9,.75,.55,.35]){url=canvas.toDataURL('image/jpeg',quality);if(url.length<270000)return{name:file.name,url};}
    throw Error('图片压缩后仍过大，请裁剪后重试');
  }finally{bitmap.close();}
}
async function addImages(files){
  if(!canAttach())return;
  const generation=imageGeneration;imageBusy=true;$('attach-images').disabled=true;$('send').disabled=true;
  try{const batch=[...files];if(attachedImages.length+batch.length>3)throw Error('每次最多添加 3 张图片');
    const ready=[];for(const file of batch)ready.push(await prepareImage(file));
    if(generation===imageGeneration)attachedImages.push(...ready);
  }catch(e){notice(e.message);}finally{imageBusy=false;renderImages();$('attach-images').disabled=!canAttach();$('send').disabled=!canInteract()||!selected;}
}
$('attach-images').onclick=()=>$('image-files').click();
$('image-files').onchange=()=>{addImages($('image-files').files);$('image-files').value='';};
$('prompt').addEventListener('paste',event=>{const files=[...event.clipboardData.items].filter(i=>i.kind==='file'&&i.type.startsWith('image/')).map(i=>i.getAsFile()).filter(Boolean);if(files.length){event.preventDefault();addImages(files);}});
Timeline.configureQuestions({
  canSend:thread=>canInteract()&&selected===thread,
  submit:async(thread,prompt)=>{
    if(!canInteract()||selected!==thread)throw Error('会话或控制权限已改变');
    const job=await client.submit('compose',thread,prompt,[],()=>selected===thread&&canInteract());
    if(['failed','uncertain'].includes(job.state))throw Error(job.error||'结果待核对，重试会沿用原请求编号');
  }
});
$('composer').onsubmit=async e=>{
  e.preventDefault();if(imageBusy||!canInteract()||!selected)return;
  const prompt=$('prompt').value.trim();
  if(!prompt&&!attachedImages.length){
    if(composeHistory?.controls?.activeTurnId&&composeHistory.runtime?.type==='active')await client.operation(selected,'interrupt',{expectedTurnId:composeHistory.controls.activeTurnId}).catch(e=>notice(e.message));
    return;
  }
  const target=selected,generation=imageGeneration;imageBusy=true;renderImages();$('send').disabled=true;$('attach-images').disabled=true;
  try{const job=await client.submit('compose',target,prompt,attachedImages.map(i=>i.url),()=>selected===target&&generation===imageGeneration);
    if(['failed','uncertain'].includes(job.state))throw Error(job.error||'请求未成功，请先核对原请求');
    if(selected===target&&generation===imageGeneration){$('prompt').value='';conversationDrafts.delete(draftScope()+':'+target);clearImages();}
  }catch(e){notice(e.message+'；重试会沿用原请求 ID。');}
  finally{imageBusy=false;renderImages();$('attach-images').disabled=!canAttach();$('send').disabled=!canInteract()||!selected;}
};
$('prompt').onkeydown=e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)){e.preventDefault();if(!$('send').disabled)$('composer').requestSubmit();}};
$('refresh').onclick=()=>loadThreads().catch(e=>notice(e.message));
$('more').onclick=()=>loadThreads(true).catch(e=>notice(e.message));
let searchTimer;$('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadThreads().catch(e=>notice(e.message)),300);};
async function tick(){
  if(refreshBusy || !client.token)return;refreshBusy=true;
  try{const status=await api('/status');const justEnabled=status.enabled&&!enabled;
    if(status.enabled!==enabled || workspaceAccountReady !== (status.accountReady !== false) || status.controllerId!==controllerId || cloudMode&&client.control!==(status.remoteControl===true)){applyStatus(status);if(enabled)renderThreads();}
    if(justEnabled)await loadThreads();
    if(enabled){const {jobs}=await api('/jobs');if(enabled)renderJobs(jobs);await loadHistory();}}
  catch(e){if(enabled)notice(e.message);}finally{refreshBusy=false;}
}
let consoleDirectoryRefresh=null;
async function refreshConsoleDevices(){
  if(client.removing)return;
  if(consoleDirectoryRefresh)return consoleDirectoryRefresh;
  consoleDirectoryRefresh=refreshConsoleDeviceDirectory();
  try{await consoleDirectoryRefresh;}finally{consoleDirectoryRefresh=null;}
}
async function refreshConsoleDeviceDirectory(){
  const previous=client.device;
  await client.initialize();
  if(previous!==client.device){
    client.close();client.epoch++;client.selection=null;
    applyStatus({enabled:false,controllerId:null});
    if(client.device){try{applyStatus(await api('/status'));if(enabled)await loadThreads();}catch(e){notice(e.message);}client.connect();}
  }
}
async function removeConsoleDevice(id=client.device,confirmed=false){
  if(!id||client.removing||(!confirmed&&!confirm('移除此设备并撤销它的云端连接凭证？')))return false;
  const previous=client.device;
  client.removing=true;
  $('console-remove-device').disabled=$('console-device').disabled=true;
  try{
    if(consoleDirectoryRefresh)await consoleDirectoryRefresh;
    if(client.device!==previous)throw Error('设备已改变，请重新选择要移除的设备');
    client.close();
    const result=await client.consoleRequest('devices/'+encodeURIComponent(id),undefined,'DELETE');
    if(result.removed!==true)throw Error('未确认设备已移除，请刷新设备列表核对');
    if(client.device===id){
      client.device='';client.epoch++;client.selection=null;client.setStorage();
      $('console-device').replaceChildren();
      applyStatus({enabled:false,controllerId:null});
    }
    try{await refreshConsoleDeviceDirectory();notice('设备已移除');}
    catch(e){notice('设备已移除；设备列表刷新失败：'+e.message);}
    return true;
  }catch(e){notice(e.message);return false;}
  finally{
    client.removing=false;
    $('console-remove-device').disabled=$('console-device').disabled=false;
    client.connect();
  }
}
let connectionRequestsVersion=0;
async function refreshConnectionRequests(){
  if(!cloudMode||!client.token)return;
  const version=++connectionRequestsVersion;
  let result;
  try{result=await client.consoleRequest('binding/pending');}
  catch(error){if(version!==connectionRequestsVersion)return;throw error;}
  if(version!==connectionRequestsVersion)return;
  $('console-requests').textContent='绑定申请'+(result.requests.length?' · '+result.requests.length:'');
  const list=$('connection-requests');list.replaceChildren();
  if(!result.requests.length)list.textContent='暂无待确认的申请';
  const labels={view:'查看会话',create:'新建会话',send:'发送消息',stop:'停止任务',edit:'编辑会话与设置',files:'查看和下载文件',approve:'处理审批'};
  for(const request of result.requests){
    const row=node('section','connection-request-card group');
    row.append(node('strong','',request.name),node('p','',request.account.username),node('p','',request.permissions.map(p=>labels[p]||p).join('、')));
    const approve=node('button','primary','确认绑定'),reject=node('button','secondary','拒绝');
    const respond=async rejected=>{
      approve.disabled=reject.disabled=true;
      try{await client.consoleRequest('binding/respond',{id:request.id,reject:rejected});await refreshConnectionRequests();await refreshConsoleDevices();}
      catch(error){notice(error.message);approve.disabled=reject.disabled=false;}
    };
    approve.onclick=()=>respond(false);reject.onclick=()=>respond(true);row.append(approve,reject);list.append(row);
  }
}
async function init(){
  $('notification-settings').hidden=!cloudMode;
  if(location.protocol==='file:'){ $('pairing').hidden=false; notice('请通过本地服务打开页面，不能直接双击 HTML 启动后台进程。');return; }
  if(cloudMode){
    document.body.classList.add('cloud-console');
    document.querySelector('.footnote').textContent='与你的 Codex 工作空间保持同步';
    $('environment-label').textContent='云端工作台';$('auth-title').textContent='登录你的工作空间';$('auth-description').textContent='安全连接，接着上次的进度继续。';$('account-menu').hidden=false;
    document.querySelector('label[for="token"]').textContent='密码';
    setupConsoleLogin(client,async()=>{await client.initialize();$('pairing').hidden=true;if(client.device)applyStatus(await api('/status'));client.connect();if(enabled)await loadThreads();});
    $('token').placeholder='输入密码';$('token').autocomplete='current-password';$('pair').textContent='登录工作空间 →';
    $('auth-help').textContent='';document.querySelector('.auth-security').hidden=true;
    for(const id of ['console-device','console-logout','console-requests','console-remove-device','console-standby'])$(id).hidden=false;
    $('console-requests').onclick=async()=>{try{await refreshConnectionRequests();$('requests-dialog').showModal();}catch(e){notice(e.message);}};
    $('requests-close').onclick=()=>$('requests-dialog').close();
    $('console-standby').onclick=async()=>{try{const s=await api('/standby');notice(s.error||(!s.supported?'此设备不支持远程待机':s.effective?'远程待机已生效（接电）':s.enabled?'远程待机已开启，当前未生效':'远程待机未开启；请在本机管理'));}catch(e){notice(e.message);}};
    $('console-remove-device').onclick=()=>removeConsoleDevice();
    const pollRequests=async()=>{try{await refreshConnectionRequests();if(client.token)await refreshConsoleDevices();}catch(e){if(client.token)notice(e.message);}finally{setTimeout(pollRequests,5000);}};
    pollRequests();
    $('console-device').onchange=async()=>{
      subagentNavigation.reset();
      client.close();client.epoch++;client.selection=null;client.device=$('console-device').value;client.setStorage();
      applyStatus({enabled:false,controllerId:null});
      try{applyStatus(await api('/status'));if(enabled)await loadThreads();}catch(e){notice(e.message);}finally{client.connect();}
    };
    $('console-logout').onclick=async()=>{
      subagentNavigation.reset();
      $('console-logout').disabled=true;
      client.close();client.epoch++;client.selection=null;
      try{await client.consoleRequest('logout',{});historyCache.clear();outgoingMessages.clear();client.token='';applyStatus({enabled:false,controllerId:null});$('pairing').hidden=false;$('pairing-error').hidden=true;$('requests-dialog').close();$('connection-requests').replaceChildren();$('account-menu').open=false;$('token').value='';$('token').focus();}catch(e){notice(e.message);client.connect();}finally{$('console-logout').disabled=false;}
    };
    try{await client.initialize();}catch(e){if(e.message!=='请先登录云端控制台'){$('pairing-error').textContent=e.message;$('pairing-error').hidden=false;}}
  }
  $('pairing').hidden=!!client.token;
  if(client.token&&(!cloudMode||client.device))try{applyStatus(await api('/status'));if(enabled)await loadThreads();}catch(e){notice(e.message);}
  client.connect();
}
document.addEventListener('click',event=>{
  for(const menu of document.querySelectorAll('.account-menu,.display-menu,.session-info,.session-actions'))if(!menu.contains(event.target))menu.open=false;
});
document.addEventListener('keydown',event=>{if(event.key==='Escape')for(const menu of document.querySelectorAll('.account-menu,.display-menu,.session-info,.session-actions'))if(menu.open){menu.open=false;menu.querySelector('summary').focus();}});
init().finally(()=>document.body.classList.remove('booting'));

function draftScope(){return cloudMode?client.storageScope:location.origin;}
let composeHistory=null;
function canAttach(){return canInteract()&&!!selected&&['idle','running','waiting'].includes(composeHistory?.status?.state)&&!imageBusy;}
function updateCompose(history){composeHistory=history;if(history.thread?.title)$('title').textContent=history.thread.title;updateComposeButton();$('attach-images').disabled=!canAttach();window.MobileUI?.sync();}
function updateComposeButton(){
  $('composer').hidden=conversationReadOnly();
  $('prompt').disabled=!canInteract()||!selected;
  $('send').disabled=!canInteract()||!selected||imageBusy;
  const running=composeHistory?.runtime?.type==='active';
  $('send').textContent=running&&!$('prompt').value.trim()&&!attachedImages.length?'停止任务':'发送任务 ↑';
}
$('prompt').addEventListener('input',updateComposeButton);
const feed=new NotificationFeed({request:api,storage:localStorage,onEvent:async(event,remind)=>{
  // Read acknowledgement happens only after the matching history packet renders.
}});
async function pollNotifications(){
  try{if(enabled&&client.token){feed.changeScope(draftScope());await feed.poll();}}
  catch(e){/* The live transport already reports connection failures. */}
  finally{setTimeout(pollNotifications,3000);}
}
let notificationVersion=0;
async function loadNotificationPreferences(){
  const version=++notificationVersion,scope=draftScope(),container=$('notification-preferences');
  container.replaceChildren(viewState('正在加载通知设置…',{loading:true}));$('system-notification-status').textContent='';
  if(!$('notification-dialog').open)$('notification-dialog').showModal();
  try{
    const {preferences}=await api('/notifications/preferences');
    if(version!==notificationVersion||scope!==draftScope())return;
    const labels={message:'新消息',done:'任务完成',failed:'执行失败',approval:'需要确认'};
    if(!preferences||Object.keys(labels).some(key=>typeof preferences[key]!=='boolean'))throw Error('通知偏好格式不正确');
    container.replaceChildren(...Object.entries(labels).map(([kind,text])=>{
      const label=node('label','',text),input=node('input');input.type='checkbox';input.setAttribute('role','switch');input.checked=preferences[kind];
      input.onchange=async()=>{
        for(const control of container.querySelectorAll('input'))control.disabled=true;
        container.setAttribute('aria-busy','true');
        try{
          const result=await api('/notifications/preferences',{...preferences,[kind]:input.checked});
          if(version!==notificationVersion||scope!==draftScope())return;
          Object.assign(preferences,result.preferences);$('system-notification-status').textContent='已保存';
        }catch(e){if(version===notificationVersion&&scope===draftScope()){input.checked=preferences[kind];$('system-notification-status').textContent='保存失败：'+e.message;}}
        finally{if(version===notificationVersion){container.removeAttribute('aria-busy');for(const control of container.querySelectorAll('input'))control.disabled=false;}}
      };
      label.append(input);return label;
    }));
    $('system-notification-status').textContent='系统推送尚未接入，当前可在前台查看更新。';
  }catch(e){if(version===notificationVersion&&scope===draftScope())container.replaceChildren(viewState('加载失败',{symbol:'offline',detail:e.message,retry:loadNotificationPreferences}));}
}
$('notification-settings').onclick=loadNotificationPreferences;
$('notification-dialog').addEventListener('close',()=>{notificationVersion++;$('notification-preferences').removeAttribute('aria-busy');});
$('notification-close').onclick=()=>$('notification-dialog').close();
pollNotifications();

document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'&&enabled&&selected)loadHistory().catch(()=>{});});

let refreshTouch=null;
const sidebar=document.querySelector('aside');
sidebar.addEventListener('touchstart',event=>{if(sidebar.scrollTop===0&&$('threads').scrollTop===0&&event.touches.length===1)refreshTouch=event.touches[0].clientY;},{passive:true});
sidebar.addEventListener('touchend',event=>{if(refreshTouch!==null&&event.changedTouches[0]?.clientY-refreshTouch>80&&enabled)loadThreads().catch(e=>notice(e.message));refreshTouch=null;},{passive:true});
sidebar.addEventListener('touchcancel',()=>{refreshTouch=null;},{passive:true});
