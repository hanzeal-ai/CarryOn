/* One invitation subscription. Reconnects read state; never replay approvals or claims. */
class ConfirmationStream {
 constructor({base,kind,invitation,onState,onError,onConnection=()=>{}}){
  Object.assign(this,{base,kind,invitation,onState,onError,onConnection});this.closed=false;this.delay=500;this.connect();
 }
 close(){this.closed=true;clearTimeout(this.retry);clearTimeout(this.heartbeat);const socket=this.socket;this.socket=null;socket?.close();}
 connect(){
  if(this.closed||this.socket)return;
  const url=new URL('console/confirmation/ws',this.base);url.protocol=url.protocol==='https:'?'wss:':'ws:';
  const socket=new WebSocket(url);this.socket=socket;const current=()=>!this.closed&&this.socket===socket;
  let pending=null,running=false;
  const drain=async()=>{if(running)return;running=true;try{while(pending&&current()){const state=pending;pending=null;await this.onState(state);}}catch(error){if(current()){this.onError(error);socket.close();}}finally{running=false;}};
  const heartbeat=()=>{clearTimeout(this.heartbeat);this.heartbeat=setTimeout(()=>{if(current())socket.close();},45000);};heartbeat();
  socket.onopen=()=>{if(current())socket.send(JSON.stringify({type:'subscribe',kind:this.kind,invitation:this.invitation}));};
  socket.onmessage=event=>{
   if(!current())return;heartbeat();
   try{const packet=JSON.parse(event.data);
    if(packet.type==='ping'){socket.send(JSON.stringify({type:'pong'}));return;}
    if(packet.type==='error'){this.close();this.onError(Error(packet.error||'确认订阅失效'));return;}
    if(packet.type==='confirmation'&&packet.body&&typeof packet.body.state==='string'){this.delay=500;this.onConnection(true);pending=packet.body;drain();}
   }catch(error){if(current()){this.onError(error);socket.close();}}
  };
  socket.onclose=()=>{if(!current())return;clearTimeout(this.heartbeat);this.socket=null;this.onConnection(false);this.retry=setTimeout(()=>this.connect(),this.delay);this.delay=Math.min(10000,this.delay*2);};
  socket.onerror=()=>{};
 }
}
