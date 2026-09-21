/* Browser adaptation of the account-confirmed binding invite protocol. */
window.WorkspaceBinding=(()=>{
  if(!cloudMode)return {open(){},offerPending(){}};
  const dialog=node('dialog','login-qr-dialog'),title=node('h2','','绑定工作区'),content=node('div'),actions=node('div','login-qr-actions');
  dialog.append(title,content,actions);document.body.append(dialog);
  let generation=0,stream=null,pending=location.hash.startsWith('#carryon-bind=')?location.href:null;
  if(pending)history.replaceState(null,'',location.pathname+location.search);
  const button=(label,run)=>{const b=node('button','quiet',label);b.type='button';b.onclick=run;return b;};
  function stop(){generation++;stream?.getTracks().forEach(t=>t.stop());stream=null;}
  dialog.addEventListener('close',stop);
  const close=button('关闭',()=>dialog.close());
  function open(){stop();content.replaceChildren();actions.replaceChildren(close);if(!dialog.open)dialog.showModal();const input=node('input');input.type='url';input.placeholder='粘贴工作区二维码链接';input.setAttribute('aria-label','工作区二维码链接');content.append(input);actions.prepend(button('读取链接',()=>inspect(input.value)),button('扫码绑定工作区',scan));}
  function parse(raw){const url=new URL(raw),base=client.base;if(url.origin!==base.origin||url.pathname!==base.pathname||url.search||url.username||url.password)throw Error('二维码不属于当前云端，请先登录对应云端账号');const match=/^#carryon-bind=([A-Za-z0-9_-]{32})\.([A-Za-z0-9_-]{43})$/.exec(url.hash);if(!match)throw Error('不是 CarryOn 工作区二维码');return {id:match[1],secret:match[2]};}
  async function inspect(raw){
    stop();const gen=generation,epoch=client.epoch;const current=()=>gen===generation&&epoch===client.epoch&&!!client.token;
    content.replaceChildren(node('p','','正在读取工作区…'));actions.replaceChildren(close);
    try{
      const code=parse(raw),details=await client.consoleRequest('binding/inspect',code);if(!current())return;
      const labels={view:'查看会话',create:'新建会话',send:'发送消息',stop:'停止任务',edit:'编辑会话与设置',files:'查看和下载文件',approve:'处理审批'};
      content.replaceChildren(node('h3','',details.name),node('p','','当前账号：'+(details.account?.username||'')),node('p','',(details.permissions||[]).map(p=>labels[p]||p).join('、')));
      const accept=button('确认绑定',async()=>{
        if(!current())return;
        accept.disabled=true;
        try{let result=await client.consoleRequest('binding/accept',code);if(!current())return;
          while(result.state==='accepted'){
            accept.textContent='等待电脑确认';await new Promise(resolve=>setTimeout(resolve,1500));if(!current())return;
            result=await client.consoleRequest('binding/inspect',code);if(!current())return;
          }
          if(result.state!=='bound')throw Error('绑定尚未完成，请重新读取状态');
          dialog.close();notice('工作区已绑定');await refreshConsoleDevices();
        }catch(e){if(current()){content.append(node('p','error',e.message));accept.disabled=false;accept.textContent='确认绑定';}}
      });actions.prepend(accept);
    }catch(e){if(current()){content.replaceChildren(node('p','error',e.message));actions.prepend(button('重新读取',open));}}
  }
  async function scan(){
    stop();const gen=generation;content.replaceChildren();
    try{
      if(!window.BarcodeDetector||(await BarcodeDetector.getSupportedFormats()).includes('qr_code')===false)throw Error('当前浏览器不支持扫码，请用系统相机打开二维码链接，或粘贴链接。');
      const camera=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'},audio:false});
      if(gen!==generation){camera.getTracks().forEach(t=>t.stop());return;}stream=camera;
      const video=node('video');video.playsInline=true;video.muted=true;video.srcObject=stream;content.append(video);await video.play();
      const detector=new BarcodeDetector({formats:['qr_code']});
      while(gen===generation){const codes=await detector.detect(video);if(gen!==generation)return;if(codes.length){await inspect(codes[0].rawValue);return;}await new Promise(resolve=>setTimeout(resolve,250));}
    }catch(e){if(gen===generation){stop();content.replaceChildren(node('p','error',e.name==='NotAllowedError'?'无法使用相机，请用系统相机打开二维码链接，或粘贴链接。':e.message));actions.replaceChildren(button('粘贴链接',open),close);}}
  }
  $('console-requests').before(button('扫码或粘贴链接绑定',open));
  function offerPending(){if(pending&&client.token){const raw=pending;pending=null;open();inspect(raw);}}
  return {open,offerPending};
})();
