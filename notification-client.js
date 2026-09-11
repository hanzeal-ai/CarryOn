/* Reader cursors and notification delivery stay separate from native approvals. */
class NotificationFeed {
  constructor({request,storage,onEvent}){this.request=request;this.storage=storage;this.onEvent=onEvent;this.generation=0;this.scope='';this.running=false;}
  changeScope(scope){if(scope!==this.scope){this.scope=scope;this.generation++;this.running=false;}}
  async poll(){
    if(this.running||!this.scope)return;
    const generation=this.generation,scope=this.scope;this.running=true;
    try{
      const key=scope+':notifications',after=Number(this.storage.getItem(key)||0);
      const packet=await this.request('/notifications?after='+after);
      if(generation!==this.generation)return;
      const prefs=(await this.request('/notifications/preferences')).preferences;
      if(generation!==this.generation)return;
      for(const event of packet.events){
        if(generation!==this.generation)return;
        await this.onEvent(event,prefs[event.kind]===true);
      }
      if(generation===this.generation)this.storage.setItem(key,String(packet.nextSequence));
    }finally{if(generation===this.generation)this.running=false;}
  }
}
