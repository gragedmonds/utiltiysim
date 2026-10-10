import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||new URL('../../out/civic-atlas/browser/node_modules/playwright-core/index.mjs',import.meta.url).href);
const base=process.env.ATLAS_URL||'http://127.0.0.1:8040',out=process.env.ATLAS_REVIEW_OUTPUT||'out/civic-atlas/review-city-places';
await mkdir(out,{recursive:true});
const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage','--enable-unsafe-swiftshader','--no-proxy-server']});
try{
 const page=await browser.newPage({viewport:{width:1600,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error'&&/THREE|WebGL|shader/i.test(m.text()))errors.push(m.text());});
 const before=await(await page.request.get(base+'/atlas/api/bootstrap')).json();
 await page.goto(base+'/#map');await page.waitForFunction(()=>document.body.dataset.ready==='true'||document.querySelector('#retry')?.hidden===false,null,{timeout:120000});
 assert.equal(await page.evaluate(()=>document.body.dataset.ready),'true',await page.locator('#boot-message').textContent());
 const diagnostics=()=>page.evaluate(()=>window.atlasDiagnostics());
 assert.equal((await diagnostics()).artwork.enabled,true);
 assert.ok((await diagnostics()).grass.surfaces>=3,'shared turf shader covers terrain, parks and parcels');
 assert.equal((await diagnostics()).artwork.count,6);
 for(const place of['park','school','depot','shops','homes','river']){
  await page.locator('#place-tour').selectOption(place);
  if(['school','depot','shops','homes'].includes(place))await page.waitForFunction(()=>document.querySelector('#inspector-content').textContent.includes('Physical property'));
  await page.screenshot({path:`${out}/map-${place}.png`});
  if(['school','depot'].includes(place)){
   const type=place==='depot'?'depot':'school',home=before.snapshot.premises.find(p=>p.buildingType===type);
   // Clear selection, then use a real mouse hit on the source building center.
   await page.locator('#close-inspector').click();
   const point=await page.evaluate(async home=>{
    const THREE=await import('/viewer/vendor/three.module.js'),d=window.atlasDiagnostics(),c=new THREE.OrthographicCamera(...d.frustum,.5,100000);
    c.position.fromArray(d.camera);c.lookAt(new THREE.Vector3(...d.target));c.updateMatrixWorld();
    const p=new THREE.Vector3(home.x,home.elevationM+home.height*.45,home.z).project(c),r=document.querySelector('#map-canvas canvas').getBoundingClientRect();return{x:r.x+(p.x+1)*r.width/2,y:r.y+(1-p.y)*r.height/2};
   },home);
   await page.mouse.click(point.x,point.y);await page.waitForFunction(id=>window.atlasDiagnostics().selectedId===id,home.id);
   assert.equal((await diagnostics()).selectedId,home.id);
  }
 }
 // One painted block must still resolve to three distinct physical properties.
 const blockIds=['P-00101','P-00102','P-00133'];
 await page.locator('#place-tour').selectOption('school-block');
 assert.equal((await diagnostics()).selectedId,undefined);
 await page.screenshot({path:`${out}/map-school-block.png`});
 for(const id of blockIds){
  await page.locator('#place-tour').selectOption('school-block');
  const home=before.snapshot.premises.find(p=>p.id===id);
  const point=await page.evaluate(async home=>{
   const THREE=await import('/viewer/vendor/three.module.js'),d=window.atlasDiagnostics(),c=new THREE.OrthographicCamera(...d.frustum,.5,100000);
   c.position.fromArray(d.camera);c.lookAt(new THREE.Vector3(...d.target));c.updateMatrixWorld();
   const p=new THREE.Vector3(home.x,home.elevationM+home.height*.45,home.z).project(c),r=document.querySelector('#map-canvas canvas').getBoundingClientRect();
   return{x:r.x+(p.x+1)*r.width/2,y:r.y+(1-p.y)*r.height/2};
  },home);
  await page.mouse.click(point.x,point.y);
  await page.waitForFunction(id=>window.atlasDiagnostics().selectedId===id,id);
  await page.waitForFunction(address=>document.querySelector('#inspector-content').textContent.includes(address),home.address);
 }
 await page.locator('#place-tour').selectOption('school-block');
 const blockFrame=await diagnostics();
 await page.locator('[data-layer=water]').click();
 await page.screenshot({path:`${out}/map-school-block-water.png`});
 await page.locator('[data-layer=town]').click();await page.locator('#map-art-toggle').click();
 assert.deepEqual((await diagnostics()).camera,blockFrame.camera);
 await page.screenshot({path:`${out}/map-school-block-native.png`});await page.locator('#map-art-toggle').click();
 await page.locator('#place-tour').selectOption('park');
 const framed=await diagnostics();await page.locator('[data-layer=water]').click();
 await page.screenshot({path:`${out}/map-park-water.png`});
 await page.locator('#map-art-toggle').click();assert.equal((await diagnostics()).artwork.enabled,false);assert.deepEqual((await diagnostics()).camera,framed.camera);
 await page.screenshot({path:`${out}/map-park-native.png`});await page.locator('#map-art-toggle').click();await page.locator('[data-layer=town]').click();
 await page.locator('#fit-map').click();await page.screenshot({path:`${out}/map-satellite-overview.png`});
 await page.locator('.sidebar [data-page="city-design"]').click();assert.equal(await page.locator('.city-study:visible').count(),8);
 await page.locator('[data-city-filter=homes]').click();assert.equal(await page.locator('.city-study:visible').count(),3);
 assert.equal(await page.locator('#city-study-apartments [data-city-example]').count(),0,'no invented apartment in saved world');
 await page.locator('[data-city-filter=all]').click();
 for(const width of[1600,1024]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:`${out}/city-design-${width}.png`,fullPage:true});}
 await page.locator('#city-study-park [data-city-example]').click();assert.match(await page.locator('#legend-text').textContent(),/Maple Park/);assert.equal((await diagnostics()).selectedId,undefined);
 await page.screenshot({path:`${out}/map-park-1024.png`});
 const after=await(await page.request.get(base+'/atlas/api/bootstrap')).json();assert.deepEqual(after,before,'art, tours and study navigation do not alter the saved world');assert.deepEqual(errors,[]);
 await writeFile(`${out}/city-checks.json`,JSON.stringify({passed:true,sourceUnchanged:true,artwork:(await diagnostics()).artwork,realMousePicks:['school','depot',...blockIds],consoleErrors:errors},null,2)+'\n');
 console.log('PASS: six map illustrations, civic property mouse picking, park tours, utility overlay, A/B camera preservation, study filters, responsive layout, unchanged saved world.');
}finally{await browser.close();}
