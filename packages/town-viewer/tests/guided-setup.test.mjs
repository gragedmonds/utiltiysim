import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fieldsFor,pagesFor,initialize,setValue,applyChoice,resetValue,meterMix,moveBoundary,setMix,sliderFor,fieldAt} from '../dist/guided-model.js';
import {worldRequest} from '../dist/guided-setup.js';

const schema=JSON.parse(readFileSync(new URL('../../../schemas/config.schema.json',import.meta.url)));
const wizard=JSON.parse(readFileSync(new URL('../../../utilsim/config/wizard.json',import.meta.url)));
const run={...schema,properties:Object.fromEntries(Object.entries(schema.properties).filter(([k,g])=>schema.$defs[g.$ref?.split('/').at(-1)]?.['x-applies']==='run'))};
const data={wizard,schemas:{town:schema,run},defaults:{town:{town:{houses:500,era_core_year:1925,era_span_years:85,era_noise_years:8},ami:{ami_route_share:.4,amr_route_share:.4}},run:{}}};
const fields=fieldsFor(data);
const draft=()=>{const d={name:'Test utility',townOverrides:{},settings:{},operations:{}};initialize(d,data,{fresh:true,local:true});return d;};

test('all generation and annual settings have exactly one page, with at most four top-level controls',()=>{
 const pages=pagesFor(data,fields),ids=pages.flatMap(p=>p.fields.map(f=>f.id));
 assert.deepEqual(ids.toSorted(),fields.map(f=>f.id).toSorted());assert.equal(new Set(ids).size,ids.length);
 assert.ok(pages.every(p=>p.fields.length<=4));assert.equal(new Set(pages.map(p=>p.id)).size,pages.length);
 assert.deepEqual(pages.find(p=>p.id==='size').fields.map(f=>f.id),['town:town.houses']);
 assert.ok(pages.find(p=>p.id==='business-2').fields.some(f=>f.id==='town:town.houses_per_school'));
 for(const id of ['town:customers_billing.services','town:town.era_core_year','town:ami.ami_route_share','town:housing.pool_rate'])assert.ok(ids.includes(id));
 const next=pagesFor(data,[...fields,{id:'town:new_network.capacity',scope:'town',group:'new_network',groupTitle:'New network'}]);
 assert.ok(next.some(p=>p.fields.some(f=>f.id==='town:new_network.capacity')));
});
test('multi-value presets keep manually tuned values and reset adopts the latest chosen profile',()=>{
 const d=draft(),page=wizard.pages.find(p=>p.id==='home-age');
 applyChoice(d,data,fields,page.id,page.presets[0]);
 setValue(d,data,fields,'town:town.era_noise_years','7');
 const skipped=applyChoice(d,data,fields,page.id,page.presets[2]);
 assert.deepEqual(skipped,['town:town.era_noise_years']);assert.equal(d.townOverrides.town.era_noise_years,7);assert.equal(d.townOverrides.town.era_core_year,1900);
 resetValue(d,data,fields,'town:town.era_noise_years');assert.equal(d.townOverrides.town.era_noise_years,10);assert.equal(d.guidedSetup.pins['town:town.era_noise_years'],undefined);
});
test('existing draft overrides migrate as pins and nested edits preserve sibling values',()=>{
 const d={townOverrides:{housing:{solar_rate:{modern:.6,postwar:.2}}}};initialize(d,data,{local:true});
 assert.equal(d.guidedSetup.mode,'studio');assert.ok(d.guidedSetup.pins['town:housing.solar_rate.modern']);
 setValue(d,data,fields,'town:housing.solar_rate.pre_1945',.1);assert.equal(d.townOverrides.housing.solar_rate.modern,.6);
 const snapshot=structuredClone(d);initialize(d,data,{local:true});assert.deepEqual(d,snapshot);
});
test('allocation boundaries conserve 100 and only exchange neighbouring route types',()=>{
 assert.deepEqual(moveBoundary([40,40,20],0,65),[65,15,20]);assert.deepEqual(moveBoundary([40,40,20],1,95),[40,55,5]);
 assert.deepEqual(moveBoundary([40,40,20],0,99),[80,0,20]);assert.deepEqual(moveBoundary([40,40,20],1,5),[40,0,60]);
 for(const original of [[100,0,0],[0,100,0],[0,0,100],[30,0,70]])for(const handle of [0,1])for(let value=-10;value<=110;value++){
  const mix=moveBoundary(original,handle,value);assert.equal(mix.reduce((a,b)=>a+b),100);assert.ok(mix.every(v=>v>=0&&v<=100));assert.equal(mix[handle===0?2:0],original[handle===0?2:0]);
 }
});
test('exact allocation rejects invalid totals without modifying either stored share',()=>{
 const d=draft();setMix(d,data,fields,[75.25,14.75,10]);assert.deepEqual(meterMix(d,data),[75.25,14.75,10]);
 const before=structuredClone(d);for(const mix of [[50,50,50],[-1,51,50],[NaN,50,50]])assert.throws(()=>setMix(d,data,fields,mix),/100/);
 assert.deepEqual(d,before);setMix(d,data,fields,[0,0,100]);assert.deepEqual(meterMix(d,data),[0,0,100]);
});
test('invalid numeric and enum values are rejected, and sliders retain exact-value support',()=>{
 const d=draft();assert.throws(()=>setValue(d,data,fields,'town:town.houses',3.5),/whole/);
 assert.throws(()=>setValue(d,data,fields,'town:town.units','invented'),/listed/);
 assert.throws(()=>setValue(d,data,fields,'town:customers_billing.services',[]),/least/);
 const f=fieldAt(fields,'town:ami.ami_route_share'),rail=sliderFor(f,.45);assert.equal(rail.scale,100);assert.equal(rail.max,100);
});
test('whole-utility Studio totals preserve a bounded district template and survive switching modes',()=>{
 const d=draft();d.execution='local';d.guidedSetup.mode='studio';
 setValue(d,{...data,homeLimit:10000},fields,'town:town.houses',25000);
 assert.equal(d.totalHomes,25000);assert.equal(d.homes,25000);assert.equal(d.townOverrides.town.houses,10000);
 d.guidedSetup.mode='world';assert.throws(()=>setValue(d,data,fields,'town:town.houses',25000),/10000/);
 assert.equal(d.totalHomes,25000);assert.equal(d.townOverrides.town.houses,10000);
});
test('hosted town sizes do not accidentally request an offline district run',()=>{
 const d=draft();d.execution='hosted';d.guidedSetup.mode='studio';setValue(d,data,fields,'town:town.houses',2500);
 assert.equal(d.totalHomes,null);assert.equal(d.townOverrides.town.houses,2500);
});
test('creation identity persists for identical requests and changes with the reviewed inputs',()=>{
 const d={...draft(),preset:'small_town',asOf:'2026-01-01',worldSettings:{meters:{annual_meter_failure:.04}}};
 const config={defaults:{world:{meters:{annual_meter_failure:.015,annual_meter_drift:.01},weather:{winter_mean_c:2,summer_mean_c:26,daily_weather_spread_c:6}}}};
 const first=worldRequest(d,config);assert.equal(first.worldSettings.annual_meter_failure,.04);
 assert.deepEqual(worldRequest(d,config),first);assert.equal(worldRequest(structuredClone(d),config).commandId,first.commandId);
 d.name='Another environment';assert.notEqual(worldRequest(d,config).commandId,first.commandId);
});
