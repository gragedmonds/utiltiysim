const $=id=>document.getElementById(id);
const esc=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const families=['electric','gas','water','sewer'];
let record,pending=null,key,busy=false,dayCursor=null,eventCursor=null;
function message(text,error=false){$('message').textContent=text;$('message').className=error?'error':'';}
function controls(){document.querySelectorAll('input,button').forEach(el=>el.disabled=busy||!!pending);$('retry').hidden=!pending;$('retry').disabled=busy;$('older').disabled=busy||!!pending||!record?.nextBefore;$('olderEvents').disabled=busy||!!pending||!record?.nextEventsBefore;}
async function request(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{cache:'no-store'});const data=await r.json();if(!r.ok){const e=Error(data.error||'Request failed.');e.rejected=r.status>=400&&r.status<500;throw e;}return data;}
async function load(){
 const args=new URLSearchParams();if(dayCursor)args.set('before',dayCursor);if(eventCursor)args.set('eventsBefore',eventCursor);
 const next=await request('/api/storms?'+args);if(record&&record.worldFingerprint!==next.worldFingerprint)throw Error('World identity changed. Reload this page.');record=next;
 $('identity').textContent=record.environmentId;$('state').textContent='Next physical day: '+record.through+' · revision '+record.revision+(record.enabled?' · Storm scheduling enabled':' · Storm scheduling not enabled');
 $('start').min=record.through;if(!$('start').value){$('start').value=record.through;const day=new Date(record.through+'T00:00:00Z');day.setUTCDate(day.getUTCDate()+3);$('end').value=day.toISOString().slice(0,10);}
 $('events').innerHTML=record.events.length?record.events.map(s=>`<tr><td>${esc(s.stormId)}<br>${esc(s.reason)}</td><td>${esc(s.startDate)} through ${esc(s.endDate)} (exclusive)</td><td>${s.temperatureOffsetC} °C<br>${families.map(f=>esc(f)+': '+s.multipliers[f]+'×').join(' · ')}</td><td>${s.cancelledEventId?'Cancelled':s.endDate<=record.through?'Finished':s.startDate<record.through?'Active':`Scheduled<br><button data-cancel="${esc(s.stormId)}">Cancel before start</button>`}</td></tr>`).join(''):'<tr><td colspan="4">No scheduled events on this page.</td></tr>';
 $('history').innerHTML=record.history.length?record.history.map(h=>`<tr><td>${esc(h.day)}</td><td>${h.baselineTemperatureC} °C</td><td>${h.temperatureC} °C</td><td>${esc(h.stormId)}<br>${esc(h.eventId)}</td></tr>`).join(''):'<tr><td colspan="4">No storm days recorded on this page.</td></tr>';controls();
}
function base(action){return{schemaVersion:'world-storms/1',commandId:crypto.randomUUID(),environmentId:record.environmentId,worldFingerprint:record.worldFingerprint,actorId:'world-admin',expectedRevision:record.revision,effectiveDate:record.through,action,reason:$('reason').value.trim(),causalReference:'local-world-controls'};}
async function send(command){
 if(busy)return;if(!pending){pending=command;try{sessionStorage.setItem(key,JSON.stringify(pending));}catch{pending=null;message('Could not retain the command. Enable session storage before saving.',true);return;}}
 busy=true;controls();message('Recording storm scenario…');
 try{const result=await request('/api/storms',pending);pending=null;sessionStorage.removeItem(key);dayCursor=null;eventCursor=null;await load();message('Storm command recorded · revision '+result.revision+'. Physical changes occur only when the world advances.');}
 catch(e){if(e.rejected){pending=null;sessionStorage.removeItem(key);}message(e.message+(pending?' Outcome uncertain; retry the retained command.':' Reload the latest events before trying again.'),true);}
 finally{busy=false;controls();}
}
$('storm').onsubmit=e=>{e.preventDefault();const multipliers=Object.fromEntries(families.map(f=>[f,Number($(f).value)]));send({...base('schedule'),startDate:$('start').value,endDate:$('end').value,temperatureOffsetC:Number($('temperature').value),multipliers});};
$('events').onclick=e=>{const button=e.target.closest('button[data-cancel]');if(button){if(!$('reason').value.trim()){message('Enter the cancellation reason in Scenario evidence first.',true);$('reason').focus();return;}send({...base('cancel'),stormId:button.dataset.cancel});}};
$('retry').onclick=()=>send();
async function page(kind,value){if(busy||pending)return;busy=true;controls();if(kind==='day')dayCursor=value;else eventCursor=value;try{await load();}catch(e){message(e.message,true);}finally{busy=false;controls();}}
$('latest').onclick=()=>page('day',null);$('older').onclick=()=>page('day',record.nextBefore);$('latestEvents').onclick=()=>page('event',null);$('olderEvents').onclick=()=>page('event',record.nextEventsBefore);
try{await load();key='world-storms-pending:'+record.worldFingerprint;pending=JSON.parse(sessionStorage.getItem(key)||'null');message(pending?'A retained command needs confirmation. Retry the same command.':'Review the affected dates and explicit storm assumptions before scheduling.');controls();}
catch(e){message(e.message,true);document.querySelectorAll('input,button').forEach(el=>el.disabled=true);}
