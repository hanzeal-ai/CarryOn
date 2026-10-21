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
test('event invalidation drains all cursor pages and coalesces a racing event',async()=>{
 const store=new Map(),seen=[],calls=[];let release;
 const feed=new ctx.Feed({storage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v)},request:async path=>{
  calls.push(path);if(path.includes('preferences'))return {preferences:{done:true}};
  const after=Number(path.split('=')[1]);
  if(after===0)await new Promise(resolve=>release=resolve);
  return after===0?{events:[{sequence:1,kind:'done'}],nextSequence:1,hasMore:true}:after===1?{events:[{sequence:2,kind:'done'}],nextSequence:2,hasMore:false}:{events:[],nextSequence:after,hasMore:false};
 },onEvent:e=>seen.push(e.sequence)});
 feed.changeScope('device');const first=feed.invalidate(1);await new Promise(setImmediate);feed.invalidate(2);release();await first;
 assert.deepEqual(seen,[1,2]);assert.equal(store.get('device:notifications'),'2');
 const count=calls.length;await feed.invalidate(2);assert.equal(calls.length,count);
 await feed.invalidate(2,true);assert.ok(calls.length>count);
});
test('failed event reads retry only on failure and pause cancels pending recovery',async()=>{
 let timer=null,attempts=0;
 const context=vm.createContext({setTimeout:fn=>(timer=fn,1),clearTimeout:()=>{timer=null;}});
 vm.runInContext(fs.readFileSync('notification-client.js','utf8')+'\nthis.Feed=NotificationFeed',context);
 const feed=new context.Feed({storage:{getItem:()=>0,setItem(){}},request:async()=>{attempts++;throw Error('offline');},onEvent(){}});
 feed.changeScope('one');await feed.invalidate(1);assert.equal(attempts,1);assert.equal(typeof timer,'function');
 feed.pause();assert.equal(timer,null);assert.equal(attempts,1);
});
