/* Flat primitive MCP forms, matching CarryOnCore.ElicitationForm. */
const ElicitationForm=(()=>{
 const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
 function valid(value,field){
  if(field.type==='string')return typeof value==='string'&&(field.minLength==null||[...value].length>=field.minLength)&&(field.maxLength==null||[...value].length<=field.maxLength);
  if(field.type==='boolean')return typeof value==='boolean';
  return typeof value==='number'&&Number.isFinite(value)&&(field.type!=='integer'||Number.isInteger(value))&&(field.minimum==null||value>=field.minimum)&&(field.maximum==null||value<=field.maximum);
 }
 function supports(schema){
  if(schema==null)return true;
  const roots=['type','properties','required','title','description','additionalProperties','$schema'],keys=['type','title','description','enum','enumNames','default','minLength','maxLength','minimum','maximum'];
  if(!object(schema)||schema.type!=='object'||!object(schema.properties)||Object.keys(schema).some(k=>!roots.includes(k)))return false;
  if(schema.required!=null&&(!Array.isArray(schema.required)||schema.required.some(k=>typeof k!=='string'||!Object.hasOwn(schema.properties,k))))return false;
  if(schema.additionalProperties!=null&&typeof schema.additionalProperties!=='boolean')return false;
  return Object.values(schema.properties).every(f=>object(f)&&['string','number','integer','boolean'].includes(f.type)&&Object.keys(f).every(k=>keys.includes(k))&&['minimum','maximum'].every(k=>f[k]==null||typeof f[k]==='number'&&Number.isFinite(f[k]))&&['minLength','maxLength'].every(k=>f[k]==null||Number.isInteger(f[k])&&f[k]>=0)&&(f.enum==null||Array.isArray(f.enum)&&f.enum.length>0&&f.enum.every(v=>valid(v,f))));
 }
 function response(schema,values){
  if(!supports(schema))throw Error('请在 Codex App 完成此请求');if(schema==null)return null;
  const result=Object.create(null);
  for(const [key,f]of Object.entries(schema.properties)){
   const raw=values[key]??'',title=f.title||key;if(raw===''){if(schema.required?.includes(key))throw Error('请填写：'+title);continue;}
   let value=raw;
   if(f.enum)value=f.enum.find(v=>JSON.stringify(v)===raw);
   else if(f.type==='boolean')value=raw==='true'?true:raw==='false'?false:undefined;
   else if(['number','integer'].includes(f.type))value=raw.trim()?Number(raw):NaN;
   if(!valid(value,f))throw Error('内容不符合要求：'+title);result[key]=value;
  }
  return result;
 }
 function render(parent,schema){
  const inputs=new Map();
  for(const [key,f]of Object.entries(schema?.properties||{}).sort(([a],[b])=>a.localeCompare(b))){
   const label=document.createElement('label');label.textContent=(f.title||key)+(schema.required?.includes(key)?' *':'');
   const input=document.createElement(f.enum||f.type==='boolean'?'select':'input');input.setAttribute('aria-label',f.title||key);input.dataset.draftKey='mcp:'+key;
   if(input.tagName==='SELECT'){input.append(new Option('请选择',''));for(const value of f.enum||[true,false])input.append(new Option(typeof value==='boolean'?(value?'是':'否'):String(value),JSON.stringify(value)));}
   else{input.type='text';if(['number','integer'].includes(f.type))input.inputMode='decimal';}
   label.append(input);if(f.description){const detail=document.createElement('small');detail.textContent=f.description;label.append(detail);}parent.append(label);inputs.set(key,input);
  }
  return ()=>response(schema,Object.fromEntries([...inputs].map(([key,input])=>[key,input.value])));
 }
 return {supports,response,render};
})();
if(typeof module!=='undefined')module.exports=ElicitationForm;
