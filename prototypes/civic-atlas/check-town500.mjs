// Retained acceptance evidence for the fully illustrated Fairhaven world.
// Start the --town500 server and finish installing all registered template assets
// before running; this check deliberately fails on partial/native fallback.
// PLAYWRIGHT_MODULE=/path/to/playwright-core/index.mjs node prototypes/civic-atlas/check-town500.mjs
import assert from 'node:assert/strict';
import {mkdir,rm,writeFile} from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||new URL('../../out/civic-atlas/browser/node_modules/playwright-core/index.mjs',import.meta.url).href);
const base=process.env.ATLAS_URL||'http://127.0.0.1:8041';
const output=process.env.ATLAS_REVIEW_OUTPUT||'out/civic-atlas/review-town500';
await mkdir(output,{recursive:true});
await Promise.all(['checks.json','failure.json','failure.png'].map(name=>rm(`${output}/${name}`,{force:true})));
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage','--enable-unsafe-swiftshader','--no-proxy-server']});
const errors=[],screenshots=[],mousePicks=[],registration=[],tourChecks=[];
let page;
try{
 page=await browser.newPage({viewport:{width:1600,height:1000}});
 page.on('pageerror',e=>errors.push(e.message));
 page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
 const bootstrap=async()=>{const response=await page.request.get(base+'/atlas/api/bootstrap');assert.equal(response.status(),200);return response.json();};
 const before=await bootstrap(),town=before.snapshot,design=town.atlasDesign;
 assert.equal(town.homes,500);assert.equal(town.count,525);assert.equal(town.premises.length,525);
 assert.match(design.version,/^civic-atlas-town500\//);assert.equal(design.blocks.length,58);
 const templateIds=[...new Set(design.blocks.map(b=>b.templateId))];assert.equal(templateIds.length,12);
 const residentialTemplates=[...new Set(design.blocks.filter(b=>b.kind==='residential').map(b=>b.templateId))];assert.equal(residentialTemplates.length,4);
 const byId=new Map(town.premises.map(p=>[p.id,p]));
 const districts=design.districts||[];
 const opening=districts.find(d=>/main street/i.test(d.name));assert.ok(opening,'saved Main Street district exists');
 await page.goto(base+'/?art=blocks&place='+encodeURIComponent('district:'+opening.id)+'#map');
 await page.waitForFunction(()=>document.body.dataset.ready==='true'||document.querySelector('#retry')?.hidden===false,null,{timeout:180000});
 assert.equal(await page.evaluate(()=>document.body.dataset.ready),'true',await page.locator('#boot-message').textContent());
 const diagnostics=()=>page.evaluate(()=>window.atlasDiagnostics());
 const frame=async()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 const shot=async name=>{await frame();const file=`${output}/${name}.png`;await page.screenshot({path:file,animations:'disabled'});screenshots.push(file);};
 const initial=await diagnostics();
 assert.equal(initial.projection,'orthographic');assert.equal(initial.artwork.enabled,true);assert.equal(initial.artwork.count,58);
 assert.equal(initial.artwork.totalBlocks,58);assert.equal(initial.artwork.fallbackCount,0);
 assert.equal(initial.artwork.templates.length,12);assert.ok(initial.artwork.templates.every(t=>t.ready));
 assert.deepEqual(new Set(initial.artwork.templates.map(t=>t.id)),new Set(templateIds));
 assert.match(await page.locator('#legend-text').textContent(),/Main Street/);
 await shot('main-street-1600');console.log('CHECK: 500 homes, 525 premises, 12 ready templates and 58 active placements.');

 // Compare every translated placement with the exact physical registration used
 // by its installed artwork. Solar, pool, footprint, frontage and terrain are
 // all included; a matching PNG filename alone is not sufficient evidence.
 for(const templateId of templateIds){
  const response=await page.request.get(`${base}/assets/civic-template-${templateId}.json`);assert.equal(response.status(),200,templateId);
  const metadata=await response.json();assert.equal(metadata.templateId,templateId);
  const members=design.blocks.filter(b=>b.templateId===templateId);
  const signatures=await page.evaluate(async({town,members})=>{
   const {templateSourceSignature}=await import('/map-town-plates.js');
   return members.map(block=>({id:block.id,signature:templateSourceSignature(town,block)}));
  },{town,members});
  for(const record of signatures)assert.equal(record.signature,metadata.signature,`${templateId}: ${record.id} physical registration`);
  const slots=JSON.parse(metadata.signature).slots;
  for(const block of members)for(let i=0;i<block.premiseIds.length;i++){
   const home=byId.get(block.premiseIds[i]),slot=slots[i];assert.equal(slot.solar,Boolean(home.solar));assert.equal(slot.hasPool,Boolean(home.hasPool));
   if(home.hasPool){
    const pool=home.poolPolygon?.map(p=>({x:p.x-block.center.x,z:p.z-block.center.z}))||design.blockTemplates[templateId].slots[i].poolPolygon;
    assert.ok(Array.isArray(pool)&&pool.length>=3,'recorded pool geometry exists in premise or source template');
    assert.ok(Array.isArray(slot.poolPolygon)&&slot.poolPolygon.length>=3,'artwork registration contains the recorded pool');
    const vertices=points=>points.map(p=>[Number(p.x.toFixed(4)),Number(p.z.toFixed(4))]).sort((a,b)=>a[0]-b[0]||a[1]-b[1]);
    assert.deepEqual(vertices(slot.poolPolygon),vertices(pool),'registered pool matches the source geometry, independent of winding');
   }
   if(home.solar)assert.ok(home.solarKW>0);
  }
  registration.push({templateId,placements:members.length,solarSlots:slots.filter(s=>s.solar).length,poolSlots:slots.filter(s=>s.hasPool).length});
 }
 assert.equal(registration.reduce((n,t)=>n+t.placements,0),58);
 assert.ok(registration.some(t=>t.solarSlots>0)&&registration.some(t=>t.poolSlots>0));
 console.log('CHECK: every template placement matches saved physical geometry and solar/pool conditions.');

 const visit=async id=>{await page.locator('#place-tour').selectOption(id);await frame();tourChecks.push(id);};
 const clickRoof=async(home,block)=>{
  await visit('block:'+block.id);
  const point=await page.evaluate(async home=>{
   const THREE=await import('/viewer/vendor/three.module.js'),d=window.atlasDiagnostics(),camera=new THREE.OrthographicCamera(...d.frustum,.5,100000);
   camera.position.fromArray(d.camera);camera.lookAt(new THREE.Vector3(...d.target));camera.zoom=d.cameraZoom||1;camera.updateProjectionMatrix();camera.updateMatrixWorld();
   const p=new THREE.Vector3(home.x,home.elevationM+home.height*.65,home.z).project(camera),r=document.querySelector('#map-canvas canvas').getBoundingClientRect();
   return{x:r.x+(p.x+1)*r.width/2,y:r.y+(1-p.y)*r.height/2,inside:Math.abs(p.x)<.98&&Math.abs(p.y)<.98};
  },home);
  assert.ok(point.inside,home.id+' roof lies inside framed block');
  // A real pointer event exercises rendered roof picking, not search, DOM
  // property buttons, or a direct call into the map's selection function.
  await page.mouse.click(point.x,point.y);
  await page.waitForFunction(id=>window.atlasDiagnostics().selectedId===id,home.id,{timeout:10000});
  await page.waitForFunction(({id,address})=>document.querySelector('#inspector-content')?.textContent.includes(address)&&document.querySelector('#inspector-content')?.textContent.includes(id)&&Boolean(document.querySelector('#close-inspector')),{id:home.id,address:home.address},{timeout:15000});
  mousePicks.push({id:home.id,blockId:block.id,templateId:block.templateId,buildingType:home.buildingType,solar:Boolean(home.solar),pool:Boolean(home.hasPool),point:{x:point.x,y:point.y}});
 };
 for(const templateId of residentialTemplates){
  const blocks=design.blocks.filter(b=>b.templateId===templateId);assert.ok(blocks.length>=2);
  const translated=[blocks[0],blocks.at(-1)];assert.notDeepEqual(translated[0].center,translated[1].center);
  for(let instance=0;instance<translated.length;instance++){
   const block=translated[instance],homes=block.premiseIds.map(id=>byId.get(id));
   const feature=homes.find(p=>p.solar||p.hasPool)||homes[2];
   const plain=homes.find(p=>!p.solar&&!p.hasPool&&p.id!==feature.id);assert.ok(plain);
   await clickRoof(feature,block);await shot(`${templateId}-${instance+1}-selected`);
   await clickRoof(plain,block);
  }
  console.log('CHECK: real roof picking in two translated instances of '+templateId);
 }
 for(const type of ['school','church','industrial','storefront']){
  const home=town.premises.find(p=>p.buildingType===type);assert.ok(home,type+' saved premise exists');
  const block=design.blocks.find(b=>b.premiseIds.includes(home.id));assert.ok(block,type+' registered block exists');
  await clickRoof(home,block);await shot(`${type}-selected`);
 }
 assert.equal(new Set(mousePicks.map(p=>p.id)).size,20,'20 distinct real mouse roof selections');
 assert.ok(mousePicks.some(p=>p.solar)&&mousePicks.some(p=>p.pool)&&mousePicks.some(p=>!p.solar&&!p.pool));

 // Search and source-driven destinations remain independent of artwork.
 const searchHome=town.premises.find(p=>p.buildingType==='church');
 await page.locator('#map-search').fill('church');await page.locator('#search-results button').first().waitFor();
 await page.locator('#map-search').press('Enter');await page.waitForFunction(id=>window.atlasDiagnostics().selectedId===id,searchHome.id);
 for(const district of districts){await visit('district:'+district.id);assert.ok((await page.locator('#legend-text').textContent()).includes(district.name));}
 const field=design.fields[0];await visit('field:'+field.id);assert.match(await page.locator('#legend-text').textContent(),/no farm production/);
 await shot('countryside-land-use');
 const sample=design.blocks.find(b=>b.kind==='residential');await visit('block:'+sample.id);
 for(const layer of ['water','electric','gas']){
  await page.locator(`[data-layer=${layer}]`).click();assert.equal(await page.locator(`[data-layer=${layer}]`).evaluate(el=>el.classList.contains('active')),true);
  assert.match(await page.locator('#legend-text').textContent(),/topology, not live flow/);await shot(`${layer}-network`);
 }
 await page.locator('[data-layer=town]').click();
 const framed=await diagnostics();await page.locator('#map-art-toggle').click();
 const native=await diagnostics();assert.equal(native.artwork.enabled,false);assert.equal(native.artwork.count,0);assert.deepEqual(native.camera,framed.camera);assert.deepEqual(native.target,framed.target);
 await shot('native-same-camera');await page.locator('#map-art-toggle').click();assert.equal((await diagnostics()).artwork.count,58);await shot('illustrated-same-camera');
 const canvas=page.locator('#map-canvas canvas'),rect=await canvas.boundingBox(),x=rect.x+rect.width*.48,y=rect.y+rect.height*.54;
 const prePan=await diagnostics();await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x+70,y+25,{steps:6});await page.mouse.up();await frame();
 const postPan=await diagnostics();assert.notDeepEqual(postPan.target,prePan.target);
 const direction=d=>d.camera.map((v,i)=>v-d.target[i]);assert.ok(direction(prePan).every((v,i)=>Math.abs(v-direction(postPan)[i])<1e-6),'pan preserves fixed angle');
 await page.mouse.wheel(0,-120);await frame();const zoomed=await diagnostics();assert.ok(zoomed.frustum[2]-zoomed.frustum[3]<postPan.frustum[2]-postPan.frustum[3]);
 await page.locator('#zoom-out').click();await frame();assert.ok((await diagnostics()).frustum[2]-(await diagnostics()).frustum[3]>zoomed.frustum[2]-zoomed.frustum[3]);

 // Home counts, source names and presentation at both evaluation widths.
 for(const width of [1600,1024]){
  await page.setViewportSize({width,height:width===1600?1000:850});
  for(const view of ['welcome','overview','configure','map']){
   await page.evaluate(view=>{location.hash=view;},view);await page.waitForFunction(view=>!document.querySelector('#'+view+'-page').hidden,view);
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${view}: no overflow at ${width}`);
   if(view==='map')await visit('district:'+opening.id);
   await shot(`${view}-${width}`);
  }
 }
 const occupants=town.premises.filter(p=>p.premiseType==='residential'&&p.occupied).reduce((n,p)=>n+p.occupants,0);
 assert.equal(await page.locator('#hero-homes').textContent(),'500');assert.equal(await page.locator('#hero-people').textContent(),occupants.toLocaleString('en'));
 assert.equal(await page.locator('.header-world').textContent(),design.name);
 assert.deepEqual(await bootstrap(),before,'presentation, selection, layers and navigation leave the saved snapshot and state unchanged');
 assert.deepEqual(errors,[]);
 const result={passed:true,world:{id:town.id,name:design.name,homes:town.homes,premises:town.count,occupiedResidents:occupants},artwork:(await diagnostics()).artwork,registration,mousePicks,tourChecks,screenshots,sourceUnchanged:true,consoleErrors:errors};
 await writeFile(`${output}/checks.json`,JSON.stringify(result,null,2)+'\n');
 console.log('PASS: Fairhaven 500 homes / 525 premises; 12 source-matched templates / 58 active blocks; 20 real roof picks across translated homes and civic/commercial records; source solar/pools; tours, search, networks, pan, zoom, native comparison; 1600/1024 layouts; saved world unchanged.');
}catch(error){
 if(page){await page.screenshot({path:`${output}/failure.png`}).catch(()=>{});await writeFile(`${output}/failure.json`,JSON.stringify({passed:false,error:error.stack,errors,diagnostics:await page.evaluate(()=>window.atlasDiagnostics?.()).catch(()=>null),mousePicks,registration,tourChecks},null,2)+'\n');}
 throw error;
}finally{await browser.close();}
