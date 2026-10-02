// Meter-to-cash client. The viewer keeps only the run's settings overrides, its seed (blank: the town's), the analyst's actions (append-only,
// dated) and the service interruptions the map's operations days produced; the engine replays the year (POST /api/m2c/*, /api/process/*, /api/vee/*) and returns one bounded view at a
// time. Nothing here decides VEE outcomes, queue order, costs or estimates.
const KEY='utility-town-m2c:';
export class EngineM2C{
 constructor({api='/api',townRef,townId,storage=globalThis.localStorage,fetchImpl}={}){
  this.api=api;this.townRef=townRef;this.townId=townId||townRef;this.storage=storage;this.fetchImpl=fetchImpl;this.tickets={};this.cache=new Map();
  const saved=this.load();this.settings=saved.settings||null;this.actions=Array.isArray(saved.actions)?saved.actions:[];this.asOf=saved.asOf||null;this.outages=saved.outages&&typeof saved.outages==='object'?saved.outages:{};
  this.outageSources=saved.outageSources&&typeof saved.outageSources==='object'?saved.outageSources:{};this.seed=typeof saved.seed==='string'&&saved.seed?saved.seed.slice(0,64):null;
 }
 get fetch(){return this.fetchImpl||globalThis.fetch.bind(globalThis);}
 load(){try{return JSON.parse(this.storage?.getItem(KEY+this.townId)||'{}')||{};}catch{return {};}}
 save(){try{this.storage?.setItem(KEY+this.townId,JSON.stringify({settings:this.settings,seed:this.seed,actions:this.actions,asOf:this.asOf,outages:this.outages,outageSources:this.outageSources}));}catch{}}
 body(extra={}){const b={town:this.townRef,actions:this.actions,...extra};if(this.settings)b.settings=this.settings;if(this.seed)b.seed=this.seed;const o=this.outageList();if(o.length)b.outages=o;if(this.asOf)b.asOf=this.asOf;return b;}
 // Interruptions per operations day (a timeline's `interruptions`); one still open at the end of the day runs a day.
 outageList(){return Object.keys(this.outages).sort().flatMap(day=>this.outages[day].map(o=>({day,utility:o.utility,start:o.start,end:o.end??o.start+86400,premiseIds:o.premiseIds})));}
 outageKey(){return Object.keys(this.outages).sort().map(d=>d+':'+this.outages[d].map(o=>o.utility[0]+o.start+'-'+o.end+'x'+o.premiseIds.length).join(',')).join('|');}
 // Replaces one day's interruptions; true when that changed the run.
 setOutages(day,list){const next=(list||[]).filter(o=>o.premiseIds?.length).map(o=>({utility:o.utility,start:o.start,end:o.end??null,premiseIds:o.premiseIds}));
  if(JSON.stringify(next)===JSON.stringify(this.outages[day]||[]))return false;if(next.length)this.outages[day]=next;else delete this.outages[day];this.save();return true;}
 // A day's interruptions from the map's operations run, background incidents included. A day you worked (commands)
 // keeps its outages when it is replayed without them (after a reload), until you work it again or Reset it.
 recordDay(day,list,{commands=false,reset=false}={}){if(!reset&&!commands&&this.outageSources[day]==='commands')return false;
  const changed=this.setOutages(day,list),src=commands&&this.outages[day]?'commands':this.outages[day]?'background':null;
  if((this.outageSources[day]||null)!==src){if(src)this.outageSources[day]=src;else delete this.outageSources[day];this.save();}return changed;}
 // One request per channel is current; an older reply that lands late is dropped (error.superseded).
 async post(path,extra={},channel=path){
  const body=JSON.stringify(this.body(extra)),key=path+body;if(this.cache.has(key))return this.cache.get(key);
  const ticket=(this.tickets[channel]||0)+1;this.tickets[channel]=ticket;
  const r=await this.fetch(this.api+path,{method:'POST',headers:{'Content-Type':'application/json'},body});
  if(!r.ok){let d='';try{d=(await r.json()).detail;}catch{}const e=Error('Engine '+r.status+(d?': '+(typeof d==='string'?d:d.message||JSON.stringify(d)):''));e.status=r.status;e.detail=d||null;throw e;}
  const data=await r.json();if(this.tickets[channel]!==ticket){const e=Error('superseded');e.superseded=true;throw e;}
  this.cache.set(key,data);if(this.cache.size>48)this.cache.delete(this.cache.keys().next().value);return data;
 }
 summary(){return this.post('/m2c/summary',{},'summary');}
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
 async vocabulary(){if(!this._vocab){const r=await this.fetch(this.api+'/m2c/vocabulary?town='+encodeURIComponent(this.townRef));if(!r.ok)throw Error('Engine '+r.status);this._vocab=await r.json();}return this._vocab;}
 async schema(){if(!this._schema){const r=await this.fetch(this.api+'/m2c/settings?town='+encodeURIComponent(this.townRef));if(!r.ok)throw Error('Engine '+r.status);this._schema=await r.json();}return this._schema;}
 lastActionDay(){return this.actions.at(-1)?.day||null;}
 canAct(){const last=this.lastActionDay();return !last||!this.asOf||this.asOf>=last;}
 // Appends a decision on the current view date and checks it with the engine; a refused action is removed again.
 async act(type,caseId,value=null,extra={}){
  if(!this.asOf)throw Error('Pick a view date first.');
  if(!this.canAct())throw Error(`Actions are append-only: move the date to ${this.lastActionDay()} or later.`);
  const a={id:'ACT-'+(this.actions.length+1),day:this.asOf,type,...(caseId?{caseId}:{}),...extra};if(value!=null&&value!=='')a.value=Number(value);
  this.actions.push(a);
  try{await this.summary();}catch(e){if(!e.superseded){this.actions.pop();throw e;}}
  this.save();return a;
 }
 setAsOf(day){this.asOf=day||null;this.save();}
 setSettings(overrides){this.settings=overrides&&Object.keys(overrides).length?overrides:null;this.save();}
 // The run's seed (≤64 characters): reads, anomalies and estimates re-roll with it; blank uses the town's own seed.
 setSeed(seed){const s=String(seed??'').trim().slice(0,64)||null;if(s===this.seed)return false;this.seed=s;this.save();return true;}
 reset(){this.actions=[];this.save();}
 // The run identity the operations timeline needs for this day's field orders.
 context(){const o=this.outageList();return {settings:this.settings||undefined,...(this.seed?{seed:this.seed}:{}),actions:this.actions,...(o.length?{outages:o}:{})};}
 export(){return {schemaVersion:'viewer-m2c-run/1.0',townId:this.townId,town:this.townRef,settings:this.settings,seed:this.seed,actions:this.actions,outages:this.outageList(),asOf:this.asOf};}
}
