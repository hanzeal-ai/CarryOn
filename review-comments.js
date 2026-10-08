'use strict';
const ReviewComments=(()=>{
 const diff=typeof module!=='undefined'?require('./diff-review.js'):DiffReview;
 function create({sourceId,path,patch,row,text}){
  const actual=diff.lines(patch)[row.id];
  if(!sourceId||!path||!text.trim()||!actual?.location||actual.location!==row.location||actual.text!==row.text)throw Error('评论位置与原始改动不一致');
  return {id:crypto.randomUUID(),sourceId,path,patch,lineId:row.id,location:row.location,lineText:row.text,text};
 }
 function note(comment){return '关于已加载改动 '+comment.path+'（'+comment.location+'）：\n'+comment.lineText+'\n'+comment.text;}
 function prompt(text,comments){return [text,...comments.map(note)].filter(Boolean).join('\n\n');}
 function equal(a,b){return a.id===b.id&&a.sourceId===b.sourceId&&a.path===b.path&&a.patch===b.patch&&a.lineId===b.lineId&&a.location===b.location&&a.lineText===b.lineText&&a.text===b.text;}
 function didSubmit(current,sent){
  const submitted=new Map(sent.map(comment=>[comment.id,comment]));
  return current.filter(comment=>!submitted.has(comment.id)||!equal(submitted.get(comment.id),comment));
 }
 return {create,note,prompt,didSubmit,equal};
})();
if(typeof module!=='undefined')module.exports=ReviewComments;
