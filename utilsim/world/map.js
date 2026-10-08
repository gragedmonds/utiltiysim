import {inspectSnapshot} from '/viewer/adapter.js';
const el=id=>document.getElementById(id);
let scene,town,selected=null,requestVersion=0;
const libraryMode=location.pathname==='/world-map';
const worldId=new URLSearchParams(location.search).get('world');
const mapStyle=new URLSearchParams(location.search).get('map')==='3d'?'3d':'iso';
el('style').value=mapStyle;
el('style').onchange=()=>{const url=new URL(location.href);url.searchParams.set('map',el('style').value);location.assign(url);};
el('rotate').hidden=mapStyle==='3d';
if(mapStyle==='3d'){el('gestures').textContent='Drag to pan · scroll to zoom · right-drag to rotate. Click a property to inspect it.';el('top').textContent='Top view';el('top').removeAttribute('aria-pressed');}
let api='/api/map',headers={};
if(libraryMode){
 el('mainControls').hidden=true;
 const {localToken}=await import('/viewer/local-session.js');
 headers={Authorization:'Bearer '+localToken()};
 api='/local/worlds/'+encodeURIComponent(worldId||'')+'/map';
 const back=document.querySelector('header a');back.href='/worlds';back.textContent='Saved worlds';
}
const esc=value=>String(value??'Not recorded').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function get(path){const r=await fetch(api+path,{cache:'no-store',headers});const value=await r.json();if(!r.ok)throw Error(value.error||value.detail||'World unavailable');return value;}
function message(text,error=false){el('status').textContent=text;el('status').className=error?'error':'';}
function layers(){return Object.fromEntries(['electric','water','gas'].map(k=>[k,el(k).checked]));}
function utility(){return ['electric','water','gas'].find(k=>el(k).checked)||'electric';}
async function choose(home,focus=true){
 const version=++requestVersion;selected=home;scene.select(home,utility(),focus);el('place').textContent='Loading current physical records…';
 try{const data=await get('/premise?id='+encodeURIComponent(home.id));if(version!==requestVersion)return;
  const p=data.premise;el('place').innerHTML=`<h2>${esc(p.address||p.id)}</h2><p>${esc(p.id)} · ${p.occupied===true?'Occupied':p.occupied===false?'Vacant':'Occupancy not recorded'} · ${esc(p.occupants)} occupants</p><p>Last completed day: ${esc(data.lastCompletedDay)}</p>`+(!libraryMode?`<p><a href="/occupancy?premiseId=${encodeURIComponent(p.id)}">Manage physical occupancy</a></p>`:'')+data.assets.map(a=>`<article class="asset"><h2>${esc(a.commodity)} · ${esc(a.condition)}</h2><dl>${a.commodity==='water'?`<dt>Leak rate when supplied</dt><dd>${a.waterFault?esc(a.waterFault.rate)+' m³/h':'None active'}</dd>`:''}${a.lastMainInterruption?`<dt>Last main isolation</dt><dd>${esc(a.lastMainInterruption.day)} · ${esc(a.lastMainInterruption.unserved_m3)} m³ unserved</dd>`:''}${a.lastSupplyInterruption?`<dt>Last supply loss</dt><dd>${esc(a.lastSupplyInterruption.day)} · ${esc(a.lastSupplyInterruption.unserved_quantity)} ${esc(a.unit)} unserved</dd>`:''}<dt>Meter</dt><dd>${esc(a.id)}</dd><dt>Current device</dt><dd>${esc(a.device)}</dd><dt>Installed</dt><dd>${esc(a.installed)}</dd><dt>Actual use</dt><dd>${esc(a.true_quantity)} ${esc(a.unit)}</dd><dt>Observed use</dt><dd>${esc(a.observed_quantity)} ${esc(a.unit)}</dd><dt>Observation</dt><dd>${esc(a.observed_status)}</dd><dt>Observed device</dt><dd>${esc(a.observed_device)}</dd></dl>${['electric','gas'].includes(a.commodity)&&!libraryMode?`<a href="/network-faults?commodity=${encodeURIComponent(a.commodity)}">Inspect supply network</a>`:''}${a.sewer?`<p>Sewer lateral: ${a.sewer.current.active?'Blocked':'Clear'} · retained ${esc(a.sewer.current.retained)} m³${a.sewer.latest?' · overflow '+esc(a.sewer.latest.overflow)+' m³ on '+esc(a.sewer.latest.day):''}</p>`:''}${a.commodity==='water'&&!libraryMode?`<p><a href="/sewer?waterAssetId=${encodeURIComponent(a.id)}">Manage sewer lateral</a></p>`:''}${a.commodity==='water'&&!libraryMode?`<a href="/water-faults?assetId=${encodeURIComponent(a.id)}">Manage physical water faults</a> · <a href="/water-mains">Inspect water mains</a>`:''}</article>`).join('');
 }catch(error){if(version===requestVersion){el('place').textContent='Current physical records unavailable.';message(error.message,true);}}
}
async function refresh(){
 const state=await get('/status');if(!state.environmentId)throw Error('Initialize a world in World controls first.');
 if(town&&state.townId!==town.id)throw Error('World identity changed. Reload the map before continuing.');
 el('identity').textContent=state.environmentId+' · '+state.townId;
 el('date').textContent='World saved through '+state.through+' (exclusive)';
 message(state.managedDelivery?'Connected world · advance time in the shared runtime. Refresh here to inspect saved outcomes.':libraryMode?'Read-only saved world · advance time in its world runtime, then refresh here.':'Standalone world · advance time in World controls, then refresh the map.');
 if(selected)await choose(selected,false);
}
el('find').onsubmit=e=>{e.preventDefault();if(!town)return;const q=el('query').value.trim().toLowerCase();const matches=town.premises.filter(p=>p.id.toLowerCase()===q||q&&(p.address||'').toLowerCase().includes(q)).slice(0,20);el('matches').replaceChildren();for(const p of matches){const b=document.createElement('button');b.type='button';b.textContent=(p.address||p.id)+' · '+p.id;b.onclick=()=>choose(p);el('matches').append(b);}if(!matches.length)el('matches').textContent=q?'No matching property.':'Enter an address or premise ID.';};
el('home').onclick=()=>scene?.home();el('top').onclick=()=>scene?.top();
el('rotate').onclick=()=>scene?.rotate();
for(const key of ['electric','water','gas'])el(key).onchange=()=>{scene?.setLayers(layers());if(selected)scene.select(selected,utility(),false);};
el('refresh').onclick=async()=>{el('refresh').disabled=true;try{await refresh();}catch(error){el('place').textContent='Refresh failed; current records are unavailable.';message(error.message,true);}finally{el('refresh').disabled=false;}};
try{
 town=await get('/snapshot');
 if(!town.bounds||!town.roads||!town.networks)throw Error('This world has service records but no map geometry. Open a world initialized from a full generated snapshot. Existing service records have been preserved.');
 inspectSnapshot(town);
 const {IsoScene,TownScene}=await import(mapStyle==='iso'?'/viewer/iso-scene.js':'/viewer/scene.js');
 const Renderer=mapStyle==='iso'?IsoScene:TownScene;
 scene=new Renderer(el('map'),({home,landmark,asset,nodeId})=>{
  if(home){choose(home);return;}
  ++requestVersion;selected=null;scene.clearSelection();
  const title=landmark?.label||landmark?.kind||asset||'Map equipment';
  el('place').innerHTML=`<h2>${esc(title)}</h2><p>${esc(landmark?.id||nodeId||'No individual asset ID supplied')}</p><p>Stored map equipment. Select a property to inspect its current physical service records.</p>`;
 },mapStyle==='iso'?'full':'lite',{renderOnDemand:true});
 scene.onViewChange=()=>{if(mapStyle==='iso'){el('top').setAttribute('aria-pressed',String(scene.view==='top'));el('map').dataset.view=scene.view;}};
 if(scene.ready&&!(await scene.ready))throw Error('Isometric artwork could not load. Restore the bundled viewer artwork and reload, or choose 3D.');
 scene.load(town,{demo:false});scene.play=false;scene.setLayers(layers());el('map').dataset.renderer=mapStyle;
 await refresh();document.body.dataset.ready='true';
}catch(error){scene?.destroy();scene=null;message('Map could not open: '+error.message,true);}
window.addEventListener('pagehide',()=>scene?.destroy(),{once:true});
