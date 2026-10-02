import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {gunzipSync} from 'node:zlib';
import {VIEWS,MATRIX,CAMERA_BEARING,DIAGONAL,STUDY,facingOf,isDiagonal,premiseArt,facilityArt,crewArt,spriteName,topRotation,project,unproject} from '../dist/iso-art.js';

const atlas=JSON.parse(readFileSync(new URL('../dist/iso/atlas.json',import.meta.url)));
const FAMILIES=['brick2','bungalow_hip','solar2','victorian2','bungalow_gable','commercial','cottage','brick_hip2','ranch_hip',...STUDY];
const ALL_VIEWS=[...VIEWS,'top'];
const turns=n=>Array.from({length:n},(_,i)=>-Math.PI+2*Math.PI*i/n);

test('every family, from every camera and facing, has its sprite in the baked atlas',()=>{
 assert.equal(atlas.version,'iso-atlas/1.0');
 for(const family of FAMILIES)for(const view of ALL_VIEWS)for(const facing of turns(32)){const name=spriteName(family,view,facing);assert.ok(atlas.sprites[name],`${name} is missing from iso/atlas.json`);}
 for(const name of ['tree','pole','pad','hydrant'])for(const v of ['iso','top'])assert.ok(atlas.sprites[`${name}.${v}`]);
 for(const [name,[x,y,w,h]] of Object.entries(atlas.sprites)){assert.ok(x>=0&&y>=0&&w>0&&h>0&&x+w<=atlas.size[0]&&y+h<=atlas.size[1],name);assert.equal(x%8,0,name);assert.equal(y%8,0,name);}
});

test('a house faces its street: front point, else the engine angle and side',()=>{
 assert.equal(facingOf({x:0,z:0,front:{x:10,z:0}}),0);
 assert.ok(Math.abs(facingOf({x:0,z:0,front:{x:0,z:-5}})+Math.PI/2)<1e-9); // north, in the east/south frame
 const a=facingOf({x:0,z:0,angle:0,side:1}),b=facingOf({x:0,z:0,angle:0,side:-1});
 assert.ok(Math.abs(Math.abs(a-b)-Math.PI)<1e-9,'the other side of the street faces the other way');
});

test('styles come from engine fields, the same in every browser',()=>{
 const north=-Math.PI/2,ne=-Math.PI/4;
 assert.equal(isDiagonal(north),false);assert.equal(isDiagonal(ne),true);assert.equal(isDiagonal(0.1),false);assert.equal(isDiagonal(Math.PI/4+.3),true);
 assert.equal(premiseArt({buildingType:'industrial'}),'industrial');
 assert.equal(premiseArt({buildingType:'depot'}),'depot');
 assert.equal(premiseArt({buildingType:'pump_house'}),'pump_station');
 assert.equal(premiseArt({buildingType:'storefront',premiseType:'commercial'}),'commercial');
 assert.equal(premiseArt({buildingType:'school'}),'commercial');
 assert.equal(premiseArt({buildingType:'detached',premiseType:'residential',roof:'flat'}),'commercial');
 assert.equal(premiseArt({buildingType:'detached',premiseType:'residential',solar:true,stories:1}),'solar2');
 assert.equal(premiseArt({buildingType:'detached',premiseType:'residential',stories:1,roof:'hip'},north),'bungalow_hip');
 assert.equal(premiseArt({buildingType:'detached',premiseType:'residential',stories:1,roof:'hip'},ne),'ranch_hip');
 assert.equal(premiseArt({buildingType:'detached',premiseType:'residential',stories:1,roof:'gable'},ne),'cottage');
 assert.equal(premiseArt({buildingType:'detached',premiseType:'residential',stories:2,id:'P-1'},ne),'brick_hip2');
 assert.equal(premiseArt({buildingType:'detached',premiseType:'residential',stories:2,era:'pre_1945',uid:'x'},north),'victorian2');
 const h={buildingType:'detached',premiseType:'residential',stories:2,era:'modern',uid:'abc'};assert.equal(premiseArt(h,north),premiseArt({...h},north),'deterministic');
 assert.equal(facilityArt('elevated_tank'),'water_tower');assert.equal(facilityArt('city_gate'),'city_gate');assert.equal(facilityArt('nope'),null);
 assert.deepEqual(['electric','water','gas','meter',undefined].map(crewArt),['bucket_truck','water_truck','gas_truck','meter_van','meter_van']);
});

test('turning the camera shows a building\'s other sides in order',()=>{
 // A west-facing house: the NE camera (at the south-west) sees its front, and each quarter turn moves on a side.
 const banks=VIEWS.map(v=>spriteName('brick2',v,Math.PI).split('.')[1]);
 assert.deepEqual(banks,['ne','se','sw','nw']);
 assert.equal(new Set(banks).size,4);
 const studies=VIEWS.map(v=>spriteName('depot',v,Math.PI).split('.')[1]);
 assert.deepEqual(studies,['front-right','rear-left','rear-right','front-left']);
 for(const f of DIAGONAL){const sides=VIEWS.map(v=>spriteName(f,v,3*Math.PI/4).split('.')[1]);assert.deepEqual(sides,['front','side-a','rear','side-b']);}
 assert.equal(spriteName('brick2','top',1),'brick2.top');assert.equal(spriteName('substation','top',1),'substation.overhead');
 assert.ok(Math.abs(topRotation('brick2',Math.PI/2))<1e-9,'a south-facing roof needs no turn');
});

test('screen projection round-trips, and every camera looks across the town from its own corner',()=>{
 for(const v of [...VIEWS,'top'])for(const [x,z] of [[0,0],[120,-40],[-900,700]]){const [sx,sy]=project(v,x,z),[bx,bz]=unproject(v,sx,sy);assert.ok(Math.abs(bx-x)<1e-6&&Math.abs(bz-z)<1e-6,v);}
 for(const v of VIEWS){const b=CAMERA_BEARING[v],toward=project(v,Math.cos(b),Math.sin(b));assert.ok(toward[1]>0,`${v}: the side nearest the camera is drawn lower on the screen`);}
 assert.deepEqual(MATRIX.top,[1,0,0,1]);
 assert.equal(project('ne',0,0,10)[1],-10,'height lifts a point on screen');
});

test('a real town pack picks a sprite for every premise and facility',()=>{
 const index=JSON.parse(readFileSync(new URL('../../../public/packs/index.json',import.meta.url)));
 const ayr=index.towns.find(t=>t.preset==='ayr');if(!ayr)return;
 const snap=JSON.parse(gunzipSync(readFileSync(new URL(`../../../public/packs/${ayr.files.snapshot.path}`,import.meta.url))));
 const families=new Set();for(const h of snap.premises){const f=premiseArt(h);families.add(f);for(const v of ALL_VIEWS)assert.ok(atlas.sprites[spriteName(f,v,facingOf(h))],h.id);}
 for(const f of snap.facilities)if(!f.premiseId)assert.ok(facilityArt(f.kind),f.kind);
 assert.ok(families.size>=8,`a town mixes its styles (${[...families]})`);
});
