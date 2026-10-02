// Network edges redrawn over the map in their own colours: a thicker tube for close views and a 1-pixel line so the
// edge still reads at town zoom. Built from the scene's path pieces, only for the edges given (loaded or switched
// edges are few), and rebuilt only when that set changes.
import * as THREE from './vendor/three.module.js';
import {zoomStep} from './lens-marks.js';
const dummy=new THREE.Object3D(),up=new THREE.Vector3(0,1,0),mid=new THREE.Vector3(),dir=new THREE.Vector3(),color=new THREE.Color();
export class EdgeOverlay{
 // pathData: {utility: [{edge, pieces: [{a, b, len}]}]} (scene.pathData)
 constructor(root,pathData,{radius=1.4,opacity=.92,renderOrder=4}={}){this.root=root;this.pathData=pathData;this.radius=radius;this.opacity=opacity;this.renderOrder=renderOrder;this.key='';this.visible=true;this.group=null;this.count=0;this.pieces=null;}
 index(){if(!this.pieces){this.pieces=new Map();for(const [u,paths] of Object.entries(this.pathData||{}))for(const p of paths||[])this.pieces.set(u+':'+p.edge.id,p.pieces);}return this.pieces;}
 // Pieces of one edge (for markers placed on it).
 piecesOf(u,id){return this.index().get(u+':'+id)||[];}
 // items: [[utility, edgeId, colour]]
 set(items=[]){const key=items.map(i=>i.join(':')).join(',');if(key===this.key)return false;this.key=key;this.dispose();
  const segs=[];for(const [u,id,c] of items)for(const s of this.piecesOf(u,id))segs.push([s,c]);this.count=segs.length;if(!segs.length)return true;
  const tubes=new THREE.InstancedMesh(new THREE.CylinderGeometry(1,1,1,6),new THREE.MeshBasicMaterial({transparent:true,opacity:this.opacity,depthWrite:false,toneMapped:false}),segs.length),pos=new Float32Array(segs.length*6),col=new Float32Array(segs.length*6);
  this.segs=segs;this.tubes=tubes;this.place();segs.forEach(([{a,b},c],i)=>{color.set(c);tubes.setColorAt(i,color);pos.set([a.x,a.y+.05,a.z,b.x,b.y+.05,b.z],i*6);col.set([color.r,color.g,color.b,color.r,color.g,color.b],i*6);});
  tubes.instanceColor.needsUpdate=true;tubes.computeBoundingSphere();tubes.renderOrder=this.renderOrder;
  const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.BufferAttribute(pos,3));g.setAttribute('color',new THREE.BufferAttribute(col,3));const lines=new THREE.LineSegments(g,new THREE.LineBasicMaterial({vertexColors:true,transparent:true,opacity:1,depthWrite:false,toneMapped:false}));lines.renderOrder=this.renderOrder;
  this.group=new THREE.Group();this.group.add(tubes,lines);this.group.visible=this.visible;this.root.add(this.group);return true;}
 // Tubes thicken with distance (lens-marks.js zoomStep) so the edge still reads at town zoom.
 zoom(distance){const k=zoomStep(distance);if(k===this.scale)return;this.scale=k;if(this.tubes){this.place();this.tubes.computeBoundingSphere();}}
 place(){const k=this.scale||1,r=this.radius*k;(this.segs||[]).forEach(([{a,b}],i)=>{mid.copy(a).add(b).multiplyScalar(.5);dir.copy(b).sub(a);const len=dir.length();dummy.position.copy(mid);dummy.quaternion.setFromUnitVectors(up,dir.normalize());dummy.scale.set(r,len,r);dummy.updateMatrix();this.tubes.setMatrixAt(i,dummy.matrix);});if(this.tubes)this.tubes.instanceMatrix.needsUpdate=true;}
 setVisible(v){this.visible=!!v;if(this.group)this.group.visible=this.visible;}
 dispose(){if(!this.group)return;this.group.traverse(o=>{o.geometry?.dispose();o.material?.dispose();});this.root.remove(this.group);this.group=null;this.tubes=null;this.segs=null;this.count=0;}
}
