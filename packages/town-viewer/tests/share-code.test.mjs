import test from 'node:test';import assert from 'node:assert/strict';
import {codeInput,importedRecord,groupedCode,fetchCode,decodeCode} from '../dist/share-code.js';
import {captureToken} from '../dist/local-session.js';
import {SimulationLibrary} from '../dist/simulation-library.js';
function memory(){const m=new Map();return {get length(){return m.size;},key:i=>[...m.keys()][i],getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v),removeItem:k=>m.delete(k)};}
const reply=(status,body)=>async()=>({ok:status<300,status,json:async()=>body});
test('a code is made from what the simulation runs with: its town reference, locked settings, seed, date and episodes',()=>{
 const s={name:'Winter VEE',preset:'small_town',townRef:'small_town~eNqr',townOverrides:{town:{houses:500}},settings:{process:{analysts:4}},opsSettings:{electricCrews:3},seed:'RUN-1',asOf:'2026-06-30',goals:['vee'],execution:'hosted',
  episodes:[{id:'EP-1',scenario:'half_staff',title:'Half the analysts',from:'2026-02-02',to:'2026-03-03',ramp:0,settings:{process:{analysts:'*0.5'}}}],summary:'x',assumptions:['a'],locked:true,townId:'town-1'};
 const input=codeInput(s);
 assert.equal(input.townRef,'small_town~eNqr');assert.deepEqual(input.opsSettings,{electricCrews:3});assert.deepEqual(input.settings,{process:{analysts:4}});assert.equal(input.seed,'RUN-1');assert.equal(input.asOf,'2026-06-30');
 assert.deepEqual(input.episodes,[{title:'Half the analysts',from:'2026-02-02',to:'2026-03-03',ramp:0,settings:{process:{analysts:'*0.5'}}}],'ids and scenario names stay behind');
 assert.equal(input.execution,'hosted');assert.equal(input.totalHomes,undefined);assert.ok(!('locked' in input)&&!('townId' in input));
 const large=codeInput({...s,execution:'local',totalHomes:25000,homes:2000});assert.equal(large.totalHomes,25000);assert.equal(large.execution,'local');
 assert.equal(codeInput({preset:'village'}).name,'Untitled simulation');
});
test('an imported code becomes a ready simulation that opens unlocked for review',()=>{
 const library=new SimulationLibrary(memory());
 const p={execution:'hosted',totalHomes:null,name:'From a friend',goals:['vee'],purpose:'',region:'',preset:'small_town',seed:'RUN-1',asOf:'2026-06-30',townOverrides:{town:{houses:500}},settings:{process:{analysts:4}},operations:{},summary:'Imported.',assumptions:[],limitations:[],
  episodes:[{id:'EP-1',title:'Half',from:'2026-02-02',to:null,ramp:0,settings:{process:{analysts:'*0.5'}},pattern:null}],opsSettings:{electricCrews:3},townRef:'small_town',townId:'town-small',townName:'Small town',homes:500,changes:[]};
 const s=library.save(importedRecord(library.create(),p));
 assert.equal(s.status,'ready');assert.equal(s.locked,false);assert.equal(s.name,'From a friend');assert.equal(s.seed,'RUN-1');assert.equal(s.asOf,'2026-06-30');assert.equal(s.homes,500);assert.equal(s.townRef,'small_town');
 assert.deepEqual(s.settings,{process:{analysts:4}});assert.deepEqual(s.opsSettings,{electricCrews:3});assert.equal(s.episodes.length,1);assert.equal(s.scenarioTitle,'Imported scenarios');assert.equal(s.step,3);
 assert.ok(library.get(s.id));
});
test('codes are shown in groups of five and the engine endpoints are called with the record and the pasted text',async()=>{
 assert.equal(groupedCode('UTS1ABCDEFGHJK12'),'UTS1-ABCDE-FGHJK-12');assert.equal(groupedCode('uts1-abcde fghjk\n12'),'UTS1-ABCDE-FGHJK-12');assert.equal(groupedCode(''),'');
 let seen;const made=await fetchCode('/api',{name:'N',preset:'village'},async(url,init)=>{seen=[url,JSON.parse(init.body)];return {ok:true,json:async()=>({code:'UTS1A',grouped:'UTS1-A',chars:5})};});
 assert.equal(made.code,'UTS1A');assert.equal(seen[0],'/api/share/encode');assert.equal(seen[1].preset,'village');
 await assert.rejects(decodeCode('/api',' bad ',reply(422,{detail:'A simulation code starts with UTS1.'})),/starts with UTS1/);
 const p=await decodeCode('/api','UTS1-A',reply(200,{proposal:{name:'x'}}));assert.equal(p.name,'x');
});
test('the launcher’s token is taken from the page fragment, kept for this origin and removed from the address',()=>{
 const storage=memory(),calls=[];const history={replaceState:(...a)=>calls.push(a)};
 assert.equal(captureToken({hash:'#token=abc',pathname:'/',search:'?x=1'},storage,history),'abc');assert.equal(storage.getItem('utility-studio-local-token'),'abc');assert.deepEqual(calls,[[null,'','/?x=1']]);
 assert.equal(captureToken({hash:'#/new',pathname:'/',search:''},storage,history),'abc','a later page without the fragment still has it');assert.equal(calls.length,1);
 assert.equal(captureToken({hash:'',pathname:'/',search:''},memory(),history),'');
});
