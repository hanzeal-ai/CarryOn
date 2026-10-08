'use strict';
const RenameControls=(()=>{
 let config,target,busy=false;
 const el=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
 const dialog=el('dialog'),header=el('header'),title=el('strong','重命名'),close=el('button','关闭'),body=el('section'),label=el('label','会话名称'),input=el('input'),status=el('p'),actions=el('div'),save=el('button','保存'),query=el('button','核对重命名结果');
 dialog.id='rename-dialog';dialog.className='archive-dialog';header.className='archive-head';body.className='archive-body';actions.className='archive-actions';input.id='rename-name';label.htmlFor=input.id;status.setAttribute('role','status');header.append(title,close);actions.append(query,save);body.append(label,input,status,actions);dialog.append(header,body);document.body.append(dialog);
 const current=t=>t&&config.scope()===t.scope&&config.client.epoch===t.epoch&&config.thread()===t.id;
 const allowed=()=>config.canEdit()&&config.snapshot()?.controls?.supportedOperations?.includes('rename')&&config.snapshot()?.access?.canInteract!==false;
 function render(){const pending=!!target?.requestId;save.disabled=busy||pending||!target?.loaded||!current(target)||!allowed()||!input.value.trim()||[...input.value.trim()].length>200;input.disabled=busy||pending||!target?.loaded;query.hidden=!pending;query.disabled=busy||!current(target);close.disabled=busy;}
 async function open(){
  if(!allowed())return;
  const t=target={id:config.thread(),scope:config.scope(),epoch:config.client.epoch,loaded:false,requestId:config.client.operations.get('rename:'+config.thread())};input.value=document.getElementById('title').textContent;status.textContent='';dialog.showModal();render();
  if(t.requestId){await perform(true);}
  if(target===t&&current(t)){t.loaded=true;render();}
 }
 async function perform(check){
  const t=target;if(busy||!current(t)||(!check&&(!allowed()||t.requestId)))return;
  busy=true;status.textContent='';render();
  try{
   const name=input.value.trim();if(!check&&(!name||[...name].length>200))throw Error('名称最多200字符');
   const job=check?await config.client.queryRename(t.id,t.requestId,()=>current(t)):await config.client.renameThread(t.id,name,()=>current(t));
   if(!current(t)||target!==t)return;
   t.requestId=config.client.operations.get('rename:'+t.id);if(typeof job.name==='string')input.value=job.name;
   if(job.state==='completed'&&job.result?.threadId===t.id&&job.result?.name===job.name){dialog.close();await config.completed(t.id,job.name);}
   else status.textContent=job.error||'结果仍待核对，原请求已保留';
  }catch(error){if(current(t)&&target===t){status.textContent=error.message;t.requestId=config.client.operations.get('rename:'+t.id);}}
  finally{busy=false;if(target===t)render();}
 }
 close.onclick=()=>dialog.close();dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});input.oninput=render;save.onclick=()=>perform(false);query.onclick=()=>perform(true);
 return {configure(value){config=value;document.getElementById('rename-thread').onclick=open;},update(){if(!config)return;if(target&&!current(target)){dialog.close();target=null;}document.getElementById('rename-thread').disabled=!allowed();},open};
})();
