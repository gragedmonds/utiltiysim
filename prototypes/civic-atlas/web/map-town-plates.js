import * as THREE from '/viewer/vendor/three.module.js';
import {heightSampler} from '/viewer/adapter.js';

export const TEMPLATE_SCHEMA='civic-atlas-town-template/1';
const rounded=value=>Math.round(Number(value)*10000)/10000;
const finite=value=>Number.isFinite(Number(value))?rounded(value):null;

function localPoint(point,center){return{x:rounded(point.x-center.x),z:rounded(point.z-center.z)};}
function polygon(points,center){
  if(!Array.isArray(points)||points.length<3)throw Error('A source polygon is missing');
  const p=points.map(point=>localPoint(point,center));
  if(p.length>3&&p[0].x===p.at(-1).x&&p[0].z===p.at(-1).z)p.pop();
  // Polygon start vertices and winding are serialization details, not changes
  // to a property's actual footprint. Normalize both without sorting corners.
  const variants=[];for(const ring of[p,[...p].reverse()])for(let i=0;i<ring.length;i++)variants.push(JSON.stringify([...ring.slice(i),...ring.slice(0,i)]));
  return JSON.parse(variants.sort()[0]);
}

/** Stable physical registration, independent of source IDs and translation. */
export function templateSourceSignature(town,block){
  const center=block.center,ids=block.premiseIds;
  if(!center||!Array.isArray(ids)||!ids.length||new Set(ids).size!==ids.length)throw Error('Block slots are missing or duplicated');
  const homes=new Map(town.premises.map(p=>[p.id,p]));
  const parcels=new Map((town.parcels||[]).map(p=>[p.premiseId,p]));
  const buildings=new Map();for(const b of town.buildings||[])for(const id of b.premiseIds||[])buildings.set(id,b);
  const elevation=heightSampler(town.terrain),surface=[];
  const boundary=polygon(block.polygon,center);
  const minX=Math.min(...boundary.map(p=>p.x)),maxX=Math.max(...boundary.map(p=>p.x)),minZ=Math.min(...boundary.map(p=>p.z)),maxZ=Math.max(...boundary.map(p=>p.z));
  for(let z=0;z<=4;z++)for(let x=0;x<=4;x++)surface.push(finite(elevation(center.x+minX+(maxX-minX)*x/4,center.z+minZ+(maxZ-minZ)*z/4)));
  const slots=ids.map((id,slot)=>{
    const p=homes.get(id),parcel=parcels.get(id),b=buildings.get(id)||town.buildings.find(b=>b.id===p?.buildingId);
    if(!p||!parcel||!b?.footprint?.polygon||!p.front)throw Error(`Physical records are incomplete for slot ${slot}`);
    const templatePool=town.atlasDesign?.blockTemplates?.[block.templateId]?.slots?.[slot]?.poolPolygon;
    return{slot,...localPoint(p,center),width:finite(p.width),depth:finite(p.depth),height:finite(p.height),elevationM:finite(p.elevationM),stories:p.stories??null,
      angle:finite(p.angle),side:p.side??null,roof:p.roof??null,roofTone:finite(p.roofTone),solar:Boolean(p.solar),solarKW:finite(p.solarKW),solarPeakKW:finite(p.solarPeakKW),hasPool:Boolean(p.hasPool),
      poolPolygon:p.poolPolygon?polygon(p.poolPolygon,center):templatePool?polygon(templatePool,{x:0,z:0}):null,family:town.atlasDesign?.buildingFamilies?.[id]??null,buildingType:p.buildingType??null,premiseType:p.premiseType??null,
      front:localPoint(p.front,center),parcel:polygon(parcel.polygon,center),footprint:polygon(b.footprint.polygon,center),buildingHeight:finite(b.heightM),buildingStories:b.stories??null,buildingRoof:b.roof??null,
      footprintWidth:finite(b.footprint.widthM),footprintDepth:finite(b.footprint.depthM)};
  });
  const places={};
  if(block.facilityIds||block.parkIds){
    places.facilities=(block.facilityIds||[]).map(id=>{const f=town.facilities?.find(f=>f.id===id);if(!f)throw Error('A saved facility is missing');return{kind:f.kind,...localPoint(f,center),polygon:polygon(f.polygon,center),premiseSlot:ids.indexOf(f.premiseId)};});
    places.parks=(block.parkIds||[]).map(id=>{const p=town.parks?.find(p=>p.id===id),design=town.atlasDesign?.parks?.find(p=>p.id===id);if(!p)throw Error('A saved park is missing');return{polygon:polygon(p.polygon,center),kind:design?.kind??null};});
  }
  if(block.commonsIds)places.commons=block.commonsIds.map(id=>{const common=town.atlasDesign?.commons?.find(c=>c.id===id);if(!common)throw Error('A designated common green is missing');return{kind:common.kind,polygon:polygon(common.polygon,center),descriptiveOnly:Boolean(common.descriptiveOnly)};});
  return JSON.stringify({schema:TEMPLATE_SCHEMA,templateId:block.templateId,polygon:boundary,surface,slots,...places});
}

/** Camera used by both registration guides and the shared runtime plates. */
export function templateCamera(map,block,definition){
  const frame=definition.frame||definition,s=map.scene,camera=s.camera.clone();
  const target=new THREE.Vector3(block.center.x,s.heightAt(block.center.x,block.center.z),block.center.z);
  camera.position.copy(target).addScaledVector(map.direction,1000);camera.quaternion.copy(s.camera.quaternion);
  camera.left=-frame.viewHeight*frame.aspect/2;camera.right=-camera.left;camera.top=frame.viewHeight/2;camera.bottom=-camera.top;camera.zoom=1;
  camera.updateProjectionMatrix();camera.updateMatrixWorld(true);return{camera,target};
}

function close(a,b){return Number.isFinite(a)&&Number.isFinite(b)&&Math.abs(a-b)<1e-5;}

/** Repeated placements share one decoded/masked texture and material per template. */
export function createTownPlates(map,{signal,assetRoot='./assets',assets={}}={}){
  const scene=map.scene,blocks=map.town.atlasDesign?.blocks||[],definitions=map.town.atlasDesign?.blockTemplates||{},controller=new AbortController();
  const stats={ready:false,enabled:false,count:0,totalBlocks:blocks.length,fallbackCount:blocks.length,readyCount:0,textureCount:0,reason:'Neighborhood templates are loading',templates:[],rejected:[]};
  const resources=[],overlays=[];let disposed=false;
  const attached=object=>{for(let p=object;p;p=p.parent)if(p===scene.scene)return true;return false;};
  const restore=record=>{Object.assign(record.object.material,{depthTest:record.depthTest,transparent:record.transparent});record.object.renderOrder=record.order;};
  function prune(){for(let i=overlays.length-1;i>=0;i--)if(!attached(overlays[i].object)){restore(overlays[i]);overlays.splice(i,1);}}
  function liftOverlays(){
    prune();if(!stats.enabled||disposed)return;
    for(const object of[...Object.values(scene.networkGroups||{}),...Object.values(scene.serviceGroups||{}),...Object.values(scene.lineGroups||{}),scene.trace,...(map.parcelHighlight?.children||[])].filter(Boolean)){
      if(!overlays.some(r=>r.object===object))overlays.push({object,depthTest:object.material.depthTest,transparent:object.material.transparent,order:object.renderOrder});
      object.material.depthTest=false;object.material.transparent=true;object.renderOrder=7;
    }
    map.request();
  }
  function setEnabled(value){
    let count=0,validCount=0;for(const resource of resources){
      const enabled=Boolean(value)&&!disposed;let visibleCount=0;
      for(const placement of resource.placements){
        let valid=false;try{valid=templateSourceSignature(map.town,placement.block)===resource.signature;}catch{}
        if(valid)validCount++;const show=enabled&&valid;resource.mesh.setMatrixAt(placement.index,show?placement.matrix:new THREE.Matrix4().makeScale(0,0,0));if(show)visibleCount++;
      }
      resource.mesh.visible=visibleCount>0;resource.mesh.instanceMatrix.needsUpdate=true;resource.mesh.computeBoundingSphere();count+=visibleCount;
    }
    stats.enabled=count>0;stats.count=count;stats.readyCount=validCount;stats.fallbackCount=stats.totalBlocks-validCount;stats.ready=validCount>0;
    if(stats.enabled)liftOverlays();else{overlays.forEach(restore);prune();}
    map.request();return stats.enabled;
  }
  function destroy(){
    if(disposed)return;disposed=true;controller.abort();stats.enabled=false;stats.count=0;overlays.forEach(restore);overlays.length=0;
    for(const r of resources){r.mesh.removeFromParent();r.geometry.dispose();r.material.dispose();r.texture.dispose();}resources.length=0;
    stats.ready=false;stats.textureCount=0;signal?.removeEventListener('abort',destroy);map.request();
  }
  signal?.addEventListener('abort',destroy,{once:true});if(signal?.aborted)destroy();
  async function loadTemplate(templateId){
    const definition=definitions[templateId],members=blocks.filter(b=>b.templateId===templateId),record={id:templateId,ready:false,count:0,reason:'Loading'};stats.templates.push(record);
    let source=null,texture=null;
    try{
      if(!definition)throw Error('Template source definition is missing');
      const paths=assets[templateId]||{},response=await fetch(paths.metadataUrl||`${assetRoot}/civic-template-${templateId}.json`,{signal:controller.signal});if(!response.ok)throw Error('Template artwork is not available');
      const metadata=await response.json();if(disposed)return;
      if(metadata.schemaVersion!==TEMPLATE_SCHEMA||metadata.templateId!==templateId)throw Error('Template metadata is incompatible');
      if(!scene.camera.isOrthographicCamera||metadata.cameraDirection?.length!==3||!metadata.cameraDirection.every((v,i)=>close(v,map.direction.toArray()[i])))throw Error('Artwork does not match the fixed map camera');
      const frame=metadata.frame;if(!frame||!close(frame.center?.x,0)||!close(frame.center?.z,0)||!close(frame.viewHeight,definition.viewHeight)||!close(frame.aspect,definition.aspect))throw Error('Template framing has changed');
      if(JSON.stringify(polygon(metadata.polygon,{x:0,z:0}))!==JSON.stringify(polygon(definition.polygon,{x:0,z:0})))throw Error('Template boundary has changed');
      const valid=[];for(const block of members){try{if(templateSourceSignature(map.town,block)!==metadata.signature)throw Error('Saved footprint, appearance, frontage or terrain differs');valid.push(block);}catch(error){stats.rejected.push({blockId:block.id,reason:error.message});}}
      if(!valid.length)throw Error('No blocks match the illustrated template');
      source=await new THREE.TextureLoader().loadAsync(paths.imageUrl||`${assetRoot}/civic-template-${templateId}.png`);if(disposed){source.dispose();return;}
      if(!close(source.image.width/source.image.height,frame.aspect))throw Error('Template image has the wrong aspect ratio');
      const canvas=document.createElement('canvas');canvas.width=source.image.width;canvas.height=source.image.height;const context=canvas.getContext('2d');context.drawImage(source.image,0,0);
      const {camera}=templateCamera(map,valid[0],definition),center=valid[0].center;
      context.globalCompositeOperation='destination-in';context.beginPath();metadata.polygon.forEach((p,i)=>{const x=p.x+center.x,z=p.z+center.z,v=new THREE.Vector3(x,scene.heightAt(x,z),z).project(camera),px=(v.x+1)*canvas.width/2,py=(1-v.y)*canvas.height/2;i?context.lineTo(px,py):context.moveTo(px,py);});context.closePath();context.fill();
      source.dispose();source=null;texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;texture.anisotropy=8;
      const geometry=new THREE.PlaneGeometry(frame.viewHeight*frame.aspect,frame.viewHeight),material=new THREE.MeshBasicMaterial({map:texture,transparent:true,depthTest:false,depthWrite:false,toneMapped:false});
      const mesh=new THREE.InstancedMesh(geometry,material,valid.length);mesh.name=`atlas-template-${templateId}`;mesh.renderOrder=2;mesh.visible=false;mesh.userData.atlasTownTemplate=templateId;
      const placements=valid.map((block,index)=>{const matrix=new THREE.Matrix4().compose(new THREE.Vector3(block.center.x,scene.heightAt(block.center.x,block.center.z),block.center.z),camera.quaternion,new THREE.Vector3(1,1,1));mesh.setMatrixAt(index,matrix);return{block,index,matrix};});mesh.computeBoundingSphere();scene.root.add(mesh);
      resources.push({mesh,geometry,material,texture,placements,signature:metadata.signature});texture=null;
      Object.assign(record,{ready:true,count:valid.length,reason:'Source-matched reusable illustration'});
    }catch(error){source?.dispose();texture?.dispose();record.reason=error.message;for(const block of members)if(!stats.rejected.some(r=>r.blockId===block.id))stats.rejected.push({blockId:block.id,reason:error.message});}
  }
  const ready=(async()=>{
    if(disposed)return null;await Promise.all([...new Set(blocks.map(b=>b.templateId))].map(loadTemplate));if(disposed)return null;
    stats.readyCount=resources.reduce((sum,r)=>sum+r.placements.length,0);stats.textureCount=resources.length;stats.fallbackCount=blocks.length-stats.readyCount;stats.ready=stats.readyCount>0;
    stats.reason=stats.ready?`${stats.readyCount} saved blocks use ${resources.length} shared illustrations${stats.fallbackCount?`; ${stats.fallbackCount} retain native assets`:''}`:'Template artwork is unavailable; native assets remain interactive';
    return stats;
  })();
  return{ready,stats,setEnabled,liftOverlays,destroy};
}
