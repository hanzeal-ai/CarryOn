'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const commands=require('../composer-commands.js');
function fixture(){
 const events=[];const history={status:{state:'idle'},controls:{supportedOperations:['settings','side-create','review','compact','fork','goal-set'],supportedSettings:['collaborationMode'],settings:{model:'native-model',effort:'high',collaborationMode:{mode:'default',settings:{developer_instructions:'retain'}}},requests:[]},queue:{messages:[]}};
 const context={history:()=>history,allowed:()=>true,current:()=>true,hasAttachments:()=>false,notice:value=>events.push(['notice',value]),clear:()=>events.push(['clear']),open:(...args)=>events.push(['open',...args]),side:async text=>events.push(['side',text]),fork:async()=>events.push(['fork']),operation:async(action,fields)=>{events.push(['operation',action,fields]);return {state:'completed'};},continueWith:text=>events.push(['continue',text])};
 return {events,history,context};
}
test('file paths and ordinary text stay ordinary; unsupported command is explicit',async()=>{
 assert.equal(commands.parse('/usr/local'),null);assert.equal(commands.parse('explain /review'),null);
 const {context,events}=fixture();assert.equal(await commands.run('/unknown value',context),true);assert.equal(events[0][0],'notice');assert.equal(events.length,1);
});
test('plan uses native current model and preserves nested instruction before continuing',async()=>{
 const {context,events}=fixture();await commands.run('/plan inspect the code',context);
 assert.deepEqual(events,[['operation','settings',{settings:{collaborationMode:{mode:'plan',settings:{developer_instructions:'retain',model:'native-model',reasoning_effort:'high'}}}}],['continue','inspect the code']]);
});
test('failed or unknown native plan does not submit continuation or clear command',async()=>{
 for(const state of ['uncertain','failed']){const {context,events}=fixture();context.operation=async()=>({state,error:'pending'});await commands.run('/plan work',context);assert.deepEqual(events,[['notice','pending']]);}
});
test('revoked ability and attachments prevent any native operation',async()=>{
 const {context,history,events}=fixture();history.controls.supportedOperations=[];await commands.run('/compact',context);assert.equal(events.length,1);assert.equal(events[0][0],'notice');
 events.length=0;history.controls.supportedOperations=['compact'];context.hasAttachments=()=>true;await commands.run('/compact',context);assert.equal(events.length,1);assert.equal(events[0][0],'notice');
});
test('compact never runs over queued work; goal routes directly to native goal',async()=>{
 const {context,history,events}=fixture();history.queue.messages=[{id:'pending'}];await commands.run('/compact',context);assert.equal(events[0][0],'notice');
 events.length=0;await commands.run('/goal finish and review',context);assert.deepEqual(events,[['operation','goal-set',{objective:'finish and review',status:'active'}],['clear']]);
});
test('picker commands do not start model tasks; side and fork use existing boundaries',async()=>{
 const {context,events}=fixture();await commands.run('/review inspect boundaries',context);assert.deepEqual(events,[['open','review','inspect boundaries'],['clear']]);
 events.length=0;await commands.run('/side discuss this',context);assert.deepEqual(events,[['side','discuss this']]);
 events.length=0;await commands.run('/fork',context);assert.deepEqual(events,[['fork']]);
});
test('late completion after scope changes cannot clear or continue another draft',async()=>{
 const {context,events}=fixture();context.operation=async()=>{context.current=()=>false;return {state:'completed'};};await commands.run('/plan new task',context);assert.deepEqual(events,[]);
});

test('bare plan toggles current native mode; a plan body always enters plan',async()=>{
 const {context,history,events}=fixture();history.controls.settings.collaborationMode.mode='plan';
 await commands.run('/plan',context);
 assert.equal(events[0][2].settings.collaborationMode.mode,'default');assert.deepEqual(events.at(-1),['clear']);
 events.length=0;await commands.run('/plan inspect',context);
 assert.equal(events[0][2].settings.collaborationMode.mode,'plan');assert.deepEqual(events.at(-1),['continue','inspect']);
});
