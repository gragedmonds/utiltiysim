import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {isLocked,allowedUnlocked,leafCount,settingCounts,lockSummary,lockPatch,lockedBanner,LOCKED_MESSAGE} from '../dist/simulation-lock.js';
import {SimulationLibrary,studioURL} from '../dist/simulation-library.js';
import {EngineM2C} from '../dist/m2c.js';
import {EngineOperations} from '../dist/engine-operations.js';
function memory(){const m=new Map();return {get length(){return m.size;},key:i=>[...m.keys()][i],getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v),removeItem:k=>m.delete(k)};}

test('a new simulation starts unlocked on Config; older records count as locked and open as before',()=>{
 assert.equal(isLocked({status:'ready'}),true);assert.equal(isLocked({status:'ready',locked:true}),true);
 assert.equal(isLocked({status:'ready',locked:false}),false);assert.equal(isLocked(null),false);
 for(const h of ['#/config','#/config/m2c','#/settings/town'])assert.equal(allowedUnlocked(h),true,h);
 for(const h of ['#/year','#/town','#/workspace','#/data','','#/worklists'])assert.equal(allowedUnlocked(h),false,h);
 const lib=new SimulationLibrary(memory()),s=lib.save({...lib.create(),name:'Lock me',status:'ready',townRef:'small_town',locked:false});
 assert.match(studioURL(s),/#\/config$/);assert.match(studioURL({...s,locked:undefined}),/#\/year$/);
 assert.match(studioURL({...s,goals:['operations']}),/#\/config$/);assert.match(studioURL({...s,goals:['operations'],locked:true}),/#\/map$/);
 const locked=lib.update(s.id,lockPatch({settings:{process:{analysts:3}},opsSettings:{crews:{fieldCrews:4}},seed:'S-1'},new Date('2026-10-03T12:00:00Z')));
 assert.equal(locked.locked,true);assert.equal(locked.lockedAt,'2026-10-03T12:00:00.000Z');assert.deepEqual(locked.settings,{process:{analysts:3}});
 assert.deepEqual(locked.opsSettings,{crews:{fieldCrews:4}});assert.equal(locked.seed,'S-1');assert.match(studioURL(locked),/#\/year$/);
 assert.equal(lockedBanner(locked),'Settings are locked for this simulation (locked Oct 3, 2026). Start a new simulation to change them.');
 assert.equal(lockedBanner({status:'ready'}),'Settings are locked for this simulation. Start a new simulation to change them.');
});
test('the lock-in summary counts settings that differ from the defaults',()=>{
 assert.equal(leafCount({a:{b:1,c:{d:2,e:3}},f:[1,2]}),4);
 const c=settingCounts({townOverrides:{town:{houses:500},gas:{all_electric_district_share:1}},settings:{process:{analysts:1}},opsSettings:null});
 assert.deepEqual(c,{town:2,year:1,map:0,total:3});
 assert.equal(lockSummary(c),'3 settings differ from the defaults (2 town · 1 year).');
 assert.equal(lockSummary(settingCounts({settings:{contact:{agents:2}}})),'1 setting differs from the defaults (1 year).');
 assert.equal(lockSummary(settingCounts({})),'Every setting is at its default.');
});
test('locked client stores refuse setting and seed edits; episodes, dates and actions stay allowed',async()=>{
 const storage=memory(),opts={townRef:'small_town',townId:'town-1',simulationId:'sim',storage};
 const open=new EngineM2C(opts);open.setSettings({process:{analysts:4}});assert.deepEqual(open.settings,{process:{analysts:4}});
 const m=new EngineM2C({...opts,locked:true});
 assert.throws(()=>m.setSettings({process:{analysts:9}}),new RegExp(LOCKED_MESSAGE.split('.')[0]));
 assert.throws(()=>m.setSeed('NEW-SEED'),/locked/);assert.deepEqual(m.settings,{process:{analysts:4}});assert.equal(m.seed,null);
 assert.equal(m.setSeed(''),false);
 m.addEpisode({title:'Storm week',from:'2026-03-01',to:'2026-03-07',settings:{contact:{volume_factor:2}}});m.setAsOf('2026-04-30');
 assert.equal(m.episodes.length,1);assert.equal(m.asOf,'2026-04-30');assert.deepEqual(m.settings,{process:{analysts:4}});
 const saved=JSON.parse(storage.getItem('utility-town-m2c:simulation:sim:town-1'));assert.deepEqual(saved.settings,{process:{analysts:4}});assert.equal(saved.episodes.length,1);
 const ops=new EngineOperations({id:'town-1'},{storage,simulationId:'sim',initial:{crews:2},locked:true});
 await assert.rejects(ops.setSettings({crews:9}),/locked/);assert.deepEqual(ops.settings,{crews:2});
 assert.equal(storage.getItem('utility-town-ops-settings:simulation:sim:town-1'),null);
});
test('the Studio bar includes Activity sequences alongside Workspace and Data; no Runs tab',()=>{
 const html=readFileSync(new URL('../dist/studio.html',import.meta.url),'utf8'),nav=html.match(/<nav class="studio-tabs"[^>]*>(.*?)<\/nav>/)[1];
 const tabs=[...nav.matchAll(/<a href="([^"]*)" id="([^"]+)">([^<]+)<\/a>/g)].map(m=>[m[2],m[3],m[1]]);
 assert.deepEqual(tabs,[['nav-simulations','Simulations','./'],['nav-config','Config','#/config'],['nav-year','Command Center','#/year'],['nav-map','Map','#/town'],['nav-workspace','Workspace','#/workspace'],['nav-data','Data','#/data'],['nav-process','Activity sequences','#/process'],['nav-glossary','Glossary','./glossary.html']]);
 assert.ok(!html.includes('id="nav-runs"'));assert.ok(html.includes('aria-label="Command Center"'));
 assert.ok(html.includes('id="cfg-lock-btn"')&&html.includes('Lock in settings and start simulation'));
});
