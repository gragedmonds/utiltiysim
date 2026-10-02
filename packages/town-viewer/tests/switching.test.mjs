import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from '../dist/vendor/three.module.js';
import {switchingIntervals,switchingAt,switchingRows,SwitchingMarks,SWITCH_COLORS} from '../dist/switching-marks.js';
// Shapes from the engine's utility-timeline/1.0 (Ayr: a trunk pole back-fed through a tie; a water main isolated).
const ev=(at,eventType,correlationId,payload,entityId=correlationId)=>({at,eventType,correlationId,entityId,payload});
function timeline(){return {
 incidents:[
  {id:'INC-1',utility:'electric',edgeId:'electric-E75',createdAt:28800,isolatedAt:30023.6,restoredAt:37223.6,device:{edgeId:'electric-E1',kind:'recloser'},tie:{edgeId:'electric-E3104',closedAt:30383.6,openedAt:37223.6}},
  {id:'INC-2',utility:'water',edgeId:'water-E2',createdAt:32400,isolatedAt:34800,restoredAt:45000,device:null},
  {id:'INC-3',utility:'electric',edgeId:'electric-E9',createdAt:40000,isolatedAt:null,restoredAt:Infinity,device:{edgeId:'electric-E9',kind:'fuse'}},
  {id:'INC-4',utility:'electric',edgeId:'electric-E50',createdAt:41000,isolatedAt:42000,restoredAt:43000,device:{edgeId:'electric-E50',kind:'conductor'}}],
 events:[
  ev(28800.2,'protection.operated','INC-1',{incidentId:'INC-1',edgeId:'electric-E1',kind:'recloser'},'electric-E1'),
  ev(30023.6,'fault.isolated','INC-1',{openedEdgeId:'electric-E75',reclosedDeviceEdgeId:'electric-E1',stillUnsupplied:461}),
  ev(30383.6,'tie.closed','INC-1',{tieEdgeId:'electric-E3104'}),
  ev(34800,'section.isolated','INC-2',{valveIds:['WV-1','WV-2','WV-3'],closedEdgeIds:['water-E1','water-E2','water-E11'],premiseIds:['P-1'],count:1}),
  ev(40000.2,'protection.operated','INC-3',{incidentId:'INC-3',edgeId:'electric-E9',kind:'fuse'},'electric-E9'),
  ev(41000.2,'protection.operated','INC-4',{incidentId:'INC-4',edgeId:'electric-E50',kind:'conductor'},'electric-E50')]};}

test('switching intervals follow the timeline: device trip to reclose, valves to restoration, tie closed to opened',()=>{
 const iv=switchingIntervals(timeline());
 assert.deepEqual(iv.map(i=>[i.type,i.incidentId,i.from,i.to]),[['device','INC-1',28800.2,30023.6],['tie','INC-1',30383.6,37223.6],['isolation','INC-2',34800,45000],['device','INC-3',40000.2,Infinity]]);
 assert.equal(iv[0].edgeId,'electric-E1');assert.equal(iv[0].kind,'recloser');assert.deepEqual(iv[2].valveIds,['WV-1','WV-2','WV-3']);assert.deepEqual(iv[2].edgeIds,['water-E1','water-E2','water-E11']);
 // No events (an older timeline): the incident's own times stand in.
 const bare=switchingIntervals({incidents:timeline().incidents.slice(0,1),events:[]});assert.deepEqual(bare.map(i=>[i.type,i.from,i.to]),[['device',28800,30023.6],['tie',30383.6,37223.6]]);
 assert.deepEqual(switchingIntervals({}),[]);assert.deepEqual(switchingIntervals({incidents:[{id:'X',createdAt:0,restoredAt:10}]}),[]);
});

test('switching at a time: what is open, closed and back-fed, with a key that changes only when the state does',()=>{
 const iv=switchingIntervals(timeline()),at=t=>switchingAt(iv,t);
 assert.equal(at(28000).key,'');
 const tripped=at(29000);assert.deepEqual(tripped.devices.map(d=>d.edgeId),['electric-E1']);assert.equal(tripped.ties.length,0);
 assert.equal(at(30100).devices.length,0,'re-closed once the faulted span is isolated');assert.equal(at(30100).ties.length,0);
 const fed=at(31000);assert.deepEqual(fed.ties.map(t=>t.edgeId),['electric-E3104']);assert.notEqual(fed.key,tripped.key);assert.equal(at(32000).key,fed.key);
 const both=at(35000);assert.deepEqual(both.valves.map(v=>v.id),['WV-1','WV-2','WV-3']);assert.deepEqual(both.edges.map(e=>e.utility+':'+e.edgeId),['water:water-E1','water:water-E2','water:water-E11']);assert.equal(both.ties.length,1);
 assert.equal(at(37223.6).ties.length,0,'the tie opens again at the repair');assert.equal(at(44999).valves.length,3);assert.equal(at(45000).valves.length,0);
 assert.deepEqual(at(50000).devices.map(d=>d.edgeId),['electric-E9'],'a fuse on the faulted span stays open until restored');
});

test('legend rows name what is switched now',()=>{
 const iv=switchingIntervals(timeline());
 assert.deepEqual(switchingRows(switchingAt(iv,28000)),[]);
 assert.deepEqual(switchingRows(switchingAt(iv,29000)).map(r=>[r.label,r.count,r.color]),[['recloser open · tripped',1,SWITCH_COLORS.device]]);
 assert.deepEqual(switchingRows(switchingAt(iv,35000)).map(r=>[r.label,r.count,r.shape]),[['valve closed · section isolated',3,'ring'],['tie closed · back-feed',1,'line']]);
 assert.deepEqual(switchingRows(null),[]);
});

test('switching marks redraw the switched edges and ring the devices, with their layers',()=>{
 const V=(x,z)=>new THREE.Vector3(x,1,z),path=(id,x)=>({edge:{id},pieces:[{a:V(x,0),b:V(x,10),len:10},{a:V(x,10),b:V(x,20),len:10}]});
 const pathData={electric:['electric-E1','electric-E3104','electric-E75','electric-E9'].map((id,i)=>path(id,i*10)),water:['water-E1','water-E2','water-E11'].map((id,i)=>path(id,100+i*10))};
 const town={networks:{electric:{nodes:[{id:'J-1',x:0,z:0,parentEdgeId:'electric-E1'}],equipment:[{id:'RCL-1',kind:'recloser',nodeId:'J-1',x:1,z:2},{id:'TIE-1',kind:'tie_switch',edgeId:'electric-E3104',x:3,z:4},{id:'POLE-1',kind:'pole',edgeId:'electric-E75',x:5,z:6}]},water:{nodes:[],equipment:[{id:'WV-1',kind:'valve',edgeId:'water-E1',x:7,z:8},{id:'WV-2',kind:'valve',edgeId:'water-E2',x:9,z:10},{id:'HYD-1',kind:'hydrant',edgeId:'water-E2',x:0,z:0}]},gas:{nodes:[],equipment:[]}}};
 const root=new THREE.Group(),marks=new SwitchingMarks(root,town,pathData,()=>0),ops={...timeline(),time:29000};
 marks.setLayers({electric:true,water:false,gas:false});marks.update(ops);
 assert.equal(marks.overlay.count,2,'the tripped recloser\'s edge (two pieces)');assert.equal(marks.ringCount,1);assert.deepEqual([marks.spots[0][0].x,marks.spots[0][0].z],[1,2],'ringed at the recloser');
 ops.time=35000;marks.update(ops);assert.equal(marks.overlay.count,2,'tie edge; the water isolation waits for its layer');assert.deepEqual([marks.spots[0][0].x,marks.spots[0][0].z],[3,4]);
 marks.setLayers({electric:true,water:true});assert.equal(marks.overlay.count,8);assert.equal(marks.ringCount,3,'two valves listed by the engine plus the tie (WV-3 has no position)');
 ops.time=50000;marks.update(ops);assert.equal(marks.ringCount,1);assert.deepEqual([marks.spots[0][0].x,marks.spots[0][0].z],[30,15],'no equipment entry: the middle of the edge');ops.time=28000;marks.update(ops);assert.equal(marks.overlay.count,0);assert.equal(marks.ringCount,0);
 marks.zoom(3000);assert.equal(marks.scale,6);
});

// Generator 0.9.0: the crew opens real sectionalising switches and may close several ties (Ayr's F1-02 trunk pole).
test('sectionalised isolation: opened switches until they close, every tie, and a recloser the engine left open',()=>{
 const tl={incidents:[
  {id:'INC-1',utility:'electric',edgeId:'electric-E289',createdAt:28800,isolatedAt:30075,restoredAt:37275,device:{edgeId:'electric-E2',kind:'recloser'},isolation:{method:'switches',upstream:{id:'SW-1',edgeId:'electric-E287',kind:'sectionalising_switch'},downstream:[{id:'SW-2',edgeId:'electric-E304',kind:'sectionalising_switch'}],deviceReclosed:true},
   tie:{edgeId:'electric-E3108',closedAt:30435,openedAt:37275},ties:[{edgeId:'electric-E3108',closedAt:30435,openedAt:37275},{edgeId:'electric-E3106',closedAt:30795,openedAt:37275}]},
  {id:'INC-2',utility:'electric',edgeId:'electric-E10',createdAt:40000,isolatedAt:41000,restoredAt:45000,device:{edgeId:'electric-E1',kind:'recloser'},isolation:{method:'switches',upstream:{id:'SW-9',edgeId:'electric-E1',kind:'recloser'},downstream:[{id:'SW-3',edgeId:'electric-E12',kind:'sectionalising_switch'}],deviceReclosed:false}}],
 events:[
  ev(28800,'protection.operated','INC-1',{incidentId:'INC-1',edgeId:'electric-E2',kind:'recloser'}),
  ev(30075,'fault.isolated','INC-1',{reclosedDeviceEdgeId:'electric-E2'}),
  ev(30075,'switch.opened','INC-1',{incidentId:'INC-1',id:'SW-1',edgeId:'electric-E287',kind:'sectionalising_switch'}),
  ev(30075,'switch.opened','INC-1',{incidentId:'INC-1',id:'SW-2',edgeId:'electric-E304',kind:'sectionalising_switch'}),
  ev(37275,'switch.closed','INC-1',{incidentId:'INC-1',id:'SW-1',edgeId:'electric-E287',kind:'sectionalising_switch'}),
  ev(37275,'switch.closed','INC-1',{incidentId:'INC-1',id:'SW-2',edgeId:'electric-E304',kind:'sectionalising_switch'}),
  ev(40000,'protection.operated','INC-2',{incidentId:'INC-2',edgeId:'electric-E1',kind:'recloser'}),
  ev(41000,'fault.isolated','INC-2',{reclosedDeviceEdgeId:null})]};
 const iv=switchingIntervals(tl),at=t=>switchingAt(iv,t);
 assert.deepEqual(iv.filter(i=>i.type==='tie').map(i=>[i.edgeId,i.from,i.to]),[['electric-E3108',30435,37275],['electric-E3106',30795,37275]],'every tie, not just the first');
 assert.deepEqual(iv.filter(i=>i.type==='switch'&&i.incidentId==='INC-1').map(i=>[i.id,i.from,i.to]),[['SW-1',30075,37275],['SW-2',30075,37275]]);
 assert.deepEqual(at(31000).switches.map(x=>x.id),['SW-1','SW-2']);assert.equal(at(31000).ties.length,2);assert.equal(at(31000).devices.length,0,'re-closed at isolation');
 assert.deepEqual(at(37300).switches,[]);
 // No switch events: the incident's isolation block stands in, from isolation to restoration.
 assert.deepEqual(iv.filter(i=>i.incidentId==='INC-2'&&i.type==='switch').map(i=>[i.id,i.from,i.to]),[['SW-9',41000,45000],['SW-3',41000,45000]]);
 const dev=iv.find(i=>i.incidentId==='INC-2'&&i.type==='device');assert.equal(dev.to,45000,'a recloser the engine did not re-close stays open until restoration');
 assert.ok(at(31000).key.includes('w:electric-E287'));
 assert.deepEqual(switchingRows(at(31000)).map(r=>r.label),['tie closed · back-feed','switch open · section isolated']);
});
