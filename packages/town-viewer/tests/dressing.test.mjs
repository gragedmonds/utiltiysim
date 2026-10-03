import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import * as THREE from '../dist/vendor/three.module.js';
import {createTown,parseStreets} from '../dist/model.js';
import {planDressing,TownDressing,distanceToSegment,DRESSING_LIMITS} from '../dist/town-dressing.js';
import {houseStyle,triangleCount,roofGeometry} from '../dist/lowpoly.js';
import {TownScene} from '../dist/scene.js';
const source=parseStreets(JSON.parse(fs.readFileSync(new URL('../dist/demo-streets.json',import.meta.url))));
test('four roof silhouettes face outward and retain the correct premise when instanced',()=>{
 const homes=['gable','hip','cross','flat'].map((roof,i)=>({id:'P-'+i,roof,x:i*40,z:0,width:10,depth:12,height:6,angle:0,side:1,roofTone:.5,solar:false}));
 const s=Object.create(TownScene.prototype);Object.assign(s,{town:{premises:homes},root:new THREE.Group(),heightAt:()=>0,ray:new THREE.Raycaster(),camera:new THREE.PerspectiveCamera(36,1,.5,1000)});s.drawHouses(s.town);s.root.updateMatrixWorld(true);
 for(let i=0;i<4;i++){assert.equal(houseStyle(homes[i]),i);assert.equal(triangleCount(roofGeometry(i)),[8,8,16,12][i]);s.camera.position.set(i*40+5.3,100,0);s.camera.lookAt(i*40+5.3,0,0);s.camera.updateMatrixWorld(true);s.ray.setFromCamera(new THREE.Vector2(),s.camera);assert.ok(s.ray.intersectObject(s.roofBatches[i]).length,'outward roof eave for '+homes[i].roof);assert.equal(s.houseAt(new THREE.Vector2()).id,homes[i].id);}
});
test('dressing repeats without changing engine records, and civic footprints and trees avoid homes and roads',()=>{
 const town=createTown(source,{seed:'TOWN-042',count:480}),before=JSON.stringify(town),p=planDressing(town,{demo:true});assert.deepEqual(p,planDressing(town,{demo:true}));assert.equal(JSON.stringify(town),before);assert.equal(p.landmarks.length,5);assert.ok(p.landmarks.some(p=>p.kind==='school'));assert.ok(p.landmarks.every(p=>p.access?.length===2));
 const obstacles=[...p.landmarks,...p.trees];
 for(let i=0;i<obstacles.length;i++){const a=obstacles[i];for(const h of town.premises)assert.ok(Math.hypot(a.x-h.x,a.z-h.z)>=a.radius+Math.hypot(h.width+9,h.depth+7)/2);for(const road of town.roads)for(let j=1;j<road.points.length;j++)assert.ok(distanceToSegment(a,road.points[j-1],road.points[j])>=a.radius+8);for(let j=0;j<i;j++)assert.ok(Math.hypot(a.x-obstacles[j].x,a.z-obstacles[j].z)>=a.radius+obstacles[j].radius);assert.ok(a.x-a.radius>town.bounds.minX&&a.x+a.radius<town.bounds.maxX);assert.ok(a.z-a.radius>town.bounds.minZ&&a.z+a.radius<town.bounds.maxZ);}
 assert.equal(planDressing(town).landmarks.length,0,'native snapshots do not get fictional civic customers');
 assert.notDeepEqual(p.trees,planDressing({...town,seed:'other'},{demo:true}).trees);
});
test('10,000-home scenery stays within its shared-instance and triangle budget',()=>{
 const town=createTown(source,{seed:'TOWN-042',count:10000}),root=new THREE.Group(),dressing=new TownDressing(root,town,()=>0,{demo:true}),s=dressing.stats();assert.ok(s.trees<=DRESSING_LIMITS.trees);assert.ok(s.stopSigns<=DRESSING_LIMITS.stops);assert.ok(s.trafficLights<=DRESSING_LIMITS.signals);assert.equal(s.landmarks,16);assert.ok(s.dressingBatches<=12);const withBrowserLabels=s.dressingTriangles+s.stopSigns*2;assert.ok(withBrowserLabels<520000);
 const scene=Object.create(TownScene.prototype);Object.assign(scene,{town,root,heightAt:()=>0});scene.drawHouses(town);const geometry=scene.geometryStats();assert.equal(geometry.houseModels.reduce((a,b)=>a+b,0),10000);assert.ok(geometry.propertyTriangles+withBrowserLabels+61056<1100000);console.log(JSON.stringify({houses:10000,...geometry,...s,sceneryWithBrowserTextTriangles:withBrowserLabels,propertiesPlusSceneryAndMaxDetails:geometry.propertyTriangles+withBrowserLabels+61056}));
 dressing.setVisible(false);assert.equal(dressing.group.visible,false);
});
