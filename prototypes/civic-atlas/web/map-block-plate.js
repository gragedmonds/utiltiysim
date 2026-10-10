import * as THREE from '/viewer/vendor/three.module.js';
export const BLOCK={id:'pine-willow-eight',center:{x:66,z:-137},viewHeight:100,aspect:1.5,ids:['P-00038','P-00039','P-00040','P-00041','P-00042','P-00047','P-00048','P-00049'],polygon:[{x:19.35848,z:-170.65066},{x:20.44617,z:-163.39938},{x:14.28999,z:-95.68139},{x:109.68034,z:-101.64329},{x:121.21199,z:-179.48189}]};
export const SECOND_BLOCK={id:'oak-birch-six',center:{x:172,z:-148},viewHeight:110,aspect:1.5,ids:['P-00063','P-00064','P-00065','P-00087','P-00088','P-00089'],polygon:[{x:135.1864,z:-181.00722},{x:123.48163,z:-102},{x:203.53157,z:-102},{x:200.46494,z:-147.99941},{x:230.93385,z:-195.08772}]};
export function sourceSignature(town,block=BLOCK){return JSON.stringify({townId:town.id,topologyRevision:town.topologyRevision,premises:town.premises.filter(p=>block.ids.includes(p.id)).map(p=>({id:p.id,x:p.x,z:p.z,angle:p.angle,side:p.side,elevationM:p.elevationM,solar:p.solar,solarKW:p.solarKW,width:p.width,depth:p.depth,height:p.height,stories:p.stories,roof:p.roof})),terrain:town.terrain,buildings:town.buildings.filter(b=>b.premiseIds?.some(id=>block.ids.includes(id))),parcels:town.parcels.filter(p=>block.ids.includes(p.premiseId)),roads:town.roads});}
export function blockCamera(map,block=BLOCK){const s=map.scene,c=s.camera.clone(),target=new THREE.Vector3(block.center.x,s.heightAt(block.center.x,block.center.z),block.center.z);c.position.copy(target).addScaledVector(map.direction,1000);c.quaternion.copy(s.camera.quaternion);c.left=-block.viewHeight*block.aspect/2;c.right=-c.left;c.top=block.viewHeight/2;c.bottom=-c.top;c.zoom=1;c.updateProjectionMatrix();c.updateMatrixWorld(true);return{camera:c,target};}
export function createBlockPlate(map, options) {
  const block = options.block || BLOCK;
  const stats = {ready:false, enabled:false, invalidated:false, reason:'Artwork is loading', overlayRecords:0};
  const s = map.scene, controller = new AbortController();
  let mesh, texture, metadata, disposed = false;
  let overlayMaterials = [];
  const attached = object => {
    for (let node=object; node; node=node.parent) if (node===s.scene) return true;
    return false;
  };
  const restoreOverlay = record => {
    record.object.renderOrder=record.order;
    record.object.material.depthTest=record.depthTest;
    record.object.material.transparent=record.transparent;
  };
  function pruneOverlays() {
    overlayMaterials=overlayMaterials.filter(record=>{
      if (attached(record.object)) return true;
      restoreOverlay(record); return false;
    });
    stats.overlayRecords=overlayMaterials.length;
  }
  function liftOverlays() {
    if (!stats.enabled || disposed || options.manageOverlays===false) return;
    pruneOverlays();
    const objects=[...Object.values(s.networkGroups||{}), ...Object.values(s.serviceGroups||{}),
      ...Object.values(s.lineGroups||{}), s.trace, ...(map.parcelHighlight?.children||[])].filter(Boolean);
    for (const object of objects) {
      if (!overlayMaterials.some(r=>r.object===object)) overlayMaterials.push({object,
        order:object.renderOrder, depthTest:object.material.depthTest, transparent:object.material.transparent});
      object.renderOrder=7; object.material.depthTest=false; object.material.transparent=true;
    }
    stats.overlayRecords=overlayMaterials.length; map.request();
  }
  function setEnabled(value) {
    value=Boolean(value)&&!disposed&&!controller.signal.aborted;
    if (value && (!stats.ready || stats.invalidated || sourceSignature(map.town,block)!==metadata.signature)) {
      stats.reason='Artwork does not match current source geometry'; value=false;
    }
    stats.enabled=value; if (mesh) mesh.visible=value;
    if (value) liftOverlays();
    else { for (const record of overlayMaterials) restoreOverlay(record); pruneOverlays(); }
    map.request(); return value;
  }
  function destroy() {
    if (disposed) return;
    disposed=true; controller.abort(); setEnabled(false);
    mesh?.removeFromParent(); mesh?.geometry.dispose(); mesh?.material.dispose(); texture?.dispose();
    mesh=null; texture=null; overlayMaterials=[]; stats.overlayRecords=0; stats.ready=false;
    options.signal?.removeEventListener('abort',destroy);
  }
  options.signal?.addEventListener('abort',destroy,{once:true});
  if (options.signal?.aborted) destroy();
  const ready=(async()=>{
    try {
      if (disposed) return null;
      const response=await fetch(options.metadataUrl,{signal:controller.signal});
      if (!response.ok) throw Error('Block metadata is not available');
      metadata=await response.json(); if (disposed) return null;
      if (metadata.schemaVersion!=='civic-atlas-block-art/1' || JSON.stringify(metadata.block)!==JSON.stringify(block))
        throw Error('Unsupported block artwork metadata');
      if (metadata.cameraDirection?.length!==3 || !metadata.cameraDirection.every((v,i)=>Math.abs(v-map.direction.toArray()[i])<1e-6))
        throw Error('Block artwork was authored for another camera');
      const expectedTarget=blockCamera(map,block).target.toArray();
      if (metadata.target?.length!==3 || !metadata.target.every((v,i)=>Math.abs(v-expectedTarget[i])<1e-6))
        throw Error('Block artwork framing no longer matches');
      if (metadata.signature!==sourceSignature(map.town,block)) throw Error('Block source geometry no longer matches');
      texture=await new THREE.TextureLoader().loadAsync(options.imageUrl);
      // TextureLoader cannot abort its image request. A late image must still be
      // released and must never add artwork to an already-destroyed map.
      if (disposed || controller.signal.aborted) { texture.dispose(); texture=null; return null; }
      if (Math.abs(texture.image.width/texture.image.height-block.aspect)>.001)
        throw Error('Block artwork must preserve the guide aspect ratio');
      const {camera,target}=blockCamera(map,block), canvas=document.createElement('canvas');
      canvas.width=texture.image.width; canvas.height=texture.image.height;
      const ctx=canvas.getContext('2d'); ctx.drawImage(texture.image,0,0);
      const points=block.polygon.map(p=>{
        const v=new THREE.Vector3(p.x,s.heightAt(p.x,p.z),p.z).project(camera);
        return {x:(v.x+1)*canvas.width/2,y:(1-v.y)*canvas.height/2};
      });
      ctx.globalCompositeOperation='destination-in'; ctx.beginPath();
      points.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y)); ctx.closePath(); ctx.fill();
      // Only the ground seam is feathered inward; roads remain the live scene.
      const rgba=ctx.getImageData(0,0,canvas.width,canvas.height);
      for (let y=0;y<canvas.height;y++) for (let x=0;x<canvas.width;x++) {
        const k=(y*canvas.width+x)*4+3; if (!rgba.data[k]) continue;
        let distance=Infinity;
        for (let i=0;i<points.length;i++) {
          const a=points[i],b=points[(i+1)%points.length],dx=b.x-a.x,dy=b.y-a.y;
          const t=Math.max(0,Math.min(1,((x-a.x)*dx+(y-a.y)*dy)/(dx*dx+dy*dy)));
          distance=Math.min(distance,Math.hypot(x-a.x-t*dx,y-a.y-t*dy));
        }
        rgba.data[k]*=Math.min(1,distance/7);
      }
      ctx.putImageData(rgba,0,0); texture.dispose(); texture=new THREE.CanvasTexture(canvas);
      texture.colorSpace=THREE.SRGBColorSpace; texture.anisotropy=8;
      const material=new THREE.MeshBasicMaterial({map:texture,transparent:true,depthTest:false,depthWrite:false,toneMapped:false});
      mesh=new THREE.Mesh(new THREE.PlaneGeometry(block.viewHeight*block.aspect,block.viewHeight),material);
      mesh.name='atlas-generated-block-study'; mesh.quaternion.copy(camera.quaternion); mesh.position.copy(target);
      mesh.renderOrder=2; mesh.visible=false; s.root.add(mesh);
      stats.ready=true; stats.reason='Camera-calibrated block experiment'; return stats;
    } catch(error) {
      texture?.dispose(); texture=null;
      stats.reason=disposed||controller.signal.aborted?'Artwork loading cancelled':error.message;
      return null;
    }
  })();
  return {ready,stats,setEnabled,liftOverlays,invalidate(reason){stats.invalidated=true;stats.reason=reason;setEnabled(false);},destroy};
}
