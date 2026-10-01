const ReviewControls = (() => {
  const writes=new Set();
  function render(root,{history,threadId,api,current,writable,drafts,notice}) {
    const detail=document.createElement('details');detail.className='mobile-review';
    const summary=document.createElement('summary');summary.textContent='审查代码';detail.append(summary);root.append(detail);
    const scope=api.epoch, same=()=>current()&&api.epoch===scope;
    const pending=()=>[...writes].find(item=>item.api===api&&item.scope===scope&&item.threadId===threadId);
    const select=document.createElement('select');select.setAttribute('aria-label','审查范围');select.dataset.draftKey='review:kind';
    for(const [value,label]of [['uncommittedChanges','未提交的改动'],['baseBranch','对比分支'],['commit','指定提交'],['custom','自定义审查']])select.append(new Option(label,value));
    select.value=drafts.get('review:kind')||'uncommittedChanges';detail.append(select);
    const fields={};
    for(const [kind,label,multiline]of [['baseBranch','分支名称',false],['commit','提交 SHA',false],['custom','审查要求',true]]){
      const holder=document.createElement('label');holder.textContent=label;
      const input=document.createElement(multiline?'textarea':'input');input.setAttribute('aria-label',label);input.dataset.draftKey='review:'+kind;
      input.value=drafts.get(input.dataset.draftKey)||'';input.maxLength=16000;holder.append(input);detail.append(holder);fields[kind]={holder,input};
    }
    const explanation=document.createElement('p');explanation.textContent='审查将在当前会话运行，结果显示在对话中。';detail.append(explanation);
    const status=document.createElement('p');status.setAttribute('role','status');detail.append(status);
    const submit=document.createElement('button');submit.type='button';submit.textContent='开始审查';detail.append(submit);
    const ready=()=>writable&&history.status?.state==='idle'&&!(history.queue?.messages?.length)&&!(history.controls.requests?.length);
    const valid=()=>select.value==='uncommittedChanges'||!!fields[select.value]?.input.value.trim();
    function update(){
      const busy=!!pending();select.disabled=busy;for(const [kind,{holder,input}]of Object.entries(fields)){holder.hidden=kind!==select.value;input.disabled=busy;}
      submit.disabled=busy||!ready()||!valid();
    }
    select.onchange=update;for(const {input}of Object.values(fields))input.oninput=update;
    submit.onclick=async()=>{
      if(!same()||!ready()||!valid()||pending())return;
      const target={type:select.value};if(select.value==='baseBranch')target.branch=fields.baseBranch.input.value.trim();
      if(select.value==='commit')target.sha=fields.commit.input.value.trim();if(select.value==='custom')target.instructions=fields.custom.input.value;
      const item={api,scope,threadId};writes.add(item);status.textContent='正在启动…';
      item.promise=api.review(threadId,target,same).finally(()=>writes.delete(item));update();
      try{const job=await item.promise;if(!same())return;if(job.state!=='completed')throw Error(job.error||'尚未确认审查启动，请核对请求记录');status.textContent='审查已启动';}
      catch(error){if(same()){status.textContent=error.message;notice(error.message);}}
      finally{if(same())update();}
    };
    update();const running=pending();if(running){status.textContent='正在启动…';running.promise.then(job=>{if(same()){status.textContent=job.state==='completed'?'审查已启动':job.error||'尚未确认审查启动，请核对请求记录';update();}},error=>{if(same()){status.textContent=error.message;update();}});}
    return detail;
  }
  return {render};
})();
