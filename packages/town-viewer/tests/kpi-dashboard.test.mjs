import test from 'node:test';
import assert from 'node:assert/strict';
import {kpiDashboard,CHART_FAMILIES,commandKpiKey} from '../dist/kpi-dashboard.js';
import {CHARTS} from '../dist/year-page.js';

const catalogue={families:[{id:'reading',title:'Meter reading',text:'Read quality.'},{id:'billing',title:'Billing',text:'Bill quality.'}],thresholds:{},kpis:[
 {id:'reads',title:'Reads',family:'reading',unit:'count',better:'context',definition:'Actual observations.',formula:'count(reads)'},
 {id:'late',title:'Delayed bills',family:'billing',unit:'share',better:'lower',definition:'Bills outside the window.',formula:'late / bills'},
 {id:'blocks',title:'Active blocks',family:'billing',unit:'count',better:'lower',definition:'Unreleased bills.',formula:'count(blocked)'},
 {id:'gaps',title:'Missing input',family:'billing',unit:'count',better:'lower',definition:'An unavailable source.',formula:'count(gaps)'}]};

test('Command Center includes every KPI even when none or only one was chosen',()=>{
 for(const watched of [[],['late']]){
  const html=kpiDashboard(catalogue,{reads:3000,late:.125,blocks:0,gaps:null},{watched,asOf:'2026-06-30'});
  assert.deepEqual([...html.matchAll(/data-kpi="([^"]+)"/g)].map(m=>m[1]),['reads','late','blocks','gaps']);
  assert.equal((html.match(/class="kpi-watched"/g)||[]).length,watched.length);
  assert.match(html,/12.5%/);assert.match(html,/>0<\/strong>/);assert.match(html,/No applicable records/);
  assert.match(html,/Context measure/);assert.doesNotMatch(html,/context is better/);
  assert.match(html,/through 2026-06-30/);assert.match(html,/data-kpi-family="billing" open/);
 }
});

test('every monthly chart has exactly one group and stays next to that group’s measures',()=>{
 assert.deepEqual(Object.keys(CHART_FAMILIES).sort(),CHARTS.map(c=>c.id).sort());
 const html=kpiDashboard(catalogue,{}, {closed:new Set(['billing']),charts:[{id:'blocked',html:'<div>BILL CHART</div>'},{id:'reads',html:'<div>READ CHART</div>'}]});
 assert.match(html,/data-kpi-family="billing" ><summary/);
 assert.ok(html.indexOf('READ CHART')<html.indexOf('data-kpi-family="billing"'));
 assert.ok(html.indexOf('BILL CHART')>html.indexOf('data-kpi-family="billing"'));
 assert.match(html,/Unavailable/);
});

test('loading and failures never substitute zero for a missing result',()=>{
 assert.match(kpiDashboard(catalogue,null,{loading:true}),/Updating the figures/);
 const failed=kpiDashboard(catalogue,null,{error:'Cannot load <source>'});
 assert.match(failed,/Cannot load &lt;source&gt;/);assert.match(failed,/data-kpi-retry/);
 assert.doesNotMatch(failed,/>0<\/strong>/);
});

test('changing a decision without changing the action count still invalidates the KPI results',()=>{
 const client={asOf:'2026-06-30',actions:[{type:'resolve',day:'2026-06-15'}],year:2026,body(extra){return {...extra,actions:this.actions,year:this.year};}};
 const before=commandKpiKey(client);client.actions[0].day='2026-06-20';assert.notEqual(commandKpiKey(client),before);
 const second=commandKpiKey(client);client.year=2027;assert.notEqual(commandKpiKey(client),second);
});
