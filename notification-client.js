/* Reader cursors and notification delivery stay separate from native approvals. */
class NotificationFeed {
  constructor({request,storage,onEvent}){this.request=request;this.storage=storage;this.onEvent=onEvent;this.generation=0;this.scope='';this.running=false;}
  changeScope(scope){if(scope!==this.scope){this.scope=scope;this.generation++;this.running=false;this.syncTask=null;this.revision=undefined;globalThis.clearTimeout?.(this.retry);}}
  pause(){this.generation++;this.running=false;this.syncTask=null;this.revision=undefined;globalThis.clearTimeout?.(this.retry);}
  invalidate(revision,force=false){
    if(!force&&this.revision===revision)return this.syncTask;
    this.revision=revision;this.dirty=true;
    if(this.syncTask)return this.syncTask;
    globalThis.clearTimeout?.(this.retry);
    const generation=this.generation;
    const task=(async()=>{
      try{
        while(this.dirty&&generation===this.generation){this.dirty=false;await this.poll();}
        this.retryDelay=1000;
      }catch(error){
        if(generation===this.generation){
          this.retryDelay=Math.min(30000,(this.retryDelay||500)*2);
          this.retry=setTimeout(()=>this.invalidate(this.revision,true),this.retryDelay);
        }
      }finally{if(this.syncTask===task)this.syncTask=null;}
    })();
    this.syncTask=task;return task;
  }
  async poll(){
    if(this.running||!this.scope)return;
    const generation=this.generation,scope=this.scope;this.running=true;
    try{
      const key=scope+':notifications';
      const prefs=(await this.request('/notifications/preferences')).preferences;
      if(generation!==this.generation)return;
      while(generation===this.generation){
      const after=Number(this.storage.getItem(key)||0);
      const packet=await this.request('/notifications?after='+after);
      if(generation!==this.generation)return;
      for(const event of packet.events){
        if(generation!==this.generation)return;
        await this.onEvent(event,prefs[event.kind]===true);
      }
      if(generation===this.generation)this.storage.setItem(key,String(packet.nextSequence));
      if(packet.nextSequence<=after||packet.hasMore!==true)return;
      }
    }finally{if(generation===this.generation)this.running=false;}
  }
}
