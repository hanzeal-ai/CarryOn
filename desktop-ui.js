/* Desktop layout preference; no conversation or execution state lives here. */
(() => {
  const aside=document.querySelector('main > aside');
  const icon=path=>{const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');svg.innerHTML=path;return svg;};
  const rail=document.createElement('nav');rail.className='app-rail';rail.setAttribute('aria-label','应用导航');
  const railButton=(label,path,target)=>{const b=document.createElement('button');b.type='button';b.title=label;b.setAttribute('aria-label',label);b.append(icon(path));b.onclick=()=>document.getElementById(target).click();rail.append(b);return b;};
  const home=railButton('首页','<path d="m3 10 9-7 9 7v10H5V10m4 10v-7h6v7"/>','show-projects');
  const activity=railButton('动态','<circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/>','show-activity');
  const plugins=railButton('插件','<path d="M9 3h6v5h4v6h-4v6H9v-6H4V8h5Z"/>','manage-plugins');
  document.body.append(rail);
  const syncRail=()=>{home.setAttribute('aria-current',document.getElementById('show-activity').getAttribute('aria-pressed')==='true'?'false':'page');activity.setAttribute('aria-current',document.getElementById('show-activity').getAttribute('aria-pressed')==='true'?'page':'false');const source=document.getElementById('manage-plugins');plugins.hidden=source.hidden;plugins.disabled=source.disabled;};
  const railObserver=new MutationObserver(syncRail);for(const id of ['show-projects','show-all','show-activity','manage-plugins'])railObserver.observe(document.getElementById(id),{attributes:true,attributeFilter:['hidden','disabled','aria-pressed']});syncRail();
  const collapse=document.createElement('button');collapse.type='button';collapse.id='sidebar-collapse';collapse.className='quiet';collapse.title='显示/隐藏侧边栏';collapse.setAttribute('aria-label','显示/隐藏侧边栏');collapse.setAttribute('aria-expanded','true');collapse.append(icon('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>'));
  const setCollapsed=value=>{document.body.classList.toggle('sidebar-collapsed',value);collapse.setAttribute('aria-expanded',String(!value));try{localStorage.setItem('carryon.sidebarCollapsed',String(value));}catch{}};
  collapse.onclick=()=>setCollapsed(!document.body.classList.contains('sidebar-collapsed'));
  try{setCollapsed(localStorage.getItem('carryon.sidebarCollapsed')==='true');}catch{}
  document.querySelector('body>header').append(document.getElementById('toggle-search'),collapse);
  const decorateCreate=()=>document.getElementById('create').replaceChildren(icon('<path d="M12 4H5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h13a2 2 0 0 0 2-2v-7M14 3l7 7M9 15l2-6 7-7 4 4-7 7Z"/>'),document.createTextNode('新聊天'));
  decorateCreate();mobileLayout.addEventListener('change',()=>requestAnimationFrame(()=>{if(!mobileLayout.matches)decorateCreate();}));
  const recent=document.getElementById('show-all');recent.textContent='最近';
  // Existing navigation handlers remain the authority for project and activity state.
  document.getElementById('show-activity').classList.add('activity-view-control');
  const sidebarLists=document.querySelector('.sidebar-lists'),projectSection=document.createElement('section'),recentSection=document.createElement('section'),projectList=document.createElement('div');
  projectSection.className='sidebar-project-section';recentSection.className='sidebar-recent-section';projectList.className='sidebar-project-shortcuts';
  projectSection.append(document.getElementById('show-projects'),projectList);recentSection.append(recent);sidebarLists.append(projectSection,recentSection);
  const threadList=document.getElementById('threads');let projectSignature='';
  const syncSections=()=>{
    if(mobileLayout.matches)return;
    const isProjects=document.getElementById('show-projects').getAttribute('aria-pressed')==='true'&&workspaceView==='projects';
    const destination=isProjects?projectSection:recentSection;if(threadList.parentElement!==destination)destination.append(threadList);
    projectList.hidden=isProjects;
    const signature=JSON.stringify([draftScope(),client.epoch,showInactive,workspaceProjects]);if(signature!==projectSignature){projectSignature=signature;if(!isProjects)projectList.replaceChildren(...workspaceProjects.map(projectRow));}
    if(isProjects)projectList.replaceChildren();
    else if(!projectList.children.length&&workspaceProjects.length)projectList.replaceChildren(...workspaceProjects.map(projectRow));
  };
  const sectionsObserver=new MutationObserver(syncSections);sectionsObserver.observe(threadList,{childList:true});for(const id of ['show-projects','show-all','show-activity'])sectionsObserver.observe(document.getElementById(id),{attributes:true,attributeFilter:['aria-pressed']});
  mobileLayout.addEventListener('change',()=>requestAnimationFrame(syncSections));syncSections();
  const searchToggle=document.getElementById('toggle-search'),searchRegion=document.getElementById('sidebar-search'),search=document.getElementById('search'),filter=document.getElementById('project-filter');
  searchToggle.onclick=()=>{
    searchRegion.hidden=!searchRegion.hidden;
    searchToggle.setAttribute('aria-expanded',String(!searchRegion.hidden));
    if(!searchRegion.hidden)search.focus();
    else if(search.value||filter.value!=='all'){search.value='';filter.value='all';search.dispatchEvent(new Event('input'));}
  };
  mobileLayout.addEventListener('change',()=>{
    if(!mobileLayout.matches&&(search.value||filter.value!=='all')){searchRegion.hidden=false;searchToggle.setAttribute('aria-expanded','true');}
  });
  const creation=document.getElementById('create-dialog');
  let homePresented=false;
  const presentHome=()=>{
    if(homePresented||mobileLayout.matches||document.getElementById('pairing').hidden===false||document.getElementById('create').disabled||!document.querySelector('#messages .welcome'))return;
    homePresented=true;document.getElementById('create').click();document.getElementById('new-prompt').focus();
  };
  const homeObserver=new MutationObserver(presentHome);homeObserver.observe(document.getElementById('messages'),{childList:true});homeObserver.observe(document.getElementById('create'),{attributes:true,attributeFilter:['disabled']});presentHome();

  const creationMenus=[document.getElementById('new-model-details'),document.getElementById('new-configuration-details'),document.getElementById('new-attachment-details')];
  document.getElementById('new-attachment-options').addEventListener('click',event=>{if(event.target.closest('button'))document.getElementById('new-attachment-details').open=false;});
  const attachment=document.getElementById('composer-attachment-details');
  document.getElementById('composer-attachment-options').addEventListener('click',event=>{if(event.target.closest('button'))attachment.open=false;});
  document.addEventListener('pointerdown',event=>{if(!matchMedia('(max-width:760px)').matches)for(const menu of [...creationMenus,attachment])if(menu.open&&!menu.contains(event.target))menu.open=false;});
  addEventListener('keydown',event=>{
    if(event.defaultPrevented||event.key!=='Escape'||matchMedia('(max-width:760px)').matches||document.querySelector('dialog:modal,[popover]:popover-open'))return;
    if(attachment.open){attachment.open=false;event.preventDefault();return;}
    if(!creation.open)return;
    const open=creationMenus.filter(menu=>menu.open);if(open.length)for(const menu of open)menu.open=false;else creation.close();event.preventDefault();
  });
  {
    const head=document.querySelector('.conversation-head'),toolbar=document.querySelector('.conversation > .timeline-toolbar');
    head.append(toolbar);head.classList.add('desktop-conversation-head');
    const actions=toolbar.querySelector(':scope > div');
    const more=actions.querySelector('.display-menu');
    const panel=more.querySelector(':scope > div');
    more.classList.add('conversation-more');
    panel.classList.add('conversation-more-panel');
    for(const id of ['open-side'])panel.append(document.getElementById(id));
    for(const detail of [...actions.querySelectorAll(':scope > .session-actions,:scope > .session-info')])panel.append(detail);
    panel.append(document.querySelector('.jobs-panel'));
    actions.append(more);
    const changes=document.getElementById('view-changes');changes.setAttribute('aria-label','查看改动');changes.title='查看改动';changes.replaceChildren(icon('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16M6 8h6M6 12h6M6 16h3"/>'));actions.append(changes);
    document.addEventListener('pointerdown',event=>{if(more.open&&!more.contains(event.target))more.open=false;});
    more.addEventListener('click',event=>{if(event.target.closest('button')?.parentElement===panel){more.open=false;if(!document.querySelector('dialog:modal'))more.querySelector('summary').focus();}});
    more.addEventListener('keydown',event=>{if(event.key==='Escape'&&more.open){more.open=false;more.querySelector('summary').focus();event.preventDefault();}});
    const operationLinks=document.createElement('div');operationLinks.className='desktop-operation-links';panel.append(operationLinks);
    const actionDialog=document.createElement('dialog');actionDialog.className='desktop-action-dialog';document.body.append(actionDialog);
    let restored=null,returnTo=null;
    const restoreOperations=(close=true)=>{if(restored){const {content,parent,next,open}=restored;restored=null;if(next?.parentNode===parent)parent.insertBefore(content,next);else parent.append(content);if(content.tagName==='DETAILS')content.open=open;}if(close&&actionDialog.open)actionDialog.close();};
    window.DesktopUI={restoreOperations,beforeOperationsRender(same){
      if(!same){restoreOperations();return;}
      if(!actionDialog.open||!restored||restored.parent.id!=='operations')return;
      const label=actionDialog.querySelector('h2').textContent,focused=document.activeElement;
      const key=focused?.dataset?.draftKey,buttonText=focused?.tagName==='BUTTON'?focused.textContent:null,start=focused?.selectionStart,end=focused?.selectionEnd;
      restoreOperations(false);
      return ()=>{
        const content=[...document.getElementById('operations').children].find(node=>node.querySelector('summary')?.textContent===label);
        if(!content){actionDialog.close();return;}
        restored={content,parent:content.parentNode,next:content.nextSibling,open:content.open};content.open=true;actionDialog.append(content);
        const focus=key?[...content.querySelectorAll('[data-draft-key]')].find(node=>node.dataset.draftKey===key):buttonText?[...content.querySelectorAll('button')].find(node=>node.textContent===buttonText):null;
        if(focus&&!focus.disabled){focus.focus({preventScroll:true});if(focus.setSelectionRange&&start!=null)focus.setSelectionRange(start,end);}
      };
    }};
    actionDialog.addEventListener('close',()=>{restoreOperations();returnTo?.focus();});
    const showAction=(label,content,trigger)=>{
      restoreOperations();returnTo=trigger;
      const heading=document.createElement('h2');heading.textContent=label;
      const close=document.createElement('button');close.type='button';close.className='quiet';close.textContent='关闭';close.onclick=()=>actionDialog.close();
      restored={content,parent:content.parentNode,next:content.nextSibling,open:content.open};
      if(content.tagName==='DETAILS')content.open=true;
      actionDialog.replaceChildren(heading,close,content);more.open=false;actionDialog.showModal();
    };
    window.DesktopUI.openCommandPanel=content=>{if(mobileLayout.matches)return false;showAction(content.querySelector('summary')?.textContent||'会话信息',content,more.querySelector('summary'));return true;};
    const syncOperationLinks=()=>{
      if(mobileLayout.matches)return;
      operationLinks.replaceChildren();
      const sources=[...document.getElementById('operations').children,document.querySelector('.session-info'),document.querySelector('.jobs-panel')];
      for(const content of sources){
        if(content.hidden||content.tagName!=='DETAILS')continue;
        const label=content.querySelector('summary')?.textContent;if(!label)continue;
        const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=()=>showAction(label,content,more.querySelector('summary'));operationLinks.append(b);
      }
    };
    new MutationObserver(syncOperationLinks).observe(document.getElementById('operations'),{childList:true});
    more.addEventListener('toggle',()=>{if(more.open)syncOperationLinks();});
    mobileLayout.addEventListener('change',()=>{restoreOperations();syncOperationLinks();});
    const source=document.getElementById('history-source');
    const syncSource=()=>{source.hidden=!source.textContent||['已同步原生记录','已同步本地记录'].includes(source.textContent);};
    new MutationObserver(syncSource).observe(source,{childList:true,subtree:true});
    mobileLayout.addEventListener('change',()=>requestAnimationFrame(syncSource));
    syncSource();
  }
  const menus=[document.getElementById('account-menu'),document.querySelector('.conversation-more'),...creationMenus,attachment];
  for(const menu of menus){
    menu.addEventListener('toggle',()=>{if(!menu.open||mobileLayout.matches)return;for(const other of menus)if(other!==menu)other.open=false;});
    menu.addEventListener('keydown',event=>{
      if(mobileLayout.matches||!['ArrowDown','ArrowUp','Home','End'].includes(event.key)||event.target.matches('input,textarea,select,[contenteditable]'))return;
      if(!menu.open)menu.open=true;
      const items=[...menu.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),summary')].filter(item=>item!==menu.firstElementChild&&item.getClientRects().length);
      if(!items.length)return;
      event.preventDefault();const index=items.indexOf(document.activeElement);
      const next=event.key==='Home'?0:event.key==='End'?items.length-1:event.key==='ArrowDown'?(index+1)%items.length:(index-1+items.length)%items.length;
      items[next].focus();
    });
  }
  const handle=document.createElement('div');handle.className='sidebar-resize';handle.tabIndex=0;
  handle.setAttribute('role','separator');handle.setAttribute('aria-label','调整侧栏宽度');handle.setAttribute('aria-orientation','vertical');
  aside.append(handle);
  const connection=document.querySelector('header .connection');
  new ResizeObserver(()=>document.documentElement.style.setProperty('--desktop-connection-height',connection.getBoundingClientRect().height+'px')).observe(connection);
  const bounds=()=>({min:240,max:Math.max(240,Math.min(520,innerWidth-372))});
  const update=(width,persist=true)=>{
    const {min,max}=bounds();width=Math.min(max,Math.max(min,width));
    document.documentElement.style.setProperty('--carryon-sidebar-width',width+'px');
    handle.setAttribute('aria-valuemin',String(min));handle.setAttribute('aria-valuemax',String(max));handle.setAttribute('aria-valuenow',String(Math.round(width)));
    if(persist)try{localStorage.setItem('carryon.sidebarWidth',String(width));}catch{}
  };
  try{const stored=Number(localStorage.getItem('carryon.sidebarWidth'));update(stored||288,false);}catch{update(288,false);}
  handle.addEventListener('pointerdown',event=>{if(event.button!==0)return;event.preventDefault();handle.setPointerCapture(event.pointerId);});
  handle.addEventListener('pointermove',event=>{if(handle.hasPointerCapture(event.pointerId))update(event.clientX-52);});
  handle.addEventListener('pointerup',event=>{if(handle.hasPointerCapture(event.pointerId))handle.releasePointerCapture(event.pointerId);});
  handle.addEventListener('dblclick',()=>update(288));
  handle.addEventListener('keydown',event=>{
    const current=aside.getBoundingClientRect().width;
    const next={ArrowLeft:current-10,ArrowRight:current+10,Home:bounds().min,End:bounds().max}[event.key];
    if(next!==undefined){event.preventDefault();update(next);}
  });
  addEventListener('resize',()=>{const {min,max}=bounds();handle.setAttribute('aria-valuemin',String(min));handle.setAttribute('aria-valuemax',String(max));handle.setAttribute('aria-valuenow',String(Math.round(aside.getBoundingClientRect().width)));});
})();
