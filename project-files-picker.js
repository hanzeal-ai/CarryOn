/* Search and selection identities come from the current native project. */
const ProjectFilesPicker = (() => {
  function create({load,current,selection,change,editable}) {
    const dialog=document.createElement('dialog');dialog.className='skills-picker project-files-picker';dialog.setAttribute('aria-label','项目文件');
    const header=document.createElement('div');header.className='dialog-head';
    const title=document.createElement('h2');title.textContent='项目文件';
    const close=document.createElement('button');close.type='button';close.textContent='完成';close.onclick=()=>dialog.close();header.append(title,close);
    const form=document.createElement('form'),search=document.createElement('input'),submit=document.createElement('button');
    search.type='search';search.maxLength=200;search.placeholder='搜索项目文件';search.setAttribute('aria-label','搜索项目文件');submit.type='submit';submit.textContent='搜索';
    form.append(search,submit);const status=document.createElement('p');status.setAttribute('role','status');const rows=document.createElement('div');rows.className='skill-options';dialog.append(header,form,status,rows);document.body.append(dialog);
    let generation=0,target=null,catalog=[],busy=false,composing=false;
    search.addEventListener('compositionstart',()=>composing=true);search.addEventListener('compositionend',()=>composing=false);
    const valid=()=>target&&current()?.key===target.key&&editable();
    function render(){const active=document.activeElement,focused=rows.contains(active)?active.dataset.path:null;rows.replaceChildren();const chosen=new Set(selection().map(file=>file.path));
      for(const file of catalog){const row=document.createElement('button');row.type='button';row.className='skill-option';row.dataset.path=file.path;row.setAttribute('aria-pressed',String(chosen.has(file.path)));row.disabled=!valid()||busy||(!chosen.has(file.path)&&chosen.size>=20);
        const name=document.createElement('strong'),path=document.createElement('small');name.textContent=file.name;path.textContent=file.relativePath;row.append(name,path);
        row.onclick=()=>{if(!valid()||busy)return;const previous=selection();change(chosen.has(file.path)?previous.filter(item=>item.path!==file.path):[...previous,{name:file.name,path:file.path,query:file.query}]);render();};rows.append(row);
      }if(focused){const restored=[...rows.children].find(row=>row.dataset.path===focused);if(restored&&!restored.disabled)restored.focus({preventScroll:true});}submit.disabled=busy||!valid();search.disabled=busy||!valid();
    }
    form.onsubmit=async event=>{event.preventDefault();if(composing||event.isComposing||search.matches(':disabled')||!valid()||busy)return;const query=search.value.trim();if(!query||query.length>200)return;const version=++generation;busy=true;catalog=[];status.textContent='正在搜索…';render();
      try{const result=await load(target.id,query);if(version!==generation||!valid()||!dialog.open)return;
        if(result.threadId!==target.id||!Array.isArray(result.files)||result.files.some(file=>typeof file.name!=='string'||typeof file.path!=='string'||!file.path.startsWith('/')||typeof file.relativePath!=='string'||file.query!==query)||new Set(result.files.map(file=>file.path)).size!==result.files.length)throw Error('文件搜索结果无效');
        catalog=result.files;status.textContent=catalog.length?'':'没有匹配的项目文件';
      }catch(error){if(version===generation&&valid())status.textContent=error.message;}
      finally{if(version===generation){busy=false;render();}}
    };
    function open(){target=current();if(!valid())return;generation++;busy=false;composing=false;catalog=[];search.value='';status.textContent='';dialog.showModal();render();search.focus();}
    dialog.addEventListener('close',()=>{generation++;busy=false;composing=false;catalog=[];});
    function refresh(){if(dialog.open){if(!valid())dialog.close();else render();}}
    return {open,refresh};
  }
  return {create};
})();
