/* Native skill identities stay separate from prompt text. The server validates each selection. */
const SkillsPicker = (() => {
  function create({load,current,selection,change,editable,title:label='技能',field='skills'}) {
    const dialog=document.createElement('dialog');dialog.className='skills-picker';dialog.setAttribute('aria-label',label);
    const header=document.createElement('div');header.className='dialog-head';
    const title=document.createElement('h2');title.textContent=label;
    const close=document.createElement('button');close.type='button';close.textContent='完成';close.onclick=()=>dialog.close();header.append(title,close);
    const search=document.createElement('input');search.type='search';search.placeholder='搜索'+label;search.setAttribute('aria-label','搜索'+label);
    const status=document.createElement('p');status.setAttribute('role','status');const rows=document.createElement('div');rows.className='skill-options';
    dialog.append(header,search,status,rows);document.body.append(dialog);
    let generation=0,catalog=[],target=null;
    const valid=()=>target&&current()?.key===target.key;
    const key=skill=>JSON.stringify([skill.name,skill.path]);
    function render(){
      rows.replaceChildren();const selected=new Set(selection().map(key));
      for(const skill of catalog.filter(s=>!search.value||(`${s.name} ${s.interface?.displayName||''} ${s.description||''}`).toLocaleLowerCase().includes(search.value.toLocaleLowerCase()))){
        const row=document.createElement('button');row.type='button';row.className='skill-option';row.setAttribute('aria-pressed',String(selected.has(key(skill))));
        const name=document.createElement('strong');name.textContent=skill.interface?.displayName||skill.name;
        const description=document.createElement('small');description.textContent=skill.interface?.shortDescription||skill.description||'';
        const titleRow=document.createElement('span');titleRow.className='reference-title';titleRow.append(ComposerReferenceIcon.create(skill),name);row.append(titleRow,description);row.disabled=!valid()||!editable()||skill.enabled!==true||(!selected.has(key(skill))&&selected.size>=20);
        row.onclick=()=>{if(!valid()||!editable())return;const previous=selection();change(selected.has(key(skill))?previous.filter(s=>key(s)!==key(skill)):[...previous,{name:skill.name,path:skill.path,displayName:skill.interface?.displayName||skill.name,...(skill.iconData?{iconData:skill.iconData}:{})}]);render();};rows.append(row);
      }
    }
    search.oninput=render;
    async function open(){
      target=current();if(!target||!editable())return;const version=++generation;catalog=[];search.value='';rows.replaceChildren();status.textContent='正在读取'+label+'…';dialog.showModal();
      try{const result=await load(target.id);if(version!==generation||!valid()||!dialog.open)return;
        catalog=result[field]||[];status.textContent=(result.errors||[]).map(e=>e.message||e.path).join('\n')||(catalog.length?'':'当前项目没有可用'+label);render();
      }catch(error){if(version===generation&&valid())status.textContent=error.message;}
    }
    dialog.addEventListener('close',()=>{generation++;});
    function refresh(){if(dialog.open){if(!valid())dialog.close();else render();}}
    return {open,refresh};
  }
  return {create};
})();
