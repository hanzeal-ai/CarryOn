const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
(async()=>{
  const browser=await chromium.launch();
  try {
    const page=await browser.newPage();
    await page.setContent(`<form><button type="button" class="primary h-12" id="action"><span>Run</span></button><input id="text" value="default" autocomplete="off" maxlength="40"><input id="check" type="checkbox" checked><input id="file" type="file"><textarea id="area">original</textarea><button type="button" disabled id="disabled">Disabled</button></form>`);
    await page.locator('#file').setInputFiles({name:'note.txt',mimeType:'text/plain',buffer:Buffer.from('content')});
    await page.evaluate(()=>{
      window.nodes=[...document.querySelectorAll('button,input,textarea')];
      window.clicks=0;document.querySelector('#action').addEventListener('click',()=>window.clicks++);
      const text=document.querySelector('#text');text.value='edited';text.focus();text.setSelectionRange(1,4);
      document.querySelector('#area').value='draft';
      const check=document.querySelector('#check');check.checked=false;check.indeterminate=true;
    });
    for(let pass=0;pass<2;pass++){
      await page.addScriptTag({path:path.resolve('shadcn-ui.js')});
      const state=await page.evaluate(()=>{
        const text=document.querySelector('#text'),check=document.querySelector('#check');
        return {identity:window.nodes.every(node=>document.getElementById(node.id)===node),active:document.activeElement===text,value:text.value,selection:[text.selectionStart,text.selectionEnd],checked:check.checked,indeterminate:check.indeterminate,defaultChecked:check.defaultChecked,defaultValue:text.defaultValue,draft:document.querySelector('#area').value,file:document.querySelector('#file').files[0].name,disabled:document.querySelector('#disabled').disabled,customSize:document.querySelector('#action').classList.contains('h-12'),defaultSize:document.querySelector('#action').classList.contains('h-9'),styled:text.classList.contains('rounded-md')};
      });
      assert.deepEqual(state,{identity:true,active:true,value:'edited',selection:[1,4],checked:false,indeterminate:true,defaultChecked:true,defaultValue:'default',draft:'draft',file:'note.txt',disabled:true,customSize:true,defaultSize:false,styled:true});
    }
    await page.locator('#action').click();assert.equal(await page.evaluate(()=>window.clicks),1);
    await page.evaluate(()=>document.querySelector('form').reset());
    assert.equal(await page.locator('#text').inputValue(),'default');
    assert.equal(await page.locator('#area').inputValue(),'original');
    assert(await page.locator('#check').isChecked());
    console.log('PASS controls: identity, listener, focus, selection, draft/defaults, checkbox, file, disabled and class precedence; repeat application preserves state.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
