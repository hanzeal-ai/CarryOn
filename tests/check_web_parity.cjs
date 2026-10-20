const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch();
 try { for(const width of [1280,390]){
 const page=await browser.newPage({viewport:{width,height:844}});
 const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.log('PAGEERROR',e.stack)});let authenticated=true;
 const writes=[],reads=[],bindingCalls=[];let historyReply=null;
 const defaultHistory={thread:{id:'t1'},historyRevision:'initial',runtime:{type:'idle'},status:{state:'idle'},metadata:{},timeline:[]};const threads=[{id:'t1',title:'让手机上的对话更顺手',cwd:'/workspace/CarryOn',unread:true},{id:'t2',title:'检查远端连接',cwd:'/workspace/CarryOn',unread:false}];
 let allThreads=threads;
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
  socket.onMessage(raw=>{const selection=JSON.parse(raw);if(selection.type==='subscribe')socket.send(JSON.stringify({type:'update',revision:++revision,resubscribe:true,subscription:selection.subscription,body:{type:'update',subscription:selection.subscription,threadId:selection.threadId,status:{enabled:true,remoteControl:true,supportsCreationReferences:true}}}));});
 });

 await page.goto('http://127.0.0.1:8923/example.html');
 await page.waitForFunction(()=>typeof Timeline!=='undefined'&&enabled);

 await page.locator('#create').click();
 await page.locator('#new-project').selectOption('p2');
 await page.locator('#new-prompt > [contenteditable]').fill('project creation fixture');
 await page.locator('#new-image-files').setInputFiles({name:'fixture.png',mimeType:'image/png',buffer:Buffer.from(await page.evaluate(()=>{const canvas=document.createElement('canvas');canvas.width=canvas.height=16;canvas.getContext('2d').fillRect(0,0,16,16);return canvas.toDataURL('image/png').split(',')[1];}),'base64')});
 await page.locator('#new-image-previews img').waitFor();
 if(width===390)await page.locator('#create-dialog').getByRole('button',{name:'模型与思考强度',exact:true}).click();else await page.locator('#new-model-details > summary').click();
 await page.locator('#new-model').selectOption('fixture-model');await page.locator('#new-effort').selectOption('high');
 await page.screenshot({path:'.runtime/web-parity-new-model-'+width+'.png'});
 if(width===390){await page.keyboard.press('Escape');
  assert((await page.locator('#create-dialog .model-button').textContent()).includes('Fixture Model High'));
  assert(await page.evaluate(()=>{const p=document.querySelector('#new-image-previews').getBoundingClientRect(),i=document.querySelector('#new-prompt').getBoundingClientRect();return p.bottom<=i.top;}),'images stay above new task input');
  assert(!(await page.locator('#create-dialog .production-composer').textContent()).includes('null'));
 }
 await page.screenshot({path:'.runtime/web-parity-new-image-'+width+'.png'});
 // Exercise actual scoped draft restoration without writing either workspace.
 await page.locator('#close-dialog').click();
 await page.evaluate(()=>{client.device='other';client.setStorage();});await page.locator('#create').click();
 assert.equal(await page.locator('#new-prompt').evaluate(el=>el.value),'');assert.equal(await page.locator('#new-image-previews img').count(),0);
 await page.locator('#new-prompt > [contenteditable]').fill('other workspace draft');await page.locator('#close-dialog').click();
 await page.evaluate(()=>{client.device='mac';client.setStorage();});await page.locator('#create').click();
 await page.locator('#new-project').selectOption('p2');
 assert.equal(await page.locator('#new-prompt').evaluate(el=>el.value),'project creation fixture');assert.equal(await page.locator('#new-image-previews img').count(),1);

 if(width===390){
  const png=Buffer.from(await page.evaluate(()=>{const c=document.createElement('canvas');c.width=c.height=16;c.getContext('2d').fillRect(0,0,16,16);return c.toDataURL('image/png').split(',')[1];}),'base64');
  await page.locator('#new-image-files').setInputFiles([{name:'second.png',mimeType:'image/png',buffer:png},{name:'third.png',mimeType:'image/png',buffer:png}]);
  await page.waitForFunction(()=>document.querySelectorAll('#new-image-previews img').length===3);
  assert(await page.locator('#new-attach-images').isEnabled(),'three photos must not disable access to skills/apps');
  await page.locator('#new-attach-images').click();
  assert(await page.locator('.mobile-attachment-menu:popover-open').getByRole('button',{name:'添加图片',exact:true}).isDisabled());
 }
 if(width>760)await page.locator('#new-attachment-details > summary').click();
 await page.locator('#new-attach-skills').click();
 const newSkills=page.getByRole('dialog',{name:'技能',exact:true});await newSkills.getByRole('button',{name:'review',exact:true}).click();await newSkills.getByRole('button',{name:'完成',exact:true}).click();
 if(width===390)await page.locator('#new-attach-images').click();else await page.locator('#new-attachment-details > summary').click();
 await page.locator('#new-attach-mentions').click();
 const newApps=page.getByRole('dialog',{name:'应用与插件',exact:true});await newApps.getByRole('button',{name:'Fixture App',exact:true}).click();await newApps.getByRole('button',{name:'完成',exact:true}).click();
 assert.equal(await page.locator('#new-prompt .inline-reference').count(),2);
 const beforeRevocation=writes.length;await page.evaluate(()=>{supportsCreationReferences=false;});await page.locator('#submit-create').click();
 assert.equal(writes.length,beforeRevocation);assert.equal(await page.locator('#new-prompt .inline-reference').count(),2);assert((await page.locator('#create-error').innerText()).includes('暂不支持引用'));
 await page.evaluate(()=>{supportsCreationReferences=true;});await page.locator('#submit-create').click();
 await page.waitForFunction(()=>!document.querySelector('#create-dialog').open);
 const created=writes.find(w=>w.path==='/api/threads').body;assert.equal(created.projectId,'p2');assert.equal(created.prompt,'project creation fixture');assert.deepEqual(created.skills,[{name:'review',path:'/skills/review/SKILL.md'}]);assert.deepEqual(created.mentions,[{name:'Fixture App',path:'app://fixture'}]);assert(created.images[0].startsWith('data:image/jpeg;base64,'));assert.deepEqual(created.settings,{model:'fixture-model',effort:'high'});
 assert(reads.some(path=>path.includes('/projects?')&&path.includes('availableOnly=true')));
 if(width===390){await page.getByRole('button',{name:'返回会话',exact:true}).click();await page.getByRole('button',{name:'我的',exact:true}).click();}
 else await page.locator('#account-menu > summary').click();
 await page.screenshot({path:'.runtime/web-parity-settings-'+width+'.png'});
 await page.locator('#show-inactive').check();
 if(width!==390)await page.locator('#account-menu > summary').click();
 await page.waitForFunction(()=>showInactive&&listLoadState.phase==='idle');
 assert(reads.some(path=>path.includes('availableOnly=false')));
 allThreads=Array.from({length:130},(_,i)=>({id:'page-'+i,title:'分页会话 '+i,cwd:'/workspace/CarryOn',status:{state:'idle'}}));
 if(width===390){await page.getByRole('button',{name:'会话',exact:true}).click();await page.getByRole('button',{name:'会话',exact:true}).click();}
 else await page.locator('#show-all').click();
 await page.waitForFunction(()=>workspaceView==='all'&&listLoadState.phase==='idle');
 await page.locator('#more').click();await page.waitForFunction(()=>threads.length===130&&listLoadState.phase==='idle');
 await page.evaluate(()=>{listViewport().scrollTop=400;});const listPosition=await page.evaluate(()=>listViewport().scrollTop);
 await page.evaluate(()=>selectThread('page-70'));
 if(width===390)await page.getByRole('button',{name:'返回会话',exact:true}).click();
 await page.waitForFunction(()=>listViewport().scrollTop>0);
 assert(Math.abs(await page.evaluate(()=>listViewport().scrollTop)-listPosition)<2);
 await page.evaluate(()=>loadThreads());assert.equal(await page.evaluate(()=>threads.length),130,'refresh preserves loaded pagination window');
 if(width!==390)await page.locator('#toggle-search').click();
 await page.locator('#project-filter').selectOption('unread');
 await page.waitForFunction(()=>listLoadState.phase==='idle');
 assert(reads.some(path=>path.includes('/workspace/threads?')&&path.includes('filter=unread')));
 if(width===390)await page.getByRole('button',{name:'动态',exact:true}).click();else await page.locator('#show-activity').click();
 await page.waitForFunction(()=>workspaceView==='activity'&&listLoadState.phase==='idle');
 assert(reads.some(path=>path.includes('/activity?')&&path.includes('includeRead=true')));
 await page.locator('#clear-read').click();
 assert(writes.some(w=>w.path==='/api/notifications/clear-read'));
 await page.evaluate(async()=>{
  await selectThread('t1');
  window.parityHistory={thread:{id:'t1'},historyRevision:'parity1',source:'local-rollout',access:{nativeReady:false,canInteract:false},status:{state:'notLoaded',label:'未加载'},runtime:{type:'notLoaded'},timeline:Array.from({length:45},(_,i)=>({id:'m'+i,type:i%2?'agentMessage':'userMessage',text:'message '+i+' '+('历史阅读内容 '.repeat(40))}))};
  await receiveUpdate({status:{enabled:true,remoteControl:true,supportsCreationReferences:true},subscription,threadId:selected,history:parityHistory},()=>true);
  Timeline.navigateTo('m20');
 });
 await page.screenshot({path:'.runtime/web-parity-history-'+width+'.png'});
 assert(await page.locator('#send').isDisabled());
 assert(await page.locator('#history-source').isVisible());
 assert((await page.locator('#history-source').textContent()).includes('桌面 Codex'));
 const position=await page.locator('[data-navigation-id="m20"]').evaluate(n=>n.getBoundingClientRect().y);
 await page.evaluate(async()=>{const history={...parityHistory,historyRevision:'parity2',timeline:parityHistory.timeline.map(i=>i.id==='m0'?{...i,text:i.text.repeat(4)}:i).concat({id:'new',type:'agentMessage',text:'new message'})};await receiveUpdate({status:{enabled:true,remoteControl:true,supportsCreationReferences:true},subscription,threadId:selected,history},()=>true);});
 assert(Math.abs(await page.locator('[data-navigation-id="m20"]').evaluate(n=>n.getBoundingClientRect().y)-position)<2,'old reading anchor stays fixed');
 assert.equal(await page.locator('#messages').getAttribute('data-new-messages'),'true');
 if(width===390)await page.getByRole('button',{name:'有新消息，回到最新',exact:true}).click();else await page.locator('#jump-latest').click();
 await page.waitForFunction(()=>{const v=document.querySelector('#messages').closest('.mobile-chat-scroll')||document.querySelector('#messages');return v.scrollHeight-v.scrollTop-v.clientHeight<100;});
 const highlightedSource='public enum Conversation {\n    case ready = "你好👋"\n}';
 await page.evaluate(async source=>{await receiveUpdate({status:{enabled:true,remoteControl:true,supportsCreationReferences:true},subscription,threadId:selected,history:{...parityHistory,historyRevision:'code-highlight',timeline:[{id:'highlight-code',type:'agentMessage',text:'代码示例\n\n```swift\n'+source+'\n```'}]}},()=>true);},highlightedSource);
 await page.locator('#messages .hljs-keyword').first().waitFor();
 assert.equal(await page.locator('#messages pre code').textContent(),highlightedSource);
 const codeLayout=await page.locator('#messages .markdown-code').evaluate(node=>{const header=node.querySelector('.markdown-code-header'),pre=node.querySelector('pre'),button=header.querySelector('button');return {header:getComputedStyle(header).display,border:getComputedStyle(node).borderTopWidth,padding:getComputedStyle(pre).paddingLeft,buttonHeight:button.getBoundingClientRect().height,overflow:node.scrollWidth-node.clientWidth};});
 assert.equal(codeLayout.header,'flex');assert.equal(codeLayout.border,'1px');assert.equal(codeLayout.padding,'16px');assert(codeLayout.buttonHeight>=(width===390?44:32));assert(codeLayout.overflow<=1);

 await page.screenshot({path:'.runtime/web-parity-code-highlight-'+width+'.png'});
 await page.evaluate(async()=>{await receiveUpdate({status:{enabled:true,remoteControl:true,supportsCreationReferences:true},subscription,threadId:selected,history:{...parityHistory,historyRevision:'changes',timeline:[{id:'f',type:'fileChange',data:{changes:[{path:'src/test.js',diff:'@@ -1 +1 @@\n-old\n+new '+('long diff line '.repeat(30))}]}},{id:'d',type:'turnDiff',data:{diff:'whole diff'}}]}},()=>true);});
 if(width===390){await page.getByRole('button',{name:'会话工具',exact:true}).click();await page.getByRole('button',{name:'查看改动',exact:true}).click();}else {await page.locator('.conversation-more > summary').click();await page.locator('#view-changes').click();}
 await page.locator('#changes-content summary').first().click();await page.locator('#changes-content summary').last().click();
assert((await page.locator('#changes-content').textContent()).includes('src/test.js'));
 await page.locator('#changes-content .diff-text').filter({hasText:'whole diff'}).waitFor();
 const diffTable=page.locator('#changes-content .diff-lines').first(),addedLine=diffTable.locator('.diff-line.added');
 const beforeWrap=await addedLine.evaluate(n=>n.getBoundingClientRect().height);
 await page.getByRole('button',{name:'自动换行',exact:true}).click();
 assert.equal(await page.locator('#changes-wrap').getAttribute('aria-pressed'),'true');
 const wrapped=await diffTable.evaluate(n=>({overflow:n.scrollWidth-n.clientWidth,height:n.querySelector('.diff-line.added').getBoundingClientRect().height,text:n.querySelector('.diff-line.added .diff-text').textContent}));
 assert(wrapped.overflow<=1,'wrapped diff must fit the reading pane: '+JSON.stringify(wrapped));assert(wrapped.height>beforeWrap+20,'long source line must wrap');
 assert(wrapped.text.startsWith('+new long diff line '));
 await page.screenshot({path:'.runtime/web-parity-diff-wrap-'+width+'.png'});
 await page.getByRole('button',{name:'自动换行',exact:true}).click();assert.equal(await page.locator('#changes-wrap').getAttribute('aria-pressed'),'false');
 assert.equal(await addedLine.evaluate(n=>n.getBoundingClientRect().height),beforeWrap);
 await page.getByRole('button',{name:'评论 src/test.js R1',exact:true}).click();
 await page.locator('.diff-comment textarea').fill('请解释这行变更');
 const beforeComment=writes.length;
 await page.screenshot({path:'.runtime/web-parity-diff-comment-'+width+'.png'});
 const beforeDraft=await page.locator('#prompt').evaluate(el=>el.value);
 await page.evaluate(()=>{client.device='other';client.setStorage();});
 await page.getByRole('button',{name:'添加评论',exact:true}).click();
 assert.equal(await page.locator('#prompt').evaluate(el=>el.value),beforeDraft,'old review cannot write another workspace');
 assert((await page.locator('.diff-comment [role=status]').textContent()).includes('已改变'));
 await page.evaluate(()=>{client.device='mac';client.setStorage();selected='t2';});
 await page.getByRole('button',{name:'添加评论',exact:true}).click();
 assert.equal(await page.locator('#prompt').evaluate(el=>el.value),beforeDraft,'old review cannot write another thread');
 await page.evaluate(()=>{selected='t1';});
 await page.getByRole('button',{name:'添加评论',exact:true}).click();
 assert.equal(await page.locator('#prompt').evaluate(el=>el.value),beforeDraft,'local card does not rewrite input');
 assert.equal(await page.evaluate(()=>reviewComments.length),1);
 assert.equal(await page.locator('#changes-content .diff-comment-card').count(),1);
 assert(await page.locator('#changes-dialog').evaluate(el=>el.open),'adding a card keeps file review open');
 await page.locator('.diff-comment-card').getByRole('button',{name:'编辑',exact:true}).click();
 await page.getByRole('textbox',{name:'编辑评论',exact:true}).fill('编辑后的评论');
 await page.locator('.diff-comment-card').getByRole('button',{name:'保存',exact:true}).click();
 assert.equal(await page.evaluate(()=>reviewComments[0].text),'编辑后的评论');
 await page.screenshot({path:'.runtime/web-parity-local-comment-card-'+width+'.png'});
 // Editing A survives a change to B in both the inline and pending-comment views.
 await page.locator('.diff-comment-card').getByRole('button',{name:'编辑',exact:true}).click();
 await page.getByRole('textbox',{name:'编辑评论',exact:true}).fill('尚未保存的 A');
 await page.getByRole('button',{name:'评论 src/test.js R1',exact:true}).click();
 await page.locator('.diff-comment textarea').fill('B');await page.getByRole('button',{name:'添加评论',exact:true}).click();
 assert.equal(await page.getByRole('textbox',{name:'编辑评论',exact:true}).inputValue(),'尚未保存的 A');
 await page.locator('.diff-comment-card').filter({hasText:'B'}).getByRole('button',{name:'删除',exact:true}).click();
 assert.equal(await page.getByRole('textbox',{name:'编辑评论',exact:true}).inputValue(),'尚未保存的 A');
 await page.locator('.diff-comment-card').getByRole('button',{name:'保存',exact:true}).click();
 await page.getByRole('button',{name:'评论 src/test.js R1',exact:true}).click();
 await page.locator('.diff-comment textarea').fill('B');await page.getByRole('button',{name:'添加评论',exact:true}).click();
 await page.locator('#changes-close').click();await page.locator('#review-comment-drafts').click();
 const overview=page.locator('#review-comments-dialog');await overview.locator('.diff-comment-card').first().getByRole('button',{name:'编辑',exact:true}).click();
 await overview.getByRole('textbox',{name:'编辑评论',exact:true}).fill('总览未保存 A');
 await overview.locator('.diff-comment-card').filter({hasText:'B'}).getByRole('button',{name:'删除',exact:true}).click();
 assert.equal(await overview.getByRole('textbox',{name:'编辑评论',exact:true}).inputValue(),'总览未保存 A');
 await overview.getByRole('button',{name:'保存',exact:true}).click();await page.locator('#review-comments-close').click();
 if(width===390){await page.getByRole('button',{name:'会话工具',exact:true}).click();await page.getByRole('button',{name:'查看改动',exact:true}).click();}else {await page.locator('.conversation-more > summary').click();await page.locator('#view-changes').click();}await page.locator('#changes-content details summary').first().click();

 await page.locator('.diff-comment-card').getByRole('button',{name:'删除',exact:true}).click();
 assert.equal(await page.evaluate(()=>reviewComments.length),0);
 await page.getByRole('button',{name:'评论 src/test.js R1',exact:true}).click();
 await page.locator('.diff-comment textarea').fill('保留到发送');
 await page.getByRole('button',{name:'添加评论',exact:true}).click();
 assert.equal(await page.evaluate(()=>reviewComments.length),1);
 await page.locator('#changes-close').click();
 await page.evaluate(async()=>{await selectThread('t2');});
 assert.equal(await page.evaluate(()=>reviewComments.length),0,'comment draft stays in source thread');
 await page.evaluate(async()=>{await selectThread('t1');});
 assert.equal(await page.evaluate(()=>reviewComments.length),1,'source comment draft restores after return');
 assert.equal(writes.length,beforeComment,'line comments remain local drafts');
 await page.evaluate(()=>client.onSubmission({id:'original-request',threadId:'t1',prompt:'test',state:'uncertain',begin:true}));
 const before=writes.length;
 await page.getByRole('button',{name:'核对发送结果',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('仍待核对'));
 assert.equal(writes.length,before,'reconciliation does not resend');
 assert(reads.includes('/api/jobs/original-request'));
 const subscriptionBefore=await page.evaluate(()=>subscription);
 await page.evaluate(()=>resumeConnection());
 await page.waitForFunction(()=>listLoadState.phase==='idle');
 assert.equal(await page.evaluate(()=>subscription),subscriptionBefore,'short resume reuses subscription');
 let release;historyReply=()=>new Promise(resolve=>release=resolve);
 await page.evaluate(()=>{window.notificationPending=openNotification({threadId:'t1',itemId:'old'});});
 await page.waitForTimeout(50);
 await page.evaluate(()=>selectThread('t2'));
 release({...defaultHistory,timeline:[{id:'old',type:'agentMessage',text:'old notification'}]});
 await page.evaluate(()=>notificationPending);
 assert.equal(await page.evaluate(()=>selected),'t2');
 assert.equal(await page.locator('[data-navigation-id="old"]').count(),0);
 await page.evaluate(()=>WorkspaceBinding.open());
 await page.getByLabel('工作区二维码链接').fill('https://wrong.example/#carryon-bind='+'a'.repeat(32)+'.'+'b'.repeat(43));
 await page.getByRole('button',{name:'读取链接',exact:true}).click();
 assert.equal(bindingCalls.length,0,'foreign QR secrets never leave current origin');
 await page.getByRole('button',{name:'重新读取',exact:true}).click();
 await page.getByLabel('工作区二维码链接').fill('http://127.0.0.1:8923/#carryon-bind='+'a'.repeat(32)+'.'+'b'.repeat(43));
 await page.getByRole('button',{name:'读取链接',exact:true}).click();
 await page.getByRole('button',{name:'确认绑定',exact:true}).waitFor();
 assert.equal(bindingCalls.length,1,'inspection never binds automatically');
 await page.getByRole('button',{name:'确认绑定',exact:true}).click();
 await page.waitForFunction(()=>!document.querySelector('.login-qr-dialog:last-of-type')?.open);
 assert.equal(bindingCalls.length,2);
 await page.screenshot({path:'.runtime/web-parity-'+width+'.png'});
 assert.deepEqual(errors,[]);
 await page.close();
 }
 console.log('PASS: desktop/mobile preference, all/unread/activity, read clearing, readonly history, streaming anchor, latest, diffs, query-only receipt, lifecycle, late notification.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
