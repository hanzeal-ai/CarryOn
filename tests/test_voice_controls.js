'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function fixture(){
 const nodes=[],requests=[],operations=[],acks=[];let reads=0,resubs=0,current=true;
 function element(tag){const n={tag,textContent:'',append(){},className:'',addEventListener(){},showModal(){},close(){},remove(){},setAttribute(){}};nodes.push(n);return n;}
 const button=element('button'),track={stop(){},enabled:true};
 class Audio{constructor(){this.sampleRate=24000;this.audioWorklet={addModule:async()=>{}};this.currentTime=0;}resume(){return Promise.resolve();}close(){return Promise.resolve();}createMediaStreamSource(){return {connect(){},disconnect(){}};}}
 class Worklet{constructor(){this.port={};}connect(){}disconnect(){}}
 const context=vm.createContext({document:{getElementById:()=>button,createElement:element,body:{append(){}},addEventListener(){}},navigator:{mediaDevices:{getUserMedia:async()=>({getTracks:()=>[track],getAudioTracks:()=>[track]})}},AudioContext:Audio,AudioWorkletNode:Worklet,Uint8Array,DataView,Date,atob,btoa});
 vm.runInContext(fs.readFileSync('voice-controls.js','utf8')+';globalThis.voice=VoiceControls;',context);
 const config={supported:()=>true,allowed:()=>true,target:()=>({thread:'thread'}),current:()=>current,resubscribe:()=>resubs++,api:async(path)=>{requests.push(path);reads++;return {voice:{state:'closed'}};},client:{operation:async(thread,action)=>{operations.push(action);return {state:'completed',result:{voiceId:'voice'}};},ackVoice:(id,after)=>acks.push([id,after])}};
 context.voice.configure(config);
 return {voice:context.voice,open:()=>button.onclick(),nodes,requests,operations,acks,get resubs(){return resubs;},switch:()=>current=false};
}
function packet(sequence,events=[],state='active'){return {voice:{voice:{id:'voice',state},events,sequence,dropped:false}};}
test('voice WS deduplicates replay, restores cursor, and never polls or restarts on reconnect',async()=>{
 const f=fixture();await f.open();assert.deepEqual(f.operations,['voice-start']);assert.equal(f.requests.length,1);
 const event={sequence:1,type:'transcript/delta',delta:'hello'};
 f.voice.receive(packet(1,[event]));f.voice.receive(packet(1,[event]));
 assert.equal(f.nodes.find(n=>n.className==='voice-transcript').textContent,'hello');
 f.voice.disconnected();assert.equal(f.voice.selection().voiceAfter,1);
 f.voice.receive(packet(2,[event,{sequence:2,type:'transcript/delta',delta:' world'}]));
 assert.equal(f.nodes.find(n=>n.className==='voice-transcript').textContent,'hello world');
 assert.deepEqual(f.acks.at(-1),['voice',2]);assert.equal(f.requests.length,1);assert.deepEqual(f.operations,['voice-start']);
 f.voice.receive(packet(2,[],'closed'));assert.equal(f.voice.selection().voiceId,undefined);
});
test('selection change and voice identity error release subscription without starting another session',async()=>{
 const f=fixture();await f.open();f.voice.receive({voiceError:'changed'});assert.equal(f.voice.selection().voiceId,undefined);assert.equal(f.operations.length,1);
 const g=fixture();await g.open();g.switch();assert.equal(g.voice.selection().voiceId,undefined);assert.equal(g.operations.length,1);
});
