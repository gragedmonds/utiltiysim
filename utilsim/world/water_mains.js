const $=id=>document.getElementById(id);
const esc=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let record,pending=null,key,busy=false;
function message(text,error=false){$('message').textContent=text;$('message').className=error?'error':'';}
async function request(path,body){const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{cache:'no-store'});const data=await response.json();if(!response.ok){const error=Error(data.error||'Request failed.');error.rejected=response.status>=400&&response.status<500;throw error;}return data;}
function controls(){
 for(const el of document.querySelectorAll('input,button,select'))el.disabled=busy||!!pending||!record;
 $('retry').hidden=!pending;$('retry').disabled=busy;
 for(const [id,cursor] of [['next','nextAfter'],['older','nextBefore'],['servicesNext','nextServiceAfter'],['lossOlder','nextDay']])$(id).disabled=busy||!!pending||!record?.[cursor];
 for(const el of $('start').elements)el.disabled=busy||!!pending||!record?.selected?.enabled||!!record?.selected?.active;
 const active=record?.selected?.active;
 for(const el of $('action').elements)el.disabled=busy||!!pending||!active;
 for(const option of $('action').elements.action.options)option.disabled=({isolate:'broken',repair:'isolated',restore:'repaired'}[option.value]!==active?.status)||(option.value==='isolate'&&!record?.selected?.isolationEdges);
 $('action').querySelector('button').disabled=busy||!!pending||!active||[...$('action').elements.action.options].every(o=>o.disabled);
}
async function load({after='',before=null,serviceAfter='',beforeDay=null}={}){
 const query=new URLSearchParams();if($('edge').value.trim())query.set('edgeId',$('edge').value.trim());for(const [k,v] of Object.entries({after,before,serviceAfter,beforeDay}))if(v)query.set(k,v);
 const next=await request('/api/water-mains?'+query);
 if(record&&record.worldFingerprint!==next.worldFingerprint)throw Error('World identity changed. Reload this page.');
 record=next;$('identity').textContent=record.environmentId;
 $('summary').textContent=`${record.interruptedServices} commissioned water services currently interrupted. Up to 25 mains per page.`;
 $('catalog').innerHTML=record.edges.map(e=>`<tr><td>${esc(e.id)}</td><td>${esc(e.material)} / ${esc(e.lengthM)} m</td><td>${esc(e.active?.status||(e.enabled?'Available':'Normally closed'))}</td><td><button data-edge="${esc(e.id)}">Inspect ${esc(e.id)}</button></td></tr>`).join('');
 for(const button of $('catalog').querySelectorAll('button'))button.onclick=()=>{$('edge').value=button.dataset.edge;reload();};
 const s=record.selected;$('detail').hidden=!s;
 if(s){
  $('current').textContent=`${s.id} · ${s.active?.status||'Available'} · revision ${s.revision}`;
  $('impact').textContent=s.isolationEdges?`${record.affectedServiceCount} commissioned services would be without supply with this isolation and other current closures.`:'The saved valves do not bound this section away from supply. Isolation cannot be recorded here.';
  $('date').textContent=`Next day to simulate: ${record.through}. Saved endpoints: ${s.a} → ${s.b}.`;
  $('valves').textContent='Isolation removes these saved edges: '+(s.isolationEdges?.join(', ')||'Unavailable');
  $('sample').textContent=`${record.affectedSample.length} of ${record.affectedServiceCount}: `+(record.affectedSample.map(x=>x.premise+' / '+x.asset).join(', ')||'None');
  $('history').innerHTML=record.history.map(f=>`<tr><td>${esc(f.opened_date)}</td><td>${esc(f.status)}</td><td>${esc(f.id)} / ${esc(f.source)}</td><td>${esc(f.work_order)}</td></tr>`).join('')||'<tr><td colspan="4">No faults recorded.</td></tr>';
  $('losses').innerHTML=record.losses.map(d=>`<tr><td>${esc(d.day)}</td><td>${esc(d.status)}</td><td>${esc(d.loss_m3)}</td><td>${esc(d.fault_id)}</td></tr>`).join('')||'<tr><td colspan="4">No processed loss days.</td></tr>';
  $('action').elements.action.value={broken:'isolate',isolated:'repair',repaired:'restore'}[s.active?.status]||'isolate';
 }
 for(const k of ['breaksPer100kmYear','lossM3PerHour'])$('policy').elements[k].value=record.policy[k];controls();
}
async function reload(args){try{await load(args);}catch(error){record=null;controls();message(error.message,true);}}
async function send(fields){
 if(busy)return;
 if(!pending){
  pending={schemaVersion:'world-water-mains/1',commandId:crypto.randomUUID(),environmentId:record.environmentId,worldFingerprint:record.worldFingerprint,
   actorId:'world-admin',effectiveDate:record.through,causalReference:'local-world-controls',expectedRevision:fields.action==='configure'?record.policy.revision:record.selected.revision,
   ...(fields.action==='configure'?{}:{edgeId:record.selected.id}),...fields};
  try{sessionStorage.setItem(key,JSON.stringify({edge:$('edge').value,command:pending}));}catch{pending=null;message('Enable session storage so commands can be retained for retry.',true);return;}
 }
 busy=true;controls();message('Recording physical-world action…');
 try{const result=await request('/api/water-mains',pending);pending=null;sessionStorage.removeItem(key);await load();message(`Physical action recorded for ${result.effectiveDate}. Enterprise reports remain separate.`);}
 catch(error){if(error.rejected){pending=null;sessionStorage.removeItem(key);}message(error.message+(pending?' Outcome uncertain: retry the retained command.':' Reload before trying again.'),true);}
 finally{busy=false;controls();}
}
$('find').onsubmit=event=>{event.preventDefault();reload();};
$('start').onsubmit=event=>{event.preventDefault();const f=event.target.elements;send({action:'start',lossM3PerHour:Number(f.lossM3PerHour.value),reason:f.reason.value.trim()});};
$('action').onsubmit=event=>{event.preventDefault();const f=event.target.elements;send({action:f.action.value,faultId:record.selected.active.id,workOrderId:f.workOrderId.value.trim(),reason:f.reason.value.trim()});};
$('policy').onsubmit=event=>{event.preventDefault();const f=event.target.elements;send({action:'configure',breaksPer100kmYear:Number(f.breaksPer100kmYear.value),lossM3PerHour:Number(f.lossM3PerHour.value),reason:f.reason.value.trim()});};
$('retry').onclick=()=>send();$('first').onclick=()=>reload();$('next').onclick=()=>reload({after:record.nextAfter});
$('latest').onclick=$('servicesFirst').onclick=$('lossLatest').onclick=$('first').onclick;
$('older').onclick=()=>reload({before:record.nextBefore});$('servicesNext').onclick=()=>reload({serviceAfter:record.nextServiceAfter});$('lossOlder').onclick=()=>reload({beforeDay:record.nextDay});
try{
 $('edge').value=new URLSearchParams(location.search).get('edgeId')||'';await load();key='world-water-mains-pending:'+record.worldFingerprint;
 const retained=JSON.parse(sessionStorage.getItem(key)||'null');pending=retained?.command||null;
 if(retained){$('edge').value=retained.edge;await load();}
 message(pending?'A retained command needs its result confirmed. Retry the same command.':'Select a main to inspect its physical state.');controls();
}catch(error){message(error.message,true);document.querySelectorAll('button').forEach(b=>b.disabled=true);}
