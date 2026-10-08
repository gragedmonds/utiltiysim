const $=id=>document.getElementById(id);
const esc=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const families={electric:'Electricity',gas:'Gas',water:'Water',sewer:'Sewer'};
const fields={ageYears:[0,10000,'Age'],annualAgeIncrease:[0,1,'Annual age increase'],coldBelowC:[-80,60,'Cold threshold'],coldMultiplier:[1,100,'Cold multiplier']};
let record,pending=null,key,busy=false;
function message(text,error=false){$('message').textContent=text;$('message').className=error?'error':'';}
function controls(){document.querySelectorAll('input,button').forEach(el=>el.disabled=busy||!!pending);$('retry').hidden=!pending;$('retry').disabled=busy;$('older').disabled=busy||!!pending||!record?.nextBefore;}
async function request(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{cache:'no-store'});const data=await r.json();if(!r.ok){const e=Error(data.error||'Request failed.');e.rejected=r.status>=400&&r.status<500;throw e;}return data;}
async function load(before=null){
 const next=await request('/api/hazards'+(before?'?before='+encodeURIComponent(before):''));
 if(record&&record.worldFingerprint!==next.worldFingerprint)throw Error('World identity changed. Reload this page.');record=next;
 $('identity').textContent=record.environmentId;$('state').textContent=(!record.enabled?'Model not enabled':record.policy.active?'Age and cold-weather effects active':'Modifiers paused; existing flat rates apply')+' · revision '+record.policy.revision;
 $('date').textContent='Next day to simulate: '+record.through;$('active').checked=record.policy.active;
 $('profiles').innerHTML=Object.entries(families).map(([f,label])=>`<tr><th>${label}</th>${Object.entries(fields).map(([k,[min,max,name]])=>`<td><input aria-label="${label} ${name}" id="${f}-${k}" type="number" min="${min}" max="${max}" step="any" required value="${k==='ageYears'?record.currentAges[f].toFixed(4):record.policy.profiles[f][k]}"></td>`).join('')}<td>${record.basePolicies[f].enabled?(100*record.basePolicies[f].annualProbability).toFixed(2)+'%':'Model not enabled'}</td></tr>`).join('');
 $('history').innerHTML=record.history.length?record.history.map(h=>`<tr><td>${esc(h.day)}</td><td>${h.temperatureC} °C</td>${Object.keys(families).map(f=>`<td>${h.multipliers[f].toFixed(2)}×<br>${(h.dailyProbabilities[f]*100).toFixed(4)}% daily<br>${h.ageYears[f].toFixed(2)} years</td>`).join('')}</tr>`).join(''):'<tr><td colspan="6">No infrastructure risk days recorded.</td></tr>';
 $('evidence').textContent=record.history[0]?'Latest displayed cause: '+record.history[0].eventId+' · policy revision '+record.history[0].policy.revision:'';controls();
}
async function send(){
 if(busy)return;
 if(!pending){const profiles={};for(const f of Object.keys(families)){profiles[f]={};for(const k of Object.keys(fields))profiles[f][k]=k==='ageYears'&&$(f+'-'+k).value===record.currentAges[f].toFixed(4)?record.currentAges[f]:Number($(f+'-'+k).value);}
 pending={schemaVersion:'world-hazards/1',commandId:crypto.randomUUID(),environmentId:record.environmentId,worldFingerprint:record.worldFingerprint,actorId:'world-admin',expectedRevision:record.policy.revision,effectiveDate:record.through,action:'configure',reason:$('reason').value.trim(),causalReference:'local-world-controls',active:$('active').checked,profiles};
 try{sessionStorage.setItem(key,JSON.stringify(pending));}catch{pending=null;message('Could not retain the command. Enable session storage before saving.',true);return;}}
 busy=true;controls();message('Recording infrastructure assumptions…');
 try{const result=await request('/api/hazards',pending);pending=null;sessionStorage.removeItem(key);await load();message('Infrastructure risk saved for '+result.effectiveDate+'. Existing faults remain unchanged.');}
 catch(e){if(e.rejected){pending=null;sessionStorage.removeItem(key);}message(e.message+(pending?' Outcome uncertain; retry the retained command.':' Reload before trying again.'),true);}
 finally{busy=false;controls();}
}
$('policy').onsubmit=e=>{e.preventDefault();send();};$('retry').onclick=send;$('latest').onclick=()=>load().catch(e=>message(e.message,true));$('older').onclick=()=>load(record.nextBefore).catch(e=>message(e.message,true));
try{await load();key='world-hazards-pending:'+record.worldFingerprint;pending=JSON.parse(sessionStorage.getItem(key)||'null');message(pending?'A retained command needs confirmation. Retry the same command.':'Review the explicit age and weather assumptions before saving.');controls();}
catch(e){message(e.message,true);document.querySelectorAll('button').forEach(el=>el.disabled=true);}
