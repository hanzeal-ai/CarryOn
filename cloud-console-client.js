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
    const result=await response.json();
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
      picker.replaceChildren(...session.devices.map(d=>new Option(d.id+(d.online?' · 在线':' · 离线'),d.id)));
      if(!session.devices.some(d=>d.id===this.device))this.device=session.devices[0]?.id||'';
      picker.value=this.device;this.setStorage();
      return session;
    } catch(error){this.token='';throw error;}
  }
  setStorage() {
    sessionStorage.setItem('connectnow-cloud-device',this.device);
    this.storageScope='connectnow-cloud:'+this.base.href+':'+this.device+':';
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
    this.close();
    this.selection={...selection,subscription:crypto.randomUUID()};
    this.connect();return this.selection.subscription;
  }
  connect() {
    if(!this.token||!this.device||this.active)return;
    if(!this.selection)this.selection={threadId:null,threadIds:[],subscription:crypto.randomUUID()};
    this.active=true;
    const generation=++this.loop, selection=this.selection,device=this.device;
    const current=()=>this.loop===generation;
    const route='devices/'+encodeURIComponent(device)+'/streams';
    const run=async()=>{
      let sid;
      try {
        const status=await this.request('/status');
        if(!current())return;
        await this.onUpdate({type:'update',status,subscription:selection.subscription,threadId:selection.threadId},current);
        if(!current()||!status.enabled)return;
        const created=await this.consoleRequest(route,selection);sid=created.streamId;
        let revision=-1;
        while(current()){
          const packet=await this.consoleRequest(route+'/'+sid+'?after='+revision);
          if(!current())break;
          if(packet.body&&packet.revision>revision){
            await this.onUpdate({...packet.body,subscription:selection.subscription},current);
          }
          revision=packet.revision;
        }
      } catch(error){if(current()){this.onDisconnect({});this.onError(error);}}
      finally {
        if(sid)await this.consoleRequest(route+'/'+sid,undefined,'DELETE').catch(()=>{});
        if(current()){this.active=false;this.timer=setTimeout(()=>this.connect(),2000);}
      }
    };
    run();
  }
  close() {this.loop++;this.active=false;clearTimeout(this.timer);}
}
