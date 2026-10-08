import {localToken} from '/viewer/local-session.js';
const $=id=>document.getElementById(id);
let offset=0,busy=false;
const limit=25;
const esc=v=>String(v??'Not recorded').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function status(text,error=false){$('status').textContent=text;$('status').className=error?'error':'';}
async function call(path,method='GET',body){
 const r=await fetch('/local/worlds'+path,{method,headers:{Authorization:'Bearer '+localToken(),'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});
 const value=await r.json();if(!r.ok)throw Error(value.detail||'World library unavailable.');return value;
}
async function render(){
 const data=await call('?offset='+offset+'&limit='+limit);
 if(offset&&offset>=data.total){offset=Math.max(0,offset-limit);return render();}
 $('worlds').innerHTML=data.worlds.map(w=>`<article class="world"><div><h2>${esc(w.environmentId||'Unavailable world')}</h2><p>${esc(w.townId||w.error)}</p>${w.available?`<p>Saved through ${esc(w.through)} · ${esc(w.days)} days · ${esc(w.assets)} meters</p><p>${w.managedDelivery?'Shared runtime controls time':'Standalone world'}</p>`:''}<p><small>${esc(w.path)}</small></p></div><div class="actions">${w.available?`<a class="open" href="/world-map?world=${encodeURIComponent(w.id)}">Open map</a>`:''}<button class="remove" data-id="${esc(w.id)}">Remove entry</button></div></article>`).join('');
 $('previous').disabled=offset===0;$('next').disabled=offset+limit>=data.total;
 $('page').textContent=data.total?`${offset+1}–${Math.min(offset+limit,data.total)} of ${data.total}`:'No saved worlds';
 status(data.total?'World records refreshed.':'Add an existing world to open its map.');
}
async function action(fn){if(busy)return;busy=true;$('add').disabled=$('refresh').disabled=true;try{await fn();await render();}catch(e){status(e.message,true);}finally{busy=false;$('add').disabled=$('refresh').disabled=false;}}
$('register').onsubmit=e=>{e.preventDefault();action(async()=>{await call('','POST',{path:$('path').value.trim()});$('path').value='';offset=0;});};
$('worlds').onclick=e=>{const b=e.target.closest('button[data-id]');if(b)action(()=>call('/'+encodeURIComponent(b.dataset.id),'DELETE'));};
$('refresh').onclick=()=>action(async()=>{});
$('previous').onclick=()=>action(async()=>{offset=Math.max(0,offset-limit);});
$('next').onclick=()=>action(async()=>{offset+=limit;});
action(async()=>{});
