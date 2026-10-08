'use strict';
const CreationSettings = {
  render(host, {settings, fields, editable, change}) {
    host.replaceChildren();
    function select(label, key, values, value) {
      const row=document.createElement('label');row.textContent=label;
      const input=document.createElement('select');input.setAttribute('aria-label',label);
      for(const [id,title] of values)input.append(new Option(title,id));
      input.value=value;input.disabled=!editable();input.onchange=()=>{if(editable())change(key,input.value);};row.append(input);host.append(row);
    }
    if(fields.includes('collaborationMode'))select('工作模式','collaborationMode',[['','项目默认'],['default','执行'],['plan','计划']],settings()?.collaborationMode?.mode||'');
    if(fields.includes('approvalPolicy')){
      const value=settings()?.approvalPolicy, options=[['','项目默认'],['on-request','按需请求'],['untrusted','不可信命令请求'],['never','不请求']];
      if(value&&typeof value!=='string')options.push(['custom','自定义策略']);
      select('执行审批','approvalPolicy',options,typeof value==='string'?value:value?'custom':'');
    }
    const status=document.createElement('small');status.setAttribute('role','status');
    status.textContent=!editable()?'当前无法修改配置':!settings()?.model?'指定工作模式前，请先选择模型。':'';host.append(status);
  }
};
