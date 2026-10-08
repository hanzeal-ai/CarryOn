const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch();
 try { for(const [width,scheme] of [[1280,'light'],[390,'light'],[1280,'dark'],[390,'dark']]){
 const page=await browser.newPage({viewport:{width,height:844},colorScheme:scheme});
 const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.log('PAGEERROR',e.stack)});let authenticated=true;
 const writes=[],reads=[],bindingCalls=[];let historyReply=null;
 const defaultHistory={thread:{id:'t1'},historyRevision:'initial',runtime:{type:'idle'},status:{state:'idle'},metadata:{},access:{nativeReady:true,canInteract:true},controls:{supportedOperations:['rename'],supportedSettings:[],requests:[],settings:{}},timeline:[]};const threads=[{id:'t1',title:'让手机上的对话更顺手',cwd:'/workspace/CarryOn',unread:true},{id:'t2',title:'检查远端连接',cwd:'/workspace/CarryOn',unread:false}];
 let allThreads=threads;let archived=false,lost=true,renameQueries=0;const archiveJobs=new Map();
 const projects=[{id:'p1',name:'CarryOn',cwd:'/workspace/CarryOn',total:12,waiting:1,running:2,unread:3,unknown:0},{id:'p2',name:'MarkFix',cwd:'/workspace/MarkFix',total:8,waiting:0,running:0,unread:1,unknown:0}];
 await page.addInitScript(()=>{window.CARRYON_CLOUD=true;});
 await page.route('**/console/**',async route=>{
  const req=route.request(),u=new URL(req.url());let data={},status=200;
  if(u.pathname.endsWith('/session')){if(!authenticated){status=401;data={error:'请先登录云端控制台'};}else data={devices:[{id:'mac',name:'我的 MacBook',online:true,permissions:['view','create','edit','send','files','approve','stop']},{id:'other',name:'工作室 Mac',online:true,permissions:['view','create','edit','send','files','approve','stop']}]};}
  else if(u.pathname.endsWith('/login'))authenticated=true;
  else if(u.pathname.endsWith('/logout'))authenticated=false;
  else if(u.pathname.endsWith('/binding/pending'))data={requests:[]};
  else if(u.pathname.includes('/binding/')){bindingCalls.push({path:u.pathname,body:req.postDataJSON()});data={name:'测试工作区',permissions:['view'],account:{username:'tester'},state:u.pathname.endsWith('/accept')?'bound':'pending'};}
  else if(u.pathname.endsWith('/request')){
   const body=req.postDataJSON(),path=body.path.split('?')[0];if(body.method==='POST')writes.push(body);else reads.push(body.path);
   if(path==='/api/threads'&&body.method==='POST')data={id:body.body.requestId,state:'completed',createdThreadId:'native-created'};
   else if(path==='/api/status')data={enabled:true,remoteControl:true,supportsCreationReferences:true};
   else if(path==='/api/creation/references')data={skills:[{name:'review',path:'/skills/review/SKILL.md',enabled:true}],mentions:[{name:'Fixture App',path:'app://fixture',enabled:true}],errors:[]};
   else if(path==='/api/models')data={models:[{id:'fixture-model',name:'Fixture Model',efforts:['medium','high'],defaultEffort:'medium'},{id:'gpt-6-astra',name:'GPT-6 Astra',efforts:['medium','high'],defaultEffort:'medium'}]};
   else if(path==='/api/projects')data={projects,total:2,nextOffset:2};
   else if(path==='/api/workspace/threads'){const query=new URL('http://fixture'+body.path).searchParams,offset=Number(query.get('offset')||0);data={threads:allThreads.slice(offset,offset+100),total:allThreads.length,nextOffset:offset+100};}
   else if(path==='/api/threads'||path==='/api/projects/p1/threads')data={threads,total:2,nextOffset:2};
   else if(path==='/api/activity')data={threads:[threads[1]],total:1,nextOffset:1};
   else if(path.includes('/history'))data=historyReply?await historyReply(body.path):defaultHistory;
   else if(path==='/api/archived')data={threads:archived?[threads[0]]:[],nextOffset:archived?1:0,supportsRestore:true};
   else if(path.endsWith('/rename')){const id=body.body.requestId,name=body.body.name;data={id:'wrong',threadId:'other',kind:'rename',name,state:'failed'};archiveJobs.set(id,{id,threadId:'t1',kind:'rename',name,state:'uncertain',result:{threadId:'t1',name}});}
   else if(path.startsWith('/api/jobs/')){renameQueries++;const job=archiveJobs.get(path.split('/').at(-1));data=renameQueries===1?{id:'wrong',threadId:'other',kind:'rename',state:'failed'}:{...job,state:renameQueries===2?'uncertain':'completed'};if(renameQueries>2)threads[0].title=job.name;}
   else if(path==='/api/notifications')data={events:[],nextSequence:0};
   else if(path==='/api/notifications/preferences')data={preferences:{message:true,done:true,failed:true,approval:true,...body.body}};
   else if(path==='/api/standby')data={supported:true,effective:true,enabled:true};
  }else if(u.pathname.endsWith('/streams')&&req.method()==='POST')data={streamId:'s'};
  else if(u.pathname.includes('/streams/')&&req.method()==='GET'){await new Promise(r=>setTimeout(r,1000));data={revision:1};}
  await route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
 });
 await page.routeWebSocket('**/console/devices/*/ws', socket=>{
  let revision=0;
  socket.onMessage(raw=>{const selection=JSON.parse(raw);if(selection.type==='subscribe')socket.send(JSON.stringify({type:'update',revision:++revision,resubscribe:true,subscription:selection.subscription,body:{type:'update',subscription:selection.subscription,threadId:selection.threadId,status:{enabled:true,remoteControl:true,supportsCreationReferences:true}}}));});
 });

 await page.goto('http://127.0.0.1:8923/example.html');
 await page.waitForFunction(()=>typeof Timeline!=='undefined'&&enabled);

 await page.evaluate(()=>selectThread('t1'));await page.evaluate(async history=>receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history},()=>true),defaultHistory);
 await page.waitForFunction(()=>composeHistory?.controls?.supportedOperations?.includes('rename'));
 await page.locator('#prompt > [contenteditable]').fill('保留本地草稿');
 if(width===390){await page.getByRole('button',{name:'会话工具',exact:true}).click();await page.locator('#mobile-tools').getByRole('button',{name:'重命名',exact:true}).click();}
 else{await page.getByLabel('会话菜单',{exact:true}).click();await page.locator('#rename-thread').click();}
 await page.locator('#rename-name').fill('新的中文名称 🧭');await page.locator('#rename-dialog').getByRole('button',{name:'保存',exact:true}).click();
 await page.waitForFunction(()=>client.operations.has('rename:t1')&&!document.querySelector('#rename-dialog .archive-actions button:first-child').hidden&&!document.querySelector('#rename-dialog .archive-actions button:first-child').disabled);
 assert(await page.locator('#rename-dialog').getByRole('button',{name:'保存',exact:true}).isDisabled());
 assert.equal(writes.filter(write=>write.path.endsWith('/rename')).length,1);
 await page.locator('#rename-dialog').getByRole('button',{name:'关闭',exact:true}).click();
 await page.evaluate(()=>RenameControls.open());await page.waitForFunction(()=>document.querySelector('#rename-dialog [role="status"]').textContent.includes('身份'));
 assert.equal(writes.filter(write=>write.path.endsWith('/rename')).length,1);assert(await page.locator('#rename-name').isDisabled());
 await page.locator('#rename-dialog').getByRole('button',{name:'核对重命名结果',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#rename-name').value==='新的中文名称 🧭');
 await page.screenshot({path:'.runtime/web-rename-'+width+'-'+scheme+'.png'});
 await page.locator('#rename-dialog').getByRole('button',{name:'核对重命名结果',exact:true}).click();
 await page.waitForFunction(()=>!document.querySelector('#rename-dialog').open&&document.querySelector('#title').textContent==='新的中文名称 🧭');
 assert.equal(writes.filter(write=>write.path.endsWith('/rename')).length,1);assert.equal(await page.locator('#prompt > [contenteditable]').textContent(),'保留本地草稿');
 await page.evaluate(()=>{composeHistory.access.canInteract=false;RenameControls.update();RenameControls.open();});assert.equal(await page.locator('#rename-dialog').evaluate(n=>n.open),false);
 assert.deepEqual(errors,[]);console.log('PASS rename query-only '+width+' '+scheme);await page.close();
 }}finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
