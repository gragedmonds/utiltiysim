import test from 'node:test';
import assert from 'node:assert/strict';
import {EngineM2C} from '../dist/m2c.js';
import {parseRoute,routeHash,sparkPath} from '../dist/worklists.js';
import {schemaFields,parseField,overridesFrom} from '../dist/schema-form.js';

function memory(){const m=new Map();return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v)};}
function fakeEngine(log,{refuse=false,delay=null}={}){return async(url,opts={})=>{const body=opts.body?JSON.parse(opts.body):null;log.push({url,body});if(delay)await delay(url,body);
 if(refuse&&body?.actions?.length)return {ok:false,status:422,json:async()=>({detail:'action 0: case is not open'})};
 return {ok:true,json:async()=>url.endsWith('/m2c/summary')?{schemaVersion:'m2c-summary/1.0',asOf:'2026-07-15',n:body.actions.length}:{rows:[],total:0,pageSize:25,echo:body}};};}

test('requests carry town, settings, actions and the view date; replies are cached per body',async()=>{
 const log=[],m=new EngineM2C({api:'/api',townRef:'small_town',townId:'town-1',storage:memory(),fetchImpl:fakeEngine(log)});
 m.setAsOf('2026-03-02');m.setSettings({process:{analysts:1}});
 await m.queue({queue:'VEE_REVIEW',page:2});await m.queue({queue:'VEE_REVIEW',page:2});
 assert.equal(log.length,1);assert.deepEqual(log[0].body,{town:'small_town',actions:[],queue:'VEE_REVIEW',page:2,settings:{process:{analysts:1}},asOf:'2026-03-02'});
 m.setSettings({});assert.equal(m.settings,null);
});

test('actions are append-only by date, persisted, and removed again when the engine refuses them',async()=>{
 const store=memory(),log=[],m=new EngineM2C({townRef:'small_town',townId:'town-1',storage:store,fetchImpl:fakeEngine(log)});
 m.setAsOf('2026-04-10');await m.act('accept','CASE-1');await m.act('override','CASE-2',12.5);
 assert.deepEqual(m.actions.map(a=>[a.day,a.type,a.caseId,a.value]),[['2026-04-10','accept','CASE-1',undefined],['2026-04-10','override','CASE-2',12.5]]);
 m.setAsOf('2026-04-01');assert.equal(m.canAct(),false);await assert.rejects(()=>m.act('accept','CASE-3'),/append-only/);
 const again=new EngineM2C({townRef:'small_town',townId:'town-1',storage:store,fetchImpl:fakeEngine(log)});assert.equal(again.actions.length,2);assert.equal(again.asOf,'2026-04-01');
 const strict=new EngineM2C({townRef:'small_town',townId:'town-2',storage:memory(),fetchImpl:fakeEngine([],{refuse:true})});strict.setAsOf('2026-05-01');
 await assert.rejects(()=>strict.act('accept','CASE-9'),/422/);assert.equal(strict.actions.length,0);
});

test('a late reply on the same channel is superseded',async()=>{
 let release;const gate=new Promise(r=>release=r);
 const m=new EngineM2C({townRef:'small_town',storage:memory(),fetchImpl:fakeEngine([],{delay:async(url,body)=>{if(body.page===1)await gate;}})});
 const first=m.queue({page:1}),second=await m.queue({page:2});release();
 assert.equal(second.echo.page,2);await assert.rejects(first,e=>e.superseded===true);
});

test('worklist routes round-trip and the backlog sparkline fits its box',()=>{
 assert.deepEqual(parseRoute('#/worklists'),{queue:null,caseId:null});
 assert.deepEqual(parseRoute('#/worklists/FIELD/case/CASE-260602-01268'),{queue:'FIELD',caseId:'CASE-260602-01268'});
 assert.deepEqual(parseRoute('#/worklists/ALL/case/CASE-1'),{queue:null,caseId:'CASE-1'});
 assert.equal(parseRoute('#/settings/town'),null);
 for(const r of [{queue:null,caseId:null},{queue:'VEE_REVIEW',caseId:null},{queue:null,caseId:'CASE-1'}])assert.deepEqual(parseRoute(routeHash(r)),r);
 const d=sparkPath([0,2,4,2]);assert.match(d,/^M0\.0 24\.0 L/);assert.ok(d.includes('L100.0 12.0'));assert.equal(sparkPath([3]),'');
});

test('settings form fields come from the engine schema and only changes are sent',()=>{
 const schema={properties:{vee:{$ref:'#/$defs/VeeConfig'}},$defs:{VeeConfig:{title:'VEE rules',description:'Five tests.',properties:{
  high_ratio:{type:'number',minimum:1.1,maximum:10,default:2,description:'High tolerance.','x-effects':['flagged reads']},
  max_consecutive_estimates:{type:'integer',minimum:1,maximum:12,default:2,description:'Estimates in a row.'},
  estimation:{enum:['prior_year','recent_average'],type:'string',default:'prior_year'},
  zero_at_occupied:{type:'boolean',default:true},history_noise:{type:'number',default:.1,'x-advanced':true,'x-unit':'share'}}}}};
 const f=schemaFields(schema);
 assert.deepEqual(f.map(x=>[x.group,x.key,x.type]),[['vee','high_ratio','number'],['vee','max_consecutive_estimates','integer'],['vee','estimation','enum'],['vee','zero_at_occupied','boolean'],['vee','history_noise','number']]);
 assert.equal(f[0].groupTitle,'VEE rules');assert.deepEqual(f[0].effects,['flagged reads']);assert.equal(f[4].advanced,true);
 assert.deepEqual(parseField(f[0],'0.5'),{ok:false,error:'At least 1.1.'});assert.deepEqual(parseField(f[1],'2.5'),{ok:false,error:'Enter a whole number.'});assert.deepEqual(parseField(f[0],'3'),{ok:true,value:3});
 assert.deepEqual(overridesFrom(f,{vee:{high_ratio:2,max_consecutive_estimates:4,zero_at_occupied:false}}),{vee:{max_consecutive_estimates:4,zero_at_occupied:false}});
});

test('outages from the map ride every request, per operations day, and replace that day when it reruns',async()=>{
 const store=memory(),log=[],m=new EngineM2C({townRef:'small_town',townId:'town-1',storage:store,fetchImpl:fakeEngine(log)});
 const cut={utility:'electric',start:3600,end:12040.2,premiseIds:['P1','P2']};
 assert.equal(m.setOutages('2026-03-11',[cut,{utility:'gas',start:10,end:null,premiseIds:['P3']}]),true);
 assert.equal(m.setOutages('2026-03-11',[cut,{utility:'gas',start:10,end:null,premiseIds:['P3']}]),false);
 m.setOutages('2026-02-02',[{...cut,premiseIds:['P9']},{utility:'water',start:5,end:9,premiseIds:[]}]);
 await m.summary();
 assert.deepEqual(log[0].body.outages,[{day:'2026-02-02',utility:'electric',start:3600,end:12040.2,premiseIds:['P9']},
  {day:'2026-03-11',...cut},{day:'2026-03-11',utility:'gas',start:10,end:86410,premiseIds:['P3']}]);
 assert.equal(m.context().outages.length,3);
 const k=m.outageKey();assert.equal(m.setOutages('2026-03-11',[]),true);assert.notEqual(m.outageKey(),k);
 assert.equal(new EngineM2C({townRef:'small_town',townId:'town-1',storage:store}).outageList().length,1);
 assert.equal(new EngineM2C({townRef:'small_town',townId:'town-9',storage:memory()}).context().outages,undefined);
});

test('the VEE scorecard renders recall per anomaly and precision per exception',async()=>{
 const {scorecardMarkup}=await import('../dist/worklists.js');
 const html=scorecardMarkup({asOf:'2026-12-31',reads:73902,flagged:172,precision:.738,recall:.408,
  anomalies:[{anomaly:'stuck_meter',class:'meter_fault',meters:32,reads:98,flagged:70,recall:.714,medianDaysToFlag:36},{anomaly:'misread',class:'read_error',meters:5,reads:5,flagged:5,recall:1}],
  exceptions:[{exception:'ERRATIC',label:'Erratic <pattern>',icon:'〰️',cases:17,real:0,precision:0}]});
 assert.match(html,/Precision <strong>74%<\/strong>, recall <strong>41%<\/strong>/);
 assert.match(html,/Stuck meter<\/td><td>Meter fault/);assert.match(html,/width:71%/);assert.match(html,/Erratic &lt;pattern&gt;/);
 assert.match(scorecardMarkup({asOf:'x',reads:0,flagged:0,precision:null,recall:null,anomalies:[],exceptions:[]}),/No VEE exceptions yet/);
});

test('the run seed rides every request, the cache key and the operations context, and is kept with the run',async()=>{
 const store=memory(),log=[],m=new EngineM2C({townRef:'small_town',townId:'town-1',storage:store,fetchImpl:fakeEngine(log)});
 await m.summary();assert.equal('seed' in log[0].body,false);assert.equal('seed' in m.context(),false);
 assert.equal(m.setSeed('  RUN-7  '),true);assert.equal(m.seed,'RUN-7');assert.equal(m.setSeed('RUN-7'),false);
 await m.summary();assert.equal(log.length,2,'a new seed is a new run, not a cached reply');assert.equal(log[1].body.seed,'RUN-7');
 await m.summary();assert.equal(log.length,2);await m.queue({queue:'FIELD'});assert.equal(log[2].body.seed,'RUN-7');
 assert.equal(m.context().seed,'RUN-7');assert.equal(m.export().seed,'RUN-7');
 assert.equal(new EngineM2C({townRef:'small_town',townId:'town-1',storage:store}).seed,'RUN-7');
 m.setSeed('x'.repeat(80));assert.equal(m.seed.length,64);
 m.setSeed('');assert.equal(m.seed,null);assert.equal('seed' in m.body(),false);const n=log.length;await m.summary();assert.equal(log.length,n,'back on the town seed: the first run is still cached');
 await m.schema().catch(()=>{});assert.equal(log.at(-1).url,'/api/m2c/settings?town=small_town');
});

test('background interruptions are recorded too; a worked day keeps its outages until worked again or reset',()=>{
 const store=memory(),m=new EngineM2C({townRef:'small_town',townId:'town-1',storage:store});
 const storm={utility:'electric',start:100,end:900,premiseIds:['P1']},cut={utility:'gas',start:2000,end:null,premiseIds:['P2']};
 assert.equal(m.recordDay('2026-05-01',[storm]),true,'no commands, but the day had an outage');assert.equal(m.outageSources['2026-05-01'],'background');
 assert.equal(m.recordDay('2026-05-02',[storm,cut],{commands:true}),true);
 // Replayed without its commands (after a reload) the day keeps what you caused.
 assert.equal(m.recordDay('2026-05-02',[storm]),false);assert.equal(m.outages['2026-05-02'].length,2);
 assert.equal(new EngineM2C({townRef:'small_town',townId:'town-1',storage:store}).outageSources['2026-05-02'],'commands');
 // Reset keeps the day's background outage and drops yours.
 assert.equal(m.recordDay('2026-05-02',[storm],{reset:true}),true);assert.deepEqual(m.outages['2026-05-02'].map(o=>o.utility),['electric']);assert.equal(m.outageSources['2026-05-02'],'background');
 assert.equal(m.recordDay('2026-05-02',[],{reset:true}),true);assert.equal(m.outages['2026-05-02'],undefined);assert.equal(m.outageSources['2026-05-02'],undefined);
 assert.equal(m.recordDay('2026-05-03',[]),false);assert.equal(m.outageList().length,1);
});
