const test=require('node:test'),assert=require('node:assert/strict');
const {lines}=require('../diff-review.js');
test('bounded hunks locate only actual source lines',()=>{
 const rows=lines('@@ -3,2 +7,2 @@\n same\n-old\n+new\n--- a/next\n+++ b/next');
 assert.equal(rows[1].location,'R7');assert.equal(rows[2].location,'L4');assert.equal(rows[3].location,'R8');assert.equal(rows[4].location,null);assert.equal(rows[5].location,null);
});
test('malformed and overflowing headers cannot create references',()=>{
 for(const patch of ['@@ -1 +1\n+bad','@@ -9007199254740991 +1 @@\n-old','+fragment'])assert.equal(lines(patch).at(-1).location,null);
});
test('empty sides and header-looking content remain valid',()=>{
 assert.equal(lines('@@ -0,0 +1 @@\n+new')[1].location,'R1');
 assert.equal(lines('@@ -1 +1 @@\n--- content\n+++ content')[2].location,'R1');
});
