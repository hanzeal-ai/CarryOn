const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('app.js','utf8');
const code=source.slice(source.indexOf('let connectionRequestsVersion=0;'),source.indexOf('async function init(){'));
test('late request snapshot cannot restore history cleared by a newer refresh',async()=>{
 const pending=[],elements=new Map();
 function element(){return {textContent:'',dataset:{},childNodes:[],append(...nodes){this.childNodes.push(...nodes);},replaceChildren(){this.childNodes=[];}};}
 const context=vm.createContext({cloudMode:true,client:{token:'session',consoleRequest:()=>new Promise(r=>pending.push(r))},
  $:id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id);},
  node:()=>element(),document:{createElement:()=>element()},Date,notice(){}});
 vm.runInContext(code,context);
 const old=context.refreshConnectionRequests(),fresh=context.refreshConnectionRequests();
 pending[1]({requests:[],history:[]});await fresh;
 const signature=elements.get('connection-requests').dataset.signature;
 pending[0]({requests:[],history:[{id:'old',name:'Cleared',result:'approved',created:1,resolvedAt:2}]});await old;
 assert.equal(elements.get('connection-requests').dataset.signature,signature);
});
test('late failed refresh is ignored after a newer refresh completes',async()=>{
 const pending=[],elements=new Map();
 function element(){return {textContent:'',dataset:{},childNodes:[],append(...nodes){this.childNodes.push(...nodes);},replaceChildren(){this.childNodes=[];}};}
 const context=vm.createContext({cloudMode:true,client:{token:'session',consoleRequest:()=>new Promise((resolve,reject)=>pending.push({resolve,reject}))},
  $:id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id);},node:()=>element(),document:{createElement:()=>element()},Date,notice(){}});
 vm.runInContext(code,context);
 const old=context.refreshConnectionRequests(),fresh=context.refreshConnectionRequests();
 pending[1].resolve({requests:[],history:[]});await fresh;
 pending[0].reject(Error('old network failure'));await assert.doesNotReject(old);
});
