import test from 'node:test';
import assert from 'node:assert/strict';
import {serviceOrderCoverage} from '../dist/service-order-coverage.js';
import {glossaryMarkup} from '../dist/glossary.js';
import {kpiDashboard} from '../dist/kpi-dashboard.js';

const catalogue={families:[],kpis:[],serviceOrders:{source:'Reference <photo>',statuses:{covered:'Core work covered',partial:'Partial match',not_modelled:'Not modelled'},groups:['Meter reads','Emergency'],engineTypes:{meter_investigation:'Meter investigation'},manualNote:'Create from a read.',timingNote:'Travel is separate.',orders:[
 {code:'216',title:'Meter Reread',group:'Meter reads',status:'covered',engineTypes:['meter_investigation'],manualActivities:['Special meter read'],behaviour:'Take & confirm reads.',gap:''},
 {code:'111',title:'Sewer Odor Complaint',group:'Emergency',status:'not_modelled',engineTypes:[],manualActivities:[],behaviour:'No wastewater network.',gap:'Needs sewer assets.'}
]}};

test('coverage distinguishes actual work, manual activities and gaps without fabricated totals',()=>{
 const html=serviceOrderCoverage(catalogue);
 assert.match(html,/2 of 2 reference types/);assert.match(html,/Reference &lt;photo&gt;/);assert.match(html,/Take &amp; confirm/);
 assert.match(html,/Related annual work<\/dt><dd>Meter investigation/);assert.match(html,/Related manual activity<\/dt><dd>Special meter read/);
 assert.match(html,/Not modelled/);assert.match(html,/Still missing:<\/b> Needs sewer assets/);
 assert.match(html,/not separate selectable order types or extra work counts/);
 assert.equal((html.match(/class="service-order-group" /g)||[]).length,2);
 assert.doesNotMatch(html,/class="service-order-group" open/);
 assert.equal(serviceOrderCoverage({}), '', 'older saved catalogues stay compatible');
});

test('search by code or engine activity opens only matching groups and shows no false empty state',()=>{
 const html=glossaryMarkup(catalogue,{filter:'216'});
 assert.match(html,/1 of 2 reference types/);assert.match(html,/class="service-order-group" open/);
 assert.match(html,/Meter Reread/);assert.doesNotMatch(html,/Sewer Odor Complaint|Nothing matches/);
 assert.match(serviceOrderCoverage(catalogue,'meter investigation'),/Meter Reread/);
 assert.match(serviceOrderCoverage(catalogue,'special meter read'),/Meter Reread/);
 assert.match(glossaryMarkup(catalogue,{filter:'never matches'}),/Nothing matches/);
});

test('the field KPI group links to coverage while preserving the simulation context',()=>{
 const cat={...catalogue,families:[{id:'field',title:'Field work',text:'Crews and visits'}]};
 const html=kpiDashboard(cat,{}, {href:'./glossary.html?simulation=local-test&town=local-test',charts:[{id:'fieldDone',html:'FIELD CHART'}]});
 assert.match(html,/href="\.\/glossary.html\?simulation=local-test&amp;town=local-test#service-orders"/);
 assert.match(html,/FIELD CHART/);
});
