const $=id=>document.getElementById(id);
const esc=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let world,record,pending=null,key,busy=false;
function message(text,error=false){$('message').textContent=text;$('message').className=error?'error':'';}
async function request(path,body){const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{cache:'no-store'});const data=await response.json();if(!response.ok){const error=Error(data.error||'Request failed.');error.rejected=response.status>=400&&response.status<500;throw error;}return data;}
function controls(){
 for(const el of document.querySelectorAll('input,button'))el.disabled=busy||!!pending;
 $('retry').hidden=!pending;$('retry').disabled=busy;
 $('older').disabled=busy||!!pending||!record?.nextBefore;$('olderFlows').disabled=busy||!!pending||!record?.nextDay;
 for(const el of $('start').elements)el.disabled=busy||!!pending||!record||!!record.current.active;
 for(const el of $('clear').elements)el.disabled=busy||!!pending||!record?.current.active;
 for(const el of $('policy').elements)el.disabled=busy||!!pending||!record;
}
async function load({before=null,beforeDay=null}={}){
 const query=new URLSearchParams({waterAssetId:$('asset').value.trim()});if(before)query.set('before',before);if(beforeDay)query.set('beforeDay',beforeDay);
 record=await request('/api/sewer?'+query);
 if(record.worldFingerprint!==world.worldFingerprint)throw Error('World identity changed. Reload this page.');
 $('service').hidden=false;
 $('current').textContent=`${!record.enabled?'Lateral model not enabled':record.current.active?'Blocked: '+record.current.active.capacity+' m³/day remaining capacity':'Clear lateral'} · ${record.current.retained} m³ retained · revision ${record.current.revision}`;
 $('date').textContent=`Next day to simulate: ${record.through}. Premise ${record.service.premise}.`;
 $('identityDetail').textContent=`Sewer service ${record.service.id} · Physical asset ${record.service.lateral} · Water source ${record.service.water_asset}`;
 $('history').innerHTML=record.history.length?record.history.map(f=>`<tr><td>${esc(f.opened_date)}</td><td>${esc(f.cleared_date||'Active')}</td><td>${esc(f.capacity)}</td><td>${esc(f.source)}</td><td><code>${esc(f.id)}</code></td><td>${esc(f.work_order)}</td></tr>`).join(''):'<tr><td colspan="6">No blockages recorded.</td></tr>';
 $('flows').innerHTML=record.flows.length?record.flows.map(f=>`<tr><td>${esc(f.day)}</td><td>${esc(f.previous_retained)}</td><td>${esc(f.inflow)}</td><td>${esc(f.transported)}</td><td>${esc(f.retained)}</td><td>${esc(f.overflow)}</td></tr>`).join(''):'<tr><td colspan="6">No physical sewer days recorded. Configure the policy or start a blockage to enable this model.</td></tr>';
 for(const field of ['annualProbability','returnFactor','storageM3','blockedCapacityM3PerDay'])$('policy').elements[field].value=record.policy[field];controls();
}
async function send(fields){
 if(busy)return;
 if(!pending){
  pending={schemaVersion:'world-sewer/1',commandId:crypto.randomUUID(),environmentId:world.environmentId,
   worldFingerprint:world.worldFingerprint,actorId:'world-admin',effectiveDate:record.through,causalReference:'local-world-controls',
   expectedRevision:fields.action==='configure'?record.policy.revision:record.current.revision,
   ...(fields.action==='configure'?{}:{waterAssetId:record.service.water_asset,servicePointId:record.service.id}),...fields};
  try{sessionStorage.setItem(key,JSON.stringify({waterAssetId:record.service.water_asset,command:pending}));}
  catch{pending=null;message('Could not retain the command for retry. Enable session storage before submitting.',true);return;}
 }
 busy=true;controls();message('Recording physical-world command…');
 try{const result=await request('/api/sewer',pending);pending=null;sessionStorage.removeItem(key);await load();message(`Physical-world command completed for ${result.effectiveDate}. Future daily processing uses the recorded state.`);}
 catch(error){if(error.rejected){pending=null;sessionStorage.removeItem(key);}message(error.message+(pending?' The outcome is uncertain. Retry the retained command.':' Reload the service before trying again.'),true);}
 finally{busy=false;controls();}
}
$('find').onsubmit=async event=>{event.preventDefault();try{await load();message('Sewer service loaded.');}catch(error){record=null;$('service').hidden=true;controls();message(error.message,true);}};
$('start').onsubmit=event=>{event.preventDefault();const f=event.target.elements;send({action:'start',capacityM3PerDay:f.capacityM3PerDay.value,reason:f.reason.value.trim()});};
$('clear').onsubmit=event=>{event.preventDefault();const f=event.target.elements;send({action:'clear',faultId:record.current.active.id,workOrderId:f.workOrderId.value.trim(),reason:f.reason.value.trim()});};
$('policy').onsubmit=event=>{event.preventDefault();const f=event.target.elements;send({action:'configure',annualProbability:Number(f.annualProbability.value),returnFactor:f.returnFactor.value,storageM3:f.storageM3.value,blockedCapacityM3PerDay:f.blockedCapacityM3PerDay.value,reason:f.reason.value.trim()});};
$('retry').onclick=()=>send();$('older').onclick=()=>load({before:record.nextBefore}).catch(error=>message(error.message,true));$('latest').onclick=()=>load().catch(error=>message(error.message,true));$('latestFlows').onclick=$('latest').onclick;$('olderFlows').onclick=()=>load({beforeDay:record.nextDay}).catch(error=>message(error.message,true));
try{
 world=await request('/api/state');if(!world.environmentId)throw Error('Initialize a world in World controls first.');
 key='world-sewer-pending:'+world.worldFingerprint;const retained=JSON.parse(sessionStorage.getItem(key)||'null');pending=retained?.command||null;
 $('identity').textContent=world.environmentId;
 const selected=retained?.waterAssetId||new URLSearchParams(location.search).get('waterAssetId');if(selected){$('asset').value=selected;await load();}
 message(pending?'A retained command needs its result confirmed. Retry the same command.':'Load a source water service to inspect its sewer lateral.');controls();
}catch(error){message(error.message,true);document.querySelectorAll('button').forEach(button=>button.disabled=true);}
