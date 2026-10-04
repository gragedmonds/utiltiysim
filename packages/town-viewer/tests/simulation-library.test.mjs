import test from 'node:test';
import assert from 'node:assert/strict';
import {SimulationLibrary,SIM_PREFIX,DELETED_PREFIX,simulationKey,studioURL,simulationYears} from '../dist/simulation-library.js';
import {EngineM2C} from '../dist/m2c.js';
import {EngineOperations} from '../dist/engine-operations.js';
function memory(){const m=new Map();return {get length(){return m.size;},key:i=>[...m.keys()][i],getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v),removeItem:k=>m.delete(k)};}
test('drafts survive reopening and independent library instances do not overwrite one another',()=>{
 const storage=memory(),a=new SimulationLibrary(storage),b=new SimulationLibrary(storage),first=a.save({...a.create(),name:'First',step:2}),second=b.save({...b.create(),name:'Second'});
 a.update(first.id,{status:'ready',townRef:'ayr'});assert.equal(b.list().length,2);assert.equal(b.get(first.id).step,2);assert.equal(a.get(second.id).name,'Second');
 assert.match(studioURL(a.get(first.id),'?engine=http://localhost:8010&town=old'),/simulation=.*town=ayr#\/year$/);
});
test('simulations sharing a town keep settings, actions, episodes and operations settings isolated',()=>{
 const storage=memory(),opts={townRef:'ayr',townId:'town-1',storage};
 const a=new EngineM2C({...opts,simulationId:'a',initial:{seed:'alpha',asOf:'2026-03-31',episodes:[{id:'EP-1'}]}});a.actions=[{id:'ACT-1'}];a.save();
 const b=new EngineM2C({...opts,simulationId:'b',initial:{seed:'beta'}});assert.equal(b.seed,'beta');assert.equal(b.actions.length,0);assert.equal(b.episodes.length,0);
 const reopened=new EngineM2C({...opts,simulationId:'a',initial:{seed:'wrong'}});assert.equal(reopened.seed,'alpha');assert.equal(reopened.actions[0].id,'ACT-1');
 storage.setItem('utility-town-ops-settings:'+simulationKey('a','town-1'),JSON.stringify({crews:3}));
 assert.deepEqual(new EngineOperations({id:'town-1'},{storage,simulationId:'a'}).settings,{crews:3});assert.equal(new EngineOperations({id:'town-1'},{storage,simulationId:'b'}).settings,null);
});
test('previous town-keyed work is adopted once without deleting the originals',()=>{
 const storage=memory(),lib=new SimulationLibrary(storage),saved=JSON.stringify({seed:'original',actions:[{id:'old'}],asOf:'2026-04-30'}),pack={towns:[{preset:'ayr',townId:'town-1',homes:20,place:{name:'Ayr'}}]};
 storage.setItem('utility-town-m2c:town-1',saved);lib.adoptPacks(pack);const s=lib.list()[0];assert.equal(s.status,'ready');assert.equal(s.asOf,'2026-04-30');
 const m=new EngineM2C({townId:'town-1',simulationId:s.id,storage});assert.equal(m.actions[0].id,'old');m.setAsOf('2026-05-01');lib.adoptPacks(pack);assert.equal(lib.list().length,1);assert.equal(new EngineM2C({townId:'town-1',simulationId:s.id,storage}).asOf,'2026-05-01');assert.equal(storage.getItem('utility-town-m2c:town-1'),saved);
});
test('corrupt data and storage failures are visible and do not silently erase the library',()=>{
 const storage=memory(),lib=new SimulationLibrary(storage);storage.setItem(SIM_PREFIX+'broken','{');assert.throws(()=>lib.list(),/could not be read/);assert.equal(storage.getItem(SIM_PREFIX+'broken'),'{');
 const blocked=new SimulationLibrary({...memory(),setItem(){throw Error('quota');}});assert.throws(()=>blocked.save({...blocked.create(),name:'New'}),/could not be saved/);
});

test('operations-only experiments open the map; mixed goals and legacy simulations open Year',()=>{
 assert.match(studioURL({id:'one',townRef:'village',goals:['operations']}),/#\/map$/);
 assert.match(studioURL({id:'two',townRef:'village',goals:['operations','vee']}),/#\/year$/);
 assert.match(studioURL({id:'old',townRef:'village'}),/#\/year$/);
});
test('deleting a simulation removes its record and the data scoped to it, and nothing else',()=>{
 const storage=memory(),lib=new SimulationLibrary(storage),a=lib.save({...lib.create(),name:'Keep'}),b=lib.save({...lib.create(),name:'Delete me',townId:'town-1'});
 for(const sim of [a,b])for(const town of ['town-1','town-2']){storage.setItem('utility-town-m2c:'+simulationKey(sim.id,town),'{"seed":"x"}');storage.setItem('utility-town-ops-settings:'+simulationKey(sim.id,town),'{}');}
 storage.setItem('utility-town-m2c:town-1','{"seed":"legacy"}');storage.setItem('utility-town-lens','{}');
 assert.equal(lib.remove(b.id),5);
 assert.equal(lib.get(b.id),null);assert.deepEqual(lib.list().map(s=>s.name),['Keep']);
 assert.equal([...Array(storage.length).keys()].map(i=>storage.key(i)).filter(k=>k.includes(b.id)).length,0);
 assert.equal(storage.getItem('utility-town-m2c:'+simulationKey(a.id,'town-2')),'{"seed":"x"}');
 assert.equal(storage.getItem('utility-town-m2c:town-1'),'{"seed":"legacy"}');assert.equal(storage.getItem('utility-town-lens'),'{}');
 assert.equal(storage.getItem(DELETED_PREFIX+b.id),null);
 assert.throws(()=>lib.remove('../x'),/could not be found/);
 const blocked=memory();blocked.setItem(SIM_PREFIX+'x','{}');blocked.removeItem=()=>{throw Error('blocked');};assert.throws(()=>new SimulationLibrary(blocked).remove('x'),/could not be deleted/);assert.equal(blocked.getItem(SIM_PREFIX+'x'),'{}');
});
test('a deleted adopted simulation stays deleted; the town-keyed original stays',()=>{
 const storage=memory(),lib=new SimulationLibrary(storage),saved=JSON.stringify({seed:'original',actions:[{id:'old'}]}),pack={towns:[{preset:'ayr',townId:'town-1',homes:20,place:{name:'Ayr'}}]};
 storage.setItem('utility-town-m2c:town-1',saved);storage.setItem('utility-town-ops-settings:town-1','{"crews":2}');lib.adoptPacks(pack);
 const id=lib.list()[0].id;assert.equal(id,'legacy-town-1');assert.ok(storage.getItem('utility-town-m2c:'+simulationKey(id,'town-1')));
 assert.equal(lib.remove(id),3);assert.ok(storage.getItem(DELETED_PREFIX+id));
 lib.adoptPacks(pack);assert.equal(lib.list().length,0);
 assert.equal(storage.getItem('utility-town-m2c:town-1'),saved);assert.equal(storage.getItem('utility-town-ops-settings:town-1'),'{"crews":2}');
 assert.equal(storage.getItem('utility-town-m2c:'+simulationKey(id,'town-1')),null);
});

test('a simulation card shows the years its meter-to-cash state has opened',()=>{
 const storage=memory(),lib=new SimulationLibrary(storage),s=lib.save({...lib.create(),name:'Years',status:'ready',townRef:'village',townId:'town-1'});
 assert.deepEqual(simulationYears(s,storage),{first:2026,last:2026,active:2026,label:'2026'},'nothing saved yet: 2026');
 const m=new EngineM2C({townRef:'village',townId:'town-1',simulationId:s.id,storage});m.setAsOf('2026-06-30');assert.equal(simulationYears(s,storage).label,'2026');
 m.continueYear();assert.deepEqual(simulationYears(s,storage),{first:2026,last:2027,active:2027,label:'2026–2027'});
 m.setYear(2026);assert.equal(simulationYears(s,storage).active,2026);assert.equal(simulationYears({id:'other',townId:'town-1'},storage).label,'2026');
 // The record keeps the view date in view and 2026's episodes; reopening from it alone never puts a 2027 date in 2026.
 const fresh=new EngineM2C({townRef:'village',townId:'town-9',storage:memory(),initial:{asOf:'2027-01-31',episodes:[]}});assert.equal(fresh.year,2026);assert.equal(fresh.asOf,null);
});
