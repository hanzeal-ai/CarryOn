import React from "react";
import {createRoot} from "react-dom/client";
import {flushSync} from "react-dom";
import {Button} from "./components/ui/button";
import {Input} from "./components/ui/input";
import {Textarea} from "./components/ui/textarea";
import "./index.css";

const ATTRIBUTE_PROPS={
  "accept-charset":"acceptCharset",
  "autocapitalize":"autoCapitalize",
  "autocomplete":"autoComplete",
  "autofocus":"autoFocus",
  "class":"className",
  "for":"htmlFor",
  "formaction":"formAction",
  "formenctype":"formEncType",
  "formmethod":"formMethod",
  "formnovalidate":"formNoValidate",
  "formtarget":"formTarget",
  "maxlength":"maxLength",
  "minlength":"minLength",
  "readonly":"readOnly",
  "spellcheck":"spellCheck",
  "tabindex":"tabIndex",
};
const BOOLEAN_ATTRIBUTES=new Set([
  "autofocus","disabled","formnovalidate","hidden","multiple","readonly","required",
]);
const NUMERIC_ATTRIBUTES=new Set(["cols","maxlength","minlength","rows","size","tabindex"]);
const CHECKABLE_TYPES=new Set(["checkbox","radio"]);

const copyAttributes=element=>{
  const props={};
  for(const attribute of element.attributes){
    const name=attribute.name.toLowerCase();
    if(name==="value"||name==="checked")continue;
    const prop=ATTRIBUTE_PROPS[name]||attribute.name;
    if(BOOLEAN_ATTRIBUTES.has(name))props[prop]=true;
    else if(NUMERIC_ATTRIBUTES.has(name))props[prop]=Number(attribute.value);
    else props[prop]=attribute.value;
  }
  return props;
};
const mount=(element,Component,props)=>{
  const state={
    active:document.activeElement===element,
    autoFocus:"autofocus" in element?element.autofocus:undefined,
    checked:"checked" in element?element.checked:undefined,
    defaultChecked:"defaultChecked" in element?element.defaultChecked:undefined,
    defaultValue:"defaultValue" in element?element.defaultValue:undefined,
    indeterminate:"indeterminate" in element?element.indeterminate:undefined,
    selectionEnd:"selectionEnd" in element?element.selectionEnd:null,
    selectionStart:"selectionStart" in element?element.selectionStart:null,
    value:"value" in element?element.value:undefined,
  };
  const host=document.createElement("div");
  const root=createRoot(host);
  flushSync(()=>root.render(<Component {...props}/>));
  const rendered=host.firstElementChild;
  if(!rendered||host.childElementCount!==1)throw new Error(`shadcn mount failed for ${element.tagName}`);
  const replacement=rendered.cloneNode(true);
  root.unmount();
  element.replaceWith(replacement);
  if(state.value!==undefined&&replacement.type!=="file"&&(replacement.tagName==="INPUT"||replacement.tagName==="TEXTAREA"))replacement.value=state.value;
  if(state.defaultValue!==undefined){
    if(element.tagName==="TEXTAREA"||element.hasAttribute("value"))replacement.defaultValue=state.defaultValue;
    else replacement.removeAttribute("value");
  }
  if(state.checked!==undefined){replacement.defaultChecked=state.defaultChecked;replacement.checked=state.checked;}
  if(state.indeterminate!==undefined)replacement.indeterminate=state.indeterminate;
  if(state.autoFocus!==undefined)replacement.autofocus=state.autoFocus;
  if(state.active){
    replacement.focus({preventScroll:true});
    if(state.selectionStart!==null&&replacement.setSelectionRange)replacement.setSelectionRange(state.selectionStart,state.selectionEnd);
  }
  return replacement;
};
for(const element of [...document.querySelectorAll("button")]){
  const attrs=copyAttributes(element);
  const variant=element.classList.contains("primary")?"default":element.classList.contains("danger-text")?"destructive":element.classList.contains("quiet")?"ghost":"outline";
  const size=element.classList.contains("copy")?"sm":"default";
  mount(element,Button,{...attrs,variant,size,dangerouslySetInnerHTML:{__html:element.innerHTML}});
}
for(const element of [...document.querySelectorAll("input")]){
  const attrs=copyAttributes(element);
  if(element.hasAttribute("value")&&element.type!=="file")attrs.defaultValue=element.defaultValue;
  if(CHECKABLE_TYPES.has(element.type)&&element.hasAttribute("checked"))attrs.defaultChecked=element.defaultChecked;
  mount(element,Input,attrs);
}
for(const element of [...document.querySelectorAll("textarea")]){
  const attrs=copyAttributes(element);
  if(element.defaultValue)attrs.defaultValue=element.defaultValue;
  mount(element,Textarea,attrs);
}
document.documentElement.dataset.shadcn="mounted";
