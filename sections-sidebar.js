'use strict';
const NativeSectionsSidebar=(()=>{
 let config,version=0,activeScope=null,capable=false,pagesLoaded=1;
 const container=document.getElementById('native-sections'),groups=new Map();
 const el=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
 const allowed=()=>config.enabled()&&config.canView();
 const reconcile=(parent,nodes)=>{const keep=new Set(nodes);for(const child of [...parent.children])if(!keep.has(child))child.remove();nodes.forEach((child,index)=>{if(parent.children[index]!==child)parent.insertBefore(child,parent.children[index]||null);});};
 const add=el('button','新建分组');add.className='quiet';add.onclick=()=>{if(allowed()&&config.canEdit())config.manage();};
 const more=el('button','加载更多分组');more.className='quiet';more.onclick=()=>refresh(pagesLoaded+1);
 function groupFor(section,scope){
  let entry=groups.get(section.id);
  if(entry){entry.section=section;entry.title.textContent=section.pinned?'置顶':section.title;entry.edit.disabled=!config.canEdit();entry.edit.hidden=section.pinned;return entry;}
  const group=el('details'),summary=el('summary'),title=el('span',section.pinned?'置顶':section.title),rows=el('div'),edit=el('button','···');
  edit.className='quiet';edit.hidden=section.pinned;edit.disabled=!config.canEdit();edit.setAttribute('aria-label','编辑分组 '+section.title);
  group.dataset.sectionId=section.id;group.className='native-section';summary.append(title,edit);group.append(summary,rows);
  entry={section,group,title,edit,rows,pages:1,request:0,loaded:false};groups.set(section.id,entry);
  const current=()=>scope===config.scope()&&allowed()&&groups.get(section.id)===entry;
  edit.onclick=event=>{event.preventDefault();if(current()&&config.canEdit())config.manage(entry.section);};
  entry.load=async(pages=entry.pages,background=false)=>{
   const request=++entry.request;entry.pages=pages;
   const valid=()=>current()&&request===entry.request;
   if(!entry.loaded)rows.textContent='正在加载…';
   try{
    let cursor=null;const threads=[];
    for(let i=0;i<pages;i++){
     const page=await config.request('/sections/'+encodeURIComponent(section.id)+'/threads?limit=50'+(cursor?'&cursor='+encodeURIComponent(cursor):''));if(!valid())return;
     threads.push(...page.threads);cursor=page.nextCursor;if(!cursor)break;
    }
    if(background&&workspaceInteractionActive()){scheduleWorkspaceRefresh();return;}
    const existing=new Map([...rows.children].filter(row=>row.dataset.threadId).map(row=>[row.dataset.threadId,row]));
    const nodes=threads.map(thread=>{
     let row=existing.get(thread.id);
     if(!row){row=el('div');row.dataset.threadId=thread.id;row.className='native-section-thread-row';const button=el('button');button.className='native-section-thread';button.dataset.threadId=thread.id;const order=el('button','···');order.className='quiet native-thread-order';row.append(button,order);}
     const [button,order]=row.children;button.textContent=thread.title;button.title=thread.title;order.setAttribute('aria-label','调整顺序 '+thread.title);order.disabled=!config.canEdit();
     button.onclick=()=>{if(current())Promise.resolve(config.open(thread)).catch(error=>{if(current())config.notice(error.message);});};order.onclick=()=>{if(current()&&config.canEdit())config.order(entry.section,thread);};return row;
    });
    if(cursor){const moreButton=entry.more||(entry.more=el('button','加载更多'));moreButton.className='quiet native-section-more';moreButton.onclick=()=>entry.load(entry.pages+1);nodes.push(moreButton);}
    if(!nodes.length)nodes.push(entry.empty||(entry.empty=el('div','暂无会话')));
    if(!entry.loaded)rows.replaceChildren();reconcile(rows,nodes);entry.loaded=true;
   }catch(error){if(valid()){let retry=rows.querySelector('.section-retry');if(!retry){retry=el('button','读取失败 · 重试');retry.className='quiet section-retry';if(!entry.loaded)rows.replaceChildren();rows.append(retry);}retry.title=error.message;retry.onclick=()=>entry.load();}}
  };
  group.ontoggle=()=>{if(group.open&&!entry.loaded)entry.load();};group.open=section.pinned;
  return entry;
 }
 async function refresh(pageCount=pagesLoaded,background=false){
  const token=++version,scope=config.scope();container.hidden=!allowed();if(!allowed()){groups.clear();container.replaceChildren();return;}
  add.disabled=!config.canEdit();more.disabled=true;
  const current=()=>token===version&&scope===config.scope()&&allowed();
  try{
   let cursor=null;const sections=[];
   for(let i=0;i<pageCount;i++){
    const page=await config.request('/sections?limit=50'+(cursor?'&cursor='+encodeURIComponent(cursor):''));if(!current())return;
    sections.push(...page.sections);cursor=page.nextCursor;if(!cursor)break;
   }
   if(background&&workspaceInteractionActive()){scheduleWorkspaceRefresh();return;}
   pagesLoaded=pageCount;
   const ids=new Set(sections.map(section=>section.id));for(const id of groups.keys())if(!ids.has(id))groups.delete(id);
   const entries=sections.map(section=>groupFor(section,scope));
   reconcile(container,[add,...entries.map(entry=>entry.group),...(cursor?[more]:[])]);
   for(const entry of entries)if(entry.group.open&&entry.loaded)entry.load(undefined,background);
  }catch(error){if(current()){let retry=container.querySelector(':scope > .section-retry');if(!retry){retry=el('button','分组读取失败 · 重试');retry.className='quiet section-retry';container.append(retry);}retry.title=error.message;retry.onclick=()=>refresh();}}
  finally{if(current())more.disabled=false;}
 }
 return {configure(value){config=value;},update(){if(!config)return;const scope=config.scope(),next=allowed();if(scope!==activeScope||next!==capable){activeScope=scope;capable=next;groups.clear();pagesLoaded=1;container.replaceChildren();refresh();}},refresh};
})();
