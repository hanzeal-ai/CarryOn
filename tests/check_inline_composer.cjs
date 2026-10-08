const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch();
 try {
  const page=await browser.newPage();
  await page.setContent('<carryon-composer id="editor"></carryon-composer>');
  await page.addStyleTag({path:path.resolve(__dirname,'../skills-picker.css')});
  await page.addScriptTag({path:path.resolve(__dirname,'../inline-composer.js')});
  const result=await page.evaluate(()=>{
   const editor=document.getElementById('editor');
   const a={text:'A\ufffcBC\ufffcD',refs:[{name:'a',path:'/a',offset:1},{name:'b',path:'/b',offset:4}]};
   const b={text:'X\ufffcYZ\ufffcQ',refs:[{name:'c',path:'/c',offset:1},{name:'d',path:'/d',offset:4}]};
   const snapshot=()=>({text:editor.value,refs:editor.references});
   editor.setDocument(a.text,a.refs,0,'a');editor.setDocument(b.text,b.refs,0,'b');const restoredB=snapshot();
   editor.setDocument(a.text,a.refs,0,'a');const restoredA=snapshot();
   editor.references=[a.refs[1]];const removedFirst=snapshot();
   editor.setDocument(a.text,a.refs,0,'a');const oldHost=editor.firstElementChild;oldHost.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));
   oldHost.textContent='旧会话正在输入';oldHost.dispatchEvent(new InputEvent('input',{isComposing:true,bubbles:true}));
   editor.setDocument(b.text,b.refs,0,'b');
   oldHost.textContent='迟到的旧会话内容';oldHost.dispatchEvent(new InputEvent('input',{isComposing:true,bubbles:true}));oldHost.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));
   const afterIME=snapshot(),domAfterIME=editor.textContent;
   editor.setDocument('🙂中\ufffc文',[{name:'工具',path:'/tool',offset:3}],2,'unicode');
   editor.focus();const caret=editor.caret;
   const range=document.createRange();range.selectNode(editor.querySelector('.inline-reference'));getSelection().removeAllRanges();getSelection().addRange(range);
   const clipboard=new DataTransfer();editor.dispatchEvent(new ClipboardEvent('copy',{clipboardData:clipboard,bubbles:true,cancelable:true}));
   editor.dispatchEvent(new ClipboardEvent('cut',{clipboardData:clipboard,bubbles:true,cancelable:true}));const cut=snapshot();
   const paste=new DataTransfer();paste.setData('text/plain','粘贴\ufffc');paste.setData('text/html','<span data-reference="fake">伪造</span>');editor.dispatchEvent(new ClipboardEvent('paste',{clipboardData:paste,bubbles:true,cancelable:true}));
   return {caret,a,b,restoredA,restoredB,removedFirst,afterIME,domAfterIME,copy:clipboard.getData('text/plain'),cut,pasted:snapshot()};
  });
  assert.deepEqual(result.restoredA,result.a);assert.deepEqual(result.restoredB,result.b);assert.deepEqual(result.afterIME,result.b);
  assert.equal(result.domAfterIME,'XcYZdQ');
  assert.deepEqual(result.removedFirst,{text:'ABC\ufffcD',refs:[{name:'b',path:'/b',offset:3}]});
  assert.equal(result.caret,2);
  assert.equal(result.copy,'工具');assert.deepEqual(result.cut,{text:'🙂中文',refs:[]});assert.deepEqual(result.pasted,{text:'🙂中粘贴文',refs:[]});
  await page.evaluate(()=>{const editor=document.getElementById('editor');editor.firstElementChild.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));editor.setDocument('',[],0,'no-end');});
  await page.locator('#editor [contenteditable]').fill('正常继续输入');assert.equal(await page.locator('#editor').evaluate(el=>el.value),'正常继续输入');
  await page.evaluate(()=>{const el=document.getElementById('editor');el.setDocument('\ufffc',[{name:'delete',path:'/delete',offset:0}]);el.focus();const range=document.createRange();range.selectNode(el.querySelector('.inline-reference'));getSelection().removeAllRanges();getSelection().addRange(range);});
  await page.keyboard.press('Backspace');assert.deepEqual(await page.locator('#editor').evaluate(el=>el.references),[]);
  await page.keyboard.press(process.platform==='darwin'?'Meta+z':'Control+z');assert.equal(await page.locator('#editor').evaluate(el=>el.references[0]?.name),'delete');
  const dropped=await page.evaluate(()=>{const el=document.getElementById('editor'),data=new DataTransfer();data.setData('text/plain','safe\ufffc');data.setData('text/html','<span data-reference=' + JSON.stringify(JSON.stringify(['delete','/delete'])) + '>forged</span>');el.setDocument('');el.focus();el.dispatchEvent(new DragEvent('drop',{dataTransfer:data,bubbles:true,cancelable:true}));return {text:el.value,refs:el.references};});
  assert.deepEqual(dropped,{text:'safe',refs:[]});
  await page.evaluate(()=>document.getElementById('editor').setDocument('使用 \ufffc 和 \ufffc 完成',[{name:'Review',path:'/skills/review',offset:3},{name:'App',path:'app://fixture',offset:7}],0,'icons'));
  const iconState=await page.locator('#editor').evaluate(el=>({text:el.value,refs:el.references,icons:[...el.querySelectorAll('.inline-reference svg')].map(svg=>{const r=svg.getBoundingClientRect();return {width:r.width,height:r.height,hidden:svg.getAttribute('aria-hidden')};})}));
  assert.equal(iconState.icons.length,2);assert(iconState.icons.every(i=>i.width>0&&i.width<=24&&i.height>0&&i.height<=24&&i.hidden==='true'));assert.deepEqual(iconState.refs.map(r=>r.offset),[3,7]);
  const iconCopy=await page.locator('#editor').evaluate(el=>{el.focus();const range=document.createRange();range.selectNodeContents(el.firstElementChild);getSelection().removeAllRanges();getSelection().addRange(range);const data=new DataTransfer();el.dispatchEvent(new ClipboardEvent('copy',{clipboardData:data,bubbles:true,cancelable:true}));return data.getData('text/plain');});
  assert.equal(iconCopy,'使用 Review 和 App 完成');
  const namedReference=await page.evaluate(()=>{
   const el=document.getElementById('editor');el.setDocument('Use \ufffc',[{name:'build-ios-apps',path:'/fixture/SKILL.md',displayName:'Build iOS Apps',offset:4}],0,'named');
   el.focus();el.readDocument();const range=document.createRange();range.selectNodeContents(el.firstElementChild);getSelection().removeAllRanges();getSelection().addRange(range);const data=new DataTransfer();el.dispatchEvent(new ClipboardEvent('copy',{clipboardData:data,bubbles:true,cancelable:true}));
   const saved=JSON.parse(JSON.stringify({text:el.value,refs:el.references}));el.setDocument(saved.text,saved.refs,0,'restored');return {label:el.textContent,copy:data.getData('text/plain'),wire:el.wireText,identity:el.references.map(({name,path})=>({name,path}))};
  });
  assert.deepEqual(namedReference,{label:'Use Build iOS Apps',copy:'Use Build iOS Apps',wire:'Use ',identity:[{name:'build-ios-apps',path:'/fixture/SKILL.md'}]});
  const png=await page.evaluate(()=>{const canvas=document.createElement('canvas');canvas.width=canvas.height=4;canvas.getContext('2d').fillRect(0,0,4,4);return canvas.toDataURL('image/png').split(',')[1];});
  await page.evaluate(iconData=>{const el=document.getElementById('editor');el.setDocument('A\ufffcZ',[{name:'raster',path:'/raster',displayName:'Raster Alias',iconData,offset:1}],0,'png');const saved=JSON.parse(JSON.stringify({text:el.value,refs:el.references}));el.setDocument(saved.text,saved.refs,0,'png-restore');},png);
  await page.locator('#editor img').evaluate(img=>img.decode());
  assert.deepEqual(await page.locator('#editor img').evaluate(img=>[img.naturalWidth,img.naturalHeight]),[4,4]);
  const raster=await page.locator('#editor').evaluate(el=>{el.focus();const range=document.createRange();range.selectNodeContents(el.firstElementChild);getSelection().removeAllRanges();getSelection().addRange(range);const data=new DataTransfer();el.dispatchEvent(new ClipboardEvent('copy',{clipboardData:data,bubbles:true,cancelable:true}));return {copy:data.getData('text/plain'),wire:el.wireText,refs:el.references};});
  assert.equal(raster.copy,'ARaster AliasZ');assert.equal(raster.wire,'AZ');assert.equal(raster.refs[0].offset,1);assert.equal(raster.refs[0].iconData,png);assert.deepEqual(raster.refs.map(({name,path})=>({name,path})),[{name:'raster',path:'/raster'}]);
  await page.locator('#editor').evaluate(el=>{const range=document.createRange();range.selectNodeContents(el.firstElementChild);range.collapse(false);getSelection().removeAllRanges();getSelection().addRange(range);});
  const started=Date.now();await page.keyboard.insertText('typing 中文🙂');assert(Date.now()-started<2000);assert.equal(await page.locator('#editor').evaluate(el=>el.references[0].iconData),png);
  for(const iconData of [Buffer.from('not a PNG').toString('base64'),'A'.repeat(87385),Buffer.from(png,'base64').subarray(0,33).toString('base64')]){
   await page.evaluate(iconData=>document.getElementById('editor').setDocument('\ufffc',[{name:'invalid',path:'/invalid',iconData,offset:0}],0,'invalid'),iconData);
   await page.waitForTimeout(80);assert.equal(await page.locator('#editor svg').count(),1,'invalid raster falls back to generic icon');
  }
  await page.locator('#editor').evaluate(el=>{el.focus();const range=document.createRange();range.selectNodeContents(el.firstElementChild);range.collapse(false);getSelection().removeAllRanges();getSelection().addRange(range);});
  await page.keyboard.insertText('回退后可编辑');assert.equal(await page.locator('#editor').evaluate(el=>el.wireText),'回退后可编辑');assert.equal(await page.locator('#editor').evaluate(el=>el.references[0].name),'invalid');
  await page.screenshot({path:'.runtime/inline-reference-icons.png'});
  console.log('Inline composer: atomic restore, multi-token removal, late IME isolation, UTF-16 cut/copy/plain paste passed');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
