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
    '\nglobalThis.client = new ConnectNowClient(callbacks);',context);
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
