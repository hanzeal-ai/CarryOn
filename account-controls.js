'use strict';
window.AccountControls=(()=>{
 const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
 const dialog=el('dialog'),nav=el('nav'),body=el('section'),head=el('header'),title=el('h2','设置'),close=el('button','关闭');
 dialog.id='account-settings';dialog.setAttribute('aria-label','设置');nav.setAttribute('aria-label','设置分类');head.append(title,close);dialog.append(head,nav,body);document.body.append(dialog);
 let config,version=0,busy=false,active='用量',entries=[],scope;
 const button=(label,fn)=>{const b=el('button',label);b.type='button';b.onclick=fn;return b;};
 const context=()=>JSON.stringify([config.scope(),config.client.epoch,config.allowed('resetQuota')]);
 const current=(v,s)=>dialog.open&&v===version&&s===context();
 close.onclick=()=>{if(!busy)dialog.close();};dialog.addEventListener('cancel',e=>{if(busy)e.preventDefault();});
 dialog.addEventListener('close',()=>{version++;body.replaceChildren();config?.trigger()?.focus();});
 const status=text=>{const p=el('p',text);p.setAttribute('role','status');body.append(p);return p;};
 function setBusy(value){busy=value;close.disabled=value;for(const b of nav.querySelectorAll('button'))b.disabled=value;}
 async function usage(){
  const v=version,s=context();const loading=status('正在读取用量…');
  try{
   const data=await config.client.request('/usage');if(!current(v,s))return;loading.remove();
   if(!Array.isArray(data.limits))throw Error('用量数据格式不正确');
   if(!data.limits.length)status('暂无可用额度数据');
   for(const limit of data.limits){body.append(el('h3',limit.name||limit.id));for(const window of limit.windows||[]){
    const row=el('div');row.className='usage-window';const mins=window.windowDurationMins;
    row.append(el('strong',Number.isFinite(mins)?(mins>=1440?mins/1440+' 天':mins/60+' 小时'):'额度窗口'));
    const known=typeof window.usedPercent==='number'&&Number.isFinite(window.usedPercent),remaining=known?Math.max(0,Math.min(100,100-window.usedPercent)):null;
    row.append(el('p',known?'剩余 '+Math.round(remaining)+'%':'用量未知'));
    if(known){const meter=el('progress');meter.max=100;meter.value=remaining;meter.setAttribute('aria-label','剩余额度');row.append(meter);}
    if(typeof window.resetsAt==='number')row.append(el('small',new Date(window.resetsAt*1000).toLocaleString()+' 重置'));body.append(row);
   }}
   const credits=data.rateLimitResetCredits;body.append(el('h3','额度重置卡'),el('p',Number.isInteger(credits?.availableCount)?'可用 '+credits.availableCount+' 张':'可用数量未知'));
   for(const credit of credits?.credits||[])body.append(el('p',[credit.title||credit.id,{available:'可用',redeeming:'处理中',redeemed:'已使用'}[credit.status]||'状态未知',credit.expiresAt?new Date(credit.expiresAt*1000).toLocaleString()+' 到期':''].filter(Boolean).join(' · ')));
   const pending=config.client.operations.has('quota:'+data.accountKey);
   const reset=button(pending?'核对并重试重置':'使用 1 张重置卡',async()=>{
    if(!current(v,s)||!config.allowed('resetQuota'))return;
    if(!confirm('使用 1 张额度重置卡？确认后会消耗卡片；结果未知时将沿用原请求核对并重试。'))return;
    if(!current(v,s)||!config.allowed('resetQuota'))return;
    reset.disabled=true;setBusy(true);const message=status('正在核对重置结果…');
    try{const job=await config.client.resetQuota(data.accountKey,()=>current(v,s)&&config.allowed('resetQuota'));if(!current(v,s))return;
     message.textContent=job.state==='completed'?({reset:'额度已重置',alreadyRedeemed:'此请求已完成，未重复消耗',nothingToReset:'没有可重置的额度，未消耗卡片',noCredit:'没有可用重置卡'}[job.result.outcome]):job.error||'结果尚未确认，请沿用原请求核对';
    }catch(error){if(current(v,s))message.textContent=error.message;}finally{if(current(v,s)){setBusy(false);reset.disabled=true;message.textContent+='；请刷新用量后再操作。';}}
   });
   reset.disabled=!config.allowed('resetQuota')||!data.accountKey||(!pending&&!(credits?.availableCount>0));body.append(reset);
   if(!config.allowed('resetQuota'))body.append(el('p','当前工作区未授权使用重置卡。'));
   body.append(button('刷新用量',()=>show('用量')));
  }catch(error){if(current(v,s)){loading.textContent=error.message;body.append(button('重试',()=>show('用量')));}}
 }
 function password(){
  const form=el('form'),fields=[];for(const [label,autocomplete]of [['当前密码','current-password'],['新密码（至少 12 位）','new-password'],['再次输入新密码','new-password']]){
   const wrap=el('label',label),input=el('input');input.type='password';input.autocomplete=autocomplete;input.required=true;input.setAttribute('aria-label',label);wrap.append(input);form.append(wrap);fields.push(input);
  }
  const [old,next,repeat]=fields;next.minLength=12;const message=el('p');message.setAttribute('role','alert');const save=button('保存并重新登录',()=>{});save.type='submit';save.disabled=true;
  const update=()=>{save.disabled=busy||!old.value||[...next.value].length<12||next.value!==repeat.value;};form.addEventListener('input',update);
  form.onsubmit=async event=>{event.preventDefault();update();if(save.disabled)return;const v=version,s=context();setBusy(true);for(const f of fields)f.disabled=true;save.disabled=true;message.textContent='';
   try{const result=await config.client.consoleRequest('password',{currentPassword:old.value,password:next.value});if(!current(v,s))return;if(result.changed!==true)throw Error('密码变更尚未确认，请重新登录核对');for(const f of fields)f.value='';config.signedOut();}
   catch(error){if(current(v,s))message.textContent=error.message;}finally{if(current(v,s)){setBusy(false);for(const f of fields)f.disabled=false;update();}}
  };form.append(el('p','保存后所有已登录设备需要重新登录。'),message,save);body.append(form);
 }
 function show(name){
  if(busy)return;active=name;version++;body.replaceChildren(el('h2',name));for(const b of nav.children)b.setAttribute('aria-current',b.textContent===name?'page':'false');
  if(name==='用量')usage();
  if(name==='账户')password();
  if(name==='偏好设置'){
   const row=el('label','显示不活跃会话'),input=el('input');input.type='checkbox';input.checked=document.getElementById('show-inactive').checked;input.onchange=()=>{const source=document.getElementById('show-inactive');source.checked=input.checked;source.dispatchEvent(new Event('change'));};row.append(input);body.append(row,button('消息通知',()=>{dialog.close();document.getElementById('notification-settings').click();}));
  }
  if(name==='运行日志'){
   if(!entries.length)status('本次页面会话暂无运行提示。');
   for(const entry of entries){const row=el('article');row.append(el('small',entry.date),el('p',entry.message));body.append(row);}
  }
  if(name==='关于')body.append(el('h3','CarryOn Web'),el('p','网页资源随当前工作区服务更新。'),el('p','运行日志仅保留当前页面会话的最近 200 条提示，刷新页面后清除。'));
 }
 return {
  configure(value){config=value;scope=context();for(const name of ['用量',...(config.cloud?['账户']:[]),'偏好设置','运行日志','关于'])nav.append(button(name,()=>show(name)));},
  open(){scope=context();document.getElementById('account-menu')?.removeAttribute('open');if(!dialog.open)dialog.showModal();show(active);},
  update(){if(!config)return;const next=context();if(scope!==next){if(dialog.open)dialog.close();setBusy(false);entries=[];scope=next;}},
  record(message){if(!config)return;const clean=String(message).replace(/((?:bearer)\s+)[^\s,;]+/gi,'$1[已隐藏]').replace(/((?:token|password|cookie|authorization)["']?\s*[=:]\s*["']?)[^\s,;"']+/gi,'$1[已隐藏]');entries.unshift({date:new Date().toLocaleString(),message:clean.slice(0,2048)});entries=entries.slice(0,200);}
 };
})();
