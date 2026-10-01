'use strict';
const DiffReview = (() => {
  function lines(patch) {
    let old=0,next=0,left=0,right=0;
    return String(patch).split('\n').map((text,id)=>{
      const row={id,text,old:null,new:null,kind:'header',location:null};
      if(text.startsWith('@@')){
        left=right=0;
        const match=/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$/.exec(text);
        if(match){const values=[Number(match[1]),Number(match[2]??1),Number(match[3]),Number(match[4]??1)];
          if(values.every(Number.isSafeInteger)&&Number.isSafeInteger(values[0]+values[1])&&Number.isSafeInteger(values[2]+values[3]))[old,left,next,right]=values;}
        return row;
      }
      if(text.startsWith('\\ No newline'))return row;
      if(text.startsWith('+')&&right>0){row.new=next++;right--;row.kind='added';}
      else if(text.startsWith('-')&&left>0){row.old=old++;left--;row.kind='removed';}
      else if(text.startsWith(' ')&&left>0&&right>0){row.old=old++;row.new=next++;left--;right--;row.kind='context';}
      else {left=right=0;return row;}
      row.location=row.new===null?'L'+row.old:'R'+row.new;return row;
    });
  }
  function render(parent,{path,patch,onComment}){
    const make=(tag,cls,text)=>{const el=document.createElement(tag);el.className=cls;if(text!==undefined)el.textContent=text;return el;};
    const rows=lines(patch),table=make('div','diff-lines'),footer=make('div','diff-footer');
    let count=0,editor=null;
    function comment(row,anchor){
      editor?.remove();editor=make('div','diff-comment');
      const title=make('label','','评论 '+path+' · '+row.location),input=make('textarea','');input.rows=3;title.append(input);
      const status=make('p','');status.setAttribute('role','status');
      const add=make('button','','添加到对话'),cancel=make('button','','取消');add.type=cancel.type='button';add.disabled=true;
      input.oninput=()=>{add.disabled=!input.value.trim();};cancel.onclick=()=>{editor.remove();editor=null;};
      add.onclick=()=>{if(!input.value.trim())return;const error=onComment({path,location:row.location,text:row.text,comment:input.value.trim()});if(error){status.textContent=error;return;}editor.remove();editor=null;};
      editor.append(title,add,cancel,status);anchor.after(editor);input.focus();
    }
    function more(){
      const fragment=document.createDocumentFragment();
      for(const row of rows.slice(count,count+250)){
        const line=make('div','diff-line '+row.kind);line.append(make('span','diff-number',row.old??''),make('span','diff-number',row.new??''),make('code','diff-text',row.text||' '));
        if(path&&onComment&&row.location){const button=make('button','diff-comment-action','＋');button.type='button';button.setAttribute('aria-label','评论 '+path+' '+row.location);button.onclick=()=>comment(row,line);line.append(button);}
        fragment.append(line);
      }
      count=Math.min(count+250,rows.length);table.append(fragment);footer.replaceChildren();
      if(count<rows.length){const button=make('button','','显示更多改动（剩余 '+(rows.length-count)+' 行）');button.type='button';button.onclick=more;footer.append(button);}
    }
    parent.append(table,footer);more();
  }
  return {lines,render};
})();
if(typeof module!=='undefined')module.exports=DiffReview;
