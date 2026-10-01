const GoalControls = (() => {
  const writes=new Set();
  const labels={active:'进行中',paused:'已暂停',blocked:'受阻',usageLimited:'已达用量限制',budgetLimited:'已达预算',complete:'已完成'};
  function render(root,{history,threadId,api,current,writable,drafts,notice}) {
    const goal=history.controls.goal,scope=api.epoch,same=()=>current()&&api.epoch===scope;
    const detail=document.createElement('details');detail.className='mobile-goal';
    const summary=document.createElement('summary');summary.textContent='会话目标';detail.append(summary);root.append(detail);
    const pending=()=>[...writes].find(item=>item.api===api&&item.scope===scope&&item.threadId===threadId);
    const permissions=api.devices?.find(device=>device.id===api.device)?.permissions;
    const allowed=action=>writable&&!history.controls.goalUnknown&&(!permissions||permissions.includes(action==='goal-set'?'send':'stop'));
    if(goal){const stats=document.createElement('p');stats.textContent=`${labels[goal.status]||goal.status} · 已用 ${goal.tokensUsed} Token${goal.tokenBudget==null?'':` / ${goal.tokenBudget}`} · ${goal.timeUsedSeconds} 秒`;detail.append(stats);}
    function field(label,key,value,multiline){
      const holder=document.createElement('label');holder.textContent=label;
      const input=document.createElement(multiline?'textarea':'input');input.setAttribute('aria-label',label);input.dataset.draftKey=key;
      input.value=drafts.has(key)?drafts.get(key):value;holder.append(input);detail.append(holder);return input;
    }
    const objective=field('目标内容','goal:objective',goal?.objective||'',true);
    const budget=field(goal?'新 Token 预算（留空保留）':'Token 预算（可选）','goal:budget','',false);budget.inputMode='numeric';
    const explanation=document.createElement('p');explanation.textContent='启动后会持续执行，直到目标完成、暂停或达到限制。暂停或移除会停止后续自动执行，当前轮次可在对话中单独停止。';detail.append(explanation);
    const status=document.createElement('p');status.setAttribute('role','status');detail.append(status);
    if(history.controls.goalUnknown){
      status.textContent='目标状态尚未确认，请先核对，避免重复启动。';
      const refresh=document.createElement('button');refresh.type='button';refresh.textContent='核对目标状态';detail.append(refresh);
      refresh.onclick=async()=>{if(!same()||refresh.disabled)return;refresh.disabled=true;
        try{await api.request('/threads/'+encodeURIComponent(threadId)+'/goal');if(same())status.textContent='已读取目标状态，正在同步…';}
        catch(error){if(same())status.textContent=error.message;}
        finally{if(same())refresh.disabled=false;}
      };
    }
    const buttons=[];
    const valid=()=>!!objective.value.trim()&&(!budget.value.trim()||(/^\d+$/.test(budget.value.trim())&&Number.isSafeInteger(Number(budget.value))&&Number(budget.value)>0));
    function update(){const busy=!!pending();objective.disabled=budget.disabled=busy;for(const {button,action,requiresInput}of buttons)button.disabled=busy||!allowed(action)||(requiresInput&&!valid());}
    function button(label,action,fields,requiresInput=false){
      const button=document.createElement('button');button.type='button';button.textContent=label;detail.append(button);buttons.push({button,action,requiresInput});
      button.onclick=async()=>{
        if(!same()||pending()||!allowed(action)||(requiresInput&&!valid()))return;
        const item={api,scope,threadId};writes.add(item);status.textContent='正在更新…';
        item.promise=api.operation(threadId,action,fields(),same).finally(()=>writes.delete(item));update();
        try{const job=await item.promise;if(!same())return;if(job.state!=='completed')throw Error(job.error||'尚未确认目标变更，请核对请求记录');status.textContent='目标已更新';}
        catch(error){if(same()){status.textContent=error.message;notice(error.message);}}
        finally{if(same())update();}
      };
    }
    button(goal?'保存目标':'启动目标','goal-set',()=>({objective:objective.value,...(budget.value.trim()?{tokenBudget:Number(budget.value)}:{}),...(!goal?{status:'active'}:{})}),true);
    if(goal){
      if(goal.status==='active')button('暂停目标','goal-pause',()=>({}));
      else if(goal.status!=='complete')button('继续目标','goal-set',()=>({status:'active'}));
      if(goal.status!=='complete')button('标记为完成','goal-set',()=>({status:'complete'}));
      button('移除目标','goal-clear',()=>({}));
    }
    objective.oninput=budget.oninput=update;update();
    const running=pending();if(running){status.textContent='正在更新…';running.promise.then(job=>{if(same()){status.textContent=job.state==='completed'?'目标已更新':job.error||'尚未确认目标变更，请核对请求记录';update();}},error=>{if(same()){status.textContent=error.message;update();}});}
    return detail;
  }
  return {render};
})();
