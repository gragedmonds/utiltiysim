import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {indexGraph,connections,projectGraph} from '../dist/dependency-model.js';
import {relationshipEntries,explanationMarkup} from '../dist/dependency-inspector.js';
const graph=indexGraph(JSON.parse(fs.readFileSync(new URL('../dist/dependency-graph.json',import.meta.url),'utf8')));

test('a collapsed connector exposes every real link with its own explanation',()=>{
 const p=projectGraph(graph,connections(graph,'kpi:bills_on_time'),'kpi:bills_on_time');
 const edge=p.edges.find(e=>e.source==='group:process');
 assert.ok(edge.links.length>1);
 const entries=relationshipEntries([edge,edge],graph);
 assert.equal(entries.length,edge.links.length);
 assert.deepEqual(new Set(entries.map(e=>e.link.source)),new Set(edge.links.map(e=>e.source)));
 assert.ok(entries.every(e=>e.edge===edge&&e.link.explanation&&e.label.includes('Invoices on time')));
});

test('shared card connectors retain different targets and kinds without merging their details',()=>{
 const p=projectGraph(graph,connections(graph,'engine:schedule'),'engine:schedule');
 const entries=relationshipEntries(p.edges.filter(e=>e.source==='engine:schedule'),graph);
 assert.equal(entries.length,graph.outgoing.get('engine:schedule').length);
 assert.equal(entries.find(e=>e.link.target==='engine:reading').link.explanation.basis,'Engine rule');
 assert.match(explanationMarkup(entries.find(e=>e.link.target==='kpi:bills_on_time').link),/account-cycles fully issued/);
 assert.match(explanationMarkup(entries.find(e=>e.link.target==='kpi:days_to_invoice').link),/6 days to issue/);
});

test('unprojected sidebar links work and markup escapes all metadata',()=>{
 const link={source:'engine:schedule',target:'engine:reading',kind:'flow',explanation:{
  basis:'<script>',summary:'A < B & C',formula:'<img src=x onerror=alert(1)>',
  steps:['<unsafe>'],conditions:['"quoted"'],example:'<b>example</b>',references:['<source>']}};
 assert.equal(relationshipEntries([link],graph)[0].edge,null);
 const html=explanationMarkup(link);
 assert.ok(!html.includes('<script>')&&!html.includes('<img'));
 assert.match(html,/A &lt; B &amp; C/);
 assert.match(html,/&lt;source&gt;/);
 assert.match(html,/&lt;b&gt;example&lt;\/b&gt;/);
});

test('older saved graphs show their note without inventing an equation',()=>{
 const html=explanationMarkup({note:'An older <note>'});
 assert.match(html,/An older &lt;note&gt;/);
 assert.match(html,/no calculation detail/);
 assert.ok(!html.includes('dep-link-formula'));
});
