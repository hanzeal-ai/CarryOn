const {test}=require('node:test');
const assert=require('node:assert/strict');
const Uploads=require('../file-uploads.js');
const limits={chunkBytes:49152,maxEntries:100,maxFileBytes:20971520,maxTotalBytes:52428800};
const file=(name,bytes)=>Object.assign(new Blob([bytes]),{name});
const dir=(name,children)=>({name,kind:'directory',async *values(){yield* children;}});
const leaf=(name,bytes)=>({name,kind:'file',getFile:async()=>file(name,bytes)});
test('directory manifest retains empty directories, zero-byte files and NFC names',async()=>{
  const value=await Uploads.directory(dir('cafe\u0301',[dir('empty',[]),leaf('zero',''),dir('子目录',[leaf('内容.txt','你好')])]),limits);
  assert.equal(value.name,'café');
  assert.deepEqual(value.entries.map(e=>e.path),['café','café/empty','café/zero','café/子目录','café/子目录/内容.txt']);
  assert.equal(value.entries[2].size,0);
  assert.equal(value.total,6);
  assert.equal(value.data.get('café/子目录/内容.txt').byteLength,6);
});
test('selection rejects traversal, aliases, entry count and oversized files before upload',async()=>{
  await assert.rejects(Uploads.prepare('../x','file',[],limits),/路径/);
  await assert.rejects(Uploads.directory(dir('root',[leaf('A','a'),leaf('a','b')]),limits),/同名/);
  await assert.rejects(Uploads.directory(dir('root',[dir('a',[])]),{...limits,maxEntries:1}),/最多/);
  await assert.rejects(Uploads.prepare('x','file',[{path:'x',file:file('x','long')}],{...limits,maxFileBytes:3}),/单个文件/);
});
test('browser directory input retains relative paths and rejects mixed roots or an empty selection',async()=>{
  const selected=[Object.assign(file('说明.txt','hello'),{webkitRelativePath:'资料/子目录/说明.txt'})];
  const item=await Uploads.directoryFiles(selected,limits);
  assert.deepEqual(item.entries.map(e=>e.path),['资料','资料/子目录','资料/子目录/说明.txt']);
  await assert.rejects(Uploads.directoryFiles([],limits),/未提供文件夹内容/);
  selected.push(Object.assign(file('other','x'),{webkitRelativePath:'其他/other'}));
  await assert.rejects(Uploads.directoryFiles(selected,limits),/一个文件夹/);
});
test('multi-chunk replay after an unknown response preserves bytes and request identity',async()=>{
  const item=await Uploads.prepare('data.bin','file',[{path:'data.bin',file:file('data.bin',Buffer.alloc(110000,7))}],limits);
  const target={type:'thread',threadId:'t1'},requests=[],chunks=new Map();let fail=true,complete=false;
  const request=async(_,body)=>{
    requests.push(body);
    if(body.action==='begin')return {id:'a'.repeat(32),name:item.name,kind:'file',target,state:complete?'complete':'uploading'};
    if(body.action==='chunk'){
      if(chunks.has(body.offset))assert.equal(chunks.get(body.offset),body.data);else chunks.set(body.offset,body.data);
      if(body.offset===98304&&fail){fail=false;throw Error('lost response');}
      return {offset:body.offset+Buffer.from(body.data,'base64').length};
    }
    complete=true;return {id:'a'.repeat(32),name:item.name,kind:'file',target,state:'complete'};
  };
  await assert.rejects(Uploads.transfer(item,target,request),/lost/);
  assert.equal((await Uploads.transfer(item,target,request)).state,'complete');
  assert.equal(chunks.size,3);
  assert.equal(new Set(requests.filter(r=>r.action==='begin').map(r=>r.requestId)).size,1);
  assert(requests.filter(r=>r.action==='chunk').every(r=>JSON.stringify(r).length<100000));
});
test('wrong target, malformed offsets and workspace switches never complete the attachment',async()=>{
  const item=await Uploads.prepare('x','file',[{path:'x',file:file('x','hello')}],limits),target={type:'thread',threadId:'t1'};
  const receipt={id:'a'.repeat(32),name:'x',kind:'file',target,state:'uploading'};
  await assert.rejects(Uploads.transfer(item,target,async()=>({...receipt,target:{type:'thread',threadId:'t2'}})),/回执/);
  await assert.rejects(Uploads.transfer(item,target,async(_,body)=>body.action==='begin'?receipt:{offset:1}),/进度/);
  let current=true,count=0;
  await assert.rejects(Uploads.transfer(item,target,async()=>{count++;current=false;return receipt;},()=>current),/暂停/);
  assert.equal(count,1);
});
