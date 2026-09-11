/* Render only with DOM text nodes: tool output and Markdown are untrusted text. */
const Timeline = (() => {
 function create(ids={runtime:'runtime',info:'conversation-info',source:'history-source'}) {
  let visible = 120, current = null, expanded = false;
  const labels = {inProgress:'进行中',completed:'已完成',failed:'失败',interrupted:'已中断',declined:'已拒绝',
    idle:'空闲',active:'正在处理',notLoaded:'未加载',systemError:'运行异常',unknown:'状态未知'};
  const el = (tag, cls, text) => {const n=document.createElement(tag);n.className=cls||'';if(text!==undefined)n.textContent=text;return n;};
  const stringify = value => typeof value==='string'?value:JSON.stringify(value,null,2);
  const duration = ms => Number.isFinite(ms)?(ms<1000?ms+' 毫秒':(ms/1000).toFixed(1)+' 秒'):'';
  function copyButton(value) {
    const button=el('button','quiet copy','复制原文');button.type='button';
    button.onclick=async()=>{try{await navigator.clipboard.writeText(value);button.textContent='已复制';}
      catch{button.textContent='复制失败，请手动选择';}};
    return button;
  }
  function block(label, value) {
    const section=el('section','detail-section');
    const head=el('div','detail-label',label);head.append(copyButton(stringify(value)));
    section.append(head,el('pre','original',stringify(value)));return section;
  }
  function details(item) {
    const d=item.data||{}, content=el('div','activity-body');
    if(item.type==='commandExecution'){
      content.append(block('命令',d.command||''));
      if(d.cwd)content.append(el('div','activity-meta','目录：'+d.cwd));
      if(d.exitCode!==null && d.exitCode!==undefined)content.append(el('div','activity-meta','退出码：'+d.exitCode));
      if(d.aggregatedOutput!==undefined && d.aggregatedOutput!==null)content.append(block('执行输出',d.aggregatedOutput));
    } else if(item.type==='fileChange'){
      for(const change of d.changes||[])content.append(block(change.path||'文件修改',change.diff??change));
    } else if(item.type==='reasoning'){
      content.append(el('div','text',item.text||'本条记录未提供可展示的思考摘要。'));
    } else if(item.type==='mcpToolCall' || item.type==='dynamicToolCall'){
      if(d.arguments!==undefined)content.append(block('调用参数',d.arguments));
      const result=d.result;
      if(result?.content){for(const part of result.content)content.append(block(part.type==='text'?'工具结果':('工具结果 · '+part.type),part.type==='text'?part.text:part));}
      else if(result!==undefined)content.append(block('工具结果',result));
      if(d.contentItems!==undefined)content.append(block('工具结果',d.contentItems));
      if(d.error)content.append(block('错误',d.error));
    } else if(item.type==='contextCompaction'){
      content.append(el('div','text',item.status==='inProgress'?'Codex 正在压缩上下文。':'这次上下文压缩已结束。'));
    } else {
      if(item.text)content.append(el('div','text',item.text));
      if(Object.keys(d).length)content.append(block('事件详情',d));
    }
    const raw=el('details','raw-event');raw.dataset.key=item.id+':raw';raw.append(el('summary','','查看结构化记录'),block('展示字段',d));content.append(raw);
    if(item.supported===false)content.prepend(el('p','coverage-note','此事件类型尚未适配，已保留类型与状态，请在 Codex App 查看完整内容。'));
    return content;
  }
  function entry(item) {
    if(item.type==='turn'){
      const row=el('div','turn-marker');const d=item.data||{};
      const time=d.turnStartedAtMs?new Date(d.turnStartedAtMs).toLocaleString():'';
      row.append(el('strong','',item.title),el('span','',[labels[item.status]||item.status,duration(d.durationMs),time,d.model,d.effort].filter(Boolean).join(' · ')));
      return row;
    }
    if(['userMessage','steeringUserMessage','agentMessage'].includes(item.type)){
      const user=item.type!=='agentMessage', article=el('article','message '+(user?'user':'assistant')+(item.phase==='commentary'?' commentary':''));
      const head=el('div','message-head');head.append(el('span','role',user?'你':item.phase==='commentary'?'Codex · 进度':'Codex'),copyButton(item.text||''));
      article.append(head,el('div','text',item.text||''));
      for(const part of item.data?.content||item.data?.input||[]){
        if(part.type==='image'&&typeof part.url==='string'&&part.url.length<300000&&/^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/.test(part.url)){
          const img=el('img','message-image');img.src=part.url;img.alt='会话图片';img.loading='lazy';article.append(img);
        }else if(part.type!=='text')article.append(block('附件 / 引用 · '+part.type,part.type==='image'?{type:part.type,description:'图片引用'}:part));
      }
      const extra={...item.data};delete extra.text;delete extra.content;delete extra.input;delete extra.phase;
      if(Object.values(extra).some(v=>v!==null && v!==undefined)){
        const info=el('details','raw-event');info.dataset.key=item.id+':extra';info.append(el('summary','','引用与消息详情'),block('消息信息',extra));article.append(info);
      }
      return article;
    }
    const card=el('details','activity'+(item.status==='inProgress'?' running':'')+(item.status==='failed'?' failed':''));
    card.dataset.key=item.id;card.open=expanded;
    const summary=el('summary','activity-summary');
    const icon=el('span','activity-icon',item.type==='contextCompaction'?'⇣':item.type==='reasoning'?'◌':item.type==='fileChange'?'±':'›_');
    const title=el('span','activity-title',item.title);
    if(item.type==='commandExecution')title.append(el('code','command-preview',' '+item.text));
    summary.append(icon,title,el('span','activity-state',[labels[item.status]||item.status,duration(item.durationMs)].filter(Boolean).join(' · ')));
    card.append(summary,details(item));return card;
  }
  function render(data, container) {
    current={data,container};
    const open=new Map([...container.querySelectorAll('details[data-key]')].map(n=>[n.dataset.key,n.open]));
    const atBottom=container.scrollHeight-container.scrollTop-container.clientHeight<100, scroll=container.scrollTop;
    const all=data.timeline||data.messages.map(m=>({id:m.id,type:m.role==='user'?'userMessage':'agentMessage',text:m.text,phase:m.phase,data:{}}));
    const fragment=document.createDocumentFragment();
    if(all.length>visible){const more=el('button','history-more','显示更早记录（还有 '+(all.length-visible)+' 条）');more.onclick=()=>{
      const oldHeight=container.scrollHeight;visible+=120;render(data,container);container.scrollTop=scroll+container.scrollHeight-oldHeight;
    };fragment.append(more);}
    for(const item of all.slice(-visible))fragment.append(entry(item));
    if(!all.length)fragment.append(el('div','empty-small','暂无会话记录。'));
    container.replaceChildren(fragment);
    for(const n of container.querySelectorAll('details[data-key]'))if(open.has(n.dataset.key))n.open=open.get(n.dataset.key);
    container.scrollTop=atBottom||!container.dataset.loaded?container.scrollHeight:scroll;container.dataset.loaded='true';
    const runtime=data.runtime||{type:'unknown'}, meta=data.metadata||{};
    const activeItems=all.filter(i=>i.status==='inProgress'&&i.type!=='turn');
    const latest=activeItems.at(-1);
    document.getElementById(ids.runtime).textContent=[data.status?.label||labels[runtime.type]||runtime.type,
      runtime.type==='active'&&latest?latest.title:'',meta.latestModel,
      data.pendingRequests?.length?'有 '+data.pendingRequests.length+' 项待处理请求':''].filter(Boolean).join(' · ');
    const warnings=[];
    if(data.truncated)warnings.push('原生历史未完整加载');
    if(!data.timeline)warnings.push('旧历史回退：仅文字记录');
    if(data.coverage?.unsupportedTypes?.length)warnings.push('未适配事件：'+data.coverage.unsupportedTypes.join('、'));
    document.getElementById(ids.source).textContent=warnings.length?warnings.join('；'):'已同步原生记录';
    const info=document.getElementById(ids.info);
    info.replaceChildren(block('会话信息',{...meta,runtime,pendingRequests:data.pendingRequests||[],coverage:data.coverage||{}}));
  }
  function setExpanded(value){expanded=value;if(current){for(const d of current.container.querySelectorAll('details.activity'))d.open=value;}}
  function reset(){visible=120;current=null;expanded=false;document.getElementById(ids.runtime).textContent='';document.getElementById(ids.info).replaceChildren();}
  return {render,reset,setExpanded};
 }
 return {...create(),create};
})();
