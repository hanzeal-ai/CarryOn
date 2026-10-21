'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');

test('upload IDs are snapshotted and participate in compose and creation request identity',async()=>{
  const f=fixture();f.respond(async()=>{throw Error('lost');});
  for(const create of [false,true]){
    const send=ids=>create?f.client.createInProject('project','',()=>true,[],null,[],[],ids):f.client.submit('compose','thread','',[],()=>true,[],[],[],ids);
    const ids=['original'],first=send(ids);ids[0]='changed';
    await assert.rejects(first,/lost/);assert.deepEqual(f.requests.at(-1).body.uploads,['original']);
    const id=f.requests.at(-1).body.requestId;
    await assert.rejects(send(['original']),/lost/);assert.equal(f.requests.at(-1).body.requestId,id);
    await assert.rejects(send(['different']),/lost/);assert.notEqual(f.requests.at(-1).body.requestId,id);
  }
});

test('section move retains original content through reload and never replays an unknown write',async()=>{
 const first=fixture();first.respond(async()=>{throw Error('lost');});
 await assert.rejects(first.client.moveThreadSection('thread','pinned'),/lost/);
 const id=first.client.operations.get('section-move:thread'),restored=fixture(first.storage);
 for(const state of ['failed','completed']){
  restored.respond(async()=>({ok:true,json:async()=>({id,threadId:'thread',kind:'section-move',sectionId:null,state,result:{threadId:'thread',sectionId:'pinned'}})}));
  await assert.rejects(restored.client.queryThreadSection('thread',id),/内容身份/);assert.equal(restored.client.operations.get('section-move:thread'),id);
 }
 await assert.rejects(restored.client.moveThreadSection('thread',null),/核对/);
 restored.respond(async()=>({ok:true,json:async()=>({id,threadId:'thread',kind:'section-move',sectionId:'pinned',state:'completed',result:{threadId:'thread',sectionId:'pinned'}})}));
 assert.equal((await restored.client.queryThreadSection('thread',id)).state,'completed');assert(!restored.client.operations.has('section-move:thread'));
 assert.equal(restored.requests.filter(request=>request.body?.requestId).length,0);
});

test('section move checks destination even in failure receipts and validates null removal',async()=>{
 const f=fixture();f.respond(async()=>({ok:true,json:async()=>({id:f.requests.at(-1).body.requestId,threadId:'thread',kind:'section-move',sectionId:'wrong',state:'failed'})}));
 assert.equal((await f.client.moveThreadSection('thread',null)).state,'uncertain');assert(f.client.operations.has('section-move:thread'));
 const g=fixture();g.respond(async()=>({ok:true,json:async()=>({id:g.requests.at(-1).body.requestId,threadId:'thread',kind:'section-move',sectionId:null,state:'completed',result:{threadId:'thread',sectionId:null}})}));
 assert.equal((await g.client.moveThreadSection('thread',null)).state,'completed');assert(!g.client.operations.has('section-move:thread'));
});

test('rename retains mismatched failure receipts and queries without replay',async()=>{
 for(const mismatch of ['id','threadId','kind','name']){
  const f=fixture();f.respond(async()=>({ok:true,json:async()=>({id:f.requests.at(-1).body.requestId,threadId:'thread',kind:'rename',name:'名称',state:'failed',[mismatch]:'wrong'})}));
  assert.equal((await f.client.renameThread('thread','名称')).state,'uncertain');
  const id=f.client.operations.get('rename:thread');assert(id);
  await assert.rejects(f.client.renameThread('thread','其他名称'),/核对/);
  f.respond(async()=>({ok:true,json:async()=>({id,threadId:'thread',kind:'rename',name:'名称',state:'completed',result:{threadId:'thread',name:'名称'}})}));
  assert.equal((await f.client.queryRename('thread',id)).state,'completed');assert(!f.client.operations.has('rename:thread'));
  assert.equal(f.requests.filter(request=>request.body?.requestId).length,1);
 }
});

test('rename success requires exact canonical name and result thread',async()=>{
 for(const result of [{threadId:'other',name:'名称'},{threadId:'thread',name:'old'}]){
  const f=fixture();f.respond(async()=>({ok:true,json:async()=>({id:f.requests.at(-1).body.requestId,threadId:'thread',kind:'rename',name:'名称',state:'completed',result})}));
  assert.equal((await f.client.renameThread('thread','名称')).state,'uncertain');assert(f.client.operations.has('rename:thread'));
 }
});

test('rename query content identity survives reload and rejects mismatched names in every state',async()=>{
 const first=fixture();first.respond(async()=>{throw Error('lost');});
 await assert.rejects(first.client.renameThread('thread','名称 🧭'),/lost/);
 const id=first.client.operations.get('rename:thread'),restored=fixture(first.storage);
 for(const state of ['failed','completed']){
  restored.respond(async()=>({ok:true,json:async()=>({id,threadId:'thread',kind:'rename',name:'other',state,result:{threadId:'thread',name:'名称 🧭'}})}));
  await assert.rejects(restored.client.queryRename('thread',id),/内容身份/);assert.equal(restored.client.operations.get('rename:thread'),id);
 }
 assert.equal(restored.requests.filter(request=>request.body?.requestId).length,0);
});

test('skills snapshot contributes to the durable submission identity', async()=>{
  const f=fixture();f.respond(async()=>{throw Error('lost');});
  const skills=[{name:'fixture',path:'/repo/SKILL.md'}];
  const first=f.client.submit('compose','thread','',[],()=>true,skills);
  skills[0].name='changed';
  await assert.rejects(first,/lost/);
  assert.equal(f.requests[0].body.skills[0].name,'fixture');
  const id=f.requests[0].body.requestId;
  await assert.rejects(f.client.submit('compose','thread','',[],()=>true,[{name:'fixture',path:'/repo/SKILL.md'}]),/lost/);
  assert.equal(f.requests[1].body.requestId,id);
  await assert.rejects(f.client.submit('compose','thread','',[],()=>true,skills),/lost/);
  assert.notEqual(f.requests[2].body.requestId,id);
});

test('mentions snapshot contributes to the durable submission identity', async()=>{
  const f=fixture();f.respond(async()=>{throw Error('lost');});
  const skills=[{name:'fixture',path:'app://fixture'}];
  const first=f.client.submit('compose','thread','',[],()=>true,[],skills);
  skills[0].name='changed';
  await assert.rejects(first,/lost/);
  assert.equal(f.requests[0].body.mentions[0].name,'fixture');
  const id=f.requests[0].body.requestId;
  await assert.rejects(f.client.submit('compose','thread','',[],()=>true,[],[{name:'fixture',path:'app://fixture'}]),/lost/);
  assert.equal(f.requests[1].body.requestId,id);
  await assert.rejects(f.client.submit('compose','thread','',[],()=>true,[],skills),/lost/);
  assert.notEqual(f.requests[2].body.requestId,id);
});

test('fork unconfirmed receipts retain identity across reload until the child is confirmed', async()=>{
  for(const receipt of [{state:'inProgress'},{state:'accepted'},{state:'completed'}]){
    const f=fixture();f.respond(async()=>({ok:true,json:async()=>receipt}));
    assert.equal((await f.client.fork('source','turn')).state,'uncertain');
    const original=f.requests[0].body.requestId;
    const restored=fixture(f.storage);
    restored.respond(async()=>({ok:true,json:async()=>({state:'completed',createdThreadId:'22222222-2222-4222-8222-222222222222'})}));
    await restored.client.fork('source','turn');
    assert.equal(restored.requests[0].body.requestId,original);
    assert.equal(restored.requests[0].body.lastTurnId,'turn');
    await restored.client.fork('source','turn');
    assert.notEqual(restored.requests[1].body.requestId,original);
  }
});

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

test('uncertain HTTP conflict retains identity across reload and success reconciles it', async()=>{
  const f=fixture();
  f.respond(async()=>({ok:false,status:409,json:async()=>({error:'unknown outcome',uncertain:true})}));
  await assert.rejects(f.client.submit('compose','thread','hello'),e=>e.uncertain===true);
  const original=f.requests[0].body.requestId;
  const restored=fixture(f.storage);
  await restored.client.submit('compose','thread','hello');
  assert.equal(restored.requests[0].body.requestId,original);
  await restored.client.submit('compose','thread','hello');
  assert.notEqual(restored.requests[1].body.requestId,original);
});

test('definite conflict releases identity while malformed 409 retains it', async()=>{
  const f=fixture();
  f.respond(async()=>({ok:false,status:409,json:async()=>({error:'rejected'})}));
  await assert.rejects(f.client.submit('message','thread','hello'));
  const rejected=f.requests[0].body.requestId;
  f.respond(async()=>({ok:false,status:409,json:async()=>{throw new SyntaxError('invalid JSON')}}));
  await assert.rejects(f.client.submit('message','thread','hello'));
  const uncertain=f.requests[1].body.requestId;
  assert.notEqual(uncertain,rejected);
  await assert.rejects(f.client.submit('message','thread','hello'));
  assert.equal(f.requests[2].body.requestId,uncertain);
});

test('non-object HTTP409 responses retain the original request identity', async()=>{
  const f=fixture();
  for(const body of [[], 'invalid shape', false, null]){
    f.respond(async()=>({ok:false,status:409,json:async()=>body}));
    await assert.rejects(f.client.submit('message','thread','hello'),e=>e.uncertain===true);
  }
  assert.equal(new Set(f.requests.map(r=>r.body.requestId)).size,1);
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


test('proxy rejections release the ID while gateway failures retain it', async()=>{
  const f=fixture();
  f.respond(async()=>({ok:false,status:413,json:async()=>{throw new SyntaxError('The string did not match the expected pattern.')}}));
  await assert.rejects(f.client.submit('message','thread','hello'),/图片请求超过服务器大小限制/);
  const id=f.requests.at(-1).body.requestId;
  f.respond(async()=>({ok:false,status:502,json:async()=>{throw new SyntaxError('invalid JSON')}}));
  await assert.rejects(f.client.submit('message','thread','hello'),/HTTP 502/);
  assert.notEqual(f.requests.at(-1).body.requestId,id);
  const ambiguous=f.requests.at(-1).body.requestId;
  await assert.rejects(f.client.submit('message','thread','hello'),/HTTP 502/);
  assert.equal(f.requests.at(-1).body.requestId,ambiguous);
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
 assert.equal(confirmed,null);
 assert.equal(context.merge(confirmed,{id:'r',state:'preparing'}),null);
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

test('project creation images participate in retry identity without persisting bytes',async()=>{
 const f=fixture();f.respond(async()=>({ok:true,json:async()=>({state:'uncertain'})}));
 await f.client.createInProject('project-a','',()=>true,['image-one']);
 await f.client.createInProject('project-a','',()=>true,['image-one']);
 await f.client.createInProject('project-a','',()=>true,['image-two']);
 assert.equal(f.requests[0].body.requestId,f.requests[1].body.requestId);
 assert.notEqual(f.requests[1].body.requestId,f.requests[2].body.requestId);
 assert.equal(f.requests[0].body.images[0],'image-one');
 assert(![...f.storage.values()].some(value=>value.includes('image-one')));
});

 test('creation snapshots settings and images before asynchronous hashing',async()=>{
 const f=fixture();f.respond(async()=>({ok:true,json:async()=>({state:'completed'})}));
 const settings={model:'test-model',effort:'high'},images=['first-image'],skills=[{name:'skill',path:'/skill'}],mentions=[{name:'App',path:'app://original'}];
 const pending=f.client.createInProject('project','task',()=>true,images,settings,skills,mentions);
 settings.effort='low';images[0]='changed-image';skills[0].path='/changed';mentions[0].path='app://changed';
 await pending;
 assert.equal(f.requests[0].body.settings.effort,'high');
 assert.deepEqual(f.requests[0].body.images,['first-image']);
 assert.deepEqual(f.requests[0].body.skills,[{name:'skill',path:'/skill'}]);assert.deepEqual(f.requests[0].body.mentions,[{name:'App',path:'app://original'}]);
});


test('review start must be completed before releasing the retry identity',async()=>{
 const f=fixture();const target={type:'baseBranch',branch:'main'};
 for(const state of ['accepted','inProgress']){
  f.respond(async()=>({ok:true,json:async()=>({state})}));
  assert.equal((await f.client.operation('thread','review',{target})).state,'uncertain');
 }
 assert.equal(f.requests[0].body.requestId,f.requests[1].body.requestId);
 f.respond(async()=>({ok:true,json:async()=>({state:'completed',reviewThreadId:'thread',turnId:'review-turn'})}));
 await f.client.operation('thread','review',{target});assert.equal(f.requests[2].body.requestId,f.requests[0].body.requestId);
 await f.client.operation('thread','review',{target});assert.notEqual(f.requests[3].body.requestId,f.requests[0].body.requestId);
});

test('goal mutations retain identity until a matching native result is confirmed',async()=>{
 for(const action of ['goal-set','goal-pause','goal-clear']){
  const f=fixture(),fields=action==='goal-set'?{objective:'finish fixture',status:'active'}:{};
  for(const result of [{state:'accepted'},{state:'completed',result:{goal:{threadId:'other',status:'paused'},cleared:false}}]){
   f.respond(async()=>({ok:true,json:async()=>result}));
   assert.equal((await f.client.operation('thread',action,fields)).state,'uncertain');
  }
  assert.equal(f.requests[0].body.requestId,f.requests[1].body.requestId);
  f.respond(async()=>({ok:true,json:async()=>({state:'completed',result:action==='goal-clear'?{cleared:true}:{goal:{threadId:'thread',status:'paused'}}})}));
  assert.equal((await f.client.operation('thread',action,fields)).state,'completed');
  assert.equal(f.requests[2].body.requestId,f.requests[0].body.requestId);
  await f.client.operation('thread',action,fields);assert.notEqual(f.requests[3].body.requestId,f.requests[0].body.requestId);
 }
});

test('side lifecycle preserves retry identity until parent and child are confirmed',async()=>{
 const f=fixture();
 for(const result of [{state:'accepted'},{state:'completed',parentId:'other',createdThreadId:'child'}]){
  f.respond(async()=>({ok:true,json:async()=>result}));
  assert.equal((await f.client.createSide('parent')).state,'uncertain');
 }
 assert.equal(f.requests[0].body.requestId,f.requests[1].body.requestId);
 f.respond(async()=>({ok:true,json:async()=>({state:'completed',parentId:'parent',createdThreadId:'child'})}));
 assert.equal((await f.client.createSide('parent')).state,'completed');
 assert.equal(f.requests[2].body.requestId,f.requests[0].body.requestId);
 f.respond(async()=>({ok:true,json:async()=>({state:'completed',result:{closed:true,threadId:'wrong'}})}));
 assert.equal((await f.client.closeSide('parent','child')).state,'uncertain');
 f.respond(async()=>({ok:true,json:async()=>({state:'completed',result:{closed:true,threadId:'child'}})}));
 assert.equal((await f.client.closeSide('parent','child')).state,'completed');
 assert.equal(f.requests[3].body.requestId,f.requests[4].body.requestId);
 await assert.rejects(f.client.createSide('parent',()=>false));
});


test('creation completion without native identity is uncertain and keeps retry ID',async()=>{
 const f=fixture();f.respond(async()=>({ok:true,json:async()=>({state:'completed'})}));
 assert.equal((await f.client.createInProject('project','task')).state,'uncertain');
 await f.client.createInProject('project','task');assert.equal(f.requests[0].body.requestId,f.requests[1].body.requestId);
 f.respond(async()=>({ok:true,json:async()=>({state:'completed',createdThreadId:'native-created'})}));
 assert.equal((await f.client.createInProject('project','task')).createdThreadId,'native-created');assert.equal(f.requests[2].body.requestId,f.requests[0].body.requestId);
 await f.client.createInProject('project','task');assert.notEqual(f.requests[3].body.requestId,f.requests[0].body.requestId);
});

test('archive receipt identity remains pending until exact state is confirmed',async()=>{
 const f=fixture();f.respond(async()=>({ok:true,json:async()=>({id:f.requests.at(-1).body.requestId,threadId:'thread',state:'completed',result:{threadId:'other',archived:true}})}));
 const wrong=await f.client.archiveThread('thread',false);assert.equal(wrong.state,'uncertain');
 const id=f.client.operations.get('archive:thread');assert.equal(id,wrong.id);
 f.respond(async()=>({ok:true,json:async()=>({id,threadId:'thread',state:'completed',result:{threadId:'thread',archived:true}})}));
 const queried=await f.client.queryArchive('thread',false,id);assert.equal(queried.state,'completed');assert(!f.client.operations.has('archive:thread'));
 assert.equal(f.requests.filter(request=>request.path.endsWith('/archive')).length,1,'explicit query never replays the mutation');
});

test('archive failure receipts cannot release another request identity',async()=>{
 for(const restoring of [false,true])for(const state of ['failed','interrupted','acknowledged'])for(const mismatch of ['id','threadId']){
  const f=fixture();f.respond(async()=>({ok:true,json:async()=>({id:mismatch==='id'?'wrong':f.requests.at(-1).body.requestId,threadId:mismatch==='threadId'?'other':'thread',state})}));
  assert.equal((await f.client.archiveThread('thread',restoring)).state,'uncertain');
  const key=(restoring?'unarchive':'archive')+':thread',id=f.client.operations.get(key);assert(id);
  f.respond(async()=>({ok:true,json:async()=>({id,threadId:'thread',state:'failed'})}));
  assert.equal((await f.client.queryArchive('thread',restoring,id)).state,'failed');assert(!f.client.operations.has(key));
  assert.equal(f.requests.filter(request=>request.body?.requestId).length,1);
 }
});

test('section lifecycle original body survives reload and mismatched terminal receipts never release it',async()=>{
 const first=fixture();first.respond(async()=>{throw Error('lost');});
 await assert.rejects(first.client.manageSection(null,{name:'研发'}),/lost/);
 const id=first.client.operations.get('section-management'),restored=fixture(first.storage);
 for(const state of ['failed','completed']){
  restored.respond(async()=>({ok:true,json:async()=>({id,threadId:'sections',kind:'section-create',sectionId:null,body:{name:'错误'},state,result:{section:{id:'g',name:'研发'}}})}));
  await assert.rejects(restored.client.querySectionManagement(id),/身份不匹配/);assert.equal(restored.client.operations.get('section-management'),id);
 }
 await assert.rejects(restored.client.manageSection(null,{name:'研发'}),/核对/);
 restored.respond(async()=>({ok:true,json:async()=>({id,threadId:'sections',kind:'section-create',sectionId:null,body:{name:'研发'},state:'completed',result:{section:{id:'g',name:'研发'}}})}));
 assert.equal((await restored.client.querySectionManagement(id)).state,'completed');assert(!restored.client.operations.has('section-management'));
 assert.equal(restored.requests.filter(request=>request.body?.requestId).length,0);
});

test('section deletion needs explicit canonical absence and exact original section',async()=>{
 for(const result of [{sectionId:'other',deleted:true},{sectionId:'g',deleted:false},{}]){
  const f=fixture();f.respond(async()=>({ok:true,json:async()=>({id:f.requests.at(-1).body.requestId,threadId:'g',kind:'section-delete',sectionId:'g',body:{action:'delete'},state:'completed',result})}));
  assert.equal((await f.client.manageSection('g',{action:'delete'})).state,'uncertain');assert(f.client.operations.has('section-management'));
 }
});

test('concurrent section creation preserves first body identity and sends only one POST',async()=>{
 const f=fixture();f.respond(async()=>{throw Error('lost');});
 const outcomes=await Promise.allSettled([f.client.manageSection(null,{name:'first'}),f.client.manageSection(null,{name:'second'})]);
 assert.equal(outcomes.filter(result=>result.status==='rejected').length,2);
 assert.equal(f.requests.filter(request=>request.body?.requestId).length,1);
 assert.equal(f.client.operations.get('section-management-content'),await f.client.requestContent('/sections',{name:f.requests[0].body.name}));
 assert(f.client.operations.has('section-management'));
});

test('section ordering preserves original body and requires exact adjacent position',async()=>{
 const f=fixture(),body={action:'order',threadId:'thread',beforeThreadId:null};f.respond(async()=>{throw Error('lost');});
 const write=f.client.manageSection('group',body);body.beforeThreadId='mutated';await assert.rejects(write,/lost/);
 assert.equal(f.requests[0].body.beforeThreadId,null);
 const id=f.client.operations.get('section-management');
 for(const result of [{threadId:'thread',sectionId:'group'},{threadId:'thread',sectionId:'group',beforeThreadId:'wrong'}]){
  f.respond(async()=>({ok:true,json:async()=>({id,kind:'section-order',threadId:'thread',sectionId:'group',body:{action:'order',threadId:'thread',beforeThreadId:null},state:'completed',result})}));
  await assert.rejects(f.client.querySectionManagement(id),/身份不匹配/);assert(f.client.operations.has('section-management'));
 }
 f.respond(async()=>({ok:true,json:async()=>({id,kind:'section-order',threadId:'thread',sectionId:'group',body:{action:'order',threadId:'thread',beforeThreadId:null},state:'completed',result:{threadId:'thread',sectionId:'group',beforeThreadId:null}})}));
 assert.equal((await f.client.querySectionManagement(id)).state,'completed');assert(!f.client.operations.has('section-management'));
});

test('terminal stop requires exact body and canonical native process absence through reload',async()=>{
 const f=fixture(),body={action:'terminate',processId:'native-pid'};
 f.respond(async()=>{throw Error('lost reply');});await assert.rejects(f.client.stopTerminal('thread',body),/lost/);
 const id=f.client.operations.get('terminal:thread'),g=fixture(f.storage);
 for(const state of ['failed','completed']){
  g.respond(async()=>({ok:true,json:async()=>({id,threadId:'thread',kind:'terminal-terminate',body:{...body,processId:'wrong'},state,result:{threadId:'thread',processId:'native-pid',terminated:true}})}));
  await assert.rejects(g.client.queryTerminal('thread',id),/内容身份/);assert.equal(g.client.operations.get('terminal:thread'),id);
 }
 await assert.rejects(g.client.stopTerminal('thread',{action:'clean'}),/核对/);
 g.respond(async()=>({ok:true,json:async()=>({id,threadId:'thread',kind:'terminal-terminate',body,state:'completed',result:{threadId:'thread',processId:'wrong',terminated:true}})}));
 await assert.rejects(g.client.queryTerminal('thread',id),/内容身份/);
 g.respond(async()=>({ok:true,json:async()=>({id,threadId:'thread',kind:'terminal-terminate',body,state:'completed',result:{threadId:'thread',processId:'native-pid',terminated:true}})}));
 assert.equal((await g.client.queryTerminal('thread',id)).state,'completed');assert(!g.client.operations.has('terminal:thread'));
 assert.equal(g.requests.filter(r=>r.body?.requestId).length,0);
});
test('terminal body capture and simultaneous writes admit only one native stop',async()=>{
 const f=fixture(),body={action:'terminate',processId:'first'};
 f.respond(async()=>{const r=f.requests.at(-1).body;return {ok:true,json:async()=>({id:r.requestId,threadId:'thread',kind:'terminal-terminate',body:{action:r.action,processId:r.processId},state:'uncertain'})};});
 const first=f.client.stopTerminal('thread',body);body.processId='mutated';
 const outcomes=await Promise.allSettled([first,f.client.stopTerminal('thread',{action:'clean'})]);
 assert.equal(outcomes.filter(r=>r.status==='fulfilled').length,1);assert.equal(f.requests.length,1);assert.equal(f.requests[0].body.processId,'first');
});
test('wrong failed terminal receipt cannot clear initial write',async()=>{
 const f=fixture();f.respond(async()=>({ok:true,json:async()=>({id:f.requests.at(-1).body.requestId,threadId:'thread',kind:'terminal-clean',body:{action:'terminate',processId:'wrong'},state:'failed'})}));
 assert.equal((await f.client.stopTerminal('thread',{action:'clean'})).state,'uncertain');assert(f.client.operations.has('terminal:thread'));
});

test('skill configuration retains exact path and enabled state across reload without replay',async()=>{
 const f=fixture(),body={path:'/skills/fixture/SKILL.md',enabled:false};f.respond(async()=>{throw Error('lost config reply');});
 await assert.rejects(f.client.configureSkill('thread',body),/lost/);const id=f.client.operations.get('skill-config'),g=fixture(f.storage);
 for(const state of ['failed','completed']){g.respond(async()=>({ok:true,json:async()=>({id,threadId:'thread',kind:'skill-config',body:{...body,enabled:true},state,result:{threadId:'thread',...body}})}));await assert.rejects(g.client.querySkillConfiguration(id),/内容身份/);assert.equal(g.client.operations.get('skill-config'),id);}
 await assert.rejects(g.client.configureSkill('other',{path:'/skills/other/SKILL.md',enabled:true}),/核对/);
 g.respond(async()=>({ok:true,json:async()=>({id,threadId:'thread',kind:'skill-config',body,state:'completed',result:{threadId:'thread',...body}})}));
 assert.equal((await g.client.querySkillConfiguration(id)).state,'completed');assert(!g.client.operations.has('skill-config'));assert.equal(g.requests.filter(r=>r.body?.requestId).length,0);
});
test('skill configuration captures original toggle and admits only one concurrent write',async()=>{
 const f=fixture(),body={path:'/skills/fixture/SKILL.md',enabled:false};f.respond(async()=>{const r=f.requests.at(-1).body;return {ok:true,json:async()=>({id:r.requestId,threadId:'thread',kind:'skill-config',body:{path:r.path,enabled:r.enabled},state:'uncertain'})};});
 const first=f.client.configureSkill('thread',body);body.enabled=true;
 const outcomes=await Promise.allSettled([first,f.client.configureSkill('thread',{path:'/skills/other/SKILL.md',enabled:true})]);
 assert.equal(outcomes.filter(r=>r.status==='fulfilled').length,1);assert.equal(f.requests.length,1);assert.equal(f.requests[0].body.enabled,false);
});

test('plugin management recovers exact installation without replay or clearing wrong receipts',async()=>{
 const f=fixture(),body={action:'install',pluginId:'fixture@market'};f.respond(async()=>{throw Error('lost install reply');});
 await assert.rejects(f.client.managePlugin('thread',body),/lost/);const id=f.client.operations.get('plugin-management'),g=fixture(f.storage);
 await assert.rejects(g.client.configureSkill('thread',{path:'/skills/fixture/SKILL.md',enabled:false}),/核对/);
 for(const state of ['failed','completed']){g.respond(async()=>({ok:true,json:async()=>({id,threadId:'thread',kind:'plugin-install',body:{...body,pluginId:'wrong'},state,result:{threadId:'thread',pluginId:body.pluginId,installed:true,appsNeedingAuth:null}})}));await assert.rejects(g.client.queryPluginManagement(id),/内容身份/);assert.equal(g.client.operations.get('plugin-management'),id);}
 g.respond(async()=>({ok:true,json:async()=>({id,threadId:'thread',kind:'plugin-install',body,state:'completed',result:{threadId:'thread',pluginId:body.pluginId,installed:true,appsNeedingAuth:null}})}));
 const job=await g.client.queryPluginManagement(id);assert.equal(job.result.appsNeedingAuth,null);assert(!g.client.operations.has('plugin-management'));assert.equal(g.requests.filter(r=>r.body?.requestId).length,0);
});
test('plugin and skill configuration share client admission guards with immutable bodies',async()=>{
 const f=fixture(),body={action:'install',pluginId:'fixture@market'};f.respond(async()=>{const r=f.requests.at(-1).body;return {ok:true,json:async()=>({id:r.requestId,threadId:'thread',kind:'plugin-'+r.action,body:{action:r.action,pluginId:r.pluginId},state:'uncertain'})};});
 const first=f.client.managePlugin('thread',body);body.pluginId='mutated';const outcomes=await Promise.allSettled([first,f.client.configureSkill('thread',{path:'/skill',enabled:false})]);assert.equal(outcomes.filter(r=>r.status==='fulfilled').length,1);assert.equal(f.requests.length,1);assert.equal(f.requests[0].body.pluginId,'fixture@market');
});
test('plugin discovery keeps search scope and opaque page identity through recovery',async()=>{
 const f=fixture(),body={action:'install',pluginId:'remote@market',discovery:{searchTerm:'fixture',scope:'global',cursor:'opaque/+='}},original=structuredClone(body);
 f.respond(async()=>{throw Error('lost discovery reply');});const write=f.client.managePlugin('thread',body);body.discovery.scope='personal';await assert.rejects(write,/lost/);assert.deepEqual(f.requests[0].body.discovery,original.discovery);
 const id=f.client.operations.get('plugin-management'),g=fixture(f.storage),job={id,threadId:'thread',kind:'plugin-install',body:original,state:'completed',result:{threadId:'thread',pluginId:original.pluginId,installed:true}};
 g.respond(async()=>({ok:true,json:async()=>({...job,body:{...original,discovery:{...original.discovery,cursor:null}}})}));await assert.rejects(g.client.queryPluginManagement(id),/内容身份/);assert.equal(g.client.operations.get('plugin-management'),id);
 g.respond(async()=>({ok:true,json:async()=>job}));await g.client.queryPluginManagement(id);assert(!g.client.operations.has('plugin-management'));assert.equal(g.requests.filter(r=>r.body?.requestId).length,0);
});


test('project files preserve search identity and original submission across reload',async()=>{
 const f=fixture();f.respond(async()=>{throw Error('lost');});
 const files=[{name:'source.swift',path:'/project/source.swift',query:'source'}];
 const sending=f.client.submit('compose','thread','',[],()=>true,[],[],files);files[0].query='changed';await assert.rejects(sending,/lost/);
 assert.equal(f.requests[0].body.files[0].query,'source');assert.equal(f.requests[0].body.prompt,'');assert.equal(f.requests[0].body.mentions,undefined);
 const id=f.requests[0].body.requestId,restored=fixture(f.storage);restored.respond(async()=>{throw Error('lost');});
 await assert.rejects(restored.client.submit('compose','thread','',[],()=>true,[],[],[{...files[0],query:'source'}]),/lost/);assert.equal(restored.requests[0].body.requestId,id);
 await assert.rejects(restored.client.submit('compose','thread','',[],()=>true,[],[],files),/lost/);assert.notEqual(restored.requests[1].body.requestId,id);
});


test('session controls query uncertain receipt without replay and reject foreign identity',async()=>{
 const f=fixture();let id;
 f.respond(async()=>{const request=f.requests.at(-1);id=request.body?.requestId||id;return {ok:true,json:async()=>({id,threadId:'thread',kind:'session:load',state:'uncertain'})};});
 assert.equal((await f.client.controlSession('thread','load')).state,'uncertain');
 assert.equal((await f.client.controlSession('thread','release')).state,'uncertain');
 assert.equal(f.requests.filter(r=>r.body).length,1);
 f.respond(async()=>({ok:true,json:async()=>({id,threadId:'foreign',kind:'session:load',state:'failed'})}));
 await assert.rejects(f.client.controlSession('thread','load'),/身份/);
 assert(f.client.operations.has('session:thread'));
 f.respond(async()=>({ok:true,json:async()=>({id,threadId:'thread',kind:'session:load',state:'completed',result:{threadId:'thread',state:'loaded'}})}));
 assert.equal((await f.client.controlSession('thread','load')).state,'completed');
 assert(!f.client.operations.has('session:thread'));
});
test('session controls retain wrong initial receipts and do not write after selection change',async()=>{
 const f=fixture();f.respond(async()=>({ok:true,json:async()=>({id:'foreign',threadId:'thread',kind:'session:release',state:'completed',result:{threadId:'thread',state:'released'}})}));
 assert.equal((await f.client.controlSession('thread','release')).state,'uncertain');assert(f.client.operations.has('session:thread'));
 await assert.rejects(f.client.controlSession('other','load',()=>false),/会话/);
 assert.equal(f.requests.filter(r=>r.body).length,1);
});

test('session controls keep incomplete admission and mismatched action results pending',async()=>{
 for(const [state,result] of [['accepted',null],['completed',{threadId:'thread',state:'released'}]]){
  const f=fixture();f.respond(async()=>({ok:true,json:async()=>({id:f.requests.at(-1).body.requestId,threadId:'thread',kind:'session:load',state,result})}));
  assert.equal((await f.client.controlSession('thread','load')).state,'uncertain');
  assert(f.client.operations.has('session:thread'));
 }
});
