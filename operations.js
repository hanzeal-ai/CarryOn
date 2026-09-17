'use strict';
const Operations = (() => {
  let selected = null, signature = '', transport, notify, writable=false;
  const seenQuestions=new Set();
  let messageEditor=null, messageEditorKey='';
  const labels = {'interrupt':'停止任务','steer':'补充指令','compact':'压缩上下文','settings':'会话设置',
    'queue-add':'添加排队任务','queue-edit':'编辑排队任务','queue-delete':'删除排队任务','queue-reorder':'调整排队顺序','queue-resume':'恢复排队任务','edit':'编辑最后一轮','clear-queue':'清空排队消息','command-approval':'命令审批',
    'file-approval':'文件审批','permissions-approval':'权限申请','user-input':'回答问题','mcp-response':'MCP 交互'};
  const el = (tag, text) => {const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
  const box = id => document.getElementById(id);
  box('question-later').onclick=()=>box('question-dialog').close();
  function reset() {messageEditor?.remove();messageEditor=null;messageEditorKey='';window.MobileUI?.resetOperations();selected=null;signature='';box('question-dialog').close();box('question-content').replaceChildren();seenQuestions.clear();box('operations').closest('.session-actions').hidden=true;for(const id of ['operations','requests']){box(id).replaceChildren();box(id).hidden=true;}}
  async function send(target, action, fields, button) {
    if(target!==selected||!writable)return;
    button.disabled=true;
    try {
      const job=await transport.operation(target,action,fields,()=>target===selected);
      if(job.state==='failed')throw Error(job.error||'操作失败');
      if(job.state==='uncertain')throw Error((job.error||'结果待确认')+'；请在 App 核对，不会自动重发');
      return true;
    } catch(e){notify(e.message);} finally{button.disabled=!writable;}
  }
  function button(parent, label, run) {const b=el('button',label);b.type='button';b.onclick=()=>run(b);parent.append(b);return b;}
  function field(parent, label, value='', multiline=false) {
    const l=el('label',label), n=el(multiline?'textarea':'input');n.value=value;
    n.dataset.draftKey=label;
    n.maxLength=16000;if(multiline)n.rows=3;l.append(n);parent.append(l);return n;
  }
  function syncMessageEditor(history, threadId) {
    const c=history.controls;
    const last=(history.timeline||[]).filter(item=>item.type==='userMessage').at(-1);
    const key=JSON.stringify([threadId,c?.lastTurnId,last?.id]);
    if(key!==messageEditorKey){messageEditor?.remove();messageEditor=null;messageEditorKey=key;}
    const row=last&&[...box('messages').querySelectorAll('.message.user')].find(el=>el.dataset.messageId===last.id);
    if(c?.supportedOperations&&!c.supportedOperations.includes('edit')||!writable||history.syncing===true||history.status?.state!=='idle'||!c?.lastUserText||!c.lastTurnId||last?.turnId!==c.lastTurnId||!row){messageEditor?.remove();return;}
    if(!messageEditor){
      const editor=el('details');editor.className='message-editor';editor.append(el('summary','编辑'));
      const input=field(editor,'修改最后一条消息',c.lastUserText,true);
      button(editor,'取消',()=>{input.value=c.lastUserText;editor.open=false;});
      const submit=button(editor,'重新发送',async b=>{
        if(!input.value.trim()||!editor.isConnected||threadId!==selected)return;
        input.disabled=true;
        if(await send(threadId,'edit',{turnId:c.lastTurnId,prompt:input.value,confirmed:true},b)){editor.open=false;}
        input.disabled=false;
      });
      input.oninput=()=>{submit.disabled=!input.value.trim();};
      messageEditor=editor;
    }
    row.append(messageEditor);
  }
  function render(history, threadId, api, notice, canWrite=true) {
    writable=canWrite&&history.access?.canInteract!==false;
    if(history.access?.canInteract===false){reset();return;}
    transport=api;notify=notice;
    const c=history.controls;
    if(!c||history.syncing===true){reset();return;}
    syncMessageEditor(history,threadId);
    const next=JSON.stringify([threadId,c,history.runtime,history.status,history.queue,canWrite]);
    if(next===signature)return;
    window.MobileUI?.beforeOperationsRender();
    const same=selected===threadId;
    const opened=same?new Set([...box('operations').querySelectorAll('details[open]')].map(d=>d.querySelector('summary')?.textContent)):new Set();
    const allDrafts=same?new Map([...box('operations').querySelectorAll('[data-draft-key]'),...box('requests').querySelectorAll('[data-draft-key]'),...box('question-content').querySelectorAll('[data-draft-key]')].map(n=>[n.dataset.draftKey,n.value])):new Map();
    const focused=document.activeElement;
    const dialogWasOpen=same&&box('question-dialog').open;
    box('question-dialog').close();
    box('question-content').replaceChildren();
    const draft=same&&focused?.dataset.draftKey?{key:focused.dataset.draftKey,value:focused.value,start:focused.selectionStart,end:focused.selectionEnd}:null;
    selected=threadId;signature=next;
    const root=box('operations'), requests=box('requests');root.hidden=false;root.closest('.session-actions').hidden=false;root.replaceChildren();requests.replaceChildren();
    const active=history.runtime?.type==='active'&&c.activeTurnId;
    const idle=history.status?.state==='idle';
    if(active){
      button(root,'停止任务',b=>send(threadId,'interrupt',{expectedTurnId:c.activeTurnId},b));
      const detail=el('details');detail.append(el('summary','补充指令'));root.append(detail);
      const input=field(detail,'给正在执行的任务补充说明','',true);
      button(detail,'发送补充指令',b=>send(threadId,'steer',{expectedTurnId:c.activeTurnId,prompt:input.value},b));
    }
    if(['active','idle'].includes(history.runtime?.type)&&(!c.supportedOperations||c.supportedOperations.includes('settings'))){
      const settings=el('details');settings.classList.add('mobile-session-settings');settings.append(el('summary','会话设置'));root.append(settings);
      const model=field(settings,'模型',c.settings.model||history.metadata?.latestModel||'');
      const effortLabel=el('label','思考强度'), effort=el('select');
      for(const value of ['', 'none','minimal','low','medium','high','xhigh','max','ultra'])effort.append(new Option(value||'默认',value));
      const currentEffort=c.settings.effort||history.metadata?.latestReasoningEffort||'';
      if(![...effort.options].some(o=>o.value===currentEffort))effort.append(new Option(currentEffort,currentEffort));
      effort.value=currentEffort;effortLabel.append(effort);settings.append(effortLabel);
      button(settings,'保存设置',b=>send(threadId,'settings',{settings:{model:model.value||null,effort:effort.value||null}},b));
      const advanced=el('details');advanced.append(el('summary','全部设置'));settings.append(advanced);
      advanced.append(el('p','填写需要修改的字段；未填写的设置保持不变。权限、沙箱和工作目录的更改会影响后续任务。'));
      advanced.append(el('small','支持：model、effort、serviceTier、cwd、approvalPolicy、approvalsReviewer、sandboxPolicy、permissions、activePermissionProfile、collaborationMode、personality、summary'));
      const editable={...c.settings};
      // Snapshots contain the resolved sandbox alongside its named profile.
      // Updates accept the profile or an explicit sandbox, not both.
      if(editable.permissions!=null||editable.activePermissionProfile!=null)delete editable.sandboxPolicy;
      const raw=field(advanced,'高级设置 JSON',JSON.stringify(editable,null,2),true);raw.rows=10;
      button(advanced,'应用全部设置',b=>{try{const patch=JSON.parse(raw.value);if(confirm('确认将填写的设置应用于此会话后续任务？'))send(threadId,'settings',{settings:patch},b);}catch(e){notice('设置 JSON 格式错误：'+e.message);}});
      const queue=el('details');queue.classList.add('mobile-queue');queue.append(el('summary','排队任务'));root.append(queue);
      if(!history.queue||history.queue.error){queue.append(el('p',history.queue?.error||'队列尚未同步'));}
      else{
        const q=history.queue, base={queueFingerprint:q.fingerprint};
        const input=field(queue,'下一轮任务','',true);
        input.parentElement.classList.add('mobile-redundant-operation');
        button(queue,'加入队列',b=>send(threadId,'queue-add',{...base,prompt:input.value},b)).classList.add('mobile-redundant-operation');
        const list=el('div');queue.append(list);
        if(!q.messages.length)list.append(el('p','暂无排队任务'));
        q.messages.forEach((m,index)=>{
          const card=el('section');card.className='queue-item';list.append(card);
          const text=field(card,`第 ${index+1} 条排队任务`,m.text||'',true);
          text.dataset.draftKey='queue:'+m.id;
          if(m.pausedReason)card.append(el('p','已暂停：'+m.pausedReason));
          button(card,'保存内容',b=>send(threadId,'queue-edit',{...base,messageId:m.id,prompt:text.value},b));
          const move=(delta,b)=>{const ids=q.messages.map(m=>m.id);[ids[index],ids[index+delta]]=[ids[index+delta],ids[index]];send(threadId,'queue-reorder',{...base,messageIds:ids},b);};
          if(index)button(card,'上移',b=>move(-1,b));
          if(index<q.messages.length-1)button(card,'下移',b=>move(1,b));
          if(m.pausedReason)button(card,'恢复执行',b=>send(threadId,'queue-resume',{...base,messageId:m.id},b));
          button(card,'删除',b=>{if(confirm('删除这条尚未执行的排队任务？'))send(threadId,'queue-delete',{...base,messageId:m.id},b);});
        });
        if(q.messages.length)button(queue,'清空排队消息',b=>{if(confirm('清空此会话全部排队任务？'))send(threadId,'clear-queue',{...base,confirmed:true},b);});
      }
    }
    if(!active&&!idle)root.append(el('small','当前状态不支持会话操作；待处理请求可在下方回应。'));
    const unsupported=(history.pendingRequests||[]).length-c.requests.length;
    requests.hidden=!c.requests.length&&!unsupported;
    if(unsupported>0)requests.append(el('p',`另有 ${unsupported} 项请求尚未适配，请在 Codex App 处理。`));
    for(const r of c.requests){
      const card=el('section');card.className='request-card';card.dataset.action=r.action;card.append(el('h3',labels[r.action]));
      const detail=el('details');detail.append(el('summary','查看请求内容'));const pre=el('pre',JSON.stringify(r.params,null,2));detail.append(pre);card.append(detail);
      const base={nativeRequestId:r.id,requestFingerprint:r.fingerprint};
      const respond=(fields,b)=>send(threadId,r.action,{...base,...fields},b);
      if(['command-approval','file-approval'].includes(r.action)){
        for(const decision of r.decisions||[]){
          const label=typeof decision==='string'?({accept:'仅本次允许',acceptForSession:'在此会话中允许',decline:'拒绝',cancel:'取消并中断'}[decision]||decision):
            decision.acceptWithExecpolicyAmendment?'允许并保存命令规则':
            decision.applyNetworkPolicyAmendment?`${decision.applyNetworkPolicyAmendment.network_policy_amendment.action==='allow'?'允许':'拒绝'}并保存网络规则`:'应用审批选项';
          button(card,label,b=>{if(['decline','cancel'].includes(decision)||confirm(label+'？请确认已查看请求及授权范围。'))respond({decision},b);});
        }
      }else if(r.action==='permissions-approval'){
        const scopeLabel=el('label','授权有效期'), scope=el('select');scope.append(new Option('仅本轮','turn'),new Option('整个会话','session'));scopeLabel.append(scope);card.append(scopeLabel);
        const response=field(card,'授予权限 JSON',JSON.stringify(r.params.permissions||{},null,2),true);
        const reviewLabel=el('label','继续逐条审查本轮命令'), review=el('input');review.type='checkbox';reviewLabel.append(review);card.append(reviewLabel);
        button(card,'授予所选权限',b=>{try{const permissions=JSON.parse(response.value);if(confirm('确认授予填写的权限，期限为'+(scope.value==='session'?'整个会话':'本轮')+'？'))respond({response:{permissions,scope:scope.value,strictAutoReview:review.checked}},b);}catch(e){notice('权限 JSON 格式错误：'+e.message);}});
        button(card,'拒绝',b=>respond({decision:'decline'},b));
      }else if(r.action==='user-input'){
        const inputs=(r.params.questions||[]).map(q=>{
          const n=field(card,q.question||q.header||q.id,'',!q.isSecret);
          if(q.isSecret){n.type='password';n.setAttribute('autocomplete','off');}
          if(q.options?.length){const choices=el('div');for(const o of q.options){const choice=button(choices,o.label,()=>{n.value=o.label;});if(o.description)choice.append(el('small',o.description));}card.append(choices);}
          return [q.id,n];
        });
        button(card,'提交回答',async b=>{if(inputs.some(([,n])=>!n.value.trim())){notice('请回答全部问题');return;}if(await respond({answers:Object.fromEntries(inputs.map(([id,n])=>[id,[n.value]]))},b))box('question-dialog').close();});
      }else{
        const input=field(card,'回应内容（JSON 对象；无内容时留空）','',true);
        button(card,'允许并提交',b=>{try{const content=input.value.trim()?JSON.parse(input.value):null;if(confirm('确认已查看请求并提交此回应？'))respond({response:{action:'accept',content}},b);}catch(e){notice('JSON 格式错误：'+e.message);}});
        button(card,'拒绝',b=>respond({response:{action:'decline'}},b));
        button(card,'取消',b=>respond({response:{action:'cancel'}},b));
      }
      for(const n of card.querySelectorAll('[data-draft-key]'))n.dataset.draftKey='request:'+r.id+':'+r.fingerprint+':'+n.dataset.draftKey;
      if(r.action==='user-input'&&!mobileLayout.matches){
        const key=threadId+':'+r.id+':'+r.fingerprint;
        box('question-content').append(card);
        const open=()=>{if(!box('question-dialog').open)box('question-dialog').showModal();};
        button(requests,'回答 Codex 的问题',open);
        if(dialogWasOpen||!seenQuestions.has(key)){seenQuestions.add(key);open();}
      }else requests.append(card);
    }
    for(const d of root.querySelectorAll('details'))if(opened.has(d.querySelector('summary')?.textContent))d.open=true;
    const fields=[...root.querySelectorAll('[data-draft-key]'),...requests.querySelectorAll('[data-draft-key]'),...box('question-content').querySelectorAll('[data-draft-key]')];
    for(const input of fields)if(allDrafts.has(input.dataset.draftKey))input.value=allDrafts.get(input.dataset.draftKey);
    for(const child of root.children){
      const label=child.tagName==='DETAILS'?child.querySelector('summary')?.textContent:child.textContent;
      if(['停止任务','补充指令'].includes(label))child.classList.add('mobile-redundant-operation');
    }
    if(!canWrite)for(const container of [root,requests,box('question-content')])for(const control of container.querySelectorAll('button,input,select,textarea'))control.disabled=true;
    window.MobileUI?.decorate(root);
    if(draft){
      const input=[...root.querySelectorAll('[data-draft-key]'),...requests.querySelectorAll('[data-draft-key]')].find(n=>n.dataset.draftKey===draft.key);
      if(input){input.value=draft.value;input.focus();if(input.setSelectionRange&&draft.start!==null)input.setSelectionRange(draft.start,draft.end);}
    }
  }
  return {render,reset,labels};
})();
