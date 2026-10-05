import test from 'node:test';
import assert from 'node:assert/strict';
import {newMetrics,metricSpecs,fitMetrics,metricReportMarkup} from '../dist/twin-setup.js';
import {wizardDraft} from '../dist/setup-config.js';
import {LocalUtility} from '../dist/local-workspace.js';
const dictionary={kpis:[{id:'invoice_timeliness',label:'Invoice timeliness',unit:'share'}]};
const draft=()=>({name:'Utility twin',metricDraft:newMetrics()});

test('metrics keep historical observations separate from future goals and convert percent inputs',()=>{
 const specs=metricSpecs(draft(),dictionary);
 assert.deepEqual(specs.history.kpis,[{id:'invoice_timeliness',before:.99,after:.94}]);
 assert.deepEqual(specs.target.kpis,[{id:'invoice_timeliness',value:.99}]);
 assert.equal(specs.history.changedOn,'2026-04-01');
 assert.equal(specs.target.changedOn,undefined);
});
test('missing baselines and goals remain optional; invalid shares and dates are refused',()=>{
 const d=draft();d.metricDraft.rows=[{id:'invoice_timeliness',after:94}];
 assert.equal(metricSpecs(d,dictionary).target,null);
 d.metricDraft.rows[0].after=101;assert.throws(()=>metricSpecs(d,dictionary),/between 0 and 100/);
 d.metricDraft=newMetrics();d.metricDraft.targetOn='2026-03-01';assert.throws(()=>metricSpecs(d,dictionary),/after the observed/);
 d.metricDraft=newMetrics();d.metricDraft.rows.push({...d.metricDraft.rows[0]});assert.throws(()=>metricSpecs(d,dictionary),/each KPI once/);
});
test('local fitting retains history and schedules the target settings on the chosen day',async()=>{
 const seen=[];const d=draft();
 const output=await fitMetrics(d,dictionary,{fetchImpl:async(url,init)=>{
  seen.push({url,body:JSON.parse(init.body)});
  return new Response(JSON.stringify({proposal:{settings:{process:{analysts:2}},episodes:seen.length===1?[{from:'2026-04-01',settings:{process:{analysts:1}}}]:[]},kpis:[{id:'invoice_timeliness',target:.99,achieved:.98,status:'close'}],notes:[]}));
 }});
 assert.equal(seen.length,2);assert.ok(seen.every(r=>r.url==='/api/twin/fit'));
 assert.equal(output.proposal.episodes.length,2);
 assert.equal(output.proposal.episodes[1].from,'2026-10-01');
 assert.equal(output.proposal.episodes[1].settings.process.analysts,2);
 assert.deepEqual(output.proposal.metricHistory.observations,d.metricDraft);
 assert.deepEqual(output.proposal.kpis,['invoice_timeliness']);
});
test('fit reports retain units and disclose an unmet target',()=>{
 const html=metricReportMarkup({history:[{label:'<unsafe>',unit:'share',target:.99,achieved:.92,status:'unfitted'}]});
 assert.match(html,/99.00%/);assert.match(html,/92.00%/);assert.match(html,/unfitted/);assert.match(html,/&lt;unsafe&gt;/);
});
test('four-step drafts migrate without losing their selected settings',()=>{
 const old={preset:'village',wizardVersion:3,step:2,settings:{process:{analysts:4}},goals:['vee']};
 const next=wizardDraft(old,{});assert.equal(next.step,3);assert.equal(next.wizardVersion,4);assert.deepEqual(next.settings,old.settings);
 assert.equal(wizardDraft({wizardVersion:4,step:0},{}).step,0);
});
test('a local utility preserves dated edits and decisions when reopened',async()=>{
 const job={jobId:'job',result:{districts:[{runKey:'key'}]}};
 let model={id:'model',preset:'village',settings:{process:{analysts:2}},episodes:[],actions:[],asOf:'2026-06-30'};
 const library={update(id,patch){model={...model,...patch};return model;}};
 let client=new LocalUtility({job,model,library});
 client.addEpisode({from:'2026-07-01',title:'More analysts',settings:{process:{analysts:4}}});
 client.summary=async()=>({warnings:[]});
 await client.act('note','district-0002::CASE-1',null,{text:'Investigated'});
 client=new LocalUtility({job,model,library});
 assert.equal(client.episodes[0].from,'2026-07-01');assert.equal(client.actions[0].caseId,'district-0002::CASE-1');
 assert.equal(client.townRef,'local-run-key');assert.equal(client.asOf,'2026-06-30');
 client.clearEpisodes();client.setSettings(null);client.setSeed(null);
 assert.deepEqual(client.body().episodes,[]);assert.deepEqual(client.body().settings,{});
 assert.deepEqual(client.body().outages,[]);assert.equal(client.body().seed,null);
});
