import test from 'node:test';
import assert from 'node:assert/strict';
import {EngineOperations,addDays,addMonths,clampDay,dayLabel,prefetchDue,YEAR_END} from '../dist/engine-operations.js';
import {EngineM2C} from '../dist/m2c.js';

// The map's day plays through midnight without a pause (tomorrow's timeline is prefetched and applied at once), and
// the run advances a week or a month at a time (the skipped days come from one POST /api/sim/days).
function memory(){const m=new Map();return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v)};}
const town={id:'town-x',facilities:[]};
const timelineFor=date=>({schemaVersion:'utility-timeline/1.0',simulationId:'run-'+date,date,incidents:[],jobs:[],events:[],reads:[],stateChanges:[],interruptions:[{utility:'electric',start:100,end:200,premiseIds:['P-1']}],depot:{x:0,z:0},warnings:[]});
function engine(log,{hold=null}={}){return async(url,opts={})=>{const body=JSON.parse(opts.body);log.push({url,body});if(hold)await hold(body);return {ok:true,json:async()=>timelineFor(body.date)};};}

test('run-day arithmetic: days, calendar months clamped to the month, the year end, labels and when to prefetch',()=>{
 assert.equal(addDays('2026-07-12',7),'2026-07-19');assert.equal(addDays('2026-12-31',1),'2027-01-01');assert.equal(addDays('2026-03-01',-1),'2026-02-28');
 assert.equal(addMonths('2026-07-12'),'2026-08-12');assert.equal(addMonths('2026-01-31'),'2026-02-28');assert.equal(addMonths('2026-03-31'),'2026-04-30');
 assert.equal(addMonths('2026-08-31'),'2026-09-30');assert.equal(addMonths('2026-12-15'),'2027-01-15');assert.equal(addMonths('2026-01-15',-1),'2025-12-15');assert.equal(addMonths('2024-01-31'),'2024-02-29');
 assert.equal(clampDay('2027-01-15'),YEAR_END);assert.equal(clampDay('2026-12-31'),'2026-12-31');assert.equal(clampDay('2026-07-01'),'2026-07-01');
 assert.equal(dayLabel('2026-07-12'),'12 Jul');assert.equal(dayLabel('2026-12-01'),'1 Dec');
 assert.equal(prefetchDue(79200,30),true);assert.equal(prefetchDue(79199,30),false,'22:00 at everyday speeds');
 assert.equal(prefetchDue(0,14400),true,'a 6-second day is asked for at once');assert.equal(prefetchDue(57600,3600),true);assert.equal(prefetchDue(57599,3600),false);
});

test('tomorrow is prefetched with the day\'s own request, kept while nothing changes, and applied at midnight without a request',async()=>{
 const log=[];globalThis.fetch=engine(log);const ctx={actions:[],outages:[{day:'2026-07-12',utility:'electric',start:1,end:2,premiseIds:['P-1']}]};let changes=0;
 const ops=new EngineOperations(town,{api:'/api',townRef:'small_town',date:'2026-07-12',storage:null,m2c:()=>ctx,onChange:()=>changes++});ops.settings={fieldCrews:3};
 ops.time=3600;await ops.command('dispatch',{targetId:'P-1'});assert.equal(log.length,1);
 const p=ops.ensureAhead('2026-07-13',1000);assert.equal(log.length,2);
 assert.deepEqual(log[1].body,{town:'small_town',date:'2026-07-13',commands:[],settings:{fieldCrews:3},m2c:ctx},'the same request, for tomorrow, with no commands');
 ops.ensureAhead('2026-07-13',1500);ops.ensureAhead('2026-07-13',4000);assert.equal(log.length,2,'one request while nothing changed');
 assert.equal(ops.prefetched('2026-07-13'),null,'not landed yet');await p;assert.ok(ops.prefetched('2026-07-13'));assert.equal(ops.prefetched('2026-07-14'),null);
 const before=log.length,c=changes;assert.equal(ops.rollTo('2026-07-13'),true);
 assert.equal(log.length,before,'no request at midnight');assert.equal(ops.date,'2026-07-13');assert.equal(ops.timeline.date,'2026-07-13');assert.equal(ops.simulationId,'run-2026-07-13');
 assert.deepEqual(ops.commands,[]);assert.equal(ops.sequence,0);assert.equal(changes,c+1,'onChange ran once (the map records the day\'s outages and fetches a frame)');assert.equal(ops.ahead,null);
 assert.equal(ops.rollTo('2026-07-14'),false,'nothing prefetched for the day after');
 ops.time=10;await ops.command('dispatch',{targetId:'P-2'});assert.equal(log.at(-1).body.commands[0].id,'CMD-1','a new day numbers its commands from one');
});

test('a changed meter-to-cash run, changed settings or a command drop the prefetch; a stale one is never applied',async()=>{
 const log=[];globalThis.fetch=engine(log);let ctx={actions:[]};
 const ops=new EngineOperations(town,{api:'/api',townRef:'small_town',date:'2026-07-12',storage:null,m2c:()=>ctx});
 await ops.ensureAhead('2026-07-13',0);assert.ok(ops.prefetched('2026-07-13'));
 ctx={actions:[{id:'ACT-1'}]};assert.equal(ops.prefetched('2026-07-13'),null,'the run changed under it');assert.equal(ops.rollTo('2026-07-13'),false);
 await ops.ensureAhead('2026-07-13',5000);assert.equal(log.at(-1).body.m2c.actions.length,1);assert.ok(ops.prefetched('2026-07-13'));
 ops.time=100;await ops.command('dispatch',{targetId:'P-1'});assert.equal(ops.ahead,null,'a command drops it');
 await ops.ensureAhead('2026-07-13',9000);assert.ok(ops.ahead);await ops.setSettings({fieldCrews:3});assert.equal(ops.ahead,null,'new settings drop it');
 await ops.ensureAhead('2026-07-13',12000);assert.equal(log.at(-1).body.settings.fieldCrews,3);
 await ops.reset();assert.equal(ops.ahead,null,'a reset drops it');
});

test('without a prefetch, midnight falls back to the request; one still in flight is awaited, not repeated',async()=>{
 let release;const gate=new Promise(r=>release=r);const log=[];globalThis.fetch=engine(log,{hold:async b=>{if(b.date==='2026-07-13')await gate;}});
 const ops=new EngineOperations(town,{api:'/api',townRef:'small_town',date:'2026-07-12',storage:null});
 ops.ensureAhead('2026-07-13',0);assert.equal(log.length,1);assert.equal(ops.rollTo('2026-07-13'),false,'not here yet');
 const set=ops.setDate('2026-07-13');assert.equal(ops.date,'2026-07-13');assert.equal(log.length,1,'the in-flight prefetch is adopted');
 release();assert.equal(await set,false);assert.equal(ops.timeline.date,'2026-07-13');assert.equal(ops.ahead,null);
 assert.equal(await ops.setDate('2026-07-14'),false);assert.equal(log.length,2,'a day never asked for is requested');assert.equal(log[1].body.date,'2026-07-14');
});

test('a failed prefetch backs off for ten seconds, then is asked for again',async()=>{
 let fail=true;const log=[];globalThis.fetch=async(url,opts)=>{log.push(JSON.parse(opts.body));if(fail)return {ok:false,status:503,json:async()=>({detail:'cold start'})};return {ok:true,json:async()=>timelineFor('2026-07-13')};};
 const ops=new EngineOperations(town,{api:'/api',townRef:'small_town',date:'2026-07-12',storage:null});
 await assert.rejects(ops.ensureAhead('2026-07-13',1000),/503/);assert.equal(ops.prefetched('2026-07-13'),null);assert.equal(ops.rollTo('2026-07-13'),false);
 ops.ensureAhead('2026-07-13',5000);assert.equal(log.length,1,'no retry within ten seconds');fail=false;
 await ops.ensureAhead('2026-07-13',12000);assert.equal(log.length,2);assert.ok(ops.prefetched('2026-07-13'));
});

test('the skipped days of a week or a month come from one /sim/days request and are recorded as background outages',async()=>{
 const log=[];const days=[{date:'2026-07-13',interruptions:[],incidents:0,jobs:2},{date:'2026-07-14',interruptions:[{utility:'water',start:100,end:5000,premiseIds:['P-2','P-3']},{utility:'ami',start:200,end:null,premiseIds:['P-4']}],incidents:2,jobs:4}];
 globalThis.fetch=async(url,opts)=>{const body=JSON.parse(opts.body);log.push({url,body});return {ok:true,json:async()=>url.endsWith('/sim/days')?{schemaVersion:'utility-days/1.0',from:body.from,to:body.to,days}:timelineFor(body.date)};};
 const m=new EngineM2C({townRef:'small_town',townId:'town-x',storage:memory()});m.setSeed('storm');
 const ops=new EngineOperations(town,{api:'/api',townRef:'small_town',date:'2026-07-12',storage:null,m2c:()=>m.context()});ops.settings={fieldCrews:3};ops.time=100;await ops.command('dispatch',{targetId:'P-1'});
 const res=await ops.days('2026-07-13','2026-07-14');assert.equal(log.at(-1).url,'/api/sim/days');
 assert.deepEqual(log.at(-1).body,{town:'small_town',settings:{fieldCrews:3},m2c:{seed:'storm',actions:[]},from:'2026-07-13',to:'2026-07-14'},'the timeline request\'s shape plus the range, without the day or its commands');
 assert.equal(m.recordDays(res.days),1,'one day changed the run');assert.equal(m.outageCount('2026-07-13','2026-07-14'),2);assert.equal(m.outageCount('2026-07-13','2026-07-13'),0);
 assert.equal(m.outageSources['2026-07-14'],'background');assert.equal(m.outages['2026-07-13'],undefined);assert.equal(m.recordDays(res.days),0,'already recorded');
 assert.deepEqual(m.outageList().map(o=>[o.day,o.utility,o.end]),[['2026-07-14','water',5000],['2026-07-14','ami',86600]]);
 m.recordDay('2026-07-14',[{utility:'gas',start:1,end:2,premiseIds:['P-9']}],{commands:true});assert.equal(m.recordDays(res.days),0,'a day you worked keeps its outages');assert.equal(m.outages['2026-07-14'][0].utility,'gas');
});
