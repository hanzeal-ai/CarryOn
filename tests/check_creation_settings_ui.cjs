const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch();
 try { for(const width of [1280,768,390,320]){
 const page=await browser.newPage({viewport:{width,height:844}});
 let createDelay=0,createState='uncertain';const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.log('PAGEERROR',e.stack)});let authenticated=true;
 const writes=[],reads=[],bindingCalls=[];let historyReply=null,failOperation=false,forkState='uncertain',forkDelay=0,composeDelay=0,operationDelay=0;
 const defaultHistory={thread:{id:'t1'},historyRevision:'initial',runtime:{type:'idle'},status:{state:'idle'},metadata:{},timeline:[]};const threads=[{id:'t1',title:'让手机上的对话更顺手',cwd:'/workspace/CarryOn',unread:true},{id:'t2',title:'检查远端连接',cwd:'/workspace/CarryOn',unread:false}];
 const projects=[{id:'p1',name:'CarryOn',cwd:'/workspace/CarryOn',total:12,waiting:1,running:2,unread:3,unknown:0},{id:'p2',name:'MarkFix',cwd:'/workspace/MarkFix',total:8,waiting:0,running:0,unread:1,unknown:0}];
 await page.addInitScript(()=>{window.CARRYON_CLOUD=true;});
 await page.route('**/console/**',async route=>{
  const req=route.request(),u=new URL(req.url());let data={},status=200;
  if(u.pathname.endsWith('/session')){if(!authenticated){status=401;data={error:'请先登录云端控制台'};}else data={devices:[{id:'mac',name:'我的 MacBook',online:true,permissions:['view','create','send','edit','stop']},{id:'other',name:'工作室 Mac',online:false}]};}
  else if(u.pathname.endsWith('/login'))authenticated=true;
  else if(u.pathname.endsWith('/logout'))authenticated=false;
  else if(u.pathname.endsWith('/binding/pending'))data={requests:[]};
  else if(u.pathname.includes('/binding/')){bindingCalls.push({path:u.pathname,body:req.postDataJSON()});data={name:'测试工作区',permissions:['view'],account:{username:'tester'},state:u.pathname.endsWith('/accept')?'bound':'pending'};}
  else if(u.pathname.endsWith('/request')){
   const body=req.postDataJSON(),path=body.path.split('?')[0];if(body.method==='POST')writes.push(body);else reads.push(body.path);
   if(body.method==='POST'&&path==='/api/threads'){if(createDelay)await new Promise(r=>setTimeout(r,createDelay));data={id:body.body.requestId,state:createState,createdThreadId:createState==='completed'?'native-created':undefined,error:createState==='uncertain'?'fixture unknown':undefined};}
   else if(body.method==='POST'&&path.endsWith('/fork')){if(forkDelay)await new Promise(resolve=>setTimeout(resolve,forkDelay));data={id:body.body.requestId,state:forkState,...(forkState==='completed'?{createdThreadId:'forked'}:{error:'fixture uncertain'})};}
   else if(body.method==='POST'&&path.endsWith('/compose')){if(composeDelay)await new Promise(resolve=>setTimeout(resolve,composeDelay));data={id:body.body.requestId,state:'accepted'};}
   else if(body.method==='POST'&&path.endsWith('/operations')){if(operationDelay)await new Promise(r=>setTimeout(r,operationDelay));data={id:body.body.requestId,state:typeof failOperation==='string'?failOperation:failOperation?'failed':'completed',error:failOperation?'fixture failure':undefined,...(body.body.action==='review'&&!failOperation?{reviewThreadId:path.split('/')[3],turnId:'review-turn'}:{}),...(['goal-set','goal-pause','goal-clear'].includes(body.body.action)&&!failOperation?{result:body.body.action==='goal-clear'?{cleared:true}:{goal:{threadId:path.split('/')[3],status:body.body.action==='goal-pause'?'paused':body.body.status||'active'}}}:{})};
   }
   else if(path==='/api/status')data={enabled:true,remoteControl:true,supportedCreationSettings:['model','effort','approvalPolicy','collaborationMode']};
   else if(path.endsWith('/mentions'))data={mentions:[{name:'Fixture App',path:'app://fixture',enabled:true,description:'Connected app'},{name:'Unavailable',path:'app://unavailable',enabled:false}],errors:[]};
   else if(path.endsWith('/skills'))data={cwd:'/workspace/CarryOn',skills:[{name:'review',path:'/skills/review/SKILL.md',enabled:true,description:'Review changes'},{name:'disabled',path:'/skills/disabled/SKILL.md',enabled:false}],errors:[{path:'/skills/broken',message:'broken skill fixture'}]};
   else if(path==='/api/models')data={models:[{id:'fixture-model',name:'Fixture Model',efforts:['medium','high'],defaultEffort:'medium'},{id:'gpt-6-astra',name:'GPT-6 Astra',efforts:['medium','high'],defaultEffort:'medium'}]};
   else if(path==='/api/projects')data={projects,total:2,nextOffset:2};
   else if(path==='/api/workspace/threads'||path==='/api/threads'||path==='/api/projects/p1/threads')data={threads,total:2,nextOffset:2};
   else if(path==='/api/activity')data={threads:[threads[1]],total:1,nextOffset:1};
   else if(path.includes('/history'))data=historyReply?await historyReply(body.path):defaultHistory;
   else if(path.startsWith('/api/jobs/'))data={id:path.split('/').at(-1),threadId:'t1',state:'uncertain',error:'仍待核对'};
   else if(path==='/api/notifications')data={events:[],nextSequence:0};
   else if(path==='/api/notifications/preferences')data={preferences:{message:true,done:true,failed:true,approval:true,...body.body}};
   else if(path==='/api/standby')data={supported:true,effective:true,enabled:true};
  }else if(u.pathname.endsWith('/streams')&&req.method()==='POST')data={streamId:'s'};
  else if(u.pathname.includes('/streams/')&&req.method()==='GET'){await new Promise(r=>setTimeout(r,1000));data={revision:1};}
  await route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
 });
 await page.routeWebSocket('**/console/devices/*/ws', socket=>{
  let revision=0;
  socket.onMessage(raw=>{const selection=JSON.parse(raw);if(selection.type==='subscribe')socket.send(JSON.stringify({type:'update',revision:++revision,resubscribe:true,subscription:selection.subscription,body:{type:'update',subscription:selection.subscription,threadId:selection.threadId,status:{enabled:true,remoteControl:true,supportedCreationSettings:['model','effort','approvalPolicy','collaborationMode']}}}));});
 });

 await page.goto('http://127.0.0.1:8923/example.html');
 await page.waitForFunction(()=>typeof Timeline!=='undefined'&&enabled);




 await page.locator('#create').click();await page.waitForFunction(()=>createProjectsReady&&newModelChoices.length===2);await page.locator('#new-project').selectOption('p1');
 if(width<=760)await page.locator('#create-dialog').getByRole('button',{name:'模型与思考强度',exact:true}).click();else await page.locator('#new-model-details > summary').click();
 await page.locator('#new-model').selectOption('fixture-model');
 if(width<=760)await page.keyboard.press('Escape');else await page.locator('#new-model-details > summary').click();
 async function config(){if(width<=760){await page.getByRole('button',{name:'新会话配置',exact:true}).click();}else await page.locator('#new-configuration-details > summary').click();}
 await config();await page.getByLabel('工作模式',{exact:true}).selectOption('plan');await page.getByLabel('执行审批',{exact:true}).selectOption('never');
 assert.deepEqual(await page.evaluate(()=>newDraft.settings),{model:'fixture-model',effort:'medium',collaborationMode:{mode:'plan',settings:{model:'fixture-model',reasoning_effort:'medium',developer_instructions:null}},approvalPolicy:'never'});
 await page.keyboard.press('Escape');
 assert.equal(await page.locator(width<=760?'#create-form .model-button':'#new-model-details > summary').innerText(),'Fixture Model Medium ⌄');
 const input=page.locator('#new-prompt > [contenteditable]');await input.click();await input.fill('configured first task');
 const regions=width<=760?['#new-attach-images','.new-configuration-trigger','#create-dialog .model-button','#submit-create']:['#new-attachment-details > summary','#new-configuration-details > summary','#new-model-details > summary','#submit-create'];
 const boxes=await page.evaluate(selectors=>selectors.map(selector=>{const r=document.querySelector(selector).getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom};}),regions);
 for(let i=0;i<boxes.length;i++){assert(boxes[i].x>=0&&boxes[i].right<=width);for(let j=i+1;j<boxes.length;j++)assert(boxes[i].right<=boxes[j].x||boxes[j].right<=boxes[i].x||boxes[i].bottom<=boxes[j].y||boxes[j].bottom<=boxes[i].y,'footer controls overlap');}

 if(width>=768){
  await input.focus();
  for(const selector of ['#new-attachment-details > summary','#new-configuration-details > summary','#new-model-details > summary','#submit-create']){await page.keyboard.press('Tab');assert(await page.locator(selector).evaluate(el=>el===document.activeElement),'keyboard order follows visible footer');}
 }
 await page.screenshot({path:'.runtime/creation-settings-'+width+'.png'});
 await page.evaluate(()=>{client.devices.find(d=>d.id===client.device).permissions=['view','create'];applyStatus({enabled:true,remoteControl:true,supportedCreationSettings:['model','effort','approvalPolicy','collaborationMode']});});
 assert(await page.locator('#submit-create').isDisabled());assert.equal(await input.innerText(),'configured first task');
 await page.evaluate(()=>{client.devices.find(d=>d.id===client.device).permissions=['view','create','edit'];applyStatus({enabled:true,remoteControl:true,supportedCreationSettings:['model','effort','approvalPolicy','collaborationMode']});});

 createState='interrupted';await page.locator('#submit-create').click();await page.waitForFunction(()=>!newDraft.pending);
 assert(await page.locator('#create-dialog').evaluate(el=>el.open),'interrupted creation without identity preserves the form');assert.equal(await input.innerText(),'configured first task');createState='uncertain';
 await page.locator('#submit-create').click();await page.waitForFunction(()=>!newDraft.pending);assert.equal(writes.at(-1).body.settings.approvalPolicy,'never');assert.equal(writes.at(-1).body.settings.collaborationMode.mode,'plan');
 assert.equal(await input.innerText(),'configured first task');const requestId=writes.at(-1).body.requestId;
 await page.locator('#submit-create').click();await page.waitForFunction(()=>!newDraft.pending);assert.equal(writes.at(-1).body.requestId,requestId,'unknown retry keeps original request identity');
 await page.locator('#close-dialog').click();await page.locator('#create').click();await page.waitForFunction(()=>createProjectsReady&&newModelChoices.length===2);await page.locator('#new-project').selectOption('p1');assert.equal(await input.innerText(),'configured first task');assert.equal(await page.evaluate(()=>newDraft.settings.approvalPolicy),'never');
 createDelay=250;createState='completed';await page.locator('#submit-create').click();await page.waitForFunction(()=>newDraft.pending);await page.locator('#close-dialog').click();await page.locator('#create').click();await page.waitForFunction(()=>createProjectsReady);await page.locator('#new-project').selectOption('p1');await page.waitForTimeout(350);
 assert(await page.locator('#create-dialog').evaluate(el=>el.open),'late completion cannot close reopened dialog');assert.equal(await input.innerText(),'configured first task','late completion cannot clear reopened draft');
 if(width===1280){const beforeResize=writes.length;await page.setViewportSize({width:390,height:844});await page.waitForFunction(()=>createProjectsReady&&document.querySelector('#create-dialog').matches(':modal'));assert.equal(await input.innerText(),'configured first task');assert.equal(await page.locator('#new-project').inputValue(),'p1');await page.setViewportSize({width,height:844});await page.waitForFunction(()=>createProjectsReady&&document.querySelector('#create-dialog').open&&!document.querySelector('#create-dialog').matches(':modal'));assert.equal(await input.innerText(),'configured first task');assert.equal(writes.length,beforeResize,'resize never submits');}
 if(width>=768){
  await page.locator('#notification-settings').click();await page.locator('#notification-dialog').waitFor();await page.keyboard.press('Escape');
  assert(await page.locator('#create-dialog').evaluate(el=>el.open),'Escape closes only the top modal, preserving creation pane');
  await page.locator('#show-all').click();await page.locator('#threads .thread').first().click();assert(!(await page.locator('#create-dialog').evaluate(el=>el.open)),'sidebar navigation closes nonmodal creation');
  await page.locator('#create').click();await page.waitForFunction(()=>createProjectsReady);assert.equal(await input.innerText(),'configured first task');assert.equal(await page.evaluate(()=>newDraft.settings.approvalPolicy),'never');
 }
 await page.evaluate(()=>{applyStatus({enabled:true,remoteControl:true,supportedCreationSettings:['model','effort']});});assert(await page.locator('#submit-create').isDisabled(),'withdrawn native settings block first turn');assert.equal(await page.evaluate(()=>newDraft.settings.approvalPolicy),'never');
 await page.evaluate(()=>{applyStatus({enabled:true,remoteControl:true,supportedCreationSettings:['model','effort','approvalPolicy','collaborationMode']});});await page.locator('#new-project').selectOption('p1');await input.fill('confirmed creation');createState='completed';createDelay=0;await page.locator('#submit-create').click();await page.waitForFunction(()=>selected==='native-created'&&!document.querySelector('#create-dialog').open);assert.equal(await page.evaluate(()=>newDraft.text),'');
 assert.deepEqual(errors,[]);await page.close();console.log('Creation settings '+width+' passed');
 }}finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
