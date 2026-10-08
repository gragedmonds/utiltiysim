const $=id=>document.getElementById(id);
const esc=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let world,record,pending=null,key,busy=false;
function message(text,error=false){$('message').textContent=text;$('message').className=error?'error':'';}
async function request(path,body){
 const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{cache:'no-store'});
 const data=await response.json();if(!response.ok){const error=Error(data.error||'Request failed.');error.rejected=response.status>=400&&response.status<500;throw error;}return data;
}
function controls(){
 for(const el of document.querySelectorAll('input,select,button'))el.disabled=busy||!!pending;
 $('retry').hidden=!pending;$('retry').disabled=busy;
 $('older').disabled=busy||!!pending||!record?.nextBefore;
 const people=$('schedule').elements.occupants;if($('schedule').elements.occupied.value==='false')people.disabled=true;
}
async function load(before){
 const id=$('premise').value.trim();
 world=await request('/api/state');
 record=await request('/api/occupancy?premiseId='+encodeURIComponent(id)+(before?'&before='+before:''));
 $('property').hidden=false;$('current').textContent=`${id} · ${record.current.occupied?'Occupied':'Vacant'} · ${record.current.occupants} people`;
 $('date').textContent=`Next day to simulate: ${world.through}. Scheduled changes do not alter current occupancy until that day is processed.`;
 $('revision').textContent=`Revision ${record.current.revision}. Showing up to 25 changes, newest scheduled first.`;
 $('schedule').elements.effectiveDate.min=world.through;$('schedule').elements.effectiveDate.value=world.through;
 $('history').innerHTML=record.changes.length?record.changes.map(c=>`<tr><td>${esc(c.effective_date)}</td><td>${c.occupied?'Occupied':'Vacant'} · ${c.occupants}</td><td>${esc(c.status)}</td><td>${esc(c.reason)}</td><td><code>${esc(c.command_id)}</code></td><td>${c.status==='scheduled'?`<button type="button" data-cancel="${esc(c.command_id)}" aria-label="Cancel change on ${esc(c.effective_date)}">Cancel</button>`:'—'}</td></tr>`).join(''):'<tr><td colspan="6">No occupancy changes recorded.</td></tr>';
 for(const button of $('history').querySelectorAll('[data-cancel]'))button.onclick=()=>send({action:'cancel',targetCommandId:button.dataset.cancel,reason:'Administrator cancelled a future occupancy change'});
 controls();
}
async function send(fields){
 if(busy)return;
 if(!pending){
  pending={schemaVersion:'world-occupancy/1',commandId:crypto.randomUUID(),environmentId:world.environmentId,
   worldFingerprint:world.worldFingerprint,actorId:'world-admin',premiseId:record.premiseId,
   expectedRevision:record.current.revision,causalReference:'local-world-controls',...fields};
  try{sessionStorage.setItem(key,JSON.stringify(pending));}catch{pending=null;message('Could not retain the command for safe retry. Enable session storage before submitting.',true);return;}
 }
 busy=true;controls();message('Recording occupancy command…');
 try{
  const result=await request('/api/occupancy',pending);
  pending=null;sessionStorage.removeItem(key);
  await load();message(`Command accepted at revision ${result.revision}. Physical changes apply when their day runs.`);
 }catch(error){
  if(error.rejected){pending=null;sessionStorage.removeItem(key);}
  message(error.message+(pending?' The outcome is uncertain. Retry the retained command to recover its result.':' Reload the property before trying again.'),true);
 }finally{busy=false;controls();}
}
$('find').onsubmit=async event=>{event.preventDefault();try{await load();message('Property loaded.');}catch(error){record=null;$('property').hidden=true;message(error.message,true);}};
$('schedule').onsubmit=event=>{event.preventDefault();const f=event.target.elements;send({action:'schedule',effectiveDate:f.effectiveDate.value,occupied:f.occupied.value==='true',occupants:Number(f.occupants.value),reason:f.reason.value.trim()});};
$('schedule').elements.occupied.onchange=()=>{const f=$('schedule').elements;f.occupants.value=f.occupied.value==='false'?'0':String(Math.max(1,record?.current.occupants||2));f.occupants.min=f.occupied.value==='false'?'0':'1';controls();};
$('retry').onclick=()=>send();
$('older').onclick=()=>load(record.nextBefore).catch(error=>message(error.message,true));
$('latest').onclick=()=>load().catch(error=>message(error.message,true));
try{
 world=await request('/api/state');if(!world.environmentId)throw Error('Initialize a world in World controls first.');
 key='world-occupancy-pending:'+world.worldFingerprint;
 pending=JSON.parse(sessionStorage.getItem(key)||'null');
 $('identity').textContent=world.environmentId;
 const selected=pending?.premiseId||new URLSearchParams(location.search).get('premiseId');
 if(selected){$('premise').value=selected;await load();}
 message(pending?'A retained command needs its result confirmed. Retry the same command.':'Load a property to inspect or schedule occupancy changes.');controls();
}catch(error){message(error.message,true);document.querySelectorAll('button').forEach(button=>button.disabled=true);}
