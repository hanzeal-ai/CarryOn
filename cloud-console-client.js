/* Browser session -> console backend -> embedded device connection module. */
class CloudConsoleClient extends CarryOnClient {
  constructor(options) {
    super(options);
    this.token='';
    this.base=new URL('.',document.querySelector('script[src$="/cloud-console-client.js"]').src);
    this.device=sessionStorage.getItem('carryon-cloud-device')||'';
    this.loop=0;this.active=false;
  }
  get initializationCommand() {
    if(this.base.href==='https://carryon.hanzeal.com/')return 'carryon init';
    if(this.base.protocol!=='https:')return '';
    return "carryon init --url '"+this.base.href.replaceAll("'","'\\''")+"'";
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
    sessionStorage.setItem('carryon-cloud-device',this.device);
    const scope='carryon-cloud:'+this.base.href+':'+this.device+':';
    if(this.storageScope===scope)return;
    this.storageScope=scope;
    this.pending=this.restore(this.storageScope+'pending');
    this.operations=this.restore(this.storageScope+'operations');
  }
  async pair(token,username) {
    this.close();this.epoch++;this.selection=null;
    await this.consoleRequest('login',username===undefined?{token:token.trim()}:{username:username.trim(),password:token});
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
      this.storageScope+(storageKey==='carryon-pending'?'pending':'operations'),retainUncertain);
  }
  subscribe(selection) {
    const key=JSON.stringify([this.epoch,this.device,selection.threadId??null,
      [...new Set(selection.threadIds||[])].sort(),selection.includeSideChats===true,selection.sideThreadId??null,selection.historyLimit??40,selection.sideHistoryLimit??selection.historyLimit??40,selection.historyProtocol??1]);
    if(this.selection && this.selectionKey===key){
      this.connect();return this.selection.subscription;
    }
    const reuse=this.supportsResubscribe&&this.socket?.readyState===WebSocket.OPEN&&this.socketScope===JSON.stringify([this.epoch,this.device]);
    if(!reuse)this.close();
    this.selectionKey=key;
    this.selection={historyProtocol:1,historyLimit:40,...selection,subscription:crypto.randomUUID()};
    if(reuse)this.socket.send(JSON.stringify({type:'subscribe',...this.selection}));
    else this.connect();
    return this.selection.subscription;
  }
  connect() {
    if(this.removing||!this.token||!this.device||this.active)return;
    if(!this.selection)this.selection={historyProtocol:1,historyLimit:40,threadId:null,threadIds:[],subscription:crypto.randomUUID()};
    this.active=true;
    const generation=++this.loop;
    this.socketScope=JSON.stringify([this.epoch,this.device]);this.supportsResubscribe=false;
    const current=()=>this.loop===generation;
    const url=new URL('console/devices/'+encodeURIComponent(this.device)+'/ws',this.base);
    url.protocol=url.protocol==='https:'?'wss:':'ws:';
    const socket=new WebSocket(url);this.socket=socket;
    let revision=0,pending=null,processing=false;
    const wire=new HistoryWire();
    const drain=async()=>{
      if(processing)return;
      processing=true;
      try{
        while(pending&&current()&&this.socket===socket){
          const packet=pending;pending=null;
          const selected=packet.subscription;
          if(this.selection?.subscription!==selected)continue;
          await this.onUpdate({...packet.body,subscription:selected},()=>current()&&this.socket===socket&&this.selection?.subscription===selected);
        }
      }catch(error){if(current()&&this.socket===socket){this.onError(error);socket.close();}}
      finally{processing=false;}
    };
    const heartbeat=()=>{clearTimeout(this.heartbeatTimer);this.heartbeatTimer=setTimeout(()=>{if(current())socket.close();},45000);};
    socket.onopen=()=>{if(current()){heartbeat();socket.send(JSON.stringify({type:'subscribe',...this.selection}));}else socket.close();};
    socket.onmessage=event=>{
      if(!current())return;heartbeat();
      let packet;
      try{packet=JSON.parse(event.data);}catch(error){this.onError(error);socket.close();return;}
      if(packet.type==='ping'){socket.send(JSON.stringify({type:'pong'}));return;}
      if(packet.type==='error'){
        if(packet.status===401){this.token='';this.close();this.onAuthError();return;}
        this.onError(Error(packet.error||'实时订阅失败'));socket.close();return;
      }
      if(packet.type!=='update'||packet.subscription!==this.selection?.subscription||!Number.isInteger(packet.revision)||packet.revision<=revision)return;
      if(!packet.body||packet.body.type!=='update'){this.onError(Error('实时更新格式无效'));socket.close();return;}
      revision=packet.revision;this.supportsResubscribe=packet.resubscribe===true;
      // Packets are complete projections: retain only the newest one while rendering.
      try{pending={...packet,body:wire.decode({...packet.body,subscription:packet.subscription})};drain();}
      catch(error){this.onError(error);socket.close();}
    };
    socket.onclose=async()=>{
      if(!current())return;
      clearTimeout(this.heartbeatTimer);pending=null;this.socket=null;this.active=false;this.onDisconnect({});
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
