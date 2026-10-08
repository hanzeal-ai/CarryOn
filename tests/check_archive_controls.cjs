const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch();
 try { for(const [width,scheme] of [[1280,'light'],[390,'light'],[1280,'dark'],[390,'dark']]){
 const page=await browser.newPage({viewport:{width,height:844},colorScheme:scheme});
 const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.log('PAGEERROR',e.stack)});let authenticated=true;
 const writes=[],reads=[],bindingCalls=[];let historyReply=null;
 const defaultHistory={thread:{id:'t1'},historyRevision:'initial',runtime:{type:'idle'},status:{state:'idle'},metadata:{},access:{nativeReady:true,canInteract:true},controls:{supportedOperations:['archive'],supportedSettings:[],requests:[],settings:{}},timeline:[]};const threads=[{id:'t1',title:'让手机上的对话更顺手',cwd:'/workspace/CarryOn',unread:true},{id:'t2',title:'检查远端连接',cwd:'/workspace/CarryOn',unread:false}];
 let allThreads=threads;let archived=false,lost=true;const archiveJobs=new Map();
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
   else if(path.endsWith('/archive')||path.endsWith('/unarchive')){archived=path.endsWith('/archive');const id=body.body.requestId;data={id,threadId:'t1',kind:archived?'archive':'unarchive',state:lost&&archived?'uncertain':'completed',result:{threadId:'t1',archived}};archiveJobs.set(id,{...data,state:'completed'});if(!archived)data={id:'wrong-receipt',threadId:'other',kind:'unarchive',state:'failed'};}
   else if(path.startsWith('/api/jobs/'))data=archiveJobs.get(path.split('/').at(-1))||{id:path.split('/').at(-1),threadId:'t1',state:'uncertain',error:'仍待核对'};
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


 await page.evaluate(()=>selectThread('t1'));await page.evaluate(async history=>receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history},()=>true),defaultHistory);await page.waitForFunction(()=>selected==='t1'&&composeHistory?.controls?.supportedOperations?.includes('archive'));
 await page.locator('#prompt > [contenteditable]').fill('归档前保留的草稿');
 if(width===390){await page.getByRole('button',{name:'会话工具',exact:true}).click();await page.locator('#mobile-tools').getByRole('button',{name:'归档会话',exact:true}).click();}else{await page.getByLabel('会话菜单',{exact:true}).click();await page.locator('#archive-thread').click();}
 await page.locator('#archive-action').getByRole('button',{name:'归档会话',exact:true}).click();
 await page.locator('#archive-action').getByRole('button',{name:'核对归档结果',exact:true}).waitFor();
 assert.equal(writes.filter(write=>write.path.endsWith('/archive')).length,1);assert.equal(await page.evaluate(()=>selected),'t1');
 await page.screenshot({path:'.runtime/web-archive-unknown-'+width+'-'+scheme+'.png'});
 await page.locator('#archive-action').getByRole('button',{name:'关闭',exact:true}).click();
 await page.evaluate(()=>document.querySelector('#archive-thread').click());
 assert.equal(await page.locator('#archive-action').getByRole('button',{name:'归档会话',exact:true}).isDisabled(),true,'reopened unknown action only allows receipt lookup');
 await page.locator('#archive-action').getByRole('button',{name:'核对归档结果',exact:true}).click();await page.waitForFunction(()=>selected===null);
 assert.equal(writes.filter(write=>write.path.endsWith('/archive')).length,1);assert.equal(await page.evaluate(()=>conversationDrafts.get(activeDraftScope+':t1').text),'归档前保留的草稿');
 await page.evaluate(()=>ArchiveControls.open());await page.locator('.archive-row').waitFor();await page.screenshot({path:'.runtime/web-archives-'+width+'-'+scheme+'.png'});
 await page.locator('.archive-row').first().click();await page.locator('#archive-action').getByRole('button',{name:'恢复会话',exact:true}).click();
 await page.locator('#archive-action').getByRole('button',{name:'核对归档结果',exact:true}).waitFor();
 assert.equal(await page.locator('#archive-action').getByRole('button',{name:'恢复会话',exact:true}).isDisabled(),true,'wrong failed receipt retains original ID');
 await page.locator('#archive-action').getByRole('button',{name:'核对归档结果',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('#archive-action').open);
 assert.equal(writes.filter(write=>write.path.endsWith('/unarchive')).length,1);assert.equal(await page.evaluate(()=>selected),null,'restore never opens/resumes the task');
 await page.locator('#archives-dialog').getByRole('button',{name:'关闭',exact:true}).click();
 await page.evaluate(()=>selectThread('t1'));await page.evaluate(async history=>receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history},()=>true),defaultHistory);await page.waitForFunction(()=>composeHistory?.controls?.supportedOperations?.includes('archive'));
 assert.equal(await page.locator('#prompt').evaluate(node=>node.value),'归档前保留的草稿');
 await page.evaluate(()=>document.querySelector('#archive-thread').click());
 const writesBefore=writes.length;await page.evaluate(()=>{client.device='other';client.setStorage();updateComposeButton();});
 assert.equal(await page.locator('#archive-action').evaluate(node=>node.open),false,'workspace changes close old actions');assert.equal(writes.length,writesBefore);
 assert.deepEqual(errors,[]);console.log('PASS archive/restore full workbench '+width+' '+scheme);await page.close();
 }}finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
