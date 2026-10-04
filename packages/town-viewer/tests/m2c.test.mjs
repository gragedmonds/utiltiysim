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

// ---- years: a simulation starts in 2026 and continues a year at a time; a later year opens on the one before ----------
const OLD_STATE={settings:{process:{analysts:3}},seed:'S-1',actions:[{id:'ACT-1',day:'2026-04-10',type:'accept',caseId:'CASE-260401-1'}],episodes:[{id:'EP-1',title:'Half',scenario:null,from:'2026-03-01',to:null,ramp:0,settings:{process:{analysts:'*0.5'}}}],asOf:'2026-05-01',outages:{'2026-03-11':[{utility:'electric',start:10,end:90,premiseIds:['P1']}]},outageSources:{'2026-03-11':'background'}};
function oldStore(){const s=memory();s.setItem('utility-town-m2c:town-1',JSON.stringify(OLD_STATE));return s;}

test('an old saved state (no years) loads as 2026, and 2026 requests stay as they were',async()=>{
 const store=oldStore(),log=[],m=new EngineM2C({townRef:'small_town',townId:'town-1',storage:store,fetchImpl:fakeEngine(log)});
 assert.equal(m.year,2026);assert.deepEqual(m.years,[2026]);assert.equal(m.lastYear,2026);assert.equal(m.isClosed(),false);assert.equal(m.canContinue(),true);
 assert.deepEqual(m.actions,OLD_STATE.actions);assert.deepEqual(m.episodes,OLD_STATE.episodes);assert.equal(m.asOf,'2026-05-01');assert.deepEqual(m.outages,OLD_STATE.outages);assert.equal(m.outageSources['2026-03-11'],'background');
 assert.equal(m.yearStart(),'2026-01-01');assert.equal(m.yearEnd(),'2026-12-31');
 const b=m.body({page:1});assert.equal('year' in b,false);assert.equal('previous' in b,false);
 assert.deepEqual(b,{town:'small_town',actions:OLD_STATE.actions,page:1,settings:OLD_STATE.settings,seed:'S-1',outages:[{day:'2026-03-11',utility:'electric',start:10,end:90,premiseIds:['P1']}],episodes:OLD_STATE.episodes,asOf:'2026-05-01'});
 assert.equal('year' in m.export(),false);assert.equal('previous' in m.export(),false);
 m.setAsOf('2026-05-02');assert.deepEqual(Object.keys(JSON.parse(store.getItem('utility-town-m2c:town-1'))),['settings','seed','actions','episodes','asOf','outages','outageSources'],'2026 alone saves as before');
});

test('Continue opens the next year on this one: empty input, viewed from 31 January, with year and previous on every request',async()=>{
 const store=oldStore(),log=[],m=new EngineM2C({townRef:'small_town',townId:'town-1',storage:store,fetchImpl:fakeEngine(log)});
 assert.equal(m.continueYear(),2027);assert.equal(m.year,2027);assert.deepEqual(m.years,[2026,2027]);assert.equal(m.asOf,'2027-01-31');
 assert.deepEqual([m.actions,m.episodes,m.outages,m.outageSources],[[],[],{},{}]);assert.equal(m.yearStart(),'2027-01-01');assert.equal(m.yearEnd(),'2027-12-31');assert.equal(m.isClosed(),false);assert.equal(m.isClosed(2026),true);
 await m.summary();const b=log.at(-1).body;
 assert.equal(b.year,2027);assert.equal(b.asOf,'2027-01-31');assert.deepEqual(b.actions,[]);assert.equal('episodes' in b,false);assert.equal('outages' in b,false);assert.equal(b.settings.process.analysts,3);assert.equal(b.seed,'S-1');
 assert.deepEqual(b.previous,[{settings:OLD_STATE.settings,episodes:OLD_STATE.episodes,actions:OLD_STATE.actions,outages:[{day:'2026-03-11',utility:'electric',start:10,end:90,premiseIds:['P1']}]}],'one entry per earlier year, its own input and the shared settings');
 // The year's own input rides as the request's; the earlier year stays in previous.
 m.addEpisode({title:'Cold',from:'2027-02-01',to:'2027-02-28',settings:{vee:{high_ratio:3}}});await m.trend();assert.deepEqual(log.at(-1).body.episodes.map(e=>e.from),['2027-02-01']);assert.equal(log.at(-1).body.previous[0].episodes.length,1);
 const x=m.export();assert.equal(x.year,2027);assert.deepEqual(x.previous,b.previous);assert.equal(x.asOf,'2027-01-31');assert.equal(x.episodes.length,1);
 // Kept: reopening finds 2027 active and 2026 as it was; the stored 2026 is still the top-level state.
 const saved=JSON.parse(store.getItem('utility-town-m2c:town-1'));assert.equal(saved.year,2027);assert.deepEqual(saved.actions,OLD_STATE.actions);assert.equal(saved.later[0].year,2027);
 const again=new EngineM2C({townRef:'small_town',townId:'town-1',storage:store});assert.equal(again.year,2027);assert.deepEqual(again.years,[2026,2027]);assert.equal(again.episodes.length,1);assert.deepEqual(again.yearState(2026).actions,OLD_STATE.actions);
 // A previous entry without settings when the run has none (the engine then runs that year on the town's).
 const plain=new EngineM2C({townRef:'small_town',townId:'town-2',storage:memory(),fetchImpl:fakeEngine(log)});plain.continueYear();assert.deepEqual(plain.body().previous,[{}]);
});

test('a closed year is view only: actions, episodes and outages are refused there; switching years is fine',async()=>{
 const store=oldStore(),log=[],m=new EngineM2C({townRef:'small_town',townId:'town-1',storage:store,fetchImpl:fakeEngine(log)});m.continueYear();
 assert.equal(m.setYear(2026),true);assert.equal(m.year,2026);assert.equal(m.isClosed(),true);assert.equal(m.canAct(),false);assert.equal(m.canContinue(),false);
 assert.equal(m.closedMessage(),'2026 is closed: 2027 opened on it. Work in 2027, or switch years to look back.');assert.equal(m.actBlock(),m.closedMessage());
 const n=log.length;await assert.rejects(()=>m.act('accept','CASE-260401-2'),/2026 is closed: 2027 opened on it\. Work in 2027, or switch years to look back\./);assert.equal(log.length,n,'refused before the engine is asked');assert.equal(m.actions.length,1);
 assert.throws(()=>m.addEpisode({from:'2026-06-01',settings:{a:{b:1}}}),/2026 is closed/);assert.throws(()=>m.reset(),/2026 is closed/);assert.throws(()=>m.continueYear(),/Continue from 2027/);
 // The map's days are 2026's: a closed 2026 keeps its outages, and nothing lands in 2027.
 assert.equal(m.recordDay('2026-06-02',[{utility:'gas',start:5,end:50,premiseIds:['P7']}],{commands:true}),false);assert.equal(m.setOutages('2026-03-11',[]),false);
 assert.equal(m.yearState(2026).outages['2026-06-02'],undefined);assert.deepEqual(m.yearState(2027).outages,{});
 // Viewing back is fine: the view date moves within 2026, and 2026's requests are 2026's as before.
 assert.equal(m.setAsOf('2026-07-01'),true);assert.equal(m.setAsOf('2027-02-01'),false,'a day of another year is not taken');assert.equal(m.asOf,'2026-07-01');
 await m.summary();assert.equal('year' in log.at(-1).body,false);assert.equal('previous' in log.at(-1).body,false);assert.equal(log.at(-1).body.asOf,'2026-07-01');
 assert.throws(()=>m.setYear(2029),/not open/);assert.equal(m.setYear(2027),true);assert.equal(m.canAct(),true);assert.equal(m.asOf,'2027-01-31');
 // The operations day (2026's) keeps 2026's input whichever year is active.
 assert.deepEqual(m.context().actions,OLD_STATE.actions);assert.equal(m.context().outages.length,1);assert.equal(m.lockedBefore('2026-04-01'),'2026-04-10');
});

test('years run to 2030, and each year has its own date bounds (2028 has 29 February)',async()=>{
 const m=new EngineM2C({townRef:'small_town',townId:'town-1',storage:memory(),fetchImpl:fakeEngine([])});
 for(const y of [2027,2028,2029,2030])assert.equal(m.continueYear(),y);
 assert.deepEqual(m.years,[2026,2027,2028,2029,2030]);assert.equal(m.canContinue(),false);assert.throws(()=>m.continueYear(),/runs to 2030/);
 assert.equal(m.body().previous.length,4);
 m.setYear(2028);assert.equal(m.yearStart(),'2028-01-01');assert.equal(m.yearEnd(),'2028-12-31');assert.equal(m.asOf,'2028-01-31');
 assert.equal(m.setAsOf('2028-02-29'),true);assert.equal(m.asOf,'2028-02-29');
 const {episodeDates}=await import('../dist/m2c.js');assert.equal(episodeDates({id:'x',episodes:[{startOffset:0,durationDays:90,settings:{}}]},'2028-12-01')[0].to,'2028-12-31','clamped at its own year end');
 assert.equal(episodeDates({id:'x',episodes:[{startOffset:0,durationDays:2,settings:{}}]},'2028-02-28')[0].to,'2028-02-29');
});

test('a sporadic episode keeps its own copy of its pattern; a steady one has no pattern key, and an edit can set or drop it',async()=>{
 const {episodeDates}=await import('../dist/m2c.js'),log=[],store=memory();
 const pattern={kind:'spikes',count:6,length:[1,2],strength:[0.7,1.0]};
 const sc={id:'headend_hiccups',title:'Head-end hiccups',episodes:[{title:'Head end down',startOffset:0,durationDays:182,ramp:0,settings:{reading:{ami_missed_read:0.9}},pattern},{title:'Steady',startOffset:0,durationDays:9,settings:{reading:{ami_missed_read:0.9}}}]};
 const [spiky,steady]=episodeDates(sc,'2026-01-12');
 assert.deepEqual(spiky,{title:'Head end down',scenario:'headend_hiccups',from:'2026-01-12',to:'2026-07-12',ramp:0,settings:{reading:{ami_missed_read:0.9}},pattern:{kind:'spikes',count:6,length:[1,2],strength:[0.7,1.0]}},'the template\'s pattern comes along as it is');
 spiky.pattern.length[1]=9;assert.equal(pattern.length[1],2,'a copy, not the library\'s own');assert.equal('pattern' in steady,false,'a steady template gives no pattern key');
 const m=new EngineM2C({api:'/api',townRef:'small_town',townId:'town-1',storage:store,fetchImpl:fakeEngine(log)});m.setAsOf('2026-07-15');
 const src={...steady,pattern:{kind:'days',share:0.3,strength:[0.2,1],independent:true}},a=m.addEpisode(src),b=m.addEpisode(steady);
 src.pattern.share=0.9;assert.equal(a.pattern.share,0.3,'addEpisode copies the pattern');assert.equal('pattern' in b,false);assert.equal('pattern' in m.addEpisode({...steady,pattern:null}),false,'never a null pattern');
 await m.summary();assert.deepEqual(log.at(-1).body.episodes.map(x=>x.pattern?.kind??null),['days',null,null],'sent with the run');
 assert.equal(m.updateEpisode(a.id,{ramp:2}).pattern.kind,'days','a patch without pattern keeps it');
 assert.equal('pattern' in m.updateEpisode(a.id,{pattern:null,title:'Steady now'}),false,'pattern: null makes it steady again');
 const p={kind:'spikes',count:2,length:[1,1],strength:[1,1],workdays:false,independent:false};m.updateEpisode(b.id,{pattern:p});p.count=5;assert.equal(m.episodes.find(x=>x.id===b.id).pattern.count,2,'an edit stores a copy');
 assert.deepEqual(new EngineM2C({townRef:'small_town',townId:'town-1',storage:store}).episodes.map(x=>x.pattern?.kind??null),[null,'spikes',null],'persisted');
});
