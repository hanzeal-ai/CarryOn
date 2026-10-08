'use strict';
const DiffReview = (() => {
  const {lines}=typeof module!=='undefined'?require('./unified-diff.js'):UnifiedDiff;
  const make=(tag,cls,text)=>{const el=document.createElement(tag);el.className=cls;if(text!==undefined)el.textContent=text;return el;};
  function commentCard(note,{save,remove}){
    const card=make('div','diff-comment-card'),head=make('div','diff-comment-head'),body=make('p','',note.text),actions=make('div','diff-comment-actions'),status=make('p','');status.setAttribute('role','status');
    const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');icon.setAttribute('viewBox','0 0 20 20');icon.setAttribute('aria-hidden','true');
    const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d','M5 3h10a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H9l-4 3v-3a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Zm2 4h6M7 11h4');icon.append(path);
    head.append(icon,make('strong','','本地评论'),make('span','','第 '+note.location+' 行'));
    const edit=make('button','','编辑'),del=make('button','','删除');edit.type=del.type='button';
    del.onclick=()=>{const error=remove(note);if(error)status.textContent=error;};
    edit.onclick=()=>{
      const input=make('textarea','');input.rows=3;input.value=note.text;input.setAttribute('aria-label','编辑评论');body.replaceWith(input);
      const accept=make('button','','保存'),cancel=make('button','','取消');accept.type=cancel.type='button';accept.disabled=!input.value.trim();
      input.oninput=()=>{accept.disabled=!input.value.trim();};accept.onclick=()=>{const error=save(note,input.value);if(error)status.textContent=error;};
      cancel.onclick=()=>{input.replaceWith(body);actions.replaceChildren(edit,del);status.textContent='';};actions.replaceChildren(accept,cancel);input.focus();
    };
    actions.append(edit,del);card.append(head,body,actions,status);return card;
  }
  function render(parent,{path,patch,onComment,onEdit,onDelete,comments=()=>[]}){
    const rows=lines(patch),table=make('div','diff-lines'),footer=make('div','diff-footer'),commentRows=new Map(),cards=new Map(),codeRows=new Map();
    let colored=null;CodeHighlight.highlightDiff(patch,CodeHighlight.fileLanguage(path)).then(runs=>{colored=CodeHighlight.splitLines(runs);for(const [id,code]of codeRows)CodeHighlight.paint(code,rows[id].text,colored[id]||[]);});
    let count=0,editor=null;
    function refreshComments(){
      const notes=comments();
      const active=new Set(notes.map(note=>note.id));
      for(const [id,entry]of cards)if(!active.has(id)){entry.card.remove();cards.delete(id);}
      for(const note of notes){const root=commentRows.get(note.lineId);if(!root)continue;let entry=cards.get(note.id);
        if(!entry||entry.note!==note){const card=commentCard(note,{save:onEdit,remove:onDelete});if(entry)entry.card.replaceWith(card);entry={note,card};cards.set(note.id,entry);}
        if(entry.card.parentNode!==root)root.append(entry.card);
      }
    }
    function comment(row,anchor){
      editor?.remove();editor=make('div','diff-comment');
      const title=make('label','','评论 '+path+' · '+row.location),input=make('textarea','');input.rows=3;title.append(input);
      const status=make('p','');status.setAttribute('role','status');
      const add=make('button','','添加评论'),cancel=make('button','','取消');add.type=cancel.type='button';add.disabled=true;
      input.oninput=()=>{add.disabled=!input.value.trim();};cancel.onclick=()=>{editor.remove();editor=null;};
      add.onclick=()=>{if(!input.value.trim())return;const error=onComment({path,patch,row,text:input.value});if(error){status.textContent=error;return;}editor.remove();editor=null;};
      editor.append(title,add,cancel,status);anchor.after(editor);input.focus();
    }
    function more(){
      const fragment=document.createDocumentFragment();
      for(const row of rows.slice(count,count+250)){
        const wrapper=make('div','diff-row'),line=make('div','diff-line '+row.kind),notes=make('div','diff-row-comments');line.append(make('span','diff-number',row.old??''),make('span','diff-number',row.new??''),make('code','diff-text',row.text||' '));
        const code=line.querySelector('.diff-text');codeRows.set(row.id,code);
        if(path&&onComment&&row.location){const button=make('button','diff-comment-action','＋');button.type='button';button.setAttribute('aria-label','评论 '+path+' '+row.location);button.onclick=()=>comment(row,line);line.append(button);}
        wrapper.append(line,notes);commentRows.set(row.id,notes);fragment.append(wrapper);
      }
      count=Math.min(count+250,rows.length);table.append(fragment);if(colored)for(const [id,code]of codeRows)CodeHighlight.paint(code,rows[id].text,colored[id]||[]);footer.replaceChildren();refreshComments();
      if(count<rows.length){const button=make('button','','显示更多改动（剩余 '+(rows.length-count)+' 行）');button.type='button';button.onclick=more;footer.append(button);}
    }
    parent.append(table,footer);more();return {refreshComments};
  }
  return {lines,render,commentCard};
})();
if(typeof module!=='undefined')module.exports=DiffReview;
