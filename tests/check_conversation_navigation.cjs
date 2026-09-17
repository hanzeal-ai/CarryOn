const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch();
 try { for(const width of [1280,390]){
 const page=await browser.newPage({viewport:{width,height:844}});
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

 await page.goto('http://127.0.0.1:8923/example.html');
 await page.waitForFunction(()=>typeof Timeline!=='undefined'&&enabled);
 await page.evaluate(async()=>{
   workspaceView='activity';await selectThread('t1');
   window.navigationFixture={thread:{id:'t1'},historyRevision:'nav1',runtime:{type:'idle'},status:{state:'idle'},metadata:{},timeline:[
      ...Array.from({length:145},(_,i)=>({id:'m'+i,type:i%2?'agentMessage':'userMessage',turnId:'turn0',text:'消息 '+i+'\n'+('内容用于验证消息定位。'.repeat(14))})),
      {id:'turn1',type:'turn',turnId:'turn1',status:'completed'},
      {id:'result',type:'agentMessage',turnId:'turn1',text:'动态对应的结果'},
      {id:'later',type:'commandExecution',turnId:'turn1',title:'后续记录',data:{command:'pwd'}}]};
   await receiveUpdate({status:{enabled:true,controllerId:'t2',remoteControl:true},subscription,threadId:selected,history:navigationFixture},()=>true);
 });
 await page.waitForFunction(()=>document.querySelector('.conversation-navigator button.active')?.dataset.anchor==='result');
 async function assertRailCentered(){const delta=await page.locator('.conversation-navigator').evaluate(n=>{const r=n.getBoundingClientRect(),v=(document.querySelector('#messages').closest('.mobile-chat-scroll')||document.querySelector('#messages')).getBoundingClientRect();return Math.abs(r.y+r.height/2-v.y-v.height/2);});assert(delta<2,'navigation rail must be centered: '+delta);}
 await assertRailCentered();
 assert.equal(await page.locator('.conversation-navigator button').count(),147);
 assert.equal(await page.locator('.conversation-navigator').evaluate(n=>getComputedStyle(n).position),'fixed');
 assert.equal(await page.locator('.conversation-navigator').evaluate(n=>getComputedStyle(n).backgroundColor),'rgba(0, 0, 0, 0)');
 const widths=await page.locator('.conversation-navigator button').evaluateAll(nodes=>nodes.slice(-6).map(n=>parseFloat(n.firstChild.style.width)));
 assert.deepEqual(widths,width<=760?[6,10,16,22,28,22]:[12,20,28,40,52,40]);
 const beforePreview=await page.evaluate(()=>{const v=document.querySelector('#messages').closest('.mobile-chat-scroll')||document.querySelector('#messages');return {scroll:v.scrollTop,count:document.querySelector('#messages').childElementCount};});
 await page.locator('.conversation-navigator button[data-anchor="result"]').hover();
 await page.locator('.conversation-navigation-preview').waitFor();
 assert((await page.locator('.conversation-navigation-preview').textContent()).includes('动态对应的结果'));
 await page.screenshot({path:'.runtime/navigation-preview-'+width+'.png'});
 await page.locator('.conversation-navigator').dispatchEvent('wheel',{deltaY:30});
 await page.waitForFunction(()=>document.querySelector('.conversation-navigator button.active')?.dataset.anchor==='later');
 await assertRailCentered();
 assert((await page.locator('.conversation-navigation-preview').textContent()).includes('后续记录'));
 assert.equal(await page.locator('.conversation-navigation-preview button').count(),0);
 await page.mouse.move(300,40);
 await page.waitForFunction(()=>!document.querySelector('.conversation-navigation-preview'));
 await page.waitForFunction(()=>document.querySelector('.conversation-navigator button.active')?.dataset.anchor==='result');
 const afterPreview=await page.evaluate(()=>{const v=document.querySelector('#messages').closest('.mobile-chat-scroll')||document.querySelector('#messages');return {scroll:v.scrollTop,count:document.querySelector('#messages').childElementCount};});
 assert.deepEqual(afterPreview,beforePreview,'preview must not move or render the message list');
 await page.evaluate(()=>{const container=document.querySelector('#messages');window.previewMutationCount=0;window.previewObserver=new MutationObserver(m=>window.previewMutationCount+=m.length);previewObserver.observe(container,{childList:true,subtree:true});const buttons=[...document.querySelectorAll('.conversation-navigator button')];for(let i=0;i<200;i++)buttons[i%buttons.length].dispatchEvent(new PointerEvent('pointerenter',{pointerType:'mouse'}));document.querySelector('.conversation-navigator').dispatchEvent(new PointerEvent('pointerleave'));});
 assert.equal(await page.evaluate(()=>{previewObserver.disconnect();return previewMutationCount;}),0,'rapid preview must not rebuild messages');


 assert.equal(await page.evaluate(()=>Timeline.activityAnchor({controls:{requests:[{params:{itemId:'native-approval',turnId:'old'}}]},timeline:[{id:'approval',nativeId:'native-approval',turnId:'old',type:'commandExecution'},{id:'new',turnId:'new',type:'agentMessage',text:'new'}]})),'approval');
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 await page.locator('.conversation-navigator').evaluate(n=>{n.scrollTop=0;});
 await page.waitForTimeout(60);
 assert.equal(await page.locator('.conversation-navigator').evaluate(n=>n.scrollTop),0);

 await page.locator('.conversation-navigator button[data-anchor="m0"]').click();
 await page.waitForFunction(()=>document.querySelector('.conversation-navigator button.active')?.dataset.anchor==='m0');
 await assertRailCentered();
 assert(await page.locator('[data-navigation-id="m0"]').isVisible());
 await page.evaluate(()=>Timeline.navigateTo('later'));
 await page.waitForFunction(()=>document.querySelector('.conversation-navigator button.active')?.dataset.anchor==='later');
 assert(await page.locator('[data-navigation-id="later"]').evaluate(n=>n.open));
 await page.evaluate(()=>{const v=document.querySelector('#messages').closest('.mobile-chat-scroll')||document.querySelector('#messages');v.dispatchEvent(new WheelEvent('wheel',{bubbles:true}));v.scrollTop=v.scrollHeight/2;});
 await page.waitForFunction(()=>!['later','m0','result'].includes(document.querySelector('.conversation-navigator button.active')?.dataset.anchor));
 await page.screenshot({path:'.runtime/navigation-'+width+'.png'});
 await page.evaluate(()=>{Timeline.reset();Timeline.render({thread:{id:'fold'},timeline:[{id:'tool-image',type:'mcpToolCall',title:'图片输出',artifacts:[{id:'art',kind:'image'}]},{id:'running-command',type:'commandExecution',status:'inProgress',title:'运行命令',data:{command:'pwd'}}]},document.querySelector('#messages'));});
 assert.equal(await page.locator('#messages details[open]').count(),0);
 await page.evaluate(()=>Timeline.reset());
 assert.equal(await page.locator('.conversation-navigator').count(),0);
 assert.deepEqual(errors,[]);
 await page.close();
 }
 console.log('PASS: both Web layouts, activity anchor highlight, earlier history, folded events, scrolling and reset.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
