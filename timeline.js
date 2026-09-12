/* Render only with DOM text nodes: tool output and Markdown are untrusted text. */
const Timeline = (() => {
 function create(ids={runtime:'runtime',info:'conversation-info',source:'history-source'}) {
  let visible = 120, current = null, expanded = false, imageObserver = null;
  const imageCache = new Map();
  let entryCache = new Map();
  let loadEarlier=null,expandingHistory=false;
  function configureHistory(callback){loadEarlier=callback;}
  const safeImage = url => typeof url==='string' && url.length<12000000 && /^data:image\/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+$/.test(url);
  function picture(article, part) {
    const frame=el('button','message-picture'),img=el('img','message-image'),status=el('span','image-status','正在加载图片…');
    frame.type='button';frame.setAttribute('aria-label','打开原图');
    img.alt=part.name||'会话图片';img.loading='eager';img.hidden=true;
    frame.onclick=()=>{if(safeImage(img.src))openImage(img.src,img.alt);};
    img.onload=()=>{status.remove();img.hidden=false;};
    img.onerror=()=>{img.remove();status.textContent='图片无法显示';};
    frame.append(img,status);article.append(frame);
    if(safeImage(part.url)){img.src=part.url;return;}
    if((!part.imageId&&!part.artifactId)||!current.loadImage){status.textContent='图片暂不可用';return;}
    const loader=current.loadImage,identifier=part.imageId||part.artifactId,kind=part.artifactId?'artifacts':'images',cacheKey=kind+':'+identifier;
    frame.loadImage=async()=>{
      try {
        if(!imageCache.has(cacheKey)){
          if(imageCache.size>=8)imageCache.delete(imageCache.keys().next().value);
          const pending=loader(identifier,kind);imageCache.set(cacheKey,pending);
          pending.catch(()=>{if(imageCache.get(cacheKey)===pending)imageCache.delete(cacheKey);});
        }
        const result=await imageCache.get(cacheKey);
        if(!frame.isConnected)return;
        const url=result.url||'data:'+result.mime+';base64,'+result.base64;
        if(!safeImage(url))throw Error('图片格式不受支持');
        img.src=url;delete frame.loadImage;
      } catch(error){if(frame.isConnected)status.textContent=error.message||'图片暂不可用';}
    };
  }
  function openImage(url,name){
    const dialog=el('dialog','timeline-image-lightbox'),bar=el('div','timeline-image-lightbox-actions'),close=el('button','quiet','关闭'),image=el('img','timeline-full-image');
    image.src=url;image.alt=name;
    close.onclick=()=>dialog.close();image.onclick=()=>image.classList.toggle('original-size');
    bar.append(close);dialog.append(bar,image);dialog.addEventListener('close',()=>dialog.remove(),{once:true});
    document.body.append(dialog);dialog.showModal();
  }
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
    if(value==null || (typeof value==='string' && !value.trim()))return document.createDocumentFragment();
    const section=el('section','detail-section');
    const head=el('div','detail-label',label);head.append(copyButton(stringify(value)));
    section.append(head,el('pre','original',stringify(value)));return section;
  }
  function details(item) {
    const d=item.data||{}, content=el('div','activity-body');
    const state=[labels[item.status]||item.status,duration(item.durationMs)].filter(Boolean).join(' · ');
    if(state)content.append(el('div','activity-meta',state));
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
    if(item.supported===false)content.prepend(el('p','coverage-note','此事件类型尚未适配，已保留类型与状态，请在 Codex App 查看完整内容。'));
    return content;
  }
  const questionState=new Map();
  let questionActions=null;
  function configureQuestions(actions){questionActions=actions;}
  function questionCard(question, article) {
    if(!questionActions)return;
    const thread=current.data.thread?.id;
    if(!thread)return;
    const key=thread+':'+question.id;
    let state=questionState.get(key);
    if(!state){state={open:question.active&&!question.answer,choice:question.answer??question.options?.[0]??'',custom:question.answer||'',useCustom:question.answer!=null&&!(question.options||[]).includes(question.answer),touched:false,pending:false,submitted:false,lastSubmission:null};questionState.set(key,state);
      if(state.open)state.timer=setTimeout(()=>{state.timer=null;if(!state.touched){state.open=false;state.update?.();}},30000);
    }
    if(question.answer!=null){state.open=false;state.submitted=true;state.lastSubmission=question.answer;clearTimeout(state.timer);}
    if(!question.active&&!state.touched)state.open=false;
    const host=el('section','async-question'),launch=el('button','question-launch',state.submitted?'已提交回答':'回答问题'),card=el('div','async-question-card');
    const head=el('div','question-heading'),close=el('button','quiet','×');close.type='button';close.setAttribute('aria-label','收起问题');head.append(el('span','','问题'),close);
    const form=el('form'),choices=el('div','question-choices');
    const touch=()=>{state.touched=true;clearTimeout(state.timer);};
    const radios=[];
    for(const [index,option] of (question.options||[]).entries()){
      const button=el('button','question-option');button.type='button';button.setAttribute('role','radio');
      button.append(el('span','question-number',String(index+1)),el('span','',option));
      button.onclick=()=>{touch();state.useCustom=false;state.choice=option;update();};choices.append(button);radios.push([button,option]);
    }
    choices.setAttribute('role','radiogroup');choices.setAttribute('aria-label',question.title);
    const custom=el('textarea','question-custom');custom.placeholder='或输入你的回答';custom.setAttribute('aria-label','自定义回答');custom.rows=2;custom.value=state.custom;custom.dataset.questionKey=key;
    custom.onfocus=()=>{touch();state.useCustom=true;update();};custom.oninput=()=>{touch();state.custom=custom.value;state.useCustom=true;update();};
    const footer=el('div','question-actions'),skip=el('button','quiet','跳过'),send=el('button','primary','发送'),error=el('p','question-error');skip.type='button';send.type='submit';
    skip.onclick=()=>{touch();state.open=false;update();};close.onclick=skip.onclick;
    footer.append(skip,send);form.append(el('p','question-title',question.title),choices,custom,error,footer);card.append(head,form);host.append(launch,card);article.append(host);
    function update(){
      if(!host.isConnected&&state.update!==update)return;
      launch.hidden=state.open;card.hidden=!state.open;error.textContent=state.error||'';
      launch.textContent=state.submitted?'已提交回答':'回答问题';
      const answer=(state.useCustom?state.custom:state.choice).trim();
      send.disabled=state.pending||!questionActions.canSend(thread)||!answer||answer===state.lastSubmission;
      custom.disabled=state.pending;skip.disabled=state.pending;close.disabled=state.pending;
      for(const [radio,option]of radios){radio.disabled=state.pending;radio.setAttribute('aria-checked',String(!state.useCustom&&state.choice===option));}
      if(state.submitted&&question.answer!=null)launch.title=question.answer;
    }
    state.update=update;
    launch.onclick=()=>{touch();state.open=true;update();};
    form.onsubmit=async event=>{
      event.preventDefault();if(state.pending||!questionActions.canSend(thread))return;
      const answer=(state.useCustom?state.custom:state.choice).trim();if(!answer||answer===state.lastSubmission)return;
      touch();state.pending=true;state.error='';update();
      const prompt='<send_user_message_question_reply>\n'+JSON.stringify([{questionItemId:question.id,question:question.title,answer}])+'\n</send_user_message_question_reply>';
      try{await questionActions.submit(thread,prompt);state.submitted=true;state.lastSubmission=answer;state.open=false;}
      catch(failure){state.error=failure.message||'提交失败，请重试';}
      finally{state.pending=false;state.update?.();}
    };
    update();
  }
  function displayText(item) {
    return (item.text||'').replace(/!?\[([^\]\n]*)\]\((<[^>\n]+>|[^\s)]+)(?:\s+"[^"\n]*")?\)/g,(match,label,target)=>{
      let path;try{path=decodeURIComponent(target.replace(/^<|>$/g,'')).replace(/:\d+(?::\d+)?$/,'');}catch{return match;}
      return (item.artifacts||[]).some(ref=>ref.path===path)?label:match;
    });
  }
  function artifacts(item, target) {
    for(const ref of item.artifacts||[]){
      if(ref.kind==='image'){picture(target,{type:ref.url?'image':'localImage',url:ref.url,artifactId:ref.id,name:ref.name});continue;}
      const card=el('section','result-attachment');
      if(ref.kind==='image')card.append(el('div','attachment-name',ref.name));
      const status=el('span','image-status');card.append(status);
      const loader=current.loadImage;
      let pending;
      const load=()=>pending||(pending=loader(ref.id,'artifacts').catch(error=>{pending=null;throw error;}));
      const preview=el('button','quiet attachment-name',ref.name);
      const bytes=result=>Uint8Array.from(atob(result.base64),c=>c.charCodeAt(0));
      preview.onclick=async()=>{try{
        const result=await load(), dialog=el('dialog','attachment-preview'),close=el('button','quiet','关闭');
        close.onclick=()=>dialog.close();dialog.append(close);
        const data=bytes(result);let url;
        if(result.mime==='application/pdf'){
          url=URL.createObjectURL(new Blob([data],{type:'application/pdf'}));
          const frame=el('iframe');frame.title=ref.name;frame.setAttribute('sandbox','');frame.src=url;dialog.append(frame);
        }else if(result.mime.startsWith('text/')||/\.(json|md|swift|py|js|ts|tsx|csv|log)$/i.test(ref.name)){
          dialog.append(el('pre','original',new TextDecoder().decode(data)));
        }else {dialog.append(el('p','','暂不支持预览此文件格式。'));}
        dialog.addEventListener('close',()=>{if(url)URL.revokeObjectURL(url);dialog.remove();},{once:true});
        document.body.append(dialog);dialog.showModal();
      }catch(error){status.textContent=error.message;}};
      card.append(preview);
      target.append(card);
    }
  }
  function entry(item) {
    if(item.type==='turn'){
      const row=el('div','turn-marker');const d=item.data||{};
      const time=d.turnStartedAtMs?new Date(d.turnStartedAtMs).toLocaleString():'';
      row.append(el('strong','',item.title),el('span','',[labels[item.status]||item.status,duration(d.durationMs),time,d.model,d.effort].filter(Boolean).join(' · ')));
      if(d.turnStartedAtMs){const stamp=el('time','mobile-turn-time',new Date(d.turnStartedAtMs).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}));stamp.dateTime=new Date(d.turnStartedAtMs).toISOString();row.append(stamp);}
      return row;
    }
    if(['userMessage','steeringUserMessage','agentMessage'].includes(item.type)){
      const user=item.type!=='agentMessage', article=el('article','message '+(user?'user':'assistant')+(item.phase==='commentary'?' commentary':''));
      const head=el('div','message-head');head.append(el('span','role',user?'你':item.phase==='commentary'?'Codex · 进度':'Codex'),copyButton(item.text||''));
      const parts=item.data?.content||item.data?.input||[];
      const nativeImages=new Set(parts.filter(p=>p.type==='localImage').map(p=>p.path));
      const refs=(item.artifacts||[]).filter(ref=>!nativeImages.has(ref.path));
      const pictures=el('div','message-images');
      for(const part of parts)if(part.type==='image'||part.type==='localImage')picture(pictures,part);
      artifacts({...item,artifacts:refs.filter(ref=>ref.kind==='image')},pictures);
      article.append(head);
      if(pictures.childNodes.length)article.append(pictures);
      article.append(el('div','text',user?(item.displayText??item.text??''):displayText(item)));
      artifacts({...item,artifacts:refs.filter(ref=>ref.kind!=='image')},article);
      for(const question of item.asyncQuestions||[])questionCard(question,article);
      for(const part of parts)if(!['image','localImage','text'].includes(part.type))article.append(block('附件 / 引用 · '+part.type,part));
      const extra={...item.data};delete extra.text;delete extra.content;delete extra.input;delete extra.phase;delete extra.questions;delete extra.delivery;
      if(Object.values(extra).some(v=>v!==null && v!==undefined)){
        const info=el('details','raw-event');info.dataset.key=item.id+':extra';info.append(el('summary','','引用与消息详情'),block('消息信息',extra));article.append(info);
      }
      return article;
    }
    if(item.artifacts?.length){const output=el('article','message assistant'),pictures=el('div','message-images');artifacts({...item,artifacts:item.artifacts.filter(ref=>ref.kind==='image')},pictures);if(pictures.childNodes.length)output.append(pictures);artifacts({...item,artifacts:item.artifacts.filter(ref=>ref.kind!=='image')},output);return output;}
    const card=el('details','activity'+(item.status==='inProgress'?' running':'')+(item.status==='failed'?' failed':''));
    card.dataset.key=item.id;card.open=expanded;
    const summary=el('summary','activity-summary');
    const icon=el('span','activity-icon',item.type==='contextCompaction'?'⇣':item.type==='reasoning'?'◌':item.type==='fileChange'?'±':'›_');
    const title=el('span','activity-title',item.title);
    summary.append(icon,title);
    card.append(summary,details(item));return card;
  }
  function render(data, container, loadImage) {
    imageObserver?.disconnect();
    const focused=document.activeElement;
    const editing=focused?.dataset?.questionKey?{key:focused.dataset.questionKey,start:focused.selectionStart,end:focused.selectionEnd}:null;
    current={data,container,loadImage};
    const open=new Map([...container.querySelectorAll('details[data-key]')].map(n=>[n.dataset.key,n.open]));
    const viewport=container.closest('.mobile-chat-scroll')||container;
    const atBottom=viewport.scrollHeight-viewport.scrollTop-viewport.clientHeight<100, scroll=viewport.scrollTop;
    const all=data.timeline||data.messages.map(m=>({id:m.id,type:m.role==='user'?'userMessage':'agentMessage',text:m.text,phase:m.phase,data:{}}));
    const fragment=document.createDocumentFragment();
    const nextEntries=new Map();
    if(data.historyWindow?.hasMore&&loadEarlier){
      const more=el('button','history-more','加载更早记录');
      more.disabled=expandingHistory;
      more.onclick=async()=>{expandingHistory=true;more.disabled=true;visible+=120;try{await loadEarlier();}finally{expandingHistory=false;more.disabled=false;}};
      fragment.append(more);
    }
    function renderEntry(item){
      const cached=entryCache.get(item.id),signature=cached?.item===item?cached.signature:JSON.stringify(item);
      // Question controls depend on current authorization as well as item content.
      const reusable=!(item.asyncQuestions?.length);
      const node=reusable&&cached?.signature===signature?cached.node:entry(item);
      nextEntries.set(item.id,{signature,node,item});return node;
    }
    if(all.length>visible){const more=el('button','history-more','显示更早记录（还有 '+(all.length-visible)+' 条）');more.onclick=()=>{
      const oldHeight=viewport.scrollHeight;visible+=120;render(data,container,loadImage);viewport.scrollTop=scroll+viewport.scrollHeight-oldHeight;
    };fragment.append(more);}
    let group=null;
    for(const item of all.slice(-visible)){
      const activity=item.type!=='turn'&&!['userMessage','steeringUserMessage','agentMessage','error'].includes(item.type)&&!item.artifacts?.length;
      if(activity){
        if(!group){group=el('details','activity-group');group.dataset.key=item.id+':group';group.open=expanded;const summary=el('summary');summary.append(el('span','activity-icon','›_'),el('span','activity-group-label'));group.append(summary);fragment.append(group);}
        group.append(renderEntry(item));
        group.firstChild.querySelector('.activity-group-label').textContent='执行活动 · '+(group.children.length-1)+' 项';
      }else{group=null;fragment.append(renderEntry(item));}
    }
    if(!all.length)fragment.append(typeof viewState==='function'?viewState(data.syncing?'正在同步会话…':'暂无会话记录',{loading:data.syncing===true,symbol:'chat'}):el('div','empty-small',data.syncing?'正在同步会话…':'暂无会话记录。'));
    container.replaceChildren(fragment);
    entryCache=nextEntries;
    if(editing){const input=[...container.querySelectorAll('[data-question-key]')].find(n=>n.dataset.questionKey===editing.key);if(input&&!input.disabled){input.focus({preventScroll:true});input.setSelectionRange(editing.start,editing.end);}}
    imageObserver=new IntersectionObserver(entries=>{for(const entry of entries)if(entry.isIntersecting){imageObserver.unobserve(entry.target);entry.target.loadImage();}},{root:viewport,rootMargin:'300px'});
    for(const frame of container.querySelectorAll('.message-picture'))if(frame.loadImage)imageObserver.observe(frame);
    for(const n of container.querySelectorAll('details[data-key]'))if(open.has(n.dataset.key))n.open=open.get(n.dataset.key);
    viewport.scrollTop=atBottom||!container.dataset.loaded?viewport.scrollHeight:scroll;container.dataset.loaded='true';
    const runtime=data.runtime||{type:'unknown'}, meta=data.metadata||{};
    const activeItems=all.filter(i=>i.status==='inProgress'&&i.type!=='turn');
    const latest=activeItems.at(-1);
    const elapsed=(data.earlierDurationMs||0)+all.filter(i=>i.type==='turn').reduce((sum,i)=>sum+(Number.isFinite(i.data?.durationMs)?i.data.durationMs:i.status==='inProgress'&&i.data?.turnStartedAtMs?Math.max(0,Date.now()-i.data.turnStartedAtMs):0),0);
    document.getElementById(ids.runtime).textContent=[elapsed?'已执行 '+duration(elapsed):'',data.status?.label||labels[runtime.type]||runtime.type,
      runtime.type==='active'&&latest?latest.title:'',meta.latestModel,
      data.pendingRequests?.length?'有 '+data.pendingRequests.length+' 项待处理请求':''].filter(Boolean).join(' · ');
    const warnings=[];
    if(data.syncing)warnings.push('已显示本地记录，正在同步原生历史');
    if(data.truncated)warnings.push('原生历史未完整加载');
    if(!data.timeline)warnings.push('旧历史回退：仅文字记录');
    if(data.coverage?.unsupportedTypes?.length)warnings.push('未适配事件：'+data.coverage.unsupportedTypes.join('、'));
    document.getElementById(ids.source).textContent=warnings.length?warnings.join('；'):'已同步原生记录';
    const info=document.getElementById(ids.info);
    info.replaceChildren(block('会话信息',{...meta,runtime,pendingRequests:data.pendingRequests||[],coverage:data.coverage||{}}));
  }
  function setExpanded(value){expanded=value;if(current){for(const d of current.container.querySelectorAll('details.activity, details.activity-group'))d.open=value;}}
  function reset(){for(const state of questionState.values())clearTimeout(state.timer);questionState.clear();imageObserver?.disconnect();imageCache.clear();entryCache.clear();visible=120;current=null;expanded=false;document.getElementById(ids.runtime).textContent='';document.getElementById(ids.info).replaceChildren();}
  return {render,reset,setExpanded,configureQuestions,configureHistory};
 }
 return {...create(),create};
})();
