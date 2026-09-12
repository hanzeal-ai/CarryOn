/* Account login and owner-confirmed QR invitations. No secrets leave this origin. */
function setupConsoleLogin(client,onLogin) {
  const el=id=>document.getElementById(id);
  const button=(title,action)=>{const b=document.createElement('button');b.type='button';b.textContent=title;b.className='quiet';b.onclick=action;return b;};
  const label=document.createElement('label');label.htmlFor='login-username';label.textContent='账号';
  const username=document.createElement('input');username.id='login-username';username.name='username';username.autocomplete='username';username.required=true;username.placeholder='输入账号';username.autocapitalize='none';
  el('token').before(label,username);el('token').before(document.querySelector('label[for=token]'));
  const dialog=document.createElement('dialog');dialog.className='login-qr-dialog';
  const title=document.createElement('h2'),content=document.createElement('div'),actions=document.createElement('div');
  title.textContent='扫码登录';actions.className='login-qr-actions';dialog.append(title,content,actions);document.body.append(dialog);
  let generation=0, invitation=null,stream=null;
  async function stop(){generation++;stream?.getTracks().forEach(t=>t.stop());stream=null;const old=invitation;invitation=null;if(old)try{await client.consoleRequest('qr/cancel',{id:old});}catch{} }
  dialog.addEventListener('close',stop);
  const close=button('关闭',()=>dialog.close());
  function open(){stop();content.replaceChildren();actions.replaceChildren(close);if(!dialog.open)dialog.showModal();return generation;}
  const message=text=>{content.textContent=text;};
  const delay=()=>new Promise(r=>setTimeout(r,1500));
  function parse(raw){
    const url=new URL(raw),base=new URL(client.base);
    if(url.origin!==base.origin||url.pathname!==base.pathname||url.search)throw Error('二维码不属于当前云端地址');
    const match=/^#carryon-login=([A-Za-z0-9_-]{32})\.([A-Za-z0-9_-]{43})$/.exec(url.hash);
    if(!match)throw Error('不是 CarryOn 登录二维码');return {id:match[1],secret:match[2]};
  }
  async function claim(raw){
    const gen=open();let data;
    try{data=parse(raw);}catch(e){message(e.message);return;}
    message('登录 '+client.base.host+'，请继续后在已登录电脑上确认。');
    actions.prepend(button('继续登录',async function(){
      this.disabled=true;
      try{
        data.claim=crypto.randomUUID();
        const result=await client.consoleRequest('qr/claim',data);
        if(gen!==generation)return;
        message('确认码：'+result.verification+'。请在电脑上核对并允许登录。');
        const end=Date.now()+180000;
        while(gen===generation&&Date.now()<end){
          await delay();if(gen!==generation)return;
          const state=await client.consoleRequest('qr/poll',{id:data.id,claim:data.claim});
          if(gen!==generation)return;
          if(state.authenticated){dialog.close();await onLogin();return;}
          if(state.state==='rejected')throw Error('电脑已拒绝本次登录');
        }
        if(gen===generation)message('二维码已过期，请在电脑重新生成。');
      }catch(e){if(gen===generation)message(e.message);}
    }));
  }
  async function scan(){
    const gen=open();
    if(!window.BarcodeDetector){message('请用手机系统相机扫描已登录电脑上的二维码，并打开链接继续登录。');return;}
    try{
      const formats=await BarcodeDetector.getSupportedFormats();if(!formats.includes('qr_code'))throw Error('请用手机系统相机扫描二维码并打开链接。');
      stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'},audio:false});
      if(gen!==generation){stream.getTracks().forEach(t=>t.stop());stream=null;return;}
      const video=document.createElement('video');video.playsInline=true;video.muted=true;video.srcObject=stream;content.append(video);await video.play();
      const detector=new BarcodeDetector({formats:['qr_code']});
      while(gen===generation){const codes=await detector.detect(video);if(codes.length){await claim(codes[0].rawValue);return;}await new Promise(r=>setTimeout(r,250));}
    }catch(e){if(gen===generation){stream?.getTracks().forEach(t=>t.stop());stream=null;message(e.name==='NotAllowedError'?'无法使用相机，请用系统相机扫码后打开链接。':e.message);}}
  }
  const scanButton=button('扫码登录',scan);scanButton.classList.add('login-scan-button');el('pair').after(scanButton);
  const invite=button('扫码登录其他设备',async()=>{
    const gen=open();message('正在生成二维码…');
    try{
      const qr=await client.consoleRequest('qr/create',{});if(gen!==generation)return;
      invitation=qr.id;const code=qrcode(0,'M');code.addData(qr.url);code.make();
      // Only library-generated numeric SVG markup; no URL is inserted as HTML.
      content.innerHTML=code.createSvgTag({cellSize:4,margin:16,scalable:true});
      const hint=document.createElement('p');hint.textContent='用手机扫码，随后在此确认登录。二维码 3 分钟内有效。';content.append(hint);
      const end=Date.now()+180000;
      while(gen===generation&&Date.now()<end){
        await delay();if(gen!==generation)return;
        const state=await client.consoleRequest('qr/status',{id:qr.id});if(gen!==generation)return;
        if(state.state==='scanned'){
          message('手机确认码：'+state.verification+'。确认与自己手机显示一致后允许登录。');
          const decide=action=>async()=>{
            for(const b of actions.querySelectorAll('button'))b.disabled=true;
            try{await client.consoleRequest('qr/'+action,{id:qr.id,verification:state.verification});message(action==='approve'?'已允许，等待手机完成登录。':'已拒绝登录');actions.replaceChildren(close);close.disabled=false;}
            catch(e){message(e.message);actions.replaceChildren(close);close.disabled=false;}
          };
          actions.replaceChildren(button('允许登录',decide('approve')),button('拒绝',decide('reject')),close);
          // Keep the grant alive until the receiving client redeems it.
          while(gen===generation&&Date.now()<end){await delay();if(gen!==generation)return;const result=await client.consoleRequest('qr/status',{id:qr.id});if(result.state==='redeemed'||result.state==='rejected'){message(result.state==='redeemed'?'设备已登录':'已拒绝登录');return;}}
          break;
        }
      }
      if(gen===generation){message('二维码已过期，请关闭后重新生成。');actions.replaceChildren(close);close.disabled=false;}
    }catch(e){if(gen===generation)message(e.message);}
  });
  invite.id='console-login-device';el('console-logout').before(invite);
  if(location.hash.startsWith('#carryon-login=')){
    const raw=location.href;history.replaceState(null,'',location.pathname+location.search);claim(raw);
  }
}
