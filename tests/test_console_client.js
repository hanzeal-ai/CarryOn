const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const {webcrypto}=require('node:crypto');
function fixture(fetch){
 const storage=new Map(), errors=[], sockets=[];
 class Socket {
  constructor(url){this.url=String(url);this.sent=[];sockets.push(this);}
  send(value){this.sent.push(JSON.parse(value));}
  close(){this.onclose?.({code:1000});}
  open(){this.onopen();}
  message(value){this.onmessage({data:JSON.stringify(value)});}
 }
 const ctx=vm.createContext({URL,URLSearchParams,TextEncoder,crypto:webcrypto,fetch,setTimeout,clearTimeout,WebSocket:Socket,
  location:{hash:'',pathname:'/carryon/',href:'https://console.test/carryon/'},history:{replaceState(){}},
  sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},
  document:{querySelector:()=>({src:'https://console.test/carryon/cloud-console-client.js'}),getElementById:()=>({replaceChildren(){}})},Option:class{},
 });
 vm.runInContext(fs.readFileSync('client.js','utf8')+'\n'+fs.readFileSync('cloud-console-client.js','utf8')+'\nthis.Client=CloudConsoleClient;',ctx);
 return {client:new ctx.Client({onUpdate(){},onDisconnect(){},onAuthError:()=>errors.push('auth'),onError(){}}),storage,errors,sockets};
}
const ok=body=>({ok:true,status:200,json:async()=>body});
test('console uses prefix-scoped cookie requests, never browser device credentials',async()=>{
 const calls=[];const {client}=fixture(async(url,options)=>{calls.push([String(url),options]);return ok({enabled:true});});
 client.device='my-mac';client.token='session';
 await client.request('/status');
 assert.equal(calls[0][0],'https://console.test/carryon/console/devices/my-mac/request');
 assert.equal(calls[0][1].credentials,'same-origin');
 assert.equal(calls[0][1].headers.Authorization,undefined);
 assert.equal(JSON.parse(calls[0][1].body).path,'/api/status');
});
test('pending requests remain scoped to their cloud device',async()=>{
 const {client,storage}=fixture(async()=>{throw Error('offline');});
 client.device='one';client.setStorage();await assert.rejects(client.submit('message','thread','prompt'));
 const first=[...client.pending.values()][0];
 client.device='two';client.setStorage();assert.equal(client.pending.size,0);
 await assert.rejects(client.submit('message','thread','prompt'));assert.notEqual([...client.pending.values()][0],first);
 client.device='one';client.setStorage();assert.equal([...client.pending.values()][0],first);
 assert.equal(storage.has('carryon-pending'),false);
});
test('old device responses are rejected after switching',async()=>{
 let release;const {client}=fixture(()=>new Promise(resolve=>release=resolve));client.device='one';
 const result=client.request('/status');client.epoch++;client.device='two';release(ok({enabled:true}));
 await assert.rejects(result,/设备已改变/);
});

test('device-list refresh preserves in-flight request maps for the same device',async()=>{
 const {client}=fixture(async()=>ok({devices:[{id:'one',name:'Laptop',online:true}]}));
 client.device='one';client.setStorage();
 const pending=client.pending,operations=client.operations;
 pending.set('test','request-before-refresh');
 await client.initialize();
 assert.equal(client.pending,pending);assert.equal(client.operations,operations);
 assert.equal(client.pending.get('test'),'request-before-refresh');
});

test('same subscription keeps the active stream and its response generation',()=>{
 const {client}=fixture(async()=>ok({}));client.device='one';
 let starts=0;client.connect=function(){if(!this.active){this.active=true;this.loop++;starts++;}};
 const selection={threadId:'thread',threadIds:['b','a'],includeSideChats:false};
 const id=client.subscribe(selection),generation=client.loop;
 assert.equal(client.subscribe({...selection,threadIds:['a','b','a']}),id);
 assert.equal(starts,1);assert.equal(client.loop,generation);
 assert.notEqual(client.subscribe({...selection,threadId:'other'}),id);
 assert.equal(starts,2);
});

test('device, pairing and side-chat changes still replace the stream',()=>{
 const {client}=fixture(async()=>ok({}));client.device='one';
 client.connect=function(){this.active=true;};
 const selection={threadId:'thread',threadIds:[]};
 const first=client.subscribe(selection);client.device='two';
 const second=client.subscribe(selection);assert.notEqual(second,first);
 client.epoch++;const third=client.subscribe(selection);assert.notEqual(third,second);
 const side=client.subscribe({...selection,includeSideChats:true,sideThreadId:'side'});assert.notEqual(side,third);
 client.close();assert.equal(client.subscribe({...selection,includeSideChats:true,sideThreadId:'side'}),side);
 assert.equal(client.active,true);
});

test('removal suppresses subscription reconnect until it finishes',()=>{
 const {client}=fixture(async()=>ok({}));
 client.device='one';client.token='session';client.removing=true;
 client.subscribe({threadId:'thread',threadIds:[]});
 assert.equal(client.active,false);
});


test('console WebSocket uses cookie scope, emits subscriptions and receives ordered updates',async()=>{
 const calls=[],updates=[];const {client,sockets}=fixture(async(url)=>{calls.push(String(url));return ok({});});
 client.token='session';client.device='my-mac';client.onUpdate=async(packet)=>updates.push(packet);
 const id=client.subscribe({threadId:'thread',threadIds:[]});
 const socket=sockets[0];assert.equal(socket.url,'wss://console.test/carryon/console/devices/my-mac/ws');
 socket.open();assert.equal(socket.sent[0].type,'subscribe');assert.equal(socket.sent[0].subscription,id);
 socket.message({type:'ping'});
 socket.message({type:'update',subscription:id,revision:1,body:{type:'update',threadId:'thread',history:{text:'first'}}});
 socket.message({type:'update',subscription:id,revision:1,body:{type:'update',history:{text:'duplicate'}}});
 socket.message({type:'update',subscription:'old',revision:2,body:{type:'update',history:{text:'wrong subscription'}}});
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(updates.length,1);assert.equal(updates[0].history.text,'first');assert.equal(socket.sent[1].type,'pong');
 assert.deepEqual(calls,[]);client.close();
});

test('changed selection ignores old WebSocket frames and session expiry stops reconnect',async()=>{
 const updates=[];const {client,sockets,errors}=fixture(async()=>ok({}));client.token='session';client.device='one';
 client.onUpdate=async packet=>updates.push(packet);
 const old=client.subscribe({threadId:'old',threadIds:[]});sockets[0].open();
 const current=client.subscribe({threadId:'new',threadIds:[]});sockets[1].open();
 sockets[0].message({type:'update',subscription:old,revision:1,body:{type:'update'}});
 sockets[1].message({type:'update',subscription:current,revision:1,body:{type:'update',threadId:'new'}});
 await new Promise(resolve=>setImmediate(resolve));assert.equal(updates.length,1);
 sockets[1].message({type:'error',status:401,error:'expired'});
 await new Promise(resolve=>setImmediate(resolve));assert.equal(client.token,'');assert.deepEqual(errors,['auth']);assert.equal(client.active,false);
});

test('heartbeat reply does not wait for slow update rendering',async()=>{
 const {client,sockets}=fixture(async()=>ok({}));client.device='one';client.token='session';
 let release;client.onUpdate=()=>new Promise(resolve=>release=resolve);
 client.subscribe({threadId:'t',threadIds:[]});const ws=sockets[0];ws.open();
 ws.message({type:'update',subscription:client.selection.subscription,revision:1,body:{type:'update'}});
 await new Promise(resolve=>setImmediate(resolve));
 ws.message({type:'ping'});
 assert.equal(ws.sent.at(-1).type,'pong');
 release();client.close();
});

test('advertised resubscribe reuses socket and drops previous subscription updates',async()=>{
 const updates=[];const {client,sockets}=fixture(async()=>ok({}));client.device='one';client.token='session';
 client.onUpdate=packet=>updates.push(packet);
 const first=client.subscribe({threadId:'a',threadIds:[]});const socket=sockets[0];socket.open();
 socket.readyState=1; // browser OPEN state; fixture's original tests omit readyState.
 const Socket=socket.constructor;Socket.OPEN=1;
 socket.message({type:'update',revision:1,subscription:first,resubscribe:true,body:{type:'update',threadId:'a'}});
 await new Promise(resolve=>setImmediate(resolve));
 const second=client.subscribe({threadId:'b',threadIds:[]});assert.equal(sockets.length,1);
 assert.equal(socket.sent.at(-1).subscription,second);
 socket.message({type:'update',revision:2,subscription:first,resubscribe:true,body:{type:'update',threadId:'old'}});
 socket.message({type:'update',revision:3,subscription:second,resubscribe:true,body:{type:'update',threadId:'b'}});
 await new Promise(resolve=>setImmediate(resolve));
 assert.deepEqual(updates.map(p=>p.threadId),['a','b']);client.close();
});

test('slow rendering keeps only the newest complete projection',async()=>{
 const updates=[];let release;const {client,sockets}=fixture(async()=>ok({}));client.device='one';client.token='session';
 client.onUpdate=async packet=>{updates.push(packet.marker);if(packet.marker===1)await new Promise(resolve=>release=resolve);};
 const id=client.subscribe({threadId:'a',threadIds:[]});const socket=sockets[0];socket.open();
 for(let i=1;i<=50;i++)socket.message({type:'update',revision:i,subscription:id,body:{type:'update',marker:i}});
 assert.deepEqual(updates,[1]);release();await new Promise(resolve=>setImmediate(resolve));
 assert.deepEqual(updates,[1,50]);client.close();
});


test('expanding the history window creates a new subscription on the same socket',async()=>{
 const {client,sockets}=fixture(async()=>ok({}));client.device='mac';client.token='session';
 const first=client.subscribe({threadId:'thread',historyLimit:40});const ws=sockets[0];ws.constructor.OPEN=1;ws.readyState=1;ws.open();
 ws.message({type:'update',subscription:first,revision:1,resubscribe:true,body:{type:'update'}});
 const next=client.subscribe({threadId:'thread',historyLimit:80});
 assert.notEqual(next,first);assert.equal(sockets.length,1);assert.equal(client.selection.historyLimit,80);
 const side=client.subscribe({threadId:'thread',historyLimit:80,sideHistoryLimit:120});
 assert.notEqual(side,next);assert.equal(client.selection.historyLimit,80);assert.equal(client.selection.sideHistoryLimit,120);
 client.close();
});
