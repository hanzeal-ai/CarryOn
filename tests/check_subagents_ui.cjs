/* Real rendered UI with isolated HTTP/WS fixtures; never sends to Codex. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const P='11111111-1111-4111-8111-111111111111',C='22222222-2222-4222-8222-222222222222',R='33333333-3333-4333-8333-333333333333';
const rows=[{id:C,title:'Implementation',access:{isSubagent:true,parentId:P,canInteract:true}},{id:R,title:'Sol release review',access:{isSubagent:true,parentId:P,canInteract:false}}];
function history(id){const thread=rows.find(t=>t.id===id)||{id:P,title:'Main conversation'};return {thread,access:thread.access,historyRevision:id,runtime:{type:'idle'},status:{state:'idle',label:'空闲'},controls:{settings:{model:'native-model'},requests:[],lastTurnId:'turn'},queue:{messages:[],fingerprint:'empty'},timeline:id===P?[
  {id:'parent-text',type:'agentMessage',text:'正在检查发布结果。',data:{}},
  {id:'child-link',type:'subAgentActivity',title:'Sol release review · 已完成',data:{},subagents:[{id:R,title:'Sol release review'}]}
]:[{id:'result',type:'agentMessage',text:'完整审查结果：构建与验证通过。',data:{}},{id:'command',type:'commandExecution',title:'执行命令',data:{command:'echo verified',aggregatedOutput:'verified',status:'completed'}}]};}
(async()=>{
 const browser=await chromium.launch();const errors=[];const screenshots=process.env.CARRYON_SCREENSHOTS||'/tmp/carryon-subagents-ui';fs.mkdirSync(screenshots,{recursive:true});
 try{for(const width of [1280,390]){
  const page=await browser.newPage({viewport:{width,height:844}});page.on('pageerror',e=>errors.push(e.message));
  let children=rows,delay=0,fail=false;
  await page.addInitScript(()=>sessionStorage.setItem('carryon-token','fixture-token'));
  await page.route('**/api/**',async route=>{const path=new URL(route.request().url()).pathname;let data={};
   if(path.endsWith('/subagents')){if(delay)await new Promise(r=>setTimeout(r,delay));if(fail){await route.fulfill({status:500,contentType:'application/json',body:'{"error":"fixture unavailable"}'});return;}data={threads:children};}
   else if(path==='/api/status')data={enabled:true,controllerId:P};
   else if(path==='/api/threads')data={threads:[{id:P,title:'Main conversation'}]};
   else if(path==='/api/projects')data={projects:[],total:0,nextOffset:0};
   else if(path==='/api/activity')data={threads:[],total:0};
   else if(path==='/api/jobs')data={jobs:[]};
   else if(path==='/api/notifications')data={events:[],nextSequence:0};
   await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.routeWebSocket('**/api/stream',socket=>socket.onMessage(raw=>{const m=JSON.parse(raw);if(m.type==='subscribe')socket.send(JSON.stringify({type:'update',threadId:m.threadId,subscription:m.subscription,status:{enabled:true,controllerId:P},...(m.threadId?{history:history(m.threadId)}:{})}));}));
  await page.goto((process.env.CARRYON_UI_URL||'http://127.0.0.1:8897/example.html'));
  await page.waitForFunction(()=>typeof selectThread==='function'&&enabled);
  const parent=async()=>{await page.evaluate(id=>selectThread(id),P);await page.locator('#messages .subagent-links button').waitFor();};
  const menu=async()=>{if(width<760){await page.getByRole('button',{name:'会话工具',exact:true}).click();await page.getByRole('button',{name:'子会话',exact:true}).click();}else{await page.locator('summary[aria-label="会话菜单"]').click();await page.locator('#open-subagents').click();}};
  await parent();await page.locator('#prompt').fill('parent draft');await menu();
  await page.getByRole('button',{name:'Sol release review · 只读',exact:true}).waitFor();
  await page.screenshot({path:`${screenshots}/${width}-list.png`});
  await page.getByRole('button',{name:'Sol release review · 只读',exact:true}).click();
  await page.waitForFunction(id=>selected===id&&composeHistory?.thread.id===id,R);
  assert.equal(await page.locator('#composer').isVisible(),false);
  assert.equal(await page.locator('#messages').innerText().then(t=>t.includes('完整审查结果')),true);
  await page.locator('#messages details.activity-group').evaluate(e=>e.open=true);await page.locator('#messages details.activity').evaluate(e=>e.open=true);
  assert((await page.locator('#messages').innerText()).includes('verified'));
  await page.screenshot({path:`${screenshots}/${width}-readonly.png`});
  await parent();assert.equal(await page.locator('#prompt').inputValue(),'parent draft');
  await page.locator('#messages .subagent-links button').click();await page.waitForFunction(id=>selected===id,R);
  children=[rows[0]];await parent();await menu();await page.waitForFunction(id=>selected===id&&composeHistory?.thread.id===id,C);
  assert.equal(await page.locator('.subagents-dialog').count(),0);assert.equal(await page.locator('#composer').isVisible(),true);
  await page.screenshot({path:`${screenshots}/${width}-interactive.png`});
  await page.evaluate(h=>receiveUpdate({type:'update',threadId:selected,subscription,status:{enabled:true},history:h},()=>true),{...history(C),historyRevision:'unready',access:{...rows[0].access,nativeReady:false}});
  assert.equal(await page.locator('#composer').isVisible(),true);assert.equal(await page.locator('#send').isDisabled(),true);
  children=[];await parent();await menu();await page.getByText('暂无子会话',{exact:true}).waitFor();await page.locator('.subagents-dialog').getByRole('button',{name:'关闭'}).click();
  fail=true;await menu();await page.locator('.subagents-dialog').getByRole('button',{name:'重试'}).waitFor();fail=false;children=rows;await page.locator('.subagents-dialog').getByRole('button',{name:'重试'}).click();await page.getByRole('button',{name:'Sol release review · 只读',exact:true}).waitFor();await page.locator('.subagents-dialog').getByRole('button',{name:'关闭'}).click();
  delay=150;await menu();await page.evaluate(id=>selectThread(id),C);await page.waitForTimeout(250);assert.equal(await page.locator('.subagents-dialog').count(),0);assert.equal(await page.evaluate(()=>selected),C);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.evaluate(()=>streamDisconnected({code:1006}));assert.equal(await page.locator('#send').isDisabled(),true);
  await page.close();
 }
 const cloud=await browser.newPage({viewport:{width:1280,height:844}});cloud.on('pageerror',e=>errors.push(e.message));let authenticated=true;
 await cloud.addInitScript(()=>window.CARRYON_CLOUD=true);
 await cloud.route('**/console/**',async route=>{
  const request=route.request(),path=new URL(request.url()).pathname;let data={},status=200;
  if(path.endsWith('/session')){if(!authenticated){status=401;data={error:'请先登录'};}else data={devices:[{id:'one',name:'One',online:true},{id:'two',name:'Two',online:true}]};}
  else if(path.endsWith('/logout'))authenticated=false;
  else if(path.endsWith('/link/pending'))data={requests:[]};
  else if(path.endsWith('/request')){const api=request.postDataJSON().path.split('?')[0];
   if(api.endsWith('/subagents')){await new Promise(r=>setTimeout(r,200));data={threads:rows};}
   else if(api==='/api/status')data={enabled:true,controllerId:P,remoteControl:true};
   else if(api==='/api/projects')data={projects:[],total:0};
   else if(api==='/api/threads')data={threads:[{id:P,title:'Main'}]};
   else if(api==='/api/jobs')data={jobs:[]};
   else if(api==='/api/notifications')data={events:[],nextSequence:0};
  }
  await route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
 });
 await cloud.routeWebSocket('**/console/devices/*/ws',socket=>{let revision=0;socket.onMessage(raw=>{const m=JSON.parse(raw);if(m.type==='subscribe')socket.send(JSON.stringify({type:'update',resubscribe:true,revision:++revision,subscription:m.subscription,body:{type:'update',threadId:m.threadId,subscription:m.subscription,status:{enabled:true,controllerId:P,remoteControl:true},...(m.threadId?{history:history(m.threadId)}:{})}}));});});
 await cloud.goto(process.env.CARRYON_UI_URL||'http://127.0.0.1:8897/example.html');await cloud.waitForFunction(()=>enabled);
 await cloud.evaluate(id=>selectThread(id),P);await cloud.locator('#messages .subagent-links button').waitFor();
 await cloud.evaluate(()=>{subagentNavigation.show();$('console-device').value='two';$('console-device').dispatchEvent(new Event('change'));});
 await cloud.waitForFunction(()=>client.device==='two'&&enabled);await cloud.waitForTimeout(250);assert.equal(await cloud.locator('.subagents-dialog').count(),0);assert.equal(await cloud.evaluate(()=>selected),null);
 await cloud.evaluate(id=>selectThread(id),P);await cloud.locator('#messages .subagent-links button').waitFor();
 await cloud.evaluate(()=>{subagentNavigation.show();$('console-logout').click();});await cloud.locator('#pairing').waitFor();await cloud.waitForTimeout(250);assert.equal(await cloud.locator('.subagents-dialog').count(),0);assert.equal(await cloud.evaluate(()=>selected),null);
 await cloud.close();
 assert.deepEqual(errors,[]);console.log('PASS desktop/mobile: navigation, readonly/ready gates, drafts, errors, disconnect; cloud device switch/logout reject late directories');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
