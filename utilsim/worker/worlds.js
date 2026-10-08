import {localToken} from '/viewer/local-session.js';
const $=id=>document.getElementById(id);
let offset=0,busy=false;
let sourceAfter='',sourceNext=null,sourceHistory=[],selectedRun=null;
let creation;
const creationKey='utility-studio-world-creation';
try{creation=JSON.parse(localStorage.getItem(creationKey)||'null');}catch{}
if(creation){for(const [id,key] of [['snapshot','path'],['environment','environment'],['start','start']])$(id).value=creation[key]||'';}
function chooseSource(key,label){selectedRun=key;$('snapshot').disabled=!!key;$('snapshot').required=!key;$('source-selection').textContent=key?'Selected saved town: '+label:'Or import a snapshot file below.';$('source-file').hidden=!key;}
if(creation?.runKey)chooseSource(creation.runKey,creation.runKey.slice(0,12)+' (saved request)');
const limit=25;
const esc=v=>String(v??'Not recorded').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function status(text,error=false){$('status').textContent=text;$('status').className=error?'error':'';}
async function call(path,method='GET',body){
 const r=await fetch('/local/worlds'+path,{method,headers:{Authorization:'Bearer '+localToken(),'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});
 const value=await r.json();if(!r.ok)throw Error(value.detail||'World library unavailable.');return value;
}
async function render(){
 const data=await call('?offset='+offset+'&limit='+limit);
 const pending=await call('/creations');
 $('pending').innerHTML=pending.pending.length?'<h2>Pending creation</h2><p>Retry resumes the saved request and pinned snapshot.</p>'+pending.pending.map(p=>`<p>${esc(p.environment)} · ${esc(p.start)} <button data-retry="${esc(p.commandId)}">Retry creation</button></p>`).join(''):'';
 if(offset&&offset>=data.total){offset=Math.max(0,offset-limit);return render();}
 $('worlds').innerHTML=data.worlds.map(w=>`<article class="world"><div><h2>${esc(w.environmentId||'Unavailable world')}</h2><p>${esc(w.townId||w.error)}</p>${w.available?`<p>Saved through ${esc(w.through)} · ${esc(w.days)} days · ${esc(w.assets)} meters</p><p>${w.managedDelivery?'Shared runtime controls time':'Standalone world'}</p>`:''}<p><small>${esc(w.path)}</small></p></div><div class="actions">${w.available?`<a class="open" href="/world-map?world=${encodeURIComponent(w.id)}">Open map</a>`:''}<button class="remove" data-id="${esc(w.id)}">Remove entry</button></div></article>`).join('');
 $('previous').disabled=offset===0;$('next').disabled=offset+limit>=data.total;
 $('page').textContent=data.total?`${offset+1}–${Math.min(offset+limit,data.total)} of ${data.total}`:'No saved worlds';
 status(data.total?'World records refreshed.':'Add an existing world to open its map.');
}
async function renderSources(){
 const data=await call('/sources?after='+encodeURIComponent(sourceAfter)+'&limit=10');sourceNext=data.next;
 $('sources').innerHTML=data.towns.length?data.towns.map(t=>`<article class="source"><div><strong>${esc(t.available?t.name:'Unavailable saved town')}</strong><p>${t.available?`${esc(t.townId)} · saved results through ${esc(t.asOf)} · ${esc(t.accounts)} accounts · ${esc(t.registers)} registers`:esc(t.error)}</p><small>Run ${esc(t.runKey.slice(0,12))}</small></div>${t.available?`<button type="button" data-source="${esc(t.runKey)}" data-label="${esc(t.name)}">Use this town</button>`:''}</article>`).join(''):'<p>No saved result archives found. Generate and save a run in Studio, or import a snapshot file below.</p>';
 $('source-previous').disabled=!sourceHistory.length;$('source-next').disabled=!sourceNext;
}
async function action(fn){if(busy)return;busy=true;$('add').disabled=$('refresh').disabled=$('create-button').disabled=true;try{await fn();await render();}catch(e){status(e.message,true);}finally{busy=false;$('add').disabled=$('refresh').disabled=$('create-button').disabled=false;}}
$('create').onsubmit=e=>{e.preventDefault();action(async()=>{
 const inputs={...(selectedRun?{runKey:selectedRun}:{path:$('snapshot').value.trim()}),environment:$('environment').value.trim(),start:$('start').value};
 if(!creation||['runKey','path','environment','start'].some(k=>creation[k]!==inputs[k]))creation={commandId:crypto.randomUUID(),...inputs};
 // Persist before sending; a lost response or page reload retains the same command.
 localStorage.setItem(creationKey,JSON.stringify(creation));
 $('create-status').textContent='Creating the saved world…';
 try{await call('/create','POST',creation);creation=null;localStorage.removeItem(creationKey);$('create-status').textContent='World created. Open its map below.';offset=0;}
 catch(error){$('create-status').textContent='Creation was not confirmed. Refresh to inspect pending work, or retry these same inputs.';throw error;}
});};
$('pending').onclick=e=>{const b=e.target.closest('button[data-retry]');if(b)action(async()=>{await call('/creations/'+encodeURIComponent(b.dataset.retry)+'/retry','POST',{});if(creation?.commandId===b.dataset.retry){creation=null;localStorage.removeItem(creationKey);}offset=0;$('create-status').textContent='World creation recovered.';});};
$('register').onsubmit=e=>{e.preventDefault();action(async()=>{await call('','POST',{path:$('path').value.trim()});$('path').value='';offset=0;});};
$('worlds').onclick=e=>{const b=e.target.closest('button[data-id]');if(b)action(()=>call('/'+encodeURIComponent(b.dataset.id),'DELETE'));};
$('refresh').onclick=()=>action(renderSources);
$('previous').onclick=()=>action(async()=>{offset=Math.max(0,offset-limit);});
$('next').onclick=()=>action(async()=>{offset+=limit;});
$('sources').onclick=e=>{const b=e.target.closest('button[data-source]');if(b&&!busy)chooseSource(b.dataset.source,b.dataset.label);};
$('source-file').onclick=()=>{if(!busy)chooseSource(null,'');};
$('source-next').onclick=()=>action(async()=>{if(sourceNext){sourceHistory.push(sourceAfter);sourceAfter=sourceNext;await renderSources();}});
$('source-previous').onclick=()=>action(async()=>{sourceAfter=sourceHistory.pop()||'';await renderSources();});
action(async()=>{await render();await renderSources();});
