import test from 'node:test';import assert from 'node:assert/strict';
import {kpisForGoals,formatKpi,kpiChips,matchKpis,watchLine,kpiStrip,unitLabel,withKpiTitle} from '../dist/kpis.js';
import {glossaryMarkup,settingIndex} from '../dist/glossary.js';
const catalogue={schemaVersion:'m2c-kpis/1.0',families:[{id:'billing',title:'Billing',text:'Bills.'},{id:'cash',title:'Cash and collections',text:'Money in.'}],
 thresholds:{'kpi.on_time_bill_days':{title:'On time bill days',unit:'days',value:3,description:'A bill is on time within this many days.',group:'KPI definitions'}},
 kpis:[{id:'bills_on_time',title:'Bills on time',family:'billing',unit:'share',better:'higher',goals:['billing'],definition:'Share of bills released within the window.',formula:'on time ÷ bills',thresholds:['kpi.on_time_bill_days'],settings:[{path:'process.analysts',direction:-1}],scenarios:['half_staff_billing'],related:['days_to_pay'],where:['Workspace · Run statistics'],twin:false},
  {id:'days_to_pay',title:'Days to pay',family:'cash',unit:'days',better:'lower',goals:['collections'],definition:'Average days from issue to payment.',formula:'mean(paid − issued)',thresholds:[],settings:[],scenarios:[],related:['bills_on_time'],where:['Worklists · tiles'],twin:true}]};
test('goals pick figures; everything or nothing picks all',()=>{assert.deepEqual(kpisForGoals(catalogue,['billing']).map(k=>k.id),['bills_on_time']);assert.equal(kpisForGoals(catalogue,['everything']).length,2);assert.equal(kpisForGoals(catalogue,[]).length,2);assert.deepEqual(kpisForGoals(catalogue,['contact']),[]);});
test('figures are shown in their units',()=>{assert.equal(formatKpi(0.9938,'share'),'99.4%');assert.equal(formatKpi(17.77,'days'),'17.8 days');assert.equal(formatKpi(1012.55,'per_1000_accounts_year'),'1013 /1,000 a year');assert.equal(formatKpi(2.96,'per_1000_accounts'),'3.0 /1,000');assert.equal(formatKpi(17.97,'currency_per_account'),'$17.97 /account');assert.equal(formatKpi(null,'share'),'—');assert.equal(unitLabel('per_1000_accounts_year'),'per 1,000 accounts a year');});
test('chips tick the chosen figures and carry the definition',()=>{const html=kpiChips(catalogue.kpis,['days_to_pay']);assert.equal((html.match(/kpi-chip/g)||[]).length,2);assert.match(html,/value="days_to_pay" checked/);assert.match(html,/is-on"[^>]*title="Average days/);assert.doesNotMatch(html,/value="bills_on_time" checked/);});
test('autofill matches the words being typed, not the whole message',()=>{assert.deepEqual(matchKpis(catalogue,'we care about bills on time').map(k=>k.id),['bills_on_time']);assert.deepEqual(matchKpis(catalogue,'Our backlog is fine. days to').map(k=>k.id),['days_to_pay']);assert.deepEqual(matchKpis(catalogue,'hi'),[]);assert.deepEqual(matchKpis(catalogue,'the weather in Ontario'),[]);assert.deepEqual(matchKpis(null,'bills on time'),[]);});
test('the strip and the watch line name the chosen figures with their values and windows',()=>{assert.equal(watchLine(catalogue,['bills_on_time','days_to_pay']),'Watching: Bills on time · Days to pay');assert.equal(watchLine(catalogue,[]),'');
 const html=kpiStrip(catalogue,['bills_on_time','days_to_pay'],{bills_on_time:0.9938,days_to_pay:null},{thresholds:{'kpi.on_time_bill_days':3},href:'./glossary.html'});
 assert.match(html,/99\.4%/);assert.match(html,/—/);assert.match(html,/on time bill days 3/);assert.match(html,/higher is better/);assert.match(html,/Glossary/);assert.equal(kpiStrip(catalogue,[],{}),'');assert.match(kpiStrip(catalogue,['days_to_pay'],null),/…/);});
test('the glossary renders every family, the windows, the influences and a simulation’s own figures',()=>{
 const settings=settingIndex({properties:{process:{title:'Process & costs',properties:{analysts:{title:'Billing analysts'}}},field:{title:'Field work',properties:{crew_meter:{title:'Meter crew',$ref:'#/$defs/Crew'}}}},$defs:{Crew:{properties:{per_1000_premises:{title:'Per 1,000 premises'}}}}});
 assert.equal(settings['process.analysts'].title,'Billing analysts');assert.equal(settings['field.crew_meter.per_1000_premises'].title,'Meter crew · Per 1,000 premises');
 const html=glossaryMarkup(catalogue,{settings,scenarios:{half_staff_billing:{title:'Billing at half staff'}},mine:['days_to_pay'],simulation:{name:'Winter VEE',kpis:['days_to_pay']},configHref:'./studio.html#/config/m2c'});
 assert.match(html,/id="family-billing"/);assert.match(html,/id="family-cash"/);assert.match(html,/Billing analysts<span class="dir">Process &amp; costs · lowers it/);assert.match(html,/Billing at half staff/);assert.match(html,/On time bill days<\/b>: 3 days/);assert.match(html,/change in Config/);assert.match(html,/is-mine" id="days_to_pay"/);assert.match(html,/Watching <a href="#days_to_pay">Days to pay/);assert.match(html,/a digital-twin figure/);
 assert.match(glossaryMarkup(catalogue,{filter:'nothing here'}),/Nothing matches/);assert.doesNotMatch(glossaryMarkup(catalogue,{filter:'days to pay'}),/id="bills_on_time"/);
});

test('a picked figure replaces the words that named it and keeps the rest of the message',()=>{
 const bills=catalogue.kpis.find(k=>k.id==='bills_on_time'),pay=catalogue.kpis.find(k=>k.id==='days_to_pay');
 assert.equal(withKpiTitle('I want to watch the bills on',bills),'I want to watch the Bills on time ');
 assert.equal(withKpiTitle('Our backlog is fine. days to',pay),'Our backlog is fine. Days to pay ');
 assert.equal(withKpiTitle('watch time bills',bills),'watch Bills on time ');
 assert.equal(withKpiTitle('',bills),'Bills on time ');
 assert.equal(withKpiTitle('keep an eye on staffing',bills),'keep an eye on staffing Bills on time ');
});
