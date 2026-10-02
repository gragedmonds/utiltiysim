// Daytime outage cue: a flat ring at each premise the engine reports without supply (frame premises.unsupplied),
// one ring per utility in its colour, for the visible layers. At night the windows going dark tell the same story.
import * as THREE from './vendor/three.module.js';
const RADIUS={electric:1,water:1.3,gas:1.6};
export class OutageMarks{
 constructor(root,town,heightAt,colors){this.heightAt=heightAt;this.colors=colors;this.index=new Map(town.premises.map(h=>[h.id,h]));this.mesh=new THREE.InstancedMesh(new THREE.RingGeometry(2.4,3.2,24),new THREE.MeshBasicMaterial({transparent:true,opacity:.9,side:THREE.DoubleSide,depthTest:false,toneMapped:false}),Math.max(1,town.premises.length*4));this.mesh.count=0;this.mesh.frustumCulled=false;this.mesh.renderOrder=3;root.add(this.mesh);this.dummy=new THREE.Object3D();this.color=new THREE.Color();this.key='';this.count=0;}
 update(flow,layers={}){let n=0,key='';const d=this.dummy;
  for(const u of ['electric','water','gas']){if(layers[u]===false)continue;const out=flow?.[u]?.unavailable;if(!out?.size)continue;key+=u+out.size+':';
   for(const id of out){const h=this.index.get(id);if(!h)continue;const p=h.front||h;d.position.set(p.x,this.heightAt(p.x,p.z)+.3,p.z);d.rotation.set(-Math.PI/2,0,0);d.scale.setScalar(RADIUS[u]);d.updateMatrix();this.mesh.setMatrixAt(n,d.matrix);this.mesh.setColorAt(n,this.color.set(this.colors[u]||'#d77545'));n++;}}
  // Service voltage outside ANSI Range A (114–126 V): a small violet ring, with the electric layer.
  if(layers.electric!==false&&flow?.lowVoltage?.size){key+='v'+flow.lowVoltage.size;for(const id of flow.lowVoltage){const h=this.index.get(id);if(!h||n>=this.mesh.instanceMatrix.count)continue;const p=h.front||h;d.position.set(p.x,this.heightAt(p.x,p.z)+.3,p.z);d.rotation.set(-Math.PI/2,0,0);d.scale.setScalar(.65);d.updateMatrix();this.mesh.setMatrixAt(n,d.matrix);this.mesh.setColorAt(n,this.color.set('#8a5cc7'));n++;}}
  this.mesh.count=n;this.mesh.instanceMatrix.needsUpdate=true;if(this.mesh.instanceColor)this.mesh.instanceColor.needsUpdate=true;this.count=n;this.key=key;}
}
