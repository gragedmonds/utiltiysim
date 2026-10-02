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
