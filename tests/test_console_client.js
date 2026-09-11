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
  location:{hash:'',pathname:'/connectnow/',href:'https://console.test/connectnow/'},history:{replaceState(){}},
  sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},
  document:{querySelector:()=>({src:'https://console.test/connectnow/cloud-console-client.js'}),getElementById:()=>({replaceChildren(){}})},Option:class{},
 });
 vm.runInContext(fs.readFileSync('client.js','utf8')+'\n'+fs.readFileSync('cloud-console-client.js','utf8')+'\nthis.Client=CloudConsoleClient;',ctx);
 return {client:new ctx.Client({onUpdate(){},onDisconnect(){},onAuthError:()=>errors.push('auth'),onError(){}}),storage,errors,sockets};
}
const ok=body=>({ok:true,status:200,json:async()=>body});
test('console uses prefix-scoped cookie requests, never browser device credentials',async()=>{
 const calls=[];const {client}=fixture(async(url,options)=>{calls.push([String(url),options]);return ok({enabled:true});});
 client.device='my-mac';client.token='session';
 await client.request('/status');
 assert.equal(calls[0][0],'https://console.test/connectnow/console/devices/my-mac/request');
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
 assert.equal(storage.has('connectnow-pending'),false);
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
 const socket=sockets[0];assert.equal(socket.url,'wss://console.test/connectnow/console/devices/my-mac/ws');
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
