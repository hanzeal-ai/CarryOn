const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch();
 try {
  const page=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
  const errors=[],writes=[];let ready=true,publish;
  const status=()=>({enabled:true,protocol:'codex-app-server',controllerId:null,remoteControl:true,accountReady:ready});
  page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{window.CARRYON_CLOUD=true;});
  await page.route('**/console/**',async route=>{
   const req=route.request(),url=new URL(req.url());let data={};
   if(url.pathname.endsWith('/session'))data={devices:[{id:'mac',name:'独立工作区',online:true}]};
   else if(url.pathname.endsWith('/link/pending'))data={requests:[]};
   else if(url.pathname.endsWith('/request')){
    const body=req.postDataJSON(),path=body.path.split('?')[0];
    if(body.method==='POST'){writes.push(body);data={id:body.body.requestId,state:'completed',kind:'create',createdThreadId:'fixture-thread',threadId:'fixture-thread'};}
    else if(path==='/api/status')data=status();
    else if(path==='/api/projects')data={projects:[{id:'recent',name:'最近',cwd:'',total:0,canCreate:ready}],total:1,nextOffset:1};
    else if(path==='/api/threads'||path.endsWith('/threads'))data={threads:[],total:0,nextOffset:0};
    else if(path==='/api/notifications')data={events:[],nextSequence:0};
    else if(path==='/api/jobs')data={jobs:[]};
   }
   await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.routeWebSocket('**/console/devices/*/ws', socket=>{
   let revision=0,selection;
   publish=()=>socket.send(JSON.stringify({type:'update',revision:++revision,resubscribe:true,subscription:selection.subscription,body:{type:'update',subscription:selection.subscription,threadId:selection.threadId,status:status()}}));
   socket.onMessage(raw=>{const value=JSON.parse(raw);if(value.type==='subscribe'){selection=value;publish();}});
  });
  await page.goto(process.env.CARRYON_UI_URL||'http://127.0.0.1:8917/example.html');
  await page.locator('#mobile-session-list .project-row').waitFor();
  await page.locator('#create').click();
  await page.locator('#new-prompt').fill('独立工作区首个会话');
  assert(await page.locator('#submit-create').isEnabled());
  assert.equal(await page.getByRole('button',{name:'控制会话',exact:true}).isVisible(),false);
  await page.locator('#submit-create').click();
  await page.waitForFunction(()=>!document.getElementById('create-dialog').open);
  assert.equal(writes.filter(w=>w.path==='/api/threads').length,1);
  ready=false;publish();
  await page.waitForFunction(()=>document.getElementById('create').disabled);
  ready=true;publish();
  await page.waitForFunction(()=>!document.getElementById('create').disabled);
  await page.evaluate(()=>Operations.render({runtime:{type:'idle'},status:{state:'idle'},controls:{settings:{},requests:[],supportedOperations:['interrupt','steer','compact']},queue:{messages:[],fingerprint:'empty'}},'fixture-thread',{},()=>{}));
  assert.equal(await page.locator('.mobile-session-settings,.mobile-queue').count(),0);
  assert.deepEqual(errors,[]);
  console.log('PASS: independent first creation without controller, missing-login write gate, backend operation capabilities. HTTP/WS mocked.');
 } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
