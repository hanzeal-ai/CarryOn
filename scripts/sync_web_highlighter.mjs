// Reuse the Highlight.js engine already shipped by the pinned iOS Highlightr dependency.
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const localRequire=createRequire(path.join(root,'web/package.json'));
const viteRequire=createRequire(localRequire.resolve('vite/package.json'));
const {parseAst}=await import(viteRequire.resolve('rollup/parseAst'));
const source=path.resolve(process.argv[2]||path.join(root,'iOS/.build/SourcePackages/checkouts/Highlightr/src/assets/highlighter'));
const input=fs.readFileSync(path.join(source,'highlight.min.js'),'utf8');
const languages=new Set(['swift','python','javascript','typescript','json','go','rust','java','kotlin','c','cpp','objectivec','csharp','ruby','php','bash','sql','xml','css','scss','yaml','ini','markdown','plaintext','diff','dockerfile','makefile','dart','r','lua','perl']);
const statements=parseAst(input).body,parts=[input.slice(0,statements[0].start)],found=new Set();
for(const [index,statement] of statements.entries()){
 const code=input.slice(statement.start,statement.end);
 const names=[...code.matchAll(/registerLanguage\("([\w-]+)"/g)].map(match=>match[1]);
 if(index<2||names.some(name=>languages.has(name))){
  if(index>=2&&names.length!==1)throw Error('Unexpected grammar module structure');
  parts.push(input.slice(index?statements[index-1].end:statement.start,statement.end));
  names.forEach(name=>found.add(name));
 }
}
for(const language of languages)if(!found.has(language))throw Error('Missing language '+language);
fs.writeFileSync(path.join(root,'highlight-engine.js'),parts.join('\n')+'\n');
const license=path.join(root,'highlight-engine.LICENSE');
if(fs.existsSync(license))fs.chmodSync(license,0o644);
fs.writeFileSync(license,fs.readFileSync(path.join(source,'LICENSE')));
console.log('Generated existing engine for '+found.size+' languages: '+Buffer.byteLength(parts.join('\n'))+' bytes');
// Project only colors; typography, layout and selection remain owned by the Web views.
const postcss=localRequire('postcss');
function palette(name){
 const rules=[];
 postcss.parse(fs.readFileSync(path.join(source,'..','styles',name+'.min.css'),'utf8')).walkRules(rule=>{
  const colors=rule.nodes.filter(node=>node.type==='decl'&&node.prop==='color');
  if(!colors.length)return;
  const selector=rule.selector.split(',').map(value=>{const trimmed=value.trim();return trimmed==='.hljs'?'.syntax-colors':'.syntax-colors '+trimmed;}).join(',');
  rules.push(selector+'{'+colors.map(node=>'color:'+node.value).join(';')+'}');
 });
 return rules.join('');
}
fs.writeFileSync(path.join(root,'code-highlight.css'),'/* Color-only palettes from the existing Highlightr Highlight.js resources. BSD-3-Clause; see highlight-engine.LICENSE. */\n'+palette('github-gist')+'\n@media(prefers-color-scheme:dark){'+palette('atom-one-dark')+'}\n');
