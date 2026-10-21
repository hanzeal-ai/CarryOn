const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
fs.mkdirSync('.runtime/uploads',{recursive:true});
(async()=>{
 const browser=await chromium.launch();
 try{for(const [width,cloud] of [[1280,true],[390,true],[1280,false]]){
  const page=await browser.newPage({viewport:{width,height:900}}),errors=[],writes=[],batches=new Map();
  page.on('pageerror',e=>{errors.push(e.message);console.error(e.message);});page.setDefaultTimeout(10000);
  const uploadLimits={chunkBytes:49152,maxEntries:100,maxFileBytes:20971520,maxTotalBytes:52428800};
  const status={workspaceSession:'upload-fixture',enabled:true,remoteControl:true,supportsUploads:true,uploadLimits};
  let failChunk=true,delayChunk=0,loseCompose=false,accountID='owner';
  await page.addInitScript(cloud=>{window.CARRYON_CLOUD=cloud;if(!cloud)sessionStorage.setItem('carryon-token','fixture-pairing-token');},cloud);
  await page.route(/\/(console|api)\//,async route=>{
   const req=route.request(),u=new URL(req.url());let data={},code=200;
   if(u.pathname.endsWith('/session'))data={account:{id:accountID},devices:[{id:'mac',name:'我的 MacBook',online:true,permissions:['view','send','files','create','stop']}]};
   else if(u.pathname.endsWith('/binding/pending'))data={requests:[]};
   else if(u.pathname.endsWith('/request')||u.pathname.startsWith('/api/')){
    const b=cloud?req.postDataJSON():{method:req.method(),path:u.pathname+u.search,body:req.method()==='POST'?req.postDataJSON():undefined},path=b.path.split('?')[0],body=b.body;
    if(b.method==='POST')writes.push(b);
    if(path==='/api/uploads'){
     if(body.action==='begin'){
      let entry=[...batches.values()].find(x=>x.requestId===body.requestId);
      if(!entry){entry={...body,id:batches.size.toString(16).padStart(32,'0'),state:'uploading',chunks:new Map()};batches.set(entry.id,entry);}
      data={id:entry.id,name:entry.name,kind:entry.kind,target:entry.target,state:entry.state};
     }else{
      const entry=batches.get(body.uploadId);assert(entry);
      if(body.action==='chunk'){
       if(delayChunk)await new Promise(r=>setTimeout(r,delayChunk));
       const key=body.path+':'+body.offset;if(entry.chunks.has(key))assert.equal(entry.chunks.get(key),body.data);entry.chunks.set(key,body.data);
       if(body.offset===98304&&failChunk){failChunk=false;code=503;data={error:'测试连接中断'};}else data={offset:body.offset+Buffer.from(body.data,'base64').length};
      }else {entry.state='complete';data={id:entry.id,name:entry.name,kind:entry.kind,target:entry.target,state:'complete',path:'/attachments/'+entry.id+'/'+entry.name};}
     }
    }else if(b.method==='POST'&&(path.endsWith('/compose')||path.endsWith('/operations')||path==='/api/threads')){
     data={id:body.requestId,state:path==='/api/threads'?'completed':'accepted',...(path==='/api/threads'?{createdThreadId:'created'}:{})};
     if(path.endsWith('/compose')&&loseCompose){loseCompose=false;code=503;data={error:'发送结果暂未确认'};}
    }else if(path==='/api/status')data=status;
    else if(path==='/api/projects')data={projects:[{id:'p1',name:'CarryOn',cwd:'/workspace/CarryOn'},{id:'p2',name:'Notes',cwd:'/workspace/Notes'}],total:2,nextOffset:2};
    else if(path==='/api/threads'||path==='/api/workspace/threads'||path.endsWith('/threads'))data={threads:[{id:'t1',title:'整理项目资料',cwd:'/workspace/CarryOn'},{id:'t2',title:'另一个会话',cwd:'/workspace/CarryOn'}],total:2,nextOffset:2};
    else if(path==='/api/models')data={models:[]};
    else if(path==='/api/activity')data={threads:[],total:0,nextOffset:0};
    else if(path==='/api/jobs')data={jobs:[]};
    else if(path==='/api/notifications')data={events:[],nextSequence:0};
    else if(path==='/api/standby')data={supported:true,enabled:true,effective:true};
   }
   await route.fulfill({status:code,contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.routeWebSocket('**/console/devices/*/ws',socket=>{
   let revision=0;socket.onMessage(raw=>{const selection=JSON.parse(raw);if(selection.type==='subscribe')socket.send(JSON.stringify({type:'update',revision:++revision,resubscribe:true,subscription:selection.subscription,body:{type:'update',subscription:selection.subscription,threadId:selection.threadId,status}}));});
  });
  await page.routeWebSocket('**/api/stream',socket=>socket.onMessage(raw=>{const value=JSON.parse(raw);if(value.type==='ping')socket.send(JSON.stringify({type:'pong'}));else if(value.subscription)socket.send(JSON.stringify({type:'update',subscription:value.subscription,threadId:value.threadId,status}));}));
  await page.goto('http://127.0.0.1:8923/example.html');await page.waitForFunction(()=>typeof enabled!=='undefined'&&enabled&&!document.body.classList.contains('booting'));
  async function select(id,running=false){await page.evaluate(async({id,running})=>{
   await selectThread(id);const history={thread:{id,title:'整理项目资料'},runtime:{type:running?'active':'idle'},status:{state:running?'running':'idle'},access:{nativeReady:true,canInteract:true},controls:{requests:[],supportedOperations:['queue-add'],canSteer:true,activeTurnId:running?'turn':null},queue:{fingerprint:'queue',messages:[]},timeline:[{id:'welcome',type:'agentMessage',text:'可以把需要整理的文件发给我。'}]};
   await receiveUpdate({status:{enabled:true,remoteControl:true,supportsUploads:true,uploadLimits:{chunkBytes:49152,maxEntries:100,maxFileBytes:20971520,maxTotalBytes:52428800}},subscription,threadId:id,history},()=>true);
  },{id,running});}
  async function menu(context='chat'){
   if(width===390)await page.locator(context==='new'?'#new-attach-images':'#attach-images').click();
   else await page.locator(context==='new'?'#new-attachment-details > summary':'#composer-attachment-details > summary').click();
  }
  async function choose(name,buffer,context='chat'){
   await menu(context);const [chooser]=await Promise.all([page.waitForEvent('filechooser'),page.locator(context==='new'?'#new-upload-files':'#upload-files').click()]);
   await chooser.setFiles({name,mimeType:'application/octet-stream',buffer});
   if(width!==390)await page.evaluate(context=>{$(context==='new'?'new-attachment-details':'composer-attachment-details').open=false;},context);
  }
  await select('t1');await choose('资料.bin',Buffer.alloc(110000,7));
  await page.locator('[aria-label="重试上传 资料.bin"]').waitFor();assert(await page.locator('#send').isDisabled());
  await page.locator('[aria-label="重试上传 资料.bin"]').click();await page.waitForFunction(()=>chatUploads.has()&&!chatUploads.blocked());
  assert.equal(batches.size,1);assert.equal([...batches.values()][0].chunks.size,3);
  await select('t2');assert.equal(await page.locator('#upload-previews .upload-chip').count(),0);
  await select('t1');assert.equal(await page.locator('#upload-previews .upload-chip').count(),1);
  // Exercise the directory picker contract, including an empty subdirectory.
  await page.evaluate(()=>{window.showDirectoryPicker=async()=>({name:'设计资料',kind:'directory',async *values(){yield {name:'空目录',kind:'directory',async *values(){}};yield {name:'说明.txt',kind:'file',getFile:async()=>new File(['项目说明'],'说明.txt')};}});});
  await menu();await page.locator('#upload-folder').click();
  if(width!==390)await page.evaluate(()=>{$('composer-attachment-details').open=false;});
  await page.waitForFunction(()=>chatUploads.snapshot().ids.length===2);
  assert([...batches.values()].at(-1).entries.some(e=>e.path==='设计资料/空目录'&&e.kind==='directory'));
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.locator('#notice').waitFor({state:'hidden'});
  await page.screenshot({path:`.runtime/uploads/${width}-${cloud?'cloud':'local'}-attachments.png`});
  await menu();await page.screenshot({path:`.runtime/uploads/${width}-${cloud?'cloud':'local'}-menu.png`});
  if(width===390)await page.evaluate(()=>document.querySelector('.mobile-attachment-menu:popover-open').hidePopover());else await page.evaluate(()=>{$('composer-attachment-details').open=false;});
  await page.locator('#send').click();await page.waitForFunction(()=>!chatUploads.has()&&!imageBusy);
  const compose=writes.filter(w=>w.path.endsWith('/compose')).at(-1);assert.equal(compose.body.prompt,'');assert.equal(compose.body.uploads.length,2);assert(!('path' in compose.body));
  await page.evaluate(()=>Timeline.render({thread:{id:'t1'},timeline:[{id:'uploaded',type:'userMessage',text:'',artifacts:[
   {id:'folder',name:'设计资料',kind:'directory',previewAvailable:false},
   {id:'large',name:'原始图片.png',kind:'image',previewAvailable:false},
   {id:'small',name:'说明.txt',kind:'file'}
  ]}]},$('messages'),()=>{throw Error('非预览附件不应自动读取');}));
  assert.equal(await page.locator('#messages .result-attachment button').count(),1);
  assert.equal(await page.locator('#messages .result-attachment button.attachment-name').innerText(),'说明.txt');
  assert.equal(await page.locator('#messages [aria-label=\"设计资料，文件夹附件\"]').count(),1);
  // Browser download must preserve the actual bytes and Unicode filename, including on mobile.
  await page.evaluate(()=>{
   window.downloadAttempts=0;
   Timeline.render({thread:{id:'t1'},timeline:[{id:'download-result',type:'agentMessage',text:'生成完成',artifacts:[
    {id:'binary',name:'报告 数据.bin',kind:'file'}
   ]}]},$('messages'),async(id,kind)=>{
    if(id!=='binary'||kind!=='artifacts')throw Error('附件路由错误');
    window.downloadAttempts++;
    if(window.downloadAttempts===1)throw Error('文件权限已撤销');
    await new Promise(resolve=>setTimeout(resolve,100));
    return {mime:'application/octet-stream',base64:'AAEC/w=='};
   });
  });
  assert.equal(await page.getByRole('button',{name:'下载 报告 数据.bin',exact:true}).count(),0);
  const previewButton=page.getByRole('button',{name:'报告 数据.bin',exact:true});
  await previewButton.click();await page.getByText('文件权限已撤销',{exact:true}).waitFor();
  await previewButton.click();
  const downloadButton=page.locator('.attachment-preview').getByRole('button',{name:'下载 报告 数据.bin',exact:true});
  await downloadButton.waitFor();
  const downloaded=page.waitForEvent('download');await downloadButton.click();
  const file=await downloaded;assert.equal(file.suggestedFilename(),'报告 数据.bin');
  assert.deepEqual(fs.readFileSync(await file.path()),Buffer.from([0,1,2,255]));
  assert.equal(await page.locator('#messages .image-status').innerText(),'');
  assert.equal(await page.evaluate(()=>window.downloadAttempts),2);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:`.runtime/uploads/${width}-${cloud?'cloud':'local'}-download.png`});
  await page.locator('.attachment-preview').getByRole('button',{name:'关闭',exact:true}).click();
  assert.equal(await page.getByRole('button',{name:'下载 报告 数据.bin',exact:true}).count(),0);
  const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII=';
  await page.evaluate(png=>Timeline.render({thread:{id:'t1'},timeline:[{id:'image-download',type:'agentMessage',text:'图片',artifacts:[{id:'png',kind:'image',name:'结果.png',url:'data:image/png;base64,'+png}]}]},$('messages')),png);
  await page.getByRole('button',{name:'打开原图',exact:true}).click();
  const imageDownloaded=page.waitForEvent('download');await page.locator('.timeline-image-lightbox').getByRole('button',{name:'下载',exact:true}).click();
  const imageFile=await imageDownloaded;assert.equal(imageFile.suggestedFilename(),'结果.png');
  assert.deepEqual(fs.readFileSync(await imageFile.path()),Buffer.from(png,'base64'));
  await page.locator('.timeline-image-lightbox').getByRole('button',{name:'关闭',exact:true}).click();
  // In-flight completion stays with its captured conversation.
  delayChunk=100;await choose('原会话.txt',Buffer.alloc(60000,2));await select('t2');
  await page.waitForTimeout(400);assert.equal(await page.locator('#upload-previews .upload-chip').count(),0);
  await select('t1',true);await page.waitForFunction(()=>chatUploads.has()&&!chatUploads.blocked());
  await page.locator('#send').click();await page.waitForFunction(()=>!chatUploads.has()&&!imageBusy);
  assert.equal(writes.filter(w=>w.path.endsWith('/operations')).at(-1).body.action,'queue-add');delayChunk=0;
  // Creation attachments are scoped to the selected project and allow an attachment-only task.
  await page.evaluate(()=>$('create').click());await page.locator('#new-project').selectOption('p1');
  await choose('需求.txt',Buffer.from('需求'),'new');await page.waitForFunction(()=>newUploads.has()&&!newUploads.blocked());
  await page.locator('#new-project').selectOption('p2');assert.equal(await page.locator('#new-upload-previews .upload-chip').count(),0);
  await page.locator('#new-project').selectOption('p1');assert.equal(await page.locator('#new-upload-previews .upload-chip').count(),1);
  await page.locator('#submit-create').click();await page.waitForFunction(()=>selected==='created');
  assert.equal(writes.filter(w=>w.path==='/api/threads'&&w.method==='POST').at(-1).body.uploads.length,1);
  // An unknown send survives reload with the same attachment and request IDs, isolated from other accounts.
  if(!cloud)await page.evaluate(()=>{client.epoch=9;});
  await select('t1');await choose('恢复.txt',Buffer.from('恢复'));
  await page.waitForFunction(()=>chatUploads.has()&&!chatUploads.blocked());
  const originalIDs=await page.evaluate(()=>chatUploads.snapshot().ids),batchCount=batches.size;
  loseCompose=true;await page.locator('#send').click();await page.waitForFunction(()=>!imageBusy);
  const originalRequest=writes.filter(w=>w.path.endsWith('/compose')).at(-1).body.requestId;
  if(cloud){accountID='other';await page.reload();await page.waitForFunction(()=>enabled&&!document.body.classList.contains('booting'));await select('t1');
  assert.equal(await page.locator('#upload-previews .upload-chip').count(),0);}
  accountID='owner';await page.reload();await page.waitForFunction(()=>enabled&&!document.body.classList.contains('booting'));await select('t1');
  assert.deepEqual(await page.evaluate(()=>chatUploads.snapshot().ids),originalIDs);assert.equal(batches.size,batchCount);
  await page.locator('#send').click();await page.waitForFunction(()=>!imageBusy&&!chatUploads.has());
  assert.equal(writes.filter(w=>w.path.endsWith('/compose')).at(-1).body.requestId,originalRequest);
  // Revoked file capability blocks sending an existing upload but never traps it in the draft.
  await select('t1');await choose('删除.txt',Buffer.from('x'));await page.waitForFunction(()=>chatUploads.has()&&!chatUploads.blocked());
  await page.evaluate(()=>{if(cloudMode)client.devices[0].permissions=client.devices[0].permissions.filter(v=>v!=='files');else supportsUploads=false;updateComposeButton();});
  assert(await page.locator('#send').isDisabled());await page.locator('[aria-label="移除附件 删除.txt"]').click();assert.equal(await page.locator('#upload-previews .upload-chip').count(),0);
  assert.deepEqual(errors,[]);await page.close();console.log(`upload UI ${width} ${cloud?'cloud':'local'}: passed`);
 }}finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
