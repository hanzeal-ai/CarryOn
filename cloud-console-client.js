/* Browser session -> console backend -> embedded device connection module. */
class CloudConsoleClient extends ConnectNowClient {
  constructor(options) {
    super(options);
    this.token='';
    this.base=new URL('.',document.querySelector('script[src$="/cloud-console-client.js"]').src);
    this.device=sessionStorage.getItem('connectnow-cloud-device')||'';
    this.loop=0;this.active=false;
  }
  async consoleRequest(path,body,method) {
    const epoch=this.epoch;
    const response=await fetch(new URL('console/'+path,this.base),{
      method:method||(body===undefined?'GET':'POST'),credentials:'same-origin',
      headers:body===undefined?{}:{'Content-Type':'application/json'},
      ...(body===undefined?{}:{body:JSON.stringify(body)})
    });
    const result=await readApiResponse(response);
    if(epoch!==this.epoch)throw Error('设备已改变，请重新读取状态');
    if(!response.ok){
      if(response.status===401){this.token='';this.close();this.onAuthError();}
      throw Error(result.error||'云端请求失败');
    }
    return result;
  }
  async initialize() {
    try {
      const session=await this.consoleRequest('session');
      this.token='session';
      const picker=document.getElementById('console-device');
      picker.replaceChildren(...session.devices.map(d=>new Option((d.name||d.id)+(d.online?' · 在线':' · 离线'),d.id)));
      if(!session.devices.some(d=>d.id===this.device))this.device=session.devices[0]?.id||'';
      picker.value=this.device;this.setStorage();
      return session;
    } catch(error){this.token='';throw error;}
  }
  setStorage() {
    sessionStorage.setItem('connectnow-cloud-device',this.device);
    const scope='connectnow-cloud:'+this.base.href+':'+this.device+':';
    if(this.storageScope===scope)return;
    this.storageScope=scope;
    this.pending=this.restore(this.storageScope+'pending');
    this.operations=this.restore(this.storageScope+'operations');
  }
  async pair(token) {
    this.close();this.epoch++;this.selection=null;
    await this.consoleRequest('login',{token:token.trim()});
    await this.initialize();
  }
  async request(path,body) {
    if(!this.device)throw Error('请先选择云端设备');
    const epoch=this.epoch;
    const result=await this.consoleRequest('devices/'+encodeURIComponent(this.device)+'/request',
      {method:body===undefined?'GET':'POST',path:'/api'+path,body});
    if(epoch!==this.epoch)throw Error('设备已改变，请重新读取状态');
    return result;
  }
  requestJob(path,body,key,pending,storageKey,retainUncertain=false) {
    return super.requestJob(path,body,key,pending,
      this.storageScope+(storageKey==='connectnow-pending'?'pending':'operations'),retainUncertain);
  }
  subscribe(selection) {
    const key=JSON.stringify([this.epoch,this.device,selection.threadId??null,
      [...new Set(selection.threadIds||[])].sort(),selection.includeSideChats===true,selection.sideThreadId??null]);
    if(this.selection && this.selectionKey===key){
      this.connect();return this.selection.subscription;
    }
    this.close();
    this.selectionKey=key;
    this.selection={...selection,subscription:crypto.randomUUID()};
    this.connect();return this.selection.subscription;
  }
  connect() {
    if(this.removing||!this.token||!this.device||this.active)return;
    if(!this.selection)this.selection={threadId:null,threadIds:[],subscription:crypto.randomUUID()};
    this.active=true;
    const generation=++this.loop,selection=this.selection;
    const current=()=>this.loop===generation;
    const url=new URL('console/devices/'+encodeURIComponent(this.device)+'/ws',this.base);
    url.protocol=url.protocol==='https:'?'wss:':'ws:';
    const socket=new WebSocket(url);this.socket=socket;
    let revision=0,chain=Promise.resolve();
    const heartbeat=()=>{clearTimeout(this.heartbeatTimer);this.heartbeatTimer=setTimeout(()=>{if(current())socket.close();},45000);};
    socket.onopen=()=>{if(current()){heartbeat();socket.send(JSON.stringify({type:'subscribe',...selection}));}else socket.close();};
    socket.onmessage=event=>{
      if(!current())return;heartbeat();
      chain=chain.then(async()=>{
        if(!current())return;
        const packet=JSON.parse(event.data);
        if(packet.type==='ping'){socket.send(JSON.stringify({type:'pong'}));return;}
        if(packet.type==='error'){
          if(packet.status===401){this.token='';this.close();this.onAuthError();return;}
          throw Error(packet.error||'实时订阅失败');
        }
        if(packet.type!=='update'||packet.subscription!==selection.subscription||!Number.isInteger(packet.revision)||packet.revision<=revision)return;
        if(!packet.body||packet.body.type!=='update')throw Error('实时更新格式无效');
        revision=packet.revision;
        await this.onUpdate({...packet.body,subscription:selection.subscription},current);
      }).catch(error=>{if(current()){this.onError(error);socket.close();}});
    };
    socket.onclose=async()=>{
      if(!current())return;
      clearTimeout(this.heartbeatTimer);this.socket=null;this.active=false;this.onDisconnect({});
      // Browsers do not expose HTTP handshake failures; distinguish expiry via HTTP.
      try{await this.consoleRequest('session');}catch(error){if(!this.token||!current())return;}
      if(current()&&this.token)this.timer=setTimeout(()=>this.connect(),2000);
    };
    socket.onerror=()=>{}; // onclose owns retry; never replay HTTP writes.
  }
  close() {
    this.loop++;this.active=false;clearTimeout(this.timer);clearTimeout(this.heartbeatTimer);
    const socket=this.socket;this.socket=null;if(socket)socket.close();
  }
}
