// Engine-backed field operations: the same interface as DemoOperations (jobs, incidents, jobState, active,
// breakAsset, dispatch, export), but every decision comes from the engine. The viewer keeps only the command list
// (append-only) and sends it whole to POST /api/sim/timeline; the engine replays it deterministically and returns
// incidents, crew jobs with road routes and timestamps, events and state changes. Frames with the run's outages come
// from POST /api/sim/frame. Nothing here decides protection, isolation, dispatch, routes or repair times.
export async function probeEngine(api='/api'){
 try{const r=await fetch(api+'/health',{cache:'no-store'});if(!r.ok)return null;const h=await r.json();return h?.status==='ok'?h:null;}catch{return null;}
}
function interpolate(points,times,t){
 // times are seconds from the start of this leg; positions between supplied points only.
 if(!points?.length)return null;if(t<=times[0])return seg(points,0);const last=times.length-1;if(t>=times[last])return seg(points,Math.max(0,last-1),1);
 let lo=0,hi=last;while(hi-lo>1){const mid=(lo+hi)>>1;if(times[mid]<=t)lo=mid;else hi=mid;}
 return seg(points,lo,(t-times[lo])/Math.max(1e-6,times[hi]-times[lo]));
}
function seg(points,i,f=0){const a=points[i],b=points[Math.min(i+1,points.length-1)],len=Math.hypot(b.x-a.x,b.z-a.z)||1;return {x:a.x+(b.x-a.x)*f,z:a.z+(b.z-a.z)*f,dx:(b.x-a.x)/len,dz:(b.z-a.z)/len};}
const OPS_KEY='utility-town-ops-settings:';
// Schema-form overrides ({group:{key:value}}) ↔ timeline settings: groups marked x-flat hold top-level keys.
export function toOpsSettings(overrides,schema){const out={};for(const [g,vals] of Object.entries(overrides||{})){if(schema?.properties?.[g]?.['x-flat'])Object.assign(out,vals);else out[g]={...(out[g]||{}),...vals};}return out;}
export function opsFormValues(settings,schema){const out={};for(const [g,gs] of Object.entries(schema?.properties||{})){out[g]={};for(const k of Object.keys(gs.properties||{})){const v=gs['x-flat']?settings?.[k]:settings?.[g]?.[k];if(v!==undefined)out[g][k]=v;}}return out;}
export class EngineOperations{
 constructor(town,{api='/api',townRef,date=null,onChange=()=>{},m2c=()=>null,storage=globalThis.localStorage}={}){
  this.engine=true;this.town=town;this.api=api;this.townRef=townRef||town.id;this.date=date;this.onChange=onChange;this.m2c=m2c;
  this.commands=[];this.jobs=[];this.incidents=[];this.events=[];this.reads=[];this.stateChanges=[];this.time=8*3600;this.sequence=0;this.request=0;this.applied=0;this.error=null;
  const depot=(town.facilities||[]).find(f=>f.kind==='depot');this.depot=depot?{x:depot.x,z:depot.z}:{x:0,z:0};
  this.storage=storage;try{this.settings=JSON.parse(storage?.getItem(OPS_KEY+town.id)||'null');}catch{this.settings=null;}
 }
 // Operations settings from Configuration (crews, response times, back-feed limits); only what differs from the
 // engine defaults is sent, so the engine's defaults stay authoritative.
 setSettings(s){this.settings=s&&Object.keys(s).length?s:null;try{this.storage?.setItem(OPS_KEY+this.town.id,JSON.stringify(this.settings));}catch{}return this.refresh();}
 async schema(){if(!this._schema){const r=await fetch(this.api+'/sim/settings/schema');if(!r.ok)throw Error('Engine '+r.status);this._schema=await r.json();}return this._schema;}
 // The meter-to-cash run (settings, actions) rides along so the day's field orders arrive as crew jobs.
 body(extra={}){const m2c=this.m2c();return JSON.stringify({town:this.townRef,date:this.date,commands:this.commands,...(this.settings?{settings:this.settings}:{}),...(m2c?{m2c}:{}),...extra});}
 async post(path,extra){const r=await fetch(this.api+path,{method:'POST',headers:{'Content-Type':'application/json'},body:this.body(extra)});if(!r.ok){let detail='';try{detail=(await r.json()).detail;}catch{}throw Error(`Engine ${r.status}${detail?': '+(typeof detail==='string'?detail:JSON.stringify(detail)):''}`);}return r.json();}
 // Commands are appended at the current sim time (never earlier than the last one), then the timeline is refreshed.
 command(type,payload){const at=Math.max(this.time,this.commands.at(-1)?.at??0);const cmd={id:'CMD-'+(++this.sequence),at:Math.round(at*1000)/1000,type,payload};this.commands.push(cmd);return this.refresh().then(()=>cmd);}
 async refresh(){const ticket=++this.request;try{const tl=await this.post('/sim/timeline');if(ticket<this.applied)return;this.applied=ticket;this.apply(tl);this.error=null;}catch(e){this.error=e.message;throw e;}finally{this.onChange(this);}}
 apply(tl){this.timeline=tl;this.simulationId=tl.simulationId;this.incidents=tl.incidents.map(i=>({...i,restoredAt:i.restoredAt??Infinity}));this.jobs=tl.jobs;this.events=tl.events;this.reads=tl.reads;this.stateChanges=tl.stateChanges;if(tl.depot)this.depot={x:tl.depot.x,z:tl.depot.z};}
 async breakAsset(target){const cmd=await this.command('break_asset',{id:target.id,kind:target.kind==='pole'?'pole':'main',utility:target.utility||'electric',edgeId:target.edgeId,x:target.x,z:target.z});return this.incidents.find(i=>i.commandId===cmd.id)||null;}
 async dispatch(target,incident=null){const cmd=await this.command('dispatch',incident?{incidentId:incident.id}:{targetId:target.id});const job=incident?this.jobs.find(j=>j.incidentId===incident.id):this.jobs.filter(j=>j.premiseId===target.id).at(-1);if(!job)throw Error(this.timeline?.warnings?.at(-1)||'The engine did not create a job.');return job;}
 active(i,time=this.time){return time>=i.createdAt&&time<i.restoredAt;}
 jobState(job,time=this.time){
  if(time<job.startAt)return {status:'future',position:null};
  if(time>=job.endAt)return {status:'completed',position:this.depot};
  if(time<job.arrivalAt)return {status:'en_route',position:interpolate(job.route,job.routeTimes,time-job.startAt)};
  if(time<job.returnStartAt&&job.walkRoute){const w=interpolate(job.walkRoute,job.walkTimes,time-job.arrivalAt);return job.mode==='drive'?{status:'on_site',position:w}:{status:'on_site',position:interpolate(job.route,job.routeTimes,job.routeTimes.at(-1)),agent:w};}
  if(time<job.returnStartAt){const p=interpolate(job.route,job.routeTimes,job.routeTimes.at(-1)),work=time-job.arrivalAt,w=Math.max(0,Math.min(1,work/35,(job.workSeconds-work)/35)),a=job.roadPoint,b=job.visitPoint;return {status:'on_site',position:p,agent:{x:a.x+(b.x-a.x)*w,z:a.z+(b.z-a.z)*w}};}
  return {status:'returning',position:interpolate(job.returnRoute,job.returnTimes,time-job.returnStartAt)};
 }
 // Changes at or before `time` that the current frame does not reflect yet (the engine's state change list).
 stateKey(time=this.time){let k=-1;for(let i=0;i<this.stateChanges.length;i++)if(this.stateChanges[i].at<=time)k=i;return k+':'+this.commands.length;}
 async frame(at,premises=true){return this.post('/sim/frame',{at,premises});}
 reset(){this.commands=[];this.sequence=0;return this.refresh();}
 // A different run day is a different run: its command list starts empty.
 setDate(date){if(date===this.date)return Promise.resolve(false);const had=this.commands.length;this.date=date;this.commands=[];this.sequence=0;return this.refresh().then(()=>had>0);}
 export(){return {schemaVersion:'viewer-engine-operations/1.0',townId:this.town.id,town:this.townRef,commands:this.commands,timeline:this.timeline||null};}
}
