import test from 'node:test';
import assert from 'node:assert/strict';
import {actionableFrom,canWork,workHint,refusal,overdueLabel,isAscending,newestPages,newestFirst,mergeRows,registerDrop,releasedValue,expectedOf,readSeries,historyChart,causeOf,matchesCategory} from '../dist/workspace.js';
import {EngineM2C,cycleWithOutages,mainsAmiPremises} from '../dist/m2c.js';
import {incidentImpact,nextJob} from '../dist/engine-operations.js';
import {invoiceDetails} from '../dist/customer.js';
import {billingMarkup} from '../dist/customer-view.js';

function memory(){const m=new Map();return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v)};}

test('a case raised after 09:00 on the run date is worked from the next day; the engine field wins',()=>{
 const late={caseId:'C1',createdAt:'2026-06-15T22:00:00Z'},early={caseId:'C2',createdAt:'2026-06-15T12:30:00Z'}; // 18:00 and 08:30 in Toronto
 assert.equal(actionableFrom(late),'2026-06-16');assert.equal(actionableFrom(early),'2026-06-15');
 assert.equal(canWork(late,'2026-06-15'),false);assert.equal(canWork(late,'2026-06-16'),true);assert.equal(canWork(early,'2026-06-15'),true);
 assert.equal(workHint(late,'2026-06-15'),'Raised today at 18:00: work it from 2026-06-16.');assert.equal(workHint(late,'2026-06-16'),'');
 assert.equal(actionableFrom({...late,actionableFrom:'2026-06-17'}),'2026-06-17');assert.equal(workHint({...late,actionableFrom:'2026-06-17'},'2026-06-16'),'Work it from 2026-06-17.');
 assert.equal(actionableFrom({...late,resolvedAt:'2026-06-16T13:00:00Z'}),null);assert.equal(canWork({caseId:'X'},'2026-06-15'),true); // nothing to go on: allowed
 assert.equal(overdueLabel(0),'New');assert.equal(overdueLabel(1),'1 Day');assert.equal(overdueLabel(3),'3 Days');
});

test('a refusal reads as the engine wrote it, whatever the detail shape',()=>{
 assert.equal(refusal({message:'Engine 422: x',detail:'action 3 (accept): case C1 is already resolved'}),'action 3 (accept): case C1 is already resolved');
 assert.equal(refusal({message:'Engine 422',detail:{message:'Release needs a planner group',fieldErrors:{}}}),'Release needs a planner group');
 assert.equal(refusal({message:'Engine 422',detail:[{msg:'value is not a number'}]}),'value is not a number');
 assert.equal(refusal(Error('Engine 500: boom')),'boom');
});

test('Completed and All read newest first from whichever end the engine sorts "created"',()=>{
 const asc=[{createdAt:'2026-01-02T00:00:00Z'},{createdAt:'2026-01-05T00:00:00Z'}],tail=[{createdAt:'2026-06-01T00:00:00Z'},{createdAt:'2026-06-02T00:00:00Z'}];
 assert.equal(isAscending(asc,tail),true);assert.equal(isAscending([...tail].reverse(),[...asc].reverse()),false);
 assert.deepEqual(newestPages(530,200,true),[3,2,1]);assert.deepEqual(newestPages(530,200,false),[1,2,3]);assert.deepEqual(newestPages(0,200,true),[1]);
 const rows=newestFirst([{caseId:'A',createdAt:'2026-06-01T22:00:00Z'},{caseId:'C',createdAt:'2026-06-02T22:00:00Z'},{caseId:'B',createdAt:'2026-06-02T22:00:00Z'}]);
 assert.deepEqual(rows.map(r=>r.caseId),['C','B','A']);assert.deepEqual(mergeRows(rows,[{caseId:'B'},{caseId:'D'}]).map(r=>r.caseId),['C','B','A','D']);
 assert.equal(matchesCategory({assignee:'SUP-01',released:{by:'you'}},'My Assigned Cases'),true);assert.equal(matchesCategory({assignee:'SUP-01'},'My Assigned Cases'),false);
});

test('decision data: register drop, expected, released value, cause and the read history series',()=>{
 // engine fields first
 assert.deepEqual(registerDrop({registerWentBackwards:true,registerDelta:-21958.167}),{by:21958.167});assert.equal(registerDrop({registerWentBackwards:false,consumption:-5}),null);
 // fallbacks: the read's regression flag (its consumption is rollover-sized), or a negative row consumption
 assert.deepEqual(registerDrop({read:{registerRegression:true,registerValue:49.5,previousRegisterValue:22007.5,consumption:977042}}),{by:21958});
 assert.deepEqual(registerDrop({consumption:-12,observed:8,previous:20}),{by:12});assert.equal(registerDrop({consumption:4}),null);
 assert.deepEqual(expectedOf({expected:0.432}),{consumption:0.432,registerValue:null});assert.deepEqual(expectedOf({expected:{consumption:3,registerValue:120}}),{consumption:3,registerValue:120});assert.equal(expectedOf({decision:{expectedConsumption:7}}).consumption,7);
 assert.deepEqual(releasedValue({released:{registerValue:10,consumption:2,method:'estimated',by:'RPA',at:'2026-06-16T13:00:00Z'}}).method,'estimated');
 assert.equal(releasedValue({resolvedAt:'x',outcome:'estimate',assignee:'you',read:{revisions:[{readType:'adjusted',registerValue:11,consumption:3,at:'y'}]}}).method,'corrected');
 assert.equal(releasedValue({resolvedAt:'x',outcome:'accept',assignee:'you',read:{registerValue:5,consumption:1}}).by,'you');assert.equal(releasedValue({resolvedAt:null}),null);
 assert.equal(causeOf({cause:'Collector outage'}),'Collector outage');assert.equal(causeOf({read:{reasonCode:'SIM_TELEMETRY_FAILURE'}}),'Telemetry failure');assert.equal(causeOf({cause:{label:'No access'}}),'No access');assert.equal(causeOf({}),'');
 const fromEngine=readSeries({readHistory:Array.from({length:15},(_,i)=>({date:`2026-${String(i%12+1).padStart(2,'0')}-05`,registerValue:i,consumption:i?1:null,readType:i===3?'estimated':'actual',estimated:i===3,veeStatus:i===4?'review':'accepted'}))});
 assert.equal(fromEngine.length,13);assert.equal(fromEngine.find(x=>x.kind==='est')?.registerValue,3);assert.equal(fromEngine.find(x=>x.kind==='flag')?.registerValue,4);
 const legacy=readSeries({history:[{month:0,readAt:'2025-12-04T14:05:00Z',released:100,status:'released'},{month:1,readAt:'2026-01-07T14:05:00Z',observed:130,consumption:30,expected:32,released:130,status:'released'},{month:2,readAt:'2026-02-05T14:05:00Z',observed:null,consumption:null,expected:28,released:158,status:'estimated',caseId:'C'},{month:3,readAt:'2026-03-05T14:05:00Z',observed:null,consumption:null,expected:20,released:null,status:'pending',caseId:'D'}]});
 assert.deepEqual(legacy.map(x=>[x.kind,x.consumption]),[['ok',30],['est',28],['miss',null]]);
 const svg=historyChart(legacy,'m3');assert.match(svg,/<svg class="wl-chart ws-chart"/);assert.equal((svg.match(/<rect/g)||[]).length,3);assert.match(svg,/no read/);assert.equal(historyChart([]),'');
});

test('an action the engine skips with a warning is a refusal; one action records at a time',async()=>{
 let release;const log=[];const fetchImpl=async(url,opts)=>{const body=JSON.parse(opts.body),a=body.actions.at(-1);log.push(a?.type);if(a?.type==='slow')await new Promise(r=>release=r);
  return {ok:true,json:async()=>({asOf:body.asOf,warnings:a?.type==='accept'?[`${a.id}: case C1 is not open on ${a.day}`]:[]})};};
 const m=new EngineM2C({api:'/api',townRef:'t',townId:'t-1',storage:memory(),fetchImpl});m.setAsOf('2026-06-15');
 await assert.rejects(m.act('accept','C1'),e=>e.status===422&&e.message==='case C1 is not open on 2026-06-15');assert.equal(m.actions.length,0);
 const first=m.act('slow','C2');await new Promise(r=>setTimeout(r,5));assert.ok(m.pending);
 await assert.rejects(m.act('estimate','C3'),/still recording/);release();await first;assert.equal(m.pending,null);assert.deepEqual(m.actions.map(a=>a.type),['slow']);
 assert.equal(m.lockedBefore('2026-06-14'),'2026-06-15');assert.equal(m.lockedBefore('2026-06-15'),null);assert.equal(m.lockedBefore(null),null);
});

test("the map's meter-to-cash card counts AMI meters dark at the collection hour as missed",()=>{
 const town={meters:[{id:'M1e',technology:'AMI'},{id:'M2e',technology:'AMR'},{id:'M2w',technology:'AMI'},{id:'M3e',technology:'AMI'}],servicePoints:[{premiseId:'P1',commodity:'electric',meterId:'M1e'},{premiseId:'P2',commodity:'electric',meterId:'M2e'},{premiseId:'P2',commodity:'water',meterId:'M2w'},{premiseId:'P3',commodity:'electric',meterId:'M3e'}]};
 const mains=mainsAmiPremises(town);assert.deepEqual([...mains].sort(),['P1','P3']);
 const cycle={ami:{at:7200,read:['P1','P2','P3','P4'],missed:['P9']},vee:{at:64800,flagged:[]}};
 const out=cycleWithOutages(cycle,[{utility:'electric',start:6000,end:7563,premiseIds:['P1','P2']},{utility:'ami',start:7000,end:null,premiseIds:['P4']},{utility:'electric',start:8000,end:9000,premiseIds:['P3']}],mains);
 assert.deepEqual(out.ami.read,['P2','P3']);assert.deepEqual(out.ami.missed,['P9','P1','P4']);assert.equal(out.ami.dark,2);assert.equal(out.vee,cycle.vee); // P2's water meter runs on a battery
 assert.equal(cycleWithOutages(out,[{utility:'electric',start:6000,end:7563,premiseIds:['P1','P2']}],mains),out); // idempotent
 assert.equal(cycleWithOutages(cycle,[],mains),cycle);assert.equal(cycleWithOutages(null,[{utility:'ami',start:0,premiseIds:['P1']}],mains),null);
});

test('incident cards and an empty job list say something sensible',()=>{
 assert.equal(incidentImpact({utility:'electric',unsupplied:{atFault:120,afterIsolation:14}}),'120 out at the fault · 14 after isolation');
 assert.equal(incidentImpact({utility:'water',unsupplied:{atFault:0,afterIsolation:9},isolatedAt:5000,restoredAt:Infinity},100),'Leaking · customers keep water until a crew isolates it (then 9 customers lose supply)');
 assert.equal(incidentImpact({utility:'water',unsupplied:{atFault:0,afterIsolation:9},isolatedAt:5000,restoredAt:Infinity},6000),'Isolated · 9 customers without water until the repair');
 assert.equal(incidentImpact({utility:'gas',unsupplied:{atFault:0,afterIsolation:1},isolatedAt:5000,restoredAt:9000},9500),'1 customer was without gas while it was isolated');
 assert.equal(incidentImpact({utility:'ami',kind:'collector_outage',premiseIds:['a','b'],unsupplied:{atFault:0,afterIsolation:0}}),'2 customers: AMI meters cannot report; service continues');
 assert.doesNotMatch(incidentImpact({utility:'water',unsupplied:{atFault:0,afterIsolation:0}},0),/0 out/);
 assert.equal(nextJob([{id:'a',startAt:30000},{id:'b',startAt:20000},{id:'c',startAt:100}],1000).id,'b');assert.equal(nextJob([{startAt:10}],1000),null);
});

test('invoices on the billing tab carry their period, payments, dunning and an estimate mark',()=>{
 const docs=[{id:'BD-e',periodStart:'2026-05-04T13:00:00Z',periodEnd:'2026-06-04T13:00:00Z',estimated:false},{id:'BD-w',periodStart:'2026-05-02T13:00:00Z',periodEnd:'2026-06-03T13:00:00Z',estimated:true}];
 const [v]=invoiceDetails([{id:'INV-1',billingDocumentIds:['BD-e','BD-w','BD-gone'],totalAmount:80,currency:'CAD',issuedAt:'2026-06-05',dueAt:'2026-06-25',payments:[{at:'2026-06-20T10:00:00Z',amount:80,status:'received'}],dunning:[{at:'2026-05-27T11:12:00Z',type:'PAYMENT_REJECTED',label:'Payment rejected'},{at:'2026-06-01T04:00:00Z',type:'DUNNING_REMINDER',label:'Reminder'}]}],docs);
 assert.equal(v.periodStart,'2026-05-02T13:00:00Z');assert.equal(v.periodEnd,'2026-06-04T13:00:00Z');assert.equal(v.estimated,true);
 assert.equal(invoiceDetails([{id:'X',billingDocumentIds:[]}],docs)[0].estimated,null); // unknown stays unknown
 const html=billingMarkup({account:{currency:'CAD',balance:0},bills:docs,invoices:[v]},[]);
 assert.match(html,/Period<\/span><strong>2026-05-02 to 2026-06-04/);assert.match(html,/2026-05-27<\/time> Payment rejected/);assert.match(html,/2026-06-01<\/time> Reminder/);assert.match(html,/2026-06-20<\/time> \$80\.00 · received/);
 assert.equal((html.match(/class="estimate-tag"/g)||[]).length,2);assert.doesNotMatch(html,/Period<\/span><strong>Not supplied/);
});
