import test from 'node:test';import assert from 'node:assert/strict';
import {fileInput,importedRecord,handleLabel,exportFile,importFile,parseFileText,FILE_SUFFIX} from '../dist/share-file.js';
import {captureToken} from '../dist/local-session.js';
import {SimulationLibrary} from '../dist/simulation-library.js';
function memory(){const m=new Map();return {get length(){return m.size;},key:i=>[...m.keys()][i],getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v),removeItem:k=>m.delete(k)};}
const reply=(status,body)=>async()=>({ok:status<300,status,json:async()=>body});
test('a file is made from what the simulation runs with: its town reference, locked settings, seed, date and episodes',()=>{
 const s={name:'Winter VEE',preset:'small_town',townRef:'small_town~eNqr',townOverrides:{town:{houses:500}},settings:{process:{analysts:4}},opsSettings:{electricCrews:3},seed:'RUN-1',asOf:'2026-06-30',goals:['vee'],execution:'hosted',
  episodes:[{id:'EP-1',scenario:'half_staff',title:'Half the analysts',from:'2026-02-02',to:'2026-03-03',ramp:0,settings:{process:{analysts:'*0.5'}}}],summary:'x',assumptions:['a'],locked:true,townId:'town-1'};
 const input=fileInput(s);
 assert.equal(input.townRef,'small_town~eNqr');assert.deepEqual(input.opsSettings,{electricCrews:3});assert.deepEqual(input.settings,{process:{analysts:4}});assert.equal(input.seed,'RUN-1');assert.equal(input.asOf,'2026-06-30');
 assert.deepEqual(input.episodes,[{title:'Half the analysts',from:'2026-02-02',to:'2026-03-03',ramp:0,settings:{process:{analysts:'*0.5'}}}],'ids and scenario names stay behind');
 assert.equal(input.execution,'hosted');assert.equal(input.totalHomes,undefined);assert.ok(!('locked' in input)&&!('townId' in input));
 const large=fileInput({...s,execution:'local',totalHomes:500000,homes:2000});assert.equal(large.totalHomes,500000);assert.equal(large.execution,'local');
 assert.equal(fileInput({preset:'village'}).name,'Untitled simulation');
});
test('an imported file becomes a ready simulation that opens unlocked for review, with its handle',()=>{
 const library=new SimulationLibrary(memory());
 const p={execution:'hosted',totalHomes:null,name:'From a friend',goals:['vee'],purpose:'',region:'',preset:'small_town',seed:'RUN-1',asOf:'2026-06-30',townOverrides:{town:{houses:500}},settings:{process:{analysts:4}},operations:{},summary:'Imported.',assumptions:[],limitations:[],
  episodes:[{id:'EP-1',title:'Half',from:'2026-02-02',to:null,ramp:0,settings:{process:{analysts:'*0.5'}},pattern:null}],opsSettings:{electricCrews:3},townRef:'small_town',townId:'town-small',townName:'Small town',homes:500,changes:[]};
 const s=library.save(importedRecord(library.create(),p,'brave-otter-harbour'));
 assert.equal(s.status,'ready');assert.equal(s.locked,false);assert.equal(s.name,'From a friend');assert.equal(s.seed,'RUN-1');assert.equal(s.asOf,'2026-06-30');assert.equal(s.homes,500);assert.equal(s.townRef,'small_town');
 assert.deepEqual(s.settings,{process:{analysts:4}});assert.deepEqual(s.opsSettings,{electricCrews:3});assert.equal(s.episodes.length,1);assert.equal(s.scenarioTitle,'Imported scenarios');assert.equal(s.step,3);assert.equal(s.handle,'brave-otter-harbour');
 assert.ok(library.get(s.id));assert.equal(handleLabel('brave-otter-harbour'),'Brave Otter Harbour');assert.equal(handleLabel(''),'');assert.equal(FILE_SUFFIX,'.utilitysim.json');
});
test('the engine endpoints are called with the record and the chosen file; other files are refused',async()=>{
 let seen;const made=await exportFile('/api',{name:'N',preset:'village'},async(url,init)=>{seen=[url,JSON.parse(init.body)];return {ok:true,json:async()=>({file:{handle:'calm-owl-bay',simulation:{}},filename:'calm-owl-bay.utilitysim.json'})};});
 assert.equal(made.filename,'calm-owl-bay.utilitysim.json');assert.equal(seen[0],'/api/share/export');assert.equal(seen[1].preset,'village');
 await assert.rejects(importFile('/api',{nope:1},reply(422,{detail:'This is not a Utility Studio simulation file.'})),/not a Utility Studio/);
 const p=await importFile('/api',{schemaVersion:'utility-studio-simulation/1.0'},reply(200,{handle:'h',proposal:{name:'x'}}));assert.equal(p.proposal.name,'x');
 assert.throws(()=>parseFileText('not json'),/not a Utility Studio/);assert.throws(()=>parseFileText('[1]'),/not a Utility Studio/);assert.deepEqual(parseFileText('{"a":1}'),{a:1});
});
test('the launcher’s token is taken from the page fragment, kept for this origin and removed from the address',()=>{
 const storage=memory(),calls=[];const history={replaceState:(...a)=>calls.push(a)};
 assert.equal(captureToken({hash:'#token=abc',pathname:'/',search:'?x=1'},storage,history),'abc');assert.equal(storage.getItem('utility-studio-local-token'),'abc');assert.deepEqual(calls,[[null,'','/?x=1']]);
 assert.equal(captureToken({hash:'#/new',pathname:'/',search:''},storage,history),'abc','a later page without the fragment still has it');assert.equal(calls.length,1);
 assert.equal(captureToken({hash:'',pathname:'/',search:''},memory(),history),'');
});
