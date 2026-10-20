/* Desktop layout preference; no conversation or execution state lives here. */
(() => {
  const aside=document.querySelector('main > aside');
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
    for(const id of ['view-changes','open-side'])panel.append(document.getElementById(id));
    for(const detail of [...actions.querySelectorAll(':scope > .session-actions,:scope > .session-info')])panel.append(detail);
    panel.append(document.querySelector('.jobs-panel'));
    actions.append(more);
    document.addEventListener('pointerdown',event=>{if(more.open&&!more.contains(event.target))more.open=false;});
    more.addEventListener('click',event=>{if(event.target.closest('button')?.parentElement===panel){more.open=false;if(!document.querySelector('dialog:modal'))more.querySelector('summary').focus();}});
    more.addEventListener('keydown',event=>{if(event.key==='Escape'&&more.open){more.open=false;more.querySelector('summary').focus();event.preventDefault();}});
    const source=document.getElementById('history-source');
    const syncSource=()=>{source.hidden=!source.textContent||['已同步原生记录','已同步本地记录'].includes(source.textContent);};
    new MutationObserver(syncSource).observe(source,{childList:true,subtree:true});
    mobileLayout.addEventListener('change',()=>requestAnimationFrame(syncSource));
    syncSource();
  }
  const handle=document.createElement('div');handle.className='sidebar-resize';handle.tabIndex=0;
  handle.setAttribute('role','separator');handle.setAttribute('aria-label','调整侧栏宽度');handle.setAttribute('aria-orientation','vertical');
  aside.append(handle);
  const connection=document.querySelector('header .connection');
  new ResizeObserver(()=>document.documentElement.style.setProperty('--desktop-connection-height',connection.getBoundingClientRect().height+'px')).observe(connection);
  const bounds=()=>({min:240,max:Math.max(240,Math.min(520,innerWidth-320))});
  const update=(width,persist=true)=>{
    const {min,max}=bounds();width=Math.min(max,Math.max(min,width));
    document.documentElement.style.setProperty('--carryon-sidebar-width',width+'px');
    handle.setAttribute('aria-valuemin',String(min));handle.setAttribute('aria-valuemax',String(max));handle.setAttribute('aria-valuenow',String(Math.round(width)));
    if(persist)try{localStorage.setItem('carryon.sidebarWidth',String(width));}catch{}
  };
  try{const stored=Number(localStorage.getItem('carryon.sidebarWidth'));update(stored||275,false);}catch{update(275,false);}
  handle.addEventListener('pointerdown',event=>{if(event.button!==0)return;event.preventDefault();handle.setPointerCapture(event.pointerId);});
  handle.addEventListener('pointermove',event=>{if(handle.hasPointerCapture(event.pointerId))update(event.clientX);});
  handle.addEventListener('pointerup',event=>{if(handle.hasPointerCapture(event.pointerId))handle.releasePointerCapture(event.pointerId);});
  handle.addEventListener('dblclick',()=>update(275));
  handle.addEventListener('keydown',event=>{
    const current=aside.getBoundingClientRect().width;
    const next={ArrowLeft:current-10,ArrowRight:current+10,Home:bounds().min,End:bounds().max}[event.key];
    if(next!==undefined){event.preventDefault();update(next);}
  });
  addEventListener('resize',()=>{const {min,max}=bounds();handle.setAttribute('aria-valuemin',String(min));handle.setAttribute('aria-valuemax',String(max));handle.setAttribute('aria-valuenow',String(Math.round(aside.getBoundingClientRect().width)));});
})();
