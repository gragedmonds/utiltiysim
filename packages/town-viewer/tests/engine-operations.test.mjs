import test from 'node:test';
import assert from 'node:assert/strict';
import {EngineOperations} from '../dist/engine-operations.js';

// A tiny fake engine: records requests and answers with a fixed timeline.
function fakeFetch(log){return async(url,opts={})=>{const body=opts.body?JSON.parse(opts.body):null;log.push({url,body});
 const job={id:'JOB-1',kind:'field_visit',premiseId:'P-1',incidentId:null,startAt:100,arrivalAt:110,workSeconds:20,returnStartAt:130,endAt:140,
  route:[{x:0,z:0},{x:10,z:0},{x:10,z:10}],routeTimes:[0,4,10],returnRoute:[{x:10,z:10},{x:10,z:0},{x:0,z:0}],returnTimes:[0,6,10],roadPoint:{x:10,z:10},visitPoint:{x:12,z:12}};
 const tl={schemaVersion:'utility-timeline/1.0',simulationId:'run-x',incidents:[{id:'INC-1',commandId:'CMD-1',createdAt:50,restoredAt:null,jobId:null}],jobs:[job],events:[],reads:[],stateChanges:[{at:50},{at:90}],depot:{x:0,z:0},warnings:[]};
 return {ok:true,json:async()=>url.endsWith('/sim/frame')?{schemaVersion:'utility-state/1.0'}:tl};};}

test('commands are appended at sim time, never earlier, and the whole list is sent',async()=>{
 const log=[];globalThis.fetch=fakeFetch(log);const ops=new EngineOperations({id:'town-x',facilities:[]},{api:'/api',townRef:'ayr'});
 ops.time=200;await ops.dispatch({id:'P-1'});ops.time=150;await ops.breakAsset({id:'POLE-1',kind:'pole',utility:'electric',edgeId:'E1',x:1,z:2});
 const last=log.at(-1).body;assert.equal(log.at(-1).url,'/api/sim/timeline');assert.equal(last.town,'ayr');
 assert.deepEqual(last.commands.map(c=>[c.type,c.at]),[['dispatch',200],['break_asset',200]]);
 assert.deepEqual(last.commands[1].payload,{id:'POLE-1',kind:'pole',utility:'electric',edgeId:'E1',x:1,z:2});
 assert.equal(ops.incidents[0].restoredAt,Infinity,'open-ended until the engine schedules a repair');
});

test('job state follows the engine route by time, parks on site and returns',()=>{
 const ops=new EngineOperations({id:'town-x',facilities:[]},{townRef:'ayr'});ops.apply({incidents:[],events:[],reads:[],stateChanges:[],jobs:[{startAt:100,arrivalAt:110,workSeconds:20,returnStartAt:130,endAt:140,
  route:[{x:0,z:0},{x:10,z:0},{x:10,z:10}],routeTimes:[0,4,10],returnRoute:[{x:10,z:10},{x:10,z:0},{x:0,z:0}],returnTimes:[0,6,10],roadPoint:{x:10,z:10},visitPoint:{x:12,z:12}}]});
 const job=ops.jobs[0];assert.equal(ops.jobState(job,99).status,'future');
 const half=ops.jobState(job,102);assert.equal(half.status,'en_route');assert.deepEqual([half.position.x,half.position.z],[5,0]);
 const turn=ops.jobState(job,107);assert.deepEqual([turn.position.x,turn.position.z],[10,5]);
 const site=ops.jobState(job,120);assert.equal(site.status,'on_site');assert.ok(site.agent);
 assert.equal(ops.jobState(job,133).status,'returning');assert.equal(ops.jobState(job,140).status,'completed');
});

test('reading rounds: a walker leaves the van parked; a drive-by van drives its round',()=>{
 const ops=new EngineOperations({id:'town-x',facilities:[]},{townRef:'x'});
 const base={startAt:0,arrivalAt:10,returnStartAt:110,endAt:120,route:[{x:0,z:0},{x:10,z:0}],routeTimes:[0,10],returnRoute:[{x:10,z:0},{x:0,z:0}],returnTimes:[0,10],
  walkRoute:[{x:10,z:0},{x:10,z:50},{x:10,z:100}],walkTimes:[0,50,100],workSeconds:100,roadPoint:{x:10,z:0},visitPoint:{x:10,z:0}};
 const walk=ops.jobState({...base,kind:'meter_reading',mode:'walk'},60);
 assert.equal(walk.status,'on_site');assert.equal(walk.position.x,10);assert.equal(walk.position.z,0);assert.ok(Math.abs(walk.agent.z-50)<1e-9);
 const drive=ops.jobState({...base,kind:'meter_reading',mode:'drive'},85);
 assert.equal(drive.agent,undefined);assert.ok(Math.abs(drive.position.z-75)<1e-9);
});

test('the run day is part of the request; a new day starts an empty command list; the meter-to-cash run rides along',async()=>{
 const log=[];globalThis.fetch=fakeFetch(log);
 const ops=new EngineOperations({id:'town-x',facilities:[]},{api:'/api',townRef:'ayr',m2c:()=>({actions:[{id:'A1'}]})});
 ops.time=100;await ops.command('dispatch',{targetId:'P-1'});
 assert.deepEqual(log.at(-1).body.m2c,{actions:[{id:'A1'}]});assert.equal(log.at(-1).body.date,null);
 assert.equal(await ops.setDate('2026-03-04'),true);assert.equal(ops.commands.length,0);assert.equal(log.at(-1).body.date,'2026-03-04');
 assert.equal(await ops.setDate('2026-03-04'),false);
});
