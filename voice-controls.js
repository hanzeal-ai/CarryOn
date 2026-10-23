/* One explicitly opened native voice session; microphone buffers never persist. */
const VoiceControls=(()=>{
  let config,dialog,session=null;
  const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
  const labels={starting:'正在连接…',active:'正在聆听',stopping:'正在结束…',closed:'语音已结束',unknown:'状态待核对'};
  function configure(value){config=value;document.getElementById('voice-open').onclick=open;}
  function update(){if(session?.watching&&!config.current(session.target)){cleanup(session);session.watching=false;}const b=document.getElementById('voice-open');if(!b||!config)return;b.hidden=!config.supported();b.disabled=!config.allowed('send');}
  function cleanup(s){s.capture?.disconnect();s.source?.disconnect();s.stream?.getTracks().forEach(t=>t.stop());s.audio?.close().catch(()=>{});s.queue=[];s.sources.forEach(n=>{try{n.stop();}catch{}});s.sources.clear();s.closed=true;}
  function show(s,text){if(session===s)s.status.textContent=text;}
  async function stop(s){
    if(s.stopping)return;s.stopping=true;s.stopAt=Date.now();cleanup(s);
    if(s.id&&config.current(s.target)&&config.allowed('stop')){
      try{const result=await config.client.operation(s.target.thread,'voice-stop',{voiceId:s.id},()=>config.current(s.target));if(['failed','uncertain'].includes(result.state))throw Error(result.error||'结束结果待核对');show(s,'结束请求已提交，等待原生关闭');s.watching=true;config.resubscribe();}catch(e){s.stopping=false;show(s,e.message);}
    }else{s.stopping=false;}
  }
  function play(s,audio){
    if(audio?.sampleRate!==24000||audio.numChannels!==1||typeof audio.data!=='string')throw Error('收到不支持的音频格式');
    const binary=atob(audio.data);if(binary.length%2||binary.length>480000)throw Error('音频帧过大或格式无效');
    const data=new DataView(Uint8Array.from(binary,c=>c.charCodeAt(0)).buffer),buffer=s.audio.createBuffer(1,binary.length/2,24000),output=buffer.getChannelData(0);
    for(let i=0;i<output.length;i++)output[i]=data.getInt16(i*2,true)/32768;
    const source=s.audio.createBufferSource();source.buffer=buffer;source.connect(s.audio.destination);s.sources.add(source);source.onended=()=>s.sources.delete(source);
    if(s.playAt>s.audio.currentTime+5)throw Error('音频播放积压，请结束后重试');
    s.playAt=Math.max(s.playAt,s.audio.currentTime);source.start(s.playAt);s.playAt+=buffer.duration;
  }
  async function drain(s){
    if(s.sending||s.closed||!s.connected)return;s.sending=true;
    try{while(s.queue.length&&!s.closed&&s.connected){
      if(!config.current(s.target)||!config.allowed('send'))throw Error('会话或发送权限已改变');
      const bytes=new Uint8Array(s.queue.shift());let binary='';for(const byte of bytes)binary+=String.fromCharCode(byte);
      await config.api('/threads/'+s.target.thread+'/voice/audio',{voiceId:s.id,sequence:++s.inputSequence,audio:{data:btoa(binary),sampleRate:24000,numChannels:1,samplesPerChannel:bytes.length/2}});
    }}catch(e){show(s,e.message);await stop(s);}finally{s.sending=false;}
  }
  function selection(){
    const s=session;
    if(!s?.id||!s.watching)return {};
    if(!config.current(s.target)){cleanup(s);s.watching=false;show(s,'工作区或会话已改变，音频已停止');return {};}
    return {voiceId:s.id,voiceAfter:s.sequence};
  }
  function disconnected(){
    const s=session;if(!s?.watching)return;
    s.connected=false;s.queue=[];
    for(const n of s.sources){try{n.stop();}catch{}}s.sources.clear();s.playAt=0;
    show(s,'连接已断开，正在恢复语音状态…');
  }
  function receive(packet){
    const s=session;if(!s?.watching||!config.current(s.target))return;
    if(packet.voiceError){cleanup(s);s.watching=false;show(s,packet.voiceError);config.resubscribe();return;}
    const result=packet.voice;if(!result)return;
    try{
      const voice=result.voice;if(voice.id!==s.id)throw Error('语音会话已改变');
      if(!config.allowed('send')&&!s.closed)throw Error('语音权限已改变');
      s.connected=true;show(s,voice.error||labels[voice.state]||voice.state);s.state=voice.state;
      if(result.dropped){for(const n of s.sources){try{n.stop();}catch{}}s.sources.clear();s.playAt=0;show(s,'部分音频未及时接收，已跳过');}
      for(const event of result.events||[]){
        if(event.sequence<=s.sequence)continue;
        if(event.type==='outputAudio/delta'&&!s.closed&&s.audio)play(s,event.audio);
        if(event.type==='transcript/delta')s.transcript.textContent=(s.transcript.textContent+(event.delta||'')).slice(-16000);
        if(event.type==='transcript/done')s.transcript.textContent=(s.transcript.textContent+'\n').slice(-16000);
        s.sequence=event.sequence;
      }
      s.sequence=Math.max(s.sequence,result.sequence);config.client.ackVoice(s.id,s.sequence);
      if(voice.state==='closed'){cleanup(s);s.watching=false;config.resubscribe();return;}
      if(voice.state==='active'&&!s.closed&&!s.capture){
        const source=s.audio.createMediaStreamSource(s.stream),capture=new AudioWorkletNode(s.audio,'carryon-capture');s.source=source;s.capture=capture;
        capture.port.onmessage=e=>{if(s.closed||s.muted||!s.connected)return;if(s.queue.length>=10){show(s,'音频上传积压，已停止');stop(s);return;}s.queue.push(e.data);drain(s);};
        source.connect(capture);capture.connect(s.audio.destination);
      }
    }catch(e){cleanup(s);s.watching=false;show(s,e.message);config.resubscribe();}
  }
  async function open(){
    if(session&&!session.closed){dialog.showModal();return;}
    const target=config.target();if(!target||!config.allowed('send'))return;
    dialog?.remove();dialog=el('dialog');dialog.className='voice-dialog';
    const title=el('h2','语音聊天'),status=el('p','正在准备麦克风…'),transcript=el('div'),mute=el('button','静音'),end=el('button','结束语音');
    transcript.className='voice-transcript';const controls=el('div');controls.className='voice-actions';controls.append(mute,end);dialog.append(title,status,transcript,controls);document.body.append(dialog);
    const s={target,status,transcript,id:null,sequence:0,inputSequence:0,queue:[],sources:new Set(),playAt:0,closed:false,muted:false,stopping:false,watching:false,connected:false};session=s;
    mute.onclick=()=>{s.muted=!s.muted;mute.textContent=s.muted?'取消静音':'静音';mute.setAttribute('aria-pressed',String(s.muted));s.stream?.getAudioTracks().forEach(t=>t.enabled=!s.muted);};
    end.onclick=async()=>{await stop(s);dialog.close();};dialog.addEventListener('cancel',()=>stop(s));dialog.addEventListener('close',()=>stop(s));dialog.showModal();
    try{
      const previous=await config.api('/threads/'+target.thread+'/voice?after=0');
      if(!config.current(target)||s.closed){cleanup(s);return;}
      if(['starting','active','stopping','unknown'].includes(previous.voice?.state)){
        s.id=previous.voice.id;cleanup(s);mute.disabled=true;show(s,'已有语音会话：'+(labels[previous.voice.state]||previous.voice.state)+'，可结束后重新启动');return;
      }
      s.stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
      if(s.closed||!config.current(target)){cleanup(s);return;}
      s.audio=new AudioContext({sampleRate:24000});await s.audio.resume();if(s.audio.sampleRate!==24000)throw Error('此设备暂不支持 24 kHz 音频');
      await s.audio.audioWorklet.addModule('/voice-audio-worklet.js');
      if(s.closed||!config.current(target)){cleanup(s);return;}
      const job=await config.client.operation(target.thread,'voice-start',{},()=>config.current(target)&&!s.closed);
      s.id=job.result?.voiceId;
      if(job.state!=='completed'||!s.id)throw Error(job.error||'语音启动结果待核对，请查看原请求');
      if(s.closed){s.stopping=false;await stop(s);return;}
      s.watching=true;config.resubscribe();
    }catch(e){
      cleanup(s);show(s,e.message);
      if(config.current(target))try{const current=await config.api('/threads/'+target.thread+'/voice?after=0');if(['starting','active','stopping','unknown'].includes(current.voice?.state)){s.id=current.voice.id;s.stopping=false;await stop(s);}}catch{}
    }
  }
  document.addEventListener('visibilitychange',()=>{if(document.hidden&&session&&!session.closed)stop(session);});
  return {configure,update,selection,receive,disconnected};
})();
