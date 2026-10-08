const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch();
 try{for(const [width,scheme] of [[1280,'light'],[390,'light'],[1280,'dark'],[390,'dark']]){
  const page=await browser.newPage({viewport:{width,height:844},colorScheme:scheme}),errors=[],writes=[],reads=[],jobs=new Map();
  page.on('pageerror',error=>errors.push(error.message));let queryCount=0;
  const status={enabled:true,remoteControl:true,supportsThreadSections:true},thread={id:'t1',title:'置顶测试',cwd:'/workspace'},history={thread:{id:'t1'},historyRevision:'fixture',runtime:{type:'idle'},status:{state:'idle'},access:{nativeReady:true,canInteract:true},controls:{requests:[],settings:{},supportedOperations:[]},timeline:[]};
  await page.addInitScript(()=>{window.CARRYON_CLOUD=true;});
  await page.route('**/console/**',async route=>{
   const request=route.request(),url=new URL(request.url());let data={};
   if(url.pathname.endsWith('/session'))data={devices:[{id:'mac',name:'Mac',online:true,permissions:['view','edit','send','create']},{id:'other',name:'Other',online:true,permissions:['view','edit','send','create']}]};
   else if(url.pathname.endsWith('/request')){
    const body=request.postDataJSON(),path=body.path.split('?')[0],params=new URL('http://fixture'+body.path).searchParams;
    if(body.method==='POST')writes.push(body);else reads.push(body.path);
    if(path==='/api/status')data=status;
    else if(path==='/api/sections')data={sections:params.has('cursor')?[{id:'extra',title:'More'}]:[{id:'pinned',title:'Pinned',pinned:true},{id:'custom',title:'研发'}],nextCursor:params.has('cursor')?null:'opaque|groups'};
    else if(path==='/api/sections/pinned/threads')data={threads:params.has('cursor')?[{id:'t2',title:'第二个置顶'}]:[thread],nextCursor:params.has('cursor')?null:'opaque|pinned'};
    else if(path==='/api/sections/custom/threads')data={threads:[{id:'t3',title:'研发任务'}],nextCursor:null};
    else if(path==='/api/sections/extra/threads')data={threads:[],nextCursor:null};
    else if(path==='/api/threads/t1/section'&&body.method==='GET')data={threadId:'t1',sectionId:null};
    else if(path==='/api/threads/t1/section'){
     const id=body.body.requestId,destination=body.body.sectionId;jobs.set(id,{id,threadId:'t1',kind:'section-move',sectionId:destination,state:'uncertain'});data={id:'wrong',threadId:'other',kind:'section-move',sectionId:destination,state:'failed'};
    }
    else if(path.startsWith('/api/jobs/')){queryCount++;const id=path.split('/').at(-1),job=jobs.get(id);data=queryCount===1?{...job,sectionId:'wrong',state:'failed'}:queryCount===2?job:{...job,state:'completed',result:{threadId:'t1',sectionId:job.sectionId}};}
    else if(path==='/api/projects')data={projects:[],total:0,nextOffset:0};
    else if(path==='/api/workspace/threads')data={threads:[thread],total:1,nextOffset:1};
    else if(path.endsWith('/history'))data=history;
    else if(path==='/api/jobs')data={jobs:[]};
    else if(path==='/api/notifications')data={events:[],nextSequence:0};
    else if(path==='/api/models')data={models:[]};
   }else if(url.pathname.endsWith('/streams')&&request.method()==='POST')data={streamId:'s'};
   else if(url.pathname.includes('/streams/')&&request.method()==='GET'){await new Promise(r=>setTimeout(r,1000));data={revision:1};}
   await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  });
  let revision=0;await page.routeWebSocket('**/console/devices/*/ws',socket=>socket.onMessage(raw=>{const selection=JSON.parse(raw);if(selection.type==='subscribe')socket.send(JSON.stringify({type:'update',revision:++revision,resubscribe:true,subscription:selection.subscription,body:{type:'update',subscription:selection.subscription,threadId:selection.threadId,status,history}}));}));
  await page.goto(process.env.CARRYON_UI_URL||'http://127.0.0.1:8923/example.html');await page.waitForFunction(()=>typeof NativeSectionsSidebar!=='undefined'&&enabled&&supportsThreadSections);
  await page.waitForSelector('#native-sections [data-thread-id="t1"]');
  await page.locator('#native-sections [data-section-id="pinned"] .native-section-more').click();await page.waitForSelector('#native-sections [data-thread-id="t2"]');assert(reads.some(path=>path.includes('cursor=opaque%7Cpinned')));
  await page.locator('#native-sections [data-section-id="custom"] summary').click();await page.waitForSelector('#native-sections [data-thread-id="t3"]');
  await page.screenshot({path:'.runtime/section-sidebar-before-more-'+width+'.png',fullPage:true});await page.locator('#native-sections').getByRole('button',{name:'加载更多分组',exact:true}).click();await page.waitForSelector('#native-sections [data-section-id="extra"]');
  await page.setViewportSize({width:width===390?1280:390,height:844});await page.waitForTimeout(100);assert(await page.locator('#native-sections').isVisible());await page.setViewportSize({width,height:844});await page.waitForTimeout(100);assert(await page.locator('#native-sections').isVisible());
  await page.locator('#native-sections [data-thread-id="t1"]').click();await page.waitForFunction(()=>selected==='t1'&&streamReady);
  await page.locator('#prompt > [contenteditable]').fill('保留分组操作前的草稿');
  if(width===390){await page.getByRole('button',{name:'会话工具',exact:true}).click();await page.locator('#mobile-tools').getByRole('button',{name:'移动到分组',exact:true}).click();}
  else{await page.getByLabel('会话菜单',{exact:true}).click();await page.locator('#move-section').click();}
  await page.waitForFunction(()=>!document.querySelector('#section-destination').disabled);await page.locator('#section-destination').selectOption('pinned');await page.locator('#section-dialog').getByRole('button',{name:'保存',exact:true}).click();
  await page.waitForFunction(()=>client.operations.has('section-move:t1')&&!document.querySelector('#section-dialog .archive-actions button:first-child').disabled);
  assert.equal(writes.length,1);assert.equal(writes[0].body.sectionId,'pinned');assert(await page.locator('#section-destination').isDisabled());
  await page.locator('#section-dialog').getByRole('button',{name:'核对移动结果',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#section-dialog [role=status]').textContent.includes('身份不匹配'));
  await page.locator('#section-dialog').getByRole('button',{name:'核对移动结果',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('#section-dialog .archive-actions button:first-child').disabled);
  await page.screenshot({path:'.runtime/web-section-'+width+'-'+scheme+'.png',fullPage:true});
  await page.locator('#section-dialog').getByRole('button',{name:'核对移动结果',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('#section-dialog').open);assert.equal(writes.length,1);assert.equal(await page.locator('#prompt > [contenteditable]').innerText(),'保留分组操作前的草稿');
  await page.evaluate(()=>{client.devices.find(d=>d.id===client.device).permissions=[];receiveUpdate({status:{enabled:true,remoteControl:true,supportsThreadSections:true}},()=>true);});await page.waitForFunction(()=>document.querySelector('#native-sections').hidden);
  assert.deepEqual(errors,[]);await page.close();console.log('PASS native section controls '+width+' '+scheme);
 }}finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
