const test=require('node:test');
const assert=require('node:assert/strict');
const {tokenize,diff,limit}=require('../code-highlight-worker.js');
const engine=require('../highlight-engine.js');
test('reused engine preserves source and emits color scopes for common languages',()=>{
 for(const [language,text]of [['swift','public enum Sample: String {\n case ready = "你好👋"\n}'],['javascript','const text = "<script>window.injected=true</script>";'],['python','def hello():\n    return "你好"'],['typescript','interface Sample { name: string }']]){
  const runs=tokenize(text,language);assert.equal(runs.map(run=>run.text).join(''),text);assert(runs.some(run=>run.scopes.includes('hljs-keyword')));assert(runs.every(run=>run.scopes.every(scope=>/^[\w -]+$/.test(scope))));
 }
 assert.equal(engine.versionString,'11.11.1');assert.equal(engine.listLanguages().length,31);
});
test('unknown language and UTF-8 limit remain plain without auto detection',()=>{
 assert.deepEqual(tokenize('const a = 1','unknown-fixture'),[]);
 assert.deepEqual(tokenize('你'.repeat(Math.ceil(limit/3)),'javascript'),[]);
 const text='// '+('a'.repeat(limit-3));assert.equal(tokenize(text,'javascript').map(run=>run.text).join(''),text);
});
test('diff highlighting preserves hunk, signs, original line endings and Unicode',()=>{
 const text='@@ -1 +1 @@\n-old()\n+public enum Sample { case ready = "👋\ufffc" }\n';
 assert.equal(tokenize(text,'swift').map(run=>run.text).join(''),text);
});

test('hunks isolate old and new lexical state and retain exact original rows',()=>{
 const patch='@@ -1,2 +1 @@\n-/* removed comment\n-closed */\n+const value = "你好👋"\n@@ -20 +20 @@\n-/* unfinished\n+const next = 2\n';
 const runs=diff(patch,'javascript');assert.equal(runs.map(run=>run.text).join(''),patch);
 const lines=[[]];for(const run of runs){for(const [index,text]of run.text.split('\n').entries()){if(index)lines.push([]);if(text)lines.at(-1).push({text,scopes:run.scopes});}}
 for(const index of [3,6]){
  assert(lines[index].some(run=>run.scopes.includes('hljs-keyword')));
  assert(!lines[index].some(run=>run.scopes.includes('hljs-comment')));
  assert.deepEqual(lines[index][0],{text:'+',scopes:[]});
 }
 for(const index of [0,4])assert(lines[index].every(run=>run.scopes.length===0));
 assert(lines[1].some(run=>run.scopes.includes('hljs-comment')));
 assert.deepEqual(diff('你'.repeat(Math.ceil(limit/3)),'javascript'),[]);
});
test('hunk work is bounded and invalid rows stay plain',()=>{
 const patch=Array.from({length:130},(_,i)=>'@@ -'+(i+1)+' +'+(i+1)+' @@\n-old()\n+const next = 2').join('\n');
 const runs=diff(patch,'javascript');assert.equal(runs.map(run=>run.text).join(''),patch);
 assert(runs.slice(-3).every(run=>run.scopes.length===0));
 const invalid='@@ broken @@\n+const next = 2';assert(diff(invalid,'javascript').every(run=>run.scopes.length===0));
});

test('no-newline annotations do not break source state inside a hunk',()=>{
 const patch='@@ -1,2 +1,3 @@\n /* common open\n-old */\n\\ No newline at end of file\n+new */\n+const next = 2';
 const runs=diff(patch,'javascript');assert.equal(runs.map(run=>run.text).join(''),patch);
 const lines=[[]];for(const run of runs){for(const [index,text]of run.text.split('\n').entries()){if(index)lines.push([]);if(text)lines.at(-1).push({text,scopes:run.scopes});}}
 assert(lines[4].some(run=>run.scopes.includes('hljs-comment')));
 assert(lines[5].some(run=>run.scopes.includes('hljs-keyword')));
 assert(lines[3].every(run=>run.scopes.length===0));
});
