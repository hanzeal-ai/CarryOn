/* Native full-text discovery. Search never loads or sends to a task. */
(() => {
  const dialog=document.createElement('dialog');dialog.className='archive-dialog search-dialog';
  dialog.setAttribute('aria-label','搜索会话内容');
  const head=document.createElement('div');head.className='dialog-head';
  const heading=document.createElement('h2');heading.textContent='搜索会话内容';
  const back=document.createElement('button');back.type='button';back.textContent='返回结果';back.hidden=true;
  const close=document.createElement('button');close.type='button';close.textContent='关闭';
  head.append(back,heading,close);
  const input=document.createElement('input');input.type='search';input.placeholder='搜索消息内容';input.setAttribute('aria-label','搜索消息内容');input.maxLength=200;
  const status=document.createElement('p');status.setAttribute('role','status');
  const list=document.createElement('div');list.className='archive-list';
  const more=document.createElement('button');more.textContent='加载更多';more.type='button';more.hidden=true;
  dialog.append(head,input,status,list,more);document.body.append(dialog);
  let config,version=0,timer,cursor=null,busy=false,capturedScope,term='',thread=null;
  const current=token=>version===token&&dialog.open&&config.allowed()&&config.scope()===capturedScope;
  function reset(){version++;cursor=null;busy=false;list.replaceChildren();more.hidden=true;status.textContent='';}
  async function load(append=false){
    if(!config.allowed()||!dialog.open||busy)return;
    const query=input.value.trim();if(!query){reset();status.textContent='输入消息内容以搜索';return;}
    if(!append){reset();term=query;thread=null;back.hidden=true;heading.textContent='搜索会话内容';}
    const token=version;busy=true;more.disabled=true;status.textContent='正在搜索…';
    try{
      const path=thread?'/threads/'+encodeURIComponent(thread.id)+'/search':'/search';
      const result=await config.request(path+'?search='+encodeURIComponent(term)+'&limit=30'+(append&&cursor?'&cursor='+encodeURIComponent(cursor):''));
      if(!current(token))return;
      const rows=thread?result.occurrences:result.threads;
      if(!Array.isArray(rows))throw new Error('搜索回执格式无效');
      for(const row of rows){
        const button=document.createElement('button');button.type='button';button.className='search-result';
        const title=document.createElement('strong');title.textContent=thread?'打开会话':row.title;
        const snippet=document.createElement('span'),source=row.snippet||'',range=row.snippetMatchRange;
        if(range&&Number.isInteger(range.start)&&Number.isInteger(range.end)&&range.start>=0&&range.end>range.start&&range.end<=source.length){const mark=document.createElement('mark');mark.textContent=source.slice(range.start,range.end);snippet.append(source.slice(0,range.start),mark,source.slice(range.end));}else snippet.textContent=source;
        button.append(title,snippet);
        button.onclick=()=>{if(!current(token))return;if(thread){const record=thread;dialog.close();config.open(record,row);}else{reset();thread=row;back.hidden=false;heading.textContent=row.title;status.textContent='';load(true);}};
        list.append(button);
      }
      cursor=result.nextCursor||null;more.hidden=!cursor;status.textContent=list.children.length?'':'没有匹配的消息';
    }catch(error){if(current(token))status.textContent=error.message;}
    finally{if(current(token)){busy=false;more.disabled=false;}}
  }
  back.onclick=()=>{reset();thread=null;load();input.focus();};
  close.onclick=()=>dialog.close();dialog.addEventListener('close',()=>{clearTimeout(timer);reset();});
  input.oninput=()=>{clearTimeout(timer);reset();thread=null;timer=setTimeout(()=>load(),250);};
  more.onclick=()=>load(true);
  window.SearchControls={available(){return !!config?.allowed();},configure(value){config=value;},update(){if(!config)return;const button=document.getElementById('search-content');button.hidden=!config.allowed();if(dialog.open&&(!config.allowed()||config.scope()!==capturedScope))dialog.close();},open(){if(!config.allowed())return;reset();thread=null;capturedScope=config.scope();input.value='';back.hidden=true;heading.textContent='搜索会话内容';dialog.showModal();status.textContent='输入消息内容以搜索';input.focus();}};
})();
