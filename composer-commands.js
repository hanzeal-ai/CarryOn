'use strict';
const ComposerCommands=(()=>{
  const definitions=[['side','临时聊天','side-create','create'],['plan','计划模式','settings','edit'],['review','审查代码','review','send'],['compact','压缩上下文','compact','edit'],['fork','分叉会话','fork','create'],['goal','会话目标','goal-set','send'],['model','模型与思考强度','settings','edit'],['status','会话信息',null,null]];
  function parse(text){const match=/^\/([a-z][a-z-]*)(?:\s+([\s\S]*))?$/.exec(text.trim());return match?{name:match[1],argument:(match[2]||'').trim()}:null;}
  function available(name,context){
    const entry=definitions.find(item=>item[0]===name);if(!entry)return false;
    const history=context.history(),controls=history?.controls;
    if(["review","fork","compact"].includes(name)&&history?.status?.state!=='idle')return false;
    return !!controls&&(!entry[2]||controls.supportedOperations?.includes(entry[2]))&&(!entry[3]||context.allowed(entry[3]))&&(name!=='plan'||controls.supportedSettings?.includes('collaborationMode'));
  }
  async function run(text,context){
    const command=parse(text);if(!command)return false;
    if(context.hasAttachments()){context.notice('此命令不接受图片、引用或评论，请先处理附件');return true;}
    if(!available(command.name,context)){context.notice('当前原生连接未提供此命令：/'+command.name);return true;}
    const {name,argument}=command;
    if(['plan','side'].includes(name)&&argument&&!context.allowed('send')){context.notice('工作区未授权发送任务');return true;}
    if(['compact','fork','model','status'].includes(name)&&argument){context.notice('/'+name+' 不接受参数');return true;}
    try{
      if(name==='side'){await context.side(argument);return true;}
      if(name==='fork'){await context.fork();return true;}
      if(['review','model','status'].includes(name)||name==='goal'&&!argument){context.open(name,argument);context.clear();return true;}
      const history=context.history();
      if(name==='compact'&&(history.status?.state!=='idle'||history.controls.requests?.length||history.queue?.messages?.length))throw Error('请等待会话空闲并处理排队任务与审批');
      let action=name,fields={};
      if(name==='plan'){
        const settings=history.controls.settings,model=settings?.model||history.metadata?.latestModel,effort=settings?.effort??history.metadata?.latestReasoningEffort??null;
        if(!model)throw Error('原生会话尚未提供当前模型');
        action='settings';fields={settings:{collaborationMode:{mode:!argument&&settings?.collaborationMode?.mode==='plan'?'default':'plan',settings:{...settings?.collaborationMode?.settings,model,reasoning_effort:effort,developer_instructions:settings?.collaborationMode?.settings?.developer_instructions??null}}}};
      }else if(name==='goal'){if(history.controls.goalUnknown)throw Error('请先核对原生目标状态');action='goal-set';fields={objective:argument,status:'active'};}
      const job=await context.operation(action,fields);
      if(!context.current())return true;
      if(job.state!=='completed')throw Error(job.error||'操作结果尚未确认，请核对原请求');
      if(name==='plan'&&argument)context.continueWith(argument);else context.clear();
    }catch(error){if(context.current())context.notice(error.message);}
    return true;
  }
  function mount(input,host,context,choose){
    const menu=document.createElement('div');menu.className='composer-command-menu';menu.hidden=true;menu.setAttribute('role','listbox');menu.setAttribute('aria-label','会话命令');host.append(menu);
    let selected=0;
    function mark(){const buttons=[...menu.children];buttons.forEach((button,index)=>button.setAttribute('aria-selected',String(index===selected)));buttons[selected]?.scrollIntoView({block:'nearest'});}
    function refresh(){const query=/^\/([a-z]*)$/.exec(input.wireText.trim());menu.replaceChildren();selected=0;menu.hidden=!query||context.hasAttachments();if(menu.hidden)return;
      for(const [name,label] of definitions){if(!name.startsWith(query[1])||!available(name,context))continue;const button=document.createElement('button');button.type='button';button.setAttribute('role','option');button.textContent='/'+name+' · '+label;button.onclick=()=>choose(name);menu.append(button);}
      menu.hidden=!menu.childElementCount;if(!menu.hidden)mark();
    }
    input.addEventListener('keydown',event=>{
      if(menu.hidden||event.isComposing||event.metaKey||event.ctrlKey||event.altKey)return;
      if(event.key==='Escape'){menu.hidden=true;event.preventDefault();return;}
      if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();selected=(selected+(event.key==='ArrowDown'?1:-1)+menu.childElementCount)%menu.childElementCount;mark();}
      else if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();menu.children[selected]?.click();}
    });
    input.addEventListener('input',refresh);return {refresh};
  }
  return {parse,run,mount,available};
})();
if(typeof module!=='undefined')module.exports=ComposerCommands;
