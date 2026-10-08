const $=id=>document.getElementById(id);
const esc=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const operations={'repair-water-leak':'Repair water leak','restore-electric-supply':'Restore electric supply','restore-gas-supply':'Restore gas supply','clear-sewer-blockage':'Clear sewer blockage'};
const outcomes={completed:'Repair completed',not_found:'No active fault found',not_attempted:'Inspected; repair not attempted'};
let state=null,pending=null,storageKey=null,selectedId='',after=0,busy=false,loading=false,stale=true,identityChanged=false,storageReady=true;
const selected=()=>state?.items.find(item=>item.assignment.assignmentId===selectedId);
function message(text,error=false){$('message').textContent=text;$('message').className=error?'error':'';}
function blocked(){return busy||loading||stale||identityChanged||!storageReady||!state;}
function controls(){
 const item=selected(),locked=blocked()||!!pending;
 $('assignmentSelect').disabled=locked||!state?.items.length;
 $('first').disabled=locked||after===0;$('next').disabled=locked||!state?.nextAfter;
 $('refresh').disabled=busy||loading||identityChanged;
 for(const id of ['configure','reportMode','workMode'])$(id).disabled=locked||!item?.canConfigure;
 $('workMode').disabled||=$('reportMode').value!=='manual';
 for(const id of ['submitReport','claimedOutcome'])$(id).disabled=locked||!item?.canSubmit||!item?.submitActorId;
 $('retry').hidden=!pending;$('retry').disabled=blocked();
 $('pendingDetails').hidden=!pending;
 if(pending)$('pendingDetails').textContent=`Retained ${pending.action} command for ${pending.assignmentId}, actor ${pending.actorId}, policy revision ${pending.expectedRevision}. ${pending.action==='submit'?'Claim: '+pending.outcome:pending.reportMode+' reporting / '+pending.workMode+' work'}. Retry confirms this exact command even if the saved state has already changed.`;
}
function renderSelection(){
 const item=selected();
 if(!item){
  $('assignmentDetails').textContent='No accepted assignments on this page. Register a crew and accept an assignment in Crews and visits.';
  for(const id of ['physicalResult','reportStatus','transportStatus'])$(id).textContent='No assignment selected';
  $('policyHelp').textContent='Select an assignment before configuring reporting.';
  $('submitHelp').textContent='A manual report requires a completed visit.';controls();return;
 }
 const a=item.assignment;
 $('assignmentDetails').textContent=`${operations[a.operation]||a.operation} · target ${a.assetId} · crew ${a.crewId} · order ${a.orderId} / revision ${a.orderRevision} · scheduled ${a.scheduledDate}`;
 $('physicalResult').textContent=item.actualOutcome?`${outcomes[item.actualOutcome]||item.actualOutcome} · visit ${item.visitDate}`:'Visit not yet recorded';
 $('reportStatus').textContent=item.claimedOutcome?`Submitted claim: ${item.claimedOutcome}. Report ${item.reportId}`:item.reportMode==='manual'?(item.actualOutcome?'Awaiting crew submission — no report exists':'Manual submission waits for the visit'):'Automatic report waits for the visit';
 const transport=item.reportTransport;
 $('transportStatus').textContent=!item.reportId?'No report to deliver':`Available from ${item.reportAvailableDate}. `+(transport?`${transport.state==='received'?'Transport receipt recorded':transport.state==='pending'?'Pending transport':transport.state} · ${transport.attempts} attempt(s)${transport.lastError?' · '+transport.lastError:''}. A receipt is not enterprise acceptance.`:'Transport receipt status is not exposed here. Availability is not delivery.');
 $('reportMode').value=item.reportMode;$('workMode').value=item.workMode;
 if(pending?.assignmentId===selectedId){
  if(pending.action==='configure'){$('reportMode').value=pending.reportMode;$('workMode').value=pending.workMode;}
  else $('claimedOutcome').value=pending.outcome;
 }
 $('policyHelp').textContent=`Saved policy revision ${item.policyRevision}. `+(item.canConfigure?'Policy can be changed before this visit.':'Policy is locked because physical execution has started or the visit is recorded.');
 $('submitHelp').textContent=item.canSubmit?`Submit as assigned simulator crew ${item.submitActorId}. The report will use today's date (${state.through}) plus ${a.reportDelayDays} day(s) of transport delay.`:item.reportId?'This report is already submitted and cannot be changed.':item.reportMode==='automatic'?'Automatic reporting is enabled. No manual submission is needed.':'Run the accepted visit from Crews and visits or cruise control before submitting.';
 controls();
}
function render(){
 $('identity').textContent=`${state.environmentId} · ${state.ownerId}`;
 $('today').textContent=`Current world day: ${state.through}. Refresh after running visits or advancing time.`;
 if(!state.items.some(item=>item.assignment.assignmentId===selectedId))selectedId=state.items[0]?.assignment.assignmentId||'';
 $('assignmentSelect').innerHTML=state.items.length?state.items.map(item=>`<option value="${esc(item.assignment.assignmentId)}">${esc(item.assignment.assignmentId)} · ${esc(operations[item.assignment.operation]||item.assignment.operation)} · ${esc(item.assignment.crewId)}</option>`).join(''):'<option value="">No assignments</option>';
 $('assignmentSelect').value=selectedId;
 $('history').innerHTML=state.items.length?state.items.map(item=>{const a=item.assignment;return `<tr><td>${esc(a.assignmentId)}<br>${esc(a.orderId)} · revision ${esc(a.orderRevision)}</td><td>${esc(operations[a.operation]||a.operation)}<br>${esc(a.crewId)}</td><td>${esc(item.reportMode)} / ${esc(item.workMode)}<br>Revision ${esc(item.policyRevision)}</td><td>${esc(outcomes[item.actualOutcome]||'Visit not recorded')}<br>${esc(item.visitDate)}</td><td>${esc(item.claimedOutcome||'Not submitted')}</td></tr>`;}).join(''):'<tr><td colspan="5">No accepted assignments.</td></tr>';
 renderSelection();
}
async function request(body=null,cursor=after){
 const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),body?15000:10000);
 try{
  const response=await fetch('/api/field-reporting'+(body?'':`?limit=25&after=${cursor}`),body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:controller.signal}:{cache:'no-store',signal:controller.signal});
  const data=await response.json();
  if(!response.ok){const error=Error(data.error||'Field-reporting request failed.');error.rejected=response.status>=400&&response.status<500;throw error;}
  return data;
 }finally{clearTimeout(timeout);}
}
function retainedValid(value){
 if(!value)return true;
 const common=['schemaVersion','commandId','environmentId','worldFingerprint','actorId','effectiveDate','action','causalReference','assignmentId','expectedRevision'];
 const extra=value.action==='configure'?['reportMode','workMode']:value.action==='submit'?['outcome']:null;
 return !!extra&&value.schemaVersion==='field-reporting/1'&&value.environmentId===state.environmentId&&value.worldFingerprint===state.worldFingerprint
  &&Object.keys(value).length===common.length+extra.length&&[...common,...extra].every(key=>Object.hasOwn(value,key))
  &&common.filter(key=>key!=='expectedRevision').every(key=>typeof value[key]==='string'&&value[key].length>0)
  &&Number.isInteger(value.expectedRevision)&&value.expectedRevision>=0
  &&(value.action==='configure'?value.actorId==='world-admin'&&['automatic','manual'].includes(value.reportMode)&&['perform','inspect-only'].includes(value.workMode)&&(value.workMode!=='inspect-only'||value.reportMode==='manual'):['completed','not_found'].includes(value.outcome)&&value.actorId!=='world-admin');
}
async function refresh(cursor=after,announce=true){
 if(busy||loading||identityChanged)return;
 loading=true;controls();
 try{
  const next=await request(null,cursor);
  if(next.schemaVersion!=='field-reporting/1'||!Array.isArray(next.items)||!next.environmentId||!next.worldFingerprint||!next.ownerId||next.actorId!=='world-admin')throw Error('Unsupported administrator reporting response. Update the server and reload.');
  if(state&&['environmentId','worldFingerprint','ownerId'].some(key=>state[key]!==next[key])){identityChanged=true;throw Error('World or field owner changed. Reload before issuing any command.');}
  state=next;after=cursor;stale=false;
  if(!storageKey){
   storageKey='field-reporting-pending:'+JSON.stringify([state.environmentId,state.worldFingerprint,state.ownerId]);
   try{pending=JSON.parse(sessionStorage.getItem(storageKey)||'null');if(!retainedValid(pending))throw Error('Invalid retained command.');}
   catch{storageReady=false;pending=null;throw Error('Could not read retained commands safely. Restore session storage and reload before submitting.');}
   if(pending)selectedId=pending.assignmentId;
  }
  render();
  if(announce)message(pending?'A retained command needs its result confirmed. Retry the same command.':'Saved reporting status is current.');
 }catch(error){stale=true;message(error.name==='AbortError'?'Status request timed out. Refresh to recover.':error.message,true);}
 finally{loading=false;controls();}
}
function clearPending(){pending=null;try{sessionStorage.removeItem(storageKey);}catch{storageReady=false;}}
async function send(action){
 if(blocked())return;
 const item=selected();
 if(!pending){
  if(action==='configure'?!item?.canConfigure:action==='submit'?!item?.canSubmit||!item?.submitActorId:true)return;
  const extras=action==='configure'?{reportMode:$('reportMode').value,workMode:$('workMode').value}:{outcome:$('claimedOutcome').value};
  if(action==='configure'&&extras.workMode==='inspect-only'&&extras.reportMode!=='manual'){message('Inspection without repair requires manual reporting.',true);return;}
  pending={schemaVersion:'field-reporting/1',commandId:crypto.randomUUID(),environmentId:state.environmentId,worldFingerprint:state.worldFingerprint,
   actorId:action==='configure'?'world-admin':item.submitActorId,effectiveDate:state.through,action,causalReference:'local-field-reporting-admin',
   assignmentId:item.assignment.assignmentId,expectedRevision:item.policyRevision,...extras};
  try{sessionStorage.setItem(storageKey,JSON.stringify(pending));}
  catch{pending=null;storageReady=false;message('Enable session storage and reload so commands can be retained for exact retry.',true);controls();return;}
 }
 busy=true;controls();message('Recording field-reporting command…');
 let resultMessage='',failed=false;
 try{await request(pending);clearPending();resultMessage='Command recorded. Physical work, report claims and enterprise decisions remain separate.';}
 catch(error){if(error.rejected)clearPending();failed=true;resultMessage=(error.name==='AbortError'?'Command response timed out.':error.message)+(pending?' The outcome is uncertain. Retry the retained command.':' Refresh status before trying again.');}
 finally{busy=false;stale=true;await refresh(after,false);if(!stale)message(resultMessage+(!storageReady?' Session storage could not be cleared. Reload before further commands.':''),failed||!storageReady);controls();}
}
$('assignmentSelect').onchange=()=>{if(blocked()||pending)return;selectedId=$('assignmentSelect').value;$('claimedOutcome').value='completed';renderSelection();};
$('reportMode').onchange=()=>{if($('reportMode').value==='automatic')$('workMode').value='perform';controls();};
$('policyForm').onsubmit=event=>{event.preventDefault();return send('configure');};
$('reportForm').onsubmit=event=>{event.preventDefault();return send('submit');};
$('retry').onclick=()=>send();$('refresh').onclick=()=>refresh();
$('first').onclick=()=>{if(!blocked()&&!pending)return refresh(0);};
$('next').onclick=()=>{if(!blocked()&&!pending&&state?.nextAfter)return refresh(state.nextAfter);};
controls();await refresh();
