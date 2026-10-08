const test=require('node:test');
const assert=require('node:assert/strict');
const {webcrypto}=require('node:crypto');
global.crypto=webcrypto;
const Diff=require('../diff-review.js'),Comments=require('../review-comments.js');
const patch='@@ -1 +1 @@\n-old()\n+new()',row=Diff.lines(patch)[2];
const create=(text='检查',sourceId='item')=>Comments.create({sourceId,path:'src/main.js',patch,row,text});
test('comments require an actual parsed line and source identity',()=>{
 assert.throws(()=>create('x',''));
 assert.throws(()=>Comments.create({sourceId:'item',path:'src/main.js',patch:patch.replace('new','other'),row,text:'x'}));
 assert.throws(()=>Comments.create({sourceId:'item',path:'src/main.js',patch,row:Diff.lines(patch)[0],text:'x'}));
});
test('same path and line in different native changes have separate identity',()=>{
 const a=create('x','one'),b=create('x','two');assert.equal(a.location,b.location);assert.notEqual(a.sourceId,b.sourceId);assert.notEqual(a.id,b.id);
});
test('only comments produce deterministic ordinary text without moving body references',()=>{
 const a=create('说明 **原文** 👋'),b=create('说明 **原文** 👋');
 assert.equal(Comments.prompt('正文引用',[a]),'正文引用\n\n关于已加载改动 src/main.js（R1）：\n+new()\n说明 **原文** 👋');
 assert.equal(Comments.prompt('',[a]),Comments.prompt('',[b]));
});
test('confirmation removes exact sent comments and keeps later edits and additions',()=>{
 const unchanged=create('不变'),changed=create('原文'),added=create('新评论'),edited={...changed,text:'后改'};
 assert.deepEqual(Comments.didSubmit([unchanged,edited,added],[unchanged,changed]),[edited,added]);
 assert.deepEqual(Comments.didSubmit([unchanged],[unchanged]),[]);
});
