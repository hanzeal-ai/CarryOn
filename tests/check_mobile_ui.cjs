const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch();const page=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
 const visualChecks=[];
 async function checkLayout(selectors){
  for(const selector of selectors){const box=await page.locator(selector).first().boundingBox();assert(box&&box.width>0&&box.height>0,selector+' visible');assert(box.x>=-1&&box.x+box.width<=page.viewportSize().width+1,selector+' fits viewport');visualChecks.push(selector);}
 }
 const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.log('PAGEERROR',e.stack)});let authenticated=true;
 const writes=[];const threads=[{id:'t1',title:'让手机上的对话更顺手',cwd:'/workspace/CarryOn',unread:true},{id:'t2',title:'检查远端连接',cwd:'/workspace/CarryOn',unread:false}];
 const projects=[{id:'p1',name:'CarryOn',cwd:'/workspace/CarryOn',total:12,waiting:1,running:2,unread:3,unknown:0},{id:'p2',name:'MarkFix',cwd:'/workspace/MarkFix',total:8,waiting:0,running:0,unread:1,unknown:0}];
 await page.addInitScript(()=>{window.CARRYON_CLOUD=true;});
 await page.route('**/console/**',async route=>{
  const req=route.request(),u=new URL(req.url());let data={},status=200;
  if(u.pathname.endsWith('/session')){if(!authenticated){status=401;data={error:'请先登录云端控制台'};}else data={devices:[{id:'mac',name:'我的 MacBook',online:true},{id:'other',name:'工作室 Mac',online:false}]};}
  else if(u.pathname.endsWith('/login'))authenticated=true;
  else if(u.pathname.endsWith('/logout'))authenticated=false;
  else if(u.pathname.endsWith('/link/pending'))data={requests:[]};
  else if(u.pathname.endsWith('/request')){
   const body=req.postDataJSON(),path=body.path.split('?')[0];if(body.method==='POST')writes.push(body);
   if(path==='/api/status')data={enabled:true,controllerId:'t2',remoteControl:true};
   else if(path==='/api/projects')data={projects,total:2,nextOffset:2};
   else if(path==='/api/threads'||path==='/api/projects/p1/threads')data={threads,total:2,nextOffset:2};
   else if(path==='/api/activity')data={threads:[threads[1]],total:1,nextOffset:1};
   else if(path==='/api/notifications')data={events:[],nextSequence:0};
   else if(path==='/api/notifications/preferences')data={preferences:{message:true,done:true,failed:true,approval:true,...body.body}};
   else if(path==='/api/standby')data={supported:true,effective:true,enabled:true};
  }else if(u.pathname.endsWith('/streams')&&req.method()==='POST')data={streamId:'s'};
  else if(u.pathname.includes('/streams/')&&req.method()==='GET'){await new Promise(r=>setTimeout(r,1000));data={revision:1};}
  await route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
 });
 await page.routeWebSocket('**/console/devices/*/ws', socket=>{
  let revision=0;
  socket.onMessage(raw=>{const selection=JSON.parse(raw);if(selection.type==='subscribe')socket.send(JSON.stringify({type:'update',revision:++revision,resubscribe:true,subscription:selection.subscription,body:{type:'update',subscription:selection.subscription,threadId:selection.threadId,status:{enabled:true,controllerId:'t2',remoteControl:true}}}));});
 });
 await page.goto((process.env.CARRYON_UI_URL||'http://127.0.0.1:8892/example.html'));
 await page.locator('#mobile-session-list .project-row').first().waitFor();
 await page.evaluate(async()=>receiveUpdate({status:{enabled:true,controllerId:'t2',remoteControl:true},subscription,threadId:selected},()=>true));
 await page.screenshot({path:'.runtime/mobile-projects.png'});await checkLayout(['.mobile-list-page .toolbar', '.search', '#mobile-session-list .project-row', '.bottom-nav']);
 await page.locator('#create').click();await page.locator('#new-prompt').fill('新建草稿');await page.screenshot({path:'.runtime/mobile-create.png'});await checkLayout(['#create-dialog .toolbar', '#create-dialog .group', '#create-dialog .production-composer', '#create-dialog .input-shell']);
 assert.equal(await page.locator('#create-dialog').evaluate(el=>Math.round(el.getBoundingClientRect().height)),844);
 await page.getByRole('button',{name:'控制会话',exact:true}).click();assert(await page.locator('#controller').isVisible());await page.locator('#mobile-controller button[aria-label="返回"]').click();await page.locator('#close-dialog').click();
 await page.locator('#mobile-session-list .project-row').first().click();await page.locator('.session').first().waitFor();await page.screenshot({path:'.runtime/mobile-sessions.png'});
 await page.locator('.session').first().click();
 await page.evaluate(async()=>{
  window.fixture={thread:{id:'t1'},runtime:{type:'active'},status:{state:'running',label:'进行中'},metadata:{latestModel:'gpt-6-astra'},controls:{activeTurnId:'turn1',settings:{model:'gpt-6-astra',effort:'medium'},requests:[]},queue:{messages:[],fingerprint:'q'},timeline:[{id:'u1',type:'userMessage',text:'重新设计手机端的会话体验，让它更简洁，也更容易使用。'},{id:'a1',type:'agentMessage',text:'我会围绕阅读和回复，重新整理这段体验。\n\n界面会更专注于内容：\n• 消息自然展开，执行细节按需查看\n• 主要操作留在拇指容易触达的位置\n• 需要确认时，再呈现完整上下文'}]};
  await receiveUpdate({status:{enabled:true,controllerId:'t2',remoteControl:true},subscription,threadId:selected,history:fixture,readSequence:2},()=>true);
 });
 await page.screenshot({path:'.runtime/mobile-chat.png'});await checkLayout(['.conversation-head', '#composer', '#composer .input-shell']);assert.equal(await page.locator('#send').getAttribute('data-mode'),'stop');
 for(const value of ['', '第一行\n第二行\n第三行', '短句']){
  await page.locator('#prompt').fill(value);await page.waitForTimeout(60);
  const layout=await page.evaluate(()=>{const shell=document.querySelector('#composer .input-shell'),a=document.querySelector('#attach-images').getBoundingClientRect(),b=document.querySelector('#composer .model-button').getBoundingClientRect();return {expanded:shell.classList.contains('expanded'),gap:b.x+b.width/2-a.x-a.width/2,focused:document.activeElement===document.querySelector('#prompt')};});
  assert.equal(layout.expanded,value.includes('\n'));assert.equal(layout.gap,32);assert(layout.focused,'reflow retains editor focus');
 }
 await page.locator('#prompt').fill('保留独立草稿');assert.equal(await page.locator('#send').getAttribute('data-mode'),'send');
 await page.getByRole('button',{name:'查看当前模型与思考强度',exact:true}).click();assert(await page.locator('#mobile-model').isVisible());assert.equal(await page.locator('#mobile-model select').first().inputValue(),'gpt-6-astra');await page.screenshot({path:'.runtime/mobile-model.png'});await checkLayout(['#mobile-model']);await page.keyboard.press('Escape');
 await page.getByRole('button',{name:'会话工具',exact:true}).click();await page.screenshot({path:'.runtime/mobile-tools.png'});
 assert((await page.getByRole('button',{name:'队列管理',exact:true}).boundingBox()).height>=44);await checkLayout(['#mobile-tools .sheet-top', '#mobile-tools .setting']);await page.locator('#mobile-tools button[aria-label="关闭"]').click();
 // Exercise the restored actions through the existing transport, against mocked API responses.
 await page.context().grantPermissions(['clipboard-read','clipboard-write']);
 for(const selector of ['.message.user','.message.assistant']){
  const message=page.locator(selector).first();await message.getByRole('button',{name:'复制原文',exact:true}).click();
  const expected=await message.locator('.text').textContent();
  await page.waitForFunction(async text=>(await navigator.clipboard.readText())===text,expected,{timeout:3000});
 }
 await page.evaluate(()=>{fixture.queue={fingerprint:'queue-v1',messages:[{id:'q1',text:'第一项',pausedReason:'等待恢复'},{id:'q2',text:'第二项'}]};Operations.render(fixture,selected,client,notice,true);});
 await page.getByRole('button',{name:'会话工具',exact:true}).click();await page.getByRole('button',{name:'队列管理',exact:true}).click();
 const queue=page.locator('#mobile-aux .mobile-queue');assert(await queue.isVisible());assert(!(await queue.getByRole('button',{name:'加入队列',exact:true}).isVisible()));
 await queue.getByLabel('第 1 条排队任务', {exact:true}).fill('修改后的排队任务');
 await page.evaluate(()=>{fixture.queue.fingerprint='queue-v2';Operations.render(fixture,selected,client,notice,true);});
 assert.equal(await queue.getByLabel('第 1 条排队任务',{exact:true}).inputValue(),'修改后的排队任务');
 async function queueAction(label,expected,confirm=false){
  const response=page.waitForResponse(r=>r.url().includes('/console/')&&r.url().endsWith('/request')&&r.request().postDataJSON()?.body?.action===expected.action);
  if(confirm)page.once('dialog',d=>d.accept());await queue.getByRole('button',{name:label,exact:true}).first().click();await response;
  const sent=writes.filter(w=>w.path==='/api/threads/t1/operations').at(-1).body;
  for(const [key,value]of Object.entries({...expected,queueFingerprint:'queue-v2'}))assert.deepEqual(sent[key],value);
 }
 await queueAction('保存内容',{action:'queue-edit',messageId:'q1',prompt:'修改后的排队任务'});
 await queueAction('下移',{action:'queue-reorder',messageIds:['q2','q1']});
 await queueAction('上移',{action:'queue-reorder',messageIds:['q2','q1']});
 await queueAction('恢复执行',{action:'queue-resume',messageId:'q1'});
 await queueAction('删除',{action:'queue-delete',messageId:'q1'},true);
 await queueAction('清空排队消息',{action:'clear-queue',confirmed:true},true);
 await page.screenshot({path:'.runtime/mobile-queue-management.png'});
 await page.evaluate(()=>Operations.render(fixture,selected,client,notice,false));
 assert(await queue.getByRole('button',{name:'保存内容',exact:true}).first().isDisabled());
 assert(await queue.getByLabel('第 1 条排队任务',{exact:true}).isDisabled());
 await page.evaluate(()=>Operations.render(fixture,selected,client,notice,true));
 await page.locator('#mobile-aux button[aria-label="返回"]').click();
 await page.getByRole('button',{name:'会话工具',exact:true}).click();await page.getByRole('button',{name:'队列管理',exact:true}).click();assert(await queue.isVisible());
 await page.evaluate(()=>{fixture.queue={fingerprint:'queue-empty',messages:[]};Operations.render(fixture,selected,client,notice,true);});
 assert(await queue.getByText('暂无排队任务').isVisible());await page.locator('#mobile-aux button[aria-label="返回"]').click();
 await page.getByRole('button',{name:'返回会话',exact:true}).click();assert(await page.locator('.session').first().isVisible());
 const readBefore=writes.filter(w=>w.path==='/api/notifications/read').length;
 await page.evaluate(async()=>receiveUpdate({status:{enabled:true,controllerId:'t2',remoteControl:true},subscription,threadId:selected,history:fixture,readSequence:3},()=>true));await page.waitForTimeout(100);assert.equal(writes.filter(w=>w.path==='/api/notifications/read').length,readBefore);
 await page.locator('.bottom-nav').getByRole('button',{name:'我的',exact:true}).click();await page.screenshot({path:'.runtime/mobile-settings.png'});await checkLayout(['.device-card', '.workspace-card-title', '.workspace-settings .setting', '.bottom-nav']);
 await page.getByRole('button',{name:'消息通知',exact:true}).click();await page.locator('#notification-preferences input').first().uncheck();await page.screenshot({path:'.runtime/mobile-notifications.png'});await page.locator('#notification-dialog button[aria-label="返回"]').click();
 await page.getByRole('button',{name:'切换工作区',exact:true}).click();await page.screenshot({path:'.runtime/mobile-workspaces.png'});await page.locator('#mobile-devices button[aria-label="关闭"]').click();
 await page.locator('.bottom-nav').getByRole('button',{name:'会话',exact:true}).click();await page.locator('#mobile-session-list .project-row').first().click();await page.locator('.session').first().click();assert.equal(await page.locator('#prompt').inputValue(),'保留独立草稿');
 await page.evaluate(()=>{fixture.controls.requests=[{id:'req1',fingerprint:'f1',action:'user-input',params:{questions:[{id:'q1',question:'请选择验证范围'}]}}];fixture.pendingRequests=[{id:'req1'}];Operations.render(fixture,selected,client,notice,true);});
 assert(await page.locator('#requests textarea').isVisible());assert(!(await page.locator('#question-dialog').isVisible()));await page.screenshot({path:'.runtime/mobile-question.png'});
 await page.setViewportSize({width:390,height:390});await page.waitForTimeout(100);assert(await page.locator('#send').evaluate(el=>el.getBoundingClientRect().bottom<=innerHeight));await page.setViewportSize({width:390,height:844});
 await page.evaluate(()=>{fixture.runtime={type:'idle'};fixture.status={state:'idle',label:'空闲'};fixture.controls.lastUserText='原有任务内容';fixture.controls.lastTurnId='last';fixture.controls.requests=[];fixture.timeline.push({id:'last:input',turnId:'last',type:'userMessage',text:'原有任务内容',data:{}});Timeline.render(fixture,document.getElementById('messages'));Operations.render(fixture,selected,client,notice,true);});
 await page.getByRole('button',{name:'会话工具',exact:true}).click();assert.equal(await page.getByText('编辑最后一轮',{exact:true}).count(),0);assert.equal(await page.getByText('压缩上下文',{exact:true}).count(),0);await page.locator('#mobile-tools').evaluate(el=>el.close());
 await page.locator('.message-editor summary').click();assert.equal(await page.locator('.message-editor textarea').inputValue(),'原有任务内容');await page.screenshot({path:'.runtime/mobile-edit.png'});await page.locator('.message-editor').getByRole('button',{name:'取消',exact:true}).click();
 await page.evaluate(()=>applyStatus({enabled:true,controllerId:'t2',remoteControl:false}));assert(await page.locator('#prompt').isDisabled());assert(await page.locator('#send').isDisabled());assert(await page.locator('#create').isDisabled());
 await page.setViewportSize({width:1440,height:1000});await page.waitForTimeout(100);assert(await page.locator('main>aside').isVisible());assert(await page.locator('.conversation').isVisible());assert(!(await page.locator('.bottom-nav').isVisible()));await page.screenshot({path:'.runtime/mobile-desktop-regression.png'});
 await page.setViewportSize({width:320,height:640});await page.waitForTimeout(100);await page.evaluate(()=>MobileUI.show('projects'));assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 await page.locator('.bottom-nav').getByRole('button',{name:'我的',exact:true}).click();page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'退出登录',exact:true}).click();await page.locator('#pairing').waitFor();await page.setViewportSize({width:390,height:844});await page.screenshot({path:'.runtime/mobile-login.png'});assert(!(await page.locator('.bottom-nav').isVisible()));await checkLayout(['.login-symbol', '#token', '#pair']);
 await page.setViewportSize({width:1280,height:900});await page.goto((process.env.CARRYON_UI_URL||'http://127.0.0.1:8892/example.html')+'?mobile=1');await page.waitForFunction(()=>document.body.classList.contains('mobile-ready'));assert.equal(await page.locator('#mobile-shell').evaluate(el=>el.getBoundingClientRect().width),430);
 await page.evaluate(()=>{fixture={thread:{id:'t1'},runtime:{type:'active'},status:{state:'waiting'},controls:{settings:{},requests:[{id:'preview-question',fingerprint:'preview-fingerprint',action:'user-input',params:{questions:[{id:'q1',question:'移动预览问题'}]}}]},pendingRequests:[{id:'preview-question'}],queue:{messages:[]}};Operations.render(fixture,'t1',client,notice,true);});
 assert.equal(await page.locator('#requests textarea').count(),1);assert(!(await page.locator('#question-dialog').isVisible()));
 const local=await browser.newPage({viewport:{width:390,height:844}});local.on('pageerror',e=>errors.push(e.message));
 await local.addInitScript(()=>sessionStorage.setItem('carryon-token','mock-local-token'));
 await local.routeWebSocket('**/api/stream',()=>{});
 await local.route('**/api/**',route=>{const path=new URL(route.request().url()).pathname;let data={};
  if(path==='/api/status')data={enabled:true,controllerId:'t2'};
  else if(path==='/api/projects')data={projects,total:2,nextOffset:2};
  else if(path==='/api/threads')data={threads,total:2,nextOffset:2};
  else if(path==='/api/standby')data={supported:true,enabled:false};
  else if(path==='/api/notifications')data={events:[],nextSequence:0};
  return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
 });
 await local.goto(process.env.CARRYON_UI_URL||'http://127.0.0.1:8892/example.html');
 await local.locator('#mobile-session-list .project-row').first().waitFor();
 await local.locator('.bottom-nav').getByRole('button',{name:'我的',exact:true}).click();
 assert(!(await local.locator('.cloud-settings').isVisible()));assert(!(await local.locator('#bridge').isVisible()));assert.equal(await local.locator('.workspace-settings').getByText('本机设置',{exact:true}).count(),0);
 await local.screenshot({path:'.runtime/mobile-local-settings.png'});
 await local.setViewportSize({width:1440,height:1000});
 // Local service management lives in CLI/desktop; the Web header retains its status.
 await local.locator('body>header #bridge').waitFor({state:'visible'});
 assert(await local.locator('body>header #bridge').isVisible());
 await local.setViewportSize({width:390,height:844});await local.locator('#bridge').waitFor({state:'hidden'});
 await local.close();
 assert.deepEqual(errors,[]);console.log('Checked responsive geometry:',visualChecks.length);console.log('PASS design components: navigation, full screen create and inline edit, chat, popover, settings, requests, draft/read gates, desktop restoration, queue management, message clipboard, local status placement and narrow/short viewports. API responses mocked.');await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
