const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch();
 try{for(const width of [1280,390]){
  const context=await browser.newContext({viewport:{width,height:844},permissions:['clipboard-read','clipboard-write']});const page=await context.newPage();const errors=[],engines=[];
  page.on('pageerror',error=>errors.push(error.message));page.on('request',request=>{if(request.url().endsWith('/highlight-engine.js'))engines.push(request.url());});
  await page.route('**/code-highlight-fixture',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:'<!doctype html><html><head><meta charset="utf-8"></head><body></body></html>'}));await page.goto('http://127.0.0.1:8923/code-highlight-fixture');await page.setContent('<link rel="stylesheet" href="/code-highlight.css"><style>body{margin:24px}pre{overflow:auto;font:14px/1.6 monospace}.markdown-code{border:1px solid #ddd;padding:16px;border-radius:16px}.markdown-code-header{display:flex;justify-content:space-between}</style><main id="content"></main>');
  await page.addScriptTag({url:'/code-highlight.js'});await page.addScriptTag({url:'/message-markdown.js'});await page.addScriptTag({url:'/unified-diff.js'});await page.addScriptTag({url:'/diff-review.js'});await page.addStyleTag({url:'/diff-review.css'});
  await page.evaluate(()=>document.querySelector('#content').append(MessageMarkdown.render('```text\nplain <b>text</b>\n```')));await page.waitForTimeout(40);assert.equal(engines.length,0,'plain text does not load the engine');
  const source='public enum Sample: String {\n    case ready = "你好👋\ufffc"\n}';
  await page.evaluate(source=>{const root=MessageMarkdown.render('```swift\n'+source+'\n```');root.id='swift';document.querySelector('#content').append(root);},source);
  await page.locator('#swift .hljs-keyword').first().waitFor();assert.equal(await page.locator('#swift pre code').textContent(),source);assert.equal(engines.length,1);
  const light=await page.locator('#swift .hljs-keyword').first().evaluate(node=>getComputedStyle(node).color);assert.equal(light,'rgb(167, 29, 93)');
  await page.locator('#swift').getByRole('button',{name:'复制代码',exact:true}).click();assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),source);
  await page.emulateMedia({colorScheme:'dark'});assert.equal(await page.locator('#swift .hljs-keyword').first().evaluate(node=>getComputedStyle(node).color),'rgb(198, 120, 221)');await page.emulateMedia({colorScheme:'light'});
  const inert=await page.evaluate(async()=>{const source='const a = "<script>window.injected=true</script><img src=x onerror=alert(1)>";';const node=document.createElement('code');node.textContent=source;document.querySelector('#content').append(node);await CodeHighlight.render(node,source,'javascript');return {same:node.textContent===source,unsafe:!!node.querySelector('script,img'),injected:window.injected===true,colors:!!node.querySelector('.hljs-keyword')};});assert.deepEqual(inert,{same:true,unsafe:false,injected:false,colors:true});
  const selection=await page.evaluate(async()=>{const source='const selected = "原文";';const node=document.createElement('code');node.textContent=source;document.querySelector('#content').append(node);const range=document.createRange();range.setStart(node.firstChild,6);range.setEnd(node.firstChild,14);window.getSelection().removeAllRanges();window.getSelection().addRange(range);const before=window.getSelection().toString();const painted=await CodeHighlight.render(node,source,'javascript');return {before,after:window.getSelection().toString(),painted,same:node.textContent===source};});assert.equal(selection.before,selection.after);assert(!selection.painted&&selection.same);
  const diff='@@ -1 +1 @@\n-old()\n+public enum Sample { case ready = "你好👋" }';
  await page.evaluate(diff=>{const root=document.createElement('section');root.id='diff';document.querySelector('#content').append(root);DiffReview.render(root,{path:'src/main.swift',patch:diff});},diff);
  await page.locator('#diff .diff-line.added .hljs-keyword').first().waitFor();assert.deepEqual(await page.locator('#diff .diff-text').allTextContents(),diff.split('\n'));
  const isolated='@@ -1,2 +1 @@\n-/* removed comment\n-closed */\n+const value = "你好👋"\n@@ -20 +20 @@\n-/* unfinished\n+const next = 2';
  await page.evaluate(patch=>{const root=document.createElement('section');root.id='isolated-diff';document.querySelector('#content').append(root);DiffReview.render(root,{path:'src/main.js',patch});},isolated);
  await page.locator('#isolated-diff .diff-line.added .hljs-keyword').first().waitFor();
  await page.waitForFunction(()=>document.querySelectorAll('#isolated-diff .diff-line.added .hljs-keyword').length===2);
  assert.equal(await page.locator('#isolated-diff .diff-line.added .hljs-comment').count(),0);
  assert.equal(await page.locator('#isolated-diff .diff-line.header .hljs-keyword').count(),0);
  assert.deepEqual(await page.locator('#isolated-diff .diff-text').allTextContents(),isolated.split('\n'));
  await page.screenshot({path:'.runtime/web-code-highlight-'+width+'.png'});
  const bounded=await page.evaluate(async()=>{const text='你'.repeat(34000),node=document.createElement('code');node.textContent=text;document.querySelector('#content').append(node);const start=performance.now(),painted=await CodeHighlight.render(node,text,'swift');return {painted,same:node.textContent===text,ms:performance.now()-start};});assert(!bounded.painted&&bounded.same&&bounded.ms<100,'oversized Unicode stays plain: '+JSON.stringify(bounded));
  // A stalled lexer stays off the main thread and is terminated, then reset can recover.
  await page.route('**/code-highlight-worker.js',route=>route.fulfill({contentType:'text/javascript',body:'self.onmessage=()=>{while(true){}};'}));
  const stalled=await page.evaluate(async()=>{CodeHighlight.reset();let ticks=0;const timer=setInterval(()=>ticks++,20),start=performance.now();const runs=await CodeHighlight.highlight('const stalled = 1','javascript');clearInterval(timer);return {ticks,ms:performance.now()-start,plain:runs.length===0};});
  assert(stalled.plain&&stalled.ticks>50&&stalled.ms<3000,'stalled worker remains bounded and responsive: '+JSON.stringify(stalled));
  await page.unroute('**/code-highlight-worker.js');const recovered=await page.evaluate(async()=>{CodeHighlight.reset();return (await CodeHighlight.highlight('const recovered = 1','javascript')).some(run=>run.scopes.includes('hljs-keyword'));});assert(recovered);
  assert.deepEqual(errors,[]);console.log('PASS syntax color projection '+width,JSON.stringify({bounded,stalled}));await context.close();
 }}finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
