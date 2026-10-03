import test from 'node:test';
import assert from 'node:assert/strict';
import {ROUTE,parseYearRoute,yearHash,calendarModel,episodeSpans,episodeColor,EPISODE_COLORS,parseSettingValue,draftEpisode,settingRows,niceTicks,linePath,barPath,fmtTick,fmtValue,chartModel,readout,describeChart,chartSvg,chartTable,CHARTS,PHASES,rangeLabel,longDay} from '../dist/year-page.js';
import {EngineM2C,episodeDates,YEAR_END} from '../dist/m2c.js';

function memory(){const m=new Map();return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v)};}
const LIBRARY={schemaVersion:'m2c-scenarios/1.0',groups:[{id:'staffing',title:'Staffing'}],
 scenarios:[{id:'half_staff_billing',title:'Billing at half staff',group:'staffing',description:'Half the analysts.',watch:'Backlog.',tags:['backlog'],
  episodes:[{title:'Half the analysts',startOffset:0,durationDays:null,ramp:0,settings:{process:{analysts:'*0.5'}}},{title:'Overtime after',startOffset:10,durationDays:30,ramp:5,settings:{process:{analysts:'+2'},vee:{high_ratio:3}}}]}],coming:[]};
// A trend month as the engine writes it: figures and `complete` for a month before the run date, figures to the run
// date and `complete: false` for the month holding it, null figures after it.
function month(n,figures,{partial=false,end=null}={}){const cal=calendarModel()[n-1];return {month:n,label:cal.label,start:cal.start,end:end||cal.end,complete:!!figures&&!partial,reads:null,cases:null,cost:null,billing:null,collections:null,...(figures||{})};}
function fakeTrend(){return [month(1,{cases:{opened:210,resolved:190,backlog:45,byQueue:{VEE_REVIEW:20,ESTIMATION:15,FIELD:10}},reads:{missedPct:.028,estimatedPct:.019},cost:{total:1484.5,carry:300},billing:{blocked:40,invoiced:812345.67,collected:790000,overdue:12000,receivable:60000},collections:{reminders:80,notices:30,disconnectNotices:5,disconnected:0,phases:{current:2000,overdue:40,reminder:45,'overdue notice':27,'winter moratorium':0,'dunning hold':0,'payment arrangement':0,'disconnection notice':51,disconnected:0}}}),
 month(2,{cases:{opened:180,resolved:200,backlog:52,byQueue:{VEE_REVIEW:30,ESTIMATION:12,FIELD:10}},reads:{missedPct:.031,estimatedPct:.02},cost:{total:1600,carry:280},billing:{blocked:35,invoiced:800000,collected:810000,overdue:11000,receivable:58000},collections:{reminders:70,notices:35,disconnectNotices:6,disconnected:1,phases:{current:2010,overdue:38,reminder:40,'overdue notice':30,'winter moratorium':0,'dunning hold':0,'payment arrangement':2,'disconnection notice':48,disconnected:1}}}),
 month(3,{cases:{opened:150,resolved:160,backlog:60,byQueue:{VEE_REVIEW:35,ESTIMATION:15,FIELD:10}},reads:{missedPct:.03,estimatedPct:.021},cost:{total:900,carry:150},billing:{blocked:20,invoiced:400000,collected:390000,overdue:10000,receivable:55000},collections:{reminders:40,notices:10,disconnectNotices:2,disconnected:0,phases:{current:2015,overdue:30,reminder:20,'overdue notice':0,'winter moratorium':0,'dunning hold':0,'payment arrangement':0,'disconnection notice':0,disconnected:0}}},{partial:true,end:'2026-03-15'}),
 ...Array.from({length:9},(_,i)=>month(i+4,null))];}

test('the year route round-trips and matches nothing else',()=>{
 assert.deepEqual(parseYearRoute('#/year'),{year:2026});assert.equal(parseYearRoute('#/year/3'),null);assert.equal(parseYearRoute('#/data'),null);assert.equal(parseYearRoute(''),null);
 assert.equal(yearHash(),'#/year');assert.deepEqual(parseYearRoute(yearHash()),{year:2026});assert.ok(ROUTE.test('#/year'));
});

test('episodeDates turns a scenario into concrete episodes for the inflict day',()=>{
 const sc=LIBRARY.scenarios[0],eps=episodeDates(sc,'2026-03-01');
 assert.deepEqual(eps,[{title:'Half the analysts',scenario:'half_staff_billing',from:'2026-03-01',to:null,ramp:0,settings:{process:{analysts:'*0.5'}}},
  {title:'Overtime after',scenario:'half_staff_billing',from:'2026-03-11',to:'2026-04-09',ramp:5,settings:{process:{analysts:'+2'},vee:{high_ratio:3}}}]);
 eps[0].settings.process.analysts='x';assert.equal(sc.episodes[0].settings.process.analysts,'*0.5','settings are copied, not shared');
 const late=episodeDates(sc,'2026-12-20');assert.equal(late[0].to,null);assert.equal(late[1].from,'2026-12-30');assert.equal(late[1].to,YEAR_END,'the end is clamped at the year end');
 assert.equal(episodeDates(sc,'2026-12-31')[1].from,YEAR_END,'so is a start past it');
 assert.deepEqual(episodeDates({id:'x',title:'X',episodes:[{startOffset:0,durationDays:1,settings:{a:{b:1}}}]},'2026-05-05')[0],{title:'X',scenario:'x',from:'2026-05-05',to:'2026-05-05',ramp:0,settings:{a:{b:1}}},'one day is one day');
 assert.deepEqual(episodeDates(null,'2026-05-05'),[]);
});

test('the calendar model lays 2026 out Monday first',()=>{
 const cal=calendarModel();assert.equal(cal.length,12);
 assert.deepEqual(cal[0],{month:1,label:'Jan',days:31,offset:3,weeks:5,start:'2026-01-01',end:'2026-01-31'},'1 Jan 2026 is a Thursday');
 assert.equal(cal[1].offset,6,'1 Feb 2026 is a Sunday');assert.equal(cal[1].days,28);assert.equal(cal[1].weeks,5);
 assert.equal(cal[11].end,'2026-12-31');assert.equal(cal[2].start,'2026-03-01');assert.equal(cal.reduce((n,m)=>n+m.days,0),365);
 assert.equal(calendarModel(2024)[1].days,29);
});

test('episodeSpans gives the day ranges an episode covers in a month, continuing across months',()=>{
 const eps=[{id:'EP-2',from:'2026-01-20',to:'2026-02-05'},{id:'EP-1',from:'2026-03-10',to:null}];
 assert.deepEqual(episodeSpans(eps,1),[{id:'EP-2',index:0,lane:0,from:20,to:31,startsHere:true,endsHere:false}]);
 assert.deepEqual(episodeSpans(eps,2),[{id:'EP-2',index:0,lane:0,from:1,to:5,startsHere:false,endsHere:true}]);
 assert.deepEqual(episodeSpans(eps,3),[{id:'EP-1',index:1,lane:0,from:10,to:31,startsHere:true,endsHere:false}]);
 assert.deepEqual(episodeSpans(eps,calendarModel()[11]),[{id:'EP-1',index:1,lane:0,from:1,to:31,startsHere:false,endsHere:true}],'an open end runs to the year end');
 assert.deepEqual(episodeSpans(eps,6).map(s=>s.id),['EP-1']);assert.deepEqual(episodeSpans([],4),[]);
 const both=episodeSpans([{id:'a',from:'2026-05-01',to:'2026-05-03'},{id:'b',from:'2026-05-02',to:null}],5);assert.deepEqual(both.map(s=>[s.index,s.lane]),[[0,0],[1,1]],'each episode in a month takes its own lane');
 assert.equal(episodeColor(0),EPISODE_COLORS[0]);assert.equal(episodeColor(8),EPISODE_COLORS[0]);assert.equal(episodeColor(3),'#eb6834');
 assert.equal(rangeLabel({from:'2026-03-01',to:null}),'1 Mar – year end');assert.equal(rangeLabel({from:'2026-03-01',to:'2026-04-09'}),'1 Mar – 9 Apr');assert.equal(longDay('2026-03-05'),'Thu 5 Mar 2026');
});

test('setting values parse as absolute numbers, booleans or base operators; a draft becomes one episode',()=>{
 assert.equal(parseSettingValue('*0.5'),'*0.5');assert.equal(parseSettingValue(' + 2 '),'+2');assert.equal(parseSettingValue('-1'),'-1');
 assert.equal(parseSettingValue('3'),3);assert.equal(parseSettingValue('2.5'),2.5);assert.equal(parseSettingValue('true'),true);assert.equal(parseSettingValue('false'),false);
 assert.equal(parseSettingValue('recent_average'),'recent_average');assert.equal(parseSettingValue(''),undefined);assert.equal(parseSettingValue(4),4);
 assert.deepEqual(settingRows({process:{analysts:'*0.5'},vee:{high_ratio:3}}),[['process','analysts','*0.5'],['vee','high_ratio','3']]);
 const ok=draftEpisode({title:' Half ',scenario:'s',from:'2026-03-01',to:'',ramp:'3',settings:{process:{analysts:'*0.5',rpa:'true'}}});
 assert.deepEqual(ok,{episode:{title:'Half',scenario:'s',from:'2026-03-01',to:null,ramp:3,settings:{process:{analysts:'*0.5',rpa:true}}}});
 assert.equal(draftEpisode({from:'2026-03-01',to:'2026-12-31',ramp:0,settings:{a:{b:'1'}}}).episode.to,null,'an end on the last day is the year end');
 assert.equal(draftEpisode({from:'2026-03-01',to:'2026-06-30',ramp:'',settings:{a:{b:'1'}}}).episode.to,'2026-06-30');
 assert.match(draftEpisode({from:'2025-03-01',settings:{a:{b:'1'}}}).error,/2026 date/);assert.match(draftEpisode({from:'2026-03-01',to:'2026-02-01',settings:{a:{b:'1'}}}).error,/before the start/);
 assert.match(draftEpisode({from:'2026-03-01',ramp:'1.5',settings:{a:{b:'1'}}}).error,/whole number/);assert.match(draftEpisode({from:'2026-03-01',settings:{a:{b:''}}}).error,/a\.b needs a value/);
 assert.match(draftEpisode({from:'2026-03-01',settings:{}}).error,/at least one setting/);
});

test('chart scales: clean ticks, a line that skips empty months, rounded columns, compact ticks',()=>{
 assert.deepEqual(niceTicks(45),{max:50,ticks:[0,10,20,30,40,50]});assert.deepEqual(niceTicks(0.028),{max:0.03,ticks:[0,0.01,0.02,0.03]});
 assert.deepEqual(niceTicks(812345.67).ticks,[0,200000,400000,600000,800000,1000000]);assert.deepEqual(niceTicks(163).ticks,[0,50,100,150,200]);assert.deepEqual(niceTicks(0),{max:1,ticks:[0,1]});assert.deepEqual(niceTicks(4),{max:4,ticks:[0,1,2,3,4]});
 const x=i=>i*10,y=v=>100-v;
 assert.equal(linePath([10,20,null,40],x,y),'M0 90 L10 80 M30 60 L30 60','a lone point after a gap draws as a dot');
 assert.equal(linePath([null,5,6,null,null],x,y),'M10 95 L20 94');assert.equal(linePath([null,null],x,y),'');
 assert.equal(barPath(10,20,16,30),'M10 50 V24 Q10 20 14 20 H22 Q26 20 26 24 V50 Z');assert.equal(barPath(10,20,16,0),'');assert.match(barPath(10,48,16,2),/Q10 48 11 48/,'a short column rounds within its height');
 assert.equal(fmtTick(812345.67,'money'),'$812K');assert.equal(fmtTick(1234567,'money'),'$1.2M');assert.equal(fmtTick(60,'money'),'$60');assert.equal(fmtTick(0,'money'),'$0');
 assert.equal(fmtTick(6363,'int'),'6.4K');assert.equal(fmtTick(45,'int'),'45');assert.equal(fmtTick(250000,'int'),'250K');assert.equal(fmtTick(0.028,'pct'),'2.8%');assert.equal(fmtTick(0.1,'pct'),'10%');assert.equal(fmtTick(0,'pct'),'0%');
 assert.equal(fmtValue(0.028,'pct'),'2.8%');assert.equal(fmtValue(1484.5,'money'),'$1,484.50');assert.equal(fmtValue(45149,'int'),'45,149');assert.equal(fmtValue(null,'int'),'—');
});

test('chart models read the engine months, leave future months blank and describe themselves',()=>{
 const months=fakeTrend(),backlog=chartModel(CHARTS[0],months),cases=chartModel(CHARTS[1],months),phases=chartModel(CHARTS.find(c=>c.id==='phases'),months),dunning=chartModel(CHARTS.find(c=>c.id==='dunning'),months);
 assert.deepEqual(backlog.series[0].values,[45,52,60,null,null,null,null,null,null,null,null,null]);assert.equal(backlog.latest,2);assert.equal(backlog.max,60);
 assert.deepEqual(backlog.partial.slice(0,4),[false,false,true,false],'the month holding the run date is drawn and marked partial');
 assert.equal(readout(backlog,1),'Feb: Backlog 52 · VEE review 30 · Estimation 12 · Field 10');assert.equal(readout(backlog,2),'Mar (to 15 Mar): Backlog 60 · VEE review 35 · Estimation 15 · Field 10');assert.equal(readout(backlog,5),'Jun: no figures yet');
 assert.equal(describeChart(backlog),'Case backlog, open cases at month end. 3 months, Jan to Mar 2026, Mar to the run date only. Latest, Mar (to 15 Mar): Backlog 60 · VEE review 35 · Estimation 15 · Field 10.');
 assert.deepEqual(cases.series.map(s=>[s.label,s.color,s.values[0]]),[['Opened','#2a78d6',210],['Resolved','#eb6834',190]]);assert.equal(cases.max,250);
 assert.equal(phases.series.length,PHASES.length);assert.equal(phases.series[0].label,'Overdue');assert.equal(phases.tops[0],163,'a stack is as tall as its parts');assert.match(readout(phases,0),/Current \(not in collections\) 2,000$/);
 assert.deepEqual(dunning.tops.slice(0,4),[115,112,52,null]);
 const empty=chartModel(CHARTS[0],[]);assert.equal(empty.latest,-1);assert.equal(describeChart(empty),'Case backlog, open cases at month end. No figures yet.');
 const svg=chartSvg(cases,{asOf:'2026-03-15',episodes:[{id:'EP-1',title:'Half',from:'2026-02-01',to:null}],id:'t'});
 assert.match(svg,/<svg class="yr-svg" viewBox="0 0 320 150" role="img" aria-labelledby="t-t" aria-describedby="t-d">/);assert.match(svg,/<title id="t-t">Cases opened and resolved<\/title>/);
 assert.equal((svg.match(/class="yr-line"/g)||[]).length,2);assert.equal((svg.match(/class="yr-hit"/g)||[]).length,3,'one hit target per month with figures');assert.match(svg,/class="yr-band"[^>]*fill="#4a3aa7"/);assert.match(svg,/class="yr-run"/);
 assert.match(svg,/<text class="yr-tick" x="38" y="[\d.]+" text-anchor="end">250<\/text>/);assert.equal((svg.match(/<circle/g)||[]).length,4,'an end dot with a surface ring per series');assert.match(svg,/r="3" fill="#fff" stroke="#2a78d6" stroke-width="2"/,'a partial month ends in a hollow dot');
 const whole=chartSvg(chartModel(CHARTS[1],months.slice(0,2)),{id:'w'});assert.match(whole,/r="4" fill="#eb6834"/,'a whole month ends in a filled dot');
 const stack=chartSvg(dunning,{id:'s'});assert.ok(stack.includes('<path d="M'));assert.ok(stack.includes('<rect x='),'stacked segments');
 const table=chartTable(backlog);assert.match(table,/<th>Month<\/th><th>Backlog<\/th><th>VEE review<\/th><th>Estimation<\/th><th>Field<\/th>/);assert.match(table,/<td>Jan<\/td><td>45<\/td><td>20<\/td><td>15<\/td><td>10<\/td>/);assert.match(table,/<td>Mar\*<\/td><td>60<\/td>/);assert.match(table,/<td>Apr<\/td><td>—<\/td>/);assert.match(table,/\* to the run date/);
});

test('the client keeps episodes with the run: sorted, ided, persisted, sent on every request',async()=>{
 const store=memory(),log=[];
 const fetchImpl=async(url,opts={})=>{const body=opts.body?JSON.parse(opts.body):null;log.push({url,body});
  if(url.endsWith('/m2c/scenarios'))return {ok:true,json:async()=>LIBRARY};
  return {ok:true,json:async()=>({schemaVersion:'m2c-trend/1.0',asOf:body.asOf,months:[],echo:body})};};
 const m=new EngineM2C({api:'/api',townRef:'small_town',townId:'town-1',storage:store,fetchImpl});m.setAsOf('2026-07-15');
 assert.deepEqual(m.episodes,[]);assert.equal('episodes' in m.body(),false);assert.equal('episodes' in m.context(),false);
 const b=m.addEpisode({title:'Later',scenario:'s',from:'2026-05-01',to:'2026-05-31',ramp:0,settings:{vee:{high_ratio:3}}});
 const a=m.addEpisode({title:'Half the analysts',scenario:'half_staff_billing',from:'2026-03-01',to:null,ramp:0,settings:{process:{analysts:'*0.5'}}});
 assert.equal(b.id,'EP-1');assert.equal(a.id,'EP-2');assert.deepEqual(m.episodes.map(x=>x.id),['EP-2','EP-1'],'sorted by from');
 assert.deepEqual(m.episodes[0],{id:'EP-2',title:'Half the analysts',scenario:'half_staff_billing',from:'2026-03-01',to:null,ramp:0,settings:{process:{analysts:'*0.5'}}});
 assert.deepEqual(m.body().episodes,m.episodes);assert.deepEqual(m.context().episodes,m.episodes);assert.deepEqual(m.export().episodes,m.episodes);
 const t=await m.trend();assert.equal(log.at(-1).url,'/api/m2c/trend');assert.deepEqual(log.at(-1).body,{town:'small_town',actions:[],episodes:m.episodes,asOf:'2026-07-15'});assert.equal(t.schemaVersion,'m2c-trend/1.0');
 await m.trend();assert.equal(log.length,1,'the same run is cached');
 assert.equal(m.updateEpisode('EP-1',{from:'2026-02-01',ramp:4}).ramp,4);assert.deepEqual(m.episodes.map(x=>x.id),['EP-1','EP-2'],'re-sorted after an edit');assert.equal(m.updateEpisode('EP-9',{}),null);
 await m.trend();assert.equal(log.length,2,'a changed episode is a new run');
 const again=new EngineM2C({api:'/api',townRef:'small_town',townId:'town-1',storage:store,fetchImpl});assert.equal(again.episodes.length,2);assert.equal(again.episodes[0].from,'2026-02-01');
 assert.equal(m.removeEpisode('EP-1'),true);assert.equal(m.removeEpisode('EP-1'),false);assert.deepEqual(m.episodes.map(x=>x.id),['EP-2']);
 assert.equal(m.addEpisode({from:'2026-09-01',settings:{a:{b:1}}}).id,'EP-3','ids are never reused');assert.equal(m.episodes[1].title,'Episode');
 const lib=await m.scenarios();await m.scenarios();assert.equal(lib.scenarios[0].id,'half_staff_billing');assert.equal(log.filter(x=>x.url.endsWith('/m2c/scenarios')).length,1,'the library is fetched once');
 m.clearEpisodes();assert.deepEqual(m.episodes,[]);assert.equal('episodes' in m.body(),false);assert.equal(new EngineM2C({townRef:'small_town',townId:'town-1',storage:store}).episodes.length,0);
 m.reset();assert.deepEqual(m.actions,[]);
});

test('the field work charts read the trend field block',()=>{
 const c=Object.fromEntries(CHARTS.map(x=>[x.id,x]));
 assert.ok(c.fieldDone&&c.fieldBacklog&&c.fieldOnTime&&c.fieldCost);
 const months=[{month:1,label:'Jan',start:'2026-01-01',end:'2026-01-31',complete:true,field:{created:140,completed:130,remote:12,overdue:4,onTimePct:0.97,responseMin:34,responseP90Min:52,daysToComplete:2.4,hours:310.5,overtimeHours:6,utilisationPct:0.61,byProgram:{emergency:3,service:60,meter:40,maintenance:25,construction:2},backlog:{emergency:0,service:5,meter:30,maintenance:12,construction:8},cost:{labour:24000,materials:9000,total:33000}}}];
 assert.deepEqual(chartModel(c.fieldDone,months).series.map(s=>s.values[0]),[3,60,40,25,2]);
 assert.deepEqual(chartModel(c.fieldBacklog,months).series.map(s=>s.values[0]),[0,5,30,12,8]);
 assert.equal(chartModel(c.fieldOnTime,months).series[0].values[0],0.97);
 assert.deepEqual(chartModel(c.fieldCost,months).series.map(s=>s.values[0]),[24000,9000]);
 assert.deepEqual(c.fieldOnTime.detail(months[0])[0],['Emergency response (min)',34]);
 assert.deepEqual(c.fieldBacklog.detail(months[0]),[['Overdue',4],['Crew utilisation','61%']]);
 assert.equal(chartModel(c.fieldDone,[{month:1,label:'Jan',start:'2026-01-01',end:'2026-01-31',complete:true,field:null}]).latest,-1);
});

test('inflicting runs to the last period end, including open-ended and year-clamped periods',async()=>{
 const {episodeRunEnd}=await import('../dist/year-page.js');
 assert.equal(episodeRunEnd([{to:'2026-04-30'},{to:'2026-03-31'}]),'2026-04-30');
 assert.equal(episodeRunEnd([{to:null},{to:'2026-03-31'}]),'2026-12-31');
 const late=episodeDates({id:'late',episodes:[{durationDays:90,settings:{}}]},'2026-12-01');assert.equal(episodeRunEnd(late),'2026-12-31');
});

test('reviewed voice tweaks append periods, preserve user decisions and run through the validated date',async()=>{
 const {inflictReviewedEpisodes}=await import('../dist/year-page.js');
 const m=new EngineM2C({townRef:'whitby_small',townId:'town-1',storage:memory()});
 m.setAsOf('2026-03-31');m.setSettings({process:{analysts:4}});m.seed='keep-me';m.actions=[{id:'ACT-1',day:'2026-03-01'}];m.outages={};
 const earlier=m.addEpisode({title:'Existing',from:'2026-01-01',to:'2026-02-01',settings:{process:{analysts:3}}});
 const patch={name:'Voice tweak',runTo:'2026-05-12',episodes:[{title:'Half staff',from:'2026-04-01',to:'2026-05-12',ramp:0,settings:{process:{analysts:'*0.5'}}}]};
 let analysed;
 await inflictReviewedEpisodes(m,patch,async()=>{analysed=structuredClone(m.body());return null;});
 assert.equal(analysed.asOf,'2026-05-12');assert.equal(m.episodes.length,2);assert.deepEqual(m.episodes[0],earlier);
 assert.deepEqual(m.settings,{process:{analysts:4}});assert.equal(m.seed,'keep-me');assert.equal(m.actions.length,1);assert.equal(m.townRef,'whitby_small');
 const refusal=Object.assign(Error('Overlap rejected'),{status:422});
 await assert.rejects(inflictReviewedEpisodes(m,patch,async()=>refusal),/Overlap rejected/);
 assert.equal(m.episodes.length,2);assert.equal(m.asOf,'2026-05-12');
 const reopened=new EngineM2C({townRef:'whitby_small',townId:'town-1',storage:m.storage});assert.equal(reopened.episodes.length,2);
 await assert.rejects(inflictReviewedEpisodes(m,patch,async()=>{throw Error('Network down');}),/Network down/);
 assert.equal(m.episodes.length,2,'network failure restores episodes before retry');
 m.readOnly=true;await assert.rejects(inflictReviewedEpisodes(m,patch,async()=>null),/live simulation/);
});

test('the contact centre charts read the trend contact block',()=>{
 const c=Object.fromEntries(CHARTS.map(x=>[x.id,x]));
 assert.ok(c.contacts&&c.service&&c.contactCost);
 const months=[{month:1,label:'Jan',start:'2026-01-01',end:'2026-01-31',complete:true,contact:{byGroup:{billing:120,payments:10,service:30,emergency:20,complaints:2},byReason:{balance:70,high_bill:12,outage:18},serviceLevelPct:0.95,abandonedPct:0.04,asaS:6.2,callbacks:3,occupancyPct:0.07,cost:{total:7200}}}];
 const stack=chartModel(c.contacts,months);assert.deepEqual(stack.series.map(s=>s.values[0]),[120,10,30,20,2]);
 assert.deepEqual(c.contacts.detail(months[0])[0],['Balance',70]);
 const svc=chartModel(c.service,months);assert.deepEqual(svc.series.map(s=>s.values[0]),[0.95,0.04]);
 assert.equal(chartModel(c.contactCost,months).series[0].values[0],7200);
 const none=chartModel(c.contacts,[{month:1,label:'Jan',start:'2026-01-01',end:'2026-01-31',complete:true,contact:null}]);assert.equal(none.latest,-1);
});
