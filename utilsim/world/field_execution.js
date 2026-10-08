const $=id=>document.getElementById(id);
const esc=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const skills={plumbing:'skillPlumbing',electric:'skillElectric',gas:'skillGas',sewer:'skillSewer'};
const operations={
 'repair-water-leak':{label:'Repair water leak',skill:'plumbing',target:'Water service meter ID',placeholder:'Stable water meter ID from the map',help:'Requires plumbing. Use a saved water service meter ID.',url:'/water-faults',source:'Inspect water faults to identify the target'},
 'restore-electric-supply':{label:'Restore electric supply',skill:'electric',target:'Electric network edge ID',placeholder:'Enabled edge ID from electric supply inspection',help:'Requires electric. Use an enabled edge ID in the saved electric network, not an electric meter ID.',url:'/network-faults?commodity=electric',source:'Inspect electric supply connections to identify the target'},
 'restore-gas-supply':{label:'Restore gas supply',skill:'gas',target:'Gas network edge ID',placeholder:'Enabled edge ID from gas supply inspection',help:'Requires gas. Use an enabled edge ID in the saved gas network, not a gas meter ID.',url:'/network-faults?commodity=gas',source:'Inspect gas supply connections to identify the target'},
 'clear-sewer-blockage':{label:'Clear sewer blockage',skill:'sewer',target:'Sewer service point ID',placeholder:'Stable SEWER-SP-… identity from sewer inspection',help:'Requires sewer. Inspect the lateral using its source water meter, then copy the displayed sewer service ID. No sewer meter is created.',url:'/sewer',source:'Inspect sewer laterals to identify the target'},
};
let state,pending=null,key,busy=false,after=0;
function message(text,error=false){$('message').textContent=text;$('message').className=error?'error':'';}
async function request(path,body){const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{cache:'no-store'});const data=await response.json();if(!response.ok){const error=Error(data.error||'Request failed.');error.rejected=response.status>=400&&response.status<500;throw error;}return data;}
function controls(){for(const el of document.querySelectorAll('input,button,select'))el.disabled=busy||!!pending;$('retry').hidden=!pending;$('retry').disabled=busy;$('next').disabled=busy||!!pending||!state?.nextAfter;}
function showSkills(selected){const f=$('crew').elements;for(const [skill,name] of Object.entries(skills))if(f[name])f[name].checked=selected.includes(skill);}
function selectedSkills(crew){
 const f=$('crew').elements;
 // Preserve saved behavior if an older cached screen has no skill controls.
 return Object.values(skills).every(name=>f[name])?Object.entries(skills).filter(([,name])=>f[name].checked).map(([skill])=>skill):crew?[...crew.skills]:['plumbing'];
}
function showOperation(clearTarget=false){
 const f=$('assignment').elements;if(!f.operation)return;
 const operation=operations[f.operation.value];if(!operation)return;
 if(clearTarget)f.assetId.value='';
 $('assetLabel').textContent=operation.target;f.assetId.placeholder=operation.placeholder;
 $('operationHelp').textContent=operation.help;$('operationSource').href=operation.url;$('operationSource').textContent=operation.source;
}
function showPending(){
 if(pending?.action==='accept'){
  const f=$('assignment').elements;
  for(const name of ['assignmentId','crewId','operation','assetId','orderId','orderRevision','scheduledDate','reportDelayDays'])if(f[name])f[name].value=pending[name];
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
 const next=await request('/api/field-execution?after='+after);
 if(state&&(next.worldFingerprint!==state.worldFingerprint||next.ownerId!==state.ownerId))throw Error('World or field owner changed. Reload this page.');
 if(!state&&next.crews.length&&!next.crews.some(c=>c.id===$('crew').elements.crewId.value.trim()))$('crew').elements.crewId.value=next.crews[0].id;
 state=next;hydrateCrew();$('identity').textContent=`${state.environmentId} · ${state.ownerId}`;
 $('today').textContent=`Current world day: ${state.through}. Visits run before that day's next physical simulation.`;
 $('assignment').elements.scheduledDate.value||=state.through;
 $('crews').textContent=state.crews.length?state.crews.map(c=>`${c.id}: ${c.daily_capacity} visits/day shared across ${c.skills.length?c.skills.join(', '):'no enabled skills'}, revision ${c.revision}`).join(' · '):'No crews registered.';
 $('history').innerHTML=state.items.length?state.items.map(item=>{const a=item.assignment,r=item.result,operation=operations[a.operation||'repair-water-leak'];return `<tr><td><code>${esc(a.assignmentId)}</code><br>${esc(a.orderId)} · revision ${esc(a.orderRevision)}</td><td>${esc(operation?.label||a.operation)}<br>Skill: ${esc(operation?.skill||'Unknown')}<br>${esc(a.assetId)}<br>${esc(a.crewId)}</td><td>${esc(a.scheduledDate)}</td><td><span class="badge">${esc(r?.outcome||item.state)}</span><br>${esc(r?.effectiveDate||item.blockedReason||'Ready for a due visit')}</td><td>${item.messages.map(m=>`${m.id===r?.reportId?'Report':'Dispatch acknowledgement'}: <strong>${esc(m.state)}</strong><br>Available ${esc(m.available_day)} · ${esc(m.attempts)} attempt(s)${m.last_error?'<br>'+esc(m.last_error):''}`).join('<hr>')}</td></tr>`;}).join(''):'<tr><td colspan="5">No accepted assignments.</td></tr>';
 showOperation();
 controls();
}
async function send(fields){
 if(busy)return;
 if(!pending){pending={schemaVersion:'field-world-execution/1',commandId:crypto.randomUUID(),environmentId:state.environmentId,worldFingerprint:state.worldFingerprint,actorId:'world-admin',effectiveDate:state.through,causalReference:'local-field-admin',...fields};try{sessionStorage.setItem(key,JSON.stringify(pending));}catch{pending=null;message('Could not retain this command for safe retry. Enable session storage before submitting.',true);return;}}
 busy=true;controls();message('Recording field command…');
 try{await request('/api/field-execution',pending);pending=null;sessionStorage.removeItem(key);await load();message('Field command recorded. Physical execution and report delivery remain separate.');}
 catch(error){if(error.rejected){pending=null;sessionStorage.removeItem(key);}message(error.message+(pending?' The outcome is uncertain. Retry the same retained command.':''),true);}
 finally{busy=false;controls();}
}
$('crew').elements.crewId.onchange=hydrateCrew;
$('crew').onsubmit=event=>{event.preventDefault();const f=event.target.elements,crew=state.crews.find(c=>c.id===f.crewId.value.trim());return send({action:'configure-crew',crewId:f.crewId.value.trim(),expectedRevision:crew?.revision||0,skills:selectedSkills(crew),weekdays:f.weekdays.value?f.weekdays.value.split(',').map(Number):[],dailyCapacity:Number(f.dailyCapacity.value)});};
$('assignment').onsubmit=event=>{event.preventDefault();const f=event.target.elements;return send({action:'accept',assignmentId:f.assignmentId.value.trim(),crewId:f.crewId.value.trim(),assetId:f.assetId.value.trim(),orderId:f.orderId.value.trim(),orderRevision:Number(f.orderRevision.value),scheduledDate:f.scheduledDate.value,operation:f.operation?.value||'repair-water-leak',reportDelayDays:Number(f.reportDelayDays.value)});};
if($('assignment').elements.operation)$('assignment').elements.operation.onchange=()=>showOperation(true);
$('run').onclick=async()=>{if(busy||pending)return;busy=true;controls();message('Executing due visits…');try{const result=await request('/api/field-execution/run-due',{environmentId:state.environmentId,worldFingerprint:state.worldFingerprint,effectiveDate:state.through});await load();message(`Due visits processed: ${Array.isArray(result)?result.length:(result.results||[]).length}. Reports remain in the delivery queue.`);}catch(error){message(error.message+' Refresh status before running again; committed physical actions recover without repeating repairs.',true);}finally{busy=false;controls();}};
$('retry').onclick=()=>send();$('refresh').onclick=()=>load().catch(e=>message(e.message,true));$('first').onclick=()=>{after=0;load().catch(e=>message(e.message,true));};$('next').onclick=()=>{after=state.nextAfter;load().catch(e=>message(e.message,true));};
try{await load();key='field-execution-pending:'+state.worldFingerprint+':'+state.ownerId;pending=JSON.parse(sessionStorage.getItem(key)||'null');showPending();message(pending?'A retained command needs its result confirmed. Retry the same command.':'Administrator scenario controls are ready.');controls();}catch(error){message(error.message,true);document.querySelectorAll('button').forEach(b=>b.disabled=true);}
