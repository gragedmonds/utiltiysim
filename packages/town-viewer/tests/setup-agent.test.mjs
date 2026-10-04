import test from 'node:test';
import assert from 'node:assert/strict';
import {applyAgentProposal,proposalInput,supportsVoice} from '../dist/setup-agent.js';
import {EngineM2C} from '../dist/m2c.js';
import {EngineOperations} from '../dist/engine-operations.js';

const proposal={name:'Recovery',purpose:'Reduce backlog',preset:'village',region:'Ontario',seed:'repeat-me',asOf:'2026-05-28',summary:'A recovery plan.',assumptions:[],limitations:[],townOverrides:{},settings:{process:{analysts:2}},operations:{crews:{fieldCrews:3}},opsSettings:{fieldCrews:3},townRef:'village',townId:'town-1',townName:'Village',homes:480,changes:[],episodes:[{id:'EP-1',title:'RPA off',from:'2026-04-01',to:'2026-04-30',ramp:0,settings:{process:{rpa_coverage:0}}}]};
function memory(){const m=new Map();return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v)};}
test('reviewed proposals populate a draft without replacing identity or conversation',()=>{
 const old={id:'sim-1',status:'draft',name:'Old',agent:{messages:[{role:'user',content:'Help'}]},createdAt:'today'};
 const updated=applyAgentProposal(old,proposal);
 assert.equal(updated.id,'sim-1');assert.equal(updated.status,'draft');assert.equal(updated.step,3);assert.equal(updated.scenarioId,'custom');assert.equal(updated.createdAt,'today');assert.equal(updated.agent.messages.length,1);
 assert.deepEqual(updated.settings,{process:{analysts:2}});assert.equal(old.name,'Old');
 assert.throws(()=>applyAgentProposal({...old,status:'ready'},proposal),/new simulation/);
});
test('revalidation sends only configuration inputs, stripping derived fields and episode IDs',()=>{
 const input=proposalInput({...proposal,secret:'do not send',townRef:'anything'});
 assert.equal(input.townRef,undefined);assert.equal(input.opsSettings,undefined);assert.equal(input.secret,undefined);assert.equal(input.episodes[0].id,undefined);assert.equal(proposal.episodes[0].id,'EP-1');
});
test('agent settings reach both engine clients and saved user changes win when reopening',()=>{
 const store=memory(),draft=applyAgentProposal({id:'sim-1',status:'draft'},proposal);
 const m=new EngineM2C({townRef:draft.townRef,townId:draft.townId,simulationId:draft.id,storage:store,initial:draft});
 assert.deepEqual(m.body().settings,proposal.settings);assert.equal(m.body().episodes[0].from,'2026-04-01');assert.equal(m.body().seed,'repeat-me');
 m.setSettings({process:{analysts:4}});const reopened=new EngineM2C({townId:draft.townId,simulationId:draft.id,storage:store,initial:draft});assert.equal(reopened.settings.process.analysts,4);
 const ops=new EngineOperations({id:draft.townId},{simulationId:draft.id,storage:store,initial:draft.opsSettings});assert.equal(ops.settings.fieldCrews,3);
 store.setItem('utility-town-ops-settings:simulation:sim-1:town-1','null');assert.equal(new EngineOperations({id:draft.townId},{simulationId:draft.id,storage:store,initial:draft.opsSettings}).settings,null,'an explicit reset stays reset on reopen');
});
test('voice feature detection supports standard and prefixed browsers, with typing fallback',()=>{
 assert.equal(supportsVoice({}),false);assert.equal(supportsVoice({SpeechRecognition:class{}}),true);assert.equal(supportsVoice({webkitSpeechRecognition:class{}}),true);
});

test('Year context includes live settings and existing episodes while omitting conversation metadata',async()=>{
 const {runInput,currentRunInput,inflictInput,BASELINE_TOPICS}=await import('../dist/setup-agent.js');
 const m=new EngineM2C({townRef:'village',townId:'town-1',storage:memory(),initial:proposal});
 m.setSettings({process:{analysts:5}});
 const context=runInput({...currentRunInput(m,'2026-06-01'),agent:{messages:[{role:'user',content:'Private history'}]},actions:[{id:'ACT-1'}]});
 assert.equal(context.settings.process.analysts,5);assert.equal(context.startDate,'2026-06-01');assert.equal(context.episodes[0].id,'EP-1');assert.equal(context.agent,undefined);assert.equal(context.actions,undefined);
 const tweak=inflictInput({name:'Half staff',summary:'Six weeks',episodes:proposal.episodes,runTo:'2026-05-28',townOverrides:{bad:true}});
 assert.equal(tweak.runTo,undefined);assert.equal(tweak.townOverrides,undefined);assert.equal(BASELINE_TOPICS.length,8);
});
