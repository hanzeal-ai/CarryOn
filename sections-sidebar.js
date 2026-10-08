'use strict';
const NativeSectionsSidebar=(()=>{
 let config,version=0,activeScope=null,capable=false;
 const container=document.getElementById('native-sections'),expanded=new Set();
 const el=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
 const allowed=()=>config.enabled()&&config.canView();
 async function refresh(){
  const token=++version,scope=config.scope();container.replaceChildren();container.hidden=!allowed();if(!allowed())return;
  const add=el('button','新建分组');add.className='quiet';add.disabled=!config.canEdit();add.onclick=()=>{if(allowed()&&config.canEdit())config.manage();};container.append(add);
  const current=()=>token===version&&scope===config.scope()&&allowed();
  async function load(cursor=null){
   const page=await config.request('/sections?limit=50'+(cursor?'&cursor='+encodeURIComponent(cursor):''));if(!current())return;
   for(const section of page.sections){
    const group=el('details'),summary=el('summary',section.pinned?'置顶':section.title),rows=el('div');group.dataset.sectionId=section.id;group.className='native-section';if(!section.pinned){const edit=el('button','···');edit.className='quiet';edit.setAttribute('aria-label','编辑分组 '+section.title);edit.disabled=!config.canEdit();edit.onclick=event=>{event.preventDefault();if(current()&&config.canEdit())config.manage(section);};summary.append(edit);}group.append(summary,rows);container.append(group);
    let loaded=false,busy=false,next=null;
    const failure=error=>{if(current()){const retry=el('button','读取失败 · 重试');retry.className='quiet';retry.title=error.message;retry.onclick=()=>loadThreads(false);rows.replaceChildren(retry);}};
    async function loadThreads(more){
     if(busy||!current()||more&&!next)return;busy=true;
     if(!more)rows.textContent='正在加载…';
     try{
      const page=await config.request('/sections/'+encodeURIComponent(section.id)+'/threads?limit=50'+(more?'&cursor='+encodeURIComponent(next):''));if(!current())return;
      if(!more)rows.replaceChildren();else rows.querySelector('.native-section-more')?.remove();
      for(const thread of page.threads){const button=el('button',thread.title);button.className='native-section-thread';button.dataset.threadId=thread.id;button.title=thread.title;button.onclick=()=>{if(current())Promise.resolve(config.open(thread)).catch(error=>{if(current())config.notice(error.message);});};const row=el('div');row.className='native-section-thread-row';const order=el('button','···');order.className='quiet native-thread-order';order.setAttribute('aria-label','调整顺序 '+thread.title);order.disabled=!config.canEdit();order.onclick=()=>{if(current()&&config.canEdit())config.order(section,thread);};row.append(button,order);rows.append(row);}
      next=page.nextCursor;loaded=true;
      if(next){const moreButton=el('button','加载更多');moreButton.className='quiet native-section-more';moreButton.onclick=()=>loadThreads(true);rows.append(moreButton);}
      else if(!rows.children.length)rows.textContent='暂无会话';
     }catch(error){failure(error);}finally{busy=false;}
    }
    group.ontoggle=()=>{if(group.open){expanded.add(section.id);if(!loaded)loadThreads(false);}else expanded.delete(section.id);};
    group.open=section.pinned||expanded.has(section.id);
   }
   if(page.nextCursor){const more=el('button','加载更多分组');more.className='quiet';more.onclick=async()=>{more.disabled=true;try{await load(page.nextCursor);if(current())more.remove();}catch(error){if(current()){more.disabled=false;config.notice(error.message);}}};container.append(more);}
  }
  try{await load();}catch(error){if(current()){const retry=el('button','分组读取失败 · 重试');retry.className='quiet';retry.title=error.message;retry.onclick=refresh;container.append(retry);}}
 }
 return {configure(value){config=value;},update(){if(!config)return;const scope=config.scope(),next=allowed();if(scope!==activeScope||next!==capable){activeScope=scope;capable=next;expanded.clear();refresh();}},refresh};
})();
