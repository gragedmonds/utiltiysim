import test from 'node:test';
import assert from 'node:assert/strict';
import {SimulationLibrary,SIM_PREFIX,simulationKey,studioURL} from '../dist/simulation-library.js';
import {EngineM2C} from '../dist/m2c.js';
import {EngineOperations} from '../dist/engine-operations.js';
function memory(){const m=new Map();return {get length(){return m.size;},key:i=>[...m.keys()][i],getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v)};}
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
