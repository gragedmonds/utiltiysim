import test from 'node:test';
import assert from 'node:assert/strict';
import {STAFFING_REFERENCE_HOMES,suggestedStaffing,staffingBase,applySuggestedStaffing,markStaffingEdited,staffingEdited,staffingHint,staffingSummary,crewHint,
 legacyServices,migrateServices,servicesState,servicesSummary,servicesNote,toggleService,withServices,hasGasMains} from '../dist/setup-utility.js';
import {wizardDraft,setupProposal} from '../dist/setup-config.js';
import {servedServices} from '../dist/schema-form.js';

const BASE={analysts:2,agents:1};
test('suggested staffing: the reference town gets the engine defaults, others scale linearly, round and keep one',()=>{
 assert.equal(STAFFING_REFERENCE_HOMES,1900);
 assert.deepEqual(suggestedStaffing(1900,BASE),{analysts:2,agents:1});
 assert.deepEqual(suggestedStaffing(1900),{analysts:2,agents:1});
 assert.deepEqual(suggestedStaffing(3800,BASE),{analysts:4,agents:2});
 assert.deepEqual(suggestedStaffing(5000,BASE),{analysts:5,agents:3});
 assert.deepEqual(suggestedStaffing(10000,BASE),{analysts:11,agents:5});
 assert.deepEqual(suggestedStaffing(500,BASE),{analysts:1,agents:1});
 for(const tiny of [1,100,0,-5,NaN,undefined])assert.deepEqual(suggestedStaffing(tiny,BASE),{analysts:1,agents:1});
 assert.deepEqual(suggestedStaffing(1900,{analysts:6,agents:3}),{analysts:6,agents:3});
 assert.deepEqual(suggestedStaffing(10_000_000,BASE),{analysts:200,agents:500});
 assert.deepEqual(staffingBase({process:{analysts:2},contact:{agents:1}}),BASE);
 assert.deepEqual(staffingHint({key:'analysts'},5000,5,BASE),{suggested:5,text:'Suggested for 5,000 homes: 5',differs:false});
 assert.equal(staffingHint({key:'analysts'},1900,7,BASE).differs,true);
});
test('suggestions follow the town size until someone types a value, and stay out of the settings at the reference size',()=>{
 const draft={settings:{process:{rpa_coverage:.5}}};
 assert.deepEqual(applySuggestedStaffing(draft,500,BASE),['process.analysts']);
 assert.deepEqual(draft.settings,{process:{rpa_coverage:.5,analysts:1}});
 assert.deepEqual(applySuggestedStaffing(draft,5000,BASE).sort(),['contact.agents','process.analysts']);
 assert.equal(draft.settings.process.analysts,5);assert.equal(draft.settings.contact.agents,3);
 // Typed: analysts stays 7 whatever the size; agents keeps following.
 draft.settings.process.analysts=7;markStaffingEdited(draft,'process.analysts');assert.equal(staffingEdited(draft,'process.analysts'),true);
 assert.deepEqual(applySuggestedStaffing(draft,500,BASE),['contact.agents']);
 assert.equal(draft.settings.process.analysts,7);assert.equal(draft.settings.contact,undefined);
 // Back to the suggestion ("Use 1") and back at the reference size: the engine defaults, nothing in the settings.
 markStaffingEdited(draft,'process.analysts',false);draft.staffing.applied['process.analysts']=7;
 applySuggestedStaffing(draft,STAFFING_REFERENCE_HOMES,BASE);
 assert.deepEqual(draft.settings,{process:{rpa_coverage:.5}});assert.deepEqual(draft.staffing.edited,{});
 // A value chosen elsewhere (the conversation, an old draft) is not a suggestion: it stays.
 const chosen={settings:{process:{analysts:4}}};assert.deepEqual(applySuggestedStaffing(chosen,5000,BASE),['contact.agents']);
 assert.equal(chosen.settings.process.analysts,4);assert.equal(chosen.settings.contact.agents,3);
 assert.equal(staffingSummary(chosen.settings,BASE),'4 billing analysts · 3 contact-centre agents');
 assert.equal(staffingSummary({},BASE),'2 billing analysts · 1 contact-centre agent');
 assert.equal(crewHint(.3,5000),'About 1.5 crews at 5,000 homes, more with shops and other sites');
 assert.equal(crewHint(.2,5000),'About 1 crew at 5,000 homes, more with shops and other sites');
});
test('service cards: every service is a toggle, served by default; the last one on stays on',()=>{
 const all=servicesState({share:.15,homes:500,gasMinHomes:2251});
 for(const k of ['electric','water','gas'])assert.deepEqual([all[k].on,all[k].locked,all[k].line],[true,false,'Served by your utility']);
 assert.equal(servicesSummary(all),'Electricity · Water · Natural gas');
 // Electricity only: water and gas come from another utility; electricity is the last one, so it is locked with why.
 const e=servicesState({served:['electric'],share:.15,homes:500,gasMinHomes:2251});
 assert.deepEqual([e.electric.on,e.electric.locked,e.electric.note],[true,true,'Your only service']);assert.match(e.electric.reason,/at least one service/);
 for(const k of ['water','gas'])assert.deepEqual([e[k].on,e[k].locked,e[k].line],[false,false,'Another utility serves this']);
 assert.equal(servicesSummary(e),'Electricity only; water and gas by another utility');
 assert.match(servicesNote(e,{gasMinHomes:2251}),/^Water and gas come from another utility: their networks stay on the map/);
 assert.match(servicesNote(e,{gasMinHomes:2251}),/Gas mains still run under the streets: they are another utility’s\./);
 assert.match(servicesNote(e,{gasMinHomes:2251}),/a town under 2,251 homes is one district and keeps its gas mains/);
 assert.equal(servicesSummary(servicesState({served:['electric','water']})),'Electricity and water only; gas by another utility');
 // Toggles keep the canonical order and never empty the list.
 assert.deepEqual(toggleService(['electric','water','gas'],'water',false),['electric','gas']);
 assert.deepEqual(toggleService(['gas'],'electric',true),['electric','gas']);
 assert.deepEqual(toggleService(['electric'],'electric',false),[]);
 assert.deepEqual(servedServices({customers_billing:{services:['gas','electric']}}),['electric','gas']);
 assert.deepEqual(servedServices({customers_billing:{}}),['electric','water','gas']);assert.deepEqual(servedServices(null),['electric','water','gas']);
});
test('service cards write customers_billing.services into the town overrides, leaving it out when all three are on',()=>{
 const one=withServices({town:{houses:500}},['electric']);assert.deepEqual(one,{town:{houses:500},customers_billing:{services:['electric']}});
 const back=withServices(one,['gas','water','electric']);assert.deepEqual(back,{town:{houses:500}});
 assert.deepEqual(withServices({customers_billing:{due_days:30,services:['water']}},['electric','water','gas']),{customers_billing:{due_days:30}});
 assert.deepEqual(withServices(undefined,['water','electric']),{customers_billing:{services:['electric','water']}});
 // The proposal the setup validates carries it as a town override.
 const p=setupProposal({name:'E only',preset:'village',townOverrides:one,settings:{},operations:{},episodes:[]});
 assert.deepEqual(p.townOverrides.customers_billing,{services:['electric']});
});
test('gas mains are physical: the share of districts without them, from the size where a town has several districts',()=>{
 assert.equal(hasGasMains({share:1,homes:5000,gasMinHomes:2251}),false);assert.equal(hasGasMains({share:1,homes:500,gasMinHomes:2251}),true);
 assert.equal(hasGasMains({share:.15,homes:5000,gasMinHomes:2251}),true);assert.equal(hasGasMains({share:1,homes:500}),false);
 // Served gas with no mains: no home takes it; the summary says so.
 const none=servicesState({share:1,homes:5000,gasMinHomes:2251});assert.equal(none.gas.on,true);
 assert.equal(servicesSummary(none),'Electricity · Water · Natural gas · no gas mains (all-electric heating)');
 assert.match(servicesNote(none),/no gas mains \(Advanced\), so no home takes your gas/);
 // A utility would be left with gas alone in a town without gas mains: the others it serves stay on.
 const eg=servicesState({served:['electric','gas'],share:1,homes:5000,gasMinHomes:2251});
 assert.deepEqual([eg.electric.locked,eg.electric.note,eg.gas.locked],[true,'Kept: no gas mains',false]);
 assert.equal(servicesSummary(eg),'Electricity and gas only; water by another utility · no gas mains (all-electric heating)');
 // Not served and no mains: nobody's gas.
 assert.equal(servicesSummary(servicesState({served:['electric','water'],share:1,homes:5000,gasMinHomes:2251})),'Electricity and water only; no gas mains');
});
test('drafts that switched gas off the old way keep it as the physical gas share',()=>{
 assert.deepEqual(legacyServices('mixed'),{electric:true,water:true,gas:true});
 assert.deepEqual(legacyServices('electric'),{electric:true,water:true,gas:false});
 const electric=migrateServices({services:'electric',townOverrides:{town:{houses:5000}}});
 assert.equal(electric.services,undefined);assert.equal(electric.townOverrides.gas.all_electric_district_share,1);
 assert.equal(servicesState({share:electric.townOverrides.gas.all_electric_district_share,homes:5000,gasMinHomes:2251}).gasMains,false);
 const mixed=migrateServices({services:'mixed',townOverrides:{}});assert.equal(mixed.services,undefined);assert.deepEqual(mixed.townOverrides,{});
 const kept=migrateServices({services:'electric',townOverrides:{gas:{all_electric_district_share:.4}}});assert.equal(kept.townOverrides.gas.all_electric_district_share,.4);
 assert.equal(migrateServices({services:{gas:false}}).townOverrides.gas.all_electric_district_share,1);
 const loaded=wizardDraft({wizardVersion:2,step:1,preset:'small_town',services:'electric',townOverrides:{}},{});
 assert.equal(loaded.services,undefined);assert.equal(loaded.townOverrides.gas.all_electric_district_share,1);
 // Gas switched off the old way stays physical (no gas mains); the utility's services are not invented from it.
 for(const d of [loaded,electric,wizardDraft({wizardVersion:3,step:2,preset:'small_town',townOverrides:{gas:{all_electric_district_share:1}}},{})]){
  assert.equal(d.townOverrides.customers_billing,undefined);
  assert.equal(servicesState({served:servedServices(d.townOverrides),share:1,homes:5000,gasMinHomes:2251}).gas.on,true);}
});
