import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {schemaFields} from '../dist/schema-form.js';
import {inStage,mergeValues,applyRegion,wizardDraft,replaceStageOverrides,setupProposal,acceptSetup,focusGroup} from '../dist/setup-config.js';

const schema=JSON.parse(readFileSync(new URL('../../../schemas/config.schema.json',import.meta.url)));
test('every supported generation field appears in exactly one appropriate wizard stage',()=>{
 const all=schemaFields(schema,{groups:(k,g)=>g['x-applies']!=='run'}).map(f=>f.path);
 const env=schemaFields(schema,{groups:(k,g)=>inStage('town',0,k,g)}).map(f=>f.path);
 const utility=schemaFields(schema,{groups:(k,g)=>inStage('town',1,k,g)}).map(f=>f.path);
 assert.deepEqual([...env,...utility].sort(),all.sort());assert.ok(env.includes('weather.winter'));assert.ok(env.includes('housing.pool_rate'));
 assert.ok(utility.includes('gas.all_electric_district_share'));assert.ok(utility.includes('ami.ami_route_share'));
 assert.equal(inStage('run',0,'process',{}),false);assert.equal(inStage('run',1,'field',{}),true);
});
test('regional choices change their environment inputs and preserve size, advanced edits and utility work',()=>{
 const old={townOverrides:{town:{houses:250},housing:{solar_rate:{modern:.4}},gas:{all_electric_district_share:1}},settings:{process:{analysts:5}},episodes:[{id:'EP-1'}]};
 const next=applyRegion(old,{id:'midwest',name:'Midwest',overrides:{town:{terrain_relief_m:8},housing:{pool_rate:.04}}});
 assert.equal(next.townOverrides.town.houses,250);assert.equal(next.townOverrides.housing.solar_rate.modern,.4);
 assert.equal(next.townOverrides.gas.all_electric_district_share,1);assert.deepEqual(next.settings,old.settings);assert.deepEqual(next.episodes,old.episodes);
 assert.equal(old.townOverrides.housing.pool_rate,undefined);assert.equal(next.configDirty,true);
});
test('advanced reset replaces only this stage and keeps the other stage intact',()=>{
 const draft={townOverrides:{housing:{pool_rate:.2},gas:{all_electric_district_share:1}}};
 replaceStageOverrides(draft,'town',0,{},schema);assert.deepEqual(draft.townOverrides,{gas:{all_electric_district_share:1}});
});
test('old draft steps migrate without changing their configuration; new drafts get a working base town',()=>{
 const old={step:2,name:'Existing',preset:'village',townOverrides:{housing:{pool_rate:.1}}};const next=wizardDraft(old,{});
 assert.equal(next.step,3);assert.equal(next.wizardVersion,4);assert.deepEqual(next.goals,['everything']);assert.deepEqual(next.townOverrides,old.townOverrides);
 assert.equal(wizardDraft({...old,step:3},{}).step,4);assert.equal(wizardDraft({...next,step:2},{}).step,2);
 const fresh=wizardDraft({step:0},{towns:[{preset:'small_town',townId:'town-1',homes:1900}]});assert.equal(fresh.preset,'small_town');assert.equal(fresh.homes,500);assert.equal(fresh.townOverrides.town.houses,500);
});
test('manual review strips derived identifiers and keeps the chosen scenario after validation',()=>{
 const draft={id:'one',status:'draft',name:'Utility',preset:'village',scenarioId:'baseline',scenarioTitle:'Normal operations',townOverrides:{town:{houses:200}},settings:{process:{analysts:4}},episodes:[]};
 const input=setupProposal(draft);assert.equal(input.id,undefined);assert.equal(input.scenarioId,undefined);
 const result=acceptSetup(draft,{...input,townRef:'custom-ref',townId:'town-two',townName:'Village',homes:200,changes:[],opsSettings:{fieldCrews:2}});
 assert.equal(result.scenarioId,'baseline');assert.equal(result.townRef,'custom-ref');assert.equal(result.settings.process.analysts,4);assert.equal(result.step,4);assert.equal(result.configDirty,false);
});
test('merging an advanced nested input preserves sibling defaults and replaces arrays',()=>{
 assert.deepEqual(mergeValues({winter:{mean_c:0,sd_c:6},weights:[1,2]},{winter:{mean_c:-4},weights:[3]}),{winter:{mean_c:-4,sd_c:6},weights:[3]});
});

test('focused forms retain hidden edits and everything reveals every stage group',()=>{
 const data={goals:[{id:'vee',environment:[],town:['ami'],run:['vee','process']},{id:'everything',environment:['*'],town:['*'],run:['*']}]};
 const draft={goals:['vee'],townOverrides:{housing:{pool_rate:.2},weather:{storm_days_per_year:40},town:{houses:500}}};
 const groups=(k,g)=>focusGroup(data,draft,'town',0,k,g);
 assert.equal(groups('housing',{'x-applies':'town'}),false);assert.equal(groups('town',{'x-applies':'town'}),true);
 replaceStageOverrides(draft,'town',0,{town:{houses:1000}},schema,groups);
 assert.equal(draft.townOverrides.housing.pool_rate,.2);assert.equal(draft.townOverrides.weather.storm_days_per_year,40);
 assert.equal(focusGroup(data,{goals:['everything']},'town',0,'housing',{'x-applies':'town'}),true);
 assert.equal(focusGroup(data,{...draft,showAllSettings:{0:true}},'town',0,'housing',{'x-applies':'town'}),true);
 assert.equal(wizardDraft({preset:'village',wizardVersion:2,step:0},{}).step,2);
});
