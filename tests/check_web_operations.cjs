const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch();
 try { for(const width of [1280,390]){
 const page=await browser.newPage({viewport:{width,height:844}});
 const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.log('PAGEERROR',e.stack)});let authenticated=true;
 const writes=[],reads=[],bindingCalls=[];let historyReply=null,failOperation=false,forkState='uncertain',forkDelay=0,composeDelay=0;
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
   else if(body.method==='POST'&&path.endsWith('/compose')){if(composeDelay)await new Promise(resolve=>setTimeout(resolve,composeDelay));data={id:body.body.requestId,state:'accepted'};}
   else if(body.method==='POST'&&path.endsWith('/operations'))data={id:body.body.requestId,state:typeof failOperation==='string'?failOperation:failOperation?'failed':'completed',error:failOperation?'fixture failure':undefined,...(body.body.action==='review'&&!failOperation?{reviewThreadId:path.split('/')[3],turnId:'review-turn'}:{}),...(['goal-set','goal-pause','goal-clear'].includes(body.body.action)&&!failOperation?{result:body.body.action==='goal-clear'?{cleared:true}:{goal:{threadId:path.split('/')[3],status:body.body.action==='goal-pause'?'paused':body.body.status||'active'}}}:{})};
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
  await selectThread('t1');window.operationHistory={thread:{id:'t1'},historyRevision:'ops1',runtime:{type:'active'},status:{state:'running'},access:{nativeReady:true,canInteract:true},controls:{supportedOperations:['settings','interrupt','steer','queue-add','queue-edit','queue-delete','queue-reorder','queue-resume','clear-queue'],activeTurnId:'turn',requests:[],supportedSettings:['model','effort','collaborationMode','sandboxPolicy'],settings:{activePermissionProfile:{id:'desktop-only'},sandboxPolicy:{type:'readOnly'}}},queue:{fingerprint:'queue-authority',messages:[{id:'q1',text:'queued',pausedReason:'paused'},{id:'q2',text:'next'}]},timeline:[{id:'user',type:'userMessage',text:'hello'}]};
  await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:operationHistory},()=>true);
 });
 await page.evaluate(()=>{operationHistory.controls.supportsSkills=true;updateCompose(operationHistory);});
 if(width===390)await page.locator('#attach-images').click();else await page.locator('#composer-attachment-details > summary').click();
 await page.getByRole('button',{name:'添加技能',exact:true}).click();
 const skillDialog=page.getByRole('dialog',{name:'技能',exact:true});
 await skillDialog.getByRole('button',{name:'review Review changes',exact:true}).click();
 assert(await skillDialog.getByRole('button',{name:'disabled',exact:true}).isDisabled());
 assert((await skillDialog.innerText()).includes('broken skill fixture'));
 await skillDialog.getByRole('button',{name:'完成',exact:true}).click();
 assert.equal(await page.locator('#prompt .inline-reference').count(),1);
 await page.evaluate(async()=>{await selectThread('t2');});assert.equal(await page.locator('#prompt .inline-reference').count(),0);
 await page.evaluate(async()=>{await selectThread('t1');await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:operationHistory},()=>true);});
 assert.equal(await page.locator('#prompt .inline-reference').count(),1);
 await page.locator('#send').click();await page.waitForFunction(()=>!selectedSkills.length&&!imageBusy);
 assert.deepEqual(writes.at(-1).body.skills,[{name:'review',path:'/skills/review/SKILL.md'}]);assert.equal(writes.at(-1).body.action,'queue-add');assert.equal(writes.at(-1).body.prompt,'');
 // Native skill-only history remains visible as a named reference, not an empty bubble or raw JSON.
 await page.evaluate(()=>{Timeline.render({thread:{id:'t1'},timeline:[{id:'skill-only',type:'userMessage',text:'',data:{content:[{type:'skill',name:'review',path:'/skills/review/SKILL.md'}]}}]},$('messages'),()=>{});});
 assert.equal(await page.locator('#messages .skill-chip').innerText(),'review');
 assert.equal(await page.locator('#messages details').count(),0);
 // A skill unavailable on the current owner remains in the draft and cannot become a plain-text send.
 await page.evaluate(()=>{selectedSkills=[{name:'review',path:'/skills/review/SKILL.md'}];operationHistory.controls.supportsSkills=false;updateCompose(operationHistory);renderSkills();});
 const beforeUnavailable=writes.length;await page.locator('#send').click();await page.waitForTimeout(30);assert.equal(writes.length,beforeUnavailable);assert.equal(await page.locator('#prompt .inline-reference').count(),1);
 await page.locator('#prompt > [contenteditable]').focus();await page.evaluate(()=>{const range=document.createRange();range.selectNode(document.querySelector('#prompt .inline-reference'));getSelection().removeAllRanges();getSelection().addRange(range);});await page.keyboard.press('Backspace');
 assert.equal(await page.locator('#prompt .inline-reference').count(),0);
 await page.evaluate(()=>{operationHistory.controls.supportsSkills=true;updateCompose(operationHistory);});
 // A confirmed send clears its original scoped snapshot even after navigation.
 composeDelay=250;
 await page.evaluate(()=>{selectedSkills=[{name:'review',path:'/skills/review/SKILL.md'}];$('prompt').value='submitted A';$('followup-mode').value='steer';renderSkills();updateComposeButton();});
 const beforeDelayed=writes.length;await page.locator('#send').click();
 await page.waitForFunction(()=>imageBusy);while(writes.length===beforeDelayed)await page.waitForTimeout(10);
 await page.evaluate(async()=>{await selectThread('t2');$('prompt').value='unsent B';selectedSkills=[{name:'other',path:'/skills/other/SKILL.md'}];renderSkills();});
 await page.waitForFunction(()=>!imageBusy);assert.equal(await page.locator('#prompt').evaluate(el=>el.wireText),'unsent B');
 await page.evaluate(async()=>{await selectThread('t1');await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:operationHistory},()=>true);});
 assert.equal(await page.locator('#prompt').evaluate(el=>el.value),'');assert.equal(await page.locator('#prompt .inline-reference').count(),0);
 composeDelay=0;await page.evaluate(()=>{$('followup-mode').value='queue';updateComposeButton();});
 await page.evaluate(()=>{operationHistory.controls.supportsMentions=true;updateCompose(operationHistory);renderSkills();});
 if(width===390)await page.locator('#attach-images').click();else await page.locator('#composer-attachment-details > summary').click();
 await page.getByRole('button',{name:'添加应用或插件',exact:true}).click();
 const mentionsDialog=page.getByRole('dialog',{name:'应用与插件',exact:true});
 await mentionsDialog.getByRole('button',{name:'Fixture App Connected app',exact:true}).click();
 assert(await mentionsDialog.getByRole('button',{name:'Unavailable',exact:true}).isDisabled());
 await mentionsDialog.getByRole('button',{name:'完成',exact:true}).click();
 assert.equal(await page.locator('#prompt .inline-reference').innerText(),'Fixture App');
 await page.locator('#send').click();await page.waitForFunction(()=>!selectedSkills.length&&!imageBusy);
 assert.deepEqual(writes.at(-1).body.mentions,[{name:'Fixture App',path:'app://fixture'}]);
 assert.deepEqual(writes.at(-1).body.skills,[]);

 const settingsPanel=page.locator('.mobile-session-settings');
 const advancedSettings=JSON.parse(await settingsPanel.getByLabel('高级设置 JSON',{exact:true}).inputValue());
 assert(!('activePermissionProfile' in advancedSettings));assert.deepEqual(advancedSettings.sandboxPolicy,{type:'readOnly'});
 if(width===390){await page.getByRole('button',{name:'会话工具',exact:true}).click();await page.getByRole('button',{name:'高级会话设置',exact:true}).click();}
 else {await page.locator('.session-actions>summary').click();await settingsPanel.locator(':scope>summary').click();}
 await page.waitForFunction(()=>!document.querySelector('[aria-label="模型"]').disabled);
 await settingsPanel.getByLabel('模型',{exact:true}).selectOption('fixture-model');
 await settingsPanel.getByLabel('思考强度',{exact:true}).selectOption('high');
 await settingsPanel.getByLabel('工作模式',{exact:true}).selectOption('plan');
 await settingsPanel.getByRole('button',{name:'保存设置',exact:true}).evaluate(button=>button.click());
 await page.waitForTimeout(50);
 assert.deepEqual(writes.at(-1).body.settings,{model:'fixture-model',effort:'high',collaborationMode:{mode:'plan',settings:{model:'fixture-model',reasoning_effort:'high',developer_instructions:null}}});
 if(width===390)await page.locator('#mobile-aux button[aria-label="返回"]').click();
 else await page.locator('.session-actions>summary').click();
 // Composer projections use native usage and separate model/configuration controls.
 if(width===390)await page.evaluate(()=>{const tools=document.querySelector('#mobile-tools');if(tools.open)tools.close();});
 await page.evaluate(()=>{composeHistory=operationHistory;composeHistory.controls.supportedOperations=['settings','voice-start'];VoiceControls.update();composeHistory.metadata={latestTokenUsageInfo:{modelContextWindow:1000,last:{totalTokens:250}}};composeHistory.controls.settings={model:'fixture-model',effort:'high',approvalPolicy:'on-request',collaborationMode:{mode:'plan',settings:{model:'fixture-model',reasoning_effort:'high',developer_instructions:'keep'}}};composeHistory.controls.supportedSettings.push('approvalPolicy');updateComposerContext();});
 assert.equal(await page.locator('#context-usage').getAttribute('aria-label'),'上下文已用 25%');
 await page.evaluate(()=>{delete composeHistory.metadata.latestTokenUsageInfo;updateComposerContext();});assert(await page.locator('#context-usage').isHidden());
 await page.evaluate(()=>{composeHistory.metadata.latestTokenUsageInfo={modelContextWindow:1000,last:{totalTokens:250}};updateComposerContext();});
 if(width===390){
  for(const viewportWidth of [320,1280,390]){
   await page.setViewportSize({width:viewportWidth,height:844});await page.waitForTimeout(80);
   assert(await page.locator('#context-usage').isVisible());
   const bounds=await page.locator('#context-usage').boundingBox();assert(bounds.x>=0&&bounds.x+bounds.width<=viewportWidth);
   assert.equal(await page.locator('#context-usage').count(),1);
   if(viewportWidth<768){
    const row=await page.evaluate(()=>['#attach-images','#composer button[aria-label="对话配置"]','#context-usage','#composer .model-button','#voice-open','#send'].map(s=>{const r=document.querySelector(s).getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};}));
    assert(row.every(r=>r.w>0&&r.x>=0&&r.x+r.w<=viewportWidth));
    assert(Math.max(...row.map(r=>r.y+r.h/2))-Math.min(...row.map(r=>r.y+r.h/2))<=2,'all composer controls share one footer row');
    assert(row.every((r,i)=>i===0||r.x>=row[i-1].x+row[i-1].w-1),'composer controls do not overlap');
   }

   const fileChooser=page.waitForEvent('filechooser');
   if(viewportWidth>=768)await page.locator('#composer-attachment-details > summary').click();
   await page.locator('#attach-images').click();
   if(viewportWidth<768)await page.locator('.mobile-attachment-menu:popover-open').getByRole('button',{name:'添加图片',exact:true}).click();
   await fileChooser;
   assert.equal(await page.locator('#attach-skills').count(),1);assert.equal(await page.locator('#attach-mentions').count(),1);

  }
 }
 await page.getByRole('button',{name:'对话配置',exact:true}).filter({visible:true}).click();
 const composerSettings=width===390?page.locator('#mobile-model'):page.locator('.composer-settings-dialog');
 await composerSettings.getByLabel('执行审批',{exact:true}).waitFor();
 assert(await composerSettings.getByLabel('模型',{exact:true}).isHidden());assert(await composerSettings.getByLabel('工作模式',{exact:true}).isVisible());
 await page.keyboard.press('Escape');
 await page.getByRole('button',{name:width===390?'查看当前模型与思考强度':'模型与思考强度',exact:true}).filter({visible:true}).click();
 await composerSettings.getByLabel('模型',{exact:true}).waitFor();assert(await composerSettings.getByLabel('工作模式',{exact:true}).isHidden());
 await composerSettings.getByLabel('模型',{exact:true}).selectOption('gpt-6-astra');await composerSettings.getByLabel('思考强度',{exact:true}).selectOption('high');
 await composerSettings.getByRole('button',{name:'保存设置',exact:true}).click();await page.waitForTimeout(50);
 assert.equal(writes.at(-1).body.settings.collaborationMode.settings.model,'gpt-6-astra');assert.equal(writes.at(-1).body.settings.collaborationMode.mode,'plan');assert.equal(writes.at(-1).body.settings.collaborationMode.settings.developer_instructions,'keep');
 await page.keyboard.press('Escape');
 // An already open configuration cannot write after native settings capability is revoked.
 await page.evaluate(()=>{operationHistory.controls.supportedOperations=['settings'];Operations.render(operationHistory,selected,client,notice,true);composeHistory=operationHistory;updateComposerContext();});
 await page.getByRole('button',{name:'对话配置',exact:true}).filter({visible:true}).click();
 await composerSettings.getByLabel('执行审批',{exact:true}).waitFor();
 await composerSettings.getByLabel('执行审批',{exact:true}).selectOption('never');
 const beforeRevokedSettings=writes.length;
 await page.evaluate(()=>{operationHistory.controls.supportedOperations=[];Operations.render(operationHistory,selected,client,notice,true);composeHistory=operationHistory;updateComposerContext();});
 const staleSave=composerSettings.getByRole('button',{name:'保存设置',exact:true});
 if(await staleSave.isVisible()&&await staleSave.isEnabled())await staleSave.click();
 await page.waitForTimeout(80);assert.equal(writes.length,beforeRevokedSettings,'revoked settings must not write from an already open composer panel');
 await page.keyboard.press('Escape');
 await page.evaluate(()=>{operationHistory.controls.supportedOperations=['settings','interrupt','steer','queue-add','queue-edit','queue-delete','queue-reorder','queue-resume','clear-queue'];Operations.render(operationHistory,selected,client,notice,true);composeHistory=operationHistory;updateComposerContext();});
 await page.locator('#image-files').setInputFiles({name:'fixture.png',mimeType:'image/png',buffer:Buffer.from(await page.evaluate(()=>{const canvas=document.createElement('canvas');canvas.width=canvas.height=16;canvas.getContext('2d').fillRect(0,0,16,16);return canvas.toDataURL('image/png').split(',')[1];}),'base64')});
 await page.locator('#image-previews img').waitFor();await page.locator('#prompt > [contenteditable]').fill('image fixture');
 await page.locator('#send').click();await page.waitForFunction(()=>!document.querySelector('#prompt').value&&!document.querySelector('#image-previews img'));
 const imageWrite=writes.find(w=>w.body.action==='queue-add'&&w.body.images?.length);assert(imageWrite.body.images[0].startsWith('data:image/jpeg;base64,'));assert.equal(imageWrite.body.queueFingerprint,'queue-authority');
 await page.locator('#followup-mode').selectOption('steer');await page.locator('#prompt > [contenteditable]').fill('steering fixture');await page.locator('#send').click();await page.waitForFunction(()=>!document.querySelector('#prompt').value);assert(writes.some(w=>w.path==='/api/threads/t1/compose'&&w.body.prompt==='steering fixture'));
 await page.locator('#send').click();
 await page.waitForTimeout(50);
 assert.equal(writes.at(-1).body.action,'interrupt');assert.equal(writes.at(-1).body.expectedTurnId,'turn');
 if(width===390){await page.getByRole('button',{name:'会话工具',exact:true}).click();await page.getByRole('button',{name:'队列管理',exact:true}).click();}
 else {await page.locator('.session-actions>summary').click();await page.locator('.mobile-queue>summary').click();}
 const queue=page.locator('.mobile-queue');
 await queue.getByLabel('第 1 条排队任务',{exact:true}).fill('changed');
 for(const [label,action]of [['保存内容','queue-edit'],['下移','queue-reorder'],['恢复执行','queue-resume']]){
  await queue.getByRole('button',{name:label,exact:true}).first().click();await page.waitForTimeout(30);
  assert.equal(writes.at(-1).body.action,action);assert.equal(writes.at(-1).body.queueFingerprint,'queue-authority');
 }
 if(width===390)await page.locator('#mobile-aux button[aria-label="返回"]').click();
 await page.evaluate(async()=>{operationHistory={...operationHistory,historyRevision:'approval',status:{state:'waiting'},controls:{...operationHistory.controls,supportedOperations:[...operationHistory.controls.supportedOperations,'command-approval','user-input'],requests:[{id:'native-approval',fingerprint:'approval-fingerprint',action:'command-approval',params:{command:'echo fixture'},decisions:['accept','decline']}]}};await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:operationHistory},()=>true);});
 page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'仅本次允许',exact:true}).click();await page.waitForTimeout(30);
 assert.equal(writes.at(-1).body.requestFingerprint,'approval-fingerprint');assert.equal(writes.at(-1).body.nativeRequestId,'native-approval');assert.equal(writes.at(-1).body.decision,'accept');
 await page.evaluate(async()=>{operationHistory={...operationHistory,historyRevision:'question',controls:{...operationHistory.controls,requests:[{id:'native-question',fingerprint:'question-fingerprint',action:'user-input',params:{questions:[{id:'answer',question:'fixture question'}]}}]}};await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:operationHistory},()=>true);});
 await page.getByLabel('fixture question',{exact:true}).fill('answer fixture');failOperation=true;
 await page.getByRole('button',{name:'提交回答',exact:true}).click();await page.waitForTimeout(40);
 assert.equal(await page.getByLabel('fixture question',{exact:true}).inputValue(),'answer fixture');
 const first=writes.at(-1).body;assert.equal(first.requestFingerprint,'question-fingerprint');assert.deepEqual(first.answers,{answer:['answer fixture']});
 failOperation='uncertain';await page.getByRole('button',{name:'提交回答',exact:true}).click();await page.waitForTimeout(40);
 const uncertain=writes.at(-1).body;assert.notEqual(uncertain.requestId,first.requestId);
 failOperation=false;await page.getByRole('button',{name:'提交回答',exact:true}).click();await page.waitForTimeout(40);
 assert.equal(writes.at(-1).body.requestId,uncertain.requestId);
 await page.evaluate(async()=>{operationHistory={...operationHistory,historyRevision:'queue-only',runtime:{type:'idle'},status:{state:'idle'},controls:{...operationHistory.controls,supportedOperations:['queue-edit'],requests:[]}};await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:operationHistory},()=>true);});
 assert.equal(await page.locator('.mobile-session-settings').count(),0);
 assert.equal(await page.locator('.mobile-queue').count(),1,'queue capabilities are independent of settings');
 assert.equal(await page.locator('.mobile-queue button').count(),2,'edit-only queue exposes only existing message save controls');
 await page.evaluate(()=>{window.revokedQueueSave=document.querySelector('.mobile-queue button');});
 const beforeQueueRevocation=writes.length;
 await page.evaluate(async()=>{operationHistory={...operationHistory,historyRevision:'settings-only',controls:{...operationHistory.controls,supportedOperations:['settings']}};await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:operationHistory},()=>true);revokedQueueSave.click();});
 await page.waitForTimeout(50);assert.equal(writes.length,beforeQueueRevocation,'revoked detached queue controls cannot submit');
 assert.equal(await page.locator('.mobile-queue').count(),0,'settings support alone cannot advertise queue operations');
 await page.evaluate(async()=>{const controls={...operationHistory.controls};delete controls.supportedOperations;operationHistory={...operationHistory,historyRevision:'missing-capabilities',runtime:{type:'active'},status:{state:'running'},controls};await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:operationHistory},()=>true);});
 assert(!(await page.locator('.mobile-session-settings').count()),'missing capability list must not enable settings');
 assert(await page.locator('#followup-label').isHidden(),'missing capability list must not enable queued composer');
 await page.evaluate(async()=>{await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:{...operationHistory,historyRevision:'readonly',source:'local-rollout',access:{canInteract:false,nativeReady:false},controls:{},status:{state:'notLoaded'}}},()=>true);});
 assert(await page.locator('#send').isDisabled());assert.equal(await page.locator('#requests button').count(),0);
 const count=writes.length;await page.evaluate(()=>$('composer').requestSubmit());await page.waitForTimeout(30);assert.equal(writes.length,count);
 await page.evaluate(async()=>{
   await selectThread('t1');window.reviewHistory={thread:{id:'t1'},historyRevision:'review1',runtime:{type:'idle'},status:{state:'idle'},access:{nativeReady:true,canInteract:true},controls:{supportedOperations:['review'],requests:[],settings:{}},queue:{fingerprint:'empty',messages:[]},timeline:[]};
   await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:reviewHistory},()=>true);
 });
 if(width===390){await page.getByRole('button',{name:'会话工具',exact:true}).click();await page.getByRole('button',{name:'审查代码',exact:true}).click();}
 else {await page.locator('.session-actions>summary').click();await page.locator('.mobile-review>summary').click();}
 const reviewPanel=page.locator('.mobile-review');await reviewPanel.getByLabel('审查范围',{exact:true}).selectOption('baseBranch');
 assert(await reviewPanel.getByRole('button',{name:'开始审查',exact:true}).isDisabled());
 await reviewPanel.getByLabel('分支名称',{exact:true}).fill('main');failOperation='uncertain';
 await reviewPanel.getByRole('button',{name:'开始审查',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('.mobile-review button').disabled);
 const reviewFirst=writes.at(-1);assert.deepEqual(reviewFirst.body.target,{type:'baseBranch',branch:'main'});assert.equal(reviewFirst.body.action,'review');
 assert.equal(await reviewPanel.getByLabel('分支名称',{exact:true}).inputValue(),'main');
 await page.evaluate(async()=>{reviewHistory={...reviewHistory,historyRevision:'review2',status:{state:'idle',label:'updated'}};await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:reviewHistory},()=>true);});
 assert.equal(await reviewPanel.getByLabel('审查范围',{exact:true}).inputValue(),'baseBranch');assert.equal(await reviewPanel.getByLabel('分支名称',{exact:true}).inputValue(),'main');
 failOperation=false;await reviewPanel.getByRole('button',{name:'开始审查',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('.mobile-review button').disabled);assert.equal(writes.at(-1).body.requestId,reviewFirst.body.requestId);
 if(width===390)await page.locator('#mobile-aux button[aria-label="返回"]').click();
 else await page.locator('.session-actions>summary').click();
 await page.evaluate(async()=>{
   window.goalHistory={...reviewHistory,historyRevision:'goal-new',controls:{requests:[],settings:{},supportsGoal:true,goal:null}};
   await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:goalHistory},()=>true);
 });
 if(width===390){await page.getByRole('button',{name:'会话工具',exact:true}).click();await page.getByRole('button',{name:'会话目标',exact:true}).click();}
 else {await page.locator('.session-actions>summary').click();await page.locator('.mobile-goal>summary').click();}
 const goalPanel=page.locator('.mobile-goal');assert(await goalPanel.getByRole('button',{name:'启动目标',exact:true}).isDisabled());
 await goalPanel.getByLabel('目标内容',{exact:true}).fill('Complete isolated fixture');
 await goalPanel.getByLabel('Token 预算（可选）',{exact:true}).fill('1.5');assert(await goalPanel.getByRole('button',{name:'启动目标',exact:true}).isDisabled());
 await goalPanel.getByLabel('Token 预算（可选）',{exact:true}).fill('2000');failOperation='uncertain';
 await goalPanel.getByRole('button',{name:'启动目标',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('.mobile-goal button').disabled);
 const goalFirst=writes.at(-1).body;assert.equal(goalFirst.action,'goal-set');assert.equal(goalFirst.status,'active');assert.equal(goalFirst.tokenBudget,2000);
 failOperation=false;await goalPanel.getByRole('button',{name:'启动目标',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('.mobile-goal button').disabled);assert.equal(writes.at(-1).body.requestId,goalFirst.requestId);
 await page.evaluate(async()=>{
   goalHistory={...goalHistory,historyRevision:'goal-active',controls:{...goalHistory.controls,goal:{threadId:'t1',objective:'Complete isolated fixture',status:'active',tokenBudget:2000,tokensUsed:125,timeUsedSeconds:9}}};
   await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:goalHistory},()=>true);
 });
 assert((await goalPanel.innerText()).includes('125 Token / 2000'));
 await page.evaluate(async()=>{
   goalHistory={...goalHistory,historyRevision:'goal-unknown',controls:{...goalHistory.controls,goalUnknown:true}};
   await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:goalHistory},()=>true);
 });
 assert(await goalPanel.getByRole('button',{name:'保存目标',exact:true}).isDisabled());
 const goalReadBefore=reads.length;await goalPanel.getByRole('button',{name:'核对目标状态',exact:true}).click();
 await page.waitForFunction(()=>!Array.from(document.querySelectorAll('.mobile-goal button')).find(button=>button.textContent==='核对目标状态').disabled);
 assert(reads.slice(goalReadBefore).some(path=>path==='/api/threads/t1/goal'));
 await page.evaluate(async()=>{
   goalHistory={...goalHistory,historyRevision:'goal-confirmed',controls:{...goalHistory.controls,goalUnknown:false}};
   await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:goalHistory},()=>true);
 });

 await goalPanel.getByRole('button',{name:'暂停目标',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('.mobile-goal button').disabled);assert.equal(writes.at(-1).body.action,'goal-pause');
 await page.evaluate(async()=>{
   client.devices.find(item=>item.id===client.device).permissions=['view','send'];
   goalHistory={...goalHistory,historyRevision:'goal-no-stop',controls:{...goalHistory.controls,goal:{...goalHistory.controls.goal,status:'paused'}}};
   await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:goalHistory},()=>true);
 });
 assert(await goalPanel.getByRole('button',{name:'移除目标',exact:true}).isDisabled());
 await goalPanel.getByRole('button',{name:'继续目标',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('.mobile-goal button').disabled);assert.equal(writes.at(-1).body.status,'active');
 await page.evaluate(()=>{client.devices.find(item=>item.id===client.device).permissions=['view','create','send','edit','stop'];});
 if(width===390)await page.locator('#mobile-aux button[aria-label="返回"]').click();
 else await page.locator('.session-actions>summary').click();
 await page.evaluate(async()=>{reviewHistory={...reviewHistory,historyRevision:'review-running',status:{state:'running'},runtime:{type:'active'},controls:{...reviewHistory.controls,supportedOperations:['review','queue-add'],activeTurnId:'review-turn',canSteer:false,activeTurnKind:'review'}};await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:reviewHistory},()=>true);});
 assert(await page.locator('#followup-mode option[value=steer]').evaluate(option=>option.disabled));assert.equal(await page.locator('#followup-mode').inputValue(),'queue');assert.equal(await page.getByRole('button',{name:'发送补充指令',exact:true}).count(),0);
 await page.evaluate(async()=>{
  await selectThread('t1');window.forkHistory={thread:{id:'t1'},historyRevision:'fork1',runtime:{type:'idle'},status:{state:'idle'},access:{nativeReady:true,canInteract:true},controls:{supportedOperations:['fork'],requests:[],settings:{},lastTurnId:'turn2'},timeline:[{id:'u1',turnId:'turn1',type:'userMessage',text:'first turn'},{id:'u2',turnId:'turn2',type:'userMessage',text:'second turn'}]};
  await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:forkHistory},()=>true);
 });
 if(width===390){await page.getByRole('button',{name:'会话工具',exact:true}).click();await page.getByRole('button',{name:'分叉会话',exact:true}).click();}
 else {await page.locator('.session-actions>summary').click();await page.locator('.mobile-fork>summary').click();}
 const forkPanel=page.locator('.mobile-fork');await forkPanel.getByLabel('分叉保留到',{exact:true}).selectOption('turn1');
 await page.evaluate(async()=>{forkHistory={...forkHistory,historyRevision:'fork-more',timeline:[{id:'u0',turnId:'turn0',type:'userMessage',text:'older turn'},...forkHistory.timeline]};await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:forkHistory},()=>true);});
 assert.equal(await forkPanel.getByLabel('分叉保留到',{exact:true}).inputValue(),'turn1');assert.equal(await forkPanel.locator('option[value=turn0]').count(),1);
 await page.evaluate(async()=>{forkHistory={...forkHistory,historyRevision:'fork-missing',timeline:forkHistory.timeline.filter(item=>item.turnId!=='turn1')};await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:forkHistory},()=>true);});
 assert.equal(await forkPanel.getByLabel('分叉保留到',{exact:true}).inputValue(),'turn1');assert(await forkPanel.getByRole('button',{name:'创建分叉',exact:true}).isDisabled());
 await page.evaluate(async()=>{forkHistory={...forkHistory,historyRevision:'fork-restored',timeline:[{id:'u1',turnId:'turn1',type:'userMessage',text:'first turn'},...forkHistory.timeline]};await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:forkHistory},()=>true);});

 forkDelay=200;await forkPanel.getByRole('button',{name:'创建分叉',exact:true}).click();
 await page.evaluate(async()=>{forkHistory={...forkHistory,historyRevision:'fork-pending',status:{state:'idle',label:'updated'}};await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:forkHistory},()=>true);});
 assert(await forkPanel.getByRole('button',{name:'创建分叉',exact:true}).isDisabled());assert(await forkPanel.getByLabel('分叉保留到',{exact:true}).isDisabled());
 await page.waitForFunction(()=>!document.querySelector('.mobile-fork button').disabled);forkDelay=0;
 const forkFirst=writes.at(-1);assert.equal(forkFirst.path,'/api/threads/t1/fork');assert.equal(forkFirst.body.lastTurnId,'turn1');assert.equal(await page.evaluate(()=>selected),'t1');
 forkState='completed';await forkPanel.getByRole('button',{name:'创建分叉',exact:true}).click();
 await page.waitForFunction(()=>selected==='forked');assert.equal(writes.at(-1).body.requestId,forkFirst.body.requestId);
 await page.screenshot({path:'.runtime/web-operations-'+width+'.png'});
 assert.deepEqual(errors,[]);await page.close();
 }
 console.log('PASS desktop/mobile: fork selected turn/uncertain identity/confirmed navigation, plan mode model/effort payload, stop expected turn, queue fingerprint, approval confirmation/native request, failed question retains answer, known failure retries with new ID, uncertain retry preserves ID, readonly denies writes. Mock transport only.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
