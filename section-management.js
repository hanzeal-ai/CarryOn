'use strict';
const SectionManagement=(()=>{
 let config,target,busy=false;
 const el=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
 const dialog=el('dialog'),header=el('header'),title=el('strong'),close=el('button','关闭'),body=el('section'),label=el('label','分组名称'),name=el('input'),before=el('select'),more=el('button','加载更多会话'),retry=el('button','重新读取会话'),status=el('p'),actions=el('div'),save=el('button','保存'),remove=el('button','删除分组'),query=el('button','核对原请求');
 dialog.id='section-management-dialog';dialog.className='archive-dialog';header.className='archive-head';body.className='archive-body';actions.className='archive-actions';name.id='section-name';name.maxLength=200;before.id='section-order-before';label.htmlFor=name.id;status.setAttribute('role','status');header.append(title,close);actions.append(remove,query,save);body.append(label,name,before,more,retry,status,actions);dialog.append(header,body);document.body.append(dialog);
 const current=t=>t&&dialog.open&&target===t&&config.scope()===t.scope&&config.client.epoch===t.epoch&&config.canView()&&config.supported();
 function render(){const pending=config.client.operations.has('section-management'),allowed=current(target)&&config.canEdit();name.disabled=busy||pending;before.disabled=busy||pending||!target?.orderLoaded;save.disabled=busy||pending||!allowed||(target?.thread?!target.orderLoaded:!name.value.trim());retry.hidden=!target?.orderFailed;retry.disabled=busy||!current(target);more.hidden=!target?.cursor;more.disabled=busy||!current(target);remove.hidden=!target?.section||!!target?.thread;remove.disabled=busy||pending||!allowed;query.hidden=!pending;query.disabled=busy||!current(target);close.disabled=busy;}
 async function open(section=null,thread=null){
  if(!config.supported()||!config.canView()||!config.canEdit()||section?.pinned&&!thread)return;
  const t=target={section,thread,scope:config.scope(),epoch:config.client.epoch,orderLoaded:false,cursor:null};
  title.textContent=thread?'调整顺序':section?'编辑分组':'新建分组';name.value=section?.title||'';name.hidden=!!thread;before.hidden=!thread;before.replaceChildren(el('option','末尾'));before.firstChild.value='';label.textContent=thread?'排在会话之前':'分组名称';label.htmlFor=thread?before.id:name.id;status.textContent='';dialog.showModal();render();
  if(config.client.operations.has('section-management'))await perform(true);
  if(thread&&current(t))await loadOrder(false);else if(current(t))name.focus();
 }
 async function loadOrder(morePage){
  const t=target;if(busy||!current(t)||!t.thread||morePage&&!t.cursor)return;busy=true;if(t.orderError&&status.textContent===t.orderError)status.textContent='';t.orderError=null;t.orderFailed=false;render();
  try{const page=await config.request('/sections/'+encodeURIComponent(t.section.id)+'/threads?limit=50'+(morePage?'&cursor='+encodeURIComponent(t.cursor):''));if(!current(t))return;
   for(const row of page.threads)if(row.id!==t.thread.id&&![...before.options].some(option=>option.value===row.id)){const option=el('option',row.title);option.value=row.id;before.append(option);}
   t.cursor=page.nextCursor;t.orderLoaded=true;
  }catch(error){if(current(t)){t.orderFailed=true;t.orderError=error.message;status.textContent=error.message;}}finally{if(target===t){busy=false;render();}}
 }
 async function perform(check,deleteGroup=false){
  const t=target;if(busy||!current(t)||!check&&(save.disabled&&!deleteGroup||!config.canEdit()||config.client.operations.has('section-management')))return;
  if(deleteGroup&&(!t.section||!confirm('删除此分组？其中的会话会保留。')))return;
  busy=true;render();status.textContent='';
  try{const job=check?await config.client.querySectionManagement(config.client.operations.get('section-management'),()=>current(t)):await config.client.manageSection(t.section?.id||null,t.thread?{action:'order',threadId:t.thread.id,beforeThreadId:before.value||null}:t.section?(deleteGroup?{action:'delete'}:{action:'update',name:name.value.trim()}):{name:name.value.trim()},()=>current(t));
   if(!current(t))return;
   if(job.state==='completed'){dialog.close();await config.completed();}else status.textContent=job.error||'结果待核对，原请求已保留';
  }catch(error){if(current(t))status.textContent=error.message;}finally{if(target===t){busy=false;render();}}
 }
 retry.onclick=()=>loadOrder(false);more.onclick=()=>loadOrder(true);name.oninput=render;save.onclick=()=>perform(false);remove.onclick=()=>perform(false,true);query.onclick=()=>perform(true);close.onclick=()=>dialog.close();dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
 return {configure(value){config=value;},open,update(){if(!config)return;if(target&&!current(target)){dialog.close();target=null;busy=false;}if(target)render();}};
})();
