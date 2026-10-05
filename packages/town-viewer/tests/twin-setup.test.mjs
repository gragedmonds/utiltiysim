import test from 'node:test';
import assert from 'node:assert/strict';
import {newMetrics,metricSpecs,fitMetrics,metricReportMarkup,metricsMarkup,metricOptions,bindMetrics} from '../dist/twin-setup.js';
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


test('expanded picker groups invoice and reading metrics and explains comparison counts',()=>{
 const data={families:[{id:'billing',title:'Billing'},{id:'reading',title:'Meter reading'}],kpis:[
  {id:'estimated_bill_share',label:'Estimated invoices',family:'billing',unit:'share',fitMode:'adjustable'},
  {id:'active_services',label:'Active services',family:'billing',unit:'count',fitMode:'comparison',fitNote:'Counts scale to your utility.'},
  {id:'late_read_share',label:'Reads taken late',family:'reading',unit:'share',fitMode:'comparison'},
 ]};
 const d=draft();d.metricDraft.rows=[{id:'active_services',before:25000,after:30000,target:31000}];
 const html=metricsMarkup(d,data);
 assert.match(html,/<optgroup label="Billing">/);assert.match(html,/<optgroup label="Meter reading">/);
 assert.match(html,/Estimated invoices/);assert.match(html,/Active services \(comparison only\)/);
 assert.match(html,/Count across your utility/);assert.match(html,/Counts scale to your utility/);
 assert.equal(metricSpecs(d,data).history.kpis[0].after,30000);
 assert.equal(metricSpecs(d,data).target.kpis[0].value,31000);
 assert.match(metricOptions(data,'active_services',['active_services','estimated_bill_share']),/value="estimated_bill_share"[^>]*disabled/);
 const report=metricReportMarkup({history:[{label:'Services',unit:'count',target:30000,achieved:29800,status:'comparison',note:'Comparison only: no fitted lever.'}]});
 assert.match(report,/Comparison only: no fitted lever/);
});


test('comparison-only goals retain their report without adding a recovery episode',async()=>{
 const d=draft();d.metricDraft.rows=[{id:'active_services',after:500,target:600}];
 const data={kpis:[{id:'active_services',label:'Active services',unit:'count',fitMode:'comparison'}]};
 const output=await fitMetrics(d,data,{fetchImpl:async()=>new Response(JSON.stringify({
  proposal:{settings:{process:{analysts:2}},episodes:[]},
  kpis:[{id:'active_services',status:'comparison',target:600,achieved:500}],notes:[],
 }))});
 assert.deepEqual(output.proposal.episodes,[]);
 assert.equal(output.report.target[0].status,'comparison');
 assert.deepEqual(output.proposal.kpis,['active_services']);
});


test('typing a value then adding a row preserves it before a blur event',()=>{
 const d=draft();d.metricReport={history:[]};let add,rendered;
 const input={dataset:{rowField:'after'},value:'88',closest:()=>({dataset:{metricRow:'0'}})};
 const root={querySelectorAll:selector=>selector==='[data-row-field]'?[input]:[],
  querySelector:()=>({addEventListener:(_,handler)=>{add=handler;}})};
 const data={kpis:[...dictionary.kpis,{id:'estimated_bill_share',unit:'share'}]};
 bindMetrics(root,d,{dictionary:data,save(){},render(){rendered=structuredClone(d.metricDraft);}});
 input.oninput();add();
 assert.equal(rendered.rows[0].after,'88');
 assert.equal(rendered.rows[1].id,'estimated_bill_share');
 assert.equal(d.metricReport,null);
});
