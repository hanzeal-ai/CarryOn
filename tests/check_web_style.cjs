const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
require('node:fs').mkdirSync('.runtime/web-style',{recursive:true});
(async()=>{
const browser=await chromium.launch();
for(const width of [390,1440,320,768])for(const colorScheme of ['light','dark']){
 const page=await browser.newPage({viewport:{width,height:900},colorScheme});
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
 await page.locator(width<761?'#mobile-session-list .project-row':'#threads button').first().waitFor();
 await page.evaluate(async()=>receiveUpdate({status:{enabled:true,controllerId:'t2',remoteControl:true},subscription,threadId:selected},()=>true));

 const prefix='.runtime/web-style/'+width+'-'+colorScheme;
 await page.screenshot({path:prefix+'-projects.png'});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'no page overflow');
 if(width<761){
  await page.getByRole('button',{name:'我的',exact:true}).click();
  await page.screenshot({path:prefix+'-settings.png'});
  await page.getByRole('button',{name:'会话',exact:true}).click();
  await page.locator('#mobile-session-list .project-row').first().click();
  await page.locator('.session').first().click();
 }else{
  await page.locator('#threads button').first().click();
  await page.locator('#threads .thread').first().click();
 }
 await page.evaluate(async()=>{
  const history={thread:{id:selected},runtime:{type:'active'},status:{state:'running',label:'进行中'},metadata:{latestModel:'gpt-6-astra'},controls:{activeTurnId:'turn1',settings:{model:'gpt-6-astra',effort:'medium'},requests:[]},queue:{messages:[],fingerprint:'q'},timeline:[{id:'u1',type:'userMessage',text:'统一网页端的风格，保留现有功能。'},{id:'a1',type:'agentMessage',text:'已统一页面的视觉层级。\n\n- 移动网页保持与手机端一致\n- 桌面网页适配宽屏和鼠标操作\n\n```swift\nlet theme = Color.primary\nprint("CarryOn")\n```'}]};
  await receiveUpdate({status:{enabled:true,controllerId:'t2',remoteControl:true},subscription,threadId:selected,history,readSequence:2},()=>true);
 });
 await page.screenshot({path:prefix+'-chat.png'});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'chat stays within viewport');
 if(width<761){
  await page.locator('#prompt').fill('短句');await page.waitForTimeout(100);
  assert(!await page.locator('#composer .input-shell').evaluate(e=>e.classList.contains('expanded')));
  const gap=await page.evaluate(()=>{const a=document.querySelector('#attach-images').getBoundingClientRect(),b=document.querySelector('#composer .model-button').getBoundingClientRect();return b.x+b.width/2-a.x-a.width/2;});assert.equal(gap,32);
  await page.locator('#prompt').fill('这是一段连续输入的长文字，用来确认超过一行后会展开输入区域，并且保留现有的发送和停止按钮。');await page.waitForTimeout(100);
  assert(await page.locator('#composer .input-shell').evaluate(e=>e.classList.contains('expanded')));
  await page.screenshot({path:prefix+'-expanded.png'});
  await page.locator('#prompt').fill('');await page.waitForTimeout(100);
  assert(!await page.locator('#composer .input-shell').evaluate(e=>e.classList.contains('expanded')));
 }
 assert.deepEqual(errors,[]);assert(writes.every(w=>w.path==='/api/notifications/read'),'only read acknowledgements');
 
 if(width<761){
  await page.getByRole('button',{name:'查看当前模型与思考强度',exact:true}).click();
  await page.screenshot({path:prefix+'-model.png'});await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'会话工具',exact:true}).click();
  await page.screenshot({path:prefix+'-tools.png'});await page.keyboard.press('Escape');
 }else{
  await page.locator('#create').click();await page.screenshot({path:prefix+'-create.png'});await page.keyboard.press('Escape');
 }
 authenticated=false;await page.reload();await page.locator('#pairing').waitFor();await page.screenshot({path:prefix+'-login.png'});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'login stays within viewport');
 console.log(width,colorScheme,'passed');await page.close();
}
await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
