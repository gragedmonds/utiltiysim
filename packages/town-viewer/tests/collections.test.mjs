import test from 'node:test';
import assert from 'node:assert/strict';
import {EngineM2C} from '../dist/m2c.js';
import {parseWorkspaceRoute,workspaceHash,TRANSACTIONS} from '../dist/workspace.js';
import {COLLECTION_LISTS,COLLECTION_TRANSACTIONS,ACTION_LABELS,PERIODS,periodStart,actionBody,actionForm,rowActions,listTable,caseExtras,periodBody,collectionsGroup,isCollectionsRoute} from '../dist/workspace-collections.js';

function memory(){const m=new Map();return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v)};}
function fakeEngine(log){return async(url,opts={})=>{const body=opts.body?JSON.parse(opts.body):null;log.push({url,body});return {ok:true,json:async()=>({asOf:'2026-08-05',rows:[],total:0,echo:body})};};}

test('collections routes round-trip and leave the other workspace routes alone',()=>{
 for(const r of [{tx:'collections',list:'disconnect'},{tx:'collections',list:'overdue'},{tx:'account',record:'CA-P-00124-H1'},{tx:'outages'},{tx:'collector',record:'COL-04',day:'2026-03-09'},{tx:'collector',record:'COL-04'}]){
  const back=parseWorkspaceRoute(workspaceHash(r));
  for(const [k,v] of Object.entries(r))assert.equal(back[k],v,`${k} of ${workspaceHash(r)}`);
  assert.ok(isCollectionsRoute(back));
 }
 assert.equal(parseWorkspaceRoute('#/workspace/collections').list,'disconnect'); // the first list
 assert.equal(parseWorkspaceRoute('#/workspace/collections/nope').list,'disconnect');
 assert.deepEqual(parseWorkspaceRoute('#/workspace/vee'),{tx:'vee'});
 assert.equal(parseWorkspaceRoute('#/workspace/case/CASE-1').caseId,'CASE-1');
 assert.ok(!isCollectionsRoute(parseWorkspaceRoute('#/workspace/statistics')));
 // The Studio's own transactions are unchanged; Collections adds its own group to the transaction picker.
 assert.equal(TRANSACTIONS.length,4);
 assert.deepEqual(COLLECTION_TRANSACTIONS.map(t=>t[0]),['Collections','Collections']);
 assert.deepEqual(COLLECTION_LISTS.map(l=>l[0]),['disconnect','moratorium','rejected','overdue']); // the engine's lists
});

test('run statistics periods start on the right day',()=>{
 assert.equal(periodStart('ytd','2026-08-05','2026-03-31'),null);
 assert.equal(periodStart('month','2026-08-05',null),'2026-08-01');
 assert.equal(periodStart('30d','2026-08-05',null),'2026-07-07'); // 30 days including today
 assert.equal(periodStart('30d','2026-01-12',null),'2026-01-01'); // never before the year
 assert.equal(periodStart('run','2026-08-05','2026-03-31'),'2026-03-31');
 assert.equal(periodStart('run','2026-08-05',null),null); // no action yet: the run is the year
 assert.equal(periodStart('run','2026-03-01','2026-03-31'),null);
 assert.deepEqual(PERIODS.map(p=>p[0]),['ytd','month','30d','run']);
});

test('an action button sends the engine the action and only the fields it takes',()=>{
 const row={accountId:'CA-1',invoiceId:'INV-CA-1-20260105'};
 assert.deepEqual(actionBody('payment_arrangement',row,{instalments:'4',note:' agreed '}),{type:'payment_arrangement',accountId:'CA-1',instalments:4,note:'agreed'});
 assert.deepEqual(actionBody('waive_fee:nsf_fee',row,{}),{type:'waive_fee',invoiceId:'INV-CA-1-20260105',fee:'nsf_fee'});
 assert.deepEqual(actionBody('extend_due',row,{}),{type:'extend_due',invoiceId:'INV-CA-1-20260105',days:14});
 assert.deepEqual(actionBody('dunning_hold',row,{days:'21',note:'Dispute'}),{type:'dunning_hold',accountId:'CA-1',days:21,note:'Dispute'});
 assert.deepEqual(actionBody('disconnect_approve',row,{note:''}),{type:'disconnect_approve',invoiceId:'INV-CA-1-20260105'});
 // A hold and a cancellation need a reason; numbers carry the engine's bounds.
 const need=a=>actionForm(a,row).fields.filter(f=>f.required).map(f=>f.name);
 assert.deepEqual(need('dunning_hold'),['days','note']);assert.deepEqual(need('disconnect_cancel'),['note']);assert.deepEqual(need('budget_billing'),[]);
 const n=actionForm('payment_arrangement',row).fields[0];assert.deepEqual([n.min,n.max,n.value],[2,12,3]);
 for(const a of ['disconnect_approve','disconnect_cancel','payment_arrangement','extend_due','dunning_hold','low_income_referral','budget_billing','waive_fee:late_fee','waive_fee:nsf_fee'])assert.ok(ACTION_LABELS[a],a);
});

test('a row offers exactly the actions the engine takes today',()=>{
 const row={invoiceId:'INV-CA-1-20260105',accountId:'CA-1',actions:['disconnect_approve','waive_fee:late_fee','payment_arrangement']};
 const html=rowActions('disconnect',row);
 assert.match(html,/data-col-act="disconnect_approve"/);assert.doesNotMatch(html,/data-col-act="disconnect_cancel"/); // not offered: no button
 assert.match(html,/<option value="waive_fee:late_fee">Waive late fee/);assert.match(html,/<option value="payment_arrangement">/);
 assert.match(rowActions('disconnect',{...row,actions:[]}),/No action today/);
 const busy=rowActions('disconnect',row,{act:'col:disconnect_approve:INV-CA-1-20260105'});
 assert.match(busy,/disabled>Recording…/);assert.match(busy,/<select[^>]*disabled/);
 const t=listTable('overdue',[{accountId:'CA-<1>',name:'A & B',address:'1 Main',overdue:12.5,invoices:2,oldestDueAt:'2026-03-01',ageDays:40,lastDunning:null,flags:{arrangementId:'ARR-1'},actions:['dunning_hold'],open:true}]);
 assert.match(t,/CA-&lt;1&gt;/);assert.match(t,/A &amp; B/);assert.match(t,/arrangement/);assert.match(t,/Hold dunning/);
 assert.match(listTable('disconnect',[{invoiceId:'I',accountId:'A',state:'paid',open:false,actions:[]}]),/class="ws-col-closed"/);
 assert.match(listTable('rejected',[]),/Nothing in this list/);
});

test('a missed read shows its collector and the related cases; a collections case shows its account',()=>{
 const c={network:{collectorId:'COL-04',mountedOn:'streetlight',mountId:'SL-1',day:'2026-03-09',cases:4,relatedCases:[{caseId:'CASE-2',address:'2 Main',status:'open'},{caseId:'CASE-3',address:'3 Main',status:'resolved',outcome:'estimate'}]}};
 const html=caseExtras(c);
 assert.match(html,/AMI Network/);assert.match(html,/4 cases on collector COL-04/);assert.match(html,/data-col-go="collector" data-id="COL-04" data-day="2026-03-09"/);assert.match(html,/CASE-3/);
 assert.doesNotMatch(caseExtras({network:{...c.network,cases:1,relatedCases:[]}}),/cases on collector/);
 assert.equal(caseExtras({network:null}),'');
 const k=caseExtras({collections:{accountId:'CA-9',overdue:10,outstanding:20,flags:{lowIncome:'referred'},referral:{decideBy:'2026-08-19',outcome:null}}});
 assert.match(k,/Account Collections/);assert.match(k,/by 2026-08-19/);assert.match(k,/data-col-go="account" data-id="CA-9"/);
});

test('statistics for a period show the engine window; the year shows its collections',()=>{
 const sum={window:{since:'2026-07-07',asOf:'2026-08-05',days:30,kpis:{reads:10,actual:9,missing:1,autoAccepted:8,flagged:1,estimated:1,casesOpened:3,casesResolved:2,casesOpenAtStart:4,casesOpen:5,fieldOrders:1,truckRolls:1,avgDaysToRelease:1.5,costs:{labor:1,system:2,cx:3,reads:4,total:10},carry:5},billing:{documents:4,billed:100,invoices:2,collected:90,overdueAtStart:10,overdue:20,receivableAtStart:30,receivable:40,dunning:{DUNNING_REMINDER:2}},collections:{arrangements:1,dunningHolds:0,disconnections:0,lowIncomeReferrals:2,lowIncomeGrants:500,budgetEnrolments:1,feesWaived:0}}};
 const html=periodBody(sum);
 assert.match(html,/2026-07-07 to 2026-08-05 \(30 days\)/);assert.match(html,/Low-income referrals/);assert.match(html,/4 → 5/);
 assert.equal(collectionsGroup({}),'');
 const y=collectionsGroup({dunning:{DISCONNECT_NOTICE:7},collections:{arrangements:{made:1,active:1,broken:0},disconnections:{disconnected:1,reconnected:1,pending:3},lowIncome:{referred:4,grants:1500},budgetPlans:{enrolled:2,masterData:9}}});
 assert.match(y,/Disconnect notices/);assert.match(y,/4 · \$1,500\.00 in grants/);assert.match(y,/2 \(3 notices awaiting a decision\)/);
});

test('the client posts collections requests with the run identity',async()=>{
 const log=[],m=new EngineM2C({api:'/api',townRef:'small_town',townId:'town-1',storage:memory(),fetchImpl:fakeEngine(log)});
 m.setAsOf('2026-08-05');
 await m.collections({list:'overdue',sort:'amount',page:2,pageSize:50});
 await m.collectionsAccount('CA-1');await m.outageFollowup({kind:'last_gasp'});await m.collectorGroups({collector:'COL-04',status:'all'});
 await m.summary('2026-07-07');await m.summary();
 assert.deepEqual(log.map(x=>x.url),['/api/m2c/collections','/api/m2c/collections/account','/api/m2c/outage-followup','/api/m2c/collector-groups','/api/m2c/summary','/api/m2c/summary']);
 assert.deepEqual(log[0].body,{town:'small_town',actions:[],list:'overdue',sort:'amount',page:2,pageSize:50,asOf:'2026-08-05'});
 assert.equal(log[1].body.accountId,'CA-1');assert.equal(log[4].body.since,'2026-07-07');assert.equal(log[5].body.since,undefined);
 assert.equal(m.firstActionDay(),null);
 await m.act('dunning_hold',null,null,{accountId:'CA-1',days:30,note:'Dispute'});
 assert.deepEqual(m.actions[0],{id:'ACT-1',day:'2026-08-05',type:'dunning_hold',accountId:'CA-1',days:30,note:'Dispute'});
 assert.equal(m.firstActionDay(),'2026-08-05');
});
