/* Structured references live in the editable document, never in pasted HTML. */
const ComposerReferenceIcon = {
  create(reference){
    let png=false;
    if(reference.iconData&&reference.iconData.length<=87384&&/^[A-Za-z0-9+/]+={0,2}$/.test(reference.iconData)){
      try{const header=atob(reference.iconData.slice(0,44));const dimension=offset=>[...header.slice(offset,offset+4)].reduce((value,byte)=>value*256+byte.charCodeAt(0),0);png=header.startsWith('\x89PNG\r\n\x1a\n')&&header.slice(12,16)==='IHDR'&&dimension(16)>0&&dimension(16)<=512&&dimension(20)>0&&dimension(20)<=512;}catch{}
    }
    if(png){
      const raster=document.createElement('img');raster.src='data:image/png;base64,'+reference.iconData;raster.alt='';raster.setAttribute('aria-hidden','true');raster.onerror=()=>raster.replaceWith(this.create({path:reference.path}));return raster;
    }
    const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('aria-hidden','true');
    const outline=document.createElementNS(icon.namespaceURI,'path');outline.setAttribute('d',/^(app|plugin):\/\//.test(reference.path)?'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z':'M12 2 3 7v10l9 5 9-5V7z M3 7l9 5 9-5 M12 12v10 M7.5 4.5l9 5');icon.append(outline);return icon;
  }
};

class CarryOnComposer extends HTMLElement {
  static observedAttributes=['disabled','placeholder'];
  constructor(){
    super();this._text='';this._references=[];this._knownReferences=new Map();this._caret=0;this._editor=document.createElement('div');
    this.addEventListener('input',()=>this.readDocument());
    this.addEventListener('compositionstart',event=>{if(event.target===this._editor)this._composing=true;});
    this.addEventListener('compositionend',event=>{if(event.target!==this._editor)return;this._composing=false;this.readDocument();if(this._pendingReferences){const values=this._pendingReferences;this._pendingReferences=null;this.references=values;this.dispatchEvent(new Event('input',{bubbles:true}));}});
    this.addEventListener('focusin',event=>{if(event.target===this._editor&&this._restoreOnFocus){this._restoreOnFocus=false;const selection=getSelection();if(!selection||selection.isCollapsed||!this._editor.contains(selection.anchorNode))this.restoreCaret();}});
    this.addEventListener('keyup',()=>this.rememberCaret());
    this.addEventListener('mouseup',()=>this.rememberCaret());
    this.addEventListener('blur',()=>this.rememberCaret());
    this.addEventListener('paste',event=>{
      if([...event.clipboardData.items].some(item=>item.kind==='file'))return;
      event.preventDefault();
      const text=event.clipboardData.getData('text/plain').replaceAll('\ufffc','');
      this.insertText(text);
    });
    this.addEventListener('drop',event=>{
      event.preventDefault();if(this.disabled)return;
      const point=document.caretRangeFromPoint?.(event.clientX,event.clientY);
      if(point&&this._editor.contains(point.startContainer)){const selection=getSelection();selection.removeAllRanges();selection.addRange(point);}
      this.insertText(event.dataTransfer.getData('text/plain').replaceAll('\ufffc',''));
    });
    this.addEventListener('copy',event=>this.copySelection(event,false));
    this.addEventListener('cut',event=>this.copySelection(event,true));
    this.addEventListener('beforeinput',event=>{
      if(this.disabled){event.preventDefault();return;}
      if(event.inputType==='insertParagraph'){event.preventDefault();this.insertText('\n');}
    });
  }
  connectedCallback(){this.replaceChildren(this._editor);this.attributeChangedCallback();this.render();}
  attributeChangedCallback(){if(this._editor.contentEditable!==String(!this.disabled))this._editor.contentEditable=String(!this.disabled);this._editor.setAttribute('role','textbox');this._editor.setAttribute('aria-multiline','true');this._editor.setAttribute('aria-disabled',String(this.disabled));this._editor.setAttribute('aria-label',this.placeholder||'消息');this._editor.setAttribute('data-placeholder',this.placeholder);}
  focus(options){this._editor.focus(options);if(this._restoreOnFocus){this._restoreOnFocus=false;this.restoreCaret();}}
  get disabled(){return this.hasAttribute('disabled');}
  set disabled(value){this.toggleAttribute('disabled',!!value);}
  get placeholder(){return this.getAttribute('placeholder')||'';}
  set placeholder(value){this.setAttribute('placeholder',value);}
  get value(){return this._text;}
  set value(value){this._text=String(value);this._references=this._references.filter(r=>this._text[r.offset]==='\ufffc');this._caret=Math.min(this._caret,this._text.length);this.render();}
  setDocument(text,references=[],caret=0,scope=null){
    // Detached editing hosts cannot deliver a late composition into another draft.
    this._editor.blur();this._composing=false;this._editor=document.createElement('div');this.replaceChildren(this._editor);this.attributeChangedCallback();
    this._pendingReferences=null;this._scope=scope;this._text=String(text);
    const occupied=new Set();
    this._references=references.filter(r=>Number.isInteger(r.offset)&&this._text[r.offset]==='\ufffc'&&!occupied.has(r.offset)&&occupied.add(r.offset)).map(r=>({...r}));
    this._knownReferences=new Map(this._references.map(r=>[JSON.stringify([r.name,r.path]),{name:r.name,path:r.path,...(r.displayName?{displayName:r.displayName}:{}),...(r.iconData?{iconData:r.iconData}:{})}]));
    this._restoreOnFocus=true;this._caret=Math.max(0,Math.min(caret,this._text.length));this._rendered=null;this.render();
  }
  get caret(){this.rememberCaret();return this._caret;}
  get wireText(){return this._text.replaceAll('\ufffc','');}
  get references(){return this._references.map(reference=>({...reference}));}
  set references(values){
    const identity=reference=>JSON.stringify([reference.name,reference.path]);
    if(this._composing){if(JSON.stringify(values.map(identity))!==JSON.stringify(this._references.map(identity)))this._pendingReferences=values;return;}
    const desired=new Set(values.map(identity));
    for(const reference of [...this._references].sort((a,b)=>b.offset-a.offset)){
      if(!desired.has(identity(reference)))this.replaceRange(reference.offset,1,'',false);
    }
    const references=[];
    for(const reference of values){
      let offset=this._references.find(r=>identity(r)===identity(reference))?.offset;
      if(!Number.isInteger(offset)||this._text[offset]!=='\ufffc'||references.some(r=>r.offset===offset)){
        offset=this._caret;this.replaceRange(offset,0,'\ufffc',false);
        for(const existing of references)if(existing.offset>=offset)existing.offset++;
        this._caret=offset+1;
      }
      references.push({name:reference.name,path:reference.path,...(reference.displayName?{displayName:reference.displayName}:{}),...(reference.iconData?{iconData:reference.iconData}:{}),offset});
    }
    this._references=references;for(const r of references)this._knownReferences.set(identity(r),{name:r.name,path:r.path,...(r.displayName?{displayName:r.displayName}:{}),...(r.iconData?{iconData:r.iconData}:{})});this.render();
  }
  readNodes(root,display=false){
    let text='',references=[];
    const walk=node=>{
      if(node.nodeType===Node.TEXT_NODE){text+=node.textContent;return;}
      if(node.nodeType!==Node.ELEMENT_NODE&&node.nodeType!==Node.DOCUMENT_FRAGMENT_NODE)return;
      if(node.dataset?.reference!==undefined){
        const reference=this._knownReferences.get(node.dataset.reference);
        if(reference){references.push({...reference,offset:text.length});text+=display?(reference.displayName||reference.name):'\ufffc';}return;
      }
      if(node.nodeName==='BR'){text+='\n';return;}
      if((node.nodeName==='DIV'||node.nodeName==='P')&&text&&!text.endsWith('\n'))text+='\n';
      for(const child of node.childNodes)walk(child);
    };
    for(const child of root.childNodes)walk(child);
    return {text,references};
  }
  readDocument(){
    const value=this.readNodes(this._editor);this._text=value.text;this._references=value.references;this.rememberCaret();this._rendered=JSON.stringify([this._text,this._references]);
  }
  rememberCaret(){
    const selection=getSelection();if(!selection?.rangeCount||!this.contains(selection.anchorNode))return;
    const range=document.createRange();range.selectNodeContents(this._editor);range.setEnd(selection.anchorNode,selection.anchorOffset);
    this._caret=this.readNodes(range.cloneContents()).text.length;
  }
  selectionOffsets(){
    const selection=getSelection();if(!selection?.rangeCount)return {start:this._caret,length:0};
    const selected=selection.getRangeAt(0);if(!this.contains(selected.commonAncestorContainer))return {start:this._caret,length:0};
    const prefix=document.createRange();prefix.selectNodeContents(this._editor);prefix.setEnd(selected.startContainer,selected.startOffset);
    return {start:this.readNodes(prefix.cloneContents()).text.length,length:this.readNodes(selected.cloneContents()).text.length};
  }
  copySelection(event,cut){
    const selection=getSelection();if(!selection?.rangeCount)return;
    event.preventDefault();event.clipboardData.setData('text/plain',this.readNodes(selection.getRangeAt(0).cloneContents(),true).text);
    if(cut&&!this.disabled)this.insertText('');
  }
  replaceRange(start,length,text,emit=true){
    this._references=this._references.filter(r=>r.offset<start||r.offset>=start+length).map(r=>({...r,offset:r.offset>=start+length?r.offset+text.length-length:r.offset}));
    this._text=this._text.slice(0,start)+text+this._text.slice(start+length);this._caret=start+text.length;
    if(emit){this.render(true);this.dispatchEvent(new Event('input',{bubbles:true}));}
  }
  insertText(text){if(this.disabled)return;const range=this.selectionOffsets();this.replaceRange(range.start,range.length,text);}
  render(focus=false){
    if(this._composing)return;
    const signature=JSON.stringify([this._text,this._references]);
    if(!focus&&this._rendered===signature)return;this._rendered=signature;
    const references=new Map(this._references.map((r,index)=>[r.offset,{...r,index}]));
    this._editor.replaceChildren();let start=0;
    for(let offset=0;offset<this._text.length;offset++){
      const reference=references.get(offset);if(!reference)continue;
      this._editor.append(document.createTextNode(this._text.slice(start,offset)));
      const token=document.createElement('span');token.className='inline-reference';token.contentEditable='false';token.dataset.reference=JSON.stringify([reference.name,reference.path]);
      token.append(ComposerReferenceIcon.create(reference));
      token.append(document.createTextNode(reference.displayName||reference.name));token.setAttribute('aria-label',reference.displayName||reference.name);this._editor.append(token);start=offset+1;
    }
    this._editor.append(document.createTextNode(this._text.slice(start)));
    if(focus){this.focus();this.restoreCaret();}
  }
  restoreCaret(){
    let remaining=this._caret;
      for(const node of this._editor.childNodes){const length=node.nodeType===Node.TEXT_NODE?node.length:1;
        if(remaining<=length){const range=document.createRange();if(node.nodeType===Node.TEXT_NODE)range.setStart(node,remaining);else if(remaining)range.setStartAfter(node);else range.setStartBefore(node);range.collapse(true);const selection=getSelection();selection.removeAllRanges();selection.addRange(range);break;}remaining-=length;
      }
  }
}
customElements.define('carryon-composer',CarryOnComposer);
