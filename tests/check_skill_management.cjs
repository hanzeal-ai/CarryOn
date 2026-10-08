const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch();try{for(const [width,scheme] of [[1280,'light'],[390,'light'],[1280,'dark'],[390,'dark']]){
 const page=await browser.newPage({viewport:{width,height:844},colorScheme:scheme}),errors=[],writes=[],jobs=new Map();let reads=0,queries=0,readFailurePhase=0;
 const history={thread:{id:'t1'},historyRevision:'initial',runtime:{type:'idle'},status:{state:'idle'},metadata:{},access:{canInteract:true,nativeReady:true},controls:{supportsSkills:true,supportedOperations:[],supportedSettings:[],requests:[],settings:{}},timeline:[]};
 const skills=[{name:'review',path:'/skills/review/SKILL.md',description:'检查实现与协议的一致性',enabled:true},{name:'frontend',path:'/skills/frontend/SKILL.md',description:'构建可验证的界面与交互',enabled:false}];
 await page.addInitScript(()=>window.CARRYON_CLOUD=true);page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/console/**',async route=>{const req=route.request(),url=new URL(req.url());let data={};
  if(url.pathname.endsWith('/session'))data={devices:[{id:'mac',name:'Mac',online:true,permissions:['view','edit','send']}]};
  else if(url.pathname.endsWith('/request')){const env=req.postDataJSON(),path=env.path.split('?')[0];
   if(env.method==='POST')writes.push(env);
   if(path==='/api/status')data={enabled:true,remoteControl:true};
   else if(path==='/api/projects')data={projects:[],total:0,nextOffset:0};
   else if(path==='/api/workspace/threads')data={threads:[{id:'t1',title:'验证后台任务'}],total:1,nextOffset:1};
   else if(path.endsWith('/history'))data=history;
   else if(path.endsWith('/skills/config')||path.endsWith('/skills')){if(env.method==='POST'){const body={...env.body};delete body.requestId;const job={id:env.body.requestId,threadId:'t1',kind:'skill-config',body,state:'completed',result:{threadId:'t1',path:body.path,enabled:body.enabled}};jobs.set(job.id,job);if(writes.length===2){data={...job,state:'failed',error:'fixture config write rejected'};readFailurePhase=1;}else data={...job,id:'wrong',state:'failed'};}
    else{reads++;if(readFailurePhase===1){readFailurePhase=2;await route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({error:'fixture second read failure'})});return;}if(readFailurePhase===2){readFailurePhase=3;data={skills,errors:[{message:'fixture partial skill errors'}]};}else data={skills,errors:[]};if(reads===1){await route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({error:'fixture inventory unavailable'})});return;}}}
   else if(path.startsWith('/api/jobs/')){queries++;const job=jobs.get(path.split('/').at(-1));data=queries===1?{...job,body:{path:'/wrong',enabled:false},state:'failed'}:job;}
   else if(path==='/api/notifications')data={events:[],nextSequence:0};else if(path==='/api/jobs')data={jobs:[]};else if(path==='/api/models')data={models:[]};
  }else if(url.pathname.endsWith('/streams')&&req.method()==='POST')data={streamId:'s'};else if(url.pathname.includes('/streams/')){await new Promise(r=>setTimeout(r,500));data={revision:1};}
  await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
 });await page.routeWebSocket('**/console/devices/*/ws',()=>{});
 await page.goto(process.env.CARRYON_UI_URL||'http://127.0.0.1:8923/example.html');await page.waitForFunction(()=>enabled);
 await page.evaluate(()=>selectThread('t1'));await page.evaluate(h=>receiveUpdate({status:{enabled:true,remoteControl:true},subscription,threadId:selected,history:h},()=>true),history);
 await page.waitForFunction(()=>composeHistory?.controls?.supportsSkills===true);
 if(width===390){await page.getByRole('button',{name:'会话工具',exact:true}).click();await page.locator('#mobile-tools').getByRole('button',{name:'管理技能',exact:true}).click();}else{await page.getByLabel('会话菜单',{exact:true}).click();await page.locator('#manage-skills').click();}
 const dialog=page.locator('#skill-management-dialog');await dialog.getByRole('status').filter({hasText:'fixture inventory unavailable'}).waitFor();assert.equal(writes.length,0);
 await dialog.getByRole('button',{name:'刷新',exact:true}).click();await dialog.getByRole('button',{name:'停用',exact:true}).first().waitFor();assert.equal(await dialog.getByRole('status').innerText(),'');
 await page.screenshot({path:'.runtime/web-skill-management-'+width+'-'+scheme+'.png',fullPage:true});
 assert(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth+1));await dialog.getByRole('button',{name:'停用',exact:true}).first().focus();await page.evaluate(()=>SkillManagement.update());assert.equal(await page.evaluate(()=>document.activeElement?.textContent),'停用');await page.keyboard.press('Enter');
 await page.waitForFunction(()=>client.operations.has('skill-config')&&!document.querySelector('#skill-management-dialog button:last-child').disabled);assert.equal(writes.length,1);assert(await dialog.getByRole('button',{name:'停用',exact:true}).first().isDisabled());assert.equal(await page.evaluate(()=>document.activeElement?.textContent),'核对原请求');
 await dialog.getByRole('button',{name:'关闭',exact:true}).click();await page.evaluate(()=>SkillManagement.open());await dialog.getByRole('button',{name:'核对原请求',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#skill-management-dialog [role=status]').textContent.includes('身份不匹配'));assert.equal(writes.length,1);
 await dialog.getByRole('button',{name:'核对原请求',exact:true}).click();await page.waitForFunction(()=>!client.operations.has('skill-config'));assert.equal(writes.length,1);
 await dialog.getByRole('button',{name:'停用',exact:true}).first().click();await page.waitForFunction(()=>document.querySelector('#skill-management-dialog [role=status]').textContent.includes('fixture second read failure'));
 assert((await dialog.getByRole('status').innerText()).includes('fixture config write rejected'));assert.equal(writes.length,2);
 await dialog.getByRole('button',{name:'刷新',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#skill-management-dialog [role=status]').textContent.includes('fixture partial skill errors'));assert((await dialog.getByRole('status').innerText()).includes('fixture config write rejected'));
 await dialog.getByRole('button',{name:'刷新',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#skill-management-dialog [role=status]').textContent==='fixture config write rejected');assert.equal(writes.length,2);
 await page.evaluate(()=>{client.devices.find(d=>d.id===client.device).permissions=[];SkillManagement.update();});assert.equal(await dialog.evaluate(el=>el.open),false);assert.equal(errors.length,0,errors.join('\n'));console.log('PASS native skill management UI',width,scheme);await page.close();
 }}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
