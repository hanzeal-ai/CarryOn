const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch();
 try {for(const width of [1280,390]){
  const page=await browser.newPage({viewport:{width,height:844}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.setContent('<section class="session-actions"><div id="operations"></div></section><div id="requests"></div><div id="messages"></div><dialog id="question-dialog"><button id="question-later"></button><div id="question-content"></div></dialog>');
  await page.addScriptTag({path:path.resolve('operations.js')});
  await page.evaluate(()=>{
   window.mobileLayout={matches:false};window.writes=[];window.mode='ok';
   window.catalog={models:[{id:'model-a',name:'Model A',efforts:['low','high'],defaultEffort:'high'},{id:'model-b',name:'Model B',efforts:['medium'],defaultEffort:'medium'}]};
   window.api={epoch:1,request:async path=>{if(path!=='/models')throw Error('unexpected path');if(mode==='fail')throw Error('offline');if(mode==='delay')return new Promise(resolve=>window.resolveCatalog=resolve);return catalog;},operation:async(target,action,fields)=>{writes.push({target,action,fields});if(window.deferWrite)return new Promise(resolve=>window.resolveWrite=resolve);return {state:'completed'};}};
   window.historyFixture={controls:{settings:{model:'model-a',effort:'low'},requests:[]},runtime:{type:'idle'},status:{state:'idle'},timeline:[]};
   window.render=(canWrite=true)=>Operations.render(historyFixture,'thread-a',api,()=>{},canWrite);
   render();
  });
  const settings=page.locator('.mobile-session-settings');await settings.getByText('会话设置',{exact:true}).click();
  const model=settings.getByLabel('模型',{exact:true}),effort=settings.getByLabel('思考强度',{exact:true}),save=settings.getByRole('button',{name:'保存设置',exact:true});
  await page.waitForFunction(()=>document.querySelector('[data-draft-key="模型"]').options.length===2);
  assert.deepEqual(await effort.locator('option').allTextContents(),['low','high']);
  await model.selectOption('model-b');assert.deepEqual(await effort.locator('option').allTextContents(),['medium']);
  assert.equal(await effort.inputValue(),'medium');await save.click();
  assert.deepEqual(await page.evaluate(()=>writes[0]),{target:'thread-a',action:'settings',fields:{settings:{model:'model-b',effort:'medium'}}});
  await page.evaluate(()=>{historyFixture={...historyFixture,queue:{messages:[],fingerprint:'changed'}};render();});
  await page.waitForFunction(()=>document.querySelector('[data-draft-key="模型"]').value==='model-b');
  assert.equal(await effort.inputValue(),'medium');
  await page.evaluate(()=>window.deferWrite=true);await save.click();
  await page.evaluate(()=>{historyFixture={...historyFixture,queue:{messages:[],fingerprint:'during-save'}};render();});
  assert(await save.isDisabled());assert(await model.isDisabled());assert(await effort.isDisabled());
  await save.evaluate(button=>button.click());assert.equal(await page.evaluate(()=>writes.length),2);
  await page.evaluate(()=>{deferWrite=false;resolveWrite({state:'completed'});});
  await page.waitForFunction(()=>!document.querySelector('.mobile-session-settings button').disabled);
  await page.evaluate(()=>render(false));assert(await save.isDisabled());
  await page.evaluate(()=>{Operations.reset();mode='fail';render();});
  await settings.getByText('会话设置',{exact:true}).click();await settings.getByText('模型读取失败：offline').waitFor();
  assert.equal(await model.inputValue(),'model-a');assert(await save.isDisabled());
  await page.evaluate(()=>mode='ok');await settings.getByRole('button',{name:'重新读取模型'}).click();
  await page.waitForFunction(()=>!document.querySelector('.mobile-session-settings button').disabled);
  assert(await save.isEnabled());
  await page.evaluate(()=>{Operations.reset();mode='delay';render();api.epoch++;Operations.reset();});
  await page.evaluate(()=>resolveCatalog(catalog));await page.waitForTimeout(20);
  assert.equal(await page.locator('#operations').innerText(),'');
  assert.deepEqual(errors,[]);await page.close();
 }
 console.log('PASS model settings: desktop/mobile options, model switch/default, draft preservation, readonly, failed/retry, stale workspace response.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
