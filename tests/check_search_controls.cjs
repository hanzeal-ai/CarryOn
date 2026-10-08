const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch();
 try { for(const [width,scheme] of [[1280,'light'],[390,'light'],[1280,'dark'],[390,'dark']]){
 const page=await browser.newPage({viewport:{width,height:844},colorScheme:scheme});
 const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.log('PAGEERROR',e.stack)});let authenticated=true;
 const writes=[],reads=[];
 const defaultHistory={thread:{id:'t1'},historyRevision:'initial',runtime:{type:'idle'},status:{state:'idle'},metadata:{},access:{nativeReady:true,canInteract:true},controls:{supportedOperations:['rename'],supportedSettings:[],requests:[],settings:{}},timeline:[]};const threads=[{id:'t1',title:'让手机上的对话更顺手',cwd:'/workspace/CarryOn',unread:true},{id:'t2',title:'检查远端连接',cwd:'/workspace/CarryOn',unread:false}];
 const allThreads=threads;
 const projects=[{id:'p1',name:'CarryOn',cwd:'/workspace/CarryOn',total:12,waiting:1,running:2,unread:3,unknown:0},{id:'p2',name:'MarkFix',cwd:'/workspace/MarkFix',total:8,waiting:0,running:0,unread:1,unknown:0}];
 await page.addInitScript(()=>{window.CARRYON_CLOUD=true;});
 await page.route('**/console/**',async route=>{
  const req=route.request(),u=new URL(req.url());let data={},status=200;
  if(u.pathname.endsWith('/session')){if(!authenticated){status=401;data={error:'请先登录云端控制台'};}else data={devices:[{id:'mac',name:'我的 MacBook',online:true,permissions:['view']},{id:'other',name:'工作室 Mac',online:true,permissions:['view']}]};}
  else if(u.pathname.endsWith('/login'))authenticated=true;
  else if(u.pathname.endsWith('/logout'))authenticated=false;
  else if(u.pathname.endsWith('/binding/pending'))data={requests:[]};
  else if(u.pathname.endsWith('/request')){
   const body=req.postDataJSON(),path=body.path.split('?')[0];if(body.method==='POST')writes.push(body);else reads.push(body.path);
   if(path==='/api/status')data={enabled:true,remoteControl:false,supportsFullTextSearch:true};
   else if(path==='/api/models')data={models:[{id:'fixture-model',name:'Fixture Model',efforts:['medium','high'],defaultEffort:'medium'},{id:'gpt-6-astra',name:'GPT-6 Astra',efforts:['medium','high'],defaultEffort:'medium'}]};
   else if(path==='/api/projects')data={projects,total:2,nextOffset:2};
   else if(path==='/api/workspace/threads'){const query=new URL('http://fixture'+body.path).searchParams,offset=Number(query.get('offset')||0);data={threads:allThreads.slice(offset,offset+100),total:allThreads.length,nextOffset:offset+100};}
   else if(path==='/api/threads'||path==='/api/projects/p1/threads')data={threads,total:2,nextOffset:2};
   else if(path==='/api/activity')data={threads:[threads[1]],total:1,nextOffset:1};
   else if(path==='/api/search'){const query=new URL('http://fixture'+body.path).searchParams;const term=query.get('search');if(term==='late')await new Promise(resolve=>setTimeout(resolve,700));data={threads:query.has('cursor')?[{...threads[1],snippet:'second match'}]:[{...threads[0],snippet:term+' first match'}],nextCursor:query.has('cursor')?null:'native-opaque|cursor'};}
   else if(path==='/api/threads/t1/search-anchor')data={threadId:'t1',itemId:'hit',turnId:'turn',historyLimit:3};
   else if(path==='/api/threads/t1/history')data={...defaultHistory,thread:{id:'t1'},timeline:[{id:'native-hit',nativeId:'hit',turnId:'turn',type:'agentMessage',status:'completed',data:{text:'MATCHED MESSAGE'}},...Array.from({length:140},(_,index)=>({id:'later-'+index,turnId:'later-turn',type:'agentMessage',status:'completed',data:{text:'later message '+index}}))]};
   else if(path==='/api/threads/t1/search'){await new Promise(resolve=>setTimeout(resolve,700));data={threadId:'t1',occurrences:[{itemId:'hit',turnId:'turn',turnCursor:'native-turn-cursor',snippet:'fixture 中文命中',snippetMatchRange:{start:0,end:7}}],nextCursor:null};}
   else if(path==='/api/notifications')data={events:[],nextSequence:0};
   else if(path==='/api/notifications/preferences')data={preferences:{message:true,done:true,failed:true,approval:true,...body.body}};
   else if(path==='/api/standby')data={supported:true,effective:true,enabled:true};
  }else if(u.pathname.endsWith('/streams')&&req.method()==='POST')data={streamId:'s'};
  else if(u.pathname.includes('/streams/')&&req.method()==='GET'){await new Promise(r=>setTimeout(r,1000));data={revision:1};}
  await route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
 });
 await page.routeWebSocket('**/console/devices/*/ws', socket=>{
  let revision=0;
  socket.onMessage(raw=>{const selection=JSON.parse(raw);if(selection.type==='subscribe')socket.send(JSON.stringify({type:'update',revision:++revision,resubscribe:true,subscription:selection.subscription,body:{type:'update',subscription:selection.subscription,threadId:selection.threadId,status:{enabled:true,remoteControl:false,supportsFullTextSearch:true}}}));});
 });

 await page.goto(process.env.CARRYON_UI_URL||'http://127.0.0.1:8923/example.html');
 if(width<761){await page.getByRole('button',{name:'我的',exact:true}).click();await page.getByRole('button',{name:'搜索会话内容',exact:true}).click();}
 else await page.locator('#search-content').click();
 const dialog=page.getByRole('dialog',{name:'搜索会话内容',exact:true}),input=dialog.getByRole('searchbox',{name:'搜索消息内容',exact:true});
 await input.fill('fixture');await dialog.locator('.search-result').first().waitFor();
 await dialog.getByRole('button',{name:'加载更多',exact:true}).click();await page.waitForFunction(()=>document.querySelectorAll('.search-dialog .search-result').length===2);
 assert(reads.some(path=>path.includes('cursor=native-opaque%7Ccursor')),'opaque native cursor preserved');
 await dialog.locator('.search-result').first().click();await page.waitForFunction(()=>document.querySelector('.search-dialog .search-result span')?.textContent==='fixture 中文命中');
 assert.equal(await dialog.locator('mark').textContent(),'fixture','UTF-16 occurrence range highlighted');
 await page.screenshot({path:'.runtime/web-search-'+width+'-'+scheme+'.png'});
 await dialog.getByRole('button',{name:'返回结果',exact:true}).focus();await dialog.getByRole('button',{name:'返回结果',exact:true}).press('Enter');
 await page.waitForFunction(()=>document.querySelector('.search-dialog .search-result span')?.textContent==='fixture first match');
 assert.equal(await input.inputValue(),'fixture','return preserves original search');
 await dialog.locator('.search-result').first().click();
 await dialog.getByRole('button',{name:'返回结果',exact:true}).press('Enter');
 await page.waitForFunction(()=>document.querySelector('.search-dialog .search-result span')?.textContent==='fixture first match');await page.waitForTimeout(800);
 assert.equal(await dialog.locator('.search-result span').textContent(),'fixture first match','late occurrence cannot overwrite returned global search');
 assert(await input.evaluate(node=>document.activeElement===node),'return restores focus to search input');
 await dialog.getByRole('button',{name:'加载更多',exact:true}).click();await page.waitForFunction(()=>document.querySelectorAll('.search-dialog .search-result').length===2);
 await dialog.locator('.search-result').first().click();await page.waitForFunction(()=>document.querySelector('.search-dialog .search-result span')?.textContent==='fixture 中文命中');
 await dialog.locator('.search-result').first().click();
 await page.waitForFunction(()=>document.querySelector('[data-navigation-id="native-hit"]'));
 await page.waitForTimeout(250);
 assert(await page.evaluate(()=>{const hit=document.querySelector('[data-navigation-id="native-hit"]'),viewport=hit.closest('.mobile-chat-scroll')||document.querySelector('#messages');const a=hit.getBoundingClientRect(),b=viewport.getBoundingClientRect();return a.bottom>b.top&&a.top<b.bottom;}),'native search hit is in actual reading viewport');
 assert(reads.some(path=>path==='/api/threads/t1/history?limit=3'),'native tail window used');
 await page.screenshot({path:'.runtime/web-search-anchor-'+width+'-'+scheme+'.png'});
 await page.evaluate(()=>SearchControls.open());await input.fill('late');await page.waitForTimeout(300);await input.fill('current');
 await page.waitForFunction(()=>document.querySelector('.search-dialog .search-result span')?.textContent==='current first match');await page.waitForTimeout(800);
 assert.equal(await dialog.locator('.search-result span').textContent(),'current first match','late query cannot overwrite current results');
 await dialog.getByRole('button',{name:'关闭',exact:true}).click();await page.evaluate(()=>SearchControls.open());await input.fill('late');await page.waitForTimeout(300);
 await page.evaluate(()=>{client.devices.find(device=>device.id===client.device).permissions=[];SearchControls.update();});
 assert.equal(await page.locator('.search-dialog').evaluate(node=>node.open),false);await page.waitForTimeout(800);
 assert.equal(writes.length,0,'read-only content search emits no writes');assert.deepEqual(errors,[]);
 console.log('PASS content search '+width+' '+scheme);await page.close();
 }}finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
