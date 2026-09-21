const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch();
 try { for(const width of [1280,390]){
 const page=await browser.newPage({viewport:{width,height:844}});
 const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.log('PAGEERROR',e.stack)});let authenticated=true;
 const writes=[],reads=[],bindingCalls=[];let historyReply=null,failOperation=false;
 const defaultHistory={thread:{id:'t1'},historyRevision:'initial',runtime:{type:'idle'},status:{state:'idle'},metadata:{},timeline:[]};const threads=[{id:'t1',title:'让手机上的对话更顺手',cwd:'/workspace/CarryOn',unread:true},{id:'t2',title:'检查远端连接',cwd:'/workspace/CarryOn',unread:false}];
 const projects=[{id:'p1',name:'CarryOn',cwd:'/workspace/CarryOn',total:12,waiting:1,running:2,unread:3,unknown:0},{id:'p2',name:'MarkFix',cwd:'/workspace/MarkFix',total:8,waiting:0,running:0,unread:1,unknown:0}];
 await page.addInitScript(()=>{window.CARRYON_CLOUD=true;});
 await page.route('**/console/**',async route=>{
  const req=route.request(),u=new URL(req.url());let data={},status=200;
  if(u.pathname.endsWith('/session')){if(!authenticated){status=401;data={error:'请先登录云端控制台'};}else data={devices:[{id:'mac',name:'我的 MacBook',online:true},{id:'other',name:'工作室 Mac',online:false}]};}
  else if(u.pathname.endsWith('/login'))authenticated=true;
  else if(u.pathname.endsWith('/logout'))authenticated=false;
  else if(u.pathname.endsWith('/binding/pending'))data={requests:[]};
  else if(u.pathname.includes('/binding/')){bindingCalls.push({path:u.pathname,body:req.postDataJSON()});data={name:'测试工作区',permissions:['view'],account:{username:'tester'},state:u.pathname.endsWith('/accept')?'bound':'pending'};}
  else if(u.pathname.endsWith('/request')){
   const body=req.postDataJSON(),path=body.path.split('?')[0];if(body.method==='POST')writes.push(body);else reads.push(body.path);
   if(body.method==='POST'&&path.endsWith('/compose'))data={id:body.body.requestId,state:'accepted'};
   else if(body.method==='POST'&&path.endsWith('/operations'))data={id:body.body.requestId,state:failOperation?'failed':'completed',error:failOperation?'fixture failure':undefined};
   else if(path==='/api/status')data={enabled:true,controllerId:'t2',remoteControl:true};
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
  socket.onMessage(raw=>{const selection=JSON.parse(raw);if(selection.type==='subscribe')socket.send(JSON.stringify({type:'update',revision:++revision,resubscribe:true,subscription:selection.subscription,body:{type:'update',subscription:selection.subscription,threadId:selection.threadId,status:{enabled:true,controllerId:'t2',remoteControl:true}}}));});
 });

 await page.goto('http://127.0.0.1:8923/example.html');
 await page.waitForFunction(()=>typeof Timeline!=='undefined'&&enabled);


 await page.evaluate(async()=>{
  await selectThread('t1');window.operationHistory={thread:{id:'t1'},historyRevision:'ops1',runtime:{type:'active'},status:{state:'running'},access:{nativeReady:true,canInteract:true},controls:{activeTurnId:'turn',requests:[],settings:{}},queue:{fingerprint:'queue-authority',messages:[{id:'q1',text:'queued',pausedReason:'paused'},{id:'q2',text:'next'}]},timeline:[{id:'user',type:'userMessage',text:'hello'}]};
  await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:operationHistory},()=>true);
 });
 await page.locator('#image-files').setInputFiles({name:'fixture.png',mimeType:'image/png',buffer:Buffer.from(await page.evaluate(()=>{const canvas=document.createElement('canvas');canvas.width=canvas.height=16;canvas.getContext('2d').fillRect(0,0,16,16);return canvas.toDataURL('image/png').split(',')[1];}),'base64')});
 await page.locator('#image-previews img').waitFor();await page.locator('#prompt').fill('image fixture');
 await page.locator('#send').click();await page.waitForFunction(()=>!document.querySelector('#prompt').value&&!document.querySelector('#image-previews img'));
 const imageWrite=writes.find(w=>w.path==='/api/threads/t1/compose');assert(imageWrite.body.images[0].startsWith('data:image/jpeg;base64,'));
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
 await page.evaluate(async()=>{operationHistory={...operationHistory,historyRevision:'approval',status:{state:'waiting'},controls:{...operationHistory.controls,requests:[{id:'native-approval',fingerprint:'approval-fingerprint',action:'command-approval',params:{command:'echo fixture'},decisions:['accept','decline']}]}};await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:operationHistory},()=>true);});
 page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'仅本次允许',exact:true}).click();await page.waitForTimeout(30);
 assert.equal(writes.at(-1).body.requestFingerprint,'approval-fingerprint');assert.equal(writes.at(-1).body.nativeRequestId,'native-approval');assert.equal(writes.at(-1).body.decision,'accept');
 await page.evaluate(async()=>{operationHistory={...operationHistory,historyRevision:'question',controls:{...operationHistory.controls,requests:[{id:'native-question',fingerprint:'question-fingerprint',action:'user-input',params:{questions:[{id:'answer',question:'fixture question'}]}}]}};await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:operationHistory},()=>true);});
 await page.getByLabel('fixture question',{exact:true}).fill('answer fixture');failOperation=true;
 await page.getByRole('button',{name:'提交回答',exact:true}).click();await page.waitForTimeout(40);
 assert.equal(await page.getByLabel('fixture question',{exact:true}).inputValue(),'answer fixture');
 const first=writes.at(-1).body;assert.equal(first.requestFingerprint,'question-fingerprint');assert.deepEqual(first.answers,{answer:['answer fixture']});
 failOperation=false;await page.getByRole('button',{name:'提交回答',exact:true}).click();await page.waitForTimeout(40);
 assert.equal(writes.at(-1).body.requestId,first.requestId);
 await page.evaluate(async()=>{await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:{...operationHistory,historyRevision:'readonly',source:'local-rollout',access:{canInteract:false,nativeReady:false},controls:{},status:{state:'notLoaded'}}},()=>true);});
 assert(await page.locator('#send').isDisabled());assert.equal(await page.locator('#requests button').count(),0);
 const count=writes.length;await page.evaluate(()=>$('composer').requestSubmit());await page.waitForTimeout(30);assert.equal(writes.length,count);
 await page.screenshot({path:'.runtime/web-operations-'+width+'.png'});
 assert.deepEqual(errors,[]);await page.close();
 }
 console.log('PASS desktop/mobile: stop expected turn, queue fingerprint, approval confirmation/native request, failed question retains answer and retry identity, readonly denies writes. Mock transport only.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
