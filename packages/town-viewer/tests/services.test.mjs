// A utility can provide any of electricity, water and gas (customers_billing.services): settings for the others show
// as not applicable, and a premise's other networks read "Served by another utility".
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {schemaFields,applyServices,serviceStatus,serviceNames,servedServices,infoLines,parseField,overridesFrom} from '../dist/schema-form.js';
import {traceConnection,serviceOf,premiseConnections,OTHER_UTILITY} from '../dist/adapter.js';
import {customerIndex,customerProfile} from '../dist/customer.js';
import {customerTabs,profileHeader,customerMarkup,otherUtilityServices} from '../dist/customer-view.js';
import {snapshot} from './fixtures.mjs';

// x-services on a scalar, on a compound field (a crew, through $ref), on a whole group and on one sub-value.
const schema={properties:{billing:{$ref:'#/$defs/Billing'},field:{$ref:'#/$defs/Field'},gas:{$ref:'#/$defs/Gas'}},
 $defs:{
  Crew:{type:'object',properties:{per_1000_premises:{type:'number',default:.2},overtime_factor:{type:'number',default:1.5}}},
  Billing:{title:'Billing',properties:{
   winter_moratorium:{type:'boolean',default:true,'x-services':['electric','water']},
   gas_price_m3:{type:'number',default:.4,'x-services':['gas']},
   basement:{type:'number',default:0,'x-status':'not-modelled','x-status-reason':'Not yet.','x-services':['gas']},
   due_days:{type:'integer',default:20}}},
  Field:{title:'Field',properties:{
   crew_gas:{$ref:'#/$defs/Crew',default:{per_1000_premises:.2,overtime_factor:1.5},'x-services':['gas']},
   valve:{type:'object',properties:{water:{type:'number',default:1,'x-services':['water']},gas:{type:'number',default:1,'x-services':['gas']}},default:{water:1,gas:1}}}},
  Gas:{title:'Gas','x-services':['gas'],properties:{leak_rate:{type:'number',default:.1},meter_digits:{type:'integer',default:5,'x-services':['electric']}}}}};

test('a setting for a service the utility does not provide is disabled as not applicable, with the reason; it keeps its value',()=>{
 const f=Object.fromEntries(schemaFields(schema,{services:['electric']}).map(x=>[x.path,x]));
 assert.deepEqual([f['billing.gas_price_m3'].disabled,f['billing.gas_price_m3'].status,f['billing.gas_price_m3'].reason],[true,'not-applicable','your utility does not provide gas.']);
 assert.equal(f['billing.winter_moratorium'].disabled,false,'one of its services is provided');
 assert.equal(f['billing.due_days'].disabled,false,'untagged settings always apply');
 // A whole compound field (a crew) and a whole group.
 assert.equal(f['field.crew_gas'].type,'object');assert.deepEqual([f['field.crew_gas'].disabled,f['field.crew_gas'].status],[true,'not-applicable']);
 assert.ok(f['field.crew_gas'].children.every(c=>c.disabled));
 assert.deepEqual([f['gas.leak_rate'].disabled,f['gas.leak_rate'].reason],[true,'your utility does not provide gas.']);
 assert.equal(f['gas.meter_digits'].disabled,false,'a field\'s own tag wins over its group\'s');
 // One sub-value of a compound row: only that sub-input is not applicable.
 const valve=f['field.valve'];assert.equal(valve.disabled,false);
 assert.deepEqual(valve.children.map(c=>[c.key,c.disabled]),[['water',true],['gas',true]]);
 const water=schemaFields(schema,{services:['water']}).find(x=>x.path==='field.valve');
 assert.deepEqual(water.children.map(c=>[c.key,c.disabled,c.notApplicable]),[['water',false,''],['gas',true,'Not applicable: your utility does not provide gas.']]);
 // The engine's own status comes first.
 assert.deepEqual([f['billing.basement'].status,f['billing.basement'].reason],['not-modelled','Not yet.']);
 // No services given: everything applies, as before.
 assert.ok(schemaFields(schema).filter(x=>!x.modelStatus).every(x=>!x.disabled));
 // Not applicable is display only: an edited value still reports.
 assert.deepEqual(overridesFrom(Object.values(f),{billing:{gas_price_m3:.6}}),{billing:{gas_price_m3:.6}});
});
test('the served set changes in place: settings come back when their service is ticked again',()=>{
 const f=schemaFields(schema,{services:['electric']}).find(x=>x.path==='billing.gas_price_m3');
 applyServices(f,['electric','gas']);assert.deepEqual([f.disabled,f.status],[false,undefined]);
 applyServices(f,['water']);assert.equal(f.status,'not-applicable');
 const b=schemaFields(schema,{services:['electric']}).find(x=>x.path==='billing.basement');applyServices(b,['gas']);assert.equal(b.status,'not-modelled');
 assert.equal(serviceStatus(['water','gas'],['electric']).reason,'your utility does not provide water or gas.');
 assert.equal(serviceStatus(['electric','water'],['gas']).reason,'your utility does not provide electricity or water.');
 assert.equal(serviceStatus(['gas'],null),null);assert.equal(serviceStatus(undefined,['electric']),null);
 assert.equal(serviceNames(['electric','water','gas'],'and'),'electricity, water and gas');
 assert.ok(infoLines(f).includes('Not applicable: your utility does not provide gas.'));
 assert.ok(infoLines(f).includes('Applies when your utility provides gas'));
});
test('the engine schema: an electricity-only utility greys out water and gas tariffs, crews and work',()=>{
 const config=JSON.parse(readFileSync(new URL('../../../schemas/config.schema.json',import.meta.url)));
 const served=servedServices({customers_billing:{services:['electric']}}),f=Object.fromEntries(schemaFields(config,{services:served}).map(x=>[x.path,x]));
 for(const p of ['customers_billing.gas_price_m3','customers_billing.water_price_m3','field.hydrant_flush','field.valve_exercise','field.crew_gas','contact.gas_odour','anomalies.leak','ami.meter_digits_water'])
  assert.equal(f[p].status,'not-applicable',p);
 for(const p of ['customers_billing.electric_fixed_monthly','billing.winter_moratorium','field.crew_electric','field.pole_inspection','gas.all_electric_district_share','water.cast_iron_before_year','customers_billing.services']){
  assert.ok(f[p],p);assert.equal(f[p].status,undefined,p);}
 assert.match(f['field.valve_exercise'].reason,/water or gas/);
 // The services themselves: a row of checkboxes, at least one ticked.
 const s=f['customers_billing.services'];assert.equal(s.type,'set');assert.deepEqual(s.options,['electric','water','gas']);
 assert.deepEqual(parseField(s,['gas','electric']),{ok:true,value:['electric','gas']});
 assert.deepEqual(parseField(s,[]),{ok:false,error:'Choose at least one.'});
 assert.equal(parseField(s,['steam']).ok,false);
});

// P-2 is another utility's water and gas customer: its utility (this one) serves its electricity only.
function shared(){const t=snapshot(),h=t.premises[1];h.services={electric:'SP-2-electric'};h.connections=['electric','water','gas'];return t;}
test('a network another utility serves reads "Served by another utility", not "No service"',()=>{
 const t=shared(),h=t.premises[1];
 assert.deepEqual(traceConnection(t,'P-2','water'),{connected:false,edges:[],reason:OTHER_UTILITY});
 assert.equal(traceConnection(t,'P-2','electric').connected,true);
 assert.deepEqual([serviceOf(h,'electric'),serviceOf(h,'water'),serviceOf(h,'gas')],['served','other','other']);
 assert.deepEqual(premiseConnections(h),['electric','water','gas']);
 // Without connections (every service is the utility's), a missing service is no service at all.
 const g=snapshot();g.premises[1].services.gas=null;
 assert.equal(serviceOf(g.premises[1],'gas'),null);assert.deepEqual(premiseConnections(g.premises[1]),['electric','water']);
 assert.equal(traceConnection(g,'P-2','gas').reason,'No service');
});
test('the inspector lists another utility\'s services and has no billing for a premise that is not a customer',()=>{
 const at='2026-07-15T12:00:00Z',home={id:'P-9',address:'9 Side St',accountId:'CA-P-9',occupied:true,services:{electric:'SP-9'},connections:['electric','water','gas']};
 const t={premises:[home],servicePoints:[{id:'SP-9',installationId:'IN-9'}],installations:[{id:'IN-9'}],accounts:[{id:'CA-P-9',businessPartnerId:'BP-P-9'}],businessPartners:[{id:'BP-P-9',name:'Sam Patel'}]};
 assert.deepEqual(otherUtilityServices(home),['water','gas']);
 const html=customerMarkup(customerProfile(t,customerIndex(t),home,at),[]);
 assert.match(html,/<h3>Electricity<\/h3><button data-service-detail="electric"/);
 assert.equal(html.match(/Served by another utility: no meter, contract or bills of yours here\./g).length,2);
 assert.match(html,/<h3>Water<\/h3>/);assert.match(html,/<h3>Gas<\/h3>/);
 // Not a customer at all (accountId null): no Billing tab, and the header and account say so.
 const other={...home,id:'P-8',accountId:null,services:{},connections:['electric','water']},t2={premises:[other]},p=customerProfile(t2,customerIndex(t2),other,at);
 assert.match(profileHeader(p,'snapshot'),/<h2>Not a customer of this utility<\/h2>/);
 assert.match(customerMarkup(p,[]),/Not a customer of this utility: another utility serves this property\./);
 assert.doesNotMatch(customerTabs('customer',{billing:false}),/data-profile-tab="billing"/);
 assert.match(customerTabs('customer'),/data-profile-tab="billing"/);
});
