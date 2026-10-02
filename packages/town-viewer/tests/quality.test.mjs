import test from 'node:test';
import assert from 'node:assert/strict';
import {chooseQuality,PROFILES} from '../dist/quality.js';
import {TownScene} from '../dist/scene.js';

test('phones and low-memory devices start in lite; the URL or a saved choice wins',()=>{
 const phone={coarse:true,shortSide:390,deviceMemory:8,saved:null},desktop={coarse:false,shortSide:1080,deviceMemory:8,saved:null};
 assert.equal(chooseQuality({...phone,search:''}),'lite');
 assert.equal(chooseQuality({...desktop,search:''}),'full');
 assert.equal(chooseQuality({...desktop,deviceMemory:4,search:''}),'lite','4 GB devices');
 assert.equal(chooseQuality({...phone,coarse:true,shortSide:1024,search:''}),'full','large touch screens (tablets in landscape)');
 assert.equal(chooseQuality({...phone,search:'?quality=full'}),'full');
 assert.equal(chooseQuality({...desktop,search:'?town=ayr&quality=lite'}),'lite');
 assert.equal(chooseQuality({...phone,saved:'full',search:''}),'full');
 assert.equal(chooseQuality({...phone,search:'?quality=bogus'}),'lite');
 assert.ok(!PROFILES.lite.shadows&&!PROFILES.lite.antialias&&!PROFILES.lite.streetscape&&PROFILES.lite.maxPixelRatio<=1.5);
});

test('losing the GPU context drops the scene to lite once',()=>{
 const calls=[],s=Object.create(TownScene.prototype);
 Object.assign(s,{quality:PROFILES.full,renderer:{shadowMap:{enabled:true},setPixelRatio:r=>calls.push(['ratio',r])},
  setDressing:v=>calls.push(['dressing',v]),setHouseDetail:v=>calls.push(['detail',v]),resize:()=>calls.push(['resize'])});
 assert.equal(s.useLite(),true);assert.equal(s.quality.name,'lite');assert.equal(s.renderer.shadowMap.enabled,false);
 assert.deepEqual(calls.map(c=>c[0]),['ratio','dressing','detail','resize']);assert.deepEqual(calls[1],['dressing',false]);assert.deepEqual(calls[2],['detail','simple']);
 assert.equal(s.useLite(),false,'already lite');
});
