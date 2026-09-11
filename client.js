/* HTTP authentication, durable retry IDs and the live connection lifecycle. */
'use strict';
async function readApiResponse(response) {
  try { return await response.json(); }
  catch {
    if (response.status === 413) throw Error('图片请求超过服务器大小限制，请减少图片或压缩后重试');
    throw Error(response.ok ? '服务器返回了无效数据，请重试' : '服务请求失败（HTTP '+response.status+'），请稍后重试');
  }
}
class ConnectNowClient {
  constructor({onUpdate, onDisconnect, onAuthError, onError}) {
    this.onUpdate = onUpdate;
    this.onDisconnect = onDisconnect;
    this.onAuthError = onAuthError;
    this.onError = onError;
    const fragment = new URLSearchParams(location.hash.slice(1));
    this.token = fragment.get('token') || sessionStorage.getItem('connectnow-token') || '';
    if (fragment.has('token')) history.replaceState(null, '', location.pathname);
    if (this.token) sessionStorage.setItem('connectnow-token', this.token);
    this.pending = this.restore('connectnow-pending');
    this.operations = this.restore('connectnow-operations');
    this.socket = null;
    this.timer = null;
    this.delay = 500;
    this.selection = null;
    this.epoch = 0;
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

  async requestJob(path, body, key, pending, storageKey, retainUncertain = false) {
    const requestId = pending.get(key) || crypto.randomUUID();
    pending.set(key, requestId);
    sessionStorage.setItem(storageKey, JSON.stringify([...pending]));
    const job = await this.request(path, {...body, requestId});
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
    return this.requestJob(kind === 'create' ? '/threads' : '/threads/' + target + '/messages',
      {prompt,...(images.length?{images}:{})}, key, this.pending, 'connectnow-pending');
  }

  async operation(target, action, fields, isCurrent = () => true) {
    const epoch = this.epoch;
    const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify([target, action, fields])));
    if (epoch !== this.epoch) throw Error('配对已改变，请重新读取状态');
    if (!isCurrent()) throw Error('当前会话已改变，请重新操作');
    const key = Array.from(new Uint8Array(bytes), v => v.toString(16).padStart(2, '0')).join('');
    return this.requestJob('/threads/' + target + '/operations', {action, ...fields},
      key, this.operations, 'connectnow-operations', true);
  }

  subscribe(selection) {
    this.selection = {...selection, type: 'subscribe', subscription: crypto.randomUUID()};
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify(this.selection));
    else this.connect();
    return this.selection.subscription;
  }

  connect() {
    if (!this.token || this.socket) return;
    clearTimeout(this.timer);
    const url = new URL('/api/stream', location.href);
    url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(url);
    this.socket = socket;
    const current = () => this.socket === socket;
    socket.onopen = () => {
      if (!current()) return;
      this.delay = 500;
      socket.send(JSON.stringify({type: 'auth', token: this.token}));
      if (this.selection) socket.send(JSON.stringify(this.selection));
    };
    socket.onmessage = async event => {
      if (!current()) return;
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'update') await this.onUpdate(data, current);
      } catch (error) { if (current()) this.onError(error); }
    };
    socket.onclose = event => {
      if (!current()) return;
      this.socket = null;
      this.onDisconnect(event);
      if (event.code === 1008) { this.onAuthError(); return; }
      this.timer = setTimeout(() => this.connect(), this.delay);
      this.delay = Math.min(10000, this.delay * 2);
    };
  }

  close() {
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
    sessionStorage.setItem('connectnow-token', this.token);
    this.delay = 500;
  }
}
