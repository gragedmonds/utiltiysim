const $=id=>document.getElementById(id);
const esc=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state,pending=null,key,busy=false,after=0;
function message(text,error=false){$('message').textContent=text;$('message').className=error?'error':'';}
async function request(path,body){const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{cache:'no-store'});const data=await response.json();if(!response.ok){const error=Error(data.error||'Request failed.');error.rejected=response.status>=400&&response.status<500;throw error;}return data;}
function controls(){for(const el of document.querySelectorAll('input,button,select'))el.disabled=busy||!!pending;$('retry').hidden=!pending;$('retry').disabled=busy;$('next').disabled=busy||!!pending||!state?.nextAfter;}
async function load(){
 const next=await request('/api/field-execution?after='+after);
 if(state&&(next.worldFingerprint!==state.worldFingerprint||next.ownerId!==state.ownerId))throw Error('World or field owner changed. Reload this page.');
 state=next;$('identity').textContent=`${state.environmentId} · ${state.ownerId}`;
 $('today').textContent=`Current world day: ${state.through}. Visits run before that day's next physical simulation.`;
 $('assignment').elements.scheduledDate.value||=state.through;
 $('crews').textContent=state.crews.length?state.crews.map(c=>`${c.id}: ${c.daily_capacity} visits/day, revision ${c.revision}`).join(' · '):'No crews registered.';
 $('history').innerHTML=state.items.length?state.items.map(item=>{const a=item.assignment,r=item.result;return `<tr><td><code>${esc(a.assignmentId)}</code><br>${esc(a.orderId)} · revision ${esc(a.orderRevision)}</td><td>${esc(a.assetId)}<br>${esc(a.crewId)}</td><td>${esc(a.scheduledDate)}</td><td><span class="badge">${esc(r?.outcome||item.state)}</span><br>${esc(r?.effectiveDate||item.blockedReason||'Ready for a due visit')}</td><td>${item.messages.map(m=>`${m.id===r?.reportId?'Report':'Dispatch acknowledgement'}: <strong>${esc(m.state)}</strong><br>Available ${esc(m.available_day)} · ${esc(m.attempts)} attempt(s)${m.last_error?'<br>'+esc(m.last_error):''}`).join('<hr>')}</td></tr>`;}).join(''):'<tr><td colspan="5">No accepted assignments.</td></tr>';
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
$('crew').onsubmit=event=>{event.preventDefault();const f=event.target.elements;send({action:'configure-crew',crewId:f.crewId.value.trim(),expectedRevision:state.crews.find(c=>c.id===f.crewId.value.trim())?.revision||0,skills:['plumbing'],weekdays:f.weekdays.value?f.weekdays.value.split(',').map(Number):[],dailyCapacity:Number(f.dailyCapacity.value)});};
$('assignment').onsubmit=event=>{event.preventDefault();const f=event.target.elements;send({action:'accept',assignmentId:f.assignmentId.value.trim(),crewId:f.crewId.value.trim(),assetId:f.assetId.value.trim(),orderId:f.orderId.value.trim(),orderRevision:Number(f.orderRevision.value),scheduledDate:f.scheduledDate.value,operation:'repair-water-leak',reportDelayDays:Number(f.reportDelayDays.value)});};
$('run').onclick=async()=>{if(busy||pending)return;busy=true;controls();message('Executing due visits…');try{const result=await request('/api/field-execution/run-due',{environmentId:state.environmentId,worldFingerprint:state.worldFingerprint,effectiveDate:state.through});await load();message(`Due visits processed: ${Array.isArray(result)?result.length:(result.results||[]).length}. Reports remain in the delivery queue.`);}catch(error){message(error.message+' Refresh status before running again; committed physical actions recover without repeating repairs.',true);}finally{busy=false;controls();}};
$('retry').onclick=()=>send();$('refresh').onclick=()=>load().catch(e=>message(e.message,true));$('first').onclick=()=>{after=0;load().catch(e=>message(e.message,true));};$('next').onclick=()=>{after=state.nextAfter;load().catch(e=>message(e.message,true));};
try{await load();key='field-execution-pending:'+state.worldFingerprint+':'+state.ownerId;pending=JSON.parse(sessionStorage.getItem(key)||'null');message(pending?'A retained command needs its result confirmed. Retry the same command.':'Administrator scenario controls are ready.');controls();}catch(error){message(error.message,true);document.querySelectorAll('button').forEach(b=>b.disabled=true);}
