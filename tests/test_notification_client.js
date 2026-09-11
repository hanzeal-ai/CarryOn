const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const ctx=vm.createContext({});vm.runInContext(fs.readFileSync('notification-client.js','utf8')+'\nthis.Feed=NotificationFeed',ctx);
test('notifications advance only their device cursor and preferences do not delete events',async()=>{
 const store=new Map(),seen=[];const storage={getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v)};
 const feed=new ctx.Feed({storage,request:async path=>path.includes('preferences')?{preferences:{message:false}}:{events:[{sequence:3,kind:'message'}],nextSequence:3},onEvent:async(e,remind)=>seen.push([e.sequence,remind])});
 feed.changeScope('one');await feed.poll();assert.deepEqual(seen,[[3,false]]);assert.equal(store.get('one:notifications'),'3');assert.equal(store.has('two:notifications'),false);
});
test('late responses from a previous device cannot deliver or advance the new reader',async()=>{
 let resolve;const seen=[],store=new Map();const feed=new ctx.Feed({storage:{getItem:()=>0,setItem:(k,v)=>store.set(k,v)},request:()=>new Promise(r=>resolve=r),onEvent:e=>seen.push(e)});
 feed.changeScope('one');const old=feed.poll();feed.changeScope('two');resolve({events:[{sequence:1}],nextSequence:1});await old;assert.equal(seen.length,0);assert.equal(store.size,0);
});
