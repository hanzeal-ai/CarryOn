/* Isolated browser audio lifecycle: no real microphone, account or native session. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');const path=require('node:path');
(async()=>{const browser=await chromium.launch();try{
 const worklet=await browser.newPage();
 await worklet.evaluate(()=>{window.framesSent=[];window.AudioWorkletProcessor=class{constructor(){this.port={postMessage:buffer=>framesSent.push([...new Int16Array(buffer)])};}};window.registerProcessor=(name,processor)=>window.Processor=processor;});
 await worklet.addScriptTag({path:path.resolve(__dirname,'../voice-audio-worklet.js')});
 const pcm=await worklet.evaluate(()=>{const p=new Processor();p.process([[new Float32Array([1,-1,2,-2,0])]]);const before=framesSent.length;p.process([[new Float32Array(2395)]]);return {before,count:framesSent.length,length:framesSent[0].length,start:framesSent[0].slice(0,5)};});
 assert.deepEqual(pcm,{before:0,count:1,length:2400,start:[32767,-32768,32767,-32768,0]});await worklet.close();
 for(const scenario of ['normal','scope','cancel-unknown']){
  const page=await browser.newPage();await page.setContent('<button id="voice-open">Voice</button>');
  await page.evaluate(scenario=>{
   window.fixture={scenario,current:true,native:'closed',writes:[],tracksStopped:0,contextsClosed:0,played:0,startPending:null,eventsSent:false};const f=window.fixture;
   Object.defineProperty(navigator,'mediaDevices',{value:{getUserMedia:async()=>({getTracks:()=>[{stop:()=>f.tracksStopped++}],getAudioTracks:()=>[]})},configurable:true});
   window.AudioContext=class{constructor(){this.sampleRate=24000;this.currentTime=0;this.destination={};this.audioWorklet={addModule:async()=>{}};}async resume(){}async close(){f.contextsClosed++;}createMediaStreamSource(){return{connect(){},disconnect(){}};}createBuffer(ch,len,rate){return{duration:len/rate,getChannelData:()=>new Float32Array(len)}}createBufferSource(){return{connect(){},start(){f.played++},stop(){},disconnect(){}}}};
   window.AudioWorkletNode=class{constructor(){this.port={};f.capture=this;}connect(){}disconnect(){f.captureDisconnected=true;}};
  },scenario);
  await page.addScriptTag({path:path.resolve(__dirname,'../voice-controls.js')});
  await page.evaluate(()=>{const f=fixture;VoiceControls.configure({supported:()=>true,allowed:()=>true,target:()=>({thread:'t',scope:'a'}),current:()=>f.current,
   client:{operation:async(thread,action,body)=>{f.writes.push({action,body});if(action==='voice-start'){if(f.scenario==='cancel-unknown')return await new Promise(resolve=>f.startPending=resolve);f.native='starting';return{state:'completed',result:{voiceId:'v'}};}f.native='closed';return{state:'completed'};}},
   api:async(url,body)=>{if(body){f.writes.push({audio:body});return{};}const events=f.native==='active'&&!f.eventsSent?(f.eventsSent=true,[{type:'transcript/delta',delta:'测试转录'},{type:'outputAudio/delta',audio:{sampleRate:24000,numChannels:1,data:'AAAAAA=='}}]):[];return{voice:{id:f.native==='closed'?null:'v',state:f.native},events,sequence:f.eventsSent?2:0};}});VoiceControls.update();});
  await page.click('#voice-open');
  if(scenario==='cancel-unknown'){
   await page.waitForFunction(()=>!!fixture.startPending);await page.getByRole('button',{name:'结束语音',exact:true}).click();
   await page.evaluate(()=>{fixture.native='active';fixture.startPending({state:'uncertain',error:'lost reply'});});
   await page.waitForTimeout(350);
   assert(await page.evaluate(()=>fixture.writes.some(w=>w.action==='voice-stop')),'Cancelled uncertain start must stop recovered native session');
  }else{
   await page.waitForFunction(()=>fixture.writes.some(w=>w.action==='voice-start'));
   assert.equal(await page.evaluate(()=>!!fixture.capture),false,'RPC completion must not start microphone capture before native active');
   await page.evaluate(()=>fixture.native='active');await page.waitForFunction(()=>!!fixture.capture);
   await page.evaluate(()=>fixture.capture.port.onmessage({data:new Int16Array([0,32767,-32768]).buffer}));await page.waitForFunction(()=>fixture.writes.some(w=>w.audio));
   const data=await page.evaluate(()=>fixture.writes.find(w=>w.audio).audio);assert.equal(data.voiceId,'v');assert.equal(data.sequence,1);assert.equal(data.audio.sampleRate,24000);assert.equal(data.audio.samplesPerChannel,3);
   assert.equal(await page.locator('.voice-transcript').textContent(),'测试转录');assert.equal(await page.evaluate(()=>fixture.played),1);
   if(scenario==='scope'){await page.evaluate(()=>fixture.current=false);await page.waitForTimeout(350);}else await page.getByRole('button',{name:'结束语音',exact:true}).click();
   assert(await page.evaluate(()=>fixture.tracksStopped>0&&fixture.contextsClosed>0&&fixture.captureDisconnected),'Media resources must be released');
  }
  await page.close();
 }
 console.log('PASS voice controls: native state, PCM, transcript/playback, stop, cancelled unknown start, scope cleanup');
}finally{await browser.close();}})().catch(error=>{console.error(error);process.exitCode=1});
