import * as THREE from './vendor/three.module.js';
export const DETAIL_LIMIT=192;
const hash=s=>{let h=2166136261;for(const c of String(s)){h^=c.charCodeAt(0);h=Math.imul(h,16777619);}return h>>>0;};
const triangles=g=>(g.index?.count??g.attributes.position.count)/3;
function merge(parts){const positions=[],normals=[];for(const {geo,matrix} of parts){const g=(geo.index?geo.toNonIndexed():geo.clone()).applyMatrix4(matrix);positions.push(...g.attributes.position.array);normals.push(...g.attributes.normal.array);g.dispose();}const out=new THREE.BufferGeometry();out.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));out.setAttribute('normal',new THREE.Float32BufferAttribute(normals,3));out.computeBoundingSphere();return out;}
function archetype(style,tall){
 const parts={trim:[],glass:[],door:[],roof:[]},box=new THREE.BoxGeometry(1,1,1),plane=new THREE.PlaneGeometry(1,1),dummy=new THREE.Object3D();
 const add=(kind,geo,x,y,z,sx,sy,sz,rx=0,ry=0)=>{dummy.position.set(x,y,z);dummy.rotation.set(rx,ry,0);dummy.scale.set(sx,sy,sz);dummy.updateMatrix();parts[kind].push({geo,matrix:dummy.matrix.clone()});};
 const quad=(kind,x,y,z,w,h,ry=Math.PI)=>add(kind,plane,x,y,z,w,h,1,0,ry);
 const block=(kind,x,y,z,w,h,d)=>add(kind,box,x,y,z,w,h,d);
 const window=(x,y,z,w=.13,h=.2,side=0)=>{
  const ry=side===0?Math.PI:side*Math.PI/2,nx=side*.002,nz=side===0?-.002:0;
  quad('trim',x,y,z,w+.025,h+.035,ry);quad('glass',x+nx,y,z+nz,w,h,ry);
  quad('trim',x+nx*2,y,z+nz*2,.008,h,ry);quad('trim',x+nx*2,y,z+nz*2,w,.01,ry);
  if(side===0)block('trim',x,y-h/2-.016,z-.004,w+.038,.018,.025);
 };
 const ys=tall?[.30,.76]:[.53];
 for(const y of ys){for(const x of [-.30,.28]){if(style===2&&y===ys[0]&&x>.1)continue;window(x,y,-.503,.13,tall?.21:.31);}for(const x of [-.505,.505])for(const z of [-.23,.23])window(x,y,z,.14,tall?.21:.3,Math.sign(x));}
 const entry=style===1?.24:-.04,doorH=tall?.36:.57;
 quad('trim',entry,doorH/2+.015,-.507,.139,doorH+.03);quad('door',entry,doorH/2+.015,-.51,.11,doorH);quad('glass',entry,doorH*.72,-.512,.069,doorH*.25);block('trim',entry+.038,doorH*.4,-.517,.008,.008,.008);
 // A shallow stoop and portico fit within the rendered plot, without changing engine footprints.
 block('trim',entry,.018,-.565,.28,.035,.15);block('trim',entry,.045,-.544,.23,.035,.105);
 if(style!==2){block('roof',entry,doorH+.06,-.555,.30,.032,.15);for(const x of [entry-.13,entry+.13])block('trim',x,(doorH+.035)/2,-.61,.014,doorH+.035,.014);}
 // Garage front occupies the existing facade; no invented floor area or utility load.
 if(style===2){quad('trim',.26,.23,-.507,.36,.44);quad('door',.26,.23,-.51,.32,.4);for(let i=1;i<5;i++)quad('trim',.26,.032+i*.078,-.514,.32,.007);quad('glass',.26,.36,-.516,.26,.045);}
 // Eaves, fascia, chimney and downspouts give depth without a textured asset per home.
 for(const x of [-.526,.526])block('trim',x,.99,0,.024,.04,1.05);
 for(const z of [-.526,.526])block('trim',0,.993,z,1.075,.036,.014);
 block('roof',-.27,1.21,.19,.068,.44,.065);block('trim',-.27,1.44,.19,.092,.035,.088);
 for(const x of [-.478,.478])block('trim',x,.5,-.515,.009,.94,.009);
 const geometries=Object.fromEntries(Object.entries(parts).map(([k,v])=>[k,merge(v)]));box.dispose();plane.dispose();return geometries;
}
export class HouseDetails{
 constructor(root,homes,heightAt,seed){this.root=root;this.homes=homes;this.heightAt=heightAt;this.enabled=true;this.lastUpdate=-Infinity;this.visibleHomes=0;this.lastKey='';this.group=new THREE.Group();root.add(this.group);this.groups=[];this.styleByHome=homes.map(h=>hash(seed+':facade:'+h.id)%3+(h.height>=5?3:0));
  const palette={trim:'#ede8dc',glass:'#718d91',door:'#8a9a89',roof:'#828b81'};
  for(let i=0;i<6;i++){const geometry=archetype(i%3,i>=3),meshes={};for(const [kind,g]of Object.entries(geometry)){const mat=new THREE.MeshStandardMaterial({color:palette[kind],roughness:kind==='glass'?.36:.85,metalness:kind==='glass'?.16:0,side:THREE.DoubleSide});const m=new THREE.InstancedMesh(g,mat,DETAIL_LIMIT);m.instanceMatrix.setUsage(THREE.DynamicDrawUsage);m.count=0;m.frustumCulled=false;m.castShadow=kind!=='glass';m.receiveShadow=true;this.group.add(m);meshes[kind]=m;}this.groups.push(meshes);}
  this.temporary=new THREE.Object3D();this.frustum=new THREE.Frustum();this.projection=new THREE.Matrix4();this.point=new THREE.Vector3();this.drawnTriangles=0;
 }
 setEnabled(value){this.enabled=value;this.group.visible=value;this.lastUpdate=-Infinity;if(!value){this.visibleHomes=0;this.drawnTriangles=0;}this.lastKey='';}
 update(camera,viewportHeight,now,force=false){if(!this.enabled)return;if(!force&&now-this.lastUpdate<180)return;this.lastUpdate=now;camera.updateMatrixWorld(true);this.projection.multiplyMatrices(camera.projectionMatrix,camera.matrixWorldInverse);this.frustum.setFromProjectionMatrix(this.projection);const factor=viewportHeight/(2*Math.tan(camera.fov*Math.PI/360)),candidates=[];
  for(let i=0;i<this.homes.length;i++){const h=this.homes[i],y=h.elevationM??this.heightAt(h.x,h.z);this.point.set(h.x,y+h.height/2,h.z);const distance=this.point.distanceTo(camera.position);if((h.height+3)*factor/Math.max(1,distance)<18||!this.frustum.containsPoint(this.point))continue;candidates.push({i,distance,y});}
  candidates.sort((a,b)=>a.distance-b.distance||a.i-b.i);const chosen=candidates.slice(0,DETAIL_LIMIT),key=chosen.map(c=>c.i).join(',');this.visibleHomes=chosen.length;if(key===this.lastKey)return;this.lastKey=key;const counts=Array(6).fill(0);
  for(const {i,y}of chosen){const h=this.homes[i],style=this.styleByHome[i],slot=counts[style]++,d=this.temporary;d.position.set(h.x,y,h.z);d.rotation.set(0,-h.angle+(h.side===-1?Math.PI:0),0);d.scale.set(h.width,h.height,h.depth);d.updateMatrix();for(const m of Object.values(this.groups[style]))m.setMatrixAt(slot,d.matrix);}
  this.drawnTriangles=0;this.groups.forEach((meshes,i)=>{for(const m of Object.values(meshes)){m.count=counts[i];m.instanceMatrix.needsUpdate=true;this.drawnTriangles+=triangles(m.geometry)*m.count;}});
 }
 stats(){return {detailedHomes:this.visibleHomes,detailLimit:DETAIL_LIMIT,detailTriangles:this.enabled?this.drawnTriangles:0,detailBatches:this.enabled?this.groups.reduce((n,g)=>n+Object.values(g).filter(m=>m.count>0).length,0):0};}
}
