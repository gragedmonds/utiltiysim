import test from 'node:test';
import assert from 'node:assert/strict';
import {upstreamEvents,networkLayout,districtSpan,stackPool,paged,utilityKpis,districtRows,loadBatch,batchURL,runLink,dayModel,dayCharts,monthRows,summarize,chartCard,daySvg,districtsMarkup,statusMarkup,kpiMarkup,staffModels,staffMarkup,eventsMarkup,sharedWeather,MISSING,OTHER_COLOR,TOP} from '../dist/utility.js';

const KEY='c'.repeat(64),RUN=n=>String(n).repeat(64).slice(0,64);
const ids=n=>Array.from({length:n},(_,i)=>`district-${String(i+1).padStart(4,'0')}`);
const days=(n,f)=>Array.from({length:n},(_,i)=>f(i));
function network(){const d=ids(6),ev=(id,utility,day,start,end,label)=>({id,utility,day,start,end,label});
 const m1=ev('UP-M1-20260219','water','2026-02-19',24723,53674,'Transmission main M1 broke'),t2=ev('UP-T2-20260521','electric','2026-05-21',23174,28456,'Transmission circuit T2 tripped'),odd=ev('custom-gas-event','gas','2026-01-05',3600,10800,'Gate station G1 shut in');
 return {schemaVersion:'utility-network/1.0',districts:d,seed:'s',assets:[{id:'T1',kind:'circuit',utility:'electric',districts:d.slice(0,4)},{id:'T2',kind:'circuit',utility:'electric',districts:d.slice(4)},{id:'P1',kind:'plant',utility:'water',districts:d},{id:'M1',kind:'main',utility:'water',districts:d.slice(0,4)},{id:'M2',kind:'main',utility:'water',districts:d.slice(4)},{id:'G1',kind:'gate',utility:'gas',districts:d}],
  upstream:Object.fromEntries(d.map((id,i)=>[id,{stormSeed:'s:storms',events:[odd,...(i<4?[m1]:[t2])]}]))};}
// A shared plan of `n` districts over `len` days: district i has i+1 analysts at home and one more on its float days.
function staffing(n=10,len=4){const d=ids(n),home=d.map((_,i)=>i+1),staff=d.map((_,i)=>days(len,t=>home[i]+(t<i%len?1:0)));
 return {schemaVersion:'utility-staffing/1.0',floatShare:.3,districts:d,pools:{analysts:{total:sum(home)+3,home,float:3,unitMinutes:d.map(()=>360)},crew_meter:{total:.4,home:d.map(()=>.03),float:.1,unitMinutes:d.map(()=>480)}},
  staff:{analysts:staff,crew_meter:d.map(()=>days(len,t=>t===3?.04:.03))},predictedWaiting:{analysts:d.map((_,i)=>days(len,t=>i===0?60*t:0)),crew_meter:d.map(()=>days(len,()=>30))},schedules:{}};}
const sum=a=>a.reduce((s,v)=>s+v,0);
function rollup({complete=true}={}){const n=5;return {schemaVersion:'utility-batch/1.0',complete,asOf:'2026-12-31',totalHomes:300,accounts:410,registers:1100,staffing:'shared',network:'connected',note:'Additive <results>.',
 months:[{month:2,billing:{billed:200,collected:150,receivable:90,overdue:10},cases:{opened:7,resolved:6,backlog:3}},{month:1,billing:{billed:100,collected:80,receivable:40,overdue:5},cases:{opened:5,resolved:5,backlog:2}}],
 daily:{start:'2026-01-30',days:n,queues:{VEE_REVIEW:{opened:days(n,()=>1),closed:days(n,()=>1),backlog:days(n,i=>i)},ESTIMATION:{opened:days(n,()=>0),closed:days(n,()=>0),backlog:days(n,()=>2)}},
  staff:{analysts:{people:days(n,()=>3),offeredMin:days(n,()=>0),doneMin:days(n,()=>0),done:days(n,()=>0),waiting:days(n,i=>i*2),oldestDays:days(n,i=>i)},supervisors:{people:days(n,()=>1),offeredMin:days(n,()=>0),doneMin:days(n,()=>0),done:days(n,()=>0),waiting:days(n,()=>0),oldestDays:days(n,()=>0)}},
  crews:{meter:{crews:days(n,()=>.4),availableMin:days(n,()=>190),busyMin:days(n,()=>100),overtimeMin:days(n,()=>0),waitingMin:days(n,()=>120),oldestDays:days(n,()=>3)}},
  contact:{agents:days(n,()=>2),availableS:days(n,()=>0),busyS:days(n,()=>0),staffCost:days(n,()=>0),contacts:days(n,()=>10),answered:days(n,()=>6),abandoned:days(n,()=>2),selfServed:days(n,()=>2),callbacks:days(n,()=>0),emergency:days(n,()=>0),closed:days(n,()=>0)},
  outages:{electric:{customers:days(n,()=>0),customerHours:days(n,i=>i===2?50:0)},gas:{customers:days(n,()=>0),customerHours:days(n,i=>i===4?12.5:0)}}}};}
function job({staffing:mode='shared',connected=true,done=3,n=3}={}){return {schemaVersion:'utility-batch/1.0',key:KEY,homes:n*100,status:done===n?'complete':'paused',
 inputs:{staffing:mode,...(mode==='shared'?{floatShare:.3}:{}),...(connected?{network:'connected'}:{}),request:{asOf:'2026-12-31'}},
 districts:ids(n).map((id,i)=>({id,homes:100,...(mode==='shared'?{probe:{premises:140+i}}:{}),...(i<done?{result:{runKey:RUN(i+1),townId:'town-'+i,generatedHomes:100,directory:'/private/path'}}:{})}))};}
const fetchFrom=files=>{const asked=[];const f=async url=>{const name=String(url).split('/').at(-1);asked.push(name);if(!(name in files))return {ok:false,status:404,text:async()=>'Not found'};return {ok:true,status:200,text:async()=>typeof files[name]==='string'?files[name]:JSON.stringify(files[name])};};f.asked=asked;return f;};

test('upstream events: each once, with its asset, hours and the districts it reached in layout order',()=>{
 const net=network();net.upstream['district-0002'].events.push({...net.upstream['district-0001'].events[1]});const evs=upstreamEvents(net);
 assert.deepEqual(evs.map(ev=>ev.id),['custom-gas-event','UP-M1-20260219','UP-T2-20260521'],'unique by id, by day');
 const m1=evs[1];assert.equal(m1.asset,'M1');assert.equal(m1.kind,'main');assert.deepEqual(m1.districts,ids(4));assert.ok(Math.abs(m1.hours-(53674-24723)/3600)<1e-9);
 assert.equal(evs[0].asset,'G1','an id without the asset falls back to the asset of that utility feeding exactly those districts');assert.equal(evs[0].hours,2);
 assert.deepEqual(evs[2].districts,['district-0005','district-0006']);
 const lay=networkLayout(net,evs);assert.deepEqual(lay.map(a=>[a.id,a.events]),[['T1',0],['T2',1],['P1',0],['M1',1],['M2',0],['G1',1]]);
 assert.equal(sharedWeather(net),true);assert.equal(upstreamEvents(null).length,0);assert.equal(upstreamEvents({upstream:{a:{events:[{id:'UP-X9-20260101',utility:'gas'}]}}})[0].asset,null,'an unknown asset stays unknown');
});

test('district spans run neighbours together in layout order',()=>{
 const order=ids(8);assert.equal(districtSpan(['district-0003','district-0001','district-0002','district-0004','district-0006'],order),'district-0001 – district-0004, district-0006');
 assert.equal(districtSpan(['district-0005','district-0006'],order),'district-0005, district-0006');assert.equal(districtSpan(['x','district-0002'],order),'district-0002, x');assert.equal(districtSpan([],order),'');
});

test('a pool stacks its top 8 districts in district order and folds the rest into Other',()=>{
 const plan=staffing(10,4),s=stackPool(plan,'analysts');
 assert.equal(s.series.length,TOP+1);assert.deepEqual(s.series.slice(0,TOP).map(x=>x.id),ids(10).slice(2),'the eight with the most staff-days, in district order');
 assert.equal(s.series.at(-1).label,'Other (2 districts)');assert.equal(s.series.at(-1).color,OTHER_COLOR);assert.equal(s.folded,2);
 for(let t=0;t<4;t++)assert.equal(sum(s.series.map(x=>x.values[t])),sum(plan.staff.analysts.map(r=>r[t])),'every day adds up to the pool at work');
 assert.deepEqual(s.districts.map(d=>d.floatDays),[0,1,2,3,0,1,2,3,0,1]);assert.equal(s.districts[0].color,OTHER_COLOR);assert.equal(s.districts[2].color,s.series[0].color);
 assert.deepEqual(s.predicted,[0,60,120,180]);assert.equal(s.float,3);assert.equal(s.people,true);
 const few=stackPool(staffing(3,4),'analysts');assert.equal(few.series.length,3);assert.ok(few.series.every(x=>x.id));
 assert.equal(stackPool(plan,'agents'),null);assert.equal(stackPool(null,'analysts'),null);
 const m=staffModels(plan,'crew_meter','2026-01-01');assert.equal(m.alloc.fmt,'crew');assert.equal(m.pred.series[0].values[0],10*30/60,'crew minutes waiting read as hours');
 const html=staffMarkup(plan,m);assert.match(html,/Float team 0\.1 of 0\.4 meter crews/);assert.match(html,/Float share asked: 30%/);
});

test('paging: fifty rows a page, the page clamped',()=>{
 const rows=Array.from({length:120},(_,i)=>i);let p=paged(rows,3);assert.deepEqual([p.page,p.pages,p.rows.length,p.from,p.to,p.total],[3,3,20,101,120,120]);
 p=paged(rows,9);assert.equal(p.page,3);p=paged(rows,0);assert.equal(p.page,1);assert.equal(p.rows[0],0);p=paged(rows,'x');assert.equal(p.page,1);
 p=paged([],1);assert.deepEqual([p.page,p.pages,p.from,p.to],[1,1,0,0]);
});

test('KPIs from a small rollup, staffing and network',()=>{
 const k=utilityKpis({job:job(),rollup:rollup(),staffing:staffing(3),network:network()});
 assert.deepEqual([k.homes,k.districts,k.completed,k.accounts,k.registers],[300,3,3,410,1100]);
 assert.deepEqual([k.staffing,k.floatShare,k.network,k.events],['shared',.3,'connected',3]);
 assert.deepEqual([k.billed,k.collected,k.receivable,k.overdue,k.lastMonth,k.casesOpened,k.backlog],[300,230,90,10,2,12,3],'receivable and backlog at the last month, whatever the order');
 assert.deepEqual([k.contacts,k.answered,k.abandoned,k.answeredPct],[50,30,10,.75]);assert.deepEqual(k.outages,{electric:50,gas:12.5});
 const html=kpiMarkup(k);assert.match(html,/at the end of Feb/);assert.match(html,/75\.0%/);assert.match(html,/Electric outages/);assert.doesNotMatch(html,/Water outages/);
});

test('day-by-day charts: series, stacks, months and the table twin',()=>{
 const r=rollup(),models=dayCharts(r.daily),by=Object.fromEntries(models.map(m=>[m.id,m]));
 assert.deepEqual(models.map(m=>m.id),['waiting','oldest','crews','contacts','outages','backlog']);
 assert.deepEqual(by.crews.series.map(s=>s.label),['Meter'],'only the crew types the rollup has');assert.equal(by.crews.series[0].values[0],2,'minutes read as hours');
 assert.deepEqual(by.outages.series.map(s=>s.label),['Electric','Gas']);assert.deepEqual(by.outages.tops,[0,0,50,0,12.5]);
 assert.deepEqual(by.backlog.tops,[2,3,4,5,6]);assert.equal(by.backlog.series[0].label,'VEE review');
 assert.deepEqual(monthRows(by.backlog).map(x=>[x.month,...x.values]),[['2026-01',1,2],['2026-02',4,2]],'backlog at each month end');
 assert.deepEqual(monthRows(by.contacts).map(x=>x.values),[[12,4],[18,6]],'calls summed per month');
 assert.deepEqual(monthRows(by.oldest).map(x=>x.values[0]),[1,4],'oldest: the month’s peak day');
 assert.equal(summarize([1,null,3],'end'),3);assert.equal(summarize([],'sum'),null);
 const svg=daySvg(by.backlog);assert.match(svg,/class="ut-area"/);assert.match(svg,/class="ut-hit"[^>]*tabindex="0"/);assert.match(svg,/>F</,'a month tick for February');
 assert.match(daySvg(by.outages),/<rect x=/);assert.match(daySvg(by.contacts),/class="yr-line ut-line"/);
 const card=chartCard(dayModel({id:'x',title:'T <b>',unit:'u',kind:'line',fmt:'int',agg:'sum',series:[{label:'<script>',values:[1,2],color:'#000'},{label:'b',values:[0,1],color:'#111'}]},'2026-01-01',2),'k');
 assert.doesNotMatch(card,/<script>|<b>/,'labels are escaped');assert.match(card,/&lt;script&gt;/);
 assert.match(chartCard(dayModel({id:'z',title:'Z',unit:'u',kind:'line',fmt:'int',agg:'max',series:[{label:'a',values:[0,0]}]},'2026-01-01',2),'z'),/Zero on every day/);
 assert.match(chartCard(dayModel({id:'n',title:'None',unit:'u',kind:'line',fmt:'int',agg:'max',series:[{label:'a',values:undefined}]},'2026-01-01',2),'n'),/No figures/);
 assert.deepEqual(dayCharts({}),[]);
});

test('districts table: run links, home team and float days for the chosen pool, upstream events',()=>{
 const plan=staffing(3,4),net=network(),j=job();plan.districts=j.districts.map(d=>d.id);const rows=districtRows(j,{staffing:plan,network:net});
 assert.deepEqual(rows.map(r=>[r.premises,r.status,r.team.analysts,r.floatDays.analysts,r.floatDaysAny,r.events]),[[140,'done',1,0,1,2],[141,'done',2,1,2,2],[142,'done',3,2,3,2]],'any pool: the days above the home team in at least one pool');
 const base=batchURL('/batches/'+KEY+'/','http://localhost:5175/utility.html'),html=districtsMarkup(rows,{pool:'analysts',base,origin:'http://localhost:5175/utility.html',shared:true,connected:true,manifests:new Map([[RUN(1),{accounts:150,registers:420}],[RUN(2),{error:'Bundle file unavailable (404): manifest.json'}]])});
 assert.match(html,new RegExp(`href="runs.html\\?run=/runs/${RUN(1)}/"`));assert.match(html,/Home analysts/);assert.match(html,/Upstream events/);assert.match(html,/>150</);assert.match(html,/title="Bundle file unavailable/);assert.match(html,/class="ut-pending"/,'a manifest still loading');
 assert.doesNotMatch(html,/private\/path/,'the batch’s local directories are not shown');
 assert.equal(runLink(base,'not-a-key'),null);assert.equal(runLink(base,RUN(1),'https://elsewhere.example/'),`runs.html?run=http://localhost:5175/runs/${RUN(1)}/`);
 const many=districtRows({districts:ids(120).map(id=>({id,homes:10}))});assert.match(districtsMarkup(many,{page:3}),/101–120 of 120 districts · page 3 of 3/);
});

test('an independent batch reads no staffing.json or network.json and shows no allocation or events',async()=>{
 const j=job({staffing:'independent-districts',connected:false}),f=fetchFrom({'job.json':j,'rollup.json':{...rollup(),staffing:'independent-districts',network:'independent'}});
 const b=await loadBatch(batchURL('http://localhost/batches/'+KEY+'/'),{fetchImpl:f});
 assert.deepEqual(f.asked.sort(),['job.json','rollup.json']);assert.equal(b.shared,false);assert.equal(b.connected,false);assert.equal(b.staffing,null);assert.equal(b.network,null);assert.deepEqual(b.problems,{});
 const k=utilityKpis(b);assert.equal(k.staffing,'independent');assert.equal(k.network,'independent');assert.equal(k.events,null);assert.match(kpiMarkup(k),/each district its own team/);
 const rows=districtRows(b.job,b);assert.deepEqual(rows.map(r=>[r.premises,r.floatDaysAny,r.events]),[[null,null,null],[null,null,null],[null,null,null]]);
 const html=districtsMarkup(rows,{base:batchURL('http://localhost/batches/'+KEY+'/')});assert.doesNotMatch(html,/Float days|Upstream events/);assert.match(html,/Open run/);
 assert.equal(statusMarkup(b.job),'','a complete batch has no banner');
});

test('a paused shared batch shows what is done; missing files fail softly, a bad job loudly',async()=>{
 const j=job({done:1}),base=batchURL('http://localhost/batches/'+KEY+'/');
 const b=await loadBatch(base,{fetchImpl:fetchFrom({'job.json':j,'rollup.json':rollup({complete:false}),'network.json':'{broken'})});
 assert.equal(b.staffing,null);assert.equal(b.problems.staffing,MISSING.staffing);assert.equal(b.problems.network,'Damaged batch file: network.json');assert.ok(b.rollup);
 const banner=statusMarkup(j);assert.match(banner,/paused/);assert.match(banner,/1 of 3 districts are finished, 2 more through the first pass/);assert.match(banner,/resume/);
 assert.deepEqual(districtRows(j).map(r=>[r.status,r.runKey!==null]),[['done',true],['first pass',false],['first pass',false]]);
 assert.match(districtsMarkup(districtRows(j),{base}),/<td>district-0002<\/td><td>—<\/td><td>First pass done<\/td>/,'no run link before the final pass');
 const none=await loadBatch(base,{fetchImpl:fetchFrom({'job.json':j})});assert.equal(none.rollup,null);assert.equal(none.problems.rollup,MISSING.rollup);
 assert.equal(utilityKpis(none).billed,null);
 const empty=kpiMarkup(utilityKpis({job:job({done:0}),rollup:{...rollup({complete:false}),accounts:0,registers:0,months:[],daily:{}}}));assert.doesNotMatch(empty,/The year/,'no year tiles before a district finishes');assert.match(empty,/0 of 3/);assert.match(empty,/in finished districts/);
 await assert.rejects(loadBatch(base,{fetchImpl:fetchFrom({})}),/unavailable \(404\): job\.json/);
 await assert.rejects(loadBatch(base,{fetchImpl:fetchFrom({'job.json':{...j,schemaVersion:'utility-batch/9.0'}})}),/Unsupported batch/);
 await assert.rejects(loadBatch(base,{fetchImpl:fetchFrom({'job.json':{...j,key:'d'.repeat(64)}})}),/another batch/);
 await assert.rejects(loadBatch(base,{fetchImpl:async()=>{throw TypeError('offline');}}),/unreachable: job\.json/);
 const wrong=await loadBatch(base,{fetchImpl:fetchFrom({'job.json':j,'rollup.json':rollup(),'staffing.json':{schemaVersion:'utility-staffing/0.1'},'network.json':network()})});assert.match(wrong.problems.staffing,/Unsupported staffing\.json/);assert.ok(wrong.network);
 assert.throws(()=>batchURL('file:///tmp/batch'),/HTTP or HTTPS/);assert.equal(batchURL('/batches/x?y=1#z','http://h/utility.html').href,'http://h/batches/x/');
});

test('upstream events section: lanes per utility, the events table and the layout',()=>{
 const html=eventsMarkup(network(),{start:'2026-01-01',days:365});
 assert.match(html,/3 events on the shared assets/);assert.match(html,/one weather/);assert.match(html,/district-0001 – district-0004/);assert.match(html,/06:52/);assert.match(html,/<td>06:52<\/td><td>8 h<\/td>/);
 assert.equal((html.match(/class="ut-lane"/g)||[]).length,3);assert.match(html,/Transmission main/);assert.match(html,/<td>P1<\/td><td>Treatment plant<\/td><td>Water<\/td><td>6: district-0001 – district-0006<\/td><td>0<\/td>/);
 const quiet=eventsMarkup({...network(),upstream:{}});assert.match(quiet,/No upstream events this year/);
});
