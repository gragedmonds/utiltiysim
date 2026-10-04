import test from 'node:test';
import assert from 'node:assert/strict';
import {STAFFING_REFERENCE_HOMES,suggestedStaffing,staffingBase,applySuggestedStaffing,markStaffingEdited,staffingEdited,staffingHint,staffingSummary,crewHint,
 legacyServices,migrateServices,servicesState,servicesSummary,gasShareFor} from '../dist/setup-utility.js';
import {wizardDraft} from '../dist/setup-config.js';

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
test('services: electricity and water are locked on; gas maps to the share the old select used',()=>{
 const big=servicesState({share:.15,homes:5000,gasMinHomes:2251});
 assert.deepEqual([big.electric.on,big.electric.locked,big.water.on,big.water.locked],[true,true,true,true]);
 assert.deepEqual([big.gas.on,big.gas.locked],[true,false]);
 const off=servicesState({share:1,homes:5000,gasMinHomes:2251});assert.deepEqual([off.gas.on,off.gas.locked],[false,false]);
 assert.equal(servicesSummary(off),'Electricity · Water · all-electric heating (no gas)');assert.equal(servicesSummary(big),'Electricity · Water · Natural gas');
 // A one-district town keeps its gas mains whatever the share: locked on, with the reason.
 const small=servicesState({share:1,homes:500,gasMinHomes:2251});assert.deepEqual([small.gas.on,small.gas.locked,small.gas.chosen],[true,true,false]);
 assert.match(small.gas.reason,/under 2,251 homes/);
 // Without the engine's threshold, gas is a plain toggle.
 assert.equal(servicesState({share:1,homes:500}).gas.locked,false);
 assert.equal(gasShareFor(false,.3),1);assert.equal(gasShareFor(true,.3),.3);assert.equal(gasShareFor(true,1),.15);assert.equal(gasShareFor(true),.15);
});
test('drafts that stored the old select value load into the checkboxes',()=>{
 assert.deepEqual(legacyServices('mixed'),{electric:true,water:true,gas:true});
 assert.deepEqual(legacyServices('electric'),{electric:true,water:true,gas:false});
 const electric=migrateServices({services:'electric',townOverrides:{town:{houses:5000}}});
 assert.equal(electric.services,undefined);assert.equal(electric.townOverrides.gas.all_electric_district_share,1);
 assert.equal(servicesState({share:electric.townOverrides.gas.all_electric_district_share,homes:5000,gasMinHomes:2251}).gas.on,false);
 const mixed=migrateServices({services:'mixed',townOverrides:{}});assert.equal(mixed.services,undefined);assert.deepEqual(mixed.townOverrides,{});
 const kept=migrateServices({services:'electric',townOverrides:{gas:{all_electric_district_share:.4}}});assert.equal(kept.townOverrides.gas.all_electric_district_share,.4);
 assert.equal(migrateServices({services:{gas:false}}).townOverrides.gas.all_electric_district_share,1);
 const loaded=wizardDraft({wizardVersion:2,step:1,preset:'small_town',services:'electric',townOverrides:{}},{});
 assert.equal(loaded.services,undefined);assert.equal(loaded.townOverrides.gas.all_electric_district_share,1);
});
