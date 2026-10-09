const $=id=>document.getElementById(id);
const esc=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const skills={plumbing:'skillPlumbing',electric:'skillElectric',gas:'skillGas',sewer:'skillSewer','water-main':'skillWaterMain'};
const operations={
 'repair-water-leak':{label:'Repair water leak',skill:'plumbing',target:'Water service meter ID',placeholder:'Stable water meter ID from the map',help:'Requires plumbing. Use a saved water service meter ID.',url:'/water-faults',source:'Inspect water faults to identify the target'},
 'restore-electric-supply':{label:'Restore electric supply',skill:'electric',target:'Electric network edge ID',placeholder:'Enabled edge ID from electric supply inspection',help:'Requires electric. Use an enabled edge ID in the saved electric network, not an electric meter ID.',url:'/network-faults?commodity=electric',source:'Inspect electric supply connections to identify the target'},
 'restore-gas-supply':{label:'Restore gas supply',skill:'gas',target:'Gas network edge ID',placeholder:'Enabled edge ID from gas supply inspection',help:'Requires gas. Use an enabled edge ID in the saved gas network, not a gas meter ID.',url:'/network-faults?commodity=gas',source:'Inspect gas supply connections to identify the target'},
 'clear-sewer-blockage':{label:'Clear sewer blockage',skill:'sewer',target:'Sewer service point ID',placeholder:'Stable SEWER-SP-… identity from sewer inspection',help:'Requires sewer. Inspect the lateral using its source water meter, then copy the displayed sewer service ID. No sewer meter is created.',url:'/sewer',source:'Inspect sewer laterals to identify the target'},
 'isolate-water-main':{label:'Isolate water main',skill:'water-main',target:'Water main edge ID',placeholder:'Saved trunk or distribution edge ID',help:'Requires water-main. Close the saved section valves around this main. Use a distinct local phase work reference.',url:'/water-mains',source:'Inspect water mains to identify the saved edge',completed:'Isolation completed'},
 'repair-water-main':{label:'Repair water main',skill:'water-main',target:'Water main edge ID',placeholder:'Same edge as the isolation assignment',help:'Requires water-main. Reference the isolation assignment for this same edge. Physical isolation must complete first; a report claim cannot unlock repair.',url:'/water-mains',source:'Inspect water mains to identify the saved edge',predecessor:'Isolation assignment ID',completed:'Main repaired; valves remain closed'},
 'restore-water-main':{label:'Restore water main',skill:'water-main',target:'Water main edge ID',placeholder:'Same edge as the repair assignment',help:'Requires water-main. Reference the repair assignment for this same edge. Physical repair must complete first; other faults may still interrupt supply.',url:'/water-mains',source:'Inspect water mains to identify the saved edge',predecessor:'Repair assignment ID',completed:'Restoration completed; wider supply not verified'},
};
let state,pending=null,key,busy=false,after=0,fresh=false,identityBlocked=false,replacementSource=null;
const cancellationSelection=new Map();
function message(text,error=false){$('message').textContent=text;$('message').className=error?'error':'';}
async function request(path,body){const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{cache:'no-store'});const data=await response.json();if(!response.ok){const error=Error(data.error||'Request failed.');error.rejected=response.status>=400&&response.status<500;throw error;}return data;}
function controls(){
 const locked=busy||!!pending||!fresh||identityBlocked;
 for(const el of document.querySelectorAll('input,button,select'))el.disabled=locked;
 $('retry').hidden=!pending;$('retry').disabled=busy||!fresh||identityBlocked;$('refresh').disabled=busy||identityBlocked;
 $('next').disabled=locked||!state?.nextAfter;
 const f=$('assignment').elements;if(f.predecessorAssignmentId)f.predecessorAssignmentId.disabled=locked||!operations[f.operation?.value]?.predecessor;
 if(replacementSource){f.operation.disabled=true;f.assetId.disabled=true;}
 if($('cancelAssignments')){
  $('cancelSelected').disabled=locked||!!selectionProblem();
  $('clearCancellation').disabled=locked||!cancellationSelection.size;
  $('prepareReplacement').disabled=locked||!state?.items.some(i=>i.assignment.assignmentId===$('replacementSelect').value&&i.lifecycle?.canReplace);
  $('discardReplacement').hidden=!replacementSource;$('discardReplacement').disabled=locked;
  $('acceptAssignment').textContent=replacementSource?'Accept linked replacement':'Accept assignment';
  if(replacementSource)$('acceptAssignment').disabled=locked||!replacementSource.lifecycle?.canReplace;
 }
}
function selectionProblem(){
 if(!cancellationSelection.size)return 'Select pending assignments to review.';
 if(cancellationSelection.size>100)return 'Select no more than 100 assignments.';
 for(const item of cancellationSelection.values()){
  if(!item.lifecycle?.canCancel)return `Assignment ${item.assignment.assignmentId} is no longer cancellable. Clear it from the selection.`;
  if(item.lifecycle.descendantsTruncated)return 'This dependency list exceeds the supported review size. Cancel smaller descendant groups first.';
  const missing=(item.lifecycle.pendingDescendantIds||[]).filter(id=>!cancellationSelection.has(id));
  if(missing.length)return `Also select pending descendants: ${missing.join(', ')}. Use the assignment page controls below if needed.`;
 }
 return '';
}
function renderLifecycle(){
 if(!$('cancelAssignments'))return;
 if(replacementSource)replacementSource=state.items.find(i=>i.assignment.assignmentId===replacementSource.assignment.assignmentId)||replacementSource;
 for(const item of state.items)if(cancellationSelection.has(item.assignment.assignmentId))cancellationSelection.set(item.assignment.assignmentId,item);
 $('cancelAssignments').innerHTML=state.items.filter(i=>i.lifecycle?.canCancel).map(i=>`<option value="${esc(i.assignment.assignmentId)}"${cancellationSelection.has(i.assignment.assignmentId)?' selected':''}>${esc(i.assignment.assignmentId)} · ${esc(operations[i.assignment.operation]?.label||i.assignment.operation)}</option>`).join('');
 $('cancelReview').innerHTML=[...cancellationSelection.values()].map(i=>`<li>${esc(i.assignment.assignmentId)} · ${esc(operations[i.assignment.operation]?.label||i.assignment.operation)} · ${esc(i.assignment.assetId)} · revision ${esc(i.lifecycle.revision)} · pending descendants: ${esc(i.lifecycle.pendingDescendantIds?.join(', ')||'none')}</li>`).join('');
 $('cancelRequirements').textContent=selectionProblem()||`${cancellationSelection.size} assignment(s) explicitly selected. Only this reviewed set will be cancelled.`;
 const previous=$('replacementSelect').value;
 $('replacementSelect').innerHTML='<option value="">Choose a cancelled phase</option>'+state.items.filter(i=>i.lifecycle?.canReplace).map(i=>`<option value="${esc(i.assignment.assignmentId)}">${esc(i.assignment.assignmentId)} · ${esc(operations[i.assignment.operation]?.label||i.assignment.operation)}</option>`).join('');
 if(state.items.some(i=>i.assignment.assignmentId===previous&&i.lifecycle?.canReplace))$('replacementSelect').value=previous;
 if(replacementSource)$('replacementHelp').textContent=`Replacing ${replacementSource.assignment.assignmentId}, revision ${replacementSource.lifecycle.revision}. Enter fresh assignment and local work references below. The saved operation and edge are fixed.`;
}
function prepareReplacement(item){
 replacementSource=item;const f=$('assignment').elements,a=item.assignment;
 for(const name of ['crewId','operation','assetId','orderRevision','reportDelayDays'])f[name].value=a[name];
 f.assignmentId.value='';f.orderId.value='';f.scheduledDate.value=state.through;f.predecessorAssignmentId.value='';
 showOperation();renderLifecycle();controls();$('acceptSection')?.scrollIntoView?.({behavior:'smooth',block:'start'});
}
function showSkills(selected){const f=$('crew').elements;for(const [skill,name] of Object.entries(skills))if(f[name])f[name].checked=selected.includes(skill);}
function selectedSkills(crew){
 const f=$('crew').elements;
 // Preserve saved behavior if an older cached screen has no skill controls.
 return Object.values(skills).some(name=>f[name])?Object.entries(skills).filter(([,name])=>f[name]?.checked).map(([skill])=>skill):crew?[...crew.skills]:['plumbing'];
}
function showOperation(clearTarget=false){
 const f=$('assignment').elements;if(!f.operation)return;
 const operation=operations[f.operation.value];if(!operation)return;
 if(clearTarget){f.assetId.value='';if(f.predecessorAssignmentId)f.predecessorAssignmentId.value='';}
 $('assetLabel').textContent=operation.target;f.assetId.placeholder=operation.placeholder;
 $('operationHelp').textContent=operation.help;$('operationSource').href=operation.url;$('operationSource').textContent=operation.source;
 if(f.predecessorAssignmentId){
  $('predecessorField').hidden=!operation.predecessor;f.predecessorAssignmentId.required=!!operation.predecessor;
  $('predecessorLabel').textContent=operation.predecessor||'Predecessor assignment ID';
  if(!operation.predecessor)f.predecessorAssignmentId.value='';
 }
 if($('orderLabel'))$('orderLabel').textContent=operation.skill==='water-main'?'Local phase work reference':'Order reference';
}
function showPending(){
 if(pending?.action==='cancel'&&$('cancelAssignments')){
  cancellationSelection.clear();
  for(const id of pending.assignmentIds)cancellationSelection.set(id,state.items.find(i=>i.assignment.assignmentId===id)||{assignment:{assignmentId:id},lifecycle:{revision:pending.expectedRevisions[id],pendingDescendantIds:[],canCancel:false}});
  $('lifecycleReason').value=pending.reason;renderLifecycle();
  $('cancelRequirements').textContent=`Retained cancellation: ${pending.assignmentIds.join(', ')}. Retry sends this exact selection and reason; it may already be recorded.`;
 }else if(pending?.action==='accept'||pending?.action==='replace'){
  const accepted=pending.action==='replace'?pending.replacement:pending;
  if(pending.action==='replace'&&$('cancelAssignments')){
   replacementSource=state.items.find(i=>i.assignment.assignmentId===pending.assignmentId)||{assignment:{...accepted,assignmentId:pending.assignmentId},lifecycle:{revision:pending.expectedRevision,canReplace:false}};
   $('lifecycleReason').value=pending.reason;renderLifecycle();
  }
  const f=$('assignment').elements;
  for(const name of ['assignmentId','crewId','operation','assetId','orderId','orderRevision','scheduledDate','reportDelayDays','predecessorAssignmentId'])if(f[name])f[name].value=accepted[name]??'';
  showOperation();
 }else if(pending?.action==='configure-crew'){
  const f=$('crew').elements;f.crewId.value=pending.crewId;hydrateCrew();f.dailyCapacity.value=pending.dailyCapacity;showWeekdays(pending.weekdays);
  showSkills(pending.skills);
 }
}
function showWeekdays(days){
 const f=$('crew').elements;
 for(const option of Array.from(f.weekdays.options))if(option.dataset.savedSchedule)option.remove();
 const weekdays=days.join(',');
 if(!Array.from(f.weekdays.options).some(option=>option.value===weekdays)){
  const option=document.createElement('option');option.value=weekdays;option.dataset.savedSchedule='true';
  option.textContent='Saved schedule: '+days.map(day=>['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][day]).join(', ');
  f.weekdays.append(option);
 }
 f.weekdays.value=weekdays;
}
function hydrateCrew(){
 const f=$('crew').elements,crew=state?.crews.find(c=>c.id===f.crewId.value.trim());
 f.dailyCapacity.value=crew?.daily_capacity??1;
 showWeekdays(crew?crew.weekdays:[0,1,2,3,4]);
 showSkills(crew?crew.skills:['plumbing']);
}
async function load(){
 fresh=false;controls();
 const next=await request('/api/field-execution?after='+after);
 if(state&&(next.worldFingerprint!==state.worldFingerprint||next.ownerId!==state.ownerId||next.environmentId!==state.environmentId)){identityBlocked=true;throw Error('World or field owner changed. Reload this page.');}
 if(!state&&next.crews.length&&!next.crews.some(c=>c.id===$('crew').elements.crewId.value.trim()))$('crew').elements.crewId.value=next.crews[0].id;
 state=next;fresh=true;
 if(!key){
  key='field-execution-pending:'+state.worldFingerprint+':'+state.ownerId;
  try{
   pending=JSON.parse(sessionStorage.getItem(key)||'null');
   if(pending&&(!['field-world-execution/1','field-main-phases/1','field-assignment-lifecycle/1'].includes(pending.schemaVersion)||pending.environmentId!==state.environmentId||pending.worldFingerprint!==state.worldFingerprint||typeof pending.commandId!=='string'))throw Error('Invalid retained command identity.');
  }catch(error){identityBlocked=true;throw Error('Could not restore retained commands safely. Reload after restoring session storage. '+error.message);}
 }
 hydrateCrew();$('identity').textContent=`${state.environmentId} · ${state.ownerId}`;
 $('today').textContent=`Current world day: ${state.through}. Visits run before that day's next physical simulation.`;
 $('assignment').elements.scheduledDate.value||=state.through;
 $('crews').textContent=state.crews.length?state.crews.map(c=>`${c.id}: ${c.daily_capacity} visits/day shared across ${c.skills.length?c.skills.join(', '):'no enabled skills'}, revision ${c.revision}`).join(' · '):'No crews registered.';
 $('history').innerHTML=state.items.length?state.items.map(item=>{const a=item.assignment,r=item.result,operation=operations[a.operation||'repair-water-leak'];return `<tr><td><code>${esc(a.assignmentId)}</code><br>${esc(a.orderId)} · revision ${esc(a.orderRevision)}</td><td>${esc(operation?.label||a.operation)}<br>Skill: ${esc(operation?.skill||'Unknown')}<br>${esc(a.assetId)}<br>${esc(a.crewId)}</td><td>${esc(a.scheduledDate)}${item.phase?'<br>Predecessor: '+esc(item.phase.predecessorAssignmentId||'None — initial isolation'):''}</td><td><span class="badge">${esc(r?.outcome==='completed'&&operation?.completed?operation.completed:r?.outcome==='not_attempted'&&operation?.completed?'Inspected; assigned phase not performed':r?.outcome||item.state)}</span><br>${esc(item.state==='cancelled'?('Cancelled '+(item.lifecycle?.cancelledDate||'')+' · '+(item.lifecycle?.reason||'')):r?.effectiveDate||item.blockedReason||'Ready for a due visit')}${item.lifecycle?.replacementAssignmentId?'<br>Replacement: '+esc(item.lifecycle.replacementAssignmentId):''}${item.lifecycle?.replacesAssignmentId?'<br>Replaces: '+esc(item.lifecycle.replacesAssignmentId):''}</td><td>${item.messages.map(m=>`${m.schema==='field-report/1'||m.id===r?.reportId?'Report':m.schema==='field-ack/1'?'Dispatch acknowledgement':'Field message'}: <strong>${esc(m.state)}</strong><br>Available ${esc(m.available_day)} · ${esc(m.attempts)} attempt(s)${m.last_error?'<br>'+esc(m.last_error):''}`).join('<hr>')}</td></tr>`;}).join(''):'<tr><td colspan="5">No accepted assignments.</td></tr>';
 showOperation();
 renderLifecycle();
 if(pending)showPending();
 controls();
}
async function send(fields){
 if(busy||!fresh||identityBlocked)return;
 if(!pending){pending={schemaVersion:'field-world-execution/1',commandId:crypto.randomUUID(),environmentId:state.environmentId,worldFingerprint:state.worldFingerprint,actorId:'world-admin',effectiveDate:state.through,causalReference:'local-field-admin',...fields};try{sessionStorage.setItem(key,JSON.stringify(pending));}catch{pending=null;message('Could not retain this command for safe retry. Enable session storage before submitting.',true);return;}}
 busy=true;controls();message('Recording field command…');
 try{
  await request(pending.schemaVersion==='field-assignment-lifecycle/1'?'/api/field-assignment-lifecycle':pending.schemaVersion==='field-main-phases/1'?'/api/field-main-phases':'/api/field-execution',pending);
  if(pending.action==='cancel')cancellationSelection.clear();
  if(pending.action==='replace')replacementSource=null;
  pending=null;sessionStorage.removeItem(key);await load();message('Field command recorded. Physical execution, local assignment state and enterprise decisions remain separate.');
 }
 catch(error){if(error.rejected){pending=null;sessionStorage.removeItem(key);}message(error.message+(pending?' The outcome is uncertain. Retry the same retained command.':''),true);}
 finally{busy=false;controls();}
}
$('crew').elements.crewId.onchange=hydrateCrew;
$('crew').onsubmit=event=>{event.preventDefault();const f=event.target.elements,crew=state.crews.find(c=>c.id===f.crewId.value.trim());return send({action:'configure-crew',crewId:f.crewId.value.trim(),expectedRevision:crew?.revision||0,skills:selectedSkills(crew),weekdays:f.weekdays.value?f.weekdays.value.split(',').map(Number):[],dailyCapacity:Number(f.dailyCapacity.value)});};
$('assignment').onsubmit=event=>{
 event.preventDefault();const f=event.target.elements,operation=f.operation?.value||'repair-water-leak',phase=operations[operation]?.skill==='water-main';
 const predecessor=f.predecessorAssignmentId?.value.trim()||'';
 if(phase&&operations[operation].predecessor&&!predecessor){message('Enter the physically preceding assignment ID for this water-main phase.',true);return;}
 const accepted={action:'accept',assignmentId:f.assignmentId.value.trim(),crewId:f.crewId.value.trim(),assetId:f.assetId.value.trim(),orderId:f.orderId.value.trim(),orderRevision:Number(f.orderRevision.value),scheduledDate:f.scheduledDate.value,operation,reportDelayDays:Number(f.reportDelayDays.value),
  ...(phase?{schemaVersion:'field-main-phases/1',predecessorAssignmentId:operations[operation].predecessor?predecessor:null}:{})};
 if(replacementSource&&!pending){
  if(!replacementSource.lifecycle?.canReplace)return;
  const reason=$('lifecycleReason').value.trim();if(!reason){message('Enter a reason for the replacement.',true);return;}
  if(accepted.assignmentId===replacementSource.assignment.assignmentId||accepted.orderId===replacementSource.assignment.orderId){message('Use fresh assignment and local work references for the replacement.',true);return;}
  const replacement={commandId:crypto.randomUUID(),environmentId:state.environmentId,worldFingerprint:state.worldFingerprint,actorId:'world-admin',effectiveDate:state.through,causalReference:'local-field-admin',...accepted};
  return send({schemaVersion:'field-assignment-lifecycle/1',action:'replace',assignmentId:replacementSource.assignment.assignmentId,expectedRevision:replacementSource.lifecycle.revision,reason,replacement});
 }
 return send(accepted);
};
if($('assignment').elements.operation)$('assignment').elements.operation.onchange=()=>{showOperation(true);controls();};
$('run').onclick=async()=>{if(busy||pending||!fresh||identityBlocked)return;busy=true;controls();message('Executing due visits…');try{const result=await request('/api/field-execution/run-due',{environmentId:state.environmentId,worldFingerprint:state.worldFingerprint,effectiveDate:state.through});await load();message(`Due visits processed: ${Array.isArray(result)?result.length:(result.results||[]).length}. Reports remain in the delivery queue.`);}catch(error){message(error.message+' Refresh status before running again; committed physical actions recover without repeating repairs.',true);}finally{busy=false;controls();}};
$('retry').onclick=()=>send();$('refresh').onclick=()=>load().catch(e=>message(e.message,true));$('first').onclick=()=>{after=0;return load().catch(e=>message(e.message,true));};$('next').onclick=()=>{after=state.nextAfter;return load().catch(e=>message(e.message,true));};
if($('cancelAssignments')){
 $('cancelAssignments').onchange=()=>{if(busy||pending||!fresh||identityBlocked)return;const ids=new Set(Array.from($('cancelAssignments').selectedOptions,o=>o.value));for(const i of state.items)if(i.lifecycle?.canCancel){if(ids.has(i.assignment.assignmentId))cancellationSelection.set(i.assignment.assignmentId,i);else cancellationSelection.delete(i.assignment.assignmentId);}renderLifecycle();controls();};
 $('clearCancellation').onclick=()=>{if(busy||pending)return;cancellationSelection.clear();renderLifecycle();controls();};
 $('cancelSelected').onclick=()=>{
  if(busy||pending||!fresh||identityBlocked)return;
  const problem=selectionProblem(),reason=$('lifecycleReason').value.trim();if(problem||!reason){message(problem||'Enter a reason for cancellation.',true);return;}
  const assignmentIds=[...cancellationSelection.keys()].sort();
  return send({schemaVersion:'field-assignment-lifecycle/1',action:'cancel',assignmentIds,expectedRevisions:Object.fromEntries(assignmentIds.map(id=>[id,cancellationSelection.get(id).lifecycle.revision])),reason});
 };
 $('replacementSelect').onchange=controls;
 $('prepareReplacement').onclick=()=>{if(busy||pending||!fresh||identityBlocked)return;const item=state.items.find(i=>i.assignment.assignmentId===$('replacementSelect').value&&i.lifecycle?.canReplace);if(item)prepareReplacement(item);};
 $('discardReplacement').onclick=()=>{if(busy||pending)return;replacementSource=null;$('replacementHelp').textContent='Replacement draft discarded. Accepting a new assignment does not alter cancelled history.';controls();};
}
try{await load();message(pending?'A retained command needs its result confirmed. Retry the same command.':'Administrator scenario controls are ready.');controls();}catch(error){fresh=false;message(error.message,true);controls();}
