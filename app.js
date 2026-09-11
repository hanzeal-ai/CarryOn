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
const historyImageLoader=(thread,parent)=>id=>api(parent?'/side-chats/'+encodeURIComponent(thread)+'/images/'+id+'?parentId='+encodeURIComponent(parent):'/threads/'+encodeURIComponent(thread)+'/images/'+id);
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
let workspaceView='projects',workspaceProject=null,workspaceProjects=[],workspaceRevision=null;
let workspaceRefreshTimer;
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
  onAuthError: () => { $('pairing').hidden = false;if(cloudMode){applyStatus({enabled:false,controllerId:null});$('console-code-dialog').close();$('console-pair-code').textContent='';$('link-dialog').close();$('requests-dialog').close();$('connection-requests').replaceChildren();$('account-menu').open=false;} },
  onError: error => notice('实时同步失败：' + error.message)
});
const api = (path, body) => client.request(path, body);
function welcomeState(connected){
  const welcome=node('div','welcome');
  welcome.append(node('span','welcome-icon','↗'),node('span','eyebrow',connected?'工作空间已就绪':'等待工作空间连接'),node('h2','',connected?'从一段对话开始':'连接后，继续你的工作'),node('p','',connected?'从会话列表选择一个任务，查看进度或继续对话。':cloudMode?'请确认电脑在线，并在本机开启桥接。':'在上方开启桥接，连接正在运行的 Codex。'));
  $('messages').replaceChildren(welcome);
}
function canWrite(){return enabled&&(!cloudMode||client.control===true);}
function applyStatus(status) {
  if(cloudMode){if(client.control!==(status.remoteControl===true))lastHistory='';client.control=status.remoteControl===true;}
  enabled = status.enabled; controllerId = status.controllerId;
  $('status').textContent = enabled ? (cloudMode?(client.control?'可远程操作':'只读连接'):'已连接') : '等待连接'; $('status').classList.toggle('on', enabled);
  $('bridge').textContent = cloudMode ? '请在本机管理桥接' : enabled ? '取消桥接' : '开启桥接';
  if(cloudMode)$('bridge').disabled=true;
  $('create').disabled = !canWrite() || !controllerId;
  $('create').title=!controllerId?'先在「新建会话设置」中选择控制会话':'';
  for (const id of ['search','refresh','controller','set-controller']) $(id).disabled = !enabled;
  if(cloudMode)$('set-controller').disabled=!canWrite();
  $('attach-images').disabled=!canAttach(); $('prompt').disabled = !canWrite() || !selected; $('send').disabled = !canWrite() || !selected;
  $('open-side').disabled=!enabled||!selected;
  $('controller-note').textContent = controllerId ? '控制会话已选定，新建任务将通过它执行。' : '首次请在 Codex App 中打开专用控制会话。';
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
    row.append(node('strong','',(t.unread?'● ':'')+(t.title || '未命名会话')),badge);
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
function renderProjects(){
  $('threads').replaceChildren(...workspaceProjects.map(project=>{
    const button=node('button','thread');
    button.append(node('strong','',project.name),node('small','',project.cwd),node('small','',`${project.total} 个会话 · ${project.waiting} 待处理 · ${project.running} 进行中 · ${project.unread} 未读`+(project.unknown?` · ${project.unknown} 状态未知`:'')));
    button.onclick=()=>{workspaceView='threads';workspaceProject=project.id;$('search').value='';$('project-filter').value='all';loadThreads().catch(e=>notice(e.message));};
    return button;
  }));
  if(!workspaceProjects.length)$('threads').append(node('div','empty-small','没有匹配的项目。'));
  $('thread-status-summary').textContent='项目汇总来自服务端全部会话；未知状态不会计为空闲。';
}
async function loadThreads(more=false){
  const version=++listVersion,start=more?offset:0;
  const params='?limit=100&offset='+start+'&search='+encodeURIComponent($('search').value);
  const route=workspaceView==='projects'?'/projects':workspaceView==='activity'?'/activity':'/projects/'+workspaceProject+'/threads';
  const result=await api(route+params+(workspaceView==='threads'?'&filter='+$('project-filter').value:''));
  if(!enabled||version!==listVersion)return;
  offset=result.nextOffset;$('more').hidden=offset>=result.total;
  $('project-filter-label').hidden=workspaceView!=='threads';
  if(workspaceView==='projects'){workspaceProjects=more?[...workspaceProjects,...result.projects]:result.projects;threads=[];renderProjects();}
  else{threads=more?[...threads,...result.threads]:result.threads;renderThreads();}
  const totals=await api('/activity?limit=1');if(version!==listVersion)return;
  $('show-activity').textContent='动态'+(totals.total?' · '+totals.total:'');
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
async function selectThread(id) {
  if(selected)conversationDrafts.set(activeDraftScope+':'+selected,{text:$('prompt').value,images:[...attachedImages]});
  clearImages();
  activeDraftScope=draftScope();
  const draft=conversationDrafts.get(activeDraftScope+':'+id);$('prompt').value=draft?.text||'';attachedImages=draft?.images||[];renderImages();
  if(mobileLayout.matches) { setThreadListOpen(false); $('title').focus({preventScroll:true}); }
  composeHistory=null;updateComposeButton();Operations.reset();
  closeSide();$('open-side').disabled=!enabled;
  Timeline.reset();
  selected=id; lastHistory=''; delete $('messages').dataset.loaded; renderThreads(); $('attach-images').disabled=!canAttach();$('prompt').disabled=!canWrite(); $('send').disabled=!canWrite();
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
    if(changed){await loadThreads();return;}
  }
  if(data.subscription===subscription && data.threadStatuses) updateThreadStatuses(data.threadStatuses);
  if(data.jobs)renderJobs(data.jobs);
  if(data.threadId !== selected || data.subscription !== subscription)return;
  if(sideOpen&&data.sideChats)renderSides(data.sideChats);
  if(sideOpen&&data.sideThreadId===sideSelected){
    if(data.sideError){$('side-source').textContent='同步暂不可用';$('side-runtime').textContent='状态未知';$('side-discovery').textContent=data.sideError;}
    else if(data.sideHistory){const signature=JSON.stringify(data.sideHistory);if(signature!==sideSignature){sideSignature=signature;SideTimeline.render(data.sideHistory,$('side-messages'),historyImageLoader(sideSelected,selected)); }}
  }
  if(data.error) { Operations.reset();lastHistory='';notice(data.error); $('history-source').textContent='同步暂不可用'; return; }
  if(data.history) {
    updateCompose(data.history);
    const signature = JSON.stringify(data.history);
    if(signature !== lastHistory){lastHistory=signature;Timeline.render(data.history,$('messages'),historyImageLoader(data.history.thread.id));Operations.render(data.history,selected,client,notice,canWrite());}
    if(document.visibilityState==='visible'&&data.readSequence)api('/notifications/read',{threadId:selected,sequence:data.readSequence}).catch(()=>{});
  }
}
function streamDisconnected(event) {
  composeHistory=null;updateComposeButton();Operations.reset();
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
$('pairing-form').onsubmit=async event=>{
  event.preventDefault();$('pairing-error').hidden=true;
  $('pair').disabled=true;
  try {
    await client.pair($('token').value);
    if(cloudMode){$('pairing').hidden=true;$('token').value='';await offerLink();}
    if(!cloudMode||client.device)applyStatus(await api('/status'));$('pairing').hidden=true;$('token').value='';
    client.connect();if(!cloudMode)await CloudSettings.refresh();if(enabled)await loadThreads();
  } catch(e){if(!client.token){$('pairing-error').textContent=e.message;$('pairing-error').hidden=false;}else notice(e.message);}
  finally{$('pair').disabled=false;if(cloudMode)client.connect();}
};
$('set-controller').onclick=async()=>{if(!$('controller').value)return notice('请选择控制会话');$('set-controller').disabled=true;try{applyStatus(await api('/controller',{threadId:$('controller').value}));notice('控制会话已就绪');}catch(e){notice('设置失败：'+e.message);}finally{$('set-controller').disabled=!canWrite();}};
$('create').onclick=()=>{$('create-error').textContent='';$('create-dialog').showModal();$('new-prompt').focus();};
for(const id of ['close-dialog','cancel-create']) $(id).onclick=()=>$('create-dialog').close();
$('create-form').onsubmit=async e=>{e.preventDefault();$('submit-create').disabled=true;try{await submit('create',$('new-prompt').value.trim());$('create-dialog').close();$('new-prompt').value='';notice('已提交创建请求，等待控制会话处理');await tick();}catch(e){$('create-error').textContent=e.message+'；重试会沿用原请求 ID。';}finally{$('submit-create').disabled=false;}};
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
  }catch(e){notice(e.message);}finally{imageBusy=false;renderImages();$('attach-images').disabled=!canAttach();$('send').disabled=!canWrite()||!selected;}
}
$('attach-images').onclick=()=>$('image-files').click();
$('image-files').onchange=()=>{addImages($('image-files').files);$('image-files').value='';};
$('prompt').addEventListener('paste',event=>{const files=[...event.clipboardData.items].filter(i=>i.kind==='file'&&i.type.startsWith('image/')).map(i=>i.getAsFile()).filter(Boolean);if(files.length){event.preventDefault();addImages(files);}});
$('composer').onsubmit=async e=>{
  e.preventDefault();if(imageBusy||!canWrite()||!selected)return;
  const prompt=$('prompt').value.trim();
  if(!prompt&&!attachedImages.length){
    if(composeHistory?.controls?.activeTurnId&&composeHistory.runtime?.type==='active')await client.operation(selected,'interrupt',{expectedTurnId:composeHistory.controls.activeTurnId}).catch(e=>notice(e.message));
    return;
  }
  const target=selected,generation=imageGeneration;imageBusy=true;renderImages();$('send').disabled=true;$('attach-images').disabled=true;
  try{const job=await client.submit('compose',target,prompt,attachedImages.map(i=>i.url),()=>selected===target&&generation===imageGeneration);
    if(['failed','uncertain'].includes(job.state))throw Error(job.error||'请求未成功，请先核对原请求');
    if(selected===target&&generation===imageGeneration){$('prompt').value='';conversationDrafts.delete(draftScope()+':'+target);clearImages();}
    notice('请求已登记，正在交给 Codex');await tick();
  }catch(e){notice(e.message+'；重试会沿用原请求 ID。');}
  finally{imageBusy=false;renderImages();$('attach-images').disabled=!canAttach();$('send').disabled=!canWrite()||!selected;}
};
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
const linkRequest=new URLSearchParams(location.hash.slice(1)).get('connect');
async function offerLink(){
  if(!cloudMode||!linkRequest)return;
  try{const result=await client.consoleRequest('link/inspect',{id:linkRequest});$('link-verification').textContent=result.verification;$('link-dialog').showModal();}
  catch(e){notice(e.message);}
}
$('link-cancel').onclick=()=>$('link-dialog').close();
$('link-approve').onclick=async()=>{
  $('link-approve').disabled=true;
  try{await client.consoleRequest('link/approve',{id:linkRequest});$('link-dialog').close();history.replaceState(null,'',location.pathname);await refreshConsoleDevices();notice('已确认连接，等待设备上线');}
  catch(e){notice(e.message);}finally{$('link-approve').disabled=false;}
};
async function refreshConsoleDevices(){
  const previous=client.device;
  await client.initialize();
  if(previous!==client.device){
    client.close();client.epoch++;client.selection=null;selected=null;threads=[];
    applyStatus({enabled:false,controllerId:null});
    if(client.device){try{applyStatus(await api('/status'));if(enabled)await loadThreads();}catch(e){notice(e.message);}client.connect();}
  }
}
async function refreshConnectionRequests(){
  if(!cloudMode||!client.token)return;
  const result=await client.consoleRequest('link/pending');
  $('console-requests').textContent='连接申请'+(result.requests.length?' · '+result.requests.length:'');
  const list=$('connection-requests'),signature=JSON.stringify(result.requests);
  if(list.dataset.signature===signature&&list.childNodes.length)return;
  list.dataset.signature=signature;list.replaceChildren();
  if(!result.requests.length)list.textContent='暂无待连接设备';
  for(const request of result.requests){
    const row=document.createElement('section'),title=document.createElement('p');
    title.textContent=request.name+' · '+request.verification+' · '+new Date(request.created*1000).toLocaleTimeString();
    const approve=document.createElement('button'),reject=document.createElement('button');
    approve.textContent='确认连接';reject.textContent='拒绝';
    const respond=async action=>{
      approve.disabled=reject.disabled=true;
      try{await client.consoleRequest('link/'+action,{id:request.id});await refreshConnectionRequests();await refreshConsoleDevices();}
      catch(e){notice(e.message);approve.disabled=reject.disabled=false;}
    };
    approve.onclick=()=>respond('approve');reject.onclick=()=>respond('reject');row.append(title,approve,reject);list.append(row);
  }
}
async function init(){
  if(location.protocol==='file:'){ $('pairing').hidden=false; notice('请通过本地服务打开页面，不能直接双击 HTML 启动后台进程。');return; }
  if(cloudMode){
    document.body.classList.add('cloud-console');
    document.querySelector('.footnote').textContent='与你的 Codex 工作空间保持同步';
    $('environment-label').textContent='云端工作台';$('auth-title').textContent='登录你的工作空间';$('auth-description').textContent='安全连接，接着上次的进度继续。';$('account-menu').hidden=false;
    document.querySelector('.cloud-settings').hidden=true;
    $('bridge').disabled=true;$('bridge').textContent='请在本机管理桥接';
    document.querySelector('label[for="token"]').textContent='云端控制台登录凭证';
    $('token').placeholder='输入控制台登录凭证';$('pair').textContent='登录工作空间 →';
    $('auth-help').textContent='使用部署时生成的控制台登录凭证。它与设备配对码不同。';
    for(const id of ['console-device','console-pair-device','console-logout','console-requests','console-remove-device','console-standby'])$(id).hidden=false;
    $('console-requests').onclick=async()=>{try{await refreshConnectionRequests();$('requests-dialog').showModal();}catch(e){notice(e.message);}};
    $('requests-close').onclick=()=>$('requests-dialog').close();
    $('console-standby').onclick=async()=>{try{const s=await api('/standby');notice(s.error||(!s.supported?'此设备不支持远程待机':s.effective?'远程待机已生效（接电）':s.enabled?'远程待机已开启，当前未生效':'远程待机未开启；请在本机管理'));}catch(e){notice(e.message);}};
    $('console-remove-device').onclick=async()=>{
      if(!client.device||!confirm('移除此设备并撤销它的云端连接凭证？'))return;
      try{const result=await client.consoleRequest('devices/'+encodeURIComponent(client.device),undefined,'DELETE');await refreshConsoleDevices();notice(result.notice||'设备已移除');}catch(e){notice(e.message);}
    };
    const pollRequests=async()=>{try{await refreshConnectionRequests();if(client.token)await refreshConsoleDevices();}catch(e){if(client.token)notice(e.message);}finally{setTimeout(pollRequests,5000);}};
    pollRequests();
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
      $('console-logout').disabled=true;
      client.close();client.epoch++;client.selection=null;
      try{await client.consoleRequest('logout',{});client.token='';applyStatus({enabled:false,controllerId:null});$('pairing').hidden=false;$('pairing-error').hidden=true;$('requests-dialog').close();$('connection-requests').replaceChildren();$('account-menu').open=false;$('token').value='';$('token').focus();}catch(e){notice(e.message);client.connect();}finally{$('console-logout').disabled=false;}
    };
    try{await client.initialize();await offerLink();}catch(e){if(e.message!=='请先登录云端控制台'){$('pairing-error').textContent=e.message;$('pairing-error').hidden=false;}}
  }
  $('pairing').hidden=!!client.token;
  if(client.token&&(!cloudMode||client.device))try{applyStatus(await api('/status'));if(enabled)await loadThreads();}catch(e){notice(e.message);}
  client.connect();
}
document.addEventListener('click',event=>{
  for(const menu of document.querySelectorAll('.account-menu,.display-menu,.session-info,.session-actions'))if(!menu.contains(event.target))menu.open=false;
});
document.addEventListener('keydown',event=>{if(event.key==='Escape')for(const menu of document.querySelectorAll('.account-menu,.display-menu,.session-info,.session-actions'))if(menu.open){menu.open=false;menu.querySelector('summary').focus();}});
init().then(()=>{if(!cloudMode)CloudSettings.init(api,notice);}).finally(()=>document.body.classList.remove('booting'));

function draftScope(){return cloudMode?client.storageScope:location.origin;}
let composeHistory=null;
function canAttach(){return canWrite()&&!!selected&&composeHistory?.status?.state==='idle'&&!imageBusy;}
function updateCompose(history){composeHistory=history;updateComposeButton();$('attach-images').disabled=!canAttach();}
function updateComposeButton(){
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
$('notification-settings').onclick=async()=>{
  try{
    const {preferences}=await api('/notifications/preferences');
    const labels={message:'新消息',done:'任务完成',failed:'任务失败',approval:'需要确认'};
    $('notification-preferences').replaceChildren(...Object.entries(labels).map(([kind,text])=>{
      const label=node('label','',text),input=node('input');input.type='checkbox';input.checked=preferences[kind];
      input.onchange=async()=>{input.disabled=true;try{const result=await api('/notifications/preferences',{...preferences,[kind]:input.checked});Object.assign(preferences,result.preferences);}catch(e){input.checked=preferences[kind];notice(e.message);}finally{input.disabled=false;}};
      label.append(input);return label;
    }));
    $('system-notification-status').textContent='通知分类和未读状态已保存；系统推送需由对应平台接入。';$('notification-dialog').showModal();
  }catch(e){notice(e.message);}
};
$('notification-close').onclick=()=>$('notification-dialog').close();
pollNotifications();

document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'&&enabled&&selected)loadHistory().catch(()=>{});});

let refreshTouch=null;
const sidebar=document.querySelector('aside');
sidebar.addEventListener('touchstart',event=>{if(sidebar.scrollTop===0&&event.touches.length===1)refreshTouch=event.touches[0].clientY;},{passive:true});
sidebar.addEventListener('touchend',event=>{if(refreshTouch!==null&&event.changedTouches[0]?.clientY-refreshTouch>80&&enabled)loadThreads().catch(e=>notice(e.message));refreshTouch=null;},{passive:true});
sidebar.addEventListener('touchcancel',()=>{refreshTouch=null;},{passive:true});
