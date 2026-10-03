import test from 'node:test';
import assert from 'node:assert/strict';
import {parseWorkspaceRoute,workspaceHash,categoryOf,substatus,caseStatus,matchesCategory,TRANSACTIONS,CATEGORIES} from '../dist/workspace.js';

test('workspace routes round-trip and unknown transactions fall back to the case list',()=>{
 for(const r of [{tx:'exceptions'},{tx:'vee'},{tx:'billing-query'},{tx:'read-query'},{caseId:'CASE-260715-01450'},{tx:'billing',record:'IN-P-00488-water',screen:'contract'},{tx:'reads',record:'READ-town-1-R-1-2026-07-15'},{tx:'field-order',record:'WO-260715-1'},{tx:'billing',record:'IN-P-1-gas',screen:'document',item:'BD-IN-P-1-gas-202601'},{tx:'billing',record:'IN-P-1-gas',screen:'invoice',item:'INV-CA-P-1-20260106'},{tx:'reads',record:'READ-1',screen:'reads',item:'X'},{tx:'reads',record:'READ-1',screen:'device'}]){
  const back=parseWorkspaceRoute(workspaceHash(r));
  for(const [k,v] of Object.entries(r))assert.equal(back[k],v,`${k} of ${workspaceHash(r)}`);
 }
 assert.deepEqual(parseWorkspaceRoute('#/workspace'),{tx:'exceptions'});
 assert.deepEqual(parseWorkspaceRoute('#/workspace/nonsense'),{tx:'exceptions'});
 assert.equal(parseWorkspaceRoute('#/workspace/billing/X').screen,'orders');
 assert.equal(parseWorkspaceRoute('#/workspace/billing/X/documents').item,undefined); // no item unless one is chosen
 assert.equal(workspaceHash({tx:'reads',record:'R',screen:'reads'}),'#/workspace/reads/R');
 assert.deepEqual(TRANSACTIONS.map(t=>t[2]),['Clarification Case List','Resolve Implausible Meter Readings','Display Billing','Display Meter Reading Results']);
});

test('engine cases map onto clarification categories, statuses and substatuses',()=>{
 assert.equal(categoryOf({queue:'FIELD',type:'HIGH_USAGE'}),'Field Work');
 assert.equal(categoryOf({queue:'BILLING',type:'RATE_CLASS'}),'Billing Errors');
 assert.equal(categoryOf({queue:'BILLING',type:'HIGH_BILL'}),'Billing Outsorts');
 assert.equal(categoryOf({queue:'ESTIMATION',type:'COMM_FAIL'}),'Meter Read Follow-Up');
 assert.equal(categoryOf({queue:'VEE_REVIEW',type:'HIGH_USAGE'}),'MR Implausibles');
 assert.equal(categoryOf({queue:'VEE_REVIEW',type:'HIGH_USAGE',category:'Invoice Outsorts'}),'Invoice Outsorts'); // the engine's own wins
 assert.ok(['Field Work','Billing Errors','Billing Outsorts','Meter Read Follow-Up','MR Implausibles'].every(c=>CATEGORIES.includes(c)));
 assert.equal(caseStatus({resolvedAt:'2026-07-15T00:00:00Z'}),'Completed');
 assert.equal(caseStatus({assignee:'A-3'}),'Assigned');
 assert.equal(caseStatus({assignee:'RPA'}),'Open');
 assert.deepEqual(substatus({queue:'SUPERVISOR',assignee:'S-1'}),['003','Supervisor review']);
 assert.deepEqual(substatus({queue:'VEE_REVIEW'}),['001','Awaiting pickup']);
 assert.ok(matchesCategory({assignee:'you',queue:'FIELD'},'My Assigned Cases'));
 assert.ok(!matchesCategory({assignee:'A-1',queue:'FIELD'},'My Assigned Cases'));
 assert.ok(matchesCategory({owner:'you',assignee:'you',queue:'BILLING'},'My Assigned Cases')); // a case you own
 assert.ok(!matchesCategory({owner:null,assignee:'SUP-01',queue:'SUPERVISOR'},'My Assigned Cases'));
});

test('without an engine the Workspace says why and offers the way to one',async()=>{
 const {engineNotice}=await import('../dist/workspace.js');
 const where={href:'https://utiltiysim.vercel.app/#/workspace'},towns=[{preset:'small_town',label:'Small town'},{preset:'town',label:'Town'}];
 const demo=engineNotice({state:'demo',towns},where);
 assert.match(demo,/demo town drawn in your browser/);assert.match(demo,/href="\/\?town=small_town#\/workspace">Open Small town</);assert.match(demo,/Open Town</);
 assert.match(engineNotice({state:'probing',towns},where),/Connecting to the engine/);
 const down=engineNotice({state:'down',towns},where);assert.match(down,/isn't answering/);assert.match(down,/data-ws="retry"/);assert.doesNotMatch(down,/Open Small town/);
 assert.match(engineNotice({state:'idle',towns:[]},where),/No engine town is open/);
});
