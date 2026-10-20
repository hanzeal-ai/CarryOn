/* HTTP authentication, durable retry IDs and the live connection lifecycle. */
'use strict';
function responseError(message,status,uncertain=false){return Object.assign(Error(message),{status,uncertain});}
async function readApiResponse(response) {
  try {
    const result=await response.json();
    if(!result||typeof result!=='object'||Array.isArray(result))throw Error('Invalid response object');
    return result;
  }
  catch {
    if (response.status === 413) throw responseError('图片请求超过服务器大小限制，请减少图片或压缩后重试',response.status);
    throw responseError(response.ok ? '服务器返回了无效数据，请重试' : '服务请求失败（HTTP '+response.status+'），请稍后重试',response.status,response.status===409);
  }
}
// Display-only cache bounded by both count and encoded bytes.
class DisplayHistoryCache {
  constructor(maxEntries=8,maxBytes=8*1024*1024){this.maxEntries=maxEntries;this.maxBytes=maxBytes;this.entries=new Map();this.bytes=0;}
  get(key){const item=this.entries.get(key);if(!item)return;this.entries.delete(key);this.entries.set(key,item);return item.value;}
  set(key,value){
    const existing=this.entries.get(key);
    if(existing&&(existing.value===value||(value.historyRevision&&existing.value.historyRevision===value.historyRevision))){this.get(key);return;}
    this.delete(key);
    const size=new TextEncoder().encode(JSON.stringify(value)).length;
    if(size>this.maxBytes)return;
    this.entries.set(key,{value,size});this.bytes+=size;
    while(this.entries.size>this.maxEntries||this.bytes>this.maxBytes)this.delete(this.entries.keys().next().value);
  }
  delete(key){const item=this.entries.get(key);if(item){this.bytes-=item.size;this.entries.delete(key);}}
  clear(){this.entries.clear();this.bytes=0;}
}
// Decode every wire update before render coalescing; a gap requires a fresh stream.
class HistoryWire {
  constructor(){this.scope=null;this.histories={};}
  decode(packet){
    const scope=JSON.stringify([packet.subscription,packet.threadId,packet.sideThreadId]);
    if(scope!==this.scope||packet.status?.enabled===false){this.histories={};this.scope=scope;}
    const result={...packet},next={...this.histories};
    for(const field of ['history','sideHistory']){
      const delta=packet[field+'Delta'];
      if(delta!==undefined){
        const previous=this.histories[field];
        if(!delta||field in packet||!previous||delta.base!==previous.historyRevision)throw Error('历史版本缺口，正在重新同步');
        const {start,delete:count,items,fields}=delta,timeline=previous.timeline,removed=delta.remove||[];
        if(!Array.isArray(timeline)||!Number.isInteger(start)||!Number.isInteger(count)||start<0||count<0||start+count>timeline.length||!Array.isArray(items)||!fields||typeof fields.historyRevision!=='string'||!Array.isArray(removed)||removed.some(k=>typeof k!=='string'||['timeline','historyRevision'].includes(k)))throw Error('历史增量格式无效');
        const retained={...previous};for(const key of removed)delete retained[key];
        result[field]={...retained,...fields,timeline:[...timeline.slice(0,start),...items,...timeline.slice(start+count)]};
        delete result[field+'Delta'];
      }
      if(result[field])next[field]=result[field];else delete next[field];
    }
    this.histories=next;return result;
  }
}

function mergeOutgoingMessage(previous,update,live=false){
  if(!previous||['accepted','completed','inProgress','acknowledged'].includes(update.state))return null;
  // Live journal evidence can arrive before the HTTP admission response.
  if(['failed','uncertain'].includes(previous.state)&&['preparing','dispatching'].includes(update.state))return previous;
  if(previous.updated&&update.updated&&update.updated<previous.updated)return previous;
  return {...previous,...update,live:previous.live||live};
}
class CarryOnClient {
  constructor({onUpdate, onDisconnect, onAuthError, onError}) {
    this.onUpdate = onUpdate;
    this.onDisconnect = onDisconnect;
    this.onAuthError = onAuthError;
    this.onError = onError;
    const fragment = new URLSearchParams(location.hash.slice(1));
    this.token = fragment.get('token') || sessionStorage.getItem('carryon-token') || '';
    if (fragment.has('token')) history.replaceState(null, '', location.pathname);
    if (this.token) sessionStorage.setItem('carryon-token', this.token);
    this.pending = this.restore('carryon-pending');
    this.operations = this.restore('carryon-operations');
    this.socket = null;
    this.timer = null;
    this.delay = 500;
    this.selection = null;
    this.epoch = 0;
    this.onSubmission = () => {};
  }

  restore(key) {
    try { return new Map(JSON.parse(sessionStorage.getItem(key) || '[]')); }
    catch { return new Map(); }
  }

  async request(path, body) {
    const epoch = this.epoch;
    const response = await fetch('/api' + path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: {Authorization: 'Bearer ' + this.token,
        ...(body === undefined ? {} : {'Content-Type': 'application/json'})},
      ...(body === undefined ? {} : {body: JSON.stringify(body)})
    });
    const result = await readApiResponse(response);
    if (epoch !== this.epoch) throw Error('配对已改变，请重新读取状态');
    if (!response.ok) {
      if (response.status === 401) this.onAuthError();
      throw responseError(result.error || '请求失败',response.status,result.uncertain===true);
    }
    return result;
  }

  setWorkspaceSession(session){
    if(this.workspaceSession===session)return;
    if(this.workspaceSession)this.epoch++;
    this.workspaceSession=session;this.localStorageScope='carryon-local:'+session+':';
    this.pending=this.restore(this.localStorageScope+'pending');this.operations=this.restore(this.localStorageScope+'operations');
  }
  async requestJob(path, body, key, pending, storageKey) {
    if(this.localStorageScope)storageKey=this.localStorageScope+(storageKey==='carryon-pending'?'pending':'operations');
    const requestId = pending.get(key) || crypto.randomUUID();
    pending.set(key, requestId);
    sessionStorage.setItem(storageKey, JSON.stringify([...pending]));
    const scope=this.epoch;
    const composing=path.endsWith('/compose');
    if(composing)this.onSubmission({id:requestId,threadId:path.split('/')[2],prompt:body.prompt,skills:body.skills,mentions:body.mentions,files:body.files,uploads:body.uploads,state:'sending',begin:true});
    let job, admitted=false;
    try {
      job = await this.request(path, {...body, requestId});
      admitted=true;
      const deadline=Date.now()+20000;
      while(['preparing','dispatching'].includes(job.state)||(path==='/threads'&&job.state==='accepted'&&!job.createdThreadId)){
        if(scope!==this.epoch)throw Error('工作区已改变');
        if(Date.now()>=deadline)throw Error('请求仍在处理，请稍后核对；原请求编号已保留');
        await new Promise(resolve=>setTimeout(resolve,300));
        job=await this.request('/jobs/'+encodeURIComponent(requestId));
      }
    }
    catch(error){
      const rejected=!admitted&&!error.uncertain&&error.status>=400&&error.status<500&&error.status!==408;
      if(rejected){pending.delete(key);sessionStorage.setItem(storageKey,JSON.stringify([...pending]));}
      if(composing&&scope===this.epoch)this.onSubmission({id:requestId,threadId:path.split('/')[2],state:rejected?'failed':'uncertain'});
      throw error;
    }
    if(composing&&scope===this.epoch)this.onSubmission({...job,id:requestId,threadId:path.split('/')[2]});
    if(path==='/threads'&&!['failed','interrupted','uncertain'].includes(job.state)&&
      (!['accepted','completed','inProgress'].includes(job.state)||typeof job.createdThreadId!=='string'||!job.createdThreadId)){
      job={...job,state:'uncertain',error:'新会话身份尚未确认，请核对原请求；不会自动再次创建'};
    }
    if((path.endsWith('/archive')||path.endsWith('/unarchive'))&&(job.id!==requestId||job.threadId!==path.split('/')[2])){
      job={...job,state:'uncertain',error:'归档凭证身份不匹配，原请求已保留'};
    }
    if((path.endsWith('/archive')||path.endsWith('/unarchive'))&&['accepted','completed','inProgress'].includes(job.state)&&
      (job.state!=='completed'||job.id!==requestId||job.threadId!==path.split('/')[2]||job.result?.threadId!==path.split('/')[2]||job.result?.archived!==path.endsWith('/archive'))){
      job={...job,state:'uncertain',error:'归档状态尚未确认，请核对原请求'};
    }
    if(path.endsWith('/rename')&&(job.id!==requestId||job.threadId!==path.split('/')[2]||job.kind!=='rename'||job.name!==body.name||
      (['accepted','completed','inProgress'].includes(job.state)&&(job.state!=='completed'||job.result?.threadId!==path.split('/')[2]||job.result?.name!==body.name)))){
      job={...job,state:'uncertain',error:'重命名凭证或名称尚未确认，原请求已保留'};
    }
    if(path.endsWith('/section')&&(job.id!==requestId||job.threadId!==path.split('/')[2]||job.kind!=='section-move'||job.sectionId!==body.sectionId||
      (['accepted','completed','inProgress'].includes(job.state)&&(job.state!=='completed'||job.result?.threadId!==path.split('/')[2]||job.result?.sectionId!==body.sectionId)))){
      job={...job,state:'uncertain',error:'分组移动凭证尚未确认，原请求已保留'};
    }
    if((path==='/sections'||/^\/sections\/[^/]+$/.test(path))&&!await this.sectionReceiptMatches(job,requestId,path,body)){
      job={...job,state:'uncertain',error:'分组管理凭证尚未确认，原请求已保留'};
    }
    if(path.endsWith('/plugins')&&!await this.pluginReceiptMatches(job,requestId,path,body))job={...job,state:'uncertain',error:'插件管理凭证尚未确认，原请求已保留'};
    if(path.endsWith('/skills/config')&&!await this.skillConfigReceiptMatches(job,requestId,path,body))job={...job,state:'uncertain',error:'技能配置凭证尚未确认，原请求已保留'};
    if(path.endsWith('/terminals')&&!await this.terminalReceiptMatches(job,requestId,path,body))job={...job,state:'uncertain',error:'终端停止凭证尚未确认，原请求已保留'};
    if(path.endsWith('/fork')&&['accepted','completed','inProgress'].includes(job.state)&&
      (job.state!=='completed'||typeof job.createdThreadId!=='string'||!job.createdThreadId)){
      job={...job,state:'uncertain',error:'分叉身份尚未确认，请核对原请求；不会自动再次创建'};
    }
    if(path.endsWith('/side-chats')&&['accepted','completed','inProgress'].includes(job.state)&&
      (job.state!=='completed'||job.parentId!==path.split('/')[2]||typeof job.createdThreadId!=='string'||!job.createdThreadId)){
      job={...job,state:'uncertain',error:'临时聊天身份尚未确认，请核对原请求'};
    }
    if(path.startsWith('/side-chats/')&&path.endsWith('/close')&&
      (job.state!=='completed'||job.result?.closed!==true||job.result?.threadId!==path.split('/')[2])){
      job={...job,state:'uncertain',error:'临时聊天尚未确认结束，请核对原请求'};
    }
    if(body.action==='review'&&['accepted','inProgress','completed'].includes(job.state)&&
      (job.state!=='completed'||job.reviewThreadId!==path.split('/')[2]||typeof job.turnId!=='string'||!job.turnId)){
      job={...job,state:'uncertain',error:'尚未确认审查启动，请核对原请求；不会自动再次启动'};
    }
    if(['goal-set','goal-pause','goal-clear'].includes(body.action)&&['accepted','inProgress','completed'].includes(job.state)&&
      (job.state!=='completed'||(body.action==='goal-clear'?job.result?.cleared!==true:
        job.result?.goal?.threadId!==path.split('/')[2]||(body.action==='goal-pause'&&job.result?.goal?.status!=='paused')))){
      job={...job,state:'uncertain',error:'尚未确认目标变更，请核对原请求；不会自动再次执行'};
    }
    // Retain ambiguous receipts only; explicit rejections may be retried.
    if (['accepted','completed','inProgress','failed','interrupted','acknowledged'].includes(job.state)) {
      pending.delete(key);
      sessionStorage.setItem(storageKey, JSON.stringify([...pending]));
    }
    return job;
  }

  async submit(kind, target, prompt, images=[], isCurrent=()=>true, skills=[], mentions=[], files=[], uploads=[]) {
    images=[...images];
    skills=JSON.parse(JSON.stringify(skills));mentions=JSON.parse(JSON.stringify(mentions));files=JSON.parse(JSON.stringify(files));uploads=[...uploads];
    const epoch=this.epoch;
    let key=kind+':'+target+':'+prompt;
    if(images.length||skills.length||mentions.length||files.length||uploads.length){
      const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify([prompt,images,skills,mentions,files,...(uploads.length?[uploads]:[])])));
      key=kind+':'+target+':images:'+Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('');
    }
    if(epoch!==this.epoch||!isCurrent())throw Error('当前会话已改变，请重新发送');
    return this.requestJob('/threads/' + target + (kind==='compose'?'/compose':'/messages'),
      {prompt,...(images.length?{images}:{}),...(skills.length?{skills}:{}),...(mentions.length?{mentions}:{}),...(files.length?{files}:{}),...(uploads.length?{uploads}:{})}, key, this.pending, 'carryon-pending');
  }

  skills(target){return this.request('/threads/'+encodeURIComponent(target)+'/skills');}
  mentions(target){return this.request('/threads/'+encodeURIComponent(target)+'/mentions');}
  projectFiles(target,query){return this.request('/threads/'+encodeURIComponent(target)+'/files/search?query='+encodeURIComponent(query));}
  goal(target){return this.request('/threads/'+encodeURIComponent(target)+'/goal');}

  review(target,reviewTarget,isCurrent=()=>true){return this.operation(target,'review',{target:reviewTarget},isCurrent);}

  async createInProject(projectId,prompt,isCurrent=()=>true,images=[],settings=null,skills=[],mentions=[],uploads=[]){
    images=[...images];uploads=[...uploads];settings=settings===null?null:JSON.parse(JSON.stringify(settings));
    skills=skills.map(({name,path})=>({name,path}));mentions=mentions.map(({name,path})=>({name,path}));
    const epoch=this.epoch;
    const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify([projectId,prompt,images,settings,skills,mentions,...(uploads.length?[uploads]:[])])));
    if(epoch!==this.epoch)throw Error('配对已改变，请重新读取状态');
    if(!isCurrent())throw Error('工作区或项目已改变');
    const key='project:'+Array.from(new Uint8Array(bytes),v=>v.toString(16).padStart(2,'0')).join('');
    return this.requestJob('/threads',{projectId,prompt,images,settings,skills,mentions,...(uploads.length?{uploads:[...uploads]}:{})},key,this.pending,'carryon-pending');
  }

  async operation(target, action, fields, isCurrent = () => true) {
    fields=JSON.parse(JSON.stringify(fields));
    const epoch = this.epoch;
    const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify([target, action, fields])));
    if (epoch !== this.epoch) throw Error('配对已改变，请重新读取状态');
    if (!isCurrent()) throw Error('当前会话已改变，请重新操作');
    const key = Array.from(new Uint8Array(bytes), v => v.toString(16).padStart(2, '0')).join('');
    return this.requestJob('/threads/' + target + '/operations', {action, ...fields},
      key, this.operations, 'carryon-operations');
  }

  async fork(target,lastTurnId=null,isCurrent=()=>true){
    const epoch=this.epoch;
    const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(['fork',target,lastTurnId])));
    if(epoch!==this.epoch||!isCurrent())throw Error('当前会话已改变，请重新操作');
    const key='fork:'+Array.from(new Uint8Array(bytes),v=>v.toString(16).padStart(2,'0')).join('');
    return this.requestJob('/threads/'+target+'/fork',lastTurnId===null?{}:{lastTurnId},key,this.operations,'carryon-operations');
  }

  async pluginReceiptMatches(job,id,path,body){
    const target=decodeURIComponent(path.split('/')[2]);
    if(!['action,pluginId','action,discovery,pluginId'].includes(Object.keys(body).sort().join(','))||!['install','uninstall'].includes(body.action)||typeof body.pluginId!=='string'||!body.pluginId)return false;
    if('discovery'in body){const d=body.discovery;if(!d||Object.keys(d).sort().join(',')!=='cursor,scope,searchTerm'||typeof d.searchTerm!=='string'||!d.searchTerm.trim()||!['global','workspace','personal'].includes(d.scope)||d.cursor!==null&&(typeof d.cursor!=='string'||!d.cursor))return false;}
    if(job.id!==id||job.threadId!==target||job.kind!=='plugin-'+body.action||!job.body||await this.requestContent(path,job.body)!==await this.requestContent(path,body))return false;
    return !['accepted','completed','inProgress'].includes(job.state)||job.state==='completed'&&job.result?.threadId===target&&job.result?.pluginId===body.pluginId&&job.result?.installed===(body.action==='install');
  }
  async managePlugin(target,body,isCurrent=()=>true){
    body={...body,...(body.discovery?{discovery:{...body.discovery}}:{})};const epoch=this.epoch,key='plugin-management',content=key+':content',path='/threads/'+encodeURIComponent(target)+'/plugins';
    if(this.operations.has(key)||this.operations.has('skill-config'))throw Error('工作区配置待核对，请先核对原请求');
    const hash=await this.requestContent(path,body);if(epoch!==this.epoch||!isCurrent())throw Error('工作区或会话已改变');
    if(this.operations.has(key)||this.operations.has('skill-config'))throw Error('工作区配置待核对，请先核对原请求');
    this.operations.set(content,hash);
    try{return await this.requestJob(path,body,key,this.operations,'carryon-operations');}
    finally{if(epoch===this.epoch&&!this.operations.has(key)){this.operations.delete(content);this.saveOperations();}}
  }
  async queryPluginManagement(id,isCurrent=()=>true){
    const epoch=this.epoch,key='plugin-management',content=key+':content',job=await this.request('/jobs/'+encodeURIComponent(id)),path='/threads/'+encodeURIComponent(job.threadId)+'/plugins';
    const matches=job.body&&await this.requestContent(path,job.body)===this.operations.get(content)&&await this.pluginReceiptMatches(job,id,path,job.body);
    if(epoch!==this.epoch||!isCurrent())throw Error('工作区或会话已改变');
    if(this.operations.get(key)!==id||!matches)throw Error('插件凭证或内容身份不匹配，原请求已保留');
    if(['completed','failed','interrupted','acknowledged'].includes(job.state)){this.operations.delete(key);this.operations.delete(content);this.saveOperations();}
    return job;
  }

  async skillConfigReceiptMatches(job,id,path,body){
    const target=decodeURIComponent(path.split('/')[2]);
    if(Object.keys(body).sort().join(',')!=='enabled,path'||typeof body.enabled!=='boolean'||typeof body.path!=='string'||!body.path)return false;
    if(job.id!==id||job.threadId!==target||job.kind!=='skill-config'||!job.body||await this.requestContent(path,job.body)!==await this.requestContent(path,body))return false;
    return !['accepted','completed','inProgress'].includes(job.state)||job.state==='completed'&&job.result?.threadId===target&&job.result?.path===body.path&&job.result?.enabled===body.enabled;
  }
  async configureSkill(target,body,isCurrent=()=>true){
    body={...body};const epoch=this.epoch,key='skill-config',content=key+':content',path='/threads/'+encodeURIComponent(target)+'/skills/config';
    if(this.operations.has(key)||this.operations.has('plugin-management'))throw Error('技能配置待核对，请先核对原请求');
    const hash=await this.requestContent(path,body);if(epoch!==this.epoch||!isCurrent())throw Error('工作区或会话已改变');
    if(this.operations.has(key)||this.operations.has('plugin-management'))throw Error('技能配置待核对，请先核对原请求');
    this.operations.set(content,hash);
    try{return await this.requestJob(path,body,key,this.operations,'carryon-operations');}
    finally{if(epoch===this.epoch&&!this.operations.has(key)){this.operations.delete(content);this.saveOperations();}}
  }
  async querySkillConfiguration(id,isCurrent=()=>true){
    const epoch=this.epoch,key='skill-config',content=key+':content',job=await this.request('/jobs/'+encodeURIComponent(id)),path='/threads/'+encodeURIComponent(job.threadId)+'/skills/config';
    const matches=job.body&&await this.requestContent(path,job.body)===this.operations.get(content)&&await this.skillConfigReceiptMatches(job,id,path,job.body);
    if(epoch!==this.epoch||!isCurrent())throw Error('工作区或会话已改变');
    if(this.operations.get(key)!==id||!matches)throw Error('技能配置凭证或内容身份不匹配，原请求已保留');
    if(['completed','failed','interrupted','acknowledged'].includes(job.state)){this.operations.delete(key);this.operations.delete(content);this.saveOperations();}
    return job;
  }

  async terminalReceiptMatches(job,id,path,body){
    const target=decodeURIComponent(path.split('/')[2]),action=body.action;
    if(!['terminate','clean'].includes(action)||Object.keys(body).sort().join(',')!==(action==='clean'?'action':'action,processId')||action==='terminate'&&(typeof body.processId!=='string'||!body.processId))return false;
    if(job.id!==id||job.threadId!==target||job.kind!=='terminal-'+action||!job.body||await this.requestContent(path,job.body)!==await this.requestContent(path,body))return false;
    return !['accepted','completed','inProgress'].includes(job.state)||job.state==='completed'&&job.result?.threadId===target&&(action==='clean'?job.result.cleaned===true:job.result.processId===body.processId&&job.result.terminated===true);
  }
  async stopTerminal(target,body,isCurrent=()=>true){
    body={...body};const epoch=this.epoch,key='terminal:'+target,content=key+':content',path='/threads/'+encodeURIComponent(target)+'/terminals';
    if(this.operations.has(key))throw Error('终端操作待核对，请先核对原请求');
    const hash=await this.requestContent(path,body);
    if(epoch!==this.epoch||!isCurrent())throw Error('工作区或会话已改变');
    if(this.operations.has(key))throw Error('终端操作待核对，请先核对原请求');
    this.operations.set(content,hash);
    try{return await this.requestJob(path,body,key,this.operations,'carryon-operations');}
    finally{if(epoch===this.epoch&&!this.operations.has(key)){this.operations.delete(content);this.saveOperations();}}
  }
  async queryTerminal(target,id,isCurrent=()=>true){
    const epoch=this.epoch,key='terminal:'+target,content=key+':content',path='/threads/'+encodeURIComponent(target)+'/terminals',job=await this.request('/jobs/'+encodeURIComponent(id));
    const matches=job.body&&await this.requestContent(path,job.body)===this.operations.get(content)&&await this.terminalReceiptMatches(job,id,path,job.body);
    if(epoch!==this.epoch||!isCurrent())throw Error('工作区或会话已改变');
    if(this.operations.get(key)!==id||!matches)throw Error('终端凭证或内容身份不匹配，原请求已保留');
    if(['completed','failed','interrupted','acknowledged'].includes(job.state)){this.operations.delete(key);this.operations.delete(content);this.saveOperations();}
    return job;
  }

  async requestContent(path,body){
    const canonical=JSON.stringify([path,Object.keys(body).sort().map(key=>[key,body[key]])]);
    const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonical));
    return Array.from(new Uint8Array(bytes),v=>v.toString(16).padStart(2,'0')).join('');
  }
  async sectionReceiptMatches(job,id,path,body){
    const action=path==='/sections'?'create':body.action,sectionId=path==='/sections'?null:path.split('/')[2];
    if(!['create','update','delete','order'].includes(action)||job.id!==id||job.kind!=='section-'+action||job.sectionId!==sectionId||job.threadId!==(action==='order'?body.threadId:sectionId||'sections')||!job.body||await this.requestContent(path,job.body)!==await this.requestContent(path,body))return false;
    if(!['accepted','completed','inProgress'].includes(job.state))return true;
    return job.state==='completed'&&(action==='order'?job.result?.threadId===body.threadId&&job.result?.sectionId===sectionId&&Object.hasOwn(job.result,'beforeThreadId')&&job.result.beforeThreadId===body.beforeThreadId:action==='delete'?job.result?.sectionId===sectionId&&job.result?.deleted===true:
      typeof job.result?.section?.id==='string'&&!!job.result.section.id&&job.result.section.name===body.name&&(action==='create'||job.result.section.id===sectionId));
  }
  async manageSection(sectionId,body,isCurrent=()=>true){
    body={...body};
    const epoch=this.epoch,key='section-management',content='section-management-content',path=sectionId===null?'/sections':'/sections/'+encodeURIComponent(sectionId);
    if(this.operations.has(key))throw Error('分组操作待核对，请先核对原请求');
    const hash=await this.requestContent(path,body);if(epoch!==this.epoch||!isCurrent())throw Error('工作区已改变');
    if(this.operations.has(key))throw Error('分组操作待核对，请先核对原请求');
    this.operations.set(content,hash);
    try{return await this.requestJob(path,body,key,this.operations,'carryon-operations');}
    finally{if(epoch===this.epoch&&!this.operations.has(key)){this.operations.delete(content);this.saveOperations();}}
  }
  saveOperations(){sessionStorage.setItem(this.storageScope?this.storageScope+'operations':this.localStorageScope?this.localStorageScope+'operations':'carryon-operations',JSON.stringify([...this.operations]));}
  async querySectionManagement(id,isCurrent=()=>true){
    const epoch=this.epoch,job=await this.request('/jobs/'+encodeURIComponent(id)),key='section-management',content='section-management-content';
    const path=job.sectionId===null?'/sections':'/sections/'+encodeURIComponent(job.sectionId);
    const matches=job.body&&await this.requestContent(path,job.body)===this.operations.get(content)&&await this.sectionReceiptMatches(job,id,path,job.body);
    if(epoch!==this.epoch||!isCurrent())throw Error('工作区已改变');
    if(this.operations.get(key)!==id||!matches)throw Error('分组管理凭证或内容身份不匹配，原请求已保留');
    if(['completed','failed','interrupted','acknowledged'].includes(job.state)){this.operations.delete(key);this.operations.delete(content);this.saveOperations();}
    return job;
  }

  async moveThreadSection(target,sectionId,isCurrent=()=>true){
    if(!isCurrent())throw Error('当前会话已改变');
    const key='section-move:'+target,content='section-content:'+target,epoch=this.epoch;
    if(this.operations.has(key))throw Error('分组移动待核对，请先核对原请求');
    this.operations.set(content,JSON.stringify(sectionId));
    try{return await this.requestJob('/threads/'+target+'/section',{sectionId},key,this.operations,'carryon-operations');}
    finally{if(epoch===this.epoch&&!this.operations.has(key)){this.operations.delete(content);sessionStorage.setItem(this.storageScope?this.storageScope+'operations':this.localStorageScope?this.localStorageScope+'operations':'carryon-operations',JSON.stringify([...this.operations]));}}
  }
  async queryThreadSection(target,requestId,isCurrent=()=>true){
    const epoch=this.epoch,job=await this.request('/jobs/'+encodeURIComponent(requestId)),key='section-move:'+target,content='section-content:'+target;
    if(epoch!==this.epoch||!isCurrent())throw Error('工作区已改变');
    if(job.id!==requestId||job.threadId!==target||job.kind!=='section-move'||
      (job.sectionId!==null&&typeof job.sectionId!=='string')||this.operations.get(key)!==requestId||this.operations.get(content)!==JSON.stringify(job.sectionId))throw Error('分组移动凭证或内容身份不匹配');
    const confirmed=job.state==='completed'&&job.result?.threadId===target&&job.result?.sectionId===job.sectionId;
    if(confirmed||['failed','interrupted','acknowledged'].includes(job.state)){
      this.operations.delete(key);this.operations.delete(content);sessionStorage.setItem(this.storageScope?this.storageScope+'operations':this.localStorageScope?this.localStorageScope+'operations':'carryon-operations',JSON.stringify([...this.operations]));
    }
    return confirmed?job:{...job,state:job.state==='completed'?'uncertain':job.state};
  }
  async renameThread(target,name,isCurrent=()=>true){
    const epoch=this.epoch;
    if(!isCurrent())throw Error('当前会话已改变');
    if(this.operations.has('rename:'+target))throw Error('重命名待核对，请先核对原请求');
    const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(name));
    if(epoch!==this.epoch||!isCurrent())throw Error('工作区已改变');
    if(this.operations.has('rename:'+target))throw Error('重命名待核对，请先核对原请求');
    this.operations.set('rename-content:'+target,Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join(''));
    try{return await this.requestJob('/threads/'+target+'/rename',{name},'rename:'+target,this.operations,'carryon-operations');}
    finally{if(epoch===this.epoch&&!this.operations.has('rename:'+target)){this.operations.delete('rename-content:'+target);sessionStorage.setItem(this.storageScope?this.storageScope+'operations':this.localStorageScope?this.localStorageScope+'operations':'carryon-operations',JSON.stringify([...this.operations]));}}
  }
  async queryRename(target,requestId,isCurrent=()=>true){
    const epoch=this.epoch,job=await this.request('/jobs/'+encodeURIComponent(requestId));
    if(epoch!==this.epoch||!isCurrent())throw Error('工作区已改变');
    if(job.id!==requestId||job.threadId!==target||job.kind!=='rename')throw Error('重命名凭证身份不匹配');
    if(typeof job.name!=='string')throw Error('重命名内容身份不匹配');
    const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(job.name));
    if(epoch!==this.epoch||!isCurrent())throw Error('工作区已改变');
    if(this.operations.get('rename:'+target)!==requestId||this.operations.get('rename-content:'+target)!==Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join(''))throw Error('重命名内容身份不匹配');
    const confirmed=job.state==='completed'&&job.result?.threadId===target&&typeof job.name==='string'&&job.name.length>0&&job.result?.name===job.name;
    if(confirmed||['failed','interrupted','acknowledged'].includes(job.state)){
      const key='rename:'+target;
      if(this.operations.get(key)===requestId){this.operations.delete(key);this.operations.delete('rename-content:'+target);sessionStorage.setItem(this.storageScope?this.storageScope+'operations':this.localStorageScope?this.localStorageScope+'operations':'carryon-operations',JSON.stringify([...this.operations]));}
    }
    return confirmed?job:{...job,state:job.state==='completed'?'uncertain':job.state};
  }
  archiveThread(target, restoring, isCurrent=()=>true){
    if(!isCurrent())throw Error('当前会话已改变');
    const action=restoring?'unarchive':'archive';
    return this.requestJob('/threads/'+target+'/'+action,{},action+':'+target,this.operations,'carryon-operations');
  }
  async queryArchive(target, restoring, requestId, isCurrent=()=>true){
    const epoch=this.epoch,job=await this.request('/jobs/'+encodeURIComponent(requestId));
    if(epoch!==this.epoch||!isCurrent())throw Error('工作区已改变');
    if(job.id!==requestId||job.threadId!==target)throw Error('归档凭证身份不匹配');
    const confirmed=job.state==='completed'&&job.result?.threadId===target&&job.result?.archived===!restoring;
    if(confirmed||['failed','interrupted','acknowledged'].includes(job.state)){
      const key=(restoring?'unarchive':'archive')+':'+target;
      if(this.operations.get(key)===requestId){
        this.operations.delete(key);
        sessionStorage.setItem(this.storageScope?this.storageScope+'operations':this.localStorageScope?this.localStorageScope+'operations':'carryon-operations',JSON.stringify([...this.operations]));
      }
    }
    return confirmed?job:{...job,state:job.state==='completed'?'uncertain':job.state};
  }

  async createSide(parent,isCurrent=()=>true){
    if(!isCurrent())throw Error('当前会话已改变');
    return this.requestJob('/threads/'+parent+'/side-chats',{},'side-create:'+parent,this.operations,'carryon-operations');
  }
  async closeSide(parent,target,isCurrent=()=>true){
    if(!isCurrent())throw Error('当前会话已改变');
    return this.requestJob('/side-chats/'+target+'/close',{parentId:parent},'side-close:'+parent+':'+target,this.operations,'carryon-operations');
  }

  async sideAction(parent, target, action, fields, isCurrent = () => true) {
    const epoch = this.epoch;
    const body = JSON.parse(JSON.stringify({parentId: parent, ...fields, ...(action === 'compose' ? {} : {action})}));
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify([parent, target, action, body])));
    if (epoch !== this.epoch || !isCurrent()) throw Error('当前临时聊天已改变，请重新操作');
    const key = 'side:' + Array.from(new Uint8Array(digest), v => v.toString(16).padStart(2, '0')).join('');
    return this.requestJob('/side-chats/' + target + (action === 'compose' ? '/compose' : '/operations'),
      body, key, this.operations, 'carryon-operations');
  }

  subscribe(selection) {
    const normalized={historyProtocol:1,historyLimit:40,...selection};
    const previous=this.selection&&Object.fromEntries(Object.entries(this.selection).filter(([key])=>!['type','subscription'].includes(key)));
    if(previous&&JSON.stringify(previous)===JSON.stringify(normalized)){this.connect();return this.selection.subscription;}
    this.selection = {historyProtocol:1, historyLimit:40, ...selection, type: 'subscribe', subscription: crypto.randomUUID()};
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify(this.selection));
    else this.connect();
    return this.selection.subscription;
  }

  probe(){
    if(this.socket?.readyState!==WebSocket.OPEN||this.probePending)return;
    const socket=this.socket;this.probePending=true;clearTimeout(this.healthTimer);
    socket.send(JSON.stringify({type:'ping'}));
    this.healthTimer=setTimeout(()=>{if(this.socket===socket)socket.close();},15000);
  }
  scheduleProbe(){this.probePending=false;clearTimeout(this.healthTimer);this.healthTimer=setTimeout(()=>this.probe(),15000);}
  resume() {
    // Browser WebSocket control pongs are invisible to JavaScript.
    if(this.socket?.readyState===WebSocket.OPEN)this.probe();else this.connect();
  }

  connect() {
    if (!this.token || this.socket) return;
    clearTimeout(this.timer);
    const url = new URL('/api/stream', location.href);
    url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(url);
    const wire = new HistoryWire();
    this.socket = socket;
    this.healthTimer=setTimeout(()=>{if(this.socket===socket)socket.close();},15000);
    const current = () => this.socket === socket;
    socket.onopen = () => {
      if (!current()) return;
      this.delay = 500;
      this.lastReceived=Date.now();this.scheduleProbe();
      socket.send(JSON.stringify({type: 'auth', token: this.token}));
      if (this.selection) socket.send(JSON.stringify(this.selection));
    };
    socket.onmessage = async event => {
      if (!current()) return;
      try {
        this.lastReceived=Date.now();
        const packet=JSON.parse(event.data);
        if(packet.type==='pong'){this.scheduleProbe();return;}
        const data = wire.decode(packet);
        if (data.type === 'update') await this.onUpdate(data, current);
      } catch (error) { if (current()) { this.onError(error); socket.close(); } }
    };
    socket.onclose = event => {
      if (!current()) return;
      this.socket = null;clearTimeout(this.healthTimer);this.probePending=false;
      this.onDisconnect(event);
      if (event.code === 1008) { this.onAuthError(); return; }
      this.timer = setTimeout(() => this.connect(), this.delay);
      this.delay = Math.min(10000, this.delay * 2);
    };
  }

  close() {
    clearTimeout(this.healthTimer);this.probePending=false;
    clearTimeout(this.timer);
    const socket = this.socket;
    this.socket = null;
    if (socket) socket.close();
  }

  pair(token) {
    this.close();
    this.epoch++;
    this.selection = null;
    this.token = token.trim();
    sessionStorage.setItem('carryon-token', this.token);
    this.delay = 500;
  }
}
