/* Local-only cloud authorization controls. Device credentials never enter a URL. */
const CloudSettings = (() => {
  const box=id=>document.getElementById(id);
  let api,notice,linkTimer;
  async function refresh(){
    const s=await api('/cloud');
    box('cloud-permission').hidden=!s.enabled;box('cloud-current-control').checked=s.control===true;
    box('cloud-state').textContent=!s.enabled?'未绑定云端':(s.connected?'已连接':'等待连接')+' · '+s.deviceId+' · '+(s.control?'允许远程控制':'只读')+(s.error?' · '+s.error:'');
  }
  function init(transport,notify){
    api=transport;notice=notify;
    refresh().catch(()=>{box('cloud-state').textContent='请先完成本机配对';});
    box('cloud-save-control').onclick=async()=>{
      box('cloud-save-control').disabled=true;
      try{await api('/cloud/control',{control:box('cloud-current-control').checked});await refresh();notice('远程控制权限已更新');}
      catch(e){notice(e.message);}finally{box('cloud-save-control').disabled=false;}
    };
    box('cloud-link-form').onsubmit=async event=>{
      event.preventDefault();clearTimeout(linkTimer);box('cloud-link-start').disabled=true;
      const popup=window.open('about:blank','_blank');if(popup)popup.opener=null;
      try{
        const link=await api('/cloud/link/start',{url:box('cloud-link-url').value.trim(),control:box('cloud-link-control').checked});
        box('cloud-link-status').textContent='确认码：'+link.verification+' · 请打开云端确认连接（5 分钟内有效）';
        box('cloud-link-open').href=link.url;box('cloud-link-open').hidden=false;
        if(popup)popup.location.href=link.url;
        const poll=async()=>{
          try{const result=await api('/cloud/link/poll',{id:link.id});
            if(result.pending){linkTimer=setTimeout(poll,2000);return;}
            box('cloud-link-open').hidden=true;box('cloud-link-status').textContent='连接完成，桥接已开启';await refresh();
          }catch(e){box('cloud-link-status').textContent=e.message;}
        };
        linkTimer=setTimeout(poll,2000);
      }catch(e){if(popup)popup.close();notice(e.message);}finally{box('cloud-link-start').disabled=false;}
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
    box('cloud-disconnect').onclick=async()=>{
      try{await api('/cloud',{enabled:false});await refresh();notice('已断开云端并清除设备凭证。');}catch(e){notice(e.message);}
    };
    box('service-stop').onclick=async()=>{
      if(!confirm('停止 ConnectNow 本地服务？已被 Codex 接收的任务会继续执行。'))return;
      try{await api('/service/stop',{});client.close();applyStatus({enabled:false,controllerId:null});notice('本地服务已停止，可以关闭此页面。');}catch(e){notice(e.message);}
    };
  }
  return {init,refresh};
})();
