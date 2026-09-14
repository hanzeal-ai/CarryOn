/* Shared navigation: menu and timeline links resolve the same server-owned child records. */
const SubagentNavigation = (() => {
  function create({request, current, scope, open, failure}) {
    let version=0, dialog=null;
    const reset=()=>{version++;dialog?.close();dialog?.remove();dialog=null;};
    async function show(id=null) {
      reset();const generation=version,parent=current(),context=scope();
      if(!parent)return;
      const valid=()=>generation===version&&current()===parent&&scope()===context;
      const node=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
      const container=node('dialog');container.className='subagents-dialog';dialog=container;
      const header=node('div'),title=node('h2','子会话'),close=node('button','关闭'),body=node('div');
      close.onclick=reset;header.append(title,close);container.append(header,body);document.body.append(container);
      container.addEventListener('cancel',reset);container.showModal();body.textContent='正在加载子会话…';
      const navigate=thread=>{if(!valid())return;reset();open(thread);};
      try {
        const result=await request('/threads/'+encodeURIComponent(parent)+'/subagents');
        if(!valid())return;
        if(!Array.isArray(result.threads))throw Error('子会话目录格式不正确');
        const rows=result.threads;
        if(id){const thread=rows.find(t=>t.id===id);if(!thread)throw Error('此子会话已不可用');navigate(thread);return;}
        if(rows.length===1){navigate(rows[0]);return;}
        body.replaceChildren();
        if(!rows.length){body.textContent='暂无子会话';return;}
        for(const thread of rows){const button=node('button',thread.title+(thread.access?.canInteract===true?'':' · 只读'));button.onclick=()=>navigate(thread);body.append(button);}
      } catch(error) {
        if(!valid())return;
        body.replaceChildren(node('p',error.message));const retry=node('button','重试');retry.onclick=()=>show(id);body.append(retry);failure?.(error);
      }
    }
    return {show,reset};
  }
  return {create};
})();
if(typeof module!=='undefined')module.exports=SubagentNavigation;
