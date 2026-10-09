// Run the shipped cancellation and reporting screens against controlled owner responses.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import vm from 'node:vm';

const sources=Object.fromEntries(await Promise.all(['field_execution','field_reporting'].map(async name=>[name,{
 js:await readFile(new URL(`../utilsim/world/${name}.js`,import.meta.url),'utf8'),
 html:await readFile(new URL(`../utilsim/world/${name}.html`,import.meta.url),'utf8')}])));
const assignment=(id,operation='repair-water-main')=>({assignmentId:id,operation,assetId:'saved-main',crewId:'main-crew',orderId:'local-'+id,
 orderRevision:1,scheduledDate:'2026-01-02',reportDelayDays:2,predecessorAssignmentId:'isolation'});
const row=(id,descendants=[],changes={})=>({assignment:assignment(id),state:'accepted',result:null,messages:[],phase:{predecessorAssignmentId:'isolation'},
 lifecycle:{revision:0,cancelledDate:null,reason:null,replacementAssignmentId:null,replacesAssignmentId:null,pendingDescendantIds:descendants,descendantsTruncated:false,canCancel:true,canReplace:false},...changes});
const cancelled=(id='repair')=>row(id,[],{state:'cancelled',lifecycle:{revision:1,cancelledDate:'2026-01-03',reason:'Retire blocked phase',
 replacementAssignmentId:null,replacesAssignmentId:null,pendingDescendantIds:[],descendantsTruncated:false,canCancel:false,canReplace:true}});
const decode=value=>value.replaceAll('&amp;','&').replaceAll('&lt;','<').replaceAll('&gt;','>').replaceAll('&quot;','"').replaceAll('&#39;',"'");
function element(initial=''){
 let value=initial,html='';
 const e={disabled:false,hidden:false,checked:false,textContent:'',className:'',dataset:{},options:[],multiple:false,
  append(option){this.options.push(option);option.remove=()=>{this.options=this.options.filter(x=>x!==option);};}};
 Object.defineProperties(e,{value:{get:()=>value,set:v=>{value=v;}},innerHTML:{get:()=>html,set:v=>{
  html=v;if(!v.includes('<option'))return;
  e.options=[...v.matchAll(/<option value="([^"]*)"([^>]*)>/g)].map(m=>({value:decode(m[1]),selected:m[2].includes('selected')}));
  if(!e.multiple)value=e.options.find(o=>o.selected)?.value||e.options[0]?.value||'';
 }},selectedOptions:{get:()=>e.options.filter(o=>o.selected)}});return e;
}
async function screen({items=[row('repair',['restore']),row('restore')],storage=new Map(),nextAfter=null,page='field_execution',initialReadError=null}={}){
 const {js,html}=sources[page],elements=Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],element()]));
 if(page==='field_execution'){
  elements.cancelAssignments.multiple=true;
  const weekdays=element();for(const value of ['0,1,2,3,4','0,1,2,3,4,5,6',''])weekdays.append(element(value));
  elements.crew.elements={crewId:element('main-crew'),dailyCapacity:element('1'),weekdays,
   ...Object.fromEntries(['skillPlumbing','skillElectric','skillGas','skillSewer','skillWaterMain'].map(n=>[n,element()]))};
  elements.assignment.elements=Object.fromEntries(Object.entries({...assignment('new'),scheduledDate:'2026-01-03'}).map(([k,v])=>[k,element(v)]));
 }else elements.claimedOutcome.value='completed';
 const posted=[],paths=[],reads=[];let mode='ok',readError=initialReadError,uuid=0;
 let record={schemaVersion:'field-reporting/1',environmentId:'TEST',worldFingerprint:'saved-world',ownerId:'field-owner',actorId:'world-admin',
  through:'2026-01-03',crews:[{id:'main-crew',revision:1,skills:['water-main'],daily_capacity:1,weekdays:[0,1,2,3,4]}],items,nextAfter};
 const context=vm.createContext({AbortController,setTimeout:()=>1,clearTimeout(){},
  document:{getElementById:id=>elements[id],querySelectorAll:()=>[...Object.values(elements),...Object.values(elements.crew?.elements||{}),...Object.values(elements.assignment?.elements||{})],createElement:()=>element()},
  sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>{if(mode==='storage-fail')throw Error('Storage unavailable');storage.set(k,v);},removeItem:k=>storage.delete(k)},
  crypto:{randomUUID:()=>`command-${++uuid}`},fetch:async(path,options)=>{
   if(options?.method==='POST'){
    posted.push(JSON.parse(options.body));paths.push(path);
    if(mode==='lost')throw Error('Lost reply');
    if(mode==='reject')return {ok:false,status:422,json:async()=>({error:'Physical visit already committed.'})};
    return {ok:true,status:200,json:async()=>({status:'completed'})};
   }
   reads.push(path);if(readError)throw Error(readError);return {ok:true,status:200,json:async()=>structuredClone(record)};
  }});
 await new vm.Script(`(async()=>{${js}\n})()`).runInContext(context);
 return {elements,posted,paths,reads,storage,setMode(value){mode=value;},setReadError(value){readError=value;},setRecord(value){record={...record,...value};},
  async click(id){await elements[id].onclick();},select(ids){for(const option of elements.cancelAssignments.options)option.selected=ids.includes(option.value);elements.cancelAssignments.onchange();},
  async accept(){await elements.assignment.onsubmit({preventDefault(){},target:elements.assignment});},
  async configure(){await elements.policyForm.onsubmit({preventDefault(){}});},async submit(){await elements.reportForm.onsubmit({preventDefault(){}});}};
}

test('cancellation requires explicit descendants and reason, then sends exact revisioned selection',async()=>{
 const ui=await screen();ui.select(['repair']);assert.equal(ui.elements.cancelSelected.disabled,true);
 assert.match(ui.elements.cancelRequirements.textContent,/Also select pending descendants: restore/);
 await ui.click('cancelSelected');assert.equal(ui.posted.length,0);
 ui.select(['repair','restore']);await ui.click('cancelSelected');assert.equal(ui.posted.length,0);
 ui.elements.lifecycleReason.value='Retire blocked descendants';await ui.click('cancelSelected');
 assert.equal(ui.paths[0],'/api/field-assignment-lifecycle');
 assert.deepEqual(ui.posted[0],{schemaVersion:'field-assignment-lifecycle/1',commandId:'command-1',environmentId:'TEST',worldFingerprint:'saved-world',actorId:'world-admin',
  effectiveDate:'2026-01-03',causalReference:'local-field-admin',action:'cancel',assignmentIds:['repair','restore'],expectedRevisions:{repair:0,restore:0},reason:'Retire blocked descendants'});
});

test('explicit descendant selection spans bounded pages without assuming one page is the chain',async()=>{
 const ui=await screen({items:[row('repair',['restore'])],nextAfter:25});ui.select(['repair']);
 ui.setRecord({items:[row('restore')],nextAfter:null});await ui.click('next');ui.select(['restore']);
 assert.match(ui.elements.cancelReview.innerHTML,/repair/);assert.match(ui.elements.cancelReview.innerHTML,/restore/);
 assert.match(ui.reads.at(-1),/after=25/);ui.elements.lifecycleReason.value='Selected both pages';await ui.click('cancelSelected');
 assert.deepEqual(ui.posted[0].assignmentIds,['repair','restore']);
});

test('truncated descendants and noncancellable physical visits cannot be cancelled from the screen',async()=>{
 const truncated=row('large');truncated.lifecycle.descendantsTruncated=true;
 const physical=row('committed',[],{lifecycle:{canCancel:false,revision:0}});
 const ui=await screen({items:[truncated,physical]});assert.ok(!ui.elements.cancelAssignments.options.some(o=>o.value==='committed'));
 ui.select(['large']);assert.equal(ui.elements.cancelSelected.disabled,true);assert.match(ui.elements.cancelRequirements.textContent,/exceeds/);
 ui.elements.lifecycleReason.value='Review';await ui.click('cancelSelected');assert.equal(ui.posted.length,0);
});

test('lost cancellation reply reloads exact IDs, reason and endpoint even after cancellation committed',async()=>{
 const ui=await screen();ui.select(['repair','restore']);ui.elements.lifecycleReason.value='Original reason';ui.setMode('lost');await ui.click('cancelSelected');
 const original=ui.posted[0],reopened=await screen({items:[cancelled('repair'),cancelled('restore')],storage:ui.storage});
 assert.match(reopened.elements.cancelRequirements.textContent,/Retained cancellation: repair, restore/);
 assert.equal(reopened.elements.lifecycleReason.value,'Original reason');assert.equal(reopened.elements.retry.disabled,false);
 await reopened.click('retry');assert.deepEqual(reopened.posted[0],original);assert.equal(reopened.paths[0],'/api/field-assignment-lifecycle');
});

test('replacement locks original operation and edge and requires fresh references and explicit predecessor',async()=>{
 const ui=await screen({items:[cancelled()]});ui.elements.replacementSelect.value='repair';await ui.click('prepareReplacement');
 const f=ui.elements.assignment.elements;
 assert.equal(f.operation.value,'repair-water-main');assert.equal(f.operation.disabled,true);assert.equal(f.assetId.disabled,true);
 assert.equal(f.assignmentId.value,'');assert.equal(f.orderId.value,'');assert.equal(f.predecessorAssignmentId.value,'');
 ui.elements.lifecycleReason.value='Replace cancelled repair';f.assignmentId.value='repair';f.orderId.value='new-local';f.predecessorAssignmentId.value='new-isolation';
 await ui.accept();assert.equal(ui.posted.length,0);assert.match(ui.elements.message.textContent,/fresh assignment/);
 f.assignmentId.value='new-repair';await ui.accept();const outer=ui.posted[0],nested=outer.replacement;
 assert.equal(ui.paths[0],'/api/field-assignment-lifecycle');assert.equal(outer.action,'replace');assert.equal(outer.assignmentId,'repair');assert.equal(outer.expectedRevision,1);
 assert.equal(nested.schemaVersion,'field-main-phases/1');assert.equal(nested.action,'accept');assert.equal(nested.assignmentId,'new-repair');assert.equal(nested.predecessorAssignmentId,'new-isolation');
 assert.notEqual(outer.commandId,nested.commandId);
 for(const key of ['actorId','environmentId','worldFingerprint','effectiveDate','causalReference'])assert.equal(outer[key],nested[key]);
});

test('lost replacement reply preserves nested identity and exact retry after replacement already exists',async()=>{
 const ui=await screen({items:[cancelled()]});ui.elements.replacementSelect.value='repair';await ui.click('prepareReplacement');
 const f=ui.elements.assignment.elements;f.assignmentId.value='new-repair';f.orderId.value='new-local';f.predecessorAssignmentId.value='new-isolation';ui.elements.lifecycleReason.value='Original replacement';
 ui.setMode('lost');await ui.accept();const original=ui.posted[0];
 const old=cancelled();old.lifecycle={...old.lifecycle,revision:2,replacementAssignmentId:'new-repair',canReplace:false};
 const reopened=await screen({items:[old],storage:ui.storage});assert.equal(reopened.elements.assignment.elements.predecessorAssignmentId.value,'new-isolation');
 assert.equal(reopened.elements.lifecycleReason.value,'Original replacement');assert.equal(reopened.elements.retry.disabled,false);
 await reopened.click('retry');assert.deepEqual(reopened.posted[0],original);
 assert.match(reopened.elements.history.innerHTML,/Replacement: new-repair/);
});

test('cancelled history is escaped and reported as cancelled, never ready for a visit',async()=>{
 const old=cancelled();old.lifecycle.reason='<retired>';
 const ui=await screen({items:[old]});assert.match(ui.elements.history.innerHTML,/Cancelled 2026-01-03 · &lt;retired&gt;/);
 assert.doesNotMatch(ui.elements.history.innerHTML,/Ready for a due visit/);
 const reporting=await screen({page:'field_reporting',items:[{...old,canConfigure:true,canSubmit:true,submitActorId:'main-crew',reportMode:'manual',workMode:'perform',policyRevision:1}]});
 assert.equal(reporting.elements.configure.disabled,true);assert.equal(reporting.elements.submitReport.disabled,true);
 await reporting.configure();await reporting.submit();assert.equal(reporting.posted.length,0);
 assert.match(reporting.elements.physicalResult.textContent,/Cancelled before physical execution/);
 assert.match(reporting.elements.history.innerHTML,/Cancelled before visit/);
});

test('failed refresh and changed owner block lifecycle mutations; backend rejection remains visible',async()=>{
 const ui=await screen();ui.select(['repair','restore']);ui.elements.lifecycleReason.value='Cancel';ui.setReadError('Offline');await ui.click('refresh');
 await ui.click('cancelSelected');assert.equal(ui.posted.length,0);assert.equal(ui.elements.cancelSelected.disabled,true);
 ui.setReadError(null);await ui.click('refresh');ui.setMode('reject');await ui.click('cancelSelected');
 assert.match(ui.elements.message.textContent,/Physical visit already committed/);assert.equal(ui.storage.size,0);
 ui.setRecord({ownerId:'different-owner'});await ui.click('refresh');await ui.click('cancelSelected');assert.equal(ui.posted.length,1);
});

test('first load failure recovers storage identity before a later mutation',async()=>{
 const ui=await screen({initialReadError:'Unavailable'});ui.setReadError(null);await ui.click('refresh');
 ui.select(['repair','restore']);ui.elements.lifecycleReason.value='Recovered';ui.setMode('lost');await ui.click('cancelSelected');
 assert.equal(ui.storage.has('field-execution-pending:saved-world:field-owner'),true);assert.equal(ui.storage.has(undefined),false);
});
