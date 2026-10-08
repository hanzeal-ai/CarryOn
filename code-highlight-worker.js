'use strict';
if(typeof importScripts==='function')importScripts('highlight-engine.js','unified-diff.js');
const CodeHighlightTokens=(()=>{
 const engine=typeof module!=='undefined'?require('./highlight-engine.js'):hljs;
 const limit=100_000;
 function classes(scope){
  if(!/^[a-z0-9_.:-]+$/i.test(scope))throw Error('Invalid syntax scope');
  if(scope.startsWith('language:'))return 'language-'+scope.slice(9);
  const [first,...rest]=scope.split('.');return ['hljs-'+first,...rest.map((part,index)=>part+'_'.repeat(index+1))].join(' ');
 }
 function tokenize(text,language){
  if(new TextEncoder().encode(text).length>limit||!engine.getLanguage(language))return [];
  const result=engine.highlight(text,{language,ignoreIllegals:true}),root=result._emitter.rootNode;
  const stack=[{node:root,scopes:[]}],runs=[];let count=0;
  while(stack.length){
   const {node,scopes}=stack.pop();if(++count>32_000||scopes.length>48)return [];
   if(typeof node==='string'){
    if(node)runs.push({text:node,scopes});
   }else{
    const next=node.scope?[...scopes,classes(node.scope)]:scopes;
    for(let index=node.children.length-1;index>=0;index--)stack.push({node:node.children[index],scopes:next});
   }
  }
  return runs.map(run=>run.text).join('')===text?runs:[];
 }
 function diff(text,language){
  if(new TextEncoder().encode(text).length>limit||!engine.getLanguage(language))return [];
  const parser=typeof module!=='undefined'?require('./unified-diff.js'):UnifiedDiff;
  const rows=parser.lines(text),colors=new Map();let group=[],groups=0;
  function split(runs){const result=[[]];for(const run of runs){const parts=run.text.split('\n');for(const [index,part]of parts.entries()){if(index)result.push([]);if(part)result.at(-1).push({text:part,scopes:run.scopes});}}return result;}
  function flush(){
   if(!group.length)return;
   if(++groups>128){group=[];return;}
   for(const removed of [true,false]){
    const side=group.filter(row=>removed?row.kind!=='added':row.kind!=='removed');
    if(!side.length)continue;
    const source=side.map(row=>row.text.slice(1)).join('\n'),runs=tokenize(source,language);
    if(!runs.length)continue;
    const tokens=split(runs);
    for(const [index,row]of side.entries())if((row.kind==='removed')===removed){
     const line=[{text:row.text.slice(0,1),scopes:[]},...tokens[index]];
     if(line.map(run=>run.text).join('')===row.text)colors.set(row.id,line);
    }
   }
   group=[];
  }
  for(const row of rows){if(row.kind==='header'){if(!row.text.startsWith('\\ No newline'))flush();}else group.push(row);}flush();
  const result=[];for(const [index,row]of rows.entries()){if(index)result.push({text:'\n',scopes:[]});result.push(...(colors.get(row.id)||[{text:row.text,scopes:[]}]));if(result.length>32_000)return [];}
  return result.map(run=>run.text).join('')===text?result:[];
 }
 return {tokenize,diff,limit};
})();
if(typeof module!=='undefined')module.exports=CodeHighlightTokens;
else self.onmessage=event=>{
 const {id,text,language,diff}=event.data;
 try{self.postMessage({id,runs:diff?CodeHighlightTokens.diff(text,language):CodeHighlightTokens.tokenize(text,language)});}catch{self.postMessage({id,runs:[]});}
};
