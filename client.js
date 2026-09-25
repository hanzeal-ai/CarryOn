/* HTTP authentication, durable retry IDs and the live connection lifecycle. */
'use strict';
async function readApiResponse(response) {
  try { return await response.json(); }
  catch {
    if (response.status === 413) throw Error('图片请求超过服务器大小限制，请减少图片或压缩后重试');
    throw Error(response.ok ? '服务器返回了无效数据，请重试' : '服务请求失败（HTTP '+response.status+'），请稍后重试');
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
  if(!previous||update.state==='acknowledged')return null;
  // Live journal evidence can arrive before the HTTP admission response.
  if(previous.live&&!live)return previous;
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
      throw Error(result.error || '请求失败');
    }
    return result;
  }

  setWorkspaceSession(session){
    if(this.workspaceSession===session)return;
    if(this.workspaceSession)this.epoch++;
    this.workspaceSession=session;this.localStorageScope='carryon-local:'+session+':';
    this.pending=this.restore(this.localStorageScope+'pending');this.operations=this.restore(this.localStorageScope+'operations');
  }
  async requestJob(path, body, key, pending, storageKey, retainUncertain = false) {
    if(this.localStorageScope)storageKey=this.localStorageScope+(storageKey==='carryon-pending'?'pending':'operations');
    const requestId = pending.get(key) || crypto.randomUUID();
    pending.set(key, requestId);
    sessionStorage.setItem(storageKey, JSON.stringify([...pending]));
    const scope=this.epoch;
    const composing=path.endsWith('/compose');
    if(composing)this.onSubmission({id:requestId,threadId:path.split('/')[2],prompt:body.prompt,state:'sending',begin:true});
    let job;
    try { job = await this.request(path, {...body, requestId}); }
    catch(error){if(composing&&scope===this.epoch)this.onSubmission({id:requestId,threadId:path.split('/')[2],state:'uncertain'});throw error;}
    if(composing&&scope===this.epoch)this.onSubmission({...job,id:requestId,threadId:path.split('/')[2]});
    // A known failed/uncertain operation keeps its ID for explicit reconciliation.
    if (!retainUncertain || (job.state !== 'failed' && job.state !== 'uncertain')) {
      pending.delete(key);
      sessionStorage.setItem(storageKey, JSON.stringify([...pending]));
    }
    return job;
  }

  async submit(kind, target, prompt, images=[], isCurrent=()=>true) {
    const epoch=this.epoch;
    let key=kind+':'+target+':'+prompt;
    if(images.length){
      const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify([prompt,images])));
      key=kind+':'+target+':images:'+Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('');
    }
    if(epoch!==this.epoch||!isCurrent())throw Error('当前会话已改变，请重新发送');
    return this.requestJob(kind === 'create' ? '/threads' : '/threads/' + target + (kind==='compose'?'/compose':'/messages'),
      {prompt,...(images.length?{images}:{})}, key, this.pending, 'carryon-pending',kind==='compose');
  }

  async createInProject(projectId,prompt,isCurrent=()=>true){
    if(!isCurrent())throw Error('工作区或项目已改变');
    return this.requestJob('/threads',{projectId,prompt},'project:'+projectId+':'+prompt,this.pending,'carryon-pending',true);
  }

  async operation(target, action, fields, isCurrent = () => true) {
    const epoch = this.epoch;
    const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify([target, action, fields])));
    if (epoch !== this.epoch) throw Error('配对已改变，请重新读取状态');
    if (!isCurrent()) throw Error('当前会话已改变，请重新操作');
    const key = Array.from(new Uint8Array(bytes), v => v.toString(16).padStart(2, '0')).join('');
    return this.requestJob('/threads/' + target + '/operations', {action, ...fields},
      key, this.operations, 'carryon-operations', true);
  }

  async sideAction(parent, target, action, fields, isCurrent = () => true) {
    const epoch = this.epoch;
    const body = {parentId: parent, ...fields, ...(action === 'compose' ? {} : {action})};
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify([parent, target, action, body])));
    if (epoch !== this.epoch || !isCurrent()) throw Error('当前临时聊天已改变，请重新操作');
    const key = 'side:' + Array.from(new Uint8Array(digest), v => v.toString(16).padStart(2, '0')).join('');
    return this.requestJob('/side-chats/' + target + (action === 'compose' ? '/compose' : '/operations'),
      body, key, this.operations, 'carryon-operations', true);
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
