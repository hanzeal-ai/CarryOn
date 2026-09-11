const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const {webcrypto}=require('node:crypto');
function fixture(fetch){
 const storage=new Map(), errors=[];
 const ctx=vm.createContext({URL,URLSearchParams,TextEncoder,crypto:webcrypto,fetch,setTimeout,clearTimeout,
  location:{hash:'',pathname:'/connectnow/',href:'https://console.test/connectnow/'},history:{replaceState(){}},
  sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},
  document:{querySelector:()=>({src:'https://console.test/connectnow/cloud-console-client.js'}),getElementById:()=>({replaceChildren(){}})},Option:class{},
 });
 vm.runInContext(fs.readFileSync('client.js','utf8')+'\n'+fs.readFileSync('cloud-console-client.js','utf8')+'\nthis.Client=CloudConsoleClient;',ctx);
 return {client:new ctx.Client({onUpdate(){},onDisconnect(){},onAuthError:()=>errors.push('auth'),onError(){}}),storage,errors};
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
