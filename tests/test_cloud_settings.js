const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');

function fixture(){
  class Element{
    constructor(){this.children=[];this.checked=false;this.value='';}
    append(...children){this.children.push(...children);}
    replaceChildren(...children){this.children=children;}
  }
  const elements=new Map(),calls=[],bindings=[{id:'cloud-a',url:'wss://one.test/device',control:false,connected:true},{id:'cloud-b',url:'wss://two.test/device',control:true,connected:true}];
  const get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  const context=vm.createContext({document:{getElementById:get,createElement:()=>new Element(),createTextNode:text=>text},setTimeout,clearTimeout});
  vm.runInContext(fs.readFileSync('cloud-ui.js','utf8')+'\nthis.settings=CloudSettings;',context);
  const api=async(path,body)=>{if(body)calls.push({path,body:JSON.parse(JSON.stringify(body))});return {bindings};};
  context.settings.init(api,()=>{});
  return {get,calls,settings:context.settings};
}

test('permission and removal actions carry the selected binding identity',async()=>{
  const {get,calls,settings}=fixture();await settings.refresh();
  let rows=get('cloud-bindings').children;
  rows[0].children[1].children[0].checked=true;
  await rows[0].children[2].onclick();
  assert.deepEqual(calls[0],{path:'/cloud/control',body:{id:'cloud-a',control:true}});
  rows=get('cloud-bindings').children;
  await rows[1].children[3].onclick();
  assert.deepEqual(calls[1],{path:'/cloud',body:{id:'cloud-b',enabled:false}});
});
