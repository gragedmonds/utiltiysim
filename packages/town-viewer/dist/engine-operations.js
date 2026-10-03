// Engine-backed field operations: the same interface as DemoOperations (jobs, incidents, jobState, active,
// breakAsset, dispatch, export), but every decision comes from the engine. The viewer keeps only the command list
// (append-only) and sends it whole to POST /api/sim/timeline; the engine replays it deterministically and returns
// incidents, crew jobs with road routes and timestamps, events and state changes. Frames with the run's outages come
// from POST /api/sim/frame. Nothing here decides protection, isolation, dispatch, routes or repair times.
import {simulationKey} from './simulation-library.js';
import {LOCKED_MESSAGE} from './simulation-lock.js';
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
export function toOpsSettings(overrides,schema){const out={},defs=schema?.$defs||{};for(const [g,vals] of Object.entries(overrides||{})){const g0=schema?.properties?.[g];if((g0?.$ref?{...defs[g0.$ref.split('/').pop()],...g0}:g0)?.['x-flat'])Object.assign(out,vals);else out[g]={...(out[g]||{}),...vals};}return out;}
export function opsFormValues(settings,schema){const out={},defs=schema?.$defs||{};for(const [g,g0] of Object.entries(schema?.properties||{})){const gs=g0?.$ref?{...defs[g0.$ref.split('/').pop()],...g0}:g0;out[g]={};for(const k of Object.keys(gs.properties||{})){const v=gs['x-flat']?settings?.[k]:settings?.[g]?.[k];if(v!==undefined)out[g][k]=v;}}return out;}
export class EngineOperations{
 // `cycle(meterToCash, timeline)` may adjust the linked run's day for the map (the day's own outages; see m2c.js).
 constructor(town,{api='/api',townRef,simulationId=null,initial=null,date=null,onChange=()=>{},m2c=()=>null,cycle=null,storage=globalThis.localStorage,locked=false}={}){this.locked=!!locked;
  this.engine=true;this.town=town;this.api=api;this.townRef=townRef||town.id;this.date=date;this.onChange=onChange;this.m2c=m2c;this.cycle=cycle;
  this.commands=[];this.jobs=[];this.incidents=[];this.events=[];this.reads=[];this.stateChanges=[];this.time=8*3600;this.sequence=0;this.request=0;this.applied=0;this.error=null;
  const depot=(town.facilities||[]).find(f=>f.kind==='depot');this.depot=depot?{x:depot.x,z:depot.z}:{x:0,z:0};
  this.storageKey=simulationKey(simulationId,town.id);this.storage=storage;try{const saved=storage?.getItem(OPS_KEY+this.storageKey);this.settings=saved==null?(initial||null):JSON.parse(saved);}catch{this.settings=null;}
 }
 // Operations settings from Configuration (crews, response times, back-feed limits); only what differs from the
 // engine defaults is sent, so the engine's defaults stay authoritative.
 setSettings(s){if(this.locked)return Promise.reject(Error(LOCKED_MESSAGE));this.settings=s&&Object.keys(s).length?s:null;try{this.storage?.setItem(OPS_KEY+this.storageKey,JSON.stringify(this.settings));}catch{}this.dropAhead();return this.refresh();}
 // ?town= makes the defaults this town's own (its crews, incident rates).
 async schema(){if(!this._schema){const r=await fetch(this.api+'/sim/settings/schema?town='+encodeURIComponent(this.townRef));if(!r.ok)throw Error('Engine '+r.status);this._schema=await r.json();}return this._schema;}
 // The meter-to-cash run (settings, actions) rides along so the day's field orders arrive as crew jobs.
 body(extra={}){const m2c=this.m2c();return JSON.stringify({town:this.townRef,date:this.date,commands:this.commands,...(this.settings?{settings:this.settings}:{}),...(m2c?{m2c}:{}),...extra});}
 post(path,extra){return this.send(path,this.body(extra));}
 async send(path,body){const r=await fetch(this.api+path,{method:'POST',headers:{'Content-Type':'application/json'},body});if(!r.ok){let detail='';try{detail=(await r.json()).detail;}catch{}throw Error(`Engine ${r.status}${detail?': '+(typeof detail==='string'?detail:JSON.stringify(detail)):''}`);}return r.json();}
 // Commands are appended at the current sim time (never earlier than the last one), then the timeline is refreshed.
 command(type,payload){const at=Math.max(this.time,this.commands.at(-1)?.at??0);const cmd={id:'CMD-'+(++this.sequence),at:Math.round(at*1000)/1000,type,payload};this.commands.push(cmd);this.dropAhead();return this.refresh().then(()=>cmd);}
 refresh(){return this.adopt(this.post('/sim/timeline'));}
 // One timeline request is current; an older reply that lands late is dropped.
 async adopt(pending){const ticket=++this.request;try{const tl=await pending;if(ticket<this.applied)return;this.applied=ticket;this.apply(tl);this.error=null;}catch(e){this.error=e.message;throw e;}finally{this.onChange(this);}}
 // Tomorrow's timeline, requested ahead of midnight so the playing clock rolls over without a pause: the request
 // `refresh` would make for that day with no commands. It is kept with its request body (date, settings, m2c context,
 // seed): if any of those change, or a command is issued, it is dropped and asked for again. Checked every ~2 s.
 ensureAhead(date,now=0){const a=this.ahead;if(a&&a.date===date&&(a.failed?now-a.failed<10000:now-a.checked<2000))return a.promise;const body=this.body({date,commands:[]});if(a&&a.date===date&&a.body===body&&!a.failed){a.checked=now;return a.promise;}
  const entry=this.ahead={date,body,tl:null,checked:now,failed:0};entry.promise=this.send('/sim/timeline',body).then(tl=>{entry.tl=tl;return tl;},e=>{entry.failed=now||1;throw e;});entry.promise.catch(()=>{});return entry.promise;}
 prefetched(date){const a=this.ahead;return a&&a.date===date&&a.tl&&a.body===this.body({date,commands:[]})?a.tl:null;}
 dropAhead(){this.ahead=null;}
 // Midnight with the next day already here: start it at once (no request, no await). Its command list starts empty.
 rollTo(date){const tl=this.prefetched(date);if(!tl)return false;this.ahead=null;this.date=date;this.commands=[];this.sequence=0;this.applied=++this.request;this.apply(tl);this.error=null;this.onChange(this);return true;}
 // The run days between two dates, each with no commands (POST /api/sim/days): their interruptions reach the
 // meter-to-cash run when the map advances a week or a month.
 days(from,to){return this.post('/sim/days',{from,to,date:undefined,commands:undefined});}
 apply(tl){if(tl.meterToCash&&this.cycle)tl={...tl,meterToCash:this.cycle(tl.meterToCash,tl)};this.timeline=tl;this.simulationId=tl.simulationId;this.incidents=tl.incidents.map(i=>({...i,restoredAt:i.restoredAt??Infinity}));this.jobs=tl.jobs;this.events=tl.events;this.reads=tl.reads;this.stateChanges=tl.stateChanges;if(tl.depot)this.depot={x:tl.depot.x,z:tl.depot.z};}
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
 reset(){this.commands=[];this.sequence=0;this.dropAhead();return this.refresh();}
 // A different run day is a different run: its command list starts empty. A prefetch of that day still in flight
 // (midnight came before it landed) is awaited instead of a second request.
 setDate(date){if(date===this.date)return Promise.resolve(false);const had=this.commands.length;this.date=date;this.commands=[];this.sequence=0;const a=this.ahead;this.ahead=null;
  const pending=a&&a.date===date&&!a.failed&&a.body===this.body({commands:[]})?a.promise:null;return this.adopt(pending||this.post('/sim/timeline')).then(()=>had>0);}
 export(){return {schemaVersion:'viewer-engine-operations/1.0',townId:this.town.id,town:this.townRef,commands:this.commands,timeline:this.timeline||null};}
}
// Who an incident leaves without supply, as its card says it: an electric fault trips customers out at once; a water or
// gas main keeps supplying while it leaks, until a crew closes its valves; an AMI collector outage stops meters
// reporting, not service.
export function incidentImpact(i,time=0){const u=i?.unsupplied||{},n=x=>Number(x||0).toLocaleString('en-CA'),who=x=>`${n(x)} customer${x===1?'':'s'}`;
 if(i?.utility==='ami'||i?.kind==='collector_outage')return `${i.premiseIds?.length?who(i.premiseIds.length)+': ':''}AMI meters cannot report; service continues`;
 if(i?.utility==='electric'||u.atFault)return `${n(u.atFault)} out at the fault · ${n(u.afterIsolation)} after isolation${(i.ties?.length||i.tie)&&u.afterBackfeed!=null?` · ${n(u.afterBackfeed)} once the ${i.ties?.length>1?i.ties.length+' ties':'tie'} closed`:''}`;
 const what=i?.utility||'supply',restored=Number.isFinite(i?.restoredAt)&&i.restoredAt<=time,isolated=i?.isolatedAt!=null&&i.isolatedAt<=time;
 if(restored)return u.afterIsolation?`${who(u.afterIsolation)} ${u.afterIsolation===1?'was':'were'} without ${what} while it was isolated`:'Repaired without cutting anyone off';
 if(isolated)return u.afterIsolation?`Isolated · ${who(u.afterIsolation)} without ${what} until the repair`:'Isolated without cutting anyone off';
 return `Leaking · customers keep ${what} until a crew isolates it${u.afterIsolation?` (then ${who(u.afterIsolation)} lose supply)`:''}`;}
// The next job of the day that has not started yet (a reading round, a field order), for an empty operations list.
export function nextJob(jobs,time){return (jobs||[]).filter(j=>j.startAt>time).sort((a,b)=>a.startAt-b.startAt)[0]||null;}
// Run-day arithmetic (YYYY-MM-DD). A month on is the same day of the next month, clamped to its length (31 Jan →
// 28 Feb). The simulated year ends on 31 December 2026; `clampDay` holds a day there.
export const YEAR_END='2026-12-31';
export const addDays=(day,n)=>new Date(Date.parse(day+'T12:00:00Z')+n*86400000).toISOString().slice(0,10);
export function addMonths(day,n=1){const [y,m,d]=day.split('-').map(Number),t=new Date(Date.UTC(y,m-1+n,1)),last=new Date(Date.UTC(t.getUTCFullYear(),t.getUTCMonth()+1,0)).getUTCDate();t.setUTCDate(Math.min(d,last));return t.toISOString().slice(0,10);}
export const clampDay=(day,end=YEAR_END)=>day>end?end:day;
export const dayLabel=day=>new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'short',timeZone:'UTC'}).format(new Date(day+'T12:00:00Z'));
// When to ask for tomorrow's timeline: past 22:00, or earlier when the day has under 8 real seconds left at this
// clock speed (at 14,400× a day lasts 6 s, so the request goes out as the day starts).
export const prefetchDue=(t,speed)=>t>=79200||(86400-t)/Math.max(1,speed)<=8;
