'use strict';
// Color projection only: text, copy, selection and diff identities remain owned by their views.
const CodeHighlight=(()=>{
 const workerURL=new URL('code-highlight-worker.js',document.currentScript.src);
 const limit=100_000,cache=new Map(),versions=new WeakMap();
 const extensions={swift:'swift',py:'python',js:'javascript',jsx:'javascript',ts:'typescript',tsx:'typescript',json:'json',go:'go',rs:'rust',java:'java',kt:'kotlin',kts:'kotlin',c:'c',h:'c',cpp:'cpp',cc:'cpp',hpp:'cpp',m:'objectivec',mm:'objectivec',cs:'csharp',rb:'ruby',php:'php',sh:'bash',zsh:'bash',bash:'bash',sql:'sql',html:'xml',xml:'xml',svg:'xml',vue:'xml',css:'css',scss:'scss',yaml:'yaml',yml:'yaml',toml:'ini',ini:'ini',md:'markdown',markdown:'markdown',diff:'diff',patch:'diff',dart:'dart',r:'r',lua:'lua',pl:'perl'};
 let worker=null,active=null,queue=[],sequence=0,timer=null,disabled=false;
 const plain=language=>!language||['text','plaintext','txt','log'].includes(language);
 function language(info){return String(info||'').trim().split(/\s+/)[0].toLowerCase();}
 function fileLanguage(path){const name=String(path||'').split('/').at(-1).toLowerCase();return name==='dockerfile'||name==='makefile'?name:extensions[name.split('.').at(-1)]||'plaintext';}
 function finish(runs){
  clearTimeout(timer);timer=null;const task=active;active=null;
  if(task){if(runs.length){cache.delete(task.key);cache.set(task.key,runs);while(cache.size>16)cache.delete(cache.keys().next().value);}task.resolve(runs);}
  pump();
 }
 function reset(){
  disabled=false;  worker?.terminate();worker=null;clearTimeout(timer);timer=null;active?.resolve([]);active=null;for(const task of queue)task.resolve([]);queue=[];cache.clear();
 }
 function stop(){reset();disabled=true;}
 function pump(){
  if(active||!queue.length)return;
  try{
   if(!worker){worker=new Worker(workerURL);worker.onmessage=event=>{if(event.data.id===active?.id)finish(event.data.runs);};worker.onerror=stop;}
   active=queue.pop();timer=setTimeout(stop,2000);worker.postMessage({id:active.id,text:active.text,language:active.language,diff:active.diff});
  }catch{stop();}
 }
 function highlight(text,info,diff=false){
  const lang=language(info);if(disabled||plain(lang)||new TextEncoder().encode(text).length>limit)return Promise.resolve([]);
  const key=(diff?'diff:':'code:')+lang+'\n'+text;
  if(cache.has(key)){const runs=cache.get(key);cache.delete(key);cache.set(key,runs);return Promise.resolve(runs);}
  return new Promise(resolve=>{if(queue.length>=16)queue.shift().resolve([]);queue.push({id:++sequence,key,text,language:lang,diff,resolve});pump();});
 }
 function paint(node,text,runs){
  if(!runs.length||!node.isConnected||node.textContent!==text||runs.map(run=>run.text).join('')!==text)return false;
  const selection=window.getSelection();if(selection&&(node.contains(selection.anchorNode)||node.contains(selection.focusNode)||(!selection.isCollapsed&&selection.containsNode(node,true))))return false;
  const fragment=document.createDocumentFragment();let count=0;
  for(const run of runs){let root=fragment;for(const scope of run.scopes){if(++count>4096)return false;const span=document.createElement('span');span.className=scope;root.append(span);root=span;}root.append(document.createTextNode(run.text));}
  node.replaceChildren(fragment);node.classList.add('syntax-colors');return true;
 }
 function render(node,text,info){
  const version=Symbol();versions.set(node,version);
  return highlight(text,info).then(runs=>versions.get(node)===version&&paint(node,text,runs));
 }
 function splitLines(runs){
  const lines=[[]];for(const run of runs){const parts=run.text.split('\n');for(const [index,text]of parts.entries()){if(index)lines.push([]);if(text)lines.at(-1).push({text,scopes:run.scopes});}}return lines;
 }
 return {render,highlight,highlightDiff:(text,info)=>highlight(text,info,true),paint,splitLines,fileLanguage,reset,limit};
})();
