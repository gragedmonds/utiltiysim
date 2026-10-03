// Configuration → Town & meters for a town from the engine: every town-scoped setting of its SimConfig (the engine's
// GET /api/config/schema, in schema order; run-scoped groups live on Process & costs), starting from the loaded
// town's own configuration. Generate posts the edited config to a local engine (POST /api/towns), polls until the
// town is built and loads it. The hosted engine serves only prebuilt towns, so there the form stays editable and the
// config downloads for `utilsim gen --config`. The engine decides every outcome; this page only edits its input.
import {renderSchemaForm,prettyKey} from './schema-form.js';
// Only for a snapshot whose engine does not publish the schema: the SimConfig groups that belong to a run.
const RUN_FALLBACK=['process','anomalies','scenario','reading','vee','billing'];
export const isTownGroup=(key,g)=>g['x-applies']!=='run';
// A town's name for people: its own name, else its preset (small_town → Small town), else the source label.
const presetName=n=>n&&n!=='custom'?(s=>s.charAt(0).toUpperCase()+s.slice(1))(String(n).replaceAll('_',' ')):'';
export const townLabel=t=>t?.name||presetName(t?.config?.name)||t?.source?.label||'Engine town';
// A minimal schema read off a town's config (types and nesting only, no bounds or descriptions).
export function inferSchema(config){
 const infer=x=>x===null?{anyOf:[{type:'string'},{type:'null'}]}:typeof x==='boolean'?{type:'boolean'}:typeof x==='number'?{type:'number'}:typeof x==='string'?{type:'string'}:Array.isArray(x)?{type:'array'}:{type:'object',properties:Object.fromEntries(Object.entries(x).map(([k,v])=>[k,infer(v)]))};
 const properties={};let order=0;for(const [g,v] of Object.entries(config||{})){if(!v||typeof v!=='object'||Array.isArray(v))continue;properties[g]={title:prettyKey(g),type:'object','x-order':order++,'x-applies':RUN_FALLBACK.includes(g)?'run':'town',properties:Object.fromEntries(Object.entries(v).map(([k,x])=>[k,infer(x)]))};}
 return {type:'object',properties,'x-inferred':true};
}
// The town's groups as form values (deep copies, so editing never touches the loaded town).
export function townValues(config,schema){const out={};for(const [g,gs] of Object.entries(schema?.properties||{})){const d=gs?.$ref?schema.$defs?.[gs.$ref.split('/').pop()]:gs;if(d?.properties&&isTownGroup(g,d)&&config?.[g])out[g]=structuredClone(config[g]);}return out;}
// The complete SimConfig to generate from: the town's config with the edited groups.
export function fullConfig(config,values){return {...structuredClone(config||{}),...structuredClone(values||{})};}
// A new master seed that keeps the current one's prefix (TOWN-042 → TOWN-K7Q2PX); shown, so it is repeatable.
export function newSeed(current,random=Math.random){const abc='ABCDEFGHJKLMNPQRSTUVWXYZ23456789',prefix=(String(current||'').split('-')[0].replace(/[^A-Za-z0-9]/g,'').toUpperCase().slice(0,20))||'TOWN';
 for(;;){let s='';for(let i=0;i<6;i++)s+=abc[Math.floor(random()*abc.length)%abc.length];const seed=prefix+'-'+s;if(seed!==current)return seed;}}
export const HOSTED_NOTE='This engine cannot build towns (its generation libraries are not installed); it serves the prebuilt towns.';
// Can this engine build towns? health.capabilities.generate when the engine says; otherwise a local (not hosted)
// engine that serves the generator's presets also takes POST /api/towns.
export async function generateCapability(api,health,fetchImpl=globalThis.fetch?.bind(globalThis)){
 if(!health)return {ok:false,reason:'No engine is connected. '+HOSTED_NOTE};
 const c=health.capabilities;if(c&&typeof c==='object')return c.generate?{ok:true}:{ok:false,reason:HOSTED_NOTE};
 if(health.engine==='hosted')return {ok:false,reason:HOSTED_NOTE};
 try{const r=await fetchImpl(api+'/config/presets');return r.ok?{ok:true}:{ok:false,reason:HOSTED_NOTE};}catch{return {ok:false,reason:HOSTED_NOTE};}
}
function detailText(d){if(!d)return '';if(typeof d==='string')return d;if(Array.isArray(d))return d.map(e=>(e.loc?e.loc.filter(x=>x!=='body'&&x!=='config').join('.')+': ':'')+(e.msg||JSON.stringify(e))).join('; ');return d.message||JSON.stringify(d);}
// POST the config, then poll GET /api/towns/{id} until it is ready. Resolves to the town's reference (its self-describing
// name, which any engine instance and any shared link rebuilds), or its id from an engine that does not name towns.
export async function requestTown(api,config,{fetchImpl=globalThis.fetch?.bind(globalThis),onStatus=()=>{},sleep=ms=>new Promise(r=>setTimeout(r,ms)),interval=1500,timeoutMs=20*60000,now=()=>Date.now()}={}){
 const r=await fetchImpl(api+'/towns',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({config})});let body={};try{body=await r.json();}catch{}
 if(r.status===404||r.status===405){const e=Error('This engine does not generate towns. '+HOSTED_NOTE);e.unsupported=true;throw e;}
 if(body?.status==='failed')throw Error('The engine could not build this town: '+(detailText(body.error||body.detail)||'unknown error'));
 if(!r.ok||!body?.townId)throw Error(`Engine ${r.status}${body?.detail?': '+detailText(body.detail):''}`);
 const tid=body.townId,start=now();let status=body.status||'building';onStatus({townId:tid,status,elapsed:0});
 while(status!=='ready'){if(now()-start>timeoutMs)throw Error(`${tid} is still building after ${Math.round(timeoutMs/60000)} minutes.`);await sleep(interval);
  const s=await fetchImpl(api+'/towns/'+encodeURIComponent(tid));let b={};try{b=await s.json();}catch{}status=b.status||(s.ok?'ready':'unknown');
  if(status==='failed')throw Error('The engine could not build this town: '+(detailText(b.error)||'unknown error'));if(status==='unknown')throw Error(`The engine no longer knows ${tid}.`);
  onStatus({townId:tid,status,elapsed:now()-start});}
 return body.ref||tid;
}
// The page: deps give the current town and mode, the engine API, a health probe, toast/download and a loader.
export function installTownConfig({getContext,api,probe,toast,download,load}){
 const $=id=>document.getElementById(id);let form=null,draft=null,schemaCache=new Map(),capability=null,generating=false,ticker=null,shownFor=null;
 async function schemaFor(base,config){if(!schemaCache.has(base)){let s=null;try{const r=await fetch(base+'/config/schema');if(r.ok)s=await r.json();}catch{}schemaCache.set(base,s);}return schemaCache.get(base)||inferSchema(config);}
 function setStatus(text,kind=''){const el=$('town-config-status');el.textContent=text;el.dataset.kind=kind;}
 function update(){if(!form)return;const n=form.changes().length,town=getContext().town;
  $('town-config-changes').textContent=n?`${n} change${n>1?'s':''} from this town`:'No changes from this town';$('town-config-reset').disabled=!n||generating;
  $('town-config-generate').disabled=!capability?.ok||generating||!n;$('town-config-generate').title=!capability?.ok?capability?.reason||'':!n?'Change a setting or roll a new seed first.':'';
  if(!generating)setStatus(!capability?'Checking whether this engine can generate towns…':!capability.ok?capability.reason:n?`Generate builds a new town (a new town id) from these settings; ${townLabel(town)} stays as it is.`:'Change a setting or roll a new seed, then generate.',capability&&!capability.ok?'note':'');}
 async function render(){const {town,mode}=getContext(),cfg=mode==='snapshot'?town?.config:null,box=$('town-config');
  $('town-pane-title').textContent=cfg?'Town & meters':'Build a repeatable town';$('town-pane-intro').hidden=!!cfg;
  if(!cfg){box.hidden=true;return;}box.hidden=false;
  $('generator-context').hidden=false;$('generator-context').textContent='Every setting that shapes this town, from the engine. Values start at this town\'s own configuration; Generate builds a new town from your edits.';
  const base=api(),schema=await schemaFor(base,cfg);if(getContext().town!==town)return;
  if(!draft||draft.townId!==town.id)draft={townId:town.id,values:townValues(cfg,schema)};
  $('town-config-id').textContent=`${townLabel(town)} · ${town.id}${town.generatorVersion?' · generator '+town.generatorVersion:''}${schema['x-inferred']?' · this engine does not publish its settings schema, so bounds and descriptions are missing':''}`;
  if(shownFor!==town.id||!form||$('town-config-form').childElementCount===0){shownFor=town.id;
   form=renderSchemaForm($('town-config-form'),schema,{values:draft.values,base:cfg,groups:isTownGroup,showAdvanced:true,collapsible:true,open:'all',skip:['seeds.master'],baseLabel:'This town',onChange:()=>{draft.values=form.values;update();}});
   draft.values=form.values;form.filter($('town-config-filter').value);}
  $('town-master-seed').value=draft.values.seeds?.master??'';
  if(capability===null){capability=undefined;update();Promise.resolve(probe()).then(h=>generateCapability(base,h)).then(c=>{capability=c;update();});}else update();}
 function setSeed(v){if(!form)return;form.set('seeds.master',String(v).trim().slice(0,64));$('town-master-seed').value=form.values.seeds?.master??'';}
 async function generate(){if(!form||generating)return;if(form.invalid()){setStatus('Fix the highlighted settings first.','error');return;}
  const {town}=getContext(),config=fullConfig(town.config,form.values),t0=Date.now();generating=true;update();
  const tick=s=>setStatus(`${s} · ${Math.round((Date.now()-t0)/1000)} s`,'busy');let phase='Sending the configuration to the engine';tick(phase);clearInterval(ticker);ticker=setInterval(()=>tick(phase),1000);
  try{const tid=await requestTown(api(),config,{onStatus:({townId,status})=>{phase=status==='ready'?`${townId} built`:`Building ${townId} (larger towns take a minute or two)`;tick(phase);}});
   phase=`Loading ${tid}`;tick(phase);const ok=await load(tid);clearInterval(ticker);generating=false;
   if(ok){capability=null;setStatus(`Generated ${tid} in ${Math.round((Date.now()-t0)/1000)} s.`,'ok');}else{setStatus(`${tid} was built but could not be loaded.`,'error');update();}}
  catch(e){clearInterval(ticker);generating=false;if(e.unsupported)capability={ok:false,reason:HOSTED_NOTE};update();setStatus(e.message,'error');}}
 $('town-new-seed').onclick=()=>setSeed(newSeed(form?.values.seeds?.master));
 $('town-master-seed').onchange=e=>setSeed(e.target.value);
 $('town-config-reset').onclick=()=>{const {town}=getContext();if(!town?.config)return;draft=null;shownFor=null;render();toast('Town settings reset to this town\'s configuration.');};
 $('town-config-generate').onclick=generate;
 $('town-config-download').onclick=()=>{const {town}=getContext();if(!town?.config||!form)return;const name=String(townLabel(town)).toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'')||'town',seed=String(form.values.seeds?.master||'').toLowerCase().replace(/[^a-z0-9]+/g,'-');
  const file=`${name}${seed?'-'+seed:''}-config.json`;download(fullConfig(town.config,form.values),file);toast(`Saved ${file}: uv run utilsim gen --config ${file}`);};
 $('town-config-expand').onclick=()=>{const cards=[...document.querySelectorAll('#settings-page details.schema-group')],open=!cards.every(c=>c.open);for(const c of cards)c.open=open;$('town-config-expand').textContent=open?'Collapse all':'Expand all';};
 return {render,filter:q=>form?form.filter(q):0,state:()=>({changes:form?.changes()||[],capability,generating,values:form?.values||null})};
}
