/* Isolated native-owner fixtures: no real Codex writes. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const P='11111111-1111-4111-8111-111111111111',C='22222222-2222-4222-8222-222222222222',D='33333333-3333-4333-8333-333333333333';
function history(id,state='idle'){return {thread:{id,title:id===P?'主会话':'侧边聊天'},parentId:id===P?undefined:P,access:{canInteract:true,nativeReady:true},historyRevision:id+state,runtime:{type:state==='running'?'active':'idle'},status:{state,label:state},controls:{supportedOperations:['side-create'],activeTurnId:'active-turn',requests:[],settings:{}},timeline:[{id:'reply',type:'agentMessage',text:'已收到，继续讨论。',data:{}}]};}
(async()=>{const browser=await chromium.launch();const errors=[];fs.mkdirSync('/tmp/carryon-side-dialogue-ui',{recursive:true});
try{for(const width of [1280,390]){
 const page=await browser.newPage({viewport:{width,height:844}});page.on('pageerror',e=>{errors.push(e.message);console.error('PAGE ERROR',e.message)});let requests=[],mode='idle',delay=0,publish,created=false,sideReply='accepted';
 await page.addInitScript(()=>sessionStorage.setItem('carryon-token','fixture-token'));
 await page.route('**/api/**',async route=>{const r=route.request(),path=new URL(r.url()).pathname;let data={};
  if(path==='/api/status')data={enabled:true};
  else if(path==='/api/threads')data={threads:[{id:P,title:'主会话'}]};
  else if(path==='/api/projects')data={projects:[],total:0,nextOffset:0};
  else if(path==='/api/activity')data={threads:[],total:0};
  else if(path==='/api/jobs')data={jobs:[]};
  else if(path==='/api/notifications')data={events:[],nextSequence:0};
  else if(r.method()==='POST'&&path===`/api/threads/${P}/side-chats`){const body=r.postDataJSON();requests.push({path,body});created=true;data={id:body.requestId,parentId:P,createdThreadId:D,state:'completed'};}
  else if(r.method()==='POST'&&path.endsWith('/close')){const body=r.postDataJSON();requests.push({path,body});created=false;data={id:body.requestId,state:'completed',result:{closed:true,threadId:D}};}
  else if(r.method()==='POST'&&path.startsWith('/api/side-chats/')){const body=r.postDataJSON();requests.push({path,body});if(delay)await new Promise(r=>setTimeout(r,delay));data={id:body.requestId,threadId:path.split('/')[3],kind:body.action?'operation:'+body.action:'message',state:sideReply};}
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
 });
 await page.routeWebSocket('**/api/stream',socket=>socket.onMessage(raw=>{const m=JSON.parse(raw);if(m.type!=='subscribe')return;
 publish=()=>socket.send(JSON.stringify({type:'update',threadId:m.threadId,subscription:m.subscription,status:{enabled:true},jobs:[],...(m.threadId?{history:history(P)}:{}),...(m.includeSideChats?{sideChats:{chats:[{id:C,title:'侧边一',label:'空闲'},{id:D,title:'侧边二',label:'空闲',canClose:created}]},sideThreadId:m.sideThreadId,...(m.sideThreadId?{sideHistory:history(m.sideThreadId,mode)}:{})}:{})}));publish();}));
 await page.goto(process.env.CARRYON_UI_URL||'http://127.0.0.1:8898/example.html');await page.waitForFunction(()=>typeof selectThread==='function'&&enabled);
 await page.evaluate(id=>selectThread(id),P);await page.locator('#prompt > [contenteditable]').fill('主会话草稿');
 await page.evaluate(()=>$('open-side').click());await page.locator('#side-select option').filter({hasText:'侧边一'}).waitFor({state:'attached'});
 assert(await page.locator('#side-send').isDisabled());await page.locator('#side-select').selectOption(C);await page.waitForFunction(()=>canSendSide());
 await page.locator('#side-prompt').fill('hello');await page.locator('#side-send').click();await page.waitForFunction(()=>$('side-prompt').value==='');
 assert.equal(requests[0].path,`/api/side-chats/${C}/compose`);assert.equal(requests[0].body.parentId,P);assert.equal(requests[0].body.prompt,'hello');assert(requests[0].body.requestId);
 assert.equal(await page.locator('#prompt').evaluate(el=>el.value),'主会话草稿');
 await page.locator('#side-prompt').fill('侧边一草稿');await page.locator('#side-select').selectOption(D);await page.waitForFunction(()=>canSendSide());assert.equal(await page.locator('#side-prompt').inputValue(),'');await page.locator('#side-prompt').fill('侧边二草稿');
 await page.locator('#side-select').selectOption(C);await page.waitForFunction(()=>canSendSide());assert.equal(await page.locator('#side-prompt').inputValue(),'侧边一草稿');
 mode='running';publish();await page.waitForFunction(()=>sideComposeHistory?.status.state==='running');await page.locator('#side-prompt').fill('');await page.locator('#side-send').click();await page.waitForFunction(()=>!sideSending);
 assert.equal(requests.at(-1).body.action,'interrupt');assert.equal(requests.at(-1).body.expectedTurnId,'active-turn');
 await page.locator('#create-side').click();await page.waitForFunction(id=>sideSelected===id,D);
 await page.evaluate(({parent,child})=>{renderJobs([{id:'side-create-fixture',kind:'side-create',state:'completed',parentId:parent,threadId:parent,createdThreadId:child}]);document.querySelector('#jobs button').click();},{parent:P,child:D});
 await page.waitForFunction(({parent,child})=>selected===parent&&sideSelected===child&&sideOpen,{parent:P,child:D});
 await page.locator('#end-side').click();await page.waitForFunction(()=>sideSelected===null);
 await page.locator('#side-select').selectOption(C);await page.waitForFunction(()=>canSendSide());
 await page.screenshot({path:`/tmp/carryon-side-dialogue-ui/${width}.png`});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 delay=150;await page.locator('#side-prompt').fill('迟到请求');await page.locator('#side-send').click();await page.locator('#side-select').selectOption(D);await page.waitForTimeout(250);assert.equal(await page.locator('#side-prompt').inputValue(),'侧边二草稿');
 // Command creation is committed separately from first-message delivery.
 delay=0;mode='idle';sideReply='uncertain';publish();
 await page.evaluate(()=>closeSide());
 await page.locator('#prompt > [contenteditable]').fill('/side 请解释这里');
 const createCount=()=>requests.filter(r=>r.path===`/api/threads/${P}/side-chats`).length;
 const beforeCommand=createCount();
 await page.evaluate(()=>$('composer').requestSubmit());
 await page.waitForFunction(()=>!sideLifecycleBusy&&$('side-prompt').value==='请解释这里');
 assert.equal(createCount(),beforeCommand+1);assert.equal(await page.locator('#prompt').evaluate(el=>el.value),'');
 const firstUnknown=requests.at(-1);assert.equal(firstUnknown.path,`/api/side-chats/${D}/compose`);
 await page.waitForFunction(()=>canSendSide());await page.locator('#side-send').click();await page.waitForFunction(()=>!sideSending);
 assert.equal(createCount(),beforeCommand+1,'Unknown first message must retry the existing side chat');
 assert.equal(requests.at(-1).body.requestId,firstUnknown.body.requestId);assert.equal(await page.locator('#side-prompt').inputValue(),'请解释这里');
 sideReply='accepted';await page.locator('#side-send').click();await page.waitForFunction(()=>$('side-prompt').value==='');
 await page.evaluate(()=>closeSide());
 await page.locator('#prompt > [contenteditable]').fill('/side 已成功的问题');
 await page.evaluate(()=>$('composer').requestSubmit());await page.waitForFunction(()=>!sideLifecycleBusy&&$('side-prompt').value===''&&$('prompt').value==='');
 assert.equal(requests.at(-1).body.prompt,'已成功的问题');assert.equal(createCount(),beforeCommand+2);
 // Invoke the rendered transcript selection action, not its internal callback.
 await page.evaluate(()=>{closeSide();const node=$('messages').querySelector('article.message .text');const range=document.createRange();range.selectNodeContents(node);getSelection().removeAllRanges();getSelection().addRange(range);});
 await page.locator('.side-selection-action').waitFor();const selectedText=await page.evaluate(()=>getSelection().toString().trim());
 const beforeSelected=requests.length;await page.locator('.side-selection-action').click();await page.waitForFunction(()=>!sideLifecycleBusy&&!!$('side-prompt').value);
 assert.equal(await page.locator('#side-prompt').inputValue(),selectedText);assert.equal(createCount(),beforeCommand+3);
 assert.equal(requests.slice(beforeSelected).filter(r=>r.path.endsWith('/compose')).length,0,'Selected text only seeds a draft');
 await page.evaluate(()=>streamDisconnected({code:1006}));assert(await page.locator('#side-send').isDisabled());
 await page.evaluate(()=>applyStatus({enabled:false}));assert.equal(await page.locator('#side-drawer').isVisible(),false);
 await page.close();
}assert.deepEqual(errors,[]);console.log('PASS side chat: scoped send/stop, drafts, switching, late responses, slash-command migration, uncertain retry identity, selected-text draft, disconnect, desktop/mobile rendering');}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
