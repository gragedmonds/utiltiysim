const $=id=>document.getElementById(id);
const esc=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let world,record,pending=null,key,busy=false,offset=0,count=0,selected=null;
function message(text,error=false){$('message').textContent=text;$('message').className=error?'error':'';}
async function request(path,body){
 const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{cache:'no-store'});
 const data=await response.json();if(!response.ok){const error=Error(data.error||'Request failed.');error.rejected=response.status>=400&&response.status<500;throw error;}return data;
}
function controls(){
 for(const el of document.querySelectorAll('input,button'))el.disabled=busy||!!pending;
 $('retry').hidden=!pending;$('retry').disabled=busy;
 $('previous').disabled=busy||!!pending||offset===0;$('next').disabled=busy||!!pending||count<25;
}
async function detail(id){
 const data=await request('/api/development?projectId='+encodeURIComponent(id));record=data.projects[0];
 if(!record)throw Error('Project no longer exists. Reload the world.');selected=id;
 $('details').hidden=false;$('detailTitle').textContent=`${record.id} · ${record.premise}`;
 $('detailState').textContent=`${record.phase} · ${record.hold?'Held: '+record.hold:'Active'} · revision ${record.revision}`;
 const actions=record.phase==='occupied'?[]:record.hold?['resume']:['pause','fail'];
 $('actions').innerHTML=actions.map(action=>`<button data-action="${action}">${action==='fail'?'Record construction failure':action[0].toUpperCase()+action.slice(1)}</button>`).join('');
 for(const button of $('actions').querySelectorAll('[data-action]'))button.onclick=()=>{
  const reason=$('actionReason').value.trim();if(!reason){message('Enter a reason before changing the project.',true);return;}
  send({projectId:record.id,expectedRevision:record.revision,action:button.dataset.action,reason});
 };
 $('history').innerHTML=data.history.map(item=>`<tr><td>${esc(item.day)}</td><td>${esc(item.kind)}</td><td>${esc(item.event_id)}</td></tr>`).join('');
 $('notices').innerHTML=data.notifications.length?data.notifications.map(item=>`<tr><td>${esc(item.available_at)}</td><td>${esc(item.state)}</td><td>${esc(item.attempts)}</td></tr>`).join(''):'<tr><td colspan="3">No stage notices yet.</td></tr>';
 controls();
}
async function load(){
 world=await request('/api/development?offset='+offset);count=world.projects.length;
 $('identity').textContent=world.environmentId;$('date').textContent=`Next day to simulate: ${world.through}. Advance days in World controls to progress construction.`;
 for(const name of ['startDate','utilityReadyDate','occupancyDate'])$('plan').elements[name].min=world.through;
 $('projects').innerHTML=count?world.projects.map(item=>`<tr><td>${esc(item.id)}<br>${esc(item.premise)}</td><td>${esc(item.phase)}<br>${esc(item.hold||'Active')}</td><td>${item.work_days} / ${item.plan.constructionDays}</td><td>Ready: ${esc(item.ready_day)}<br>Occupied: ${esc(item.occupied_day)}</td><td><button data-project="${esc(item.id)}">Inspect / manage</button></td></tr>`).join(''):'<tr><td colspan="5">No projects on this page.</td></tr>';
 for(const button of $('projects').querySelectorAll('[data-project]'))button.onclick=()=>detail(button.dataset.project).catch(error=>message(error.message,true));
 if(selected)await detail(selected);controls();
}
async function send(fields){
 if(busy)return;
 if(!pending){
  pending={schemaVersion:'world-development/1',commandId:crypto.randomUUID(),environmentId:world.environmentId,
   worldFingerprint:world.worldFingerprint,actorId:'world-admin',causalReference:'local-world-development-controls',...fields};
  try{sessionStorage.setItem(key,JSON.stringify(pending));}catch{pending=null;message('Enable session storage to retain commands for safe retry.',true);return;}
 }
 busy=true;controls();message('Recording development command…');
 try{
  const result=await request('/api/development',pending);selected=pending.projectId;
  pending=null;sessionStorage.removeItem(key);await load();
  message(`Accepted at revision ${result.revision}. Stages progress when their world day runs.`);
 }catch(error){
  if(error.rejected){pending=null;sessionStorage.removeItem(key);}
  message(error.message+(pending?' Retry the retained command to recover its result.':' Refresh before trying again.'),true);
 }finally{busy=false;controls();}
}
$('plan').onsubmit=event=>{event.preventDefault();const f=event.target.elements;send({action:'plan',expectedRevision:0,
 projectId:f.projectId.value.trim(),premiseId:f.premiseId.value.trim(),startDate:f.startDate.value,
 constructionDays:Number(f.constructionDays.value),utilityReadyDate:f.utilityReadyDate.value,occupancyDate:f.occupancyDate.value,
 occupants:Number(f.occupants.value),notificationDelaySeconds:Number(f.noticeDays.value)*86400,reason:f.reason.value.trim()});};
$('retry').onclick=()=>send();
$('refresh').onclick=()=>load().catch(error=>message(error.message,true));
$('previous').onclick=()=>{offset=Math.max(0,offset-25);load().catch(error=>message(error.message,true));};
$('next').onclick=()=>{offset+=25;load().catch(error=>message(error.message,true));};
try{
 await load();if(!world.environmentId)throw Error('Initialize a world in World controls first.');
 key='world-development-pending:'+world.worldFingerprint;pending=JSON.parse(sessionStorage.getItem(key)||'null');
 const premise=new URLSearchParams(location.search).get('premiseId');if(premise)$('plan').elements.premiseId.value=premise;
 if(pending?.projectId){selected=pending.projectId;try{await detail(selected);}catch{selected=null;}}
 message(pending?'A retained command needs its result confirmed. Retry the same command.':'Plan a saved vacant property or inspect an existing project.');controls();
}catch(error){message(error.message,true);document.querySelectorAll('button').forEach(button=>button.disabled=true);}
