/* Real rendered mobile UI under slow, empty and failed HTTP/WS responses. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch();
 try{
 const page=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let gate=null,failPreferences=false,projectCalls=0;
 const project={id:'p',name:'ConnectNow',total:2};
 const thread={id:'t',title:'加载状态验证',cwd:'/workspace',status:{state:'idle'}};
 await page.addInitScript(()=>{window.CONNECTNOW_CLOUD=true;});
 await page.route('**/console/**',async route=>{
  const url=new URL(route.request().url());let data={},status=200;
  if(url.pathname.endsWith('/session'))data={devices:[{id:'mac',name:'Mac',online:true}]};
  else if(url.pathname.endsWith('/link/pending'))data={requests:[],history:[]};
  else if(url.pathname.endsWith('/request')){
   const body=route.request().postDataJSON(),path=body.path.split('?')[0];
   if(gate?.path===path){const current=gate;gate=null;current.entered();await current.promise;}
   if(path==='/api/projects'){projectCalls++;const searching=body.path.includes('search=missing');const more=new URLSearchParams(body.path.split('?')[1]).get('offset')!=='0';data={projects:searching?[]:[more?{...project,id:'p2',name:'另一个项目'}:project],total:searching?0:2,nextOffset:more?2:1};}
   else if(path==='/api/projects/p/threads'||path==='/api/threads')data={threads:[thread],total:1,nextOffset:1};
   else if(path==='/api/status')data={enabled:true,remoteControl:true,controllerId:'t'};
   else if(path==='/api/activity')data={threads:[],total:0,nextOffset:0};
   else if(path==='/api/notifications')data={events:[],nextSequence:0};
   else if(path==='/api/notifications/preferences'){
    if(failPreferences){status=503;data={error:'读取失败，请稍后重试'};}
    else data={preferences:{message:true,done:true,failed:true,approval:true,...body.body}};
   }
  }
  await route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
 });
 await page.routeWebSocket('**/ws',socket=>{let revision=0;socket.onMessage(raw=>{const m=JSON.parse(raw);if(m.type==='subscribe')socket.send(JSON.stringify({type:'update',resubscribe:true,revision:++revision,subscription:m.subscription,body:{type:'update',threadId:m.threadId,subscription:m.subscription,status:{enabled:true,remoteControl:true,controllerId:'t'}}}));});});
 function hold(path){let release,entered;const promise=new Promise(r=>release=r),started=new Promise(r=>entered=r);gate={path,promise,entered};return {release,started};}
 const base=process.env.CONNECTNOW_UI_URL||'http://127.0.0.1:8989/example.html';
 await page.goto(base);await page.locator('#mobile-session-list .project-row').waitFor();
 let slow=hold('/api/projects');await page.evaluate(()=>{window.refreshResult=loadThreads();});await slow.started;
 assert.equal(await page.locator('#mobile-session-list .loading-spinner').count(),1);
 assert.equal(await page.locator('#mobile-session-list .project-row').count(),1,'refresh retains content');
 assert.equal(await page.locator('#mobile-session-list [data-state=empty]').count(),0);
 await page.screenshot({path:'.runtime/loading-refresh.png'});slow.release();await page.evaluate(()=>window.refreshResult);
 slow=hold('/api/projects');await page.locator('#more').click();await slow.started;
 assert.equal(await page.locator('#mobile-session-list .loading-spinner').count(),0,'pagination owns its indicator');
 assert(await page.locator('#more').isDisabled());slow.release();await page.waitForFunction(()=>!document.getElementById('more').disabled);
 await page.locator('#search').fill('missing');await page.locator('#mobile-session-list [data-state=empty]').waitFor();
 assert.match(await page.locator('#mobile-session-list').innerText(),/没有搜索结果/);
 await page.getByRole('button',{name:'清除搜索',exact:true}).click();await page.locator('#mobile-session-list .project-row').first().waitFor();
 slow=hold('/api/projects/p/threads');await page.locator('#mobile-session-list .project-row').first().click();await slow.started;
 assert.equal(await page.locator('#mobile-session-list .loading-spinner').count(),1);
 assert.equal(await page.locator('#mobile-session-list [data-state=empty]').count(),0);
 assert(await page.locator('#more').isHidden(),'new query resets pagination');slow.release();
 await page.locator('#mobile-session-list .session').first().click();
 await page.evaluate(async()=>{await receiveUpdate({type:'update',threadId:selected,subscription,status:{enabled:true,remoteControl:true},history:{thread:{id:selected},timeline:[],syncing:true,runtime:{type:'active'},controls:{}}},()=>true);});
 assert.equal(await page.locator('.mobile-chat-scroll .loading-spinner').count(),1);
 assert(await page.locator('.running-label').isHidden());
 assert(!/暂无会话记录/.test(await page.locator('#messages').innerText()));
 await page.evaluate(async()=>receiveUpdate({type:'update',threadId:selected,subscription,status:{enabled:true,remoteControl:true},error:'原生读取失败'},()=>true));
 assert.equal(await page.locator('#messages .loading-spinner').count(),0);
 assert.equal(await page.locator('#messages [data-state=error]').count(),1);
 await page.locator('#messages').getByRole('button',{name:'重试'}).click();
 await page.evaluate(async()=>receiveUpdate({type:'update',threadId:selected,subscription,status:{enabled:true,remoteControl:true},history:{thread:{id:selected},timeline:[],runtime:{type:'idle'},controls:{settings:{},requests:[]}}},()=>true));
 assert.equal(await page.locator('#messages [data-state=empty]').count(),1);
 await page.screenshot({path:'.runtime/loading-chat-empty.png'});
 await page.evaluate(async()=>receiveUpdate({type:'update',threadId:selected,subscription,status:{enabled:true,remoteControl:true},history:{thread:{id:selected},timeline:Array.from({length:40},(_,i)=>({id:String(i),type:'agentMessage',text:'消息 '+i+'\n'+('详细内容\n'.repeat(8))})),runtime:{type:'idle'},controls:{settings:{},requests:[]}}},()=>true));
 await page.locator('.mobile-chat-scroll').evaluate(el=>{el.scrollTop=0;});
 await page.getByRole('button',{name:'回到最新消息'}).waitFor();await page.getByRole('button',{name:'回到最新消息'}).click();
 await page.waitForFunction(()=>{const el=document.querySelector('.mobile-chat-scroll');return el.scrollHeight-el.scrollTop-el.clientHeight<160;});
 await page.getByRole('button',{name:'返回会话',exact:true}).click();await page.getByRole('button',{name:'我的',exact:true}).click();
 failPreferences=true;slow=hold('/api/notifications/preferences');await page.getByRole('button',{name:'消息通知',exact:true}).click();await slow.started;
 assert(await page.locator('#notification-dialog').isVisible());assert.equal(await page.locator('#notification-dialog .loading-spinner').count(),1);
 slow.release();await page.locator('#notification-dialog [data-state=error]').waitFor();
 assert.equal(await page.locator('#notification-dialog .loading-spinner').count(),0);
 await page.screenshot({path:'.runtime/loading-preferences-error.png'});
 failPreferences=false;await page.locator('#notification-dialog').getByRole('button',{name:'重试'}).click();await page.getByRole('switch').first().waitFor();
 assert.equal(await page.getByRole('switch').count(),4);
 assert.deepEqual(errors,[]);console.log('PASS: single loading owner, refresh retention, pagination reset, search clear, chat preview/error/empty, jump to latest, notification retry.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
