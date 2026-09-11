const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('app.js','utf8');
const handler=source.slice(source.indexOf('async function removeConsoleDevice('),source.indexOf('async function refreshConnectionRequests(){'));
function fixture({removeError,refreshError,removed=true}={}){
 const messages=[],events=[],elements=new Map();
 const client={device:'mac',epoch:0,selection:{},removing:false,
  close(){events.push('close');},connect(){events.push('connect');},setStorage(){},
  async consoleRequest(){events.push('delete');if(removeError)throw Error(removeError);return {removed,notice:'设备凭证已撤销'};}};
 const context=vm.createContext({client,consoleDirectoryRefresh:null,confirm:()=>true,
  $:id=>{if(!elements.has(id))elements.set(id,{disabled:false,replaceChildren(){}});return elements.get(id);},
  applyStatus:()=>events.push('reset'),notice:message=>messages.push(message),
  refreshConsoleDeviceDirectory:async()=>{if(refreshError)throw Error(refreshError);client.device='other';}});
 vm.runInContext(handler,context);
 return {client,messages,events,run:(...args)=>context.removeConsoleDevice(...args)};
}
test('confirmed removal stops stream first and reports device removed',async()=>{
 const f=fixture();await f.run();assert.deepEqual(f.events,['close','delete','reset','connect']);
 assert.deepEqual(f.messages,['设备已移除']);assert.equal(f.client.device,'other');assert.equal(f.client.removing,false);
});
test('failed removal retains device and resumes connection without success feedback',async()=>{
 const f=fixture({removeError:'无法移除'});await f.run();assert.equal(f.client.device,'mac');
 assert.deepEqual(f.messages,['无法移除']);assert.deepEqual(f.events,['close','delete','connect']);
});
test('directory failure after confirmed removal retains success and clears removed device',async()=>{
 const f=fixture({refreshError:'网络错误'});await f.run();assert.equal(f.client.device,'');
 assert.deepEqual(f.messages,['设备已移除；设备列表刷新失败：网络错误']);
});
test('unconfirmed response does not claim removal',async()=>{
 const f=fixture({removed:false});await f.run();assert.equal(f.client.device,'mac');
 assert.deepEqual(f.messages,['未确认设备已移除，请刷新设备列表核对']);
});

test('removing another workspace keeps the current selection',async()=>{
 const f=fixture({refreshError:'网络错误'});await f.run('other',true);
 assert.equal(f.client.device,'mac');assert.equal(f.events.includes('reset'),false);
});
