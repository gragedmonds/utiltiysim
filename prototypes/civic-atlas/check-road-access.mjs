import assert from 'node:assert/strict';
import {frontageAccessQuad,pavementQuad,convexOverlap} from './web/map-road-access.js';

const road={points:[{x:-100,z:0},{x:100,z:0}],width:10};
const pavement=[pavementQuad(...road.points,road.width)];
for(const x of[0,15,-15])for(const side of[-1,1]){
  const source=[{x:0,z:0},{x,z:20*side}],before=JSON.stringify(source);
  const quad=frontageAccessQuad(source,road,3.2,pavement);
  assert(quad,'A clear saved approach should remain visible.');
  assert(Math.min(quad[0].z*side,quad[1].z*side)>=5-1e-8,'The full mouth must remain outside pavement.');
  for(const corner of quad.slice(0,2))assert(Math.abs(corner.z*side-road.width/2)<1e-8,'Both mouth corners must meet the curb, with no triangular gap on an oblique approach.');
  assert(!convexOverlap(quad,pavement[0]));
  assert.equal(JSON.stringify(source),before,'Clipping must not alter source access.');
}
// Rotate an oblique approach to ensure the flush-mouth rule follows the actual
// road normal rather than assuming an east-west road.
const angle=.63,rotate=p=>({x:p.x*Math.cos(angle)-p.z*Math.sin(angle),z:p.x*Math.sin(angle)+p.z*Math.cos(angle)});
const rotatedRoad={...road,points:road.points.map(rotate)},rotatedPavement=[pavementQuad(...rotatedRoad.points,road.width)];
const rotatedQuad=frontageAccessQuad([{x:0,z:0},{x:15,z:20}].map(rotate),rotatedRoad,3.2,rotatedPavement);
assert(rotatedQuad);for(const corner of rotatedQuad.slice(0,2))assert(Math.abs(-corner.x*Math.sin(angle)+corner.z*Math.cos(angle)-road.width/2)<1e-8,'Rotated mouth corners must both meet the curb.');
assert(!convexOverlap(rotatedQuad,rotatedPavement[0]));
assert.equal(frontageAccessQuad([{x:0,z:0},{x:0,z:4}],road,3.2,pavement),null,'A building approach inside the road cannot be dressed as valid.');
assert.equal(frontageAccessQuad([{x:0,z:0},{x:0,z:20}],road,3.2,[...pavement,pavementQuad({x:-20,z:12},{x:20,z:12},6)]),null,'Do not draw a driveway crossing another street.');
assert.equal(frontageAccessQuad([{x:0,z:0},{x:0,z:20}],null,3.2,pavement),null,'Missing frontage needs an explicit fallback.');
console.log('PASS: seven perpendicular/oblique/rotated approaches with both mouth corners flush to curb, both road sides, road crossing rejection, missing frontage, immutable source.');

// Optional integration check exercises the final visible mesh, after town-center
// replacement. Geometry-only checks previously missed a second rendering pass
// that discarded the clipped driveway and restored a centerline ribbon.
if(process.env.ATLAS_ACCESS_BROWSER==='1'){
  const {mkdir,writeFile}=await import('node:fs/promises');
  const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||new URL('../../out/civic-atlas/browser/node_modules/playwright-core/index.mjs',import.meta.url).href);
  const base=process.env.ATLAS_URL||'http://127.0.0.1:8040',out=process.env.ATLAS_REVIEW_OUTPUT||'out/civic-atlas/review-road-access';
  await mkdir(out,{recursive:true});
  const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage','--enable-unsafe-swiftshader','--no-proxy-server']});
  try{
    const page=await browser.newPage({viewport:{width:1600,height:1000}}),errors=[];page.on('pageerror',error=>errors.push(error.message));
    const before=await(await page.request.get(base+'/atlas/api/bootstrap')).json();
    await page.goto(base+'/block-study.html');await page.waitForFunction(()=>document.body.dataset.ready==='true',null,{timeout:120000});
    const result=await page.evaluate(async()=>{
      const {convexOverlap,pavementQuad}=await import('./map-road-access.js'),{streetWidth}=await import('/viewer/roads.js');
      const {map,town}=window.blockStudy,scene=map.scene,mesh=scene.root.children.find(m=>m.userData.atlasAccessRanges);
      const clipped=scene.townDressing.meshes.find(m=>m.userData.atlasAccess),pos=mesh.geometry.attributes.position;
      const roads=town.roads.flatMap(r=>r.points.slice(1).map((b,i)=>pavementQuad(r.points[i],b,streetWidth(r))).filter(Boolean));
      const ranges=mesh.userData.atlasAccessRanges.map(range=>{
        const triangles=[];for(let i=range.firstVertex;i<range.firstVertex+range.vertexCount;i+=3)triangles.push([0,1,2].map(j=>({x:pos.getX(i+j),z:pos.getZ(i+j)})));
        const mouth=clipped.userData.atlasAccess.quads.find(q=>q.premiseId===range.premiseId).polygon.slice(0,2);
        return {...range,overlap:triangles.some(t=>roads.some(r=>convexOverlap(t,r))),mouthRetained:mouth.every(p=>triangles.flat().some(q=>Math.hypot(p.x-q.x,p.z-q.z)<.0001))};
      });
      return {visible:mesh.visible,legacyVisible:clipped.visible,accepted:clipped.userData.atlasAccess.accepted,omitted:clipped.userData.atlasAccess.omitted,ranges};
    });
    assert.equal(result.visible,true);assert.equal(result.legacyVisible,false);assert.equal(result.ranges.length,3);
    for(const range of result.ranges){assert.equal(range.overlap,false,range.premiseId+' visible access overlaps a road');assert.equal(range.mouthRetained,true,range.premiseId+' lost its flush curb mouth');}
    await page.goto(base+'/#map');await page.waitForFunction(()=>document.body.dataset.ready==='true',null,{timeout:120000});
    for(const place of['school','depot']){
      await page.locator('#place-tour').selectOption(place);await page.waitForFunction(()=>document.querySelector('#inspector-content').textContent.includes('Physical property'));
      await page.screenshot({path:`${out}/${place}-access-art.png`});
      await page.locator('#map-art-toggle').click();await page.screenshot({path:`${out}/${place}-access-native.png`});await page.locator('#map-art-toggle').click();
    }
    assert.deepEqual(await(await page.request.get(base+'/atlas/api/bootstrap')).json(),before);assert.deepEqual(errors,[]);
    await writeFile(`${out}/access-checks.json`,JSON.stringify({...result,sourceUnchanged:true,errors},null,2)+'\n');
    console.log('PASS: final visible school/depot/pump access has no road overlap, keeps both curb corners, and survives native/artwork comparison without source mutation.');
  }finally{await browser.close();}
}
