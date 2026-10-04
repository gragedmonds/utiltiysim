// Browser-local metadata. One record per simulation avoids lost updates to a shared list across tabs.
export const SIM_PREFIX='utility-studio-simulation:';
export const SIM_VERSION='studio-simulation/1.0';
export function browserStorage(){try{return globalThis.localStorage;}catch{throw Error('Browser storage is unavailable. Allow site storage to save and reopen simulations.');}}
export function simulationKey(id,townId){return id?'simulation:'+id+':'+townId:townId;}
export function validSimulation(s){return s?.schemaVersion===SIM_VERSION&&typeof s.id==='string'&&/^[a-zA-Z0-9_-]{1,100}$/.test(s.id)&&typeof s.name==='string'&&s.name.length<=100&&['draft','ready'].includes(s.status);}
export class SimulationLibrary{
 constructor(storage=browserStorage()){this.storage=storage;}
 list(){const rows=[];for(let i=0;i<this.storage.length;i++){const key=this.storage.key(i);if(!key?.startsWith(SIM_PREFIX))continue;const s=this.get(key.slice(SIM_PREFIX.length));if(s)rows.push(s);}return rows.sort((a,b)=>(b.openedAt||b.updatedAt||'').localeCompare(a.openedAt||a.updatedAt||''));}
 get(id){const raw=this.storage.getItem(SIM_PREFIX+id);if(raw===null)return null;let s;try{s=JSON.parse(raw);}catch{throw Error('A saved simulation could not be read. Your browser data has been kept.');}if(!validSimulation(s))throw Error('This saved simulation needs a newer Studio version. Your browser data has been kept.');return s;}
 save(s){if(!validSimulation(s))throw Error('Invalid simulation metadata.');const next={...s,updatedAt:new Date().toISOString()};try{this.storage.setItem(SIM_PREFIX+s.id,JSON.stringify(next));}catch{throw Error('Simulation could not be saved. Browser storage may be full or blocked.');}return next;}
 update(id,patch){const s=this.get(id);if(!s)throw Error('This simulation is no longer in this browser.');return this.save({...s,...patch,id,schemaVersion:SIM_VERSION});}
 create(){return {schemaVersion:SIM_VERSION,id:crypto.randomUUID(),name:'',purpose:'',status:'draft',step:0,wizardVersion:3,goals:[],createdAt:new Date().toISOString(),preset:'',townRef:'',townId:'',townName:'',homes:0,scenarioId:'baseline',scenarioTitle:'Normal operations',episodes:[],asOf:'2026-03-31',seed:''};}
 // Adopt earlier town-keyed work without moving or deleting the original data.
 adoptPacks(packs){for(const t of packs?.towns||[]){const id='legacy-'+t.townId;if(this.get(id))continue;const raw=this.storage.getItem('utility-town-m2c:'+t.townId);if(!raw)continue;let saved;try{saved=JSON.parse(raw);}catch{continue;}if(!saved||typeof saved!=='object')continue;
   const name=t.place?.name||t.preset,scope=simulationKey(id,t.townId);
   this.storage.setItem('utility-town-m2c:'+scope,raw);
   const ops=this.storage.getItem('utility-town-ops-settings:'+t.townId);if(ops)this.storage.setItem('utility-town-ops-settings:'+scope,ops);
   this.save({...this.create(),id,name:name+' · previous work',status:'ready',step:3,preset:t.preset,townRef:t.preset,townId:t.townId,townName:name,homes:t.homes,asOf:saved.asOf||'2026-03-31',seed:saved.seed||'',scenarioTitle:'Previous work'});
  }}
}
export function studioURL(s,search=''){const q=new URLSearchParams(search);q.delete('town');q.delete('setup');q.delete('new');q.set('simulation',s.id);q.set('town',s.townRef);if(s.execution==='local'){q.delete('town');q.delete('simulation');q.set('model',s.id);return './local-runs.html?'+q;}return './studio.html?'+q+(s.goals?.length===1&&s.goals[0]==='operations'?'#/map':'#/year');}
