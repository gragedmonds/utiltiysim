import test from 'node:test';
import assert from 'node:assert/strict';
import {EngineM2C,noticesFor} from '../dist/m2c.js';
import {categoryOf,CATEGORIES,matchesCategory,readNote,outcomeText,outcomeFromForm,relatedLabel,coverable,deviceRows,byLabel} from '../dist/workspace.js';

function memory(){const m=new Map();return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v)};}

test('escalations are their own category: any case in the supervisor queue, whatever its type',()=>{
 assert.ok(CATEGORIES.includes('Escalations'));
 assert.equal(categoryOf({queue:'SUPERVISOR',type:'HIGH_USAGE'}),'Escalations');
 assert.equal(categoryOf({queue:'SUPERVISOR',type:'COMM_FAIL'}),'Escalations');
 assert.equal(categoryOf({queue:'SUPERVISOR',type:'HIGH_BILL',category:'Escalations'}),'Escalations');
 assert.equal(categoryOf({queue:'VEE_REVIEW',type:'HIGH_USAGE'}),'MR Implausibles');
 assert.ok(matchesCategory({queue:'SUPERVISOR',type:'ERRATIC'},'Escalations'));
 assert.ok(!matchesCategory({queue:'SUPERVISOR',type:'ERRATIC'},'MR Implausibles'));
});

test('a read missed in an outage says so, with the outage window',()=>{
 const cause={code:'power_outage',label:'Power outage',reasonCode:'SIM_POWER_OUTAGE',outageStart:'2026-03-03T05:00:00Z',outageEnd:'2026-03-03T09:00:00Z',reason:'No read: the meter lost power…'};
 assert.equal(readNote({reasonCode:'SIM_POWER_OUTAGE',cause}),'Missed: power outage 00:00–04:00 (AMI last gasp)');
 assert.equal(readNote({cause:{code:'collector_outage',label:'AMI collector outage',outageStart:'2026-03-03T05:00:00Z',outageEnd:'2026-03-04T13:00:00Z'}}),'Missed: ami collector outage 00:00–2026-03-04 08:00');
 assert.equal(readNote({cause:{code:'no_access',label:'No access'}}),'Missed: no access');
 assert.equal(readNote({reasonCode:'SIM_POWER_OUTAGE'}),'Power outage at the AMI collection','without a cause, the reason code');
});

test('structured field outcomes read as one line and the form builds them',()=>{
 assert.equal(outcomeText({kind:'read_taken',value:4182.5,date:'2026-07-14'}),'Read taken: 4,182.5 on 2026-07-14');
 assert.equal(outcomeText({kind:'no_access',text:'No access'}),'No access','the engine\'s text wins');
 assert.equal(outcomeText({kind:'meter_exchanged',deviceId:'SN-1',installDate:'2026-07-14',initialRead:0}),'Meter exchanged: new device SN-1 installed 2026-07-14, initial read 0');
 assert.equal(outcomeText('Seals intact'),'Seals intact','an older free-text outcome');
 const ctx={start:'2026-07-10',asOf:'2026-07-14'};
 assert.deepEqual(outcomeFromForm({kind:'read_taken',value:'4182.5',date:'2026-07-14'},ctx),{outcome:{kind:'read_taken',value:4182.5,date:'2026-07-14'}});
 assert.match(outcomeFromForm({kind:'read_taken',value:'',date:'2026-07-14'},ctx).error,/read taken/);
 assert.match(outcomeFromForm({kind:'read_taken',value:'3',date:'2026-07-01'},ctx).error,/2026-07-10 to 2026-07-14/);
 assert.deepEqual(outcomeFromForm({kind:'meter_exchanged',deviceId:' SN-9 ',installDate:'2026-07-12',initialRead:'0',removalRead:''},ctx),{outcome:{kind:'meter_exchanged',deviceId:'SN-9',installDate:'2026-07-12',initialRead:0}});
 assert.equal(outcomeFromForm({kind:'meter_exchanged',deviceId:'SN-9',installDate:'2026-07-12',initialRead:'0',removalRead:'812.25'},ctx).outcome.removalRead,812.25);
 assert.match(outcomeFromForm({kind:'meter_exchanged',deviceId:'',installDate:'2026-07-12',initialRead:'0'},ctx).error,/device id/);
 assert.match(outcomeFromForm({kind:'defect_found',text:'  '},ctx).error,/defect/);
 assert.deepEqual(outcomeFromForm({kind:'no_access'},ctx),{outcome:{kind:'no_access'}});
 assert.match(outcomeFromForm({kind:'whatever'},ctx).error,/Choose/);
 assert.equal(byLabel('FIELD-2'),'Field crew FIELD-2');assert.equal(byLabel('you'),'You');
});

test('related cases at a premise: a count, and the ones one visit can cover',()=>{
 assert.equal(relatedLabel(2),'2 related cases');assert.equal(relatedLabel(1),'1 related case');assert.equal(relatedLabel(0),'');
 const c={relatedCases:[{caseId:'CASE-A',coverable:true},{caseId:'CASE-B',coverable:false},{caseId:'CASE-C',coverable:true}]};
 assert.deepEqual(coverable(c).map(x=>x.caseId),['CASE-A','CASE-C']);assert.deepEqual(coverable({}),[]);
});

test('the device history lists the current device first, with install, removal and who replaced it',()=>{
 const rows=deviceRows({devices:[{deviceId:'M-1',installedAt:null,removedAt:'2026-07-20T13:00:00Z',initialReads:null,removalReads:{'R-1':35700.5},by:null,current:false},{deviceId:'SN-9',installedAt:'2026-07-20T13:00:00Z',removedAt:null,initialReads:{'R-1':0},by:'FIELD-1',orderId:'WO-260720-0001',current:true}]});
 assert.deepEqual(rows.map(r=>r.deviceId),['SN-9','M-1']);
 assert.equal(rows[0].current,true);assert.equal(rows[0].installed,'2026-07-20');assert.equal(rows[0].initial,'0');assert.equal(rows[0].by,'Field crew FIELD-1');assert.equal(rows[0].ref,'WO-260720-0001');
 assert.equal(rows[1].installed,'Before 2026');assert.equal(rows[1].removed,'2026-07-20');assert.equal(rows[1].removal,'35,700.5');
});

test('a recorded action keeps the engine\'s notices and tells listeners (the map refreshes its day)',async()=>{
 assert.deepEqual(noticesFor(['ACT-2 (notice): CASE-1 was completed while field service order WO-1 is still Dispatched; the order goes on','ACT-1 (notice): other','ACT-2: refused'],'ACT-2'),['CASE-1 was completed while field service order WO-1 is still Dispatched; the order goes on']);
 const heard=[],m=new EngineM2C({townRef:'ayr',townId:'t',storage:memory(),fetchImpl:async(url,opts)=>{const body=JSON.parse(opts.body);return {ok:true,json:async()=>({warnings:body.actions.length?[`ACT-${body.actions.length} (notice): CASE-9 was completed while field service order WO-9 is still En route; the order goes on`]:[]})};}});
 m.onAct=a=>heard.push(a.type);m.setAsOf('2026-07-14');
 await m.act('estimate','CASE-9');
 assert.equal(m.actions.length,1,'a notice is not a refusal');assert.deepEqual(heard,['estimate']);
 assert.match(m.notices[0],/still En route/);
});
