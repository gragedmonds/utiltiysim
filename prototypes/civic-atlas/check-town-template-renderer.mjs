import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{chromium}=require(process.env.ATLAS_PLAYWRIGHT_MODULE||'/workspace/ui-review/node_modules/playwright-core');
const origin=process.env.ATLAS_REVIEW_URL||'http://127.0.0.1:8041';
const town=process.env.ATLAS_TOWN_SOURCE?JSON.parse(await readFile(process.env.ATLAS_TOWN_SOURCE,'utf8')):(await(await fetch(origin+'/atlas/api/bootstrap')).json()).snapshot;
const browser=await chromium.launch({executablePath:process.env.ATLAS_CHROMIUM||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage','--enable-unsafe-swiftshader','--no-proxy-server']});
try{
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/__template-test__/harness',r=>r.fulfill({contentType:'text/html',body:'<!doctype html><title>Shared template renderer check</title>'}));
 await page.goto(origin+'/__template-test__/harness');
 const setup=await page.evaluate(async town=>{
  const THREE=await import('/viewer/vendor/three.module.js'),module=await import('/map-town-plates.js'),{heightSampler}=await import('/viewer/adapter.js');
  const direction=new THREE.Vector3(.16,1.2,.82).normalize(),metadata={},groups={};
  for(const block of town.atlasDesign.blocks){const signature=module.templateSourceSignature(town,block);(groups[block.templateId]??=[]).push(signature);if(metadata[block.templateId])continue;const definition=town.atlasDesign.blockTemplates[block.templateId];metadata[block.templateId]={schemaVersion:module.TEMPLATE_SCHEMA,templateId:block.templateId,frame:{center:{x:0,z:0},viewHeight:definition.viewHeight,aspect:definition.aspect},polygon:definition.polygon,cameraDirection:direction.toArray(),signature};}
  const canvas=document.createElement('canvas');canvas.width=48;canvas.height=32;const context=canvas.getContext('2d');context.fillStyle='#5a875d';context.fillRect(0,0,48,32);
  function mapFor(source){const scene=new THREE.Scene(),root=new THREE.Group();scene.add(root);const camera=new THREE.OrthographicCamera(-90,90,60,-60,.5,10000);camera.position.copy(new THREE.Vector3(0,90,0)).addScaledVector(direction,1000);camera.lookAt(0,90,0);camera.updateMatrixWorld(true);return{town:source,direction,scene:{root,scene,camera,heightAt:heightSampler(source.terrain),networkGroups:{},serviceGroups:{},lineGroups:{}},request(){}};}
  window.templateTest={THREE,module,town,mapFor,original:JSON.stringify(town)};
  return{metadata,image:canvas.toDataURL('image/png'),groups:Object.fromEntries(Object.entries(groups).map(([key,values])=>[key,{count:values.length,unique:new Set(values).size}]))};
 },town);
 let missing=null,alteration=null;await page.route('**/__template-test__/*.json',route=>{const id=new URL(route.request().url()).pathname.split('/').at(-1).replace('.json','');const metadata=structuredClone(setup.metadata[id]);if(alteration&&id==='garden-cottages'){if(alteration==='camera')metadata.cameraDirection[0]+=.1;if(alteration==='frame')metadata.frame.viewHeight+=1;if(alteration==='boundary')metadata.polygon[0].x+=1;}return id===missing?route.fulfill({status:404,body:'Expected test fallback'}):route.fulfill({contentType:'application/json',body:JSON.stringify(metadata)});});
 for(const [id,group]of Object.entries(setup.groups))assert.equal(group.unique,1,`${id} must have identical physical registration for every translation`);
 const assets=Object.fromEntries(Object.keys(setup.metadata).map(id=>[id,{metadataUrl:origin+'/__template-test__/'+id+'.json',imageUrl:setup.image}]));
 const result=await page.evaluate(async assets=>{
  const {module,town,mapFor}=window.templateTest,map=mapFor(town),handle=module.createTownPlates(map,{assets});await handle.ready;handle.setEnabled(true);
  const initial={...handle.stats},meshes=map.scene.root.children.filter(m=>m.userData.atlasTownTemplate),sharedMaps=new Set(meshes.map(m=>m.material.map));
  if(sharedMaps.size!==meshes.length||meshes.length!==Object.keys(town.atlasDesign.blockTemplates).length)throw Error('Each source template must share exactly one texture');
  const block=town.atlasDesign.blocks.find(b=>b.templateId==='garden-cottages'),p=town.premises.find(p=>p.id===block.premiseIds[0]),building=town.buildings.find(b=>b.id===p.buildingId),parcel=town.parcels.find(q=>q.premiseId===p.id),base=initial.count,mutations=[];
  for(const [name,object,key,value]of[['pool',p,'hasPool',!p.hasPool],['solar',p,'solar',!p.solar],['frontage',p.front,'x',p.front.x+.25],['footprint',building.footprint.polygon[0],'x',building.footprint.polygon[0].x+.25],['parcel',parcel.polygon[0],'z',parcel.polygon[0].z+.25],['roof',p,'roof',p.roof==='hip'?'gable':'hip'],['floors',p,'stories',p.stories+1]]){
   const old=object[key];object[key]=value;handle.setEnabled(true);if(handle.stats.count!==base-1)throw Error(name+' should disable exactly one translated block');mutations.push(name);object[key]=old;handle.setEnabled(true);if(handle.stats.count!==base)throw Error(name+' restoration failed');
  }
  const terrain=town.terrain,terrainIndex=Math.round((block.center.z-terrain.originZ)/terrain.cellSizeM)*terrain.cols+Math.round((block.center.x-terrain.originX)/terrain.cellSizeM);
  const places=[['terrain',terrain.values,terrainIndex],['common',town.atlasDesign.commons[0].polygon[0],'x'],['facility',town.facilities.find(f=>town.atlasDesign.blocks.some(b=>b.facilityIds?.includes(f.id))),'x'],['park',town.parks.find(p=>town.atlasDesign.blocks.some(b=>b.parkIds?.includes(p.id))).polygon[0],'z']];
  for(const[name,object,key]of places){const old=object[key];object[key]+=.5;handle.setEnabled(true);if(handle.stats.count!==base-1)throw Error(name+' should invalidate exactly its own block');mutations.push(name);object[key]=old;handle.setEnabled(true);if(handle.stats.count!==base)throw Error(name+' restoration failed');}
  const poolTemplate=Object.values(town.atlasDesign.blockTemplates).find(d=>d.slots.some(s=>s.poolPolygon)),pool=poolTemplate.slots.find(s=>s.poolPolygon).poolPolygon[0],poolX=pool.x;pool.x+=.5;handle.setEnabled(true);if(handle.stats.count!==base-town.atlasDesign.blocks.filter(b=>b.templateId===poolTemplate.id).length)throw Error('Changing a shared pool plan must invalidate that template');pool.x=poolX;handle.setEnabled(true);if(handle.stats.count!==base)throw Error('Pool plan restoration failed');mutations.push('templatePoolPolygon');
  const occupants=p.occupants;p.occupants++;handle.setEnabled(true);if(handle.stats.count!==base)throw Error('Operational state must not invalidate physical art');p.occupants=occupants;
  handle.setEnabled(false);if(handle.stats.enabled||map.scene.root.children.some(m=>m.visible))throw Error('Native switch did not hide template planes');handle.setEnabled(true);
  let disposedTextures=0;for(const texture of sharedMaps)texture.addEventListener('dispose',()=>disposedTextures++);handle.destroy();handle.destroy();if(disposedTextures!==sharedMaps.size||map.scene.root.children.length)throw Error('Shared texture cleanup must happen exactly once');
  const abort=new AbortController();abort.abort();const cancelled=module.createTownPlates(mapFor(town),{assets,signal:abort.signal});await cancelled.ready;if(cancelled.stats.ready||cancelled.stats.textureCount)throw Error('Pre-aborted loader allocated resources');cancelled.destroy();
  if(JSON.stringify(town)!==window.templateTest.original)throw Error('Rendering changed source data');return{blocks:base,templates:meshes.length,mutations,disposedTextures};
 },assets);
 missing='garden-cottages';const partial=await page.evaluate(async assets=>{const {module,town,mapFor}=window.templateTest,map=mapFor(town),handle=module.createTownPlates(map,{assets});await handle.ready;handle.setEnabled(true);const result={count:handle.stats.count,fallback:handle.stats.fallbackCount,enabled:handle.stats.enabled};handle.destroy();return result;},assets);
 assert.equal(partial.count,result.blocks-setup.groups[missing].count);assert.equal(partial.fallback,setup.groups[missing].count);assert.equal(partial.enabled,true);assert.deepEqual(errors,[]);
 missing=null;const rejectedMetadata=[];for(const kind of['camera','frame','boundary']){alteration=kind;const count=await page.evaluate(async assets=>{const {module,town,mapFor}=window.templateTest,handle=module.createTownPlates(mapFor(town),{assets});await handle.ready;handle.setEnabled(true);const count=handle.stats.count;handle.destroy();return count;},assets);assert.equal(count,result.blocks-setup.groups['garden-cottages'].count,kind+' mismatch must reject only the affected template');rejectedMetadata.push(kind);}
 console.log(JSON.stringify({pass:true,...result,partialFallback:partial,rejectedMetadata,errors}));
}finally{await browser.close();}
