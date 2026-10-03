import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {EngineM2C} from '../dist/m2c.js';
import {parseRoute,routeHash,upstream,downstream,buildTrace,filterFeed,feedOptions,sequenceMix,dayDelta,localDate,clock,costTotal,EDGES,DOMAINS} from '../dist/process.js';

// Two Activity Sequences as /api/process/graph returns them (process-graph/1.0), nodes deliberately out of order.
// CASE-A: an RPA path, two steps at the same instant. CASE-B: analyst, field and a customer callback branching off.
const node=(id,type,d,day,hour,cost,acct,variantId)=>({id,type,l:type.toLowerCase().replaceAll('_',' '),i:'•',d,cost,day,hour,acctId:acct,variantId,seriesKey:id.split(':')[0],ts:''});
const sys=s=>({labor:0,system:s,cx:0});
const GRAPH={schemaVersion:'process-graph/1.0',month:3,nodes:[
 node('CASE-B:5','SPECIAL_READ','field',68,10,{labor:30,system:.5,cx:0},'CA-P-002','HIGH_USAGE'),
 node('CASE-A:0','COMM_FAIL','ami',60,17.52,sys(.25),'CA-P-001','COMM_FAIL'),
 node('CASE-A:1','EXCEPTION_QUEUED','wm',60,18.05,sys(.1),'CA-P-001','COMM_FAIL'),
 node('CASE-A:2','AUTO_RESOLVED','wm',61,7,sys(2),'CA-P-001','COMM_FAIL'),
 node('CASE-A:3','ESTIMATE_CREATED','vee',61,7,sys(.25),'CA-P-001','COMM_FAIL'),
 node('CASE-A:4','READ_RELEASED','billing',61,7.01,sys(.05),'CA-P-001','COMM_FAIL'),
 node('CASE-B:0','HIGH_USAGE','vee',62,18,sys(.4),'CA-P-002','HIGH_USAGE'),
 node('CASE-B:1','EXCEPTION_QUEUED','wm',62,18.05,sys(.1),'CA-P-002','HIGH_USAGE'),
 node('CASE-B:2','ANALYST_REVIEW','wm',65,10,{labor:32,system:0,cx:0},'CA-P-002','HIGH_USAGE'),
 node('CASE-B:3','FIELD_ORDER','field',65,11,{labor:8,system:.2,cx:0},'CA-P-002','HIGH_USAGE'),
 node('CASE-B:6','CX_CALLBACK','cx',66,9,{labor:0,system:0,cx:15},'CA-P-002','HIGH_USAGE'),
 node('CASE-B:4','TRUCK_ROLL','field',68,9,{labor:120,system:0,cx:5},'CA-P-002','HIGH_USAGE')],
 edges:[['A:0','A:1','triggered'],['A:1','A:2','resulted_in'],['A:2','A:3','resolved_by'],['A:3','A:4','resulted_in'],['B:0','B:1','triggered'],['B:1','B:2','resulted_in'],['B:2','B:3','escalated_to'],['B:3','B:4','required_for'],['B:4','B:5','resolved_by'],['B:2','B:6','resulted_in']]
  .map(([f,t,type])=>({id:`CASE-${f}>${t.split(':')[1]}`,from:'CASE-'+f,to:'CASE-'+t,type}))};
const COSTS={schemaVersion:'m2c-costs/1.0',asOf:'2026-03-31',types:[
 {type:'HIGH_USAGE',label:'High usage',icon:'📈',rpaRule:false,count:1,labor:190,system:1.2,cx:20,carry:7.5,rpa:0,human:1,field:1,activityCost:211.2,perCase:218.7,avgDaysToRelease:6.1},
 {type:'COMM_FAIL',label:'Comm fail',icon:'📡',rpaRule:true,count:3,labor:0,system:7.95,cx:0,carry:3.75,rpa:3,human:0,field:0,activityCost:7.95,perCase:3.9,avgDaysToRelease:.6},
 {type:'ERRATIC',label:'Erratic pattern',icon:'〰️',rpaRule:false,count:0,labor:0,system:0,cx:0,carry:0,rpa:0,human:0,field:0,activityCost:0,perCase:0,avgDaysToRelease:null}]};

test('process routes round-trip; a month is 1–12 and an event needs a month',()=>{
 assert.deepEqual(parseRoute('#/process'),{month:null,eventId:null});
 assert.deepEqual(parseRoute('#/process/3'),{month:3,eventId:null});
 assert.deepEqual(parseRoute('#/process/12/CASE-260302-00322:4'),{month:12,eventId:'CASE-260302-00322:4'});
 for(const bad of ['#/process/0','#/process/13','#/process/CASE-1:0','#/worklists','#/process/3/a/b'])assert.equal(parseRoute(bad),null,bad);
 for(const r of [{month:null,eventId:null},{month:7,eventId:null},{month:3,eventId:'CASE-B:2'}])assert.deepEqual(parseRoute(routeHash(r)),r);
 assert.equal(routeHash({eventId:'CASE-B:2'}),'#/process');
});

test('upstream follows edges backwards, downstream forwards, both excluding the event itself',()=>{
 assert.deepEqual([...upstream(GRAPH,'CASE-B:3')].sort(),['CASE-B:0','CASE-B:1','CASE-B:2']);
 assert.deepEqual([...downstream(GRAPH,'CASE-B:2')].sort(),['CASE-B:3','CASE-B:4','CASE-B:5','CASE-B:6']);
 assert.deepEqual([...downstream(GRAPH,'CASE-B:3')].sort(),['CASE-B:4','CASE-B:5']);
 assert.equal(upstream(GRAPH,'CASE-A:0').size,0);assert.equal(downstream(GRAPH,'CASE-A:4').size,0);assert.equal(upstream(GRAPH,'nope').size,0);
});

test('a trace is the whole Activity Sequence, Initiating Event first, with day badges, edges, delays, tints and totals',()=>{
 const t=buildTrace(GRAPH,'CASE-B:3');
 assert.deepEqual(t.steps.map(s=>s.node.id),['CASE-B:0','CASE-B:1','CASE-B:2','CASE-B:3','CASE-B:6','CASE-B:4','CASE-B:5']);
 assert.deepEqual(t.steps.map(s=>s.dayN),[0,0,3,3,4,6,6]);
 assert.deepEqual(t.steps.map(s=>s.edge),[null,'triggered','resulted_in','escalated_to','resulted_in','required_for','resolved_by']);
 assert.deepEqual(t.steps.map(s=>s.delay),[null,0,3,0,1,3,0]);
 assert.deepEqual(t.steps.map(s=>s.role),['upstream','upstream','upstream','selected',null,'downstream','downstream']);
 assert.equal(t.steps[0].initiating,true);assert.equal(t.steps.filter(s=>s.initiating).length,1);
 // The callback branch sits between the field order and the truck roll, so both connectors name their cause.
 assert.deepEqual(t.steps.map(s=>s.adjacent),[true,true,true,true,false,false,true]);assert.deepEqual([t.steps[4].from,t.steps[5].from],['CASE-B:2','CASE-B:3']);
 assert.deepEqual(t.cost,{labor:190,system:1.2,cx:20,total:211.2});assert.equal(t.elapsedDays,5.7);
 assert.equal(t.seriesKey,'CASE-B');assert.equal(t.variantId,'HIGH_USAGE');assert.equal(t.acctId,'CA-P-002');
 // Steps at the same instant keep the engine's order; the trace is the same whichever event of the sequence is chosen.
 const a=buildTrace(GRAPH,'CASE-A:4');assert.deepEqual(a.steps.map(s=>s.node.id),['CASE-A:0','CASE-A:1','CASE-A:2','CASE-A:3','CASE-A:4']);
 assert.deepEqual(a.steps.map(s=>s.role),['upstream','upstream','upstream','upstream','selected']);
 assert.deepEqual(buildTrace(GRAPH,'CASE-A:0').steps.map(s=>s.node.id),a.steps.map(s=>s.node.id));
 assert.equal(buildTrace(GRAPH,'CASE-Z:0'),null);
});

test('day deltas, local dates and clock times come from the engine day index and hour',()=>{
 assert.equal(dayDelta({day:60},{day:68}),8);assert.equal(localDate(0),'2026-01-01');assert.equal(localDate(60),'2026-03-02');assert.equal(localDate(364),'2026-12-31');
 assert.equal(clock(17.52),'17:31');assert.equal(clock(7),'07:00');assert.equal(clock(18.05),'18:03');assert.equal(clock(0),'00:00');
 assert.equal(costTotal({labor:1,system:.5,cx:2}),3.5);assert.equal(costTotal(undefined),0);
});

test('the event feed is newest first, filtered by domain, event type, sequence type and account, and capped',()=>{
 const all=filterFeed(GRAPH.nodes);assert.equal(all.total,12);assert.deepEqual(all.rows.slice(0,3).map(n=>n.id),['CASE-B:5','CASE-B:4','CASE-B:6']);
 assert.deepEqual(all.rows.slice(-3).map(n=>n.id),['CASE-A:2','CASE-A:1','CASE-A:0']);
 assert.deepEqual(filterFeed(GRAPH.nodes,{domain:'field'}).rows.map(n=>n.id),['CASE-B:5','CASE-B:4','CASE-B:3']);
 assert.deepEqual(filterFeed(GRAPH.nodes,{type:'EXCEPTION_QUEUED'}).rows.map(n=>n.id),['CASE-B:1','CASE-A:1']);
 assert.equal(filterFeed(GRAPH.nodes,{sequence:'COMM_FAIL'}).total,5);
 assert.equal(filterFeed(GRAPH.nodes,{search:' ca-p-001 '}).total,5);assert.equal(filterFeed(GRAPH.nodes,{search:'case-b'}).total,7);
 assert.equal(filterFeed(GRAPH.nodes,{domain:'wm',search:'CA-P-002'}).total,2);
 const capped=filterFeed(GRAPH.nodes,{limit:4});assert.equal(capped.rows.length,4);assert.equal(capped.total,12);
 const many=Array.from({length:400},(_,i)=>node(`CASE-X${i}:0`,'COMM_FAIL','ami',i%365,0,sys(.25),'CA-'+i,'COMM_FAIL'));assert.equal(filterFeed(many).rows.length,150);
 const o=feedOptions(GRAPH.nodes);assert.deepEqual(o.domains.map(d=>d.id),['ami','vee','wm','field','cx','billing']);assert.equal(o.domains.find(d=>d.id==='wm').count,4);assert.equal(o.domains[0].label,'AMI');
 assert.deepEqual(o.types.find(t=>t.type==='EXCEPTION_QUEUED'),{type:'EXCEPTION_QUEUED',label:'exception queued',icon:'•',count:2});
});

test('the sequence mix gives share, cost per case, days to release and the human / RPA / field split',()=>{
 const mix=sequenceMix(COSTS.types,GRAPH.nodes);assert.equal(mix.total,4);
 assert.deepEqual(mix.rows.map(r=>r.type),['COMM_FAIL','HIGH_USAGE','ERRATIC']);
 const [cf,hu,er]=mix.rows;assert.equal(cf.share,.75);assert.equal(cf.rpaRule,true);assert.deepEqual(cf.split,{human:0,rpa:1,field:0});assert.equal(cf.inMonth,1);assert.equal(cf.perCase,3.9);
 assert.deepEqual(hu.split,{human:.5,rpa:0,field:.5});assert.equal(hu.inMonth,1);assert.equal(hu.avgDaysToRelease,6.1);assert.equal(hu.rpaRule,false);
 assert.deepEqual(er.split,{human:0,rpa:0,field:0});assert.equal(er.share,0);assert.equal(er.inMonth,0);assert.equal(er.avgDaysToRelease,null);
 assert.deepEqual(sequenceMix([]),{total:0,rows:[]});
});

test('the graph request carries the month with the run body on its own channel',async()=>{
 const log=[],store=new Map(),m=new EngineM2C({api:'/api',townRef:'ayr',storage:{getItem:k=>store.get(k)??null,setItem:(k,v)=>store.set(k,v)},fetchImpl:async(url,o)=>{log.push({url,body:JSON.parse(o.body)});return {ok:true,json:async()=>({schemaVersion:'process-graph/1.0',nodes:[],edges:[]})};}});
 m.setAsOf('2026-04-30');await m.graph(3);await m.graph(3);await m.graph(4);
 assert.deepEqual(log.map(x=>[x.url,x.body.month,x.body.asOf,x.body.town]),[['/api/process/graph',3,'2026-04-30','ayr'],['/api/process/graph',4,'2026-04-30','ayr']]);
 assert.equal(m.tickets.graph,2);
});

test('the vocabulary covers every edge type and domain, and the page says Activity Sequence and Initiating Event',()=>{
 assert.deepEqual(Object.keys(EDGES),['caused_by','triggered','resulted_in','blocked_by','resolved_by','escalated_to','required_for','compensated_by']);
 assert.deepEqual(Object.keys(DOMAINS),['ami','read','vee','wm','field','cx','billing','invoice','payment','collections']);
 const src=readFileSync(new URL('../dist/process.js',import.meta.url),'utf8'),html=readFileSync(new URL('../dist/studio.html',import.meta.url),'utf8').match(/<section id="process-page"[\s\S]*?<\/section>/)[0];
 for(const text of [src.replaceAll('variantId',''),html])assert.doesNotMatch(text,/variant|root.cause/i);
 assert.match(src,/Initiating Event/);assert.match(html,/Activity sequences/);
});
