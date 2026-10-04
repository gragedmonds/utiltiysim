// Meter-to-cash client. The viewer keeps only the run's settings overrides, its seed (blank: the town's), the analyst's actions (append-only,
// dated), the episodes the Year tab inflicted (dated setting changes from the scenario library) and the service interruptions the map's operations days produced; the engine replays the year (POST /api/m2c/*, /api/process/*, /api/vee/*) and returns one bounded view at a
// time. Nothing here decides VEE outcomes, queue order, costs or estimates.
// Years: a simulation starts in 2026 and continues a year at a time to 2030; a later year opens where the year before
// closed (the engine replays the chain). Settings and seed are the whole simulation's; actions, episodes, outages and
// the view date are each year's own. Only the last year opened takes work: an earlier one is closed (view only).
import {simulationKey} from './simulation-library.js';
import {assertUnlocked} from './simulation-lock.js';
const KEY='utility-town-m2c:';
export const FIRST_YEAR=2026,LAST_YEAR=2030;
// The first year's last day, kept for older imports; a client's yearEnd() is its active year's.
export const YEAR_END='2026-12-31';
export const yearStart=y=>`${y}-01-01`;
export const yearEnd=y=>`${y}-12-31`;
// The year of a YYYY-MM-DD day (null for anything else), and a client's active year (2026 for a client without years).
export const dayYear=d=>/^\d{4}-\d{2}-\d{2}/.test(String(d||''))?Number(String(d).slice(0,4)):null;
export const activeYear=m=>Number(m?.year)||FIRST_YEAR;
const addDays=(day,n)=>new Date(Date.parse(day+'T12:00:00Z')+n*86400000).toISOString().slice(0,10);
const obj=v=>v&&typeof v==='object'&&!Array.isArray(v)?v:{};
// One year's own input: actions, episodes, the map's outages per day (and where each day's came from) and the view date.
const yearState=(year,s={})=>({year,actions:Array.isArray(s.actions)?s.actions:[],episodes:Array.isArray(s.episodes)?s.episodes:[],outages:obj(s.outages),outageSources:obj(s.outageSources),asOf:dayYear(s.asOf)===year?s.asOf:null});
// Interruptions per operations day as the engine takes them; one still open at the end of the day runs a day.
const outagesOf=outages=>Object.keys(outages).sort().flatMap(day=>outages[day].map(o=>({day,utility:o.utility,start:o.start,end:o.end??o.start+86400,premiseIds:o.premiseIds})));
export class EngineM2C{
 constructor({api='/api',townRef,townId,simulationId=null,initial={},onSave=null,onSaveError=null,storage=globalThis.localStorage,fetchImpl,locked=false}={}){this.locked=!!locked;
  this.api=api;this.townRef=townRef;this.townId=townId||townRef;this.storage=storage;this.fetchImpl=fetchImpl;this.storageKey=simulationKey(simulationId,this.townId);this.onSave=onSave;this.onSaveError=onSaveError;this.initial=initial;this.tickets={};this.cache=new Map();
  const saved=this.load()||{};this.settings=saved.settings||null;this.seed=typeof saved.seed==='string'&&saved.seed?saved.seed.slice(0,64):null;
  // Stored as before for 2026 (the top-level fields; an old saved state is 2026 alone), the later years in `later`.
  this.chain=[yearState(FIRST_YEAR,saved)];for(const s of Array.isArray(saved.later)?saved.later:[]){const y=FIRST_YEAR+this.chain.length;if(!s||Number(s.year)!==y||y>LAST_YEAR)break;this.chain.push(yearState(y,s));}
  this.year=this.years.includes(Number(saved.year))?Number(saved.year):FIRST_YEAR;
 }
 get fetch(){return this.fetchImpl||globalThis.fetch.bind(globalThis);}
 // ---- years ------------------------------------------------------------------------------------------------------
 get years(){return this.chain.map(s=>s.year);}
 get lastYear(){return this.chain.at(-1).year;}
 yearState(y){return this.chain.find(s=>s.year===Number(y))||null;}
 get state(){return this.yearState(this.year)||this.chain[0];}
 get actions(){return this.state.actions;} set actions(v){this.state.actions=v;}
 get episodes(){return this.state.episodes;} set episodes(v){this.state.episodes=v;}
 get outages(){return this.state.outages;} set outages(v){this.state.outages=v;}
 get outageSources(){return this.state.outageSources;} set outageSources(v){this.state.outageSources=v;}
 get asOf(){return this.state.asOf;} set asOf(v){this.state.asOf=v;}
 yearStart(){return yearStart(this.year);}
 yearEnd(){return yearEnd(this.year);}
 // A year before the last one opened is closed: the next year opened on its close, so its input stays as it is.
 isClosed(y=this.year){return Number(y)<this.lastYear;}
 closedMessage(y=this.year){return `${y} is closed: ${Number(y)+1} opened on it. Work in ${this.lastYear}, or switch years to look back.`;}
 assertOpen(y=this.year){if(this.isClosed(y))throw Error(this.closedMessage(y));}
 canContinue(){return !this.readOnly&&this.year===this.lastYear&&this.year<LAST_YEAR;}
 setYear(y){y=Number(y);if(!this.yearState(y))throw Error(`${y} is not open in this simulation.`);if(y===this.year)return false;if(this.pending)throw Error('The engine is still recording your previous action.');this.year=y;this.save();return true;}
 // Opens the next year on this one's close (no actions, episodes or outages yet; viewed from 31 January) and moves to it.
 continueYear(){if(this.pending)throw Error('The engine is still recording your previous action.');if(this.year!==this.lastYear)throw Error(`Continue from ${this.lastYear}, the last year opened.`);
  if(this.year>=LAST_YEAR)throw Error(`The simulation runs to ${LAST_YEAR}.`);const y=this.year+1;this.chain.push(yearState(y,{asOf:`${y}-01-31`}));this.year=y;this.save();return y;}
 // What an earlier year ran with, as the engine's `previous` takes it.
 inputsOf(s){const o=outagesOf(s.outages);return {...(this.settings?{settings:this.settings}:{}),...(s.episodes.length?{episodes:s.episodes}:{}),...(s.actions.length?{actions:s.actions}:{}),...(o.length?{outages:o}:{})};}
 previous(){return this.chain.filter(s=>s.year<this.year).map(s=>this.inputsOf(s));}
 load(){try{return JSON.parse(this.storage?.getItem(KEY+this.storageKey)||'null')||this.initial;}catch{return {};}}
 save(){try{const f=this.chain[0],out={settings:this.settings,seed:this.seed,actions:f.actions,episodes:f.episodes,asOf:f.asOf,outages:f.outages,outageSources:f.outageSources};if(this.chain.length>1){out.year=this.year;out.later=this.chain.slice(1);}
  this.storage?.setItem(KEY+this.storageKey,JSON.stringify(out));this.onSave?.(this);}catch(e){this.onSaveError?.(e);}}
 // 2026 requests are as they always were (no year, no previous); a later year adds both.
 body(extra={}){const s=this.state,b={town:this.townRef,actions:s.actions,...extra};if(this.settings)b.settings=this.settings;if(this.seed)b.seed=this.seed;const o=outagesOf(s.outages);if(o.length)b.outages=o;if(s.episodes.length)b.episodes=s.episodes;if(s.asOf)b.asOf=s.asOf;
  if(this.year>FIRST_YEAR){b.year=this.year;b.previous=this.previous();}return b;}
 // Episodes (the Year tab): a scenario's setting changes from one day to another (`to` null: year end), at most 40, kept
 // sorted by `from`. Ids are EP-n and never reused. The engine applies them when it replays the year; a bad one is a 422.
 addEpisode(ep){this.assertOpen();const n=this.episodes.reduce((m,x)=>Math.max(m,Number(String(x.id||'').slice(3))||0),0)+1;const e={id:'EP-'+n,title:ep.title||ep.scenario||'Episode',scenario:ep.scenario||null,from:ep.from,to:ep.to??null,ramp:Number(ep.ramp)||0,settings:ep.settings||{}};
  this.episodes.push(e);this.sortEpisodes();this.save();return e;}
 updateEpisode(id,patch){this.assertOpen();const e=this.episodes.find(x=>x.id===id);if(!e)return null;Object.assign(e,patch,{id});this.sortEpisodes();this.save();return e;}
 removeEpisode(id){this.assertOpen();const n=this.episodes.length;this.episodes=this.episodes.filter(x=>x.id!==id);if(this.episodes.length===n)return false;this.save();return true;}
 clearEpisodes(){this.assertOpen();this.episodes=[];this.save();}
 sortEpisodes(){this.episodes.sort((a,b)=>a.from<b.from?-1:a.from>b.from?1:(Number(a.id.slice(3))||0)-(Number(b.id.slice(3))||0));}
 // The scenario library (GET, fetched once) and the month-by-month trend of this run.
 async scenarios(){if(!this._scenarios){const r=await this.fetch(this.api+'/m2c/scenarios');if(!r.ok)throw Error('Engine '+r.status);this._scenarios=await r.json();}return this._scenarios;}
 trend(){return this.post('/m2c/trend',{},'trend');}
 // Interruptions per operations day (a timeline's `interruptions`) of the active year; one still open at the end of the day runs a day.
 outageList(){return outagesOf(this.outages);}
 outageKey(){return Object.keys(this.outages).sort().map(d=>d+':'+this.outages[d].map(o=>o.utility[0]+o.start+'-'+o.end+'x'+o.premiseIds.length).join(',')).join('|');}
 // Replaces one day's interruptions in that day's year; true when that changed the run. The map's days are 2026's: a
 // closed year (or one not open) keeps what it had, so the map never writes into another year.
 setOutages(day,list){const s=this.yearState(dayYear(day));if(!s||this.isClosed(s.year))return false;const next=(list||[]).filter(o=>o.premiseIds?.length).map(o=>({utility:o.utility,start:o.start,end:o.end??null,premiseIds:o.premiseIds}));
  if(JSON.stringify(next)===JSON.stringify(s.outages[day]||[]))return false;if(next.length)s.outages[day]=next;else delete s.outages[day];this.save();return true;}
 // A day's interruptions from the map's operations run, background incidents included. A day you worked (commands)
 // keeps its outages when it is replayed without them (after a reload), until you work it again or Reset it.
 recordDay(day,list,{commands=false,reset=false}={}){const s=this.yearState(dayYear(day));if(!s||this.isClosed(s.year))return false;if(!reset&&!commands&&s.outageSources[day]==='commands')return false;
  const changed=this.setOutages(day,list),src=commands&&s.outages[day]?'commands':s.outages[day]?'background':null;
  if((s.outageSources[day]||null)!==src){if(src)s.outageSources[day]=src;else delete s.outageSources[day];this.save();}return changed;}
 // The days the map skipped over (POST /api/sim/days: [{date, interruptions}]), recorded as background days; how many changed.
 recordDays(days,opts={}){let n=0;for(const d of days||[])if(d?.date&&this.recordDay(d.date,d.interruptions||[],opts))n++;return n;}
 // Interruptions recorded for the run days from `a` to `b` inclusive.
 outageCount(a,b){return this.chain.reduce((n,s)=>n+Object.keys(s.outages).filter(d=>d>=a&&d<=b).reduce((k,d)=>k+s.outages[d].length,0),0);}
 // One request per channel is current; an older reply that lands late is dropped (error.superseded).
 async post(path,extra={},channel=path){
  const body=JSON.stringify(this.body(extra)),key=path+body;if(this.cache.has(key))return this.cache.get(key);
  const ticket=(this.tickets[channel]||0)+1;this.tickets[channel]=ticket;
  const r=await this.fetch(this.api+path,{method:'POST',headers:{'Content-Type':'application/json'},body});
  if(!r.ok){let d='';try{d=(await r.json()).detail;}catch{}const e=Error('Engine '+r.status+(d?': '+(typeof d==='string'?d:d.message||JSON.stringify(d)):''));e.status=r.status;e.detail=d||null;throw e;}
  const data=await r.json();if(this.tickets[channel]!==ticket){const e=Error('superseded');e.superseded=true;throw e;}
  this.cache.set(key,data);if(this.cache.size>48)this.cache.delete(this.cache.keys().next().value);return data;
 }
 // Year to date; `since` (YYYY-MM-DD) adds the engine's `window`: the same figures for that period.
 summary(since=null){return this.post('/m2c/summary',since?{since}:{},since?'summary:window':'summary');}
 // Collections worklists, an account's collections, the outage follow-up list and AMI collector groups.
 collections(params){return this.post('/m2c/collections',params,'collections');}
 collectionsAccount(accountId){return this.post('/m2c/collections/account',{accountId},'collections:account');}
 outageFollowup(params={}){return this.post('/m2c/outage-followup',params,'outages');}
 collectorGroups(params={}){return this.post('/m2c/collector-groups',params,'collectors:'+(params.collector||''));}
 firstActionDay(){return this.actions[0]?.day||null;}
 queue(params={}){return this.post('/process/queue',params,'queue');}
 caseView(caseId,truth=false){return this.post('/m2c/case',{caseId,truth},'case');}
 premise(premiseId){return this.post('/m2c/premise',{premiseId},'premise:'+premiseId);}
 costs(){return this.post('/process/costs',{},'costs');}
 scorecard(){return this.post('/vee/scorecard',{},'scorecard');}
 graph(month){return this.post('/process/graph',{month},'graph');}
 // Studio lookups and the field service order form (the order's vocabulary is engine data, not hard-coded here).
 order(ref){return this.post('/m2c/order',ref,'order');}
 installation(installationId){return this.post('/m2c/installation',{installationId},'record');}
 readDocument(readId){return this.post('/m2c/read-document',{readId},'record');}
 possibleEntries(kind,query='',page=1){return this.post('/m2c/possible-entries',{kind,query,page,pageSize:50},'f4');}
 // Data pages: the table catalog, one page of a table (rows as arrays in column order) and one CSV page of it.
 async tables(){if(!this._tables){const r=await this.fetch(this.api+'/m2c/tables');if(!r.ok)throw Error('Engine '+r.status);this._tables=await r.json();}return this._tables;}
 table(params){return this.post('/m2c/table',params,'table');}
 async tableCsv(params){const r=await this.fetch(this.api+'/m2c/table.csv',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(this.body(params))});
  if(!r.ok){let d='';try{d=(await r.json()).detail;}catch{}const e=Error('Engine '+r.status+(d?': '+(typeof d==='string'?d:d.message||JSON.stringify(d)):''));e.status=r.status;throw e;}return r.text();}
 async vocabulary(){if(!this._vocab){const r=await this.fetch(this.api+'/m2c/vocabulary?town='+encodeURIComponent(this.townRef));if(!r.ok)throw Error('Engine '+r.status);this._vocab=await r.json();}return this._vocab;}
 async schema(){if(!this._schema){const r=await this.fetch(this.api+'/m2c/settings?town='+encodeURIComponent(this.townRef));if(!r.ok)throw Error('Engine '+r.status);this._schema=await r.json();}return this._schema;}
 lastActionDay(){return this.actions.at(-1)?.day||null;}
 canAct(){const last=this.lastActionDay();return !this.isClosed()&&(!last||!this.asOf||this.asOf>=last);}
 // Why an action on the view date would be refused ('' when it would not): a closed year, or a date before your last action.
 actBlock(){return this.isClosed()?this.closedMessage():this.canAct()?'':`Actions are append-only: move the date to ${this.lastActionDay()} or later.`;}
 // The map's commands (break an asset, send a crew) change that day's outages, which feed this run: on a day before
 // your last action they would rewrite history under it. Returns that last action day, or null when the day is open.
 lockedBefore(day){const last=(this.yearState(dayYear(day))||this.state).actions.at(-1)?.day||null;return last&&day&&day<last?last:null;}
 // Appends a decision on the current view date and checks it with the engine; a refused action is removed again:
 // HTTP 422, or an engine that skips it with a warning ("ACT-n: …"), which is a refusal too. One at a time: while the
 // engine records one (`pending`), another is refused, so a double click cannot record it twice. The engine's notices
 // on a recorded action ("ACT-n (notice): …", e.g. a case completed while its order is open) are kept in `notices`,
 // and `onAct` hears every recorded action (the map refreshes its operations day: a dispatched order is a crew job).
 // A closed year takes no actions.
 async act(type,caseId,value=null,extra={}){
  if(this.pending)throw Error('The engine is still recording your previous action.');
  this.assertOpen();
  if(!this.asOf)throw Error('Pick a view date first.');
  if(!this.canAct())throw Error(`Actions are append-only: move the date to ${this.lastActionDay()} or later.`);
  const a={id:'ACT-'+(this.actions.length+1),day:this.asOf,type,...(caseId?{caseId}:{}),...extra};if(value!=null&&value!=='')a.value=Number(value);
  const s=this.state;s.actions.push(a);this.pending=a;this.notices=[];
  try{const res=await this.summary(),warn=(res?.warnings||[]).map(String),skipped=warn.find(w=>w.startsWith(a.id+':'));
   if(skipped){const e=Error(skipped.slice(a.id.length+1).replace(/ \(skipped\)$/,'').trim());e.status=422;e.detail=e.message;throw e;}
   this.notices=noticesFor(warn,a.id);}
  catch(e){if(!e.superseded){if(s.actions.at(-1)===a)s.actions.pop();throw e;}}
  finally{this.pending=null;}
  this.save();try{this.onAct?.(a);}catch{}return a;
 }
 // The view date is the active year's: a day in another year is not taken (false).
 setAsOf(day){if(day&&dayYear(day)!==this.year)return false;this.asOf=day||null;this.save();return true;}
 // A locked simulation (simulation-lock.js) keeps its settings and seed; episodes and actions still apply.
 setSettings(overrides){assertUnlocked(this);this.settings=overrides&&Object.keys(overrides).length?overrides:null;this.save();}
 // The run's seed (≤64 characters): reads, anomalies and estimates re-roll with it; blank uses the town's own seed.
 setSeed(seed){const s=String(seed??'').trim().slice(0,64)||null;if(s===this.seed)return false;assertUnlocked(this);this.seed=s;this.save();return true;}
 reset(){this.assertOpen();this.actions=[];this.save();}
 // The run identity the operations timeline needs for this day's field orders. The map's operations days are 2026's,
 // so it is 2026's input whichever year is active.
 context(){const s=this.chain[0],o=outagesOf(s.outages);return {settings:this.settings||undefined,...(this.seed?{seed:this.seed}:{}),actions:s.actions,...(o.length?{outages:o}:{}),...(s.episodes.length?{episodes:s.episodes}:{})};}
 export(){const s=this.state;return {schemaVersion:'viewer-m2c-run/1.0',townId:this.townId,town:this.townRef,settings:this.settings,seed:this.seed,actions:s.actions,episodes:s.episodes,outages:outagesOf(s.outages),asOf:s.asOf,...(this.year>FIRST_YEAR?{year:this.year,previous:this.previous()}:{})};}
}

// A library scenario's episode templates as concrete episodes for the day they are inflicted: `startOffset` days after
// that day, `durationDays` null to the year end (to: null), else the inclusive end `durationDays - 1` days on, clamped at
// the day's year end, 31 December (as is a start past it). The ramp and the settings are the template's; the engine interprets the operators.
export function episodeDates(scenario,day){const end=yearEnd(dayYear(day)||FIRST_YEAR),clamp=d=>d>end?end:d;
 return (scenario?.episodes||[]).map(t=>{const from=clamp(addDays(day,Number(t.startOffset)||0)),to=t.durationDays==null?null:clamp(addDays(from,Math.max(1,Number(t.durationDays))-1));
  return {title:t.title||scenario.title,scenario:scenario.id,from,to,ramp:Number(t.ramp)||0,settings:JSON.parse(JSON.stringify(t.settings||{}))};});}

// The engine's notices on one action ("ACT-3 (notice): CASE-… was completed while …"): recorded, but worth a warning.
export function noticesFor(warnings,id){const p=id+' (notice):';return (warnings||[]).map(String).filter(w=>w.startsWith(p)).map(w=>w.slice(p.length).trim());}
// Premises whose electric meter is AMI (from the town snapshot): those meters need mains power to answer the head end.
export function mainsAmiPremises(town){const tech=new Map((town?.meters||[]).map(m=>[m.id,m.technology]));return new Set((town?.servicePoints||[]).filter(s=>s.commodity==='electric'&&tech.get(s.meterId)==='AMI').map(s=>s.premiseId));}
// The map's "Meter-to-cash today" card with the day's own interruptions applied. The operations timeline builds the
// day's cycle from the run without that day's outages (its field orders cannot depend on later events), so an AMI
// collection during a morning outage would still count as read while the Workspace (whose run has them) shows the
// misses. The run's rule: an electric AMI meter without power, or any AMI meter behind a down collector, misses its read
// at the collection hour (water and gas endpoints run on batteries). Idempotent once the engine applies them itself.
export function cycleWithOutages(cycle,interruptions,mainsAmi){const ami=cycle?.ami;if(!ami||!interruptions?.length)return cycle;const dark=new Set();
 for(const o of interruptions){const end=o.end??o.start+86400;if(!(o.start<=ami.at&&ami.at<end))continue;for(const p of o.premiseIds||[])if(o.utility==='ami'||(o.utility==='electric'&&mainsAmi?.has(p)))dark.add(p);}
 const hit=(ami.read||[]).filter(p=>dark.has(p));if(!hit.length)return cycle;
 return {...cycle,ami:{...ami,read:ami.read.filter(p=>!dark.has(p)),missed:[...(ami.missed||[]),...hit],dark:hit.length}};}
