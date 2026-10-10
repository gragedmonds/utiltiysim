import assert from 'node:assert/strict';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||new URL('../../out/civic-atlas/browser/node_modules/playwright-core/index.mjs',import.meta.url).href);
const base=process.env.ATLAS_URL||'http://127.0.0.1:8040',out=process.env.ATLAS_REVIEW_OUTPUT||'out/civic-atlas/review-residential';
const names=['orchard-meadow-six','juniper-cedar-six','cedar-pine-eight'];
const samples=await Promise.all(names.map(async name=>JSON.parse(await readFile(new URL(`web/assets/civic-block-${name}.json`,import.meta.url),'utf8'))));
await mkdir(out,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage','--enable-unsafe-swiftshader','--no-proxy-server']});
try{
 const page=await browser.newPage({viewport:{width:1600,height:1000}}),errors=[],hits=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('console',m=>{if(m.type()==='error'&&/THREE|WebGL|shader/i.test(m.text()))errors.push(m.text());});
 const before=await(await page.request.get(base+'/atlas/api/bootstrap')).json();
 await page.goto(base+'/?place='+names[0]+'#map');
 await page.waitForFunction(()=>document.body.dataset.ready==='true',null,{timeout:120000});
 const diagnostics=()=>page.evaluate(()=>window.atlasDiagnostics());
 assert.equal((await diagnostics()).artwork.count,9);
 assert.equal((await diagnostics()).artwork.enabled,true);
 assert.match(await page.locator('#legend-text').textContent(),/Orchard & Meadow/,'deep link opens the requested neighborhood');
 for(const sample of samples){
  const block=sample.block;
  await page.locator('#place-tour').selectOption(block.id);
  assert.equal((await diagnostics()).selectedId,undefined);
  assert.ok((await page.locator('#legend-text').textContent()).includes(block.label));
  await page.screenshot({path:`${out}/${block.id}.png`});
  for(const id of block.ids){
   await page.locator('#place-tour').selectOption(block.id);
   const home=before.snapshot.premises.find(p=>p.id===id),anchor=sample.anchors.find(p=>p.id===id);
   assert.equal(anchor.solar,home.solar);assert.equal(anchor.hasPool,home.hasPool);
   const point=await page.evaluate(async home=>{
    const THREE=await import('/viewer/vendor/three.module.js'),d=window.atlasDiagnostics(),c=new THREE.OrthographicCamera(...d.frustum,.5,100000);
    c.position.fromArray(d.camera);c.lookAt(new THREE.Vector3(...d.target));c.updateMatrixWorld();
    const p=new THREE.Vector3(home.x,home.elevationM+home.height*.45,home.z).project(c),r=document.querySelector('#map-canvas canvas').getBoundingClientRect();
    return{x:r.x+(p.x+1)*r.width/2,y:r.y+(1-p.y)*r.height/2};
   },home);
   await page.mouse.click(point.x,point.y);
   await page.waitForFunction(id=>window.atlasDiagnostics().selectedId===id,id);
   await page.waitForFunction(address=>document.querySelector('#inspector-content').textContent.includes(address),home.address);
   hits.push(id);
  }
  const home=before.snapshot.premises.find(p=>p.id===block.ids[0]);
  await page.locator('#map-search').fill(home.address);
  await page.locator('#search-results button').first().waitFor();
  await page.locator('#map-search').press('Enter');
  await page.waitForFunction(id=>window.atlasDiagnostics().selectedId===id,home.id);
  await page.waitForFunction(address=>document.querySelector('#inspector-content').textContent.includes(address)&&document.querySelector('#inspector-content').textContent.includes('Physical property'),home.address);
  await page.screenshot({path:`${out}/${block.id}-close.png`});
  await page.locator('#map-search').fill('');
  await page.locator('#place-tour').selectOption(block.id);
  const framed=await diagnostics();
  await page.locator('[data-layer=water]').click();
  await page.screenshot({path:`${out}/${block.id}-water.png`});
  await page.locator('[data-layer=town]').click();
  await page.locator('#map-art-toggle').click();assert.equal((await diagnostics()).artwork.enabled,false);
  assert.deepEqual((await diagnostics()).camera,framed.camera);
  await page.screenshot({path:`${out}/${block.id}-native.png`});
  await page.locator('#map-art-toggle').click();assert.equal((await diagnostics()).artwork.enabled,true);
 }
 await page.setViewportSize({width:1024,height:1000});
 for(const name of names){
  await page.locator('#place-tour').selectOption(name);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:`${out}/${name}-1024.png`});
 }
 assert.equal(new Set(hits).size,20);
 assert.deepEqual(await(await page.request.get(base+'/atlas/api/bootstrap')).json(),before,'presentation does not mutate the saved world');
 assert.deepEqual(errors,[]);
 await writeFile(`${out}/checks.json`,JSON.stringify({passed:true,samples:names,artwork:(await diagnostics()).artwork,pickedPremises:hits,sourceUnchanged:true,consoleErrors:errors},null,2)+'\n');
 console.log('PASS: 3 live residential samples, 20 original property mouse picks, direct navigation, water overlays, same-camera native comparison, 1024/1600 layouts, unchanged saved world.');
}finally{await browser.close();}
