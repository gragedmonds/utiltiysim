const $=id=>document.getElementById(id);
const esc=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let record,pending=null,key,busy=false;
function message(text,error=false){$('message').textContent=text;$('message').className=error?'error':'';}
async function request(path,body){const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{cache:'no-store'});const data=await response.json();if(!response.ok){const error=Error(data.error||'Request failed.');error.rejected=response.status>=400&&response.status<500;throw error;}return data;}
function controls(){
 for(const el of document.querySelectorAll('input,button,select'))el.disabled=busy||!!pending;
 $('retry').hidden=!pending;$('retry').disabled=busy;
 for(const el of $('policy').elements)el.disabled=busy||!!pending||!record;
 $('servicesNext').disabled=busy||!!pending||!record?.nextServiceAfter;
 $('next').disabled=busy||!!pending||!record?.nextAfter;$('older').disabled=busy||!!pending||!record?.nextBefore;
 for(const el of $('start').elements)el.disabled=busy||!!pending||!record?.selected?.enabled||!!record?.selected?.active;
 for(const el of $('restore').elements)el.disabled=busy||!!pending||!record?.selected?.active;
}
async function load({after='',before=null,serviceAfter=''}={}){
 const query=new URLSearchParams({commodity:$('commodity').value});if($('edge').value.trim())query.set('edgeId',$('edge').value.trim());if(after)query.set('after',after);if(before)query.set('before',before);if(serviceAfter)query.set('serviceAfter',serviceAfter);
 const next=await request('/api/network-faults?'+query);
 if(record&&record.worldFingerprint!==next.worldFingerprint)throw Error('World identity changed. Reload this page.');
 record=next;$('identity').textContent=record.environmentId;
 $('summary').textContent=`${record.interruptedServices} services currently interrupted across both utilities. Up to 25 connections per page.`;
 $('catalog').innerHTML=record.edges.map(e=>`<tr><td>${esc(e.id)}</td><td>${esc(e.kind)}</td><td>${e.active?'Fault active':e.enabled?'Available':'Normally open'}</td><td><button data-edge="${esc(e.id)}">Inspect ${esc(e.id)}</button></td></tr>`).join('');
 for(const button of $('catalog').querySelectorAll('button'))button.onclick=()=>{$('edge').value=button.dataset.edge;load().catch(error=>message(error.message,true));};
 const selected=record.selected;$('detail').hidden=!selected;
 if(selected){
  $('current').textContent=`${selected.id} · ${selected.kind} · ${selected.active?'Fault active':selected.enabled?'Available':'Normally open'} · revision ${selected.revision}`;
  $('impact').textContent=`${record.additionalInterruptedServices} additional services would lose supply if this connection failed now. ${record.affectedServiceCount} services in this utility would be interrupted in total, including other active faults.`;
  $('date').textContent=`Next day to simulate: ${record.through}. Saved endpoints: ${selected.a} → ${selected.b}.`;
  $('sample').textContent=`This page: ${record.affectedSample.length} of ${record.affectedServiceCount}: `+(record.affectedSample.map(s=>s.premise+' / '+s.asset).join(', ')||'None.');
  $('history').innerHTML=record.history.length?record.history.map(f=>`<tr><td>${esc(f.opened_date)}</td><td>${esc(f.restored_date||'Active')}</td><td>${esc(f.source)}</td><td><code>${esc(f.id)}</code></td><td>${esc(f.work_order)}</td></tr>`).join(''):'<tr><td colspan="5">No faults recorded.</td></tr>';
 }
 $('policy').elements.annualProbability.value=record.policy.annualProbability;controls();
}
async function send(fields){
 if(busy)return;
 if(!pending){
  pending={schemaVersion:'world-network-faults/1',commandId:crypto.randomUUID(),environmentId:record.environmentId,
   worldFingerprint:record.worldFingerprint,actorId:'world-admin',effectiveDate:record.through,causalReference:'local-world-controls',
   expectedRevision:fields.action==='configure'?record.policy.revision:record.selected.revision,
   ...(fields.action==='configure'?{}:{commodity:record.selected.commodity,edgeId:record.selected.id}),...fields};
  try{sessionStorage.setItem(key,JSON.stringify({commodity:$('commodity').value,edge:$('edge').value,command:pending}));}
  catch{pending=null;message('Could not retain the command for retry. Enable session storage before submitting.',true);return;}
 }
 busy=true;controls();message('Recording physical-world command…');
 try{const result=await request('/api/network-faults',pending);pending=null;sessionStorage.removeItem(key);await load();message(`Physical-world command completed for ${result.effectiveDate}. Future daily processing uses the recorded state.`);}
 catch(error){if(error.rejected){pending=null;sessionStorage.removeItem(key);}message(error.message+(pending?' The outcome is uncertain. Retry the retained command.':' Reload the network before trying again.'),true);}
 finally{busy=false;controls();}
}
$('find').onsubmit=async event=>{event.preventDefault();try{await load();message('Network loaded.');}catch(error){record=null;$('detail').hidden=true;controls();message(error.message,true);}};
$('start').onsubmit=event=>{event.preventDefault();send({action:'start',reason:event.target.elements.reason.value.trim()});};
$('restore').onsubmit=event=>{event.preventDefault();const f=event.target.elements;send({action:'restore',faultId:record.selected.active.id,workOrderId:f.workOrderId.value.trim(),reason:f.reason.value.trim()});};
$('policy').onsubmit=event=>{event.preventDefault();const f=event.target.elements;send({action:'configure',annualProbability:Number(f.annualProbability.value),reason:f.reason.value.trim()});};
$('servicesFirst').onclick=()=>load().catch(error=>message(error.message,true));$('servicesNext').onclick=()=>load({serviceAfter:record.nextServiceAfter}).catch(error=>message(error.message,true));
$('retry').onclick=()=>send();$('next').onclick=()=>load({after:record.nextAfter}).catch(error=>message(error.message,true));$('first').onclick=()=>load().catch(error=>message(error.message,true));$('latest').onclick=$('first').onclick;$('older').onclick=()=>load({before:record.nextBefore}).catch(error=>message(error.message,true));
try{
 const query=new URLSearchParams(location.search);$('commodity').value=query.get('commodity')==='gas'?'gas':'electric';$('edge').value=query.get('edgeId')||'';
 await load();key='world-network-faults-pending:'+record.worldFingerprint;
 const retained=JSON.parse(sessionStorage.getItem(key)||'null');pending=retained?.command||null;
 if(retained){$('commodity').value=retained.commodity;$('edge').value=retained.edge;await load();}
 message(pending?'A retained command needs its result confirmed. Retry the same command.':'Select a connection to inspect or change its physical state.');controls();
}catch(error){message(error.message,true);document.querySelectorAll('button').forEach(button=>button.disabled=true);}
