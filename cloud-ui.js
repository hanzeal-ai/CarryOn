/* Local-only cloud authorization controls. Device credentials never enter a URL. */
const CloudSettings = (() => {
  const box=id=>document.getElementById(id);
  let api,notice,linkTimer;
  async function refresh(){
    const s=await api('/cloud');
    const list=box('cloud-bindings');list.replaceChildren();
    box('cloud-state').textContent=s.bindings.length?'已绑定 '+s.bindings.length+' 个云端':'未绑定云端';
    for(const binding of s.bindings){
      const row=document.createElement('section'),title=document.createElement('p'),label=document.createElement('label');
      title.textContent=binding.url+' · '+(binding.connected?'已连接':'等待连接')+(binding.error?' · '+binding.error:'');
      const permission=document.createElement('input');permission.type='checkbox';permission.checked=binding.control===true;
      label.append(permission,document.createTextNode('允许此云端远程控制'));
      const save=document.createElement('button');save.type='button';save.textContent='保存权限';
      save.onclick=async()=>{save.disabled=true;try{await api('/cloud/control',{id:binding.id,control:permission.checked});await refresh();notice('权限已保存');}catch(e){notice(e.message);}finally{save.disabled=false;}};
      const remove=document.createElement('button');remove.type='button';remove.textContent='解除绑定';
      remove.onclick=async()=>{remove.disabled=true;try{await api('/cloud',{id:binding.id,enabled:false});await refresh();box('cloud-link-status').textContent='';notice('已解除此云端绑定');}catch(e){notice(e.message);}finally{remove.disabled=false;}};
      row.append(title,label,save,remove);list.append(row);
    }
  }
  function init(transport,notify){
    api=transport;notice=notify;
    refresh().catch(()=>{box('cloud-state').textContent='请先完成本机配对';});
    box('cloud-link-form').onsubmit=async event=>{
      event.preventDefault();clearTimeout(linkTimer);box('cloud-link-start').disabled=true;
      try{
        const link=await api('/cloud/link/start',{url:box('cloud-link-url').value.trim(),control:box('cloud-link-control').checked});
        box('cloud-link-status').textContent='确认码：'+link.verification+' · 等待云端管理员确认连接（5 分钟内有效）';
        box('cloud-link-open').href=link.url;box('cloud-link-open').hidden=false;
        const poll=async()=>{
          try{const result=await api('/cloud/link/poll',{id:link.id});
            if(result.pending){linkTimer=setTimeout(poll,2000);return;}
            box('cloud-link-open').hidden=true;box('cloud-link-status').textContent=result.bridgeEnabled?'连接完成，桥接已开启':'绑定已保存，请打开 Codex 并开启桥接';await refresh();
          }catch(e){box('cloud-link-status').textContent=e.message;}
        };
        linkTimer=setTimeout(poll,2000);
      }catch(e){notice(e.message);}finally{box('cloud-link-start').disabled=false;}
    };
    box('cloud-pair-form').onsubmit=async event=>{
      event.preventDefault();box('cloud-pair-submit').disabled=true;
      try{await api('/cloud/pair',{url:box('cloud-console-url').value.trim(),code:box('cloud-pair-code').value.trim(),control:box('cloud-pair-control').checked});
        box('cloud-pair-code').value='';await refresh();notice('配对完成，桥接已开启');
      }catch(e){notice(e.message);}finally{box('cloud-pair-submit').disabled=false;}
    };
    box('cloud-refresh').onclick=()=>refresh().catch(e=>notice(e.message));
    box('cloud-form').onsubmit=async event=>{
      event.preventDefault();box('cloud-connect').disabled=true;
      try{
        await api('/cloud',{enabled:true,url:box('cloud-url').value.trim(),deviceId:box('cloud-device').value.trim(),
          token:box('cloud-token').value.trim(),control:box('cloud-control').checked});
        box('cloud-token').value='';await refresh();notice('云端配置已保存；请在本机开启桥接后使用云端控制台。');
      }catch(e){notice(e.message);}finally{box('cloud-connect').disabled=false;}
    };
    box('service-stop').onclick=async()=>{
      if(!confirm('停止 ConnectNow 本地服务？已被 Codex 接收的任务会继续执行。'))return;
      try{await api('/service/stop',{});client.close();applyStatus({enabled:false,controllerId:null});notice('本地服务已停止，可以关闭此页面。');}catch(e){notice(e.message);}
    };
  }
  return {init,refresh};
})();
