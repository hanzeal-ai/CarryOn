'use strict';
const SectionControls=(()=>{
 let config,target,busy=false,cursor=null;
 const el=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
 const dialog=el('dialog'),header=el('header'),title=el('strong','移动到分组'),close=el('button','关闭'),body=el('section'),label=el('label','分组'),select=el('select'),status=el('p'),actions=el('div'),save=el('button','保存'),query=el('button','核对移动结果'),more=el('button','加载更多分组'),retry=el('button','重新读取');
 dialog.id='section-dialog';dialog.className='archive-dialog';header.className='archive-head';body.className='archive-body';actions.className='archive-actions';select.id='section-destination';label.htmlFor=select.id;status.setAttribute('role','status');header.append(title,close);actions.append(retry,query,save);body.append(label,select,more,status,actions);dialog.append(header,body);document.body.append(dialog);
 const current=t=>t&&config.scope()===t.scope&&config.client.epoch===t.epoch&&config.thread()===t.id&&config.canView();
 const allowed=()=>!!config.thread()&&config.supported()&&config.canEdit();
 function render(){const pending=!!target?.requestId,known=[...select.options].some(option=>option.value===(target?.destination||''));save.disabled=busy||pending||!target?.loaded||!current(target)||!allowed()||!known;select.disabled=busy||pending||!target?.loaded;query.hidden=!pending;query.disabled=busy||!current(target);more.hidden=!cursor;more.disabled=busy||!current(target);close.disabled=busy;retry.hidden=!!target?.loaded||pending;retry.disabled=busy;}
 function append(rows){for(const row of rows){if([...select.options].some(option=>option.value===row.id))continue;const option=el('option',row.pinned?'置顶':row.title);option.value=row.id;select.append(option);}select.value=target.destination||'';}
 async function open(){
  if(!allowed())return;
  const t=target={id:config.thread(),scope:config.scope(),epoch:config.client.epoch,loaded:false,destination:null,requestId:config.client.operations.get('section-move:'+config.thread())};select.replaceChildren(el('option','未分组'));select.firstChild.value='';cursor=null;status.textContent='';if(!dialog.open)dialog.showModal();busy=true;render();
  try{
   const [inventory,membership]=await Promise.all([config.request('/sections?limit=50'),config.request('/threads/'+encodeURIComponent(t.id)+'/section')]);
   if(!current(t)||target!==t)return;
   if(membership.threadId!==t.id||!Object.hasOwn(membership,'sectionId'))throw Error('分组归属回执不匹配');
   t.destination=membership.sectionId;append(inventory.sections);cursor=inventory.nextCursor;t.loaded=true;
  }catch(error){if(current(t)&&target===t)status.textContent=error.message;}
  finally{if(target===t){busy=false;render();}}
  if(current(t)&&target===t&&t.requestId)await perform(true);
 }
 async function loadMore(){
  const t=target;if(busy||!current(t)||!cursor)return;busy=true;render();
  try{const page=await config.request('/sections?limit=50&cursor='+encodeURIComponent(cursor));if(!current(t)||target!==t)return;append(page.sections);cursor=page.nextCursor;}
  catch(error){if(current(t)&&target===t)status.textContent=error.message;}
  finally{if(target===t){busy=false;render();}}
 }
 async function perform(check){
  const t=target;if(busy||!current(t)||(!check&&(!allowed()||t.requestId||save.disabled)))return;busy=true;status.textContent='';render();
  try{
   const job=check?await config.client.queryThreadSection(t.id,t.requestId,()=>current(t)):await config.client.moveThreadSection(t.id,t.destination,()=>current(t));
   if(!current(t)||target!==t)return;
   t.requestId=config.client.operations.get('section-move:'+t.id);t.destination=job.sectionId;select.value=t.destination||'';
   if(job.state==='completed'&&job.result?.threadId===t.id&&job.result?.sectionId===job.sectionId){dialog.close();await config.completed(t.id);}
   else status.textContent=job.error||'结果仍待核对，原请求已保留';
  }catch(error){if(current(t)&&target===t){status.textContent=error.message;t.requestId=config.client.operations.get('section-move:'+t.id);}}
  finally{if(target===t){busy=false;render();}}
 }
 retry.onclick=open;close.onclick=()=>dialog.close();dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});select.onchange=()=>{if(target)target.destination=select.value||null;render();};save.onclick=()=>perform(false);query.onclick=()=>perform(true);more.onclick=loadMore;
 return {configure(value){config=value;document.getElementById('move-section').onclick=open;},update(){if(!config)return;if(target&&!current(target)){dialog.close();target=null;busy=false;}const button=document.getElementById('move-section');button.hidden=!config.supported();button.disabled=!allowed();},open};
})();
