const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch();
 try { for(const width of [1280,390]){
 const page=await browser.newPage({viewport:{width,height:844}});
 const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.log('PAGEERROR',e.stack)});let authenticated=true;
 const writes=[],reads=[],bindingCalls=[];let historyReply=null,failOperation=false,forkState='uncertain',forkDelay=0,composeDelay=0,composeState='accepted',operationDelay=0;
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
   if(body.method==='POST'&&path.endsWith('/fork')){if(forkDelay)await new Promise(resolve=>setTimeout(resolve,forkDelay));data={id:body.body.requestId,state:forkState,...(forkState==='completed'?{createdThreadId:'forked'}:{error:'fixture uncertain'})};}
   else if(body.method==='POST'&&path.endsWith('/compose')){if(composeDelay)await new Promise(resolve=>setTimeout(resolve,composeDelay));data={id:body.body.requestId,state:composeState};}
   else if(body.method==='POST'&&path.endsWith('/operations')){if(operationDelay)await new Promise(r=>setTimeout(r,operationDelay));data={id:body.body.requestId,state:typeof failOperation==='string'?failOperation:failOperation?'failed':'completed',error:failOperation?'fixture failure':undefined,...(body.body.action==='review'&&!failOperation?{reviewThreadId:path.split('/')[3],turnId:'review-turn'}:{}),...(['goal-set','goal-pause','goal-clear'].includes(body.body.action)&&!failOperation?{result:body.body.action==='goal-clear'?{cleared:true}:{goal:{threadId:path.split('/')[3],status:body.body.action==='goal-pause'?'paused':body.body.status||'active'}}}:{})};
   }
   else if(path==='/api/status')data={enabled:true,remoteControl:true};
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
  socket.onMessage(raw=>{const selection=JSON.parse(raw);if(selection.type==='subscribe')socket.send(JSON.stringify({type:'update',revision:++revision,resubscribe:true,subscription:selection.subscription,body:{type:'update',subscription:selection.subscription,threadId:selection.threadId,status:{enabled:true,remoteControl:true}}}));});
 });

 await page.goto('http://127.0.0.1:8923/example.html');
 await page.waitForFunction(()=>typeof Timeline!=='undefined'&&enabled);



 await page.evaluate(async()=>{
  await selectThread('t1');window.commandHistory={thread:{id:'t1'},historyRevision:'commands',status:{state:'idle'},runtime:{type:'idle'},access:{nativeReady:true,canInteract:true},metadata:{},controls:{supportedOperations:['settings','compact','review','goal-set','fork'],supportsGoal:true,supportedSettings:['model','effort','collaborationMode'],settings:{model:'fixture-model',effort:'high'},requests:[]},queue:{messages:[]},timeline:[]};
  await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:commandHistory},()=>true);
 });
 const input=page.locator('#prompt > [contenteditable]');
 async function submit(text){await input.fill(text);await page.locator('#send').click();}
 await input.fill('/');const commandMenu=page.getByRole('listbox',{name:'会话命令'});
 const optionNames=await commandMenu.getByRole('option').allTextContents();assert(optionNames.length>=3);
 await input.press('ArrowDown');assert.equal(await commandMenu.locator('[aria-selected="true"]').innerText(),optionNames[1]);
 await input.press('ArrowUp');assert.equal(await commandMenu.locator('[aria-selected="true"]').innerText(),optionNames[0]);
 await input.press('ArrowUp');assert.equal(await commandMenu.locator('[aria-selected="true"]').innerText(),optionNames.at(-1));
 await input.press('Escape');assert(await commandMenu.isHidden());assert.equal(await input.innerText(),'/');
 await input.fill('/co');const beforeIME=writes.length;
 await input.dispatchEvent('keydown',{key:'Enter',isComposing:true,bubbles:true});await page.waitForTimeout(30);assert.equal(writes.length,beforeIME);assert.equal(await input.innerText(),'/co');
 await input.press('Shift+Enter');assert((await page.locator('#prompt').evaluate(el=>el.value)).includes('\n'));assert.equal(writes.length,beforeIME);
 await input.fill('/co');await input.press('Enter');await page.waitForFunction(()=>!document.querySelector('#prompt').value);assert.equal(writes.at(-1).body.action,'compact');
 const afterKeyboard=writes.length;
 await submit('/unknown');await page.waitForTimeout(50);assert.equal(writes.length,afterKeyboard);assert.equal(await input.innerText(),'/unknown');
 await input.fill('/co');await page.locator('.composer-command-menu').getByRole('option',{name:'/compact · 压缩上下文',exact:true}).waitFor();await page.screenshot({path:'.runtime/composer-commands-'+width+'.png'});await page.locator('.composer-command-menu').getByRole('option',{name:'/compact · 压缩上下文',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('#prompt').value);assert.equal(writes.at(-1).body.action,'compact');
 await submit('/plan');await page.waitForFunction(()=>!document.querySelector('#prompt').value);assert.equal(writes.at(-1).body.settings.collaborationMode.mode,'plan');
 await page.evaluate(()=>{commandHistory.controls.settings.collaborationMode={mode:'plan',settings:{model:'fixture-model',reasoning_effort:'high',developer_instructions:'keep'}};updateCompose(commandHistory);});
 const beforeToggle=writes.length;await submit('/plan');await page.waitForFunction(()=>!document.querySelector('#prompt').value);
 assert.equal(writes.length,beforeToggle+1,'bare plan toggles settings without starting a turn');
 assert.deepEqual(writes.at(-1).body.settings.collaborationMode,{mode:'default',settings:{model:'fixture-model',reasoning_effort:'high',developer_instructions:'keep'}});
 await submit('/plan explain the change');await page.waitForTimeout(150);assert(writes.some(w=>w.path.endsWith('/compose')&&w.body.prompt==='explain the change'),'plan argument is submitted after settings confirmation');
 await submit('/plan /fork');await page.waitForTimeout(150);assert(writes.some(w=>w.path.endsWith('/compose')&&w.body.prompt==='/fork'),'plan body beginning slash is literal text');
 await submit('/review check edge cases');await page.getByLabel('审查要求',{exact:true}).waitFor();assert.equal(await page.getByLabel('审查要求',{exact:true}).inputValue(),'check edge cases');
 if(width===390)await page.locator('#mobile-aux button[aria-label="返回"]').click();else await page.locator('.session-actions>summary').click();
 await submit('/goal improve reliability');await page.waitForFunction(()=>!document.querySelector('#prompt').value);assert.equal(writes.at(-1).body.action,'goal-set');assert.equal(writes.at(-1).body.objective,'improve reliability');
 operationDelay=250;await submit('/compact');await input.fill('new draft while pending');await page.waitForTimeout(320);assert.equal(await input.innerText(),'new draft while pending');operationDelay=0;
 const before=writes.length;await page.evaluate(()=>{commandHistory.controls.supportedOperations=[];updateCompose(commandHistory);});await submit('/compact');await page.waitForTimeout(50);assert.equal(writes.length,before);assert.equal(await input.innerText(),'/compact');
 await page.evaluate(()=>{commandHistory.controls.supportedOperations=['settings','compact','review','goal-set','fork'];client.devices.find(d=>d.id===client.device).permissions=['view','send'];updateCompose(commandHistory);});await submit('/plan');await page.waitForTimeout(50);assert.equal(writes.length,before);
 await page.evaluate(()=>{client.devices.find(d=>d.id===client.device).permissions=['view','edit'];updateCompose(commandHistory);});
 const editStart=writes.length;await submit('/plan');await page.waitForFunction(()=>!document.querySelector('#prompt').value);assert.equal(writes.length,editStart+1);
 await input.fill('ordinary message without send permission');assert(await page.locator('#send').isDisabled(),'ordinary send must be disabled for edit-only workspace');
 await input.fill('/plan forbidden body');await input.press('Control+Enter');await page.waitForTimeout(50);assert.equal(writes.length,editStart+1);assert.equal(await input.innerText(),'/plan forbidden body');
 await page.evaluate(()=>{commandHistory.status={state:'running'};commandHistory.runtime={type:'active'};commandHistory.controls.canSteer=false;updateCompose(commandHistory);});
 for(const command of ['/model','/plan','/status']){await input.fill(command);assert(await page.locator('#send').isEnabled(),command+' remains available while steering is unavailable');}
 await submit('/plan');await page.waitForFunction(()=>!document.querySelector('#prompt').value);assert.equal(writes.at(-1).body.action,'settings');
 await submit('/model');const modelPanel=width===390?page.locator('#mobile-model'):page.locator('.composer-settings-dialog');await modelPanel.getByLabel('模型',{exact:true}).waitFor();await page.keyboard.press('Escape');
 await submit('/status');if(width===390){await page.locator('#mobile-aux').waitFor();await page.locator('#mobile-aux button[aria-label="返回"]').click();}else await page.locator('#conversation-info').waitFor();
 await page.evaluate(()=>{commandHistory.status={state:'idle'};commandHistory.runtime={type:'idle'};updateCompose(commandHistory);});
 // Local review drafts use existing native text delivery, including queue and uncertain receipts.
 await page.evaluate(()=>{
  client.devices.find(d=>d.id===client.device).permissions=['view','send','edit'];
  commandHistory.controls.supportedOperations.push('queue-add');updateCompose(commandHistory);
  window.fixtureComment=text=>ReviewComments.create({sourceId:'native-change',path:'src/test.js',patch:'@@ -1 +1 @@\n-old\n+new',row:DiffReview.lines('@@ -1 +1 @@\n-old\n+new')[2],text});
  window.putComments=(...texts)=>{reviewComments=texts.map(fixtureComment);renderReviewComments();updateComposeButton();};
  $('prompt').setDocument('',[],0,conversationKey(selected));selectedSkills=[];attachedImages=[];putComments('仅评论');
 });
 const commentStart=writes.length;await page.locator('#send').click();await page.waitForFunction(()=>reviewComments.length===0&&!imageBusy);
 assert.equal(writes.length,commentStart+1);assert.equal(writes.at(-1).body.prompt,'关于已加载改动 src/test.js（R1）：\n+new\n仅评论');assert.deepEqual(writes.at(-1).body.images||[],[]);assert(!JSON.stringify(writes.at(-1).body).includes('native-change'));
 await page.evaluate(()=>{commandHistory.status={state:'running'};commandHistory.runtime={type:'active'};commandHistory.controls.canSteer=false;commandHistory.queue={fingerprint:'queue-fixture',messages:[]};putComments('队列评论');});
 assert((await page.locator('#send').getAttribute('aria-label')).includes('加入队列'));await page.locator('#send').click();await page.waitForFunction(()=>reviewComments.length===0&&!imageBusy);
 assert.equal(writes.at(-1).body.action,'queue-add');assert(writes.at(-1).body.prompt.endsWith('队列评论'));assert.equal(writes.at(-1).body.queueFingerprint,'queue-fixture');
 await page.evaluate(()=>{commandHistory.status={state:'idle'};commandHistory.runtime={type:'idle'};putComments('未知评论');});composeState='uncertain';
 await page.locator('#send').click();await page.waitForFunction(()=>!imageBusy);assert.equal(await page.evaluate(()=>reviewComments[0].text),'未知评论');
 const unknownWrite=writes.at(-1),unknownCount=writes.length;await page.waitForTimeout(80);assert.equal(writes.length,unknownCount,'uncertain comment does not replay automatically');
 await page.getByRole('button',{name:'核对发送结果',exact:true}).last().click();await page.waitForTimeout(80);assert.equal(writes.length,unknownCount);assert(reads.some(path=>path.endsWith('/'+unknownWrite.body.requestId)));
 composeState='accepted';composeDelay=300;await page.evaluate(()=>putComments('等待评论'));const waitingStart=writes.length;await page.locator('#send').click();await page.waitForFunction(n=>imageBusy&&reviewComments[0].text==='等待评论',waitingStart);
 await page.evaluate(()=>{reviewComments[0]={...reviewComments[0],text:'等待期间修改'};reviewComments.push(fixtureComment('等待期间新增'));renderReviewComments();});
 await page.waitForFunction(()=>!imageBusy);assert.deepEqual(await page.evaluate(()=>reviewComments.map(c=>c.text)),['等待期间修改','等待期间新增']);assert.equal(writes.length,waitingStart+1);composeDelay=0;
 await input.fill('/plan');const blockedCommentCommand=writes.length;await input.press('Control+Enter');await page.waitForTimeout(50);assert.equal(writes.length,blockedCommentCommand,'comments cannot silently attach to commands');
 await page.evaluate(()=>{reviewComments=[];renderReviewComments();updateComposeButton();});
 await page.evaluate(()=>{client.devices.find(d=>d.id===client.device).permissions=['view','create'];updateCompose(commandHistory);});forkState='completed';await submit('/fork');await page.waitForFunction(()=>selected==='forked');assert.equal(await page.evaluate(()=>imageBusy),false);
 assert(!writes.some(w=>w.path.endsWith('/compose')&&w.body.prompt?.startsWith('/')&&w.body.prompt!=='/fork'),'slash commands never become model messages');
 assert.deepEqual(errors,[]);await page.close();
 }
 console.log('PASS actual command routing desktop/mobile');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
