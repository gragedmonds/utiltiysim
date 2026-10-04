// The year of a local simulation (local-runs.html): the Command Center's calendar (year-page.js installYearPage in
// plan mode) over the episodes saved with the simulation (SimulationLibrary). Nothing runs in the browser: the
// episodes go into the next revision's job file, and POST /api/m2c/episodes/preview checks them and gives the days a
// sporadic episode strikes, so the calendar marks them as the Command Center does.
// A job's districts are separate towns with their own run seeds, so a sporadic episode gets the simulation's own
// pattern seed (`local:<id>`, as utilsim/worker/prepare.py prepare_recipe fills a missing one): every district strikes the same days.
// A revision is the job prepared from the inputs at the time; runPlan says what changed since the latest one.
import {FIRST_YEAR} from './m2c.js';
const clone=v=>JSON.parse(JSON.stringify(v));
export const patternSeed=id=>('local:'+String(id??'')).slice(0,64);
// Episodes with every sporadic pattern given the simulation's seed (a pattern with its own seed keeps it).
export function seedPatterns(episodes,id){return (episodes||[]).map(ep=>ep?.pattern&&!ep.pattern.seed?{...ep,pattern:{...ep.pattern,seed:patternSeed(id)}}:ep);}
// The plan-mode client year-page.js drives: the simulation's episodes and results date, edited in place and saved
// with the simulation (`onSave` hears each save), the engine's scenario library, and preview() for the days struck.
// Episodes are EP-n (the highest plus one, as EngineM2C), sorted by `from`; a steady one has no `pattern` key.
export class LocalPlan{
 constructor({library,id,api='/api',fetchImpl=null,onSave=null}){const s=library.get(id);if(!s)throw Error('This simulation is no longer in this browser.');
  this.library=library;this.id=id;this.api=api;this.fetchImpl=fetchImpl;this.onSave=onSave;this.readOnly=false;this.year=FIRST_YEAR;this.years=[FIRST_YEAR];this.cache=new Map();this.ticket=0;
  const raw=Array.isArray(s.episodes)?s.episodes:[];let n=raw.reduce((m,x)=>Math.max(m,Number(String(x?.id||'').slice(3))||0),0); // a job's episodes come without ids
  this.episodes=raw.map(ep=>{const {pattern,...rest}=clone(ep);return {...rest,id:ep.id||'EP-'+(++n),...(pattern?{pattern}:{})};});
  this.asOf=s.asOf||'2026-03-31';this.sortEpisodes();}
 get fetch(){return this.fetchImpl||globalThis.fetch.bind(globalThis);}
 get record(){return this.library.get(this.id)||{};}
 get townRef(){const s=this.record;return s.townRef||s.preset||'small_town';}
 get settings(){return this.record.settings||{};}
 save(){this.library.update(this.id,{episodes:this.episodes,asOf:this.asOf});this.onSave?.(this);}
 setAsOf(day){this.asOf=day;this.save();}
 seeded(pattern){return pattern.seed?clone(pattern):{...clone(pattern),seed:patternSeed(this.id)};}
 addEpisode(ep){const n=this.episodes.reduce((m,x)=>Math.max(m,Number(String(x.id||'').slice(3))||0),0)+1;
  const e={id:'EP-'+n,title:ep.title||ep.scenario||'Episode',scenario:ep.scenario||null,from:ep.from,to:ep.to??null,ramp:Number(ep.ramp)||0,settings:ep.settings||{},...(ep.pattern?{pattern:this.seeded(ep.pattern)}:{})};
  this.episodes.push(e);this.sortEpisodes();this.save();return e;}
 // A patch's `pattern` sets the episode's own (seeded) copy, or removes it when null; without the key it stays.
 updateEpisode(id,patch){const e=this.episodes.find(x=>x.id===id);if(!e)return null;const {pattern,...rest}=patch||{};Object.assign(e,rest,{id});
  if(patch&&'pattern' in patch){if(pattern)e.pattern=this.seeded(pattern);else delete e.pattern;}this.sortEpisodes();this.save();return e;}
 removeEpisode(id){const n=this.episodes.length;this.episodes=this.episodes.filter(x=>x.id!==id);if(this.episodes.length===n)return false;this.save();return true;}
 clearEpisodes(){this.episodes=[];this.save();}
 sortEpisodes(){this.episodes.sort((a,b)=>a.from<b.from?-1:a.from>b.from?1:(Number(String(a.id).slice(3))||0)-(Number(String(b.id).slice(3))||0));}
 async scenarios(){if(!this._scenarios){const r=await this.fetch(this.api+'/m2c/scenarios');if(!r.ok)throw Error('Engine '+r.status);this._scenarios=await r.json();}return this._scenarios;}
 previewBody(){return {town:this.townRef,year:this.year,episodes:this.episodes.map(({scenario,...ep})=>ep)};}
 // The episodes as the engine reads them, with each sporadic one's `hits` (the trend's shape, for episodeStrikes).
 // A refusal is an Error with `status` and `detail` (422: the engine's message); an older reply landing late is
 // dropped (`superseded`).
 async preview(){if(!this.episodes.length)return {episodes:[]};const body=JSON.stringify(this.previewBody());if(this.cache.has(body))return this.cache.get(body);const ticket=++this.ticket;
  const r=await this.fetch(this.api+'/m2c/episodes/preview',{method:'POST',headers:{'Content-Type':'application/json'},body});
  if(!r.ok){let d='';try{d=(await r.json()).detail;}catch{}const e=Error('Engine '+r.status+(d?': '+(typeof d==='string'?d:d.message||JSON.stringify(d)):''));e.status=r.status;e.detail=d||null;throw e;}
  const data=await r.json();if(ticket!==this.ticket){const e=Error('superseded');e.superseded=true;throw e;}
  this.cache.set(body,data);if(this.cache.size>24)this.cache.delete(this.cache.keys().next().value);return data;}
}
// ---- revisions -------------------------------------------------------------------------------------------------
// The inputs that change a run, as a proposal holds them (the simulation's, or a job recipe's `proposal`).
const RUN_FIELDS={preset:'prepared town',totalHomes:'homes',seed:'run seed',townOverrides:'town settings',settings:'run settings',operations:'operations settings'};
const stable=v=>JSON.stringify(v,(k,x)=>x&&typeof x==='object'&&!Array.isArray(x)?Object.fromEntries(Object.keys(x).sort().map(key=>[key,x[key]])):x);
const field=(p,k)=>{const v=p?.[k];return k==='totalHomes'?Number(v)||null:k==='seed'||k==='preset'?String(v||''):v&&typeof v==='object'?v:{};};
const dayText=day=>{try{return new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}).format(new Date(day+'T12:00:00Z'));}catch{return String(day);}};
export const episodeInput=ep=>({title:String(ep?.title||''),from:ep?.from||null,to:ep?.to||null,ramp:Number(ep?.ramp)||0,settings:ep?.settings||{},pattern:ep?.pattern||null});
// What differs between the inputs `current` (the proposal the next job would send) and a revision's proposal, as
// short phrases: an episode added, changed (one of the same title differs) or removed, the results date, other inputs.
export function revisionChanges(current,previous){const notes=[],left=(previous?.episodes||[]).map(ep=>stable(episodeInput(ep))),added=[];
 for(const ep of (current?.episodes||[]).map(episodeInput)){const i=left.indexOf(stable(ep));if(i>=0)left.splice(i,1);else added.push(ep);}
 const removed=left.map(s=>JSON.parse(s));
 for(const ep of added){const i=removed.findIndex(r=>r.title===ep.title);if(i>=0){removed.splice(i,1);notes.push(`${ep.title} changed`);}else notes.push(`${ep.title} added`);}
 for(const r of removed)notes.push(`${r.title} removed`);
 const asOf=current?.asOf||'2026-03-31';if(asOf!==(previous?.asOf||'2026-03-31'))notes.push(`results through ${dayText(asOf)}`);
 for(const [k,label] of Object.entries(RUN_FIELDS))if(stable(field(current,k))!==stable(field(previous,k)))notes.push(`${label} changed`);
 return notes;}
// The run step for a simulation: its latest revision (any status), the next number, what changed since the latest
// and whether it is up to date (its job file still holds these inputs), with the sentence that says so. `sync`: jobs
// go to the connected computers rather than as a download.
export function runPlan(jobs,modelId,current,{sync=false}={}){const rows=(jobs||[]).filter(j=>j?.recipe?.modelId===modelId).sort((a,b)=>b.revision-a.revision),latest=rows[0]||null,next=(latest?.revision||0)+1,what=sync?'queue the new job':'download the new job';
 if(!latest)return {latest,next,changes:[],upToDate:false,message:`No revision yet. Run revision 1 to ${sync?'queue':'download'} its job file.`};
 const changes=revisionChanges(current,latest.recipe.proposal||{});
 return {latest,next,changes,upToDate:!changes.length,message:changes.length?`Changed since revision ${latest.revision}: ${changes.join('; ')}. Run revision ${next} to ${what}.`
  :`Revision ${latest.revision} is up to date: nothing changed since it was prepared. Its job file stays available.`};}
