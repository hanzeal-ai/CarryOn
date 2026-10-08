'use strict';
const ArchiveControls=(()=>{
 let config,scope,version=0,rows=[],offset=0,canRestore=false,listBusy=false,hasMore=false,busyTarget=null,target=null;
 const el=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
 function dialog(id,title){const root=el('dialog');root.id=id;root.className='archive-dialog';const head=el('header'),heading=el('strong',title),close=el('button','关闭');head.className='archive-head';close.onclick=()=>root.close();head.append(heading,close);root.append(head);document.body.append(root);return root;}
 const list=dialog('archives-dialog','已归档'),body=el('section'),search=el('input'),records=el('div'),status=el('p'),more=el('button','加载更多');body.className='archive-body';search.type='search';search.placeholder='搜索已归档会话';search.setAttribute('aria-label',search.placeholder);status.setAttribute('role','status');body.append(search,status,records,more);list.append(body);
 const action=dialog('archive-action','归档会话'),name=el('p'),description=el('p'),message=el('p'),submit=el('button'),query=el('button','核对归档结果'),actions=el('div');message.setAttribute('role','status');actions.className='archive-actions';actions.append(query,submit);action.append(name,description,message,actions);
 const current=t=>config&&t.scope===config.scope()&&t.epoch===config.client.epoch&&(t.restoring||config.thread()===t.id);
 function confirmed(job,t,id){return job.id===id&&job.threadId===t.id&&job.state==='completed'&&job.result?.threadId===t.id&&job.result?.archived===!t.restoring;}
 function render(){records.replaceChildren();for(const row of rows){const button=el('button'),title=el('strong',row.title||'未命名会话'),detail=el('small',row.cwd||'');button.className='archive-row';button.append(title,detail);button.disabled=!canRestore||!config.canEdit();button.onclick=()=>openAction(row,true);records.append(button);}more.hidden=!hasMore;more.disabled=listBusy;}
 async function load(reset){
  const token=++version,captured=config.scope(),epoch=config.client.epoch,term=search.value;listBusy=true;status.textContent='正在读取…';more.disabled=true;
  if(reset){rows=[];offset=0;canRestore=false;hasMore=false;render();}
  try{const page=await config.api('/archived?limit=100&offset='+offset+'&search='+encodeURIComponent(term));
   if(token!==version||captured!==config.scope()||epoch!==config.client.epoch||!list.open)return;
   if(!Array.isArray(page.threads)||!Number.isInteger(page.nextOffset)||page.nextOffset<offset||typeof page.supportsRestore!=='boolean')throw Error('归档列表数据格式不正确');
   hasMore=page.threads.length===100;const seen=new Set(rows.map(row=>row.id));rows.push(...page.threads.filter(row=>!seen.has(row.id)));offset=page.nextOffset;canRestore=page.supportsRestore===true;status.textContent=rows.length?'':'暂无已归档会话';render();
  }catch(error){if(token===version&&captured===config.scope())status.textContent=error.message;}
  finally{if(token===version){listBusy=false;more.disabled=false;}}
 }
 function open(){if(!config)return;scope=config.scope();search.value='';list.showModal();load(true);}
 function openAction(row,restoring){
  if(!config.canEdit()||(!restoring&&!allowed()))return;
  scope=config.scope();target={id:row.id,scope:config.scope(),epoch:config.client.epoch,restoring};name.textContent=row.title||'未命名会话';description.textContent=restoring?'恢复到会话列表，不会自动运行任务。':'从会话列表移入已归档，保留历史和本地草稿。';message.textContent='';action.firstChild.firstChild.textContent=restoring?'恢复会话':'归档会话';submit.textContent=restoring?'恢复会话':'归档会话';submit.disabled=false;
  const id=config.client.operations.get((restoring?'unarchive':'archive')+':'+row.id);target.requestId=id;query.hidden=!id;submit.disabled=!!id;action.showModal();
 }
 function allowed(){const history=config.snapshot();return config.canEdit()&&history?.controls?.supportedOperations?.includes('archive')&&history.status?.state==='idle'&&history.access?.canInteract!==false;}
 async function perform(check){
  const captured=target;if(!captured||busyTarget===captured||!current(captured)||(!check&&!config.canEdit())||(!captured.restoring&&!check&&!allowed()))return;
  busyTarget=captured;submit.disabled=true;query.disabled=true;message.textContent='';
  try{const job=check?await config.client.queryArchive(captured.id,captured.restoring,captured.requestId,()=>current(captured)):await config.client.archiveThread(captured.id,captured.restoring,()=>current(captured));
   if(!current(captured)||target!==captured)return;
   const key=(captured.restoring?'unarchive':'archive')+':'+captured.id,id=captured.requestId||job.id;captured.requestId=config.client.operations.get(key)||id;
   if(confirmed(job,captured,id)){action.close();await config.completed(captured.id,!captured.restoring);if(list.open)load(true);}
   else{message.textContent=job.error||'结果仍待核对';if(['failed','interrupted','acknowledged'].includes(job.state))captured.requestId=null;query.hidden=!captured.requestId;}
  }catch(error){if(current(captured)){message.textContent=error.message;captured.requestId=config.client.operations.get((captured.restoring?'unarchive':'archive')+':'+captured.id);query.hidden=!captured.requestId;}}
  finally{if(busyTarget===captured)busyTarget=null;if(target===captured){submit.disabled=!!captured.requestId||!current(captured);query.disabled=!current(captured);}}
 }
 submit.onclick=()=>perform(false);query.onclick=()=>perform(true);more.onclick=()=>load(false);let timer;search.oninput=()=>{clearTimeout(timer);version++;timer=setTimeout(()=>load(true),180);};list.onclose=()=>{version++;};
 function update(){if(!config)return;if(scope!==undefined&&scope!==config.scope()){scope=config.scope();version++;list.close();action.close();target=null;rows=[];listBusy=false;}const button=document.getElementById('archive-thread');if(button)button.disabled=!allowed();}
 return {configure(value){config=value;document.getElementById('open-archives').onclick=open;document.getElementById('archive-thread').onclick=()=>openAction({id:config.thread(),title:document.getElementById('title').textContent},false);},open,update};
})();
