'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function fixture(onState=()=>{}){
 const sockets=[],timers=new Map();let id=0;const errors=[];
 class Socket{constructor(url){this.url=String(url);this.sent=[];sockets.push(this);}send(data){this.sent.push(JSON.parse(data));}close(){this.onclose?.();}emit(packet){this.onmessage({data:JSON.stringify(packet)});}}
 const context=vm.createContext({URL,WebSocket:Socket,setTimeout:(fn,ms)=>{timers.set(++id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id)});
 vm.runInContext(fs.readFileSync('confirmation-stream.js','utf8')+';globalThis.Stream=ConfirmationStream;',context);
 const stream=new context.Stream({base:'https://example.test/',kind:'qr-claim',invitation:{id:'id',claim:'secret'},onState,onError:e=>errors.push(e)});
 return {stream,sockets,timers,errors};
}
test('confirmation reconnect sends same credential only in frame and receives fresh state',async()=>{
 const states=[],f=fixture(s=>states.push(s.state));let ws=f.sockets[0];ws.onopen();assert.equal(ws.url,'wss://example.test/console/confirmation/ws');assert.equal(ws.sent[0].invitation.claim,'secret');
 ws.emit({type:'confirmation',body:{state:'scanned'}});await Promise.resolve();ws.close();
 const retry=[...f.timers.values()].find(t=>t.ms===500);assert(retry);retry.fn();ws=f.sockets[1];ws.onopen();assert.equal(ws.sent[0].type,'subscribe');
 ws.emit({type:'confirmation',body:{state:'approved'}});await Promise.resolve();assert.deepEqual(states,['scanned','approved']);
 ws.emit({type:'error',error:'expired',terminal:true});assert(f.stream.closed);assert.equal(f.errors.length,1);
});
test('closing ignores stale snapshots and cleans all timers',()=>{
 const states=[],f=fixture(s=>states.push(s));f.stream.close();f.sockets[0].emit({type:'confirmation',body:{state:'approved'}});assert.equal(states.length,0);assert.equal(f.timers.size,0);
});
