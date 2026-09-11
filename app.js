/* No HTML interpolation of conversation content or external responses. */
const $ = id => document.getElementById(id);
const mobileLayout = window.matchMedia('(max-width:760px)');
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
let enabled = false, selected = null, controllerId = null, threads = [], offset = 0;
let refreshBusy = false, lastHistory = '', listVersion = 0, noticeTimer;
let subscription = null;
let sideOpen=false, sideSelected=null, sideSignature='';
const SideTimeline=Timeline.create({runtime:'side-runtime',info:'side-info',source:'side-source'});
function closeSide(){
  sideOpen=false;sideSelected=null;sideSignature='';SideTimeline.reset();
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
  }
  if(sideSelected){const c=chats.find(c=>c.id===sideSelected);if(c)$('side-runtime').textContent=c.label;}
}
let threadStatuses = {};
let threadFlags = {}, catalogRevision = null;
function updateThreadStatuses(values) {
  threadStatuses = values;
  for(const badge of $('threads').querySelectorAll('[data-thread-status]')) {
    const state=values[badge.dataset.threadStatus] || {state:'unknown',label:'状态未知'};
    badge.textContent=state.label;
    badge.className='thread-status '+state.state;
  }
  const ids=threads.slice(0,100).map(t=>t.id);
  const count=state=>ids.filter(id=>values[id]?.state===state).length;
  const unknown=ids.filter(id=>!values[id] || ['loading','unknown'].includes(values[id].state)).length;
  $('thread-status-summary').textContent=enabled ? `已确认 ${count('running')} 个执行中 · ${count('waiting')} 个待处理`+(unknown?` · ${unknown} 个待确认`:'')+(threads.length>100?' · 状态仅订阅前 100 条':'') : '';
}
const states = {preparing:'检查会话中',dispatching:'正在投递',accepted:'Codex 已接收',completed:'已完成',failed:'发送失败',uncertain:'结果待确认',acknowledged:'已人工核对',interrupted:'已中断'};

function notice(text) {
  $('notice').textContent = text; $('notice').hidden = false;
  clearTimeout(noticeTimer); noticeTimer = setTimeout(() => $('notice').hidden = true, 6500);
}
const cloudMode = window.CONNECTNOW_CLOUD === true;
const client = new (cloudMode ? CloudConsoleClient : ConnectNowClient)({
  onUpdate: receiveUpdate,
  onDisconnect: event => {streamDisconnected(event);if(cloudMode)applyStatus({enabled:false,controllerId:null});},
  onAuthError: () => { $('pairing').hidden = false;if(cloudMode)applyStatus({enabled:false,controllerId:null}); },
  onError: error => notice('实时同步失败：' + error.message)
});
const api = (path, body) => client.request(path, body);
function canWrite(){return enabled&&(!cloudMode||client.control===true);}
function applyStatus(status) {
  if(cloudMode){if(client.control!==(status.remoteControl===true))lastHistory='';client.control=status.remoteControl===true;}
  enabled = status.enabled; controllerId = status.controllerId;
  $('status').textContent = enabled ? (cloudMode&&!client.control?'已连接 · 只读':'桥接已开启') : '未桥接'; $('status').classList.toggle('on', enabled);
  $('bridge').textContent = cloudMode ? '请在本机管理桥接' : enabled ? '取消桥接' : '开启桥接';
  if(cloudMode)$('bridge').disabled=true;
  $('create').disabled = !canWrite() || !controllerId;
  for (const id of ['search','refresh','controller','set-controller']) $(id).disabled = !enabled;
  if(cloudMode)$('set-controller').disabled=!canWrite();
  $('prompt').disabled = !canWrite() || !selected; $('send').disabled = !canWrite() || !selected;
  $('open-side').disabled=!enabled||!selected;
  $('controller-note').textContent = controllerId ? '控制会话已选定，新建任务将通过它执行。' : '首次请在 Codex App 中打开专用控制会话。';
  if (!enabled) {
    threadFlags={};catalogRevision=null;
    Operations.reset();
    closeSide();
    updateThreadStatuses({});
    Timeline.reset();
    listVersion++; selected = null; lastHistory = ''; threads = [];
    $('threads').replaceChildren(node('div','empty-small','开启桥接后，查看本机会话。'));
    $('messages').replaceChildren(node('div','welcome','桥接已关闭，继续使用 Codex App 即可。'));
    $('jobs').replaceChildren(); $('title').textContent = '继续你的工作'; $('cwd').textContent = '从会话列表选择一个会话';
    $('controller').replaceChildren(new Option('开启桥接后选择控制会话',''));
    $('history-source').textContent = ''; $('more').hidden = true;
    $('create-dialog').close();
  }
}
function node(tag, cls, text) { const el = document.createElement(tag); if(cls) el.className=cls; if(text!==undefined) el.textContent=text; return el; }
function renderThreads() {
  const children = threads.map(t => {
    const button = node('button','thread' + (t.id === selected ? ' active' : ''));
    const row=node('div','thread-heading');
    const badge=node('span','thread-status');badge.dataset.threadStatus=t.id;
    row.append(node('strong','',(threadFlags[t.id]?.hasUnreadTurn?'● ':'')+(t.title || '未命名会话')),badge);
    button.append(row,node('small','',t.cwd));
    button.onclick = () => selectThread(t.id); return button;
  });
  $('threads').replaceChildren(...(children.length ? children : [node('div','empty-small','没有匹配的会话。')]));
  updateThreadStatuses(threadStatuses);
  const chosen = $('controller').value || controllerId;
  $('controller').replaceChildren(new Option('选择一个已加载的空闲会话',''),...threads.map(t => new Option(t.title || t.id,t.id)));
  if(chosen && !threads.some(t=>t.id===chosen)) $('controller').append(new Option('已选控制会话 · '+chosen.slice(0,8),chosen));
  if(chosen) $('controller').value=chosen;
}
async function loadThreads(more=false) {
  const version = ++listVersion;
  const start = more ? offset : 0;
  const result = await api('/threads?limit=100&offset=' + start + '&search=' + encodeURIComponent($('search').value));
  if(!enabled || version!==listVersion) return;
  threads = more ? [...threads,...result.threads] : result.threads; offset=result.nextOffset;
  $('more').hidden = result.threads.length < 100; renderThreads();
  await loadHistory();
}
async function selectThread(id) {
  if(mobileLayout.matches) { setThreadListOpen(false); $('title').focus({preventScroll:true}); }
  Operations.reset();
  closeSide();$('open-side').disabled=!enabled;
  Timeline.reset();
  selected=id; lastHistory=''; delete $('messages').dataset.loaded; renderThreads(); $('prompt').disabled=!canWrite(); $('send').disabled=!canWrite();
  const thread=threads.find(t=>t.id===id); $('title').textContent=thread?.title || id; $('cwd').textContent=thread?.cwd || '';
  $('messages').replaceChildren(node('div','empty-small','读取历史中…'));
  try { await loadHistory(); } catch(e) { if(selected===id) $('messages').replaceChildren(node('div','empty-small',e.message)); }
}
async function loadHistory() {
  subscription = client.subscribe({threadId: enabled ? selected : null,
    threadIds: enabled ? threads.slice(0,100).map(t => t.id) : [],
    includeSideChats: enabled && sideOpen, sideThreadId: enabled && sideOpen ? sideSelected : null});
}
async function receiveUpdate(data, current) {
  const wasEnabled = enabled;
  if(enabled !== data.status.enabled || controllerId !== data.status.controllerId || cloudMode&&client.control!==(data.status.remoteControl===true)) applyStatus(data.status);
  if(enabled && !wasEnabled) { await loadThreads(); if(!current())return; await loadHistory(); }
  if(!enabled)return;
  if(data.subscription===subscription&&data.threadFlags){
    if(JSON.stringify(data.threadFlags)!==JSON.stringify(threadFlags)){
      threadFlags=data.threadFlags;
      if(selected&&threadFlags[selected]?.archived){
        closeSide();Operations.reset();selected=null;lastHistory='';
        $('messages').replaceChildren(node('div','empty-small','此会话已归档。'));
        $('send').disabled=true;$('prompt').disabled=true;$('open-side').disabled=true;
      }
      renderThreads();
    }
  }
  if(data.catalogRevision!==undefined&&data.catalogRevision!==catalogRevision){
    const changed=catalogRevision!==null;catalogRevision=data.catalogRevision;
    if(changed){await loadThreads();return;}
  }
  if(data.subscription===subscription && data.threadStatuses) updateThreadStatuses(data.threadStatuses);
  if(data.jobs)renderJobs(data.jobs);
  if(data.threadId !== selected || data.subscription !== subscription)return;
  if(sideOpen&&data.sideChats)renderSides(data.sideChats);
  if(sideOpen&&data.sideThreadId===sideSelected){
    if(data.sideError){$('side-source').textContent='同步暂不可用';$('side-runtime').textContent='状态未知';$('side-discovery').textContent=data.sideError;}
    else if(data.sideHistory){const signature=JSON.stringify(data.sideHistory);if(signature!==sideSignature){sideSignature=signature;SideTimeline.render(data.sideHistory,$('side-messages'));}}
  }
  if(data.error) { Operations.reset();lastHistory='';notice(data.error); $('history-source').textContent='同步暂不可用'; return; }
  if(data.history) {
    const signature = JSON.stringify(data.history);
    if(signature !== lastHistory){lastHistory=signature;Timeline.render(data.history,$('messages'));Operations.render(data.history,selected,client,notice);if(!canWrite())for(const control of $('operations').querySelectorAll('button,input,select,textarea'))control.disabled=true;}
  }
}
function streamDisconnected(event) {
  Operations.reset();
  lastHistory='';
  if(sideOpen){$('side-runtime').textContent='状态未知';$('side-source').textContent='连接已断开，重连后恢复';}
  updateThreadStatuses({});
  if(event.code===1008){notice('实时连接认证失败，请重新配对');return;}
  if(enabled)notice('实时连接已断开，正在重连…');
}
$('expand-events').onclick=()=>Timeline.setExpanded(true);
$('open-side').onclick=()=>{if(!enabled||!selected)return;sideOpen=true;$('side-drawer').hidden=false;document.body.classList.add('side-open');$('side-discovery').textContent='正在查找临时聊天…';loadHistory();};
$('close-side').onclick=()=>{closeSide();loadHistory();};
$('side-select').onchange=()=>{sideSelected=$('side-select').value||null;sideSignature='';SideTimeline.reset();delete $('side-messages').dataset.loaded;$('side-messages').replaceChildren(node('div','empty-small',sideSelected?'正在读取临时聊天…':'请选择临时聊天'));loadHistory();};
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
$('bridge').onclick=async()=>{
  $('bridge').disabled=true;
  try { const wasEnabled=enabled; applyStatus(await api('/bridge',{enabled:!enabled}));
    if(enabled){await loadThreads();notice('桥接已开启，请选择会话。');}
    else if(wasEnabled) notice('已取消桥接。Codex 已接收的任务仍会继续执行。');
  } catch(e){notice(e.message);} finally{$('bridge').disabled=false;}
};
$('pair').onclick=async()=>{
  $('pair').disabled=true;
  try {
    await client.pair($('token').value);
    if(cloudMode){$('pairing').hidden=true;$('token').value='';}
    applyStatus(await api('/status'));$('pairing').hidden=true;$('token').value='';
    client.connect();if(!cloudMode)await CloudSettings.refresh();if(enabled)await loadThreads();
  } catch(e){notice(e.message);}
  finally{$('pair').disabled=false;if(cloudMode)client.connect();}
};
$('set-controller').onclick=async()=>{if(!$('controller').value)return notice('请选择控制会话');$('set-controller').disabled=true;try{applyStatus(await api('/controller',{threadId:$('controller').value}));notice('控制会话已就绪');}catch(e){notice('设置失败：'+e.message);}finally{$('set-controller').disabled=!canWrite();}};
$('create').onclick=()=>{$('create-error').textContent='';$('create-dialog').showModal();$('new-prompt').focus();};
for(const id of ['close-dialog','cancel-create']) $(id).onclick=()=>$('create-dialog').close();
$('create-form').onsubmit=async e=>{e.preventDefault();$('submit-create').disabled=true;try{await submit('create',$('new-prompt').value.trim());$('create-dialog').close();$('new-prompt').value='';notice('已提交创建请求，等待控制会话处理');await tick();}catch(e){$('create-error').textContent=e.message+'；重试会沿用原请求 ID。';}finally{$('submit-create').disabled=false;}};
$('composer').onsubmit=async e=>{e.preventDefault();const prompt=$('prompt').value.trim();if(!prompt)return;$('send').disabled=true;try{await submit('message',prompt);$('prompt').value='';notice('请求已登记，正在交给 Codex');await tick();}catch(e){notice(e.message+'；重试会沿用原请求 ID。');}finally{$('send').disabled=!canWrite()||!selected;}};
$('prompt').onkeydown=e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)){e.preventDefault();if(!$('send').disabled)$('composer').requestSubmit();}};
$('refresh').onclick=()=>loadThreads().catch(e=>notice(e.message));
$('more').onclick=()=>loadThreads(true).catch(e=>notice(e.message));
let searchTimer;$('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadThreads().catch(e=>notice(e.message)),300);};
async function tick(){
  if(refreshBusy || !client.token)return;refreshBusy=true;
  try{const status=await api('/status');const justEnabled=status.enabled&&!enabled;
    if(status.enabled!==enabled || status.controllerId!==controllerId || cloudMode&&client.control!==(status.remoteControl===true)){applyStatus(status);if(enabled)renderThreads();}
    if(justEnabled)await loadThreads();
    if(enabled){const {jobs}=await api('/jobs');if(enabled)renderJobs(jobs);await loadHistory();}}
  catch(e){if(enabled)notice(e.message);}finally{refreshBusy=false;}
}
async function init(){
  if(location.protocol==='file:'){ $('pairing').hidden=false; notice('请通过本地服务打开页面，不能直接双击 HTML 启动后台进程。');return; }
  if(cloudMode){
    document.body.classList.add('cloud-console');
    document.querySelector('.footnote').textContent='云端同步本机会话 · 思考仅展示摘要 · 附件保留引用';
    document.querySelector('.cloud-settings').hidden=true;
    $('bridge').disabled=true;$('bridge').textContent='请在本机管理桥接';
    document.querySelector('label[for="token"]').textContent='云端控制台登录凭证';
    $('token').placeholder='输入独立的控制台登录凭证';$('pair').textContent='登录';
    document.querySelector('#pairing p').textContent='登录后选择设备；在本机使用配对码连接，并开启桥接。';
    for(const id of ['console-device','console-pair-device','console-logout'])$(id).hidden=false;
    $('console-device').onchange=async()=>{
      client.close();client.epoch++;client.selection=null;client.device=$('console-device').value;client.setStorage();
      selected=null;threads=[];applyStatus({enabled:false,controllerId:null});
      try{applyStatus(await api('/status'));if(enabled)await loadThreads();}catch(e){notice(e.message);}finally{client.connect();}
    };
    $('console-pair-device').onclick=async()=>{
      try{const p=await client.consoleRequest('pairing',{deviceId:client.device});
        $('console-pair-command').textContent='connectnow start\nconnectnow cloud pair --url '+p.publicUrl+(p.publicUrl.startsWith('http:')?' --dev-local':'');
        $('console-pair-code').textContent=p.code;$('console-code-dialog').showModal();
      }catch(e){notice(e.message);}
    };
    $('console-close-code').onclick=()=>{$('console-code-dialog').close();$('console-pair-code').textContent='';};
    $('console-logout').onclick=async()=>{
      client.close();client.epoch++;client.selection=null;
      try{await client.consoleRequest('logout',{});client.token='';applyStatus({enabled:false,controllerId:null});$('pairing').hidden=false;}catch(e){notice(e.message);}
    };
    try{await client.initialize();}catch(e){notice(e.message);}
  }
  $('pairing').hidden=!!client.token;
  if(client.token)try{applyStatus(await api('/status'));if(enabled)await loadThreads();}catch(e){notice(e.message);}
  client.connect();
}
init().then(()=>{if(!cloudMode)CloudSettings.init(api,notice);});
