/* Local-only cloud authorization controls. Device credentials never enter a URL. */
const CloudSettings = (() => {
  const box=id=>document.getElementById(id);
  let api,notice;
  async function refresh(){
    const s=await api('/cloud');
    box('cloud-state').textContent=!s.enabled?'未绑定云端':(s.connected?'已连接':'等待连接')+' · '+s.deviceId+' · '+(s.control?'允许远程控制':'只读')+(s.error?' · '+s.error:'');
  }
  function init(transport,notify){
    api=transport;notice=notify;
    refresh().catch(()=>{box('cloud-state').textContent='请先完成本机配对';});
    box('cloud-pair-form').onsubmit=async event=>{
      event.preventDefault();box('cloud-pair-submit').disabled=true;
      try{await api('/cloud/pair',{url:box('cloud-console-url').value.trim(),code:box('cloud-pair-code').value.trim(),control:box('cloud-pair-control').checked});
        box('cloud-pair-code').value='';await refresh();notice('配对完成；请在本机开启桥接。');
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
