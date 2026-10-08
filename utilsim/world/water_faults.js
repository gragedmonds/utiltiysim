const $=id=>document.getElementById(id);
const esc=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let world,record,pending=null,key,busy=false;
function message(text,error=false){$('message').textContent=text;$('message').className=error?'error':'';}
async function request(path,body){const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{cache:'no-store'});const data=await response.json();if(!response.ok){const error=Error(data.error||'Request failed.');error.rejected=response.status>=400&&response.status<500;throw error;}return data;}
function controls(){
 for(const el of document.querySelectorAll('input,button'))el.disabled=busy||!!pending;
 $('retry').hidden=!pending;$('retry').disabled=busy;$('older').disabled=busy||!!pending||!record?.nextBefore;
 if(record){for(const el of $('start').elements)el.disabled=busy||!!pending||!!record.current.active;for(const el of $('repair').elements)el.disabled=busy||!!pending||!record.current.active;}
}
async function load(before){
 record=await request('/api/water-faults?assetId='+encodeURIComponent($('asset').value.trim())+(before?'&before='+before:''));
 if(record.worldFingerprint!==world.worldFingerprint)throw Error('World identity changed. Reload this page.');
 $('service').hidden=false;
 const active=record.current.active;
 $('current').textContent=`${record.assetId} · Meter ${record.meterCondition} · ${active?'Active leak: '+active.rate+' m³/hour':'No active leak'}`;
 $('date').textContent=`Next day to simulate: ${record.through}. Premise ${record.premiseId}; current device ${record.deviceId}.`;
 $('revision').textContent=`Service revision ${record.current.revision}. Up to 25 faults, newest started first.`;
 $('history').innerHTML=record.history.length?record.history.map(f=>`<tr><td>${esc(f.opened_date)}</td><td>${esc(f.repaired_date||'Active')}</td><td>${esc(f.rate)}</td><td>${esc(f.source)}</td><td><code>${esc(f.id)}</code></td><td>${esc(f.work_order)}</td></tr>`).join(''):'<tr><td colspan="6">No leaks recorded.</td></tr>';
 $('policy').elements.annualProbability.value=record.policy.annualProbability;$('policy').elements.leakM3PerHour.value=record.policy.leakM3PerHour;controls();
}
async function send(fields){
 if(busy)return;
 if(!pending){
  pending={schemaVersion:'world-water-faults/1',commandId:crypto.randomUUID(),environmentId:world.environmentId,
   worldFingerprint:world.worldFingerprint,actorId:'world-admin',causalReference:'local-world-controls',
   expectedRevision:fields.action==='configure'?record.policy.revision:record.current.revision,
   ...(fields.action==='configure'?{}:{assetId:record.assetId}),...fields};
  try{sessionStorage.setItem(key,JSON.stringify({assetId:record.assetId,command:pending}));}catch{pending=null;message('Could not retain the command for retry. Enable session storage before submitting.',true);return;}
 }
 busy=true;controls();message('Recording world command…');
 try{const result=await request('/api/water-faults',pending);pending=null;sessionStorage.removeItem(key);await load();message(`Physical-world command completed for ${result.effectiveDate}. Future daily processing uses the recorded state.`);}
 catch(error){if(error.rejected){pending=null;sessionStorage.removeItem(key);}message(error.message+(pending?' The outcome is uncertain. Retry the retained command to recover its result.':' Reload the service before trying again.'),true);}
 finally{busy=false;controls();}
}
$('find').onsubmit=async event=>{event.preventDefault();try{await load();message('Service loaded.');}catch(error){record=null;$('service').hidden=true;message(error.message,true);}};
$('start').onsubmit=event=>{event.preventDefault();const f=event.target.elements;send({action:'start',leakM3PerHour:f.leakM3PerHour.value,reason:f.reason.value.trim()});};
$('repair').onsubmit=event=>{event.preventDefault();const f=event.target.elements;send({action:'repair',faultId:record.current.active.id,workOrderId:f.workOrderId.value.trim(),reason:f.reason.value.trim()});};
$('policy').onsubmit=event=>{event.preventDefault();const f=event.target.elements;send({action:'configure',annualProbability:Number(f.annualProbability.value),leakM3PerHour:f.leakM3PerHour.value,reason:f.reason.value.trim()});};
$('retry').onclick=()=>send();$('older').onclick=()=>load(record.nextBefore).catch(error=>message(error.message,true));$('latest').onclick=()=>load().catch(error=>message(error.message,true));
try{
 world=await request('/api/state');if(!world.environmentId)throw Error('Initialize a world in World controls first.');
 key='world-water-faults-pending:'+world.worldFingerprint;const retained=JSON.parse(sessionStorage.getItem(key)||'null');pending=retained?.command||null;
 $('identity').textContent=world.environmentId;
 const selected=retained?.assetId||new URLSearchParams(location.search).get('assetId');if(selected){$('asset').value=selected;await load();}
 message(pending?'A retained command needs its result confirmed. Retry the same command.':'Load a water service to inspect or change its physical state.');controls();
}catch(error){message(error.message,true);document.querySelectorAll('button').forEach(button=>button.disabled=true);}
