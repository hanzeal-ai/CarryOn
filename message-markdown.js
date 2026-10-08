/* Message formatting uses DOM nodes only. Model text never becomes HTML. */
const MessageMarkdown=(()=>{
 const element=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
 function link(value){try{const url=new URL(value,location.href);return ['https:','http:','mailto:'].includes(url.protocol)?url.href:null;}catch{return null;}}
 function inline(text,depth=0){
  const result=document.createDocumentFragment();
  if(depth>8){result.append(document.createTextNode(text));return result;}
  const positions=new Map(),codeRuns=new Map(),parentheses=new Map(),destinations=new Map(),stack=[];
  for(let index=0;index<text.length;index++){
   if(text[index]==='`'){let end=index+1;while(text[end]==='`')end++;const length=end-index;const rows=codeRuns.get(length)||[];rows.push(index);codeRuns.set(length,rows);index=end-1;}
   else if(text[index]==='(')stack.push(index);
   else if(text[index]===')'&&stack.length)parentheses.set(stack.pop(),index);
  }
  function next(rows,after){let low=0,high=rows.length;while(low<high){const mid=(low+high)>>>1;if(rows[mid]<after)low=mid+1;else high=mid;}return rows[low]??-1;}
  function closing(token,after){if(!positions.has(token)){const rows=[];let index=text.indexOf(token);while(index!==-1){rows.push(index);index=text.indexOf(token,index+token.length);}positions.set(token,rows);}return next(positions.get(token),after);}
  let index=0,plain='';const flush=()=>{if(plain){result.append(document.createTextNode(plain));plain='';}};
  while(index<text.length){
   const character=text[index];
   if(character==='\\'&&/[\\`*_[\]{}()#+.!>~-]/.test(text[index+1]||'')){plain+=text[index+1];index+=2;continue;}
   if(character==='`'){
    let end=index+1;while(text[end]==='`')end++;const length=end-index,close=next(codeRuns.get(length),end);
    if(close!==-1){flush();result.append(element('code',text.slice(end,close).replaceAll('\n',' ')));index=close+length;continue;}
    plain+=text.slice(index,end);index=end;continue;
   }
   const image=character==='!'&&text[index+1]==='[',bracket=image?index+1:index;
   if(character==='['||image){
    const labelEnd=closing(']',bracket+1),end=parentheses.get(labelEnd+1);
    if(labelEnd!==-1&&text[labelEnd+1]==='('&&end!==undefined){
     if(!destinations.has(labelEnd)){
      const destination=text.slice(labelEnd+2,end),match=/^(\S+?)(?:\s+"[^"]*")?$/.exec(destination);
      destinations.set(labelEnd,match?link(match[1]):null);
     }
     const href=destinations.get(labelEnd);
     if(href){flush();const node=element('a');node.href=href;node.rel='noopener noreferrer';node.target='_blank';node.append(inline(text.slice(bracket+1,labelEnd),depth+1));result.append(node);index=end+1;continue;}
    }
   }
   const token=text.startsWith('**',index)?'**':text.startsWith('__',index)?'__':text.startsWith('~~',index)?'~~':character==='*'||character==='_'?character:null;
   if(token){
    const close=closing(token,index+token.length),wordUnderscore=token[0]==='_'&&/[\p{L}\p{N}]/u.test(text[index-1]||'');
    if(!wordUnderscore&&close>index+token.length&&!/\s/.test(text[index+token.length])&&!/\s/.test(text[close-1])){
     flush();const node=element(token==='~~'?'del':token.length===2?'strong':'em');node.append(inline(text.slice(index+token.length,close),depth+1));result.append(node);index=close+token.length;continue;
    }
   }
   plain+=character;index++;
  }
  flush();return result;
 }
 const cells=line=>line.trim().replace(/^\|/,'').replace(/\|$/,'').split(/(?<!\\)\|/).map(v=>v.trim().replaceAll('\\|','|'));
 const separator=line=>line.includes('|')&&cells(line).every(v=>/^:?-{3,}:?$/.test(v));
 const listItem=line=>/^( {0,3})([-+*]|\d+[.)])\s+(.*)$/.exec(line);
 const blockStart=line=>/^ {0,3}(?:#{1,6}\s|`{3,}|~{3,}|>|(?:[-*_]\s*){3,}$)/.test(line)||listItem(line);
 function blocks(lines,depth=0){
  const output=document.createDocumentFragment();let index=0;
  if(depth>12){output.append(element('p',lines.join('\n')));return output;}
  while(index<lines.length){
   const line=lines[index];if(!line.trim()){index++;continue;}
   const fence=/^ {0,3}(`{3,}|~{3,})(.*)$/.exec(line);
   if(fence){
    index++;const content=[],closing=new RegExp('^ {0,3}'+fence[1][0]+'{'+fence[1].length+',}\\s*$');
    while(index<lines.length&&!closing.test(lines[index]))content.push(lines[index++]);if(index<lines.length)index++;
    const wrapper=element('div'),head=element('div'),pre=element('pre'),code=element('code',content.join('\n'));
    CodeHighlight.render(code,content.join('\n'),fence[2]);
    wrapper.className='markdown-code';head.className='markdown-code-header';head.append(element('span',fence[2].trim()));
    const copy=element('button','复制代码');copy.type='button';copy.onclick=async()=>{try{await navigator.clipboard.writeText(code.textContent);copy.textContent='已复制';}catch{copy.textContent='复制失败';}};
    head.append(copy);pre.append(code);wrapper.append(head,pre);output.append(wrapper);continue;
   }
   const heading=/^ {0,3}(#{1,6})\s+(.+)$/.exec(line);
   if(heading){const node=element('h'+heading[1].length);node.append(inline(heading[2].replace(/\s+#+\s*$/,'')));output.append(node);index++;continue;}
   if(/^ {0,3}(?:\*\s*){3,}$|^ {0,3}(?:-\s*){3,}$|^ {0,3}(?:_\s*){3,}$/.test(line)){output.append(element('hr'));index++;continue;}
   if(/^ {0,3}>/.test(line)){const quote=[];while(index<lines.length&&/^ {0,3}>/.test(lines[index]))quote.push(lines[index++].replace(/^ {0,3}> ?/,''));const node=element('blockquote');node.append(blocks(quote,depth+1));output.append(node);continue;}
   if(index+1<lines.length&&line.includes('|')&&separator(lines[index+1])){
    const table=element('table'),thead=element('thead'),tr=element('tr'),align=cells(lines[index+1]);
    for(const [column,value] of cells(line).entries()){const th=element('th');th.append(inline(value));th.style.textAlign=align[column]?.endsWith(':')?(align[column].startsWith(':')?'center':'right'):'left';tr.append(th);}thead.append(tr);table.append(thead);index+=2;
    const body=element('tbody');while(index<lines.length&&lines[index].trim()&&lines[index].includes('|')){const row=element('tr');for(const [column,value] of cells(lines[index++]).entries()){const td=element('td');td.append(inline(value));td.style.textAlign=tr.children[column]?.style.textAlign||'left';row.append(td);}body.append(row);}table.append(body);const scroll=element('div');scroll.className='markdown-table';scroll.append(table);output.append(scroll);continue;
   }
   const first=listItem(line);
   if(first){
    const ordered=/\d/.test(first[2]),list=element(ordered?'ol':'ul');if(ordered)list.start=parseInt(first[2],10);
    while(index<lines.length){const item=listItem(lines[index]);if(!item||/\d/.test(item[2])!==ordered)break;
     const content=[item[3]],indent=item[1].length+item[2].length+1;index++;
     while(index<lines.length&&new RegExp('^ {'+indent+',}\\S|^ {'+indent+',}\\s').test(lines[index]))content.push(lines[index++].slice(indent));
     const li=element('li'),task=/^\[([ xX])\]\s+/.exec(content[0]);if(task){const box=element('input');box.type='checkbox';box.disabled=true;box.checked=task[1]!==' ';box.setAttribute('aria-label',box.checked?'已完成':'未完成');li.append(box);li.className='markdown-task';content[0]=content[0].slice(task[0].length);}
     li.append(blocks(content,depth+1));list.append(li);
    }output.append(list);continue;
   }
   const paragraph=[line];index++;
   while(index<lines.length&&lines[index].trim()&&!blockStart(lines[index])&&!(index+1<lines.length&&separator(lines[index+1])))paragraph.push(lines[index++]);
   const node=element('p');node.append(inline(paragraph.join('\n')));output.append(node);
  }return output;
 }
 function render(text){const root=element('div');root.className='text markdown-message';root.append(blocks(String(text).replaceAll('\r\n','\n').split('\n')));return root;}
 return {render};
})();
