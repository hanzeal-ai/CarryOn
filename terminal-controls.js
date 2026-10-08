'use strict';
const TerminalControls=(()=>{
 let config,target,busy=false;
 const el=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
 const dialog=el('dialog'),head=el('header'),close=el('button','关闭'),body=el('section'),records=el('div'),status=el('p'),refresh=el('button','刷新'),more=el('button','加载更多'),query=el('button','核对原请求'),clean=el('button','全部停止');
 dialog.id='terminals-dialog';dialog.className='archive-dialog';head.className='archive-head';body.className='archive-body';status.setAttribute('role','status');records.className='native-management-list';head.append(el('strong','后台终端'),close);body.append(records,status,refresh,more,query,clean);dialog.append(head,body);document.body.append(dialog);
 const current=t=>t&&target===t&&dialog.open&&config.scope()===t.scope&&config.client.epoch===t.epoch&&config.thread()===t.id&&config.canView();
 const allowed=()=>config.snapshot()?.controls?.supportsBackgroundTerminals===true&&config.snapshot()?.access?.canInteract!==false&&config.snapshot()?.access?.nativeReady!==false;
 function render(){if(!target)return;if(records.contains(document.activeElement))target.focusKey=document.activeElement.dataset.focusKey;status.textContent=[target.writeError,target.readError].filter(Boolean).join('\n');const t=target,pending=config.client.operations.has('terminal:'+t.id);records.replaceChildren();
  for(const row of t.rows){const item=el('article'),command=el('pre',row.command),cwd=el('p',row.cwd),stop=el('button','停止');command.style.whiteSpace='pre-wrap';command.style.overflowWrap='anywhere';cwd.style.overflowWrap='anywhere';stop.dataset.focusKey=row.id;stop.disabled=busy||pending||!config.canStop()||!allowed();stop.onclick=()=>perform({action:'terminate',processId:row.id});item.append(command,cwd,stop);records.append(item);}
  if(t.loaded&&!t.rows.length)records.append(el('p','没有运行中的后台终端'));
  refresh.disabled=busy;more.hidden=!t.cursor;more.disabled=busy;query.hidden=!pending;query.disabled=busy;clean.disabled=busy||pending||!t.loaded||!t.rows.length||!config.canStop()||!allowed();close.disabled=busy;if(!busy&&target.focusKey&&(document.activeElement===document.body||records.contains(document.activeElement))){const item=[...records.querySelectorAll('button')].find(b=>b.dataset.focusKey===target.focusKey&&!b.disabled);(item||(pending?query:refresh)).focus();}
 }
 async function load(append=false){const t=target;if(busy||!current(t)||append&&!t.cursor)return;busy=true;render();
  try{const page=await config.request('/threads/'+encodeURIComponent(t.id)+'/terminals?limit=50'+(append?'&cursor='+encodeURIComponent(t.cursor):''));if(!current(t))return;
   if(page.threadId!==t.id||!Array.isArray(page.terminals)||!Object.hasOwn(page,'nextCursor')||page.nextCursor!==null&&(typeof page.nextCursor!=='string'||!page.nextCursor)||page.terminals.some(row=>typeof row.id!=='string'||!row.id||row.id!==row.processId||typeof row.command!=='string'||typeof row.cwd!=='string'))throw Error('终端列表格式不正确');
   const known=new Set(append?t.rows.map(row=>row.id):[]);for(const row of page.terminals){if(known.has(row.id))throw Error('终端身份重复');known.add(row.id);}
   if(!append)t.cursors.clear();if(page.nextCursor!==null){if(t.cursors.has(page.nextCursor))throw Error('终端分页游标重复');t.cursors.add(page.nextCursor);}
   t.rows=append?t.rows.concat(page.terminals):page.terminals;t.cursor=page.nextCursor;t.loaded=true;t.readError=null;
  }catch(error){if(current(t)){t.readError=error.message;}}finally{if(target===t){busy=false;render();}}
 }
 async function perform(body=null){const t=target;if(busy||!current(t)||body&&(!config.canStop()||!allowed()||config.client.operations.has('terminal:'+t.id)))return;
  if(body?.action==='clean'&&!confirm('停止此会话的所有后台终端？'))return;
  busy=true;t.writeError=null;render();
  try{const job=body?await config.client.stopTerminal(t.id,body,()=>current(t)):await config.client.queryTerminal(t.id,config.client.operations.get('terminal:'+t.id),()=>current(t));if(!current(t))return;t.writeError=job.state==='completed'?null:job.error||'结果待核对，原请求已保留';}
  catch(error){if(current(t))t.writeError=error.message;}finally{if(target===t){busy=false;render();}}
  if(current(t)&&!config.client.operations.has('terminal:'+t.id)&&!status.textContent)await load();
 }
 async function open(){if(!config.canView()||!allowed()||!config.thread())return;target={id:config.thread(),scope:config.scope(),epoch:config.client.epoch,rows:[],cursor:null,cursors:new Set(),loaded:false};status.textContent='';dialog.showModal();render();await load();}
 close.onclick=()=>dialog.close();refresh.onclick=()=>load();more.onclick=()=>load(true);clean.onclick=()=>perform({action:'clean'});query.onclick=()=>perform();dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
 return {configure(value){config=value;document.getElementById('open-terminals').onclick=open;},open,update(){if(!config)return;if(target&&!current(target)){dialog.close();target=null;busy=false;records.replaceChildren();}const button=document.getElementById('open-terminals');button.hidden=!allowed();button.disabled=!config.canView()||!config.thread();if(target)render();}};
})();
