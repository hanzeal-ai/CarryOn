const test=require('node:test'),assert=require('node:assert/strict'),form=require('../elicitation-form.js');
test('MCP typed form preserves false, numbers and Unicode while enforcing schema',()=>{
 const schema={type:'object',properties:{name:{type:'string',minLength:2,maxLength:3},count:{type:'integer',minimum:1,maximum:4},ok:{type:'boolean'},option:{type:'number',enum:[1,2]}},required:['name','ok']};
 assert(form.supports(schema));assert.deepEqual({...form.response(schema,{name:'字😀',ok:'false',count:'2',option:'1'})},{name:'字😀',count:2,ok:false,option:1});
 for(const bad of [{name:'a',ok:'false'},{name:'okay',ok:'true'},{name:'字😀',ok:''},{name:'字😀',ok:'false',count:'2.5'},{name:'字😀',ok:'false',count:'5'},{name:'字😀',ok:'false',option:'3'}])assert.throws(()=>form.response(schema,bad));
});
test('MCP unfamiliar constraints and invalid enums cannot be silently discarded',()=>{
 for(const schema of [{type:'array'},{type:'object',properties:{x:{type:'string',pattern:'a'}}},{type:'object',properties:{x:{type:'integer',enum:[1.5]}}},{type:'object',properties:{},required:['missing']}]){assert(!form.supports(schema));assert.throws(()=>form.response(schema,{}));}
 assert.equal(form.response(null,{}),null);
 const schema=JSON.parse('{"type":"object","properties":{"__proto__":{"type":"string"}}}');assert.equal(form.response(schema,JSON.parse('{"__proto__":"safe"}')).__proto__,'safe');
});
