const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch();
 try{for(const [width,scheme] of [[1280,'light'],[390,'light'],[1280,'dark'],[390,'dark']]){
  const page=await browser.newPage({viewport:{width,height:844},colorScheme:scheme}),errors=[],writes=[],jobs=new Map();let queries=0,orderQueries=0,orderReads=0,groups=[{id:'pinned',pinned:true,title:'Pinned'},{id:'g',title:'研发'}];
  page.on('pageerror',e=>errors.push(e.message));await page.addInitScript(()=>window.CARRYON_CLOUD=true);
  await page.route('**/console/**',async route=>{
   const request=route.request(),url=new URL(request.url());let data={};
   if(url.pathname.endsWith('/session'))data={devices:[{id:'mac',name:'Mac',online:true,permissions:['view','edit','send']}]};
   else if(url.pathname.endsWith('/request')){
    const envelope=request.postDataJSON(),path=envelope.path.split('?')[0],body=envelope.body;
    if(envelope.method==='POST')writes.push(envelope);
    if(path==='/api/status')data={enabled:true,remoteControl:true,supportsThreadSections:true};
    else if(path==='/api/sections'&&envelope.method==='POST'){
     const id=body.requestId;data={id:'wrong',threadId:'sections',kind:'section-create',sectionId:null,body:{name:body.name},state:'failed'};
     jobs.set(id,{id,threadId:'sections',kind:'section-create',sectionId:null,body:{name:body.name},state:'uncertain',result:{section:{id:'created',name:body.name}}});
    }else if(path==='/api/sections/g'&&envelope.method==='POST'){
     data={id:body.requestId,threadId:body.action==='order'?body.threadId:'g',kind:'section-'+body.action,sectionId:'g',body:body.action==='order'?{action:'order',threadId:body.threadId,beforeThreadId:body.beforeThreadId}:body.action==='delete'?{action:'delete'}:{action:'update',name:body.name},state:'completed',result:body.action==='order'?{threadId:body.threadId,sectionId:'g',beforeThreadId:body.beforeThreadId}:body.action==='delete'?{sectionId:'g',deleted:true}:{section:{id:'g',name:body.name}}};
     if(body.action==='order'){jobs.set(body.requestId,data);data={...data,result:{...data.result,beforeThreadId:'wrong'}};}
     else groups=body.action==='delete'?groups.filter(g=>g.id!=='g'):groups.map(g=>g.id==='g'?{...g,title:body.name}:g);
    }else if(path==='/api/sections')data={sections:groups,nextCursor:null};
    else if(path==='/api/sections/g/threads'){orderReads++;if(orderReads===2){await route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({error:'fixture member load failed'})});return;}data={threads:[{id:'t1',title:'排序会话'},{id:'t2',title:'很长的参照会话标题用于验证手机选择器宽度与触摸区域'}],nextCursor:null};}
    else if(path.startsWith('/api/sections/'))data={threads:[],nextCursor:null};
    else if(path.startsWith('/api/jobs/')){queries++;const job=jobs.get(path.split('/').at(-1));if(job.kind==='section-order'){orderQueries++;data=orderQueries===1?{...job,result:{...job.result,beforeThreadId:'wrong'}}:job;}else data=queries===1?{...job,state:'failed',body:{name:'错误名称'}}:{...job,state:'completed'};}
    else if(path==='/api/projects')data={projects:[],total:0,nextOffset:0};
    else if(path==='/api/workspace/threads')data={threads:[],total:0,nextOffset:0};
    else if(path==='/api/jobs')data={jobs:[]};else if(path==='/api/notifications')data={events:[],nextSequence:0};else if(path==='/api/models')data={models:[]};
   }else if(url.pathname.endsWith('/streams')&&request.method()==='POST')data={streamId:'s'};
   else if(url.pathname.includes('/streams/')&&request.method()==='GET'){await new Promise(r=>setTimeout(r,500));data={revision:1};}
   await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.routeWebSocket('**/console/devices/*/ws',()=>{});
  await page.goto(process.env.CARRYON_UI_URL||'http://127.0.0.1:8923/example.html');
  await page.locator('#native-sections').getByRole('button',{name:'新建分组',exact:true}).click();
  const dialog=page.locator('#section-management-dialog');await dialog.locator('input').fill('新分组');await dialog.getByRole('button',{name:'保存',exact:true}).click();
  await page.waitForFunction(()=>client.operations.has('section-management')&&!document.querySelector('#section-management-dialog .archive-actions button:nth-child(2)').disabled);
  assert(await dialog.locator('input').isDisabled());assert.equal(writes.length,1);
  await dialog.getByRole('button',{name:'关闭',exact:true}).click();
  await page.locator('#native-sections').getByRole('button',{name:'新建分组',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#section-management-dialog [role=status]').textContent.includes('身份不匹配'));assert.equal(writes.length,1);
  await page.screenshot({path:'.runtime/web-section-management-'+width+'-'+scheme+'.png',fullPage:true});
  await dialog.getByRole('button',{name:'核对原请求',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('#section-management-dialog').open);assert.equal(writes.length,1);
  await page.getByRole('button',{name:'编辑分组 研发',exact:true}).click();await dialog.locator('input').fill('研发二组');await dialog.getByRole('button',{name:'保存',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('#section-management-dialog').open);assert.equal(writes.length,2);
  await page.locator('#native-sections [data-section-id="g"] summary').click();await page.getByRole('button',{name:'调整顺序 排序会话',exact:true}).click();
  await dialog.getByRole('button',{name:'重新读取会话',exact:true}).waitFor();assert.equal(writes.length,2);await dialog.getByRole('button',{name:'重新读取会话',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('#section-order-before').disabled);assert.equal(writes.length,2);assert.equal(await dialog.locator('[role=status]').innerText(),'');const selectBox=await dialog.locator('select').boundingBox();assert(selectBox.height>=44);assert(selectBox.width>200);await dialog.locator('select').selectOption('t2');await page.screenshot({path:'.runtime/web-section-order-'+width+'-'+scheme+'.png',fullPage:true});
  await dialog.getByRole('button',{name:'保存',exact:true}).click();await page.waitForFunction(()=>client.operations.has('section-management')&&!document.querySelector('#section-management-dialog .archive-actions button:nth-child(2)').disabled);assert.equal(writes.length,3);
  await dialog.getByRole('button',{name:'核对原请求',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#section-management-dialog [role=status]').textContent.includes('身份不匹配'));assert.equal(writes.length,3);
  await dialog.getByRole('button',{name:'核对原请求',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('#section-management-dialog').open);assert.equal(writes.length,3);
  await page.getByRole('button',{name:'编辑分组 研发二组',exact:true}).click();page.once('dialog',d=>d.accept());await dialog.getByRole('button',{name:'删除分组',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('#section-management-dialog').open);assert.equal(writes.length,4);
  await page.waitForFunction(()=>!document.querySelector('#native-sections [data-section-id="g"]'));
  await page.locator('#native-sections').getByRole('button',{name:'新建分组',exact:true}).click();
  await page.evaluate(()=>{client.devices[0].permissions=[];receiveUpdate({status:{enabled:true,remoteControl:true,supportsThreadSections:true}},()=>true);});await page.waitForFunction(()=>!document.querySelector('#section-management-dialog').open);assert.equal(writes.length,4);assert.deepEqual(errors,[]);
  await page.close();console.log('PASS section management '+width+' '+scheme);
 }}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
