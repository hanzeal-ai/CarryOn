'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');

function fixture(storage = new Map()) {
  const sockets = [], timers = new Map(), requests = [], updates = [], disconnects = [], auth = [];
  let response = async () => ({ok: true, json: async () => ({state: 'accepted'})});
  class Socket {
    static OPEN = 1;
    constructor(url) {this.url=String(url);this.sent=[];this.readyState=0;sockets.push(this);}
    send(data) {this.sent.push(JSON.parse(data));}
    open() {this.readyState=1;this.onopen();}
    close() {this.readyState=3;this.onclose?.({code:1000});}
  }
  const context=vm.createContext({URL, URLSearchParams, TextEncoder, Uint8Array, crypto:webcrypto,
    location:{hash:'#token=test-pairing-token',pathname:'/example.html',href:'http://localhost:8769/example.html',protocol:'http:'},
    history:{replaceState(){}},
    sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},
    WebSocket:Socket,setTimeout:fn=>{const id=Symbol();timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id),
    fetch:async(path,init)=>{requests.push({path,body:init.body&&JSON.parse(init.body),headers:init.headers});return response();},
    callbacks:{onUpdate:data=>updates.push(data),onDisconnect:event=>disconnects.push(event),
      onAuthError:()=>auth.push(true),onError:error=>{throw error;}}
  });
  vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../client.js'),'utf8')+
    '\nglobalThis.client = new CarryOnClient(callbacks);',context);
  return {client:context.client,sockets,timers,requests,updates,disconnects,auth,storage,
    respond:fn=>{response=fn;}};
}

test('network failure survives reload with the original request ID; success releases it', async()=>{
  const f=fixture();f.respond(async()=>{throw Error('network interrupted');});
  await assert.rejects(f.client.submit('message','thread','hello'),/interrupted/);
  const original=f.requests[0].body.requestId;
  const restored=fixture(f.storage);
  await restored.client.submit('message','thread','hello');
  assert.equal(restored.requests[0].body.requestId,original);
  await restored.client.submit('message','thread','hello');
  assert.notEqual(restored.requests[1].body.requestId,original);
});

test('side chat requests retain uncertain identity and isolate parent and target', async()=>{
  const f=fixture();f.respond(async()=>{throw Error('network interrupted');});
  await assert.rejects(f.client.sideAction('parent','child','compose',{prompt:'hello'}),/interrupted/);
  const original=f.requests[0].body.requestId;
  const restored=fixture(f.storage);
  await restored.client.sideAction('parent','child','compose',{prompt:'hello'});
  assert.equal(restored.requests[0].body.requestId,original);
  assert.equal(restored.requests[0].path,'/api/side-chats/child/compose');
  assert.equal(restored.requests[0].body.parentId,'parent');
  await restored.client.sideAction('other-parent','child','compose',{prompt:'hello'});
  assert.notEqual(restored.requests[1].body.requestId,original);
  await restored.client.sideAction('parent','other-child','interrupt',{expectedTurnId:'turn'});
  assert.equal(restored.requests[2].path,'/api/side-chats/other-child/operations');
  assert.equal(restored.requests[2].body.action,'interrupt');
});

test('side chat rejects a stale selection before a network write', async()=>{
  const f=fixture();
  await assert.rejects(f.client.sideAction('parent','child','compose',{prompt:'hello'},()=>false),/已改变/);
  assert.equal(f.requests.length,0);
});

test('reconnect authenticates and resubscribes; replaced sockets cannot change the page', async()=>{
  const f=fixture();const id=f.client.subscribe({threadId:'a',threadIds:['a']});
  const first=f.sockets[0];first.open();
  assert.equal(first.sent[0].type,'auth');assert.equal(first.sent[1].subscription,id);
  first.close();assert.equal(f.timers.size,1);
  const retry=[...f.timers.values()][0];retry();
  const second=f.sockets[1];second.open();
  assert.equal(second.sent[1].threadId,'a');
  await first.onmessage({data:JSON.stringify({type:'update',threadId:'obsolete'})});
  assert.equal(f.updates.length,0);
  await second.onmessage({data:JSON.stringify({type:'update',threadId:'a'})});
  assert.equal(f.updates.length,1);
  f.client.close();assert.equal(f.timers.size,0);
});

test('invalid authentication stops retry until pairing replaces the token',()=>{
  const f=fixture();f.client.connect();f.sockets[0].onclose({code:1008});
  assert.equal(f.auth.length,1);assert.equal(f.timers.size,0);
  f.client.pair('new-token');f.client.connect();f.sockets[1].open();
  assert.equal(f.sockets[1].sent[0].token,'new-token');
});

test('uncertain operations retain their ID and switching selection prevents delayed dispatch',async()=>{
  const f=fixture();f.respond(async()=>({ok:true,json:async()=>({state:'uncertain'})}));
  await f.client.operation('thread','compact',{});
  await f.client.operation('thread','compact',{});
  assert.equal(f.requests[0].body.requestId,f.requests[1].body.requestId);
  await assert.rejects(f.client.operation('other','compact',{},()=>false),/会话已改变/);
  assert.equal(f.requests.length,2);
});

test('an HTTP response from an old pairing is rejected',async()=>{
  const f=fixture();let finish;
  f.respond(()=>new Promise(resolve=>{finish=resolve;}));
  const result=f.client.request('/status');
  f.client.pair('replacement');finish({ok:true,json:async()=>({enabled:true})});
  await assert.rejects(result,/配对已改变/);
});

test('image retry identity includes image bytes without storing attachments in session storage',async()=>{
  const f=fixture(),image='data:image/jpeg;base64,/9j/2Q==';
  f.respond(async()=>{throw Error('offline')});
  await assert.rejects(f.client.submit('message','thread','look',[image]),/offline/);
  const first=f.requests.at(-1).body;
  await assert.rejects(f.client.submit('message','thread','look',[image]),/offline/);
  assert.equal(f.requests.at(-1).body.requestId,first.requestId);
  assert.deepEqual(Array.from(f.requests.at(-1).body.images),[image]);
  assert(!JSON.stringify([...f.storage]).includes(image));
  await assert.rejects(f.client.submit('message','thread','look',[image+'changed']),/offline/);
  assert.notEqual(f.requests.at(-1).body.requestId,first.requestId);
});

test('image hashing cannot submit after device or selected conversation changes',async()=>{
  const f=fixture();
  const pending=f.client.submit('message','thread','look',['data:image/jpeg;base64,/9j/2Q==']);
  f.client.epoch++;
  await assert.rejects(pending,/当前会话已改变/);assert.equal(f.requests.length,0);
  await assert.rejects(f.client.submit('message','thread','look',[],()=>false),/当前会话已改变/);assert.equal(f.requests.length,0);
});


test('proxy HTML failures are actionable and retain the retry ID', async()=>{
  const f=fixture();
  f.respond(async()=>({ok:false,status:413,json:async()=>{throw new SyntaxError('The string did not match the expected pattern.')}}));
  await assert.rejects(f.client.submit('message','thread','hello'),/图片请求超过服务器大小限制/);
  const id=f.requests.at(-1).body.requestId;
  f.respond(async()=>({ok:false,status:502,json:async()=>{throw new SyntaxError('invalid JSON')}}));
  await assert.rejects(f.client.submit('message','thread','hello'),/HTTP 502/);
  assert.equal(f.requests.at(-1).body.requestId,id);
});

test('compose announces pending message before HTTP completes and preserves retry identity',async()=>{
 const f=fixture(),events=[];f.client.onSubmission=e=>events.push(e);
 let release;f.respond(()=>new Promise(resolve=>release=resolve));
 const sending=f.client.submit('compose','thread','hello');
 assert.equal(events[0].state,'sending');assert.equal(events[0].prompt,'hello');
 release({ok:true,json:async()=>({id:events[0].id,state:'uncertain'})});await sending;
 const retry=f.client.submit('compose','thread','hello');
 assert.equal(events.at(-1).id,events[0].id);
 release({ok:true,json:async()=>({id:events[0].id,state:'completed'})});await retry;
 assert.equal(events.at(-1).threadId,'thread');assert.equal(events.at(-1).state,'completed');
});

test('live confirmation cannot be rolled back or recreated by delayed admission response',()=>{
 const context=vm.createContext({TextEncoder});
 vm.runInContext(fs.readFileSync('client.js','utf8')+'\nthis.merge=mergeOutgoingMessage;',context);
 const start={id:'r',prompt:'hello',state:'sending'};
 const confirmed=context.merge(start,{id:'r',state:'completed',clientMessageId:'native'},true);
 assert.equal(context.merge(confirmed,{id:'r',state:'preparing'}).state,'completed');
 assert.equal(context.merge(null,{id:'r',state:'preparing'}),null);
 assert.equal(context.merge(confirmed,{id:'r',state:'acknowledged'},true),null);
});

test('display cache honors recency, byte budget and oversized entries',()=>{
 const context=vm.createContext({TextEncoder});
 vm.runInContext(fs.readFileSync('client.js','utf8')+'\nthis.Cache=DisplayHistoryCache;',context);
 const cache=new context.Cache(2,100);
 cache.set('a',{text:'a'});cache.set('b',{text:'b'});cache.get('a');cache.set('c',{text:'c'});
 assert.equal(cache.get('b'),undefined);assert.equal(cache.get('a').text,'a');
 cache.set('huge',{text:'x'.repeat(101)});assert.equal(cache.get('huge'),undefined);
 assert(cache.bytes<=100);cache.clear();assert.equal(cache.bytes,0);
});

test('history deltas reconstruct ordered state and gaps reject before rendering',()=>{
  const context=vm.createContext({});
  vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../client.js'),'utf8')+'\nglobalThis.wire=new HistoryWire();',context);
  const base={type:'update',subscription:'a',threadId:'t',history:{historyRevision:'1',timeline:[{id:'a',text:'old'},{id:'b'}],obsolete:true}};
  context.wire.decode(base);
  const next=context.wire.decode({type:'update',subscription:'a',threadId:'t',historyDelta:{base:'1',fields:{historyRevision:'2'},remove:['obsolete'],start:0,delete:1,items:[{id:'a',text:'new'}]}});
  assert.equal(next.history.timeline[0].text,'new');assert.equal(next.history.timeline[1].id,'b');
  assert.throws(()=>context.wire.decode({subscription:'a',threadId:'t',historyDelta:{base:'wrong'}}),/版本缺口/);
  assert.throws(()=>context.wire.decode({subscription:'b',threadId:'t',historyDelta:{base:'2'}}),/版本缺口/);
});

test('display cache uses history revision before serializing a newly decoded object',()=>{
  const context=vm.createContext({TextEncoder});
  vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../client.js'),'utf8')+'\nglobalThis.cache=new DisplayHistoryCache();',context);
  const first={historyRevision:'one',timeline:[]};context.cache.set('t',first);
  context.cache.set('t',{historyRevision:'one',toJSON(){throw Error('unchanged revision must not be encoded');}});
  assert.equal(context.cache.get('t'),first);
});


test('short return probes the existing socket without resubscribing; lost probe reconnects',()=>{
 const f=fixture();const id=f.client.subscribe({threadId:'a',threadIds:['a']});const socket=f.sockets[0];socket.open();
 f.client.subscribe({threadId:'a',threadIds:['a']});f.client.resume();
 assert.equal(f.sockets.length,1);assert.equal(f.client.selection.subscription,id);
 assert.equal(socket.sent.filter(x=>x.type==='subscribe').length,1);assert.equal(socket.sent.at(-1).type,'ping');
 const timeout=[...f.timers.values()][0];timeout();assert.equal(f.disconnects.length,1);
 const retry=[...f.timers.values()][0];retry();assert.equal(f.sockets.length,2);
});
test('project creation uses server project identity and keeps uncertain retry identity',async()=>{
 const f=fixture();f.respond(async()=>({ok:true,json:async()=>({state:'uncertain'})}));
 await f.client.createInProject('project-a','task');await f.client.createInProject('project-a','task');
 assert.equal(f.requests[0].body.projectId,'project-a');assert.equal(f.requests[0].body.requestId,f.requests[1].body.requestId);
 await assert.rejects(f.client.createInProject('project-b','task',()=>false),/已改变/);
 assert.equal(f.requests.length,2);
});


test('local workspace identity isolates pending jobs and invalidates old HTTP responses',async()=>{
 const f=fixture();f.client.setWorkspaceSession('workspace-one');
 f.respond(async()=>{throw Error('offline');});await assert.rejects(f.client.submit('compose','same-thread','hello'),/offline/);
 const original=f.requests.at(-1).body.requestId;
 let finish;f.respond(()=>new Promise(r=>finish=r));const old=f.client.request('/status');
 f.client.setWorkspaceSession('workspace-two');finish({ok:true,json:async()=>({enabled:true})});await assert.rejects(old,/已改变/);
 f.respond(async()=>({ok:true,json:async()=>({state:'accepted'})}));await f.client.submit('compose','same-thread','hello');
 assert.notEqual(f.requests.at(-1).body.requestId,original);
 assert(f.storage.has('carryon-local:workspace-one:pending'));
});
