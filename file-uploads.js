/* Local selections become server-owned attachment IDs; paths never authorize sending. */
const FileUploads=(()=>{
  const encoder=new TextEncoder();
  function limits(value){
    for(const key of ['chunkBytes','maxEntries','maxFileBytes','maxTotalBytes'])
      if(!Number.isSafeInteger(value?.[key])||value[key]<=0)throw Error('上传限制尚未同步');
    if(value.chunkBytes>49152)throw Error('上传分块大小不受支持');
    return value;
  }
  function validPath(path){
    if(typeof path!=='string')throw Error('文件名称或路径不受支持');
    path=path.normalize('NFC');
    if(encoder.encode(path).length>512||/[\\\u0000-\u001f\u007f]/.test(path)||
      path.split('/').some(part=>!part||part==='.'||part==='..'))throw Error('文件名称或路径不受支持');
    return path;
  }
  async function prepare(name,kind,sources,settings){
    const rules=limits(settings),entries=[],data=new Map();let total=0;
    name=validPath(name);if(name.includes('/'))throw Error('文件名称不受支持');
    if(sources.length>rules.maxEntries)throw Error(`最多上传 ${rules.maxEntries} 个文件和文件夹`);
    const seen=new Set();
    for(const source of sources){
      const path=validPath(source.path);
      if(path!==name&&!path.startsWith(name+'/')||seen.has(path.toLowerCase()))throw Error('文件夹结构无效或存在同名文件');
      seen.add(path.toLowerCase());
      if(source.kind==='directory'){entries.push({path,kind:'directory'});continue;}
      const file=source.file;
      if(!file||file.size>rules.maxFileBytes)throw Error(`单个文件不能超过 ${rules.maxFileBytes/1048576} MB`);
      total+=file.size;if(total>rules.maxTotalBytes)throw Error(`一次上传不能超过 ${rules.maxTotalBytes/1048576} MB`);
      const bytes=await file.arrayBuffer();
      if(bytes.byteLength!==file.size)throw Error('文件已改变，请重新选择');
      const sha256=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('');
      entries.push({path,kind:'file',size:bytes.byteLength,sha256});data.set(path,bytes);
    }
    entries.sort((a,b)=>a.path<b.path?-1:a.path>b.path?1:0);
    return {requestId:crypto.randomUUID(),name,kind,entries,data,total,chunkBytes:rules.chunkBytes};
  }
  async function directory(handle,settings){
    const rules=limits(settings),sources=[];
    async function walk(item,path){
      validPath(path);
      if(sources.length>=rules.maxEntries)throw Error(`最多上传 ${rules.maxEntries} 个文件和文件夹`);
      if(item.kind==='directory'){
        sources.push({path,kind:'directory'});
        for await(const child of item.values())await walk(child,path+'/'+child.name);
      }else if(item.kind==='file')sources.push({path,kind:'file',file:await item.getFile()});
      else throw Error('无法读取此文件类型');
    }
    await walk(handle,handle.name);return prepare(handle.name,'directory',sources,rules);
  }
  async function directoryFiles(files,settings){
    if(!files.length)throw Error('此浏览器未提供文件夹内容，请使用支持文件夹访问的浏览器');
    const name=validPath(files[0].webkitRelativePath.split('/')[0]),folders=new Set([name]),sources=[];
    for(const file of files){
      const path=validPath(file.webkitRelativePath);
      if(!path.startsWith(name+'/'))throw Error('请选择一个文件夹');
      const parts=path.split('/');for(let i=1;i<parts.length;i++)folders.add(parts.slice(0,i).join('/'));
      sources.push({path,kind:'file',file});
    }
    return prepare(name,'directory',[...[...folders].map(path=>({path,kind:'directory'})),...sources],settings);
  }
  const sameTarget=(a,b)=>a?.type===b?.type&&(a?.type==='thread'?a.threadId===b.threadId:a?.type==='creation'&&(a.projectId||null)===(b.projectId||null));
  async function transfer(item,target,request,current=()=>true,progress=()=>{}){
    const check=()=>{if(!current())throw Error('上传已暂停，请返回原工作区重试');};
    const call=async body=>{check();const result=await request('/uploads',body);check();return result;};
    const receipt=await call({action:'begin',requestId:item.requestId,name:item.name,kind:item.kind,entries:item.entries,target});
    const valid=result=>typeof result?.id==='string'&&/^[0-9a-f]{32}$/.test(result.id)&&result.name===item.name&&result.kind===item.kind&&sameTarget(result.target,target);
    if(!valid(receipt)||!['uploading','complete'].includes(receipt.state)||(item.uploadId&&item.uploadId!==receipt.id))throw Error('上传回执不匹配');
    item.uploadId=receipt.id;
    if(receipt.state==='complete'){progress(100);return receipt;}
    let sent=0;
    for(const entry of item.entries){
      if(entry.kind!=='file')continue;
      const bytes=new Uint8Array(item.data.get(entry.path));
      for(let offset=0;offset<bytes.length;offset+=item.chunkBytes){
        const chunk=bytes.subarray(offset,Math.min(bytes.length,offset+item.chunkBytes));
        const result=await call({action:'chunk',uploadId:receipt.id,path:entry.path,offset,data:btoa(String.fromCharCode(...chunk))});
        if(result.offset!==offset+chunk.length)throw Error('上传进度不匹配，请重试');
        sent+=chunk.length;progress(Math.round(sent/Math.max(1,item.total)*100));
      }
    }
    const complete=await call({action:'complete',uploadId:receipt.id});
    if(!valid(complete)||complete.id!==receipt.id||complete.state!=='complete')throw Error('上传完成状态尚未确认，请重试');
    progress(100);return complete;
  }
  function mount({root,fileButton,folderButton,context,enabled,supported,settings,request,changed,notice}){
    const drafts=new Map(),key=ctx=>ctx?JSON.stringify([ctx.scope,ctx.target]):null;
    const storageKey='carryon-upload-drafts:'+root.id;
    let persistenceFailed=false;
    try{
      const saved=JSON.parse(sessionStorage.getItem(storageKey)||'[]');
      if(!Array.isArray(saved)||saved.length>1000)throw Error('invalid upload drafts');
      for(const value of saved){
        const ctx=value.context,receipt=value.receipt,target=ctx?.target;
        if(typeof ctx?.scope!=='string'||ctx.scope.length>4096||
          !['thread','creation'].includes(target?.type)||
          (target.type==='thread'&&(typeof target.threadId!=='string'||!target.threadId))||
          (target.type==='creation'&&target.projectId!=null&&typeof target.projectId!=='string')||
          !/^[0-9a-f]{32}$/.test(receipt?.id)||!['file','directory'].includes(receipt?.kind)||
          validPath(receipt?.name)!==receipt.name||receipt.name.includes('/')||!sameTarget(receipt.target,target))throw Error('invalid upload receipt');
        const draftKey=key(ctx),items=drafts.get(draftKey)||[];
        if(items.length>=20||items.some(item=>item.receipt.id===receipt.id))throw Error('invalid upload count');
        drafts.set(draftKey,[...items,{key:draftKey,context:ctx,name:receipt.name,receipt,state:'complete',progress:100}]);
      }
    }catch{drafts.clear();}
    function persist(){
      try{
        const saved=[...drafts.values()].flat().filter(item=>item.state==='complete').map(item=>({
          context:{scope:item.context.scope,target:item.context.target},receipt:{id:item.receipt.id,name:item.receipt.name,kind:item.receipt.kind,target:item.context.target}
        }));
        if(saved.length)sessionStorage.setItem(storageKey,JSON.stringify(saved));else sessionStorage.removeItem(storageKey);
        persistenceFailed=false;
      }catch{
        if(!persistenceFailed)notice('无法保存附件草稿，请检查浏览器存储设置后重试');
        persistenceFailed=true;
      }
    }
    const list=ctx=>drafts.get(key(ctx))||[];
    const current=()=>list(context());
    function render(){
      fileButton.hidden=folderButton.hidden=!supported();
      fileButton.disabled=folderButton.disabled=!enabled();
      root.replaceChildren();root.hidden=!current().length;
      for(const item of current()){
        const chip=document.createElement('span');chip.className='upload-chip';chip.dataset.state=item.state;
        const label=document.createElement('span');label.className='upload-name';
        label.textContent=item.name+(item.state==='uploading'?` · ${item.progress}%`:item.state==='preparing'?' · 读取中':item.state==='error'?' · 上传失败':'');
        label.title=item.error||item.name;chip.append(label);
        if(item.state==='error'){
          const retry=document.createElement('button');retry.type='button';retry.textContent='重试';retry.disabled=!enabled();
          retry.setAttribute('aria-label','重试上传 '+item.name);retry.onclick=()=>run(item);chip.append(retry);
        }
        if(persistenceFailed&&item.state==='complete'){
          const retry=document.createElement('button');retry.type='button';retry.textContent='重试保存';retry.onclick=refresh;chip.append(retry);
        }
        const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label','移除附件 '+item.name);
        remove.onclick=()=>{item.cancelled=true;drafts.set(item.key,(drafts.get(item.key)||[]).filter(v=>v!==item));refresh();};chip.append(remove);root.append(chip);
      }
    }
    function refresh(){persist();render();changed();}
    async function run(item){
      if(item.running||!enabled()||key(context())!==item.key)return;
      item.context={...item.context,epoch:context().epoch};
      item.running=true;item.state=item.prepared?'uploading':'preparing';item.error=null;refresh();
      try{
        item.prepared??=await item.prepare();
        if(item.cancelled)return;
        item.name=item.prepared.name;item.state='uploading';refresh();
        item.receipt=await transfer(item.prepared,item.context.target,request,
          ()=>!item.cancelled&&context()?.scope===item.context.scope&&context()?.epoch===item.context.epoch&&supported(),
          value=>{item.progress=value;render();});
        item.state='complete';item.prepared=null;item.prepare=null;
      }catch(error){item.state='error';item.error=error.message;if(!item.cancelled&&key(context())===item.key)notice(error.message);}
      finally{item.running=false;refresh();}
    }
    function add(ctx,name,prepare){
      if(!ctx||key(context())!==key(ctx)||!enabled())return;
      const items=list(ctx);
      if(items.length>=20){notice('每条消息最多添加 20 个上传附件');return;}
      const item={key:key(ctx),context:ctx,name,prepare,state:'preparing',progress:0};
      drafts.set(item.key,[...items,item]);run(item);
    }
    const files=document.createElement('input');files.type='file';files.multiple=true;files.hidden=true;files.id=fileButton.id+'-input';
    const folders=document.createElement('input');folders.type='file';folders.webkitdirectory=true;folders.hidden=true;folders.id=folderButton.id+'-input';
    root.after(files,folders);let filesContext=null,folderContext=null;
    fileButton.onclick=()=>{if(enabled()){filesContext=context();files.click();}};
    files.onchange=()=>{
      const selected=[...files.files],ctx=filesContext;files.value='';
      for(const file of selected)add(ctx,file.name,()=>prepare(file.name,'file',[{path:file.name,kind:'file',file}],settings()));
    };
    folderButton.onclick=async()=>{
      if(!enabled())return;const ctx=context();
      if(typeof window.showDirectoryPicker==='function'){
        try{const handle=await window.showDirectoryPicker({mode:'read'});add(ctx,handle.name,()=>directory(handle,settings()));}
        catch(error){if(error.name!=='AbortError')notice(error.message);}
      }else {folderContext=ctx;folders.click();}
    };
    folders.onchange=()=>{
      const selected=[...folders.files],ctx=folderContext;folders.value='';
      if(!selected.length){notice('此浏览器无法读取空目录，请使用支持文件夹访问的浏览器');return;}
      notice('此浏览器上传文件夹时不包含空目录');add(ctx,selected[0].webkitRelativePath.split('/')[0],()=>directoryFiles(selected,settings()));
    };
    return {
      render,has:()=>current().length>0,blocked:()=>(persistenceFailed&&current().length>0)||current().some(v=>v.state!=='complete'),
      snapshot:()=>({key:key(context()),ids:current().filter(v=>v.state==='complete').map(v=>v.receipt.id)}),
      didSubmit(snapshot){drafts.set(snapshot.key,(drafts.get(snapshot.key)||[]).filter(v=>!snapshot.ids.includes(v.receipt?.id)));refresh();},
      clear(){for(const items of drafts.values())for(const item of items)item.cancelled=true;drafts.clear();refresh();}
    };
  }
  return {prepare,directory,directoryFiles,transfer,mount};
})();
if(typeof module!=='undefined')module.exports=FileUploads;
