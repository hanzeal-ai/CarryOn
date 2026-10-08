const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch();try{for(const [width,scheme] of [[1280,'light'],[390,'light'],[1280,'dark'],[390,'dark']]){
 const page=await browser.newPage({viewport:{width,height:844},colorScheme:scheme}),errors=[],writes=[],jobs=new Map();let reads=0,queries=0;
 const history={thread:{id:'t1'},historyRevision:'initial',runtime:{type:'idle'},status:{state:'idle'},metadata:{},access:{canInteract:true,nativeReady:true},controls:{supportsBackgroundTerminals:true,supportedOperations:[],supportedSettings:[],requests:[],settings:{}},timeline:[]};
 const terminals=[{id:'native-1',processId:'native-1',command:'npm run dev -- --host 127.0.0.1',cwd:'/workspace/CarryOn'},{id:'native-2',processId:'native-2',command:'python3 scripts/check_long_running_background_task.py',cwd:'/workspace/CarryOn/a/long/path/to/a/project'}];
 await page.addInitScript(()=>window.CARRYON_CLOUD=true);page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/console/**',async route=>{const req=route.request(),url=new URL(req.url());let data={};
  if(url.pathname.endsWith('/session'))data={devices:[{id:'mac',name:'Mac',online:true,permissions:['view','stop','send']}]};
  else if(url.pathname.endsWith('/request')){const env=req.postDataJSON(),path=env.path.split('?')[0];
   if(env.method==='POST')writes.push(env);
   if(path==='/api/status')data={enabled:true,remoteControl:true};
   else if(path==='/api/projects')data={projects:[],total:0,nextOffset:0};
   else if(path==='/api/workspace/threads')data={threads:[{id:'t1',title:'验证后台任务'}],total:1,nextOffset:1};
   else if(path.endsWith('/history'))data=history;
   else if(path.endsWith('/terminals')){if(env.method==='POST'){const body={...env.body};delete body.requestId;const job={id:env.body.requestId,threadId:'t1',kind:'terminal-'+body.action,body,state:'completed',result:body.action==='clean'?{threadId:'t1',cleaned:true}:{threadId:'t1',processId:body.processId,terminated:true}};jobs.set(job.id,job);data={...job,id:'wrong',state:'failed'};}
    else{reads++;if(reads===1){await route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({error:'fixture inventory unavailable'})});return;}data={threadId:'t1',terminals,nextCursor:null};}}
   else if(path.startsWith('/api/jobs/')){queries++;const job=jobs.get(path.split('/').at(-1));data=queries===1?{...job,body:{action:'terminate',processId:'wrong'},state:'failed'}:job;}
   else if(path==='/api/notifications')data={events:[],nextSequence:0};else if(path==='/api/jobs')data={jobs:[]};else if(path==='/api/models')data={models:[]};
  }else if(url.pathname.endsWith('/streams')&&req.method()==='POST')data={streamId:'s'};else if(url.pathname.includes('/streams/')){await new Promise(r=>setTimeout(r,500));data={revision:1};}
  await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
 });await page.routeWebSocket('**/console/devices/*/ws',()=>{});
 await page.goto(process.env.CARRYON_UI_URL||'http://127.0.0.1:8923/example.html');await page.waitForFunction(()=>enabled);
 await page.evaluate(()=>selectThread('t1'));await page.evaluate(h=>receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:h},()=>true),history);
 await page.waitForFunction(()=>composeHistory?.controls?.supportsBackgroundTerminals===true);
 if(width===390){await page.getByRole('button',{name:'会话工具',exact:true}).click();await page.locator('#mobile-tools').getByRole('button',{name:'后台终端',exact:true}).click();}else{await page.getByLabel('会话菜单',{exact:true}).click();await page.locator('#open-terminals').click();}
 const dialog=page.locator('#terminals-dialog');await dialog.getByRole('status').filter({hasText:'fixture inventory unavailable'}).waitFor();assert.equal(writes.length,0);
 await dialog.getByRole('button',{name:'刷新',exact:true}).click();await dialog.getByRole('button',{name:'停止',exact:true}).first().waitFor();assert.equal(await dialog.getByRole('status').innerText(),'');
 await page.screenshot({path:'.runtime/web-terminals-'+width+'-'+scheme+'.png',fullPage:true});
 assert(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth+1));await dialog.getByRole('button',{name:'停止',exact:true}).first().focus();await page.evaluate(()=>TerminalControls.update());assert.equal(await page.evaluate(()=>document.activeElement?.textContent),'停止');await page.keyboard.press('Enter');
 await page.waitForFunction(()=>client.operations.has('terminal:t1')&&!document.querySelector('#terminals-dialog button:nth-last-child(2)').disabled);assert.equal(writes.length,1);assert(await dialog.getByRole('button',{name:'停止',exact:true}).first().isDisabled());assert.equal(await page.evaluate(()=>document.activeElement?.textContent),'核对原请求');
 await dialog.getByRole('button',{name:'关闭',exact:true}).click();await page.evaluate(()=>TerminalControls.open());await dialog.getByRole('button',{name:'核对原请求',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#terminals-dialog [role=status]').textContent.includes('身份不匹配'));assert.equal(writes.length,1);
 await dialog.getByRole('button',{name:'核对原请求',exact:true}).click();await page.waitForFunction(()=>!client.operations.has('terminal:t1'));assert.equal(writes.length,1);
 await page.evaluate(()=>{client.devices.find(d=>d.id===client.device).permissions=[];TerminalControls.update();});assert.equal(await dialog.evaluate(el=>el.open),false);assert.equal(errors.length,0,errors.join('\n'));console.log('PASS native terminal UI',width,scheme);await page.close();
 }}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
