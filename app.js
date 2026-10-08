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
let enabled = false, selected = null, threads = [], offset = 0;
let refreshBusy = false, lastHistory = '', listVersion = 0, noticeTimer;
let subscription = null, streamReady = true;
let sideOpen=false, sideSelected=null, sideSignature='',sideHistoryLimit=40;
let sideComposeHistory=null, sideSending=false, sideDraftKey=null, sideJob=null;
const sideDrafts=new Map();
let sideLifecycleBusy=false,sideRows=[];
function sideCapability(cap){return canWrite()&&(!cloudMode||client.devices?.find(d=>d.id===client.device)?.permissions?.includes(cap)===true);}
function resetSideComposer(){
  if(sideDraftKey)sideDrafts.set(sideDraftKey,$('side-prompt').value);
  sideDraftKey=sideOpen&&sideSelected?draftScope()+':'+selected+':'+sideSelected:null;
  sideComposeHistory=null;sideJob=null;$('side-prompt').value=sideDrafts.get(sideDraftKey)||'';$('side-send-status').textContent='';updateSideComposer();
}
function canSendSide(){return sideCapability(sideComposeHistory?.status?.state==='running'&&!$('side-prompt').value.trim()?'stop':'send')&&sideOpen&&!!sideSelected&&!!sideComposeHistory&&sideComposeHistory.access?.canInteract===true&&sideComposeHistory.access?.nativeReady===true&&['idle','running','waiting'].includes(sideComposeHistory.status?.state)&&!sideSending;}
function updateSideComposer(){
  $('create-side').hidden=!composeHistory?.controls?.supportedOperations?.includes('side-create');
  $('create-side').disabled=sideLifecycleBusy||!sideCapability('create');
  $('end-side').hidden=!sideRows.find(row=>row.id===sideSelected)?.canClose;
  $('end-side').disabled=sideLifecycleBusy||!sideCapability('stop');
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
  const chats=data.chats||[];sideRows=chats;
  const old=$('side-select').value;
  $('side-select').replaceChildren(new Option('选择临时聊天',''),...chats.map(c=>new Option(`${c.title} · ${c.id.slice(-8)} · ${c.label}`,c.id)));
  $('side-select').value=sideSelected||old;
  $('side-discovery').textContent=data.error||(data.scanning?'正在核验已登记的临时聊天，找到后会自动显示。':chats.length?`已确认 ${chats.length} 个临时聊天。`:'暂无临时聊天');
  if(sideSelected&&!chats.some(c=>c.id===sideSelected)){
    sideSelected=null;sideSignature='';SideTimeline.reset();$('side-messages').replaceChildren();
    resetSideComposer();
  }
  if(sideSelected){const c=chats.find(c=>c.id===sideSelected);if(c)$('side-runtime').textContent=c.label;}
  updateSideComposer();
}
let workspaceView='projects',workspaceProject=null,workspaceProjects=[],workspaceRevision=null;
let workspaceRefreshTimer;
let showInactive=false;
try{showInactive=localStorage.getItem('carryon-show-inactive')==='true';}catch{}
$('show-inactive').checked=showInactive;
$('show-inactive').onchange=()=>{showInactive=$('show-inactive').checked;try{localStorage.setItem('carryon-show-inactive',String(showInactive));}catch{}loadThreads().catch(e=>notice(e.message));};
const lastSynced=new Map(),listWindows=new Map();
function listViewport(){return mobileLayout.matches?$('mobile-session-list'):$('threads');}

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
    const references=[...(item.skills||[]),...(item.mentions||[]),...(item.files||[])];
    if(item.prompt||!references.length)row.append(node('div','text',item.prompt||'图片消息'));
    if(references.length){const refs=node('div','skill-chips');for(const skill of references)refs.append(node('span','skill-chip',skill.name));row.append(refs);}
    const labels={sending:'发送中…',preparing:'发送中…',dispatching:'发送中…',failed:'发送失败，请核对请求记录',uncertain:'结果待核对，请勿重复发送'};
    row.append(node('small','outgoing-status',labels[item.state]||(item.kind==='operation:queue-add'?'已排队，等待同步':'已接收，等待同步')));
    if(['failed','uncertain','accepted','dispatching','preparing'].includes(item.state)){
      const check=node('button','quiet','核对发送结果');check.onclick=async()=>{const scope=draftScope();check.disabled=true;try{const job=await api('/jobs/'+encodeURIComponent(item.id));if(scope!==draftScope())return;reconcileOutgoing([job]);notice(job.error||states[job.state]||job.state);}catch(e){if(scope===draftScope())notice(e.message);}finally{check.disabled=false;}};row.append(check);
    }
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
let reviewComments=[];
let changeCommentViews=[];
function currentConversationDraft(){return {text:$('prompt').value,images:[...attachedImages],skills:[...selectedSkills],files:[...selectedFiles],caret:$('prompt').caret,comments:reviewComments.map(comment=>({...comment}))};}
function renderReviewComments(){const button=$('review-comment-drafts');button.hidden=!reviewComments.length;button.textContent=reviewComments.length+' 条待发送评论';for(const view of changeCommentViews)view.refreshComments();commentOverviewRefresh?.();}
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
  onAuthError: () => { historyCache.clear();outgoingMessages.clear();listWindows.clear();lastSynced.clear(); $('pairing').hidden = false;if(cloudMode){applyStatus({enabled:false});$('requests-dialog').close();$('connection-requests').replaceChildren();$('account-menu').open=false;} },
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
function canInteract(){return canWrite()&&!!composeHistory&&['idle','running','waiting'].includes(composeHistory.status?.state)&&!conversationReadOnly()&&composeHistory.access?.nativeReady!==false;}
function canFork(){return canInteract()&&(!cloudMode||client.devices?.find(d=>d.id===client.device)?.permissions?.includes('create')===true);}
async function forkConversation(source,lastTurnId,isCurrent,onCreated=()=>{}){
  const scope=draftScope();
  if(!canFork()||selected!==source||!isCurrent())throw Error('当前会话不可分叉');
  const job=await client.fork(source,lastTurnId,()=>scope===draftScope()&&selected===source&&canFork()&&isCurrent());
  if(scope!==draftScope()||selected!==source||!isCurrent())return;
  if(job.state!=='completed'||!job.createdThreadId)throw Error(job.error||'尚未确认分叉结果，请在请求记录中核对');
  onCreated();window.MobileUI?.resetOperations();await selectThread(job.createdThreadId);
}
function canWrite(){return streamReady&&enabled&&workspaceAccountReady&&(!cloudMode||client.control===true);}
let supportsFullTextSearch=false,supportsThreadSections=false,supportsPluginManagement=false;
function applyStatus(status) {
  supportsPluginManagement=status.supportsPluginManagement===true;supportsFullTextSearch=status.supportsFullTextSearch===true;supportsThreadSections=status.supportsThreadSections===true;
  if(!cloudMode&&status.workspaceSession&&client.workspaceSession!==status.workspaceSession){
    if(client.workspaceSession){applyStatus({enabled:false});historyCache.clear();outgoingMessages.clear();listWindows.clear();lastSynced.clear();conversationDrafts.clear();sideDrafts.clear();workspaceProjects=[];workspaceProject=null;workspaceView='projects';listLoadState.key=null;}
    client.setWorkspaceSession(status.workspaceSession);
  }
  if(cloudMode){if(client.control!==(status.remoteControl===true))lastHistory='';client.control=status.remoteControl===true;}
  supportsCreationReferences=status.supportsCreationReferences===true;
  supportedCreationSettings=Array.isArray(status.supportedCreationSettings)?status.supportedCreationSettings:[];
  enabled = status.enabled; independentWorkspace = status.protocol === 'codex-app-server'; workspaceAccountReady = status.accountReady !== false;
  $('status').textContent = enabled ? (cloudMode?(client.control?'可远程操作':'只读连接'):'已连接') : '等待连接'; $('status').classList.toggle('on', enabled);
  $('bridge').textContent = '请在 CLI 或桌面端管理桥接';
  $('create').disabled = !sideCapability('create');
  $('create').title='在所选项目中新建会话';
  for (const id of ['search','refresh']) $(id).disabled = !enabled;
  $('attach-images').disabled=!canAttach(); $('prompt').disabled = !canInteract() || !selected; $('send').disabled = !canInteract() || !selected;
  $('open-side').disabled=!enabled||!selected;
  $('open-subagents').disabled=!enabled||!selected;
  updateSideComposer();
  updateCreateButton();
  SearchControls.update();NativeSectionsSidebar.update();SectionControls.update();SectionManagement.update();TerminalControls.update();SkillManagement.update();PluginManagement.update();
  if(enabled&&!selected)welcomeState(true);
  $('prompt').placeholder=enabled?(selected?'发送新的任务…':'请先选择会话'): '请先开启本机桥接';
  if (!enabled) {
    if(selected)conversationDrafts.set(activeDraftScope+':'+selected,currentConversationDraft());
    clearImages();composeHistory=null;
    threadFlags={};catalogRevision=null;workspaceRevision=null;
    Operations.reset();
    closeSide();
    updateThreadStatuses({});
    Timeline.reset();
    subagentNavigation.reset();
    CodeHighlight.reset();navigationVersion++;listVersion++; selected = null;$('prompt').setDocument('');selectedSkills=[];selectedFiles=[];reviewComments=[];renderSkills();renderFiles();renderReviewComments(); lastHistory = ''; threads = [];
    $('threads').replaceChildren(node('div','empty-small','开启桥接后，查看本机会话。'));
    welcomeState(false);
    $('jobs').replaceChildren(); $('title').textContent = '继续你的工作'; $('cwd').textContent = '从会话列表选择一个会话';
    $('history-source').textContent = ''; $('more').hidden = true;
    $('create-dialog').close();
  }
}
function node(tag, cls, text) { const el = document.createElement(tag); if(cls) el.className=cls; if(text!==undefined) el.textContent=text; return el; }
function renderThreads() {
  const position=$('threads').scrollTop;
  if(workspaceView==='projects'){renderProjects();return;}
  const children = threads.map(t => {
    const button = node('button','thread' + (t.id === selected ? ' active' : ''));
    const row=node('div','thread-heading');
    const badge=node('span','thread-status');badge.dataset.threadStatus=t.id;
    const title=node('strong','',t.title || '未命名会话');
    if(t.unread){const unread=node('span','thread-unread');unread.setAttribute('aria-label','有未读消息');title.append(unread);}
    row.append(title,badge);
    button.append(row,node('small','',t.cwd));
    if(workspaceView==='activity'&&t.activityRead)button.style.opacity='.65';
    button.onclick = () => selectThread(t.id); return button;
  });
  $('threads').replaceChildren(...(children.length ? children : [node('div','empty-small','没有匹配的会话。')]));
  updateThreadStatuses(threadStatuses);
  $('threads').scrollTop=position;window.MobileUI?.sync();
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
  const key=JSON.stringify([draftScope(),workspaceView,workspaceProject,$('search').value,$('project-filter').value,showInactive]);
  if(more&&listLoadState.phase!=='idle')return;
  const version=++listVersion;
  if(key!==listLoadState.key){
    if(listLoadState.key)listWindows.set(listLoadState.key,{threads,projects:workspaceProjects,offset,scroll:listViewport()?.scrollTop||0});
    const cached=listWindows.get(key);offset=cached?.offset||0;threads=cached?.threads||[];if(workspaceView==='projects')workspaceProjects=cached?.projects||[];$('more').hidden=true;
    if(cached)requestAnimationFrame(()=>{if(listLoadState.key===key&&listViewport())listViewport().scrollTop=cached.scroll;});
  }
  const hasRows=(workspaceView==='projects'?workspaceProjects:threads).length>0;
  Object.assign(listLoadState,{key,phase:more?'more':hasRows?'refresh':'initial',error:null});
  $('more').disabled=true;$('more').textContent=more?'正在加载…':'加载更多';
  window.MobileUI?.sync();
  const start=more?offset:0,windowSize=more?100:Math.max(1,offset),params='?limit=100&offset='+start+'&search='+encodeURIComponent($('search').value)+'&availableOnly='+!showInactive+(workspaceView==='activity'?'&includeRead=true':'');
  const route=workspaceView==='projects'?'/projects':workspaceView==='activity'?'/activity':workspaceView==='all'?'/workspace/threads':'/projects/'+workspaceProject+'/threads';
  try{
    const suffix=workspaceView!=='projects'?'&filter='+$('project-filter').value:'';
    const result=await api(route+params+suffix);
    const rows=workspaceView==='projects'?'projects':'threads';
    while(!more&&result.nextOffset<Math.min(windowSize,result.total)){
      const next=await api(route+params.replace('offset='+start,'offset='+result.nextOffset)+suffix);
      if(version!==listVersion)return;
      result[rows].push(...next[rows]);result.nextOffset=next.nextOffset;result.total=next.total;
    }
    if(!enabled||version!==listVersion)return;
    offset=result.nextOffset;$('more').hidden=offset>=result.total;
    $('project-filter-label').hidden=workspaceView==='projects';$('clear-read').hidden=workspaceView!=='activity';
    if(workspaceView==='projects'){workspaceProjects=more?[...workspaceProjects,...result.projects]:result.projects;threads=[];renderProjects();}
    else{threads=more?[...threads,...result.threads]:result.threads;renderThreads();}
  }catch(error){
    if(version===listVersion){listLoadState.error=error.message;if(!mobileLayout.matches)notice(error.message);}
    return;
  }finally{
    if(version===listVersion){listLoadState.phase='idle';$('more').disabled=false;$('more').textContent='加载更多';window.MobileUI?.sync();}
  }
  const totals=await api('/activity?limit=1&availableOnly='+!showInactive);if(version!==listVersion)return;
  $('show-activity').textContent='动态'+(totals.total?' · '+totals.total:'');
  window.MobileUI?.sync();

  await loadHistory();
}
$('show-projects').onclick=()=>{workspaceView='projects';workspaceProject=null;$('search').value='';loadThreads().catch(e=>notice(e.message));};
$('clear-read').onclick=async()=>{const scope=draftScope();$('clear-read').disabled=true;try{await api('/notifications/clear-read',{});if(scope===draftScope())await loadThreads();}catch(e){notice(e.message);}finally{$('clear-read').disabled=false;}};
$('show-all').onclick=()=>{workspaceView='all';workspaceProject=null;$('search').value='';loadThreads().catch(e=>notice(e.message));};
$('show-activity').onclick=()=>{workspaceView='activity';workspaceProject=null;$('search').value='';loadThreads().catch(e=>notice(e.message));};
$('project-filter').onchange=()=>loadThreads().catch(e=>notice(e.message));
client.onSubmission=update=>{
  const target=update.threadId||selected,key=conversationKey(target)+':'+update.id;
  const previous=outgoingMessages.get(key);
  const item=update.begin?{...previous,...update,threadId:target,scope:draftScope()}:mergeOutgoingMessage(previous,update);
  if(item)outgoingMessages.set(key,item);else outgoingMessages.delete(key);
  reconcileOutgoing([],historyCache.get(conversationKey(target)),update.state==='sending');
};
let activityNavigationThread=null,navigationVersion=0;
async function selectThread(id, record=null) {
  if($('create-dialog').open)$('create-dialog').close();
  const navigation=++navigationVersion;
  activityNavigationThread=workspaceView==='activity'?id:null;
  subagentNavigation.reset();
  if(selected)conversationDrafts.set(activeDraftScope+':'+selected,currentConversationDraft());
  clearImages();
  activeDraftScope=draftScope();
  const draft=conversationDrafts.get(activeDraftScope+':'+id);$('prompt').setDocument(draft?.text||'',draft?.skills||[],draft?.caret||0,activeDraftScope+':'+id);attachedImages=draft?.images||[];selectedSkills=$('prompt').references;selectedFiles=draft?.files||[];reviewComments=draft?.comments||[];renderImages();renderSkills();renderFiles();renderReviewComments();
  if(mobileLayout.matches) { setThreadListOpen(false); $('title').focus({preventScroll:true}); }
  composeHistory=record?.access?{access:{...record.access,nativeReady:false}}:null;updateComposeButton();Operations.reset();
  closeSide();$('open-side').disabled=!enabled;$('open-subagents').disabled=!enabled;
  Timeline.reset();
  selected=id; skillsPicker.refresh();historyLimit=40; lastHistory=''; delete $('messages').dataset.loaded; renderThreads(); $('attach-images').disabled=!canAttach();$('prompt').disabled=!canInteract(); $('send').disabled=!canInteract();
  const thread=record||threads.find(t=>t.id===id); $('title').textContent=thread?.title || id; $('cwd').textContent=thread?.cwd || '';
  $('prompt').placeholder='发送消息…';
  window.MobileUI?.show('chat');
  const cached=historyCache.get(conversationKey(id));
  if(cached){Timeline.render(cached,$('messages'),historyImageLoader(id));$('history-source').textContent='已显示缓存，正在同步…';}
  else $('messages').replaceChildren(viewState('正在加载会话…',{loading:true}));
  renderOutgoing();
  try { await loadHistory(); } catch(e) { if(selected===id&&navigation===navigationVersion) $('messages').replaceChildren(viewState('加载失败',{detail:e.message,retry:retryHistory,symbol:'offline'})); }
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
  const wasEnabled = enabled,previousScope=draftScope();
  if(!cloudMode&&data.status.workspaceSession!==undefined&&client.workspaceSession!==data.status.workspaceSession||!wasReady || enabled !== data.status.enabled || workspaceAccountReady !== (data.status.accountReady !== false) || supportsPluginManagement!==(data.status.supportsPluginManagement===true) || supportsThreadSections!==(data.status.supportsThreadSections===true) || supportsFullTextSearch!==(data.status.supportsFullTextSearch===true) || cloudMode&&client.control!==(data.status.remoteControl===true)) applyStatus(data.status);
  if(previousScope!==draftScope())CodeHighlight.reset();
  NativeSectionsSidebar.update();SectionControls.update();SectionManagement.update();TerminalControls.update();SkillManagement.update();PluginManagement.update();
  if(enabled && (!wasEnabled||previousScope!==draftScope())) { await loadThreads(); if(!current())return; await loadHistory(); }
  if(!enabled)return;
  if(data.workspaceRevision!==undefined&&workspaceRevision!==data.workspaceRevision){
    const changed=workspaceRevision!==null;workspaceRevision=data.workspaceRevision;
    if(changed){clearTimeout(workspaceRefreshTimer);workspaceRefreshTimer=setTimeout(()=>{loadThreads().catch(e=>notice(e.message));if(supportsThreadSections)loadNativeSections();},300);}
  }
  if(data.subscription===subscription&&data.threadFlags){
    if(JSON.stringify(data.threadFlags)!==JSON.stringify(threadFlags)){
      threadFlags=data.threadFlags;
      if(selected&&threadFlags[selected]?.archived){
        conversationDrafts.set(conversationKey(selected),currentConversationDraft());
        closeSide();Operations.reset();selected=null;$('prompt').setDocument('');selectedSkills=[];selectedFiles=[];reviewComments=[];renderSkills();renderFiles();renderReviewComments();lastHistory='';
        $('messages').replaceChildren(node('div','empty-small','此会话已归档。'));
        clearImages();$('attach-images').disabled=true;$('send').disabled=true;$('prompt').disabled=true;$('open-side').disabled=true;
      }
      renderThreads();
    }
  }
  if(data.catalogRevision!==undefined&&data.catalogRevision!==catalogRevision){
    const changed=catalogRevision!==null;catalogRevision=data.catalogRevision;
    if(changed){clearTimeout(workspaceRefreshTimer);workspaceRefreshTimer=setTimeout(()=>{loadThreads().catch(e=>notice(e.message));if(supportsThreadSections)loadNativeSections();},300);}
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
  if(data.error) { composeHistory={access:{...composeHistory?.access,nativeReady:false}};updateComposeButton();Operations.reset();lastHistory='';$('history-source').textContent='同步暂不可用';if(!$('messages').dataset.loaded||$('messages').querySelector('[data-state=loading]'))$('messages').replaceChildren(viewState('加载失败',{detail:data.error,retry:retryHistory,symbol:'offline'}));else notice(data.error);return; }
  if(data.history) {
    const previousHistory=historyCache.get(conversationKey(selected));
    historyCache.set(conversationKey(selected),data.history);lastSynced.set(conversationKey(selected),Date.now());
    updateCompose(data.history);
    const viewport=$('messages').closest('.mobile-chat-scroll')||$('messages');
    if(lastHistory&&viewport.scrollHeight-viewport.scrollTop-viewport.clientHeight>100&&JSON.stringify(previousHistory?.timeline)!==JSON.stringify(data.history.timeline))$('messages').dataset.newMessages='true';
    const signature = data.history.historyRevision || JSON.stringify(data.history);
    if(signature !== lastHistory){lastHistory=signature;Timeline.render(data.history,$('messages'),historyImageLoader(data.history.thread.id));Operations.render(data.history,selected,client,notice,canInteract(),{allowed:canFork(),create:forkConversation});}
    reconcileOutgoing([],data.history);
    updateLatestButton();
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
  if(selected){const synced=lastSynced.get(conversationKey(selected));$('history-source').textContent='连接已断开，显示缓存'+(synced?' · 最近同步 '+new Date(synced).toLocaleTimeString():'');}
  if(enabled)notice('实时连接已断开，正在重连…');
}
function updateLatestButton(){const viewport=$('messages').closest('.mobile-chat-scroll')||$('messages'),away=viewport.scrollHeight-viewport.scrollTop-viewport.clientHeight>100;if(!away)delete $('messages').dataset.newMessages;$('jump-latest').hidden=!away;$('jump-latest').textContent=$('messages').dataset.newMessages?'有新消息 · 回到最新':'回到最新';}
$('messages').addEventListener('scroll',updateLatestButton,{passive:true});
$('jump-latest').onclick=()=>{const viewport=$('messages').closest('.mobile-chat-scroll')||$('messages');viewport.scrollTop=viewport.scrollHeight;updateLatestButton();};
function commentDraftActions(scope,thread){
  const current=()=>scope===draftScope()&&thread===selected;
  const stale='工作区或会话已改变，请返回原会话重新打开评论。';
  const commit=()=>{conversationDrafts.set(scope+':'+thread,currentConversationDraft());renderReviewComments();updateComposeButton();};
  return {
    current,
    add:({sourceId,path,patch,row,text})=>{if(!current())return stale;try{reviewComments.push(ReviewComments.create({sourceId,path,patch,row,text}));commit();}catch(error){return error.message;}},
    save:(original,text)=>{if(!current())return stale;const index=reviewComments.findIndex(note=>note.id===original.id);if(index<0||!ReviewComments.equal(reviewComments[index],original))return '评论已改变，请重新打开';if(!text.trim())return '评论不能为空';reviewComments[index]={...original,text};commit();},
    remove:original=>{if(!current())return stale;reviewComments=reviewComments.filter(note=>note.id!==original.id);commit();}
  };
}
$('view-changes').onclick=()=>{
  const content=$('changes-content'),scope=draftScope(),thread=selected,actions=commentDraftActions(scope,thread);content.replaceChildren();changeCommentViews=[];
  const add=(title,patch,path,sourceId)=>{
    const detail=node('details','activity');detail.append(node('summary','',title));
    detail.addEventListener('toggle',()=>{if(detail.open&&!detail.dataset.rendered){detail.dataset.rendered='true';const view=DiffReview.render(detail,{path,patch,
      comments:()=>actions.current()?reviewComments.filter(note=>note.sourceId===sourceId&&note.path===path&&note.patch===patch):[],
      onComment:sourceId&&path?note=>actions.add({...note,sourceId}):null,onEdit:actions.save,onDelete:actions.remove});changeCommentViews.push(view);}});
    content.append(detail);
  };
  for(const item of historyCache.get(conversationKey(thread))?.timeline||[]){
    const sourceId=String(item.id||item.nativeId||'');
    if(item.type==='fileChange')for(const change of item.data?.changes||[]){if(change.path)add(change.path,change.diff||JSON.stringify(change,null,2),change.path,sourceId);}
    if(item.type==='turnDiff'&&item.data?.diff)add('回合改动',item.data.diff,null,sourceId);
  }
  if(!content.childNodes.length)content.append(node('p','','当前历史没有文件改动。'));
  $('changes-dialog').showModal();
};
let commentOverviewRefresh=null;
$('review-comment-drafts').onclick=()=>{
  if(!selected)return;const scope=draftScope(),thread=selected,actions=commentDraftActions(scope,thread),content=$('review-comments-content'),groups=new Map();content.replaceChildren();
  commentOverviewRefresh=()=>{
    if(!$('review-comments-dialog').open)return;
    if(!actions.current()){content.replaceChildren();groups.clear();content.append(node('p','','会话已改变，请重新打开评论。'));return;}
    const active=new Set(reviewComments.map(note=>note.id));for(const [id,entry]of groups)if(!active.has(id)){entry.group.remove();groups.delete(id);}
    for(const note of reviewComments){let entry=groups.get(note.id);if(!entry||entry.note!==note){const group=node('div','review-comment-group');group.append(node('p','review-comment-path',note.path),node('pre','review-comment-source',note.lineText),DiffReview.commentCard(note,{save:actions.save,remove:actions.remove}));if(entry)entry.group.replaceWith(group);entry={note,group};groups.set(note.id,entry);}if(entry.group.parentNode!==content)content.append(entry.group);}
  };
  $('review-comments-dialog').showModal();commentOverviewRefresh();
};
$('review-comments-close').onclick=()=>$('review-comments-dialog').close();
$('changes-wrap').onclick=()=>{const wrapping=$('changes-dialog').classList.toggle('wrap-diff-lines');$('changes-wrap').setAttribute('aria-pressed',String(wrapping));};
$('changes-close').onclick=()=>$('changes-dialog').close();
$('expand-events').onclick=()=>Timeline.setExpanded(true);
$('open-side').onclick=()=>{if(!enabled||!selected)return;sideOpen=true;$('side-drawer').hidden=false;document.body.classList.add('side-open');$('side-discovery').textContent='正在查找临时聊天…';loadHistory();};
async function sideLifecycle(action, launch=null){
  if(sideLifecycleBusy||!selected||!sideCapability(action==='create'?'create':'stop'))return false;
  const parent=selected,target=sideSelected,scope=draftScope();
  const current=()=>sideOpen&&selected===parent&&draftScope()===scope;
  sideLifecycleBusy=true;updateSideComposer();
  try{
    const job=action==='create'?await client.createSide(parent,current):await client.closeSide(parent,target,current);
    if(!current())return;
    if(job.state!=='completed')throw Error(job.error||'结果尚未确认，请核对原请求');
    sideSelected=action==='create'?job.createdThreadId:null;sideSignature='';
    resetSideComposer();SideTimeline.reset();loadHistory();
    if(launch){
      $('side-prompt').value=launch.text;sideDrafts.set(sideDraftKey,launch.text);launch.onCreated?.();
      if(launch.send&&launch.text.trim()){
        if(!sideCapability('send'))throw Error('发送权限已改变，内容保留在临时聊天草稿中');
        const child=sideSelected;
        const sent=await client.sideAction(parent,child,'compose',{prompt:launch.text},()=>current()&&sideSelected===child);
        if(!current()||sideSelected!==child)return false;
        if(['failed','uncertain'].includes(sent.state))throw Error(sent.error||'发送结果待核对，内容保留在临时聊天草稿中');
        if($('side-prompt').value===launch.text){$('side-prompt').value='';sideDrafts.set(sideDraftKey,'');}
      }
    }
    return true;
  }catch(error){if(current())$('side-discovery').textContent=error.message;return false;}
  finally{sideLifecycleBusy=false;updateSideComposer();}
}
async function launchSide(text='',send=false,onCreated=null){
  if(!composeHistory?.controls?.supportedOperations?.includes('side-create')||!sideCapability('create')||(send&&text.trim()&&!sideCapability('send'))){notice('当前会话暂不支持创建临时聊天或权限不足');return false;}
  sideOpen=true;$('side-drawer').hidden=false;document.body.classList.add('side-open');
  return sideLifecycle('create',{text,send,onCreated});
}
Timeline.configureSideSelection(text=>launchSide(text,false));
$('create-side').onclick=()=>sideLifecycle('create');
$('end-side').onclick=()=>sideLifecycle('close');
$('close-side').onclick=()=>{closeSide();loadHistory();};
$('side-select').onchange=()=>{sideHistoryLimit=40;sideSelected=$('side-select').value||null;sideSignature='';resetSideComposer();SideTimeline.reset();delete $('side-messages').dataset.loaded;$('side-messages').replaceChildren(node('div','empty-small',sideSelected?'正在读取临时聊天…':'请选择临时聊天'));loadHistory();};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&sideOpen){closeSide();loadHistory();}});
$('collapse-events').onclick=()=>Timeline.setExpanded(false);
function renderJobs(jobs) {
  $('jobs').replaceChildren(...jobs.slice(0,6).map(job=> {
    const row=node('div','job'+(['failed','uncertain'].includes(job.state)?' error':''));
    const name=job.kind.startsWith('operation:')?(Operations.labels[job.kind.slice(10)]||'会话操作'):(job.kind==='create'?'新建会话':job.kind==='fork'?'分叉会话':job.kind==='side-create'?'新建临时聊天':job.kind==='side-close'?'结束临时聊天':'发送任务');
    const state=job.kind.startsWith('operation:')&&job.state==='completed'?'原生入口已响应':(states[job.state]||job.state);
    const label=node('div','',name+' · '+state);
    label.append(node('small','',job.error || job.result?.goalPauseError || job.id)); row.append(label);
    if(job.createdThreadId){
      const side=job.kind==='side-create',open=node('button','quiet',side?'打开临时聊天':'打开会话');
      open.onclick=async()=>{const scope=draftScope();await loadThreads();if(scope!==draftScope())return;
        await selectThread(side?job.parentId:job.createdThreadId);if(scope!==draftScope())return;
        if(side){sideSelected=job.createdThreadId;resetSideComposer();$('open-side').click();}
      };row.append(open);
    }
    if(['uncertain','failed','preparing','dispatching','accepted'].includes(job.state)){const check=node('button','quiet','核对结果');check.onclick=async()=>{const scope=draftScope();check.disabled=true;try{const result=await api('/jobs/'+encodeURIComponent(job.id));if(scope!==draftScope())return;reconcileOutgoing([result]);label.firstChild.textContent=name+' · '+(states[result.state]||result.state);label.querySelector('small').textContent=result.error||result.id;}catch(e){if(scope===draftScope())notice(e.message);}finally{check.disabled=false;}};row.append(check);}
    if(job.state==='uncertain'){ const ack=node('button','quiet','已在 App 核对');ack.disabled=!canWrite();ack.onclick=async()=>{if(confirm('确认已在 Codex App 核对这个请求？这会清除待核对标记，不会重发。')){try{await api('/jobs/'+job.id+'/acknowledge',{confirmed:true});await tick();}catch(e){notice(e.message);}}};row.append(ack); }
    return row;
  }));
}
$('pairing-form').onsubmit=async event=>{
  event.preventDefault();$('pairing-error').hidden=true;
  $('pair').disabled=true;
  try {
    historyCache.clear();outgoingMessages.clear();listWindows.clear();lastSynced.clear();
    await client.pair($('token').value,cloudMode?$('login-username').value:undefined);
    if(cloudMode){$('pairing').hidden=true;$('token').value='';window.WorkspaceBinding?.offerPending();}
    if(!cloudMode||client.device)applyStatus(await api('/status'));$('pairing').hidden=true;$('token').value='';
    client.connect();if(enabled)await loadThreads();
  } catch(e){if(!client.token){$('pairing-error').textContent=e.message;$('pairing-error').hidden=false;}else notice(e.message);}
  finally{$('pair').disabled=false;if(cloudMode)client.connect();}
};
const newDrafts=new Map();let newDraft={text:'',images:[],references:[],caret:0,busy:false};
const isMention=reference=>/^(app|plugin):\/\//.test(reference.path);
let supportsCreationReferences=false,supportedCreationSettings=[];
let createProjectScope=null,createProjectVersion=0,createProjectsReady=false,newDraftScope=null,newModelChoices=[];
function newModelCaption(){const id=newDraft.settings?.model;const label=(newModelChoices.find(value=>value.id===id)?.name||id||'默认模型').replace(/^gpt-/i,'');const effort=newDraft.settings?.effort;return label+(effort?' '+effort.charAt(0).toUpperCase()+effort.slice(1):'')+' ⌄';}
function updateNewEfforts(preserve=true){const choice=newModelChoices.find(v=>v.id===$('new-model').value);$('new-effort-label').hidden=!choice;
  $('new-effort').replaceChildren(...(choice?.efforts||[]).map(v=>new Option(v,v)));
  if(choice){const saved=preserve&&newDraft.settings?.model===choice.id?newDraft.settings.effort:null;if(saved&&!choice.efforts.includes(saved)){const unavailable=new Option('当前不可用：'+saved,saved);unavailable.disabled=true;$('new-effort').append(unavailable);}$('new-effort').value=saved||choice.defaultEffort||choice.efforts[0];}
}
$('new-model').onchange=()=>{updateNewEfforts(false);const values={...newDraft.settings};if($('new-model').value){values.model=$('new-model').value;values.effort=$('new-effort').value;}else {if(values.collaborationMode){$('new-model').value=values.model;updateNewEfforts();notice('指定工作模式时需保留模型；可先恢复项目默认工作模式');return;}delete values.model;delete values.effort;}newDraft.settings=Object.keys(values).length?values:null;syncNewMode();updateCreateButton();};
$('new-effort').onchange=()=>{if(newDraft.settings){newDraft.settings.effort=$('new-effort').value;syncNewMode();updateCreateButton();}};
function syncNewMode(){if(newDraft.settings?.collaborationMode){newDraft.settings.collaborationMode.settings={...newDraft.settings.collaborationMode.settings,model:newDraft.settings.model,reasoning_effort:newDraft.settings.effort??null};}}
function creationPermissionAvailable(settings=newDraft.settings){return sideCapability('create')&&(!settings||!Object.keys(settings).some(key=>!['model','effort'].includes(key))||sideCapability('edit'));}
function creationSelectionValid(settings=newDraft.settings){if(!creationPermissionAvailable(settings))return false;if(settings&&Object.keys(settings).some(key=>!['model','effort'].includes(key)&&!supportedCreationSettings.includes(key)))return false;if(settings?.model){const choice=newModelChoices.find(value=>value.id===settings.model);return !!choice&&choice.efforts.includes(settings.effort);}return !settings?.collaborationMode;}
function canConfigureCreation(){return sideCapability('create')&&sideCapability('edit')&&createProjectScope===draftScope()&&!newDraft.busy&&!newDraft.pending;}
function renderNewConfiguration(){const scope=draftScope();$('new-configuration-home').hidden=!supportedCreationSettings.some(key=>!['model','effort'].includes(key));CreationSettings.render($('new-configuration-settings'),{settings:()=>newDraft.settings,fields:supportedCreationSettings,editable:canConfigureCreation,change:(key,value)=>{if(scope!==draftScope()||!canConfigureCreation()||!supportedCreationSettings.includes(key))return;const settings={...newDraft.settings};if(!value)delete settings[key];else if(key==='collaborationMode'){if(!settings.model){notice('指定工作模式前，请先选择模型');renderNewConfiguration();return;}settings[key]={mode:value,settings:{...settings[key]?.settings,model:settings.model,reasoning_effort:settings.effort??null,developer_instructions:settings[key]?.settings?.developer_instructions??null}};}else if(value!=='custom')settings[key]=value;newDraft.settings=Object.keys(settings).length?settings:null;updateCreateButton();}});}
async function loadNewModels(scope,version){newModelChoices=[];$('new-model').disabled=true;$('new-model-status').textContent='正在读取模型…';
  try{const result=await api('/models');if(scope!==draftScope()||version!==createProjectVersion)return;
    if(!Array.isArray(result.models))throw Error('模型目录尚未同步');newModelChoices=result.models;
    $('new-model').replaceChildren(new Option('项目默认',''),...newModelChoices.map(v=>new Option(v.name||v.id,v.id)));
    const selected=newDraft.settings?.model;const unavailable=selected&&!newModelChoices.some(v=>v.id===selected);if(unavailable){const option=new Option('当前不可用：'+selected,selected);option.disabled=true;$('new-model').append(option);}
    $('new-model').value=newDraft.settings?.model||'';updateNewEfforts();$('new-model').disabled=false;$('new-model-status').textContent=unavailable?'此前选择的模型已不可用，请重新选择':newModelChoices.length?'':'使用项目默认设置';
  }catch(e){if(scope===draftScope()&&version===createProjectVersion){newModelChoices=[];$('new-model').replaceChildren(new Option(newDraft.settings?.model||'项目默认',newDraft.settings?.model||''));$('new-effort-label').hidden=true;$('new-model-status').textContent=e.message+'；已保留此前配置';}}finally{if(scope===draftScope()&&version===createProjectVersion)updateCreateButton();}
}
function canCreateProject(){return sideCapability('create')&&createProjectsReady&&createProjectScope===draftScope()&&!!$('new-project').value;}
function updateCreateButton(){const pending=newDraft.pending;if(pending)$('submit-create').dataset.pending='true';else delete $('submit-create').dataset.pending;const editable=canCreateProject()&&!newDraft.busy&&!pending;
  $('submit-create').disabled=!editable||!creationSelectionValid()||(!$('new-prompt').wireText.trim()&&!newDraft.images.length&&!$('new-prompt').references.length);
  $('new-prompt').disabled=!sideCapability('create')||newDraft.busy||pending;$('new-attach-images').disabled=!editable||newDraft.images.length>=3;
  for(const id of ['new-attach-skills','new-attach-mentions'])$(id).disabled=!editable||!supportsCreationReferences;
  newSkillsPicker.refresh();newMentionsPicker.refresh();renderNewConfiguration();window.MobileUI?.updateAttachments();
  $('new-model-details').querySelector('summary').textContent=newModelCaption();
}
function saveNewDocument(){newDraft.text=$('new-prompt').value;newDraft.references=$('new-prompt').references;newDraft.caret=$('new-prompt').caret;}
function newReferencePicker(mentions){return SkillsPicker.create({title:mentions?'应用与插件':'技能',field:mentions?'mentions':'skills',
  load:project=>api('/creation/references?projectId='+encodeURIComponent(project)),
  current:()=>createProjectsReady?{id:$('new-project').value,key:JSON.stringify([draftScope(),$('new-project').value,createProjectVersion])}:null,
  selection:()=>$('new-prompt').references.filter(r=>isMention(r)===mentions),
  change:refs=>{$('new-prompt').references=[...$('new-prompt').references.filter(r=>isMention(r)!==mentions),...refs];saveNewDocument();updateCreateButton();},
  editable:()=>supportsCreationReferences&&canCreateProject()&&!newDraft.busy&&!newDraft.pending});}
const newSkillsPicker=newReferencePicker(false),newMentionsPicker=newReferencePicker(true);
$('new-attach-skills').onclick=()=>newSkillsPicker.open();$('new-attach-mentions').onclick=()=>newMentionsPicker.open();
function renderNewImages(){const root=$('new-image-previews');root.replaceChildren();root.hidden=!newDraft.images.length;
  for(const item of newDraft.images){const card=node('div','image-preview'),img=document.createElement('img');img.src=item.url;img.alt=item.name;const remove=node('button','','×');remove.type='button';remove.setAttribute('aria-label','移除图片 '+item.name);remove.disabled=newDraft.busy||newDraft.pending;remove.onclick=()=>{newDraft.images=newDraft.images.filter(v=>v!==item);renderNewImages();};card.append(img,remove);root.append(card);}updateCreateButton();}
$('new-attach-images').onclick=()=>$('new-image-files').click();
$('new-image-files').onchange=async()=>{const files=[...$('new-image-files').files];$('new-image-files').value='';if(!canCreateProject()||newDraft.busy)return;const scope=draftScope(),draft=newDraft;draft.busy=true;updateCreateButton();
  try{if(newDraft.images.length+files.length>3)throw Error('每次最多添加 3 张图片');const prepared=[];for(const file of files)prepared.push(await prepareImage(file));draft.images.push(...prepared);}
  catch(e){if(scope===draftScope())$('create-error').textContent=e.message;}finally{draft.busy=false;if(draft===newDraft)renderNewImages();}};
$('new-project').onchange=()=>{newDraft.project=$('new-project').value;updateCreateButton();};$('new-prompt').addEventListener('input',()=>{saveNewDocument();updateCreateButton();});
$('create').onclick=async()=>{
  const scope=draftScope(),version=++createProjectVersion;if(newDraftScope!==scope){newDraft=newDrafts.get(scope)||{text:'',images:[],references:[],caret:0,busy:false};newDrafts.set(scope,newDraft);$('new-prompt').setDocument(newDraft.text,newDraft.references,newDraft.caret,scope);newDraftScope=scope;}createProjectScope=scope;createProjectsReady=false;renderNewImages();
  $('new-project').replaceChildren(new Option('正在加载项目…',''));$('create-error').textContent='';if(mobileLayout.matches)$('create-dialog').showModal();else $('create-dialog').show();updateCreateButton();loadNewModels(scope,version);
  try{let offset=0,total=1,projects=[];
    while(offset<total){const page=await api('/projects?limit=100&offset='+offset);if(scope!==draftScope()||version!==createProjectVersion)return;projects.push(...page.projects.filter(p=>p.cwd||p.canCreate===true));offset=page.nextOffset;total=page.total;}
    $('new-project').replaceChildren(new Option('选择项目',''),...projects.map(p=>new Option(p.name,p.id)));
    const preferred=newDraft.project||workspaceProject;if(projects.some(p=>p.id===preferred))$('new-project').value=preferred;else if(projects.length===1)$('new-project').value=projects[0].id;
    createProjectsReady=true;if(!projects.length)$('create-error').textContent='暂无可创建会话的项目';
  }catch(e){if(scope===draftScope()&&version===createProjectVersion)$('create-error').textContent=e.message;}
  finally{updateCreateButton();}
};
mobileLayout.addEventListener('change',()=>{if($('create-dialog').open){$('create-dialog').addEventListener('close',()=>{$('create').onclick();},{once:true});$('create-dialog').close();}});
$('create-dialog').addEventListener('close',()=>{saveNewDocument();createProjectVersion++;createProjectsReady=false;newSkillsPicker.refresh();newMentionsPicker.refresh();});
$('close-dialog').onclick=()=>$('create-dialog').close();
$('create-form').onsubmit=async e=>{
  e.preventDefault();if(!canCreateProject()||newDraft.busy||newDraft.pending)return;
  const scope=draftScope(),version=createProjectVersion,draft=newDraft,settings=JSON.parse(JSON.stringify(newDraft.settings||null)),project=$('new-project').value,raw=$('new-prompt').value,prompt=$('new-prompt').wireText.trim(),references=$('new-prompt').references,images=newDraft.images.map(v=>v.url);if(!prompt&&!images.length&&!references.length)return;
  if(!creationSelectionValid()){$('create-error').textContent='配置不可用，请核对模型、当前能力以及创建与编辑权限';return;}
  if(references.length&&!supportsCreationReferences){$('create-error').textContent='当前工作区暂不支持引用，请恢复连接或移除引用后重试';return;}
  draft.pending=true;updateCreateButton();
  try{const job=await client.createInProject(project,prompt,()=>canCreateProject()&&creationSelectionValid(settings)&&scope===draftScope()&&version===createProjectVersion&&newDraft===draft&&project===$('new-project').value,images,settings,references.filter(r=>!isMention(r)),references.filter(isMention));
    if(scope!==draftScope()||version!==createProjectVersion||newDraft!==draft)return;if(!['accepted','completed','inProgress'].includes(job.state)||!job.createdThreadId)throw Error(job.error||'结果待核对，请勿重复发送');
    $('create-dialog').close();if($('new-prompt').value===raw&&JSON.stringify($('new-prompt').references)===JSON.stringify(references)){$('new-prompt').setDocument('');saveNewDocument();}if(JSON.stringify(newDraft.images.map(v=>v.url))===JSON.stringify(images)){newDraft.images=[];renderNewImages();}
    await selectThread(job.createdThreadId);
  }catch(e){if(scope===draftScope()&&version===createProjectVersion&&newDraft===draft)$('create-error').textContent=e.message;}
  finally{draft.pending=false;updateCreateButton();}
};
let attachedImages=[],imageGeneration=0,imageBusy=false,selectedSkills=[],selectedFiles=[];
const skillsPicker=SkillsPicker.create({load:thread=>client.skills(thread),current:()=>selected?{id:selected,key:conversationKey(selected)}:null,
  selection:()=>selectedSkills.filter(r=>!isMention(r)),change:skills=>{selectedSkills=[...selectedSkills.filter(isMention),...skills];renderSkills();updateComposeButton();},editable:()=>canAttach()&&composeHistory?.controls?.supportsSkills===true});
$('attach-skills').onclick=()=>skillsPicker.open();
const projectFilesPicker=ProjectFilesPicker.create({load:(id,query)=>client.projectFiles(id,query),current:()=>selected?{id:selected,key:conversationKey(selected)}:null,selection:()=>selectedFiles,change:files=>{selectedFiles=files;renderFiles();updateComposeButton();},editable:()=>canAttach()&&sideCapability('files')&&composeHistory?.controls?.supportsFileReferences===true});
$('attach-files').onclick=()=>projectFilesPicker.open();
function renderFiles(){const root=$('file-references');root.replaceChildren();root.hidden=!selectedFiles.length;for(const file of selectedFiles){const remove=node('button','skill-chip','▤ '+file.name+' ×');remove.type='button';remove.setAttribute('aria-label','移除项目文件 '+file.name);remove.disabled=!canAttach();remove.onclick=()=>{if(!canAttach())return;selectedFiles=selectedFiles.filter(item=>item.path!==file.path);renderFiles();updateComposeButton();};root.append(remove);}projectFilesPicker.refresh();}
const mentionPicker=SkillsPicker.create({title:'应用与插件',field:'mentions',load:id=>client.mentions(id),current:()=>selected?{id:selected,key:conversationKey(selected)}:null,
  selection:()=>selectedSkills.filter(isMention),change:refs=>{selectedSkills=[...selectedSkills.filter(r=>!isMention(r)),...refs];renderSkills();updateComposeButton();},editable:()=>canAttach()&&composeHistory?.controls?.supportsMentions===true});
$('attach-mentions').onclick=()=>mentionPicker.open();
function renderSkills(){
  $('prompt').references=selectedSkills;selectedSkills=$('prompt').references;
  $('attach-mentions').disabled=!canAttach()||composeHistory?.controls?.supportsMentions!==true;mentionPicker.refresh();
  skillsPicker.refresh();
}

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
  }catch(e){notice(e.message);}finally{imageBusy=false;renderImages();renderSkills();renderFiles();$('attach-images').disabled=!canAttach();updateComposeButton();}
}
$('attach-images').onclick=()=>$('image-files').click();
$('image-files').onchange=()=>{addImages($('image-files').files);$('image-files').value='';};
$('prompt').addEventListener('paste',event=>{const files=[...event.clipboardData.items].filter(i=>i.kind==='file'&&i.type.startsWith('image/')).map(i=>i.getAsFile()).filter(Boolean);if(files.length){event.preventDefault();addImages(files);}});
Timeline.configureQuestions({
  canSend:thread=>canInteract()&&sideCapability('send')&&selected===thread,
  submit:async(thread,prompt)=>{
    if(!canInteract()||!sideCapability('send')||selected!==thread)throw Error('会话或控制权限已改变');
    const job=await client.submit('compose',thread,prompt,[],()=>selected===thread&&canInteract());
    if(['failed','uncertain'].includes(job.state))throw Error(job.error||'请求未确认，请核对结果');
  }
});
$('composer').onsubmit=async e=>{
  e.preventDefault();if(imageBusy||!canInteract()||!selected)return;
  const prompt=$('prompt').wireText.trim();
  const commandScope=draftScope(),commandTarget=selected,commandDraft=$('prompt').value;
  const commandCurrent=()=>draftScope()===commandScope&&selected===commandTarget&&canInteract();
  const clearCommand=()=>{if(commandCurrent()&&$('prompt').value===commandDraft){$('prompt').setDocument('',[],0,conversationKey(commandTarget));updateComposeButton();}};
  if(ComposerCommands.parse(prompt)){
    let continuation=null;
    imageBusy=true;updateComposeButton();
    try{await ComposerCommands.run(prompt,{history:()=>composeHistory,allowed:sideCapability,hasAttachments:()=>attachedImages.length>0||selectedSkills.length>0||selectedFiles.length>0||reviewComments.length>0,notice,current:commandCurrent,
      side:argument=>launchSide(argument,true,clearCommand),fork:()=>forkConversation(commandTarget,null,commandCurrent,clearCommand),open:openCommandPanel,clear:clearCommand,
      operation:(action,fields)=>client.operation(commandTarget,action,fields,commandCurrent),
      continueWith:argument=>{if(commandCurrent()&&$('prompt').value===commandDraft)continuation=argument;}
    });}finally{imageBusy=false;updateComposeButton();composerCommandMenu.refresh();}
    if(continuation!==null&&commandCurrent()&&$('prompt').value===commandDraft){$('prompt').setDocument(continuation,[],continuation.length,conversationKey(commandTarget));await submitComposerPrompt();}
    return;
  }
  await submitComposerPrompt();
};
async function submitComposerPrompt(){
  if(imageBusy||!canInteract()||!selected)return;
  const prompt=ReviewComments.prompt($('prompt').wireText.trim(),reviewComments);
  const stopOnly=!prompt&&!attachedImages.length&&!selectedSkills.length&&!selectedFiles.length&&composeHistory?.runtime?.type==='active';
  if(!sideCapability(stopOnly?'stop':'send'))return;
  if(selectedFiles.length&&(!sideCapability('files')||composeHistory?.controls?.supportsFileReferences!==true)){notice('当前会话暂不支持项目文件引用，请恢复连接或移除引用后重试');return;}
  if(selectedSkills.some(r=>!isMention(r))&&composeHistory?.controls?.supportsSkills!==true){notice('当前会话暂不支持技能，请恢复连接或移除技能后重试');return;}
  if(selectedSkills.some(isMention)&&composeHistory?.controls?.supportsMentions!==true){notice('当前会话暂不支持应用或插件引用，请恢复连接或移除引用后重试');return;}
  if(!prompt&&!attachedImages.length&&!selectedSkills.length&&!selectedFiles.length){
    if(composeHistory?.controls?.activeTurnId&&composeHistory.runtime?.type==='active')await client.operation(selected,'interrupt',{expectedTurnId:composeHistory.controls.activeTurnId}).catch(e=>notice(e.message));
    return;
  }
  const target=selected,generation=imageGeneration,sentScope=draftScope(),sentKey=conversationKey(selected),sent=currentConversationDraft();imageBusy=true;renderImages();renderSkills();renderFiles();$('send').disabled=true;$('attach-images').disabled=true;
  try{const current=()=>selected===target&&generation===imageGeneration&&canInteract();
    const queue=composeHistory?.runtime?.type==='active'&&!$('followup-label').hidden&&$('followup-mode').value==='queue';
    if(composeHistory?.runtime?.type==='active'&&composeHistory?.controls?.canSteer===false&&!queue)throw Error('当前审查暂不接受补充，请等待队列同步或审查结束');
    const job=queue?await client.operation(target,'queue-add',{prompt,images:attachedImages.map(i=>i.url),skills:selectedSkills.filter(r=>!isMention(r)).map(({name,path})=>({name,path})),mentions:selectedSkills.filter(isMention).map(({name,path})=>({name,path})),files:selectedFiles,queueFingerprint:composeHistory.queue.fingerprint},current):await client.submit('compose',target,prompt,attachedImages.map(i=>i.url),current,selectedSkills.filter(r=>!isMention(r)).map(({name,path})=>({name,path})),selectedSkills.filter(isMention).map(({name,path})=>({name,path})),selectedFiles);
    if(['failed','uncertain'].includes(job.state))throw Error(job.error||'请求未成功，请先核对原请求');
    if(draftScope()===sentScope){
      const visible=selected===target;
      const draft=visible?currentConversationDraft():conversationDrafts.get(sentKey);
      if(draft){
        if(draft.text===sent.text)draft.text='';
        if(JSON.stringify(draft.images)===JSON.stringify(sent.images))draft.images=[];
        if(JSON.stringify(draft.skills)===JSON.stringify(sent.skills))draft.skills=[];
        if(JSON.stringify(draft.files||[])===JSON.stringify(sent.files))draft.files=[];
        draft.comments=ReviewComments.didSubmit(draft.comments||[],sent.comments);
        conversationDrafts.set(sentKey,draft);
        if(visible){$('prompt').setDocument(draft.text,draft.skills,0,sentKey);attachedImages=draft.images;selectedSkills=$('prompt').references;selectedFiles=draft.files||[];reviewComments=draft.comments;renderImages();renderSkills();renderFiles();renderReviewComments();}
      }
    }
  }catch(e){if(draftScope()===sentScope&&selected===target)notice(e.message);}
  finally{imageBusy=false;renderImages();renderSkills();renderFiles();$('attach-images').disabled=!canAttach();updateComposeButton();}
}
$('prompt').onkeydown=e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)){e.preventDefault();if(!$('send').disabled)$('composer').requestSubmit();}};
$('refresh').onclick=()=>loadThreads().catch(e=>notice(e.message));
$('more').onclick=()=>loadThreads(true).catch(e=>notice(e.message));
let searchTimer;$('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadThreads().catch(e=>notice(e.message)),300);};
async function tick(){
  if(refreshBusy || !client.token)return;refreshBusy=true;
  try{const status=await api('/status');const justEnabled=status.enabled&&!enabled;
    if(!cloudMode&&status.workspaceSession!==undefined&&client.workspaceSession!==status.workspaceSession||status.enabled!==enabled || workspaceAccountReady !== (status.accountReady !== false) || cloudMode&&client.control!==(status.remoteControl===true)){applyStatus(status);if(enabled)renderThreads();}
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
  await client.initialize();window.WorkspaceBinding?.offerPending();
  if(previous!==client.device){
    client.close();client.epoch++;client.selection=null;
    applyStatus({enabled:false});
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
      applyStatus({enabled:false});
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
  const labels={view:'查看会话',create:'新建会话',send:'发送消息',stop:'停止任务',edit:'编辑会话与设置',files:'查看和下载文件',approve:'处理审批',resetQuota:'使用额度重置卡'};
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
    setupConsoleLogin(client,async()=>{await client.initialize();window.WorkspaceBinding?.offerPending();$('pairing').hidden=true;if(client.device)applyStatus(await api('/status'));client.connect();if(enabled)await loadThreads();});
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
      applyStatus({enabled:false});
      try{applyStatus(await api('/status'));if(enabled)await loadThreads();}catch(e){notice(e.message);}finally{client.connect();}
    };
    $('console-logout').onclick=async()=>{
      subagentNavigation.reset();
      $('console-logout').disabled=true;
      client.close();client.epoch++;client.selection=null;
      try{await client.consoleRequest('logout',{});historyCache.clear();outgoingMessages.clear();listWindows.clear();lastSynced.clear();client.token='';applyStatus({enabled:false});conversationDrafts.clear();sideDrafts.clear();newDrafts.clear();newDraftScope=null;newDraft={text:'',images:[],references:[],caret:0,busy:false};$('new-prompt').setDocument('');renderNewImages();$('create-dialog').close();$('pairing').hidden=false;$('pairing-error').hidden=true;$('requests-dialog').close();$('connection-requests').replaceChildren();$('account-menu').open=false;$('token').value='';$('token').focus();}catch(e){notice(e.message);client.connect();}finally{$('console-logout').disabled=false;}
    };
    try{await client.initialize();window.WorkspaceBinding?.offerPending();}catch(e){if(e.message!=='请先登录云端控制台'){$('pairing-error').textContent=e.message;$('pairing-error').hidden=false;}}
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

function draftScope(){return cloudMode?client.storageScope:location.origin+':'+client.epoch+':'+(client.workspaceSession||'unconfirmed');}
let composeHistory=null;
function canAttach(){return canInteract()&&sideCapability('send')&&!!selected&&['idle','running','waiting'].includes(composeHistory?.status?.state)&&!imageBusy;}
function updateCompose(history){composeHistory=history;if(history.thread?.title)$('title').textContent=history.thread.title;updateComposeButton();$('attach-images').disabled=!canAttach();window.MobileUI?.sync();composerCommandMenu?.refresh();}
function updateComposeButton(){VoiceControls.update();ArchiveControls.update();RenameControls.update();SectionControls.update();SectionManagement.update();TerminalControls.update();SkillManagement.update();PluginManagement.update();updateComposerContext();
  $('composer').hidden=conversationReadOnly();
  $('attach-files').hidden=composeHistory?.controls?.supportsFileReferences!==true;$('attach-files').disabled=!canAttach()||!sideCapability('files');renderFiles();
  $('attach-mentions').hidden=composeHistory?.controls?.supportsMentions!==true;
  $('attach-skills').hidden=composeHistory?.controls?.supportsSkills!==true;
  $('attach-skills').disabled=!canAttach();skillsPicker.refresh();
  $('prompt').disabled=!canInteract()||!selected;
  const running=composeHistory?.runtime?.type==='active';
  const command=ComposerCommands.parse($('prompt').wireText.trim());
  const commandAllowed=command&&!reviewComments.length&&!selectedFiles.length&&ComposerCommands.available(command.name,{history:()=>composeHistory,allowed:sideCapability})&&(!['plan','side'].includes(command.name)||!command.argument||sideCapability('send'));
  const stopOnly=running&&!$('prompt').value.trim()&&!attachedImages.length&&!selectedSkills.length&&!selectedFiles.length&&!reviewComments.length;
  $('send').disabled=!canInteract()||!selected||imageBusy||!(commandAllowed||sideCapability(stopOnly?'stop':'send'));
  const supported=composeHistory?.controls?.supportedOperations;
  $('followup-label').hidden=!running||!composeHistory?.queue?.fingerprint||!supported?.includes('queue-add');
  $('followup-mode').querySelector('[value=steer]').disabled=running&&composeHistory?.controls?.canSteer===false;
  if(running&&composeHistory?.controls?.canSteer===false)$('followup-mode').value='queue';
  $('followup-mode').disabled=!canInteract()||imageBusy;
  const inputPresent=!!$('prompt').value.trim()||attachedImages.length>0||selectedSkills.length>0||selectedFiles.length>0||reviewComments.length>0;
  if(!commandAllowed&&running&&inputPresent&&composeHistory?.controls?.canSteer===false&&$('followup-label').hidden)$('send').disabled=true;
  const label=running&&!$('prompt').value.trim()&&!attachedImages.length&&!selectedSkills.length&&!selectedFiles.length&&!reviewComments.length?'停止任务':!$('followup-label').hidden&&$('followup-mode').value==='queue'?'加入队列 ↑':'发送任务 ↑';
  $('send').textContent=label;$('send').setAttribute('aria-label',label);$('send').dataset.action=stopOnly?'stop':'send';

}
$('prompt').addEventListener('input',()=>{selectedSkills=$('prompt').references;updateComposeButton();});
try{$('followup-mode').value=localStorage.getItem('carryon-followup-mode')==='steer'?'steer':'queue';}catch{}
$('followup-mode').onchange=()=>{try{localStorage.setItem('carryon-followup-mode',$('followup-mode').value);}catch{}updateComposeButton();};
async function openNotification(event){
  const scope=draftScope(),version=navigationVersion+1;await selectThread(event.threadId);if(version!==navigationVersion||scope!==draftScope())return;
  activityNavigationThread=null;
  for(let limit=40;limit<=4000;limit=Math.min(4000,limit*2)){
    const snapshot=await api('/threads/'+encodeURIComponent(event.threadId)+'/history?limit='+limit);
    if(version!==navigationVersion||scope!==draftScope()||selected!==event.threadId)return;
    if(snapshot.thread?.id!==event.threadId)throw Error('通知历史与目标会话不匹配');
    const live=historyCache.get(conversationKey(event.threadId));
    const display=live&&Timeline.notificationAnchor(live,event)?live:snapshot;
    const anchor=Timeline.notificationAnchor(display,event);
    if(anchor||!snapshot.historyWindow?.hasMore||limit===4000){
      Timeline.render(display,$('messages'),historyImageLoader(event.threadId));lastHistory='';
      if(anchor)Timeline.navigateTo(anchor);historyLimit=Math.max(historyLimit,limit);await loadHistory();return;
    }
  }
}
const feed=new NotificationFeed({request:api,storage:localStorage,onEvent:async(event,remind)=>{
  if(!remind||document.visibilityState!=='visible')return;
  const scope=draftScope();notice(({done:'任务完成',failed:'任务失败',approval:'有待处理请求',message:'有新消息'}[event.kind]||'会话更新')+' · '+(event.title||''));
  const open=node('button','quiet','查看');open.onclick=()=>{if(scope===draftScope())openNotification(event).catch(e=>notice(e.message));};$('notice').append(open);
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

function resumeConnection(){if(document.visibilityState==='visible'&&client.token){client.resume();if(enabled)loadThreads().catch(()=>{});}}
document.addEventListener('visibilitychange',resumeConnection);
window.addEventListener('pageshow',resumeConnection);
window.addEventListener('online',resumeConnection);

let refreshTouch=null;
const sidebar=document.querySelector('aside');
sidebar.addEventListener('touchstart',event=>{if(sidebar.scrollTop===0&&$('threads').scrollTop===0&&event.touches.length===1)refreshTouch=event.touches[0].clientY;},{passive:true});
sidebar.addEventListener('touchend',event=>{if(refreshTouch!==null&&event.changedTouches[0]?.clientY-refreshTouch>80&&enabled)loadThreads().catch(e=>notice(e.message));refreshTouch=null;},{passive:true});
sidebar.addEventListener('touchcancel',()=>{refreshTouch=null;},{passive:true});

VoiceControls.configure({api,client,target:()=>selected?{thread:selected,scope:draftScope(),epoch:client.epoch}:null,current:t=>selected===t.thread&&draftScope()===t.scope&&client.epoch===t.epoch,supported:()=>composeHistory?.controls?.supportedOperations?.includes("voice-start")===true,allowed:cap=>sideCapability(cap)});

const composerSettingsDialog=document.createElement('dialog');composerSettingsDialog.className='composer-settings-dialog';document.body.append(composerSettingsDialog);
function openComposerSettings(configuration=false){
  if(!selected||!composeHistory?.controls?.settings||!composeHistory.controls.supportedOperations?.includes("settings"))return;
  composerSettingsDialog.replaceChildren(node('h2','',configuration?'对话配置':'模型与思考强度'));
  const content=node('div');composerSettingsDialog.append(content);
  const close=node('button','quiet','完成');close.type='button';close.onclick=()=>composerSettingsDialog.close();composerSettingsDialog.append(close);composerSettingsDialog.showModal();
  Operations.renderModelSettings(content,composeHistory,selected,client,new Map(),configuration?'configuration':'model');
}
$('composer-config').onclick=()=>openComposerSettings(true);$('composer-model').onclick=()=>openComposerSettings();
function updateComposerContext(){
  const usage=composeHistory?.metadata?.latestTokenUsageInfo,capacity=usage?.modelContextWindow,used=usage?.last?.totalTokens,ring=$('context-usage');
  ring.hidden=!(Number.isSafeInteger(capacity)&&capacity>0&&Number.isSafeInteger(used)&&used>=0);
  if(!ring.hidden){const percent=Math.min(100,Math.round(100*used/capacity));ring.style.setProperty('--context-used',percent+'%');ring.setAttribute('aria-label','上下文已用 '+percent+'%');ring.title='最近一轮使用 '+used+' / '+capacity+' tokens，剩余 '+Math.max(0,capacity-used);}
  const model=$('composer-model');model.hidden=!selected||!composeHistory?.controls?.settings;model.textContent=(composeHistory?.controls?.settings?.model||composeHistory?.metadata?.latestModel||'模型').replace(/^gpt-/i,'')+' '+(composeHistory?.controls?.settings?.effort||composeHistory?.metadata?.latestReasoningEffort||'');
  const settingsAllowed=composeHistory?.controls?.supportedOperations?.includes('settings')===true;
  $('composer-config').disabled=!canInteract()||!settingsAllowed;$('composer-model').disabled=!canInteract()||!settingsAllowed;
  if(!settingsAllowed&&composerSettingsDialog.open)composerSettingsDialog.close();
}
$('context-usage').onclick=()=>{notice($('context-usage').title);};

function openCommandPanel(kind,argument=''){
  if(kind==='model'){if(!window.MobileUI?.openComposerSettings())openComposerSettings();return;}
  const panel=kind==='status'?$('conversation-info'):document.querySelector('.mobile-'+kind);
  if(!panel)throw Error('当前会话尚未提供此操作');
  if(kind==='review'&&argument){const select=panel.querySelector('[aria-label="审查范围"]'),field=panel.querySelector('[aria-label="审查要求"]');if(select&&field){select.value='custom';select.dispatchEvent(new Event('change'));field.value=argument;field.dispatchEvent(new Event('input'));}}
  if(window.MobileUI?.openCommandPanel(panel))return;
  for(let ancestor=panel;ancestor;ancestor=ancestor.parentElement)if(ancestor.tagName==='DETAILS')ancestor.open=true;
  panel.scrollIntoView({block:'nearest'});
}
const composerCommandMenu=ComposerCommands.mount($('prompt'),$('composer'),{history:()=>composeHistory,allowed:sideCapability,hasAttachments:()=>attachedImages.length>0||selectedSkills.length>0||selectedFiles.length>0||reviewComments.length>0},name=>{$('prompt').setDocument('/'+name,[],name.length+1,conversationKey(selected));$('composer').requestSubmit();});

ArchiveControls.configure({api,client,scope:draftScope,thread:()=>selected,snapshot:()=>composeHistory,canEdit:()=>sideCapability('edit'),completed:async(id,archived)=>{
 if(archived&&selected===id){
  conversationDrafts.set(activeDraftScope+':'+id,currentConversationDraft());navigationVersion++;
  closeSide();selected=null;composeHistory=null;historyCache.delete(conversationKey(id));Operations.reset();Timeline.reset();
  $('prompt').setDocument('');attachedImages=[];selectedSkills=[];selectedFiles=[];reviewComments=[];renderImages();renderSkills();renderFiles();renderReviewComments();
  $('title').textContent='继续你的工作';$('cwd').textContent='从会话列表选择一个会话';$('history-source').textContent='';$('messages').replaceChildren();
  subscription=client.subscribe({threadId:null,historyLimit:historyLimit});updateComposeButton();window.MobileUI?.show('projects');welcomeState(true);
 }
 listWindows.clear();await loadThreads();
}});

RenameControls.configure({client,scope:draftScope,thread:()=>selected,snapshot:()=>composeHistory,canEdit:()=>sideCapability('edit'),completed:async(id,name)=>{if(selected===id){$('title').textContent=name;historyCache.delete(conversationKey(id));}listWindows.clear();await loadThreads();}});
PluginManagement.configure({client,request:api,scope:draftScope,thread:()=>selected,snapshot:()=>composeHistory,supported:()=>enabled&&supportsPluginManagement,canView:()=>!cloudMode||client.devices?.find(d=>d.id===client.device)?.permissions?.includes('view')===true,canEdit:()=>sideCapability('edit')});
SkillManagement.configure({client,request:api,scope:draftScope,thread:()=>selected,snapshot:()=>composeHistory,canView:()=>!cloudMode||client.devices?.find(d=>d.id===client.device)?.permissions?.includes('view')===true,canEdit:()=>sideCapability('edit')});
TerminalControls.configure({client,request:api,scope:draftScope,thread:()=>selected,snapshot:()=>composeHistory,canView:()=>!cloudMode||client.devices?.find(d=>d.id===client.device)?.permissions?.includes('view')===true,canStop:()=>sideCapability('stop')});
SectionManagement.configure({client,request:api,scope:draftScope,canView:()=>!cloudMode||client.devices?.find(d=>d.id===client.device)?.permissions?.includes('view')===true,supported:()=>enabled&&supportsThreadSections,canEdit:()=>sideCapability('edit'),completed:loadNativeSections});
SectionControls.configure({client,request:api,scope:draftScope,thread:()=>selected,canView:()=>!cloudMode||client.devices?.find(d=>d.id===client.device)?.permissions?.includes('view')===true,supported:()=>supportsThreadSections,canEdit:()=>sideCapability('edit'),completed:async()=>{await loadNativeSections();}});
NativeSectionsSidebar.configure({manage:SectionManagement.open,order:SectionManagement.open,canEdit:()=>sideCapability("edit"),request:api,scope:draftScope,enabled:()=>enabled&&supportsThreadSections,canView:()=>!cloudMode||client.devices?.find(d=>d.id===client.device)?.permissions?.includes('view')===true,open:record=>selectThread(record.id,record),notice});
async function loadNativeSections(){await NativeSectionsSidebar.refresh();}

SearchControls.configure({request:api,scope:draftScope,allowed:()=>enabled&&supportsFullTextSearch&&(!cloudMode||client.devices?.find(d=>d.id===client.device)?.permissions?.includes('view')===true),open:(record,occurrence)=>{const scope=draftScope();openSearchOccurrence(record,occurrence).catch(error=>{if(scope===draftScope()&&SearchControls.available())notice(error.message);});}});
$('search-content').onclick=()=>SearchControls.open();

async function openSearchOccurrence(record,occurrence){
  const scope=draftScope(),before=navigationVersion;
  const result=await api('/threads/'+encodeURIComponent(record.id)+'/search-anchor?itemId='+encodeURIComponent(occurrence.itemId)+'&turnId='+encodeURIComponent(occurrence.turnId)+'&turnCursor='+encodeURIComponent(occurrence.turnCursor));
  if(scope!==draftScope()||before!==navigationVersion||!SearchControls.available())return;
  if(result.threadId!==record.id||result.itemId!==occurrence.itemId||result.turnId!==occurrence.turnId||!Number.isInteger(result.historyLimit)||result.historyLimit<1||result.historyLimit>4000)throw Error('搜索定位回执与目标不匹配');
  const version=navigationVersion+1;await selectThread(record.id,record);
  if(scope!==draftScope()||version!==navigationVersion||!SearchControls.available())return;
  const snapshot=await api('/threads/'+encodeURIComponent(record.id)+'/history?limit='+result.historyLimit);
  if(scope!==draftScope()||version!==navigationVersion||selected!==record.id||!SearchControls.available())return;
  if(snapshot.thread?.id!==record.id)throw Error('搜索历史与目标会话不匹配');
  const live=historyCache.get(conversationKey(record.id));
  const matching=history=>history?.timeline?.find(item=>item.id===occurrence.itemId||item.nativeId===occurrence.itemId);
  const display=matching(live)?live:snapshot,hit=matching(display);
  if(!hit)throw Error('命中消息已变化，请重新搜索');
  historyLimit=Math.max(historyLimit,result.historyLimit);
  Timeline.render(display,$('messages'),historyImageLoader(record.id));Timeline.navigateTo(hit.id);lastHistory='';await loadHistory();
}
