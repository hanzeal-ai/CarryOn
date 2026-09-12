const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch();const page=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
 const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.log('PAGEERROR',e.stack)});let authenticated=true;
 let finishCompose, socketCount=0,sendWire,activeSelection;
 const writes=[];const threads=[{id:'t1',title:'让手机上的对话更顺手',cwd:'/workspace/ConnectNow',unread:true},{id:'t2',title:'检查远端连接',cwd:'/workspace/ConnectNow',unread:false}];
 const projects=[{id:'p1',name:'ConnectNow',cwd:'/workspace/ConnectNow',total:12,waiting:1,running:2,unread:3,unknown:0},{id:'p2',name:'MarkFix',cwd:'/workspace/MarkFix',total:8,waiting:0,running:0,unread:1,unknown:0}];
 await page.addInitScript(()=>{window.CONNECTNOW_CLOUD=true;});
 await page.route('**/console/**',async route=>{
  const req=route.request(),u=new URL(req.url());let data={},status=200;
  if(u.pathname.endsWith('/session')){if(!authenticated){status=401;data={error:'请先登录云端控制台'};}else data={devices:[{id:'mac',name:'我的 MacBook',online:true},{id:'other',name:'工作室 Mac',online:false}]};}
  else if(u.pathname.endsWith('/login'))authenticated=true;
  else if(u.pathname.endsWith('/logout'))authenticated=false;
  else if(u.pathname.endsWith('/link/pending'))data={requests:[]};
  else if(u.pathname.endsWith('/request')){
   const body=req.postDataJSON(),path=body.path.split('?')[0];if(body.method==='POST')writes.push(body);
   if(path==='/api/threads/t1/compose')data=await new Promise(resolve=>{finishCompose=resolve;});
   else if(path==='/api/status')data={enabled:true,controllerId:'t2',remoteControl:true};
   else if(path==='/api/projects')data={projects,total:2,nextOffset:2};
   else if(path==='/api/threads'||path==='/api/projects/p1/threads')data={threads,total:2,nextOffset:2};
   else if(path==='/api/activity')data={threads:[threads[1]],total:1,nextOffset:1};
   else if(path==='/api/notifications')data={events:[],nextSequence:0};
   else if(path==='/api/notifications/preferences')data={preferences:{message:true,done:true,failed:true,approval:true,...body.body}};
   else if(path==='/api/standby')data={supported:true,effective:true,enabled:true};
  }
  await route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
 });
 await page.routeWebSocket('**/console/devices/*/ws', socket=>{
  socketCount++;let revision=0;
  sendWire=body=>socket.send(JSON.stringify({type:"update",revision:++revision,resubscribe:true,subscription:activeSelection.subscription,body:{...body,subscription:activeSelection.subscription,threadId:activeSelection.threadId,status:{enabled:true,controllerId:"t2",remoteControl:true}}}));
  socket.onMessage(raw=>{const selection=JSON.parse(raw);if(selection.type==='subscribe')activeSelection=selection;if(selection.type==='subscribe')socket.send(JSON.stringify({type:'update',revision:++revision,resubscribe:true,subscription:selection.subscription,body:{type:'update',subscription:selection.subscription,threadId:selection.threadId,status:{enabled:true,controllerId:'t2',remoteControl:true}}}));});
 });
 await page.goto(process.env.CONNECTNOW_UI_URL||'http://127.0.0.1:8989/example.html');
 await page.locator('#mobile-session-list .project-row').first().click();
 await page.locator('.session').first().click();
 await page.evaluate(async()=>{
  window.fixture={thread:{id:'t1'},runtime:{type:'active'},status:{state:'running',label:'进行中'},metadata:{latestModel:'gpt-6-astra'},controls:{activeTurnId:'turn1',settings:{model:'gpt-6-astra',effort:'medium'},requests:[]},queue:{messages:[],fingerprint:'q'},timeline:[{id:'u1',type:'userMessage',text:'重新设计手机端的会话体验，让它更简洁，也更容易使用。'},{id:'a1',type:'agentMessage',text:'我会围绕阅读和回复，重新整理这段体验。\n\n界面会更专注于内容：\n• 消息自然展开，执行细节按需查看\n• 主要操作留在拇指容易触达的位置\n• 需要确认时，再呈现完整上下文'}]};
  await receiveUpdate({status:{enabled:true,controllerId:'t2',remoteControl:true},subscription,threadId:selected,history:fixture,readSequence:2},()=>true);
 });
 await page.locator('#prompt').fill('即时追加验证');await page.locator('#send').click();
 await page.locator('[data-outgoing]').waitFor();
 assert.equal(await page.locator('[data-outgoing] small').textContent(),'发送中…');
 const sentCompose=writes.findLast(w=>w.path==='/api/threads/t1/compose');
 assert(sentCompose);
 await page.evaluate(()=>{window.originalUserNode=document.querySelector('#messages .message.user');});
 await page.screenshot({path:'.runtime/realtime-fix-pending.png'});
 await page.evaluate(async id=>{
  await receiveUpdate({status:{enabled:true,controllerId:'t2',remoteControl:true},subscription,threadId:selected,
   jobs:[{id,threadId:'t1',kind:'operation:steer',state:'completed',clientMessageId:'native-added'}],
   history:{...fixture,timeline:[...fixture.timeline,{id:'added',nativeId:'native-added',type:'steeringUserMessage',text:'即时追加验证'}]}},()=>true);
 },sentCompose.body.requestId);
 assert.equal(await page.locator('[data-outgoing]').count(),0);
 finishCompose({id:sentCompose.body.requestId,state:'preparing',kind:'operation:steer'});
 await page.waitForFunction(()=>document.getElementById('prompt').value==='');
 assert.equal(await page.locator('[data-outgoing]').count(),0,'late HTTP must not recreate confirmed message');
 assert(await page.evaluate(()=>window.originalUserNode===document.querySelector('#messages .message.user')),'unchanged message node is reused');
 assert.equal(await page.locator('#messages .text').filter({hasText:'即时追加验证'}).count(),1);
 await page.evaluate(async()=>{await selectThread('t2');await selectThread('t1');});
 assert.equal(socketCount,1,'switching threads reuses WebSocket');
 assert.equal(await page.locator('#messages .text').filter({hasText:'即时追加验证'}).count(),1);
 await page.evaluate(async()=>{streamDisconnected({});});
 assert.equal(await page.locator('#messages .text').filter({hasText:'即时追加验证'}).count(),1);
 assert(await page.locator('#send').isDisabled());
 await page.evaluate(async()=>receiveUpdate({status:{enabled:true,controllerId:'t2',remoteControl:true},subscription,threadId:selected,history:fixture},()=>true));
 const nativeHistory=await page.evaluate(()=>({...fixture,historyRevision:'wire-1',historyWindow:{limit:40,total:80,hasMore:true}}));
 sendWire({type:'update',history:nativeHistory});
 await page.locator('#messages .history-more').filter({hasText:'加载更早记录'}).click();
 assert.equal(activeSelection.historyLimit,80,'earlier records request expands server window');
 sendWire({type:'update',history:{...nativeHistory,historyRevision:'wire-2',historyWindow:{limit:80,total:80,hasMore:false}}});
 await page.waitForFunction(()=>!document.querySelector('#messages .history-more'));
 sendWire({type:'update',historyDelta:{base:'wire-2',fields:{historyRevision:'wire-3'},start:1,delete:1,items:[{id:'a1',type:'agentMessage',text:'增量输出已显示'}]}});
 await page.locator('#messages .text').filter({hasText:'增量输出已显示'}).waitFor();
 sendWire({type:'update',historyDelta:{base:'missing',fields:{historyRevision:'wire-4'},start:0,delete:0,items:[]}});
 await new Promise((resolve,reject)=>{const start=Date.now();const timer=setInterval(()=>{if(socketCount===2){clearInterval(timer);resolve();}else if(Date.now()-start>6000){clearInterval(timer);reject(Error('revision gap did not reconnect'));}},50);});
 sendWire({type:'update',history:{...nativeHistory,historyRevision:'recovered',timeline:[{id:'recovered',type:'agentMessage',text:'版本缺口后恢复完整快照'}]}});
 await page.locator('#messages .text').filter({hasText:'版本缺口后恢复完整快照'}).waitFor();
 assert.deepEqual(errors,[]);
 console.log('PASS: wire deltas, earlier history window, revision gap reconnect and full recovery; immediate submission, native reconciliation without duplicates, cached selection, disconnect preserves conversation and disables sending. HTTP and WS responses mocked.');
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
