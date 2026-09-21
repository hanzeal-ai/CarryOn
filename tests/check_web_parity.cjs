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
  if(u.pathname.endsWith('/session')){if(!authenticated){status=401;data={error:'请先登录云端控制台'};}else data={devices:[{id:'mac',name:'我的 MacBook',online:true},{id:'other',name:'工作室 Mac',online:false}]};}
  else if(u.pathname.endsWith('/login'))authenticated=true;
  else if(u.pathname.endsWith('/logout'))authenticated=false;
  else if(u.pathname.endsWith('/binding/pending'))data={requests:[]};
  else if(u.pathname.includes('/binding/')){bindingCalls.push({path:u.pathname,body:req.postDataJSON()});data={name:'测试工作区',permissions:['view'],account:{username:'tester'},state:u.pathname.endsWith('/accept')?'bound':'pending'};}
  else if(u.pathname.endsWith('/request')){
   const body=req.postDataJSON(),path=body.path.split('?')[0];if(body.method==='POST')writes.push(body);else reads.push(body.path);
   if(path==='/api/status')data={enabled:true,controllerId:'t2',remoteControl:true};
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
  socket.onMessage(raw=>{const selection=JSON.parse(raw);if(selection.type==='subscribe')socket.send(JSON.stringify({type:'update',revision:++revision,resubscribe:true,subscription:selection.subscription,body:{type:'update',subscription:selection.subscription,threadId:selection.threadId,status:{enabled:true,controllerId:'t2',remoteControl:true}}}));});
 });

 await page.goto('http://127.0.0.1:8923/example.html');
 await page.waitForFunction(()=>typeof Timeline!=='undefined'&&enabled);

 await page.locator('#create').click();
 await page.locator('#new-project').selectOption('p2');
 await page.locator('#new-prompt').fill('project creation fixture');
 await page.locator('#submit-create').click();
 await page.waitForFunction(()=>!document.querySelector('#create-dialog').open);
 assert.equal(writes.find(w=>w.path==='/api/threads').body.projectId,'p2');
 assert(reads.some(path=>path.includes('/projects?')&&path.includes('availableOnly=true')));
 if(width===390){await page.getByRole('button',{name:'我的',exact:true}).click();}
 await page.screenshot({path:'.runtime/web-parity-settings-'+width+'.png'});
 await page.locator('#show-inactive').check();
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
  await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:parityHistory},()=>true);
  Timeline.navigateTo('m20');
 });
 await page.screenshot({path:'.runtime/web-parity-history-'+width+'.png'});
 assert(await page.locator('#send').isDisabled());
 assert(await page.locator('#history-source').isVisible());
 assert((await page.locator('#history-source').textContent()).includes('桌面 Codex'));
 const position=await page.locator('[data-navigation-id="m20"]').evaluate(n=>n.getBoundingClientRect().y);
 await page.evaluate(async()=>{const history={...parityHistory,historyRevision:'parity2',timeline:parityHistory.timeline.map(i=>i.id==='m0'?{...i,text:i.text.repeat(4)}:i).concat({id:'new',type:'agentMessage',text:'new message'})};await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history},()=>true);});
 assert(Math.abs(await page.locator('[data-navigation-id="m20"]').evaluate(n=>n.getBoundingClientRect().y)-position)<2,'old reading anchor stays fixed');
 assert.equal(await page.locator('#messages').getAttribute('data-new-messages'),'true');
 if(width===390)await page.getByRole('button',{name:'有新消息，回到最新',exact:true}).click();else await page.locator('#jump-latest').click();
 await page.waitForFunction(()=>{const v=document.querySelector('#messages').closest('.mobile-chat-scroll')||document.querySelector('#messages');return v.scrollHeight-v.scrollTop-v.clientHeight<100;});
 await page.evaluate(async()=>{await receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:{...parityHistory,historyRevision:'changes',timeline:[{id:'f',type:'fileChange',data:{changes:[{path:'src/test.js',diff:'-old\n+new'}]}},{id:'d',type:'turnDiff',data:{diff:'whole diff'}}]}},()=>true);});
 if(width===390){await page.getByRole('button',{name:'会话工具',exact:true}).click();await page.getByRole('button',{name:'查看改动',exact:true}).click();}else await page.locator('#view-changes').click();
 assert((await page.locator('#changes-content').textContent()).includes('src/test.js'));
 assert((await page.locator('#changes-content').textContent()).includes('whole diff'));
 await page.locator('#changes-close').click();
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
