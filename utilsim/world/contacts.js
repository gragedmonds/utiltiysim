const $=id=>document.getElementById(id);
const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let record,key,pending=null,busy=false;
function message(text,error=false){$('message').textContent=text;$('message').className=error?'error':'';}
async function request(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{cache:'no-store'});const data=await r.json();if(!r.ok){const e=Error(data.error||'Request failed');e.rejected=r.status>=400&&r.status<500;throw e;}return data;}
function controls(){for(const el of document.querySelectorAll('input,button'))el.disabled=busy||!!pending||!record;$('retry').hidden=!pending;$('retry').disabled=busy;$('next').disabled=busy||!!pending||!record?.nextAfter;}
async function load(after=0){
 const next=await request('/api/contacts?after='+after);if(record&&record.worldFingerprint!==next.worldFingerprint)throw Error('World identity changed. Reload the page.');record=next;
 $('identity').textContent=record.environmentId;$('state').textContent=`${record.enabled?(record.policy.active?'Contact generation active':'Contact generation paused'):'Model not enabled'} · revision ${record.policy.revision} · world through ${record.through}`;
 const f=$('policy').elements;f.active.checked=record.policy.active;for(const k of ['noticeProbabilityPerDay','deliveryDelaySeconds','repeatAfterDays','maxContacts'])f[k].value=record.policy[k];
 $('summary').textContent=`${record.counts.pending||0} pending intents; ${record.counts.accepted||0} acknowledged by recipient. Up to 25 per page. This administrator history includes contacts not yet available to recipients.`;
 $('history').innerHTML=record.items.map(r=>{const i=r.intent;return `<tr><td>${esc(i.createdAt)}<br>${esc(i.availableAt)}</td><td>${esc(i.premiseId)}<br>${esc(i.commodity)}</td><td>${i.condition==='no_supply'?'No supply':'Visible overflow'}</td><td>${esc(i.attempt)}<br>${esc(i.previousContactId)}</td><td>${r.available?'Available':'Delayed'} · ${esc(r.state)}<br>${r.attempts} delivery attempts${r.last_error?'<br>'+esc(r.last_error):''}</td><td>${esc(i.id)}</td></tr>`;}).join('')||'<tr><td colspan="6">No contact intents recorded.</td></tr>';controls();
}
async function send(){
 if(busy)return;
 if(!pending){const f=$('policy').elements;pending={schemaVersion:'world-contacts/1',commandId:crypto.randomUUID(),environmentId:record.environmentId,worldFingerprint:record.worldFingerprint,actorId:'world-admin',expectedRevision:record.policy.revision,effectiveDate:record.through,action:'configure',reason:f.reason.value.trim(),causalReference:'local-world-controls',active:f.active.checked};for(const k of ['noticeProbabilityPerDay','deliveryDelaySeconds','repeatAfterDays','maxContacts'])pending[k]=Number(f[k].value);
  try{sessionStorage.setItem(key,JSON.stringify(pending));}catch{pending=null;message('Enable session storage to retain commands for retry.',true);return;}}
 busy=true;controls();message('Saving contact behavior…');try{await request('/api/contacts',pending);pending=null;sessionStorage.removeItem(key);await load();message('Behavior saved. Advance the world to process customer experiences.');}
 catch(e){if(e.rejected){pending=null;sessionStorage.removeItem(key);}message(e.message+(pending?' Outcome uncertain: retry the retained command.':' Reload before changing the policy.'),true);}finally{busy=false;controls();}
}
$('policy').onsubmit=e=>{e.preventDefault();send();};$('retry').onclick=send;
$('first').onclick=()=>load().catch(e=>message(e.message,true));$('next').onclick=()=>load(record.nextAfter).catch(e=>message(e.message,true));
try{await load();key='world-contacts-pending:'+record.worldFingerprint;pending=JSON.parse(sessionStorage.getItem(key)||'null');message(pending?'A retained command needs its result confirmed. Retry the same command.':'Configure awareness, then advance a physical scenario.');controls();}catch(e){message(e.message,true);record=null;controls();}
