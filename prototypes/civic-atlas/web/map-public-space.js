import * as THREE from '/viewer/vendor/three.module.js';
import {GeometryBuilder,roofGeometry,hash} from '/viewer/lowpoly.js';
import {streetWidth} from '/viewer/roads.js';

// Decorative landscape programs contained in saved park polygons. These have
// no capacity, occupants, meters or operational state. Road/utility truth stays
// in the snapshot. The caller clears trees from the returned occupied areas.
export function furnishPark(scene,{kind,box,contains,clearPad,paths}){
  const b=new GeometryBuilder(),areas=[],width=box.maxX-box.minX,depth=box.maxZ-box.minZ;
  const cx=(box.minX+box.maxX)/2,cz=(box.minZ+box.maxZ)/2;
  const safe=(x,z,rx,rz)=>{
    for(let i=0;i<=8;i++)for(let j=0;j<=8;j++){
      const p={x:x+(i/4-1)*rx,z:z+(j/4-1)*rz};
      if(!contains(p)||!clearPad(p,1))return false;
    }
    return true;
  };
  function site(x,z,rx,rz,draw){
    if(!safe(x,z,rx,rz))return;
    const y=scene.heightAt(x,z)+.18;draw(x,y,z);
    areas.push({x,z,rx:rx+1.5,rz:rz+1.5});
  }
  const boxAt=(color,x,y,z,w,h,d)=>b.box(color,x,y,z,w,h,d);
  function cylinder(color,x,y,z,r,h,n=24){const g=new THREE.CylinderGeometry(r,r,h,n);b.add(g,color,x,y,z);g.dispose();}
  function beam(color,a,c,r=.08){const v=new THREE.Vector3(...c).sub(new THREE.Vector3(...a)),g=new THREE.CylinderGeometry(r,r,v.length(),7);g.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,1,0),v.normalize()));g.translate((a[0]+c[0])/2,(a[1]+c[1])/2,(a[2]+c[2])/2);b.add(g,color);g.dispose();}
  function bench(x,y,z){for(const dx of[-.7,.7])boxAt('#56695e',x+dx,y+.28,z,.10,.55,.55);for(let j=0;j<3;j++)boxAt('#ac9675',x,y+.60,z-.22+j*.22,1.85,.10,.15);boxAt('#a58e6f',x,y+.95,z+.30,1.85,.52,.09);}
  function planter(x,y,z,r){cylinder('#c9b99a',x,y+.25,z,r,.5);cylinder('#718c54',x,y+.58,z,r*.92,.22);for(let i=0;i<7;i++){const a=i*2.4; cylinder(i%2?'#e1c58c':'#b49cab',x+Math.cos(a)*r*.60,y+.73,z+Math.sin(a)*r*.60,.13,.12,8);}}
  if(kind==='civic'){
    site(cx-6,cz,6.7,6.7,(x,y,z)=>{
      cylinder('#c5b99d',x,y,z,6.5,.08,48);cylinder('#dfd4bb',x,y+.055,z,5.8,.035,48);
      // A garden court, not an invented hydraulic fountain.
      planter(x,y+.06,z,1.6);
      for(const dx of[-3.7,3.7])for(const dz of[-3.5,3.5])planter(x+dx,y,z+dz,.65);
      bench(x-3,y,z+3.2);bench(x+3,y,z+3.2);
      boxAt('#80755f',x-4.4,y+1,z-2,.12,2,.12);boxAt('#506f66',x-4.4,y+1.7,z-2,1.0,.65,.10);
    });
  }else if(kind==='riverfront'){
    site(cx,cz+depth*.24,5,3.4,(x,y,z)=>{
      boxAt('#b39c79',x,y,z,9.6,.12,6);
      for(let i=0;i<32;i++)boxAt('#c4ae89',x-4.65+i*.30,y+.07,z,.265,.035,6);
      for(const dx of[-4.4,4.4])for(const dz of[-2.7,2.7])boxAt('#8d886a',x+dx,y+1.7,z+dz,.19,3.4,.19);
      for(const dz of[-2.7,2.7])boxAt('#a69d7c',x,y+3.4,z+dz,9.5,.24,.20);
      for(let i=0;i<12;i++)boxAt('#b9ad8a',x-4.4+i*.8,y+3.58,z,.13,.18,6.2);
      bench(x-2.5,y,z+1.8);bench(x+2.5,y,z+1.8);planter(x-3.9,y,z-2,.55);planter(x+3.9,y,z-2,.55);
    });
  }else if(kind==='recreation'){
    site(cx,box.minZ+depth*.17,9,5,(x,y,z)=>{
      boxAt('#c5b28b',x,y,z,17.5,.08,9.5);boxAt('#bbaa89',x,y+.05,z,16.9,.035,8.9);
      // Natural timber play structure; clear approach and fall space around it.
      for(const dx of[-1.1,1.1])for(const dz of[-1,1])boxAt('#987e5d',x-4+dx,y+1.35,z+dz,.18,2.7,.18);
      boxAt('#c3a77d',x-4,y+1.55,z,2.5,.15,2.3);
      const roof=roofGeometry(1);b.add(roof,'#698678',x-4,y+2.8,z,3,.8,2.8);roof.dispose();
      for(let j=0;j<5;j++)boxAt('#a28d69',x-4,y+.25+j*.30,z-2.5+j*.30,1,.12,.3);
      beam('#7d9a8c',[x-3,y+1.7,z+.7],[x-.7,y+.25,z+3],.34);
      for(const dx of[1,6])for(const side of[-1,1])beam('#8b805f',[x+dx,y,z+side*1.5],[x+dx,y+3.1,z]);
      beam('#887759',[x+1,y+3.1,z],[x+6,y+3.1,z],.13);
      for(const dx of[2.3,4.7]){for(const side of[-1,1])beam('#69736c',[x+dx+side*.30,y+3,z],[x+dx+side*.30,y+.65,z],.025);boxAt('#536e64',x+dx,y+.63,z,.8,.10,.35);}
      bench(x+5,y,z+3.5);
    });
  }
  // Join each program to an existing park walk; sample the complete strip so
  // connectors cannot escape the park or cross a facility footprint.
  for(const area of [...areas]){
    let nearest;for(const {a,b:p}of paths){const dx=p.x-a.x,dz=p.z-a.z,t=Math.max(0,Math.min(1,((area.x-a.x)*dx+(area.z-a.z)*dz)/(dx*dx+dz*dz||1))),q={x:a.x+dx*t,z:a.z+dz*t},d=Math.hypot(q.x-area.x,q.z-area.z);if(!nearest||d<nearest.d)nearest={...q,d};}
    if(!nearest||nearest.d>40||nearest.d<1)continue;
    const dx=(nearest.x-area.x)/nearest.d,dz=(nearest.z-area.z)/nearest.d,nx=-dz*.85,nz=dx*.85,steps=Math.ceil(nearest.d),points=[];let valid=true;
    for(let i=0;i<=steps;i++){const x=area.x+dx*nearest.d*i/steps,z=area.z+dz*nearest.d*i/steps;if(!safe(x,z,.9,.9)){valid=false;break;}points.push({x,z});}
    if(!valid)continue;
    const vertices=[];for(let i=1;i<points.length;i++){const a=points[i-1],p=points[i];for(const [x,z]of[[a.x+nx,a.z+nz],[a.x-nx,a.z-nz],[p.x-nx,p.z-nz],[a.x+nx,a.z+nz],[p.x-nx,p.z-nz],[p.x+nx,p.z+nz]])vertices.push(x,scene.heightAt(x,z)+.15,z);areas.push({x:p.x,z:p.z,rx:1.8,rz:1.8});}
    const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));g.computeVertexNormals();b.add(g,'#c2b99e');g.dispose();
  }
  const geometry=b.build();if(!geometry.attributes.position.count){geometry.dispose();return{areas,mesh:null};}
  const mesh=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({vertexColors:true,roughness:1,side:THREE.DoubleSide}));mesh.castShadow=true;mesh.receiveShadow=true;mesh.userData.atlasParkFurnishing=kind;return{areas,mesh};
}

const insideField=(p,polygon)=>{
  let inside=false;
  for(let i=0,j=polygon.length-1;i<polygon.length;j=i++){
    const a=polygon[i],b=polygon[j];
    if((a.z>p.z)!==(b.z>p.z)&&p.x<(b.x-a.x)*(p.z-a.z)/(b.z-a.z)+a.x)inside=!inside;
  }
  return inside;
};
function fieldEdgeDistance(p,a,b){
  const dx=b.x-a.x,dz=b.z-a.z,t=Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.z-a.z)*dz)/(dx*dx+dz*dz||1)));
  return Math.hypot(p.x-a.x-dx*t,p.z-a.z-dz*t);
}

/**
 * Cultivated land is an illustrative surface on saved polygons, never a new
 * farm customer, building, service or production record. Existing church and
 * civic buildings remain in applyBuildingFamilies, and parks in renderParks.
 * Saved common greens receive only decorative paths, maintained lawn and seats.
 * The caller uses containsFarmland/containsCommons to keep generic woodland and
 * private garden dressing out of the public open spaces.
 */
export function renderPublicSpace(scene,town){
  const source=town.atlasDesign?.fields||[],group=new THREE.Group();
  group.name='atlas-saved-public-space';scene.root.add(group);
  const fields=source.filter(f=>Array.isArray(f.polygon)&&f.polygon.length>=3&&f.polygon.every(p=>Number.isFinite(p.x)&&Number.isFinite(p.z)));
  const fieldPolygons=fields.map(f=>f.polygon),hedges=[],resources=[];
  const metadata={fields:fields.length,fieldIds:fields.map(f=>f.id),hedgePatches:0,triangles:0,source:'atlasDesign.fields'};
  const commons=(town.atlasDesign?.commons||[]).filter(c=>c.kind==='common_green'&&Array.isArray(c.polygon)&&c.polygon.length>=3&&c.polygon.every(p=>Number.isFinite(p.x)&&Number.isFinite(p.z)));
  const commonPolygons=commons.map(c=>c.polygon);
  Object.assign(metadata,{commons:commons.length,commonIds:commons.map(c=>c.id),commonPaths:0,commonEntrances:0,commonBenches:0,commonSource:'atlasDesign.commons'});
  const height=(x,z)=>(scene.heightAt(x,z)||0);
  const clearRoad=p=>(town.roads||[]).every(r=>(r.points||[]).every((a,i,points)=>!i||fieldEdgeDistance(p,points[i-1],a)>(r.rowWidthM||r.rightOfWayWidthM||r.pavementWidthM||8)/2+3));
  const clearSite=p=>[...(town.buildings||[]),...(town.facilities||[])].every(site=>!site.polygon?.length||(!insideField(p,site.polygon)&&site.polygon.every((a,i,poly)=>fieldEdgeDistance(p,a,poly[(i+1)%poly.length])>3)));
  for(const field of fields){
    const polygon=field.polygon,seed=hash(field.id||field.name||JSON.stringify(polygon));
    const kind=String(field.crop||field.kind||'arable').toLowerCase();
    const pasture=/pasture|hay|grass|meadow/.test(kind),fallow=/fallow|tilled/.test(kind),orchard=/orchard/.test(kind);
    const color=new THREE.Color(pasture?'#9cac7d':fallow?'#a89578':orchard?'#9dad7c':'#c7b88a');
    const positions=[],colors=[];
    // Subdivision follows the real terrain without the quadratic growth caused
    // by subdividing long narrow ribbons. No field pixels extend beyond its ring.
    for(const tri of THREE.ShapeUtils.triangulateShape(polygon.map(p=>new THREE.Vector2(p.x,p.z)),[])){
      const [a,b,c]=tri.map(i=>polygon[i]);
      const steps=Math.max(1,Math.ceil(Math.max(Math.hypot(a.x-b.x,a.z-b.z),Math.hypot(a.x-c.x,a.z-c.z),Math.hypot(b.x-c.x,b.z-c.z))/20));
      const at=(i,j)=>({x:a.x+(b.x-a.x)*i/steps+(c.x-a.x)*j/steps,z:a.z+(b.z-a.z)*i/steps+(c.z-a.z)*j/steps});
      const vertex=p=>{positions.push(p.x,height(p.x,p.z)+.11,p.z);const tint=.985+Math.sin(p.x*.031+p.z*.017)*.022+Math.cos(p.z*.046)*.014;colors.push(color.r*tint,color.g*tint,color.b*tint);};
      for(let i=0;i<steps;i++)for(let j=0;j<steps-i;j++){
        [at(i,j),at(i+1,j),at(i,j+1)].forEach(vertex);
        if(i+j<steps-1)[at(i+1,j),at(i+1,j+1),at(i,j+1)].forEach(vertex);
      }
    }
    const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geometry.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));geometry.computeVertexNormals();
    const material=new THREE.MeshStandardMaterial({vertexColors:true,roughness:1,side:THREE.DoubleSide});
    const angle=Number.isFinite(field.rowAngleRadians)?field.rowAngleRadians:(seed%2?0:Math.PI/2),spacing=pasture?9:orchard?8:2.4;
    material.onBeforeCompile=shader=>{
      shader.uniforms.fieldAxis={value:new THREE.Vector2(Math.cos(angle),Math.sin(angle))};
      shader.uniforms.fieldSpacing={value:spacing};shader.uniforms.fieldStrength={value:pasture?.065:orchard?.10:.085};
      shader.vertexShader='varying vec2 fieldPosition;\n'+shader.vertexShader;
      shader.vertexShader=shader.vertexShader.replace('#include <begin_vertex>','#include <begin_vertex>\nfieldPosition=position.xz;');
      shader.fragmentShader='varying vec2 fieldPosition; uniform vec2 fieldAxis; uniform float fieldSpacing; uniform float fieldStrength;\n'+shader.fragmentShader;
      shader.fragmentShader=shader.fragmentShader.replace('#include <color_fragment>',`#include <color_fragment>
        float fieldAcross=dot(fieldPosition,fieldAxis);
        float fieldFrequency=fieldAcross/fieldSpacing;
        float fieldAA=1.0-smoothstep(.10,.75,fwidth(fieldFrequency));
        float fieldRows=cos(fieldFrequency*6.2831853)*fieldAA;
        float fieldBands=cos(fieldAcross/18.0*6.2831853)*.015;
        diffuseColor.rgb*=1.0+fieldRows*fieldStrength+fieldBands;
      `);
    };
    material.customProgramCacheKey=()=> 'atlas-farmland/1';
    const mesh=new THREE.Mesh(geometry,material);mesh.receiveShadow=true;mesh.userData.atlasFarmland=field.id;group.add(mesh);resources.push(geometry,material);metadata.triangles+=positions.length/9;
    // A quieter turning strip gives cultivated fields a readable headland. Its
    // centerline stays inside the saved edge and is sampled before each quad.
    const edgeBuilder=new GeometryBuilder();
    for(let i=0;i<polygon.length;i++){
      const a=polygon[i],b=polygon[(i+1)%polygon.length],length=Math.hypot(b.x-a.x,b.z-a.z);if(length<4)continue;
      const dx=(b.x-a.x)/length,dz=(b.z-a.z)/length,mid={x:(a.x+b.x)/2,z:(a.z+b.z)/2};
      let nx=-dz,nz=dx;if(!insideField({x:mid.x+nx*.5,z:mid.z+nz*.5},polygon)){nx=-nx;nz=-nz;}
      const edgePositions=[];
      for(let t=1;t<length-2;t+=4){
        const end=Math.min(t+4,length-1),corners=[[t,.3],[end,.3],[end,3],[t,3]].map(([along,inset])=>({x:a.x+dx*along+nx*inset,z:a.z+dz*along+nz*inset}));
        if(!corners.every(p=>insideField(p,polygon)))continue;
        for(const j of[0,1,2,0,2,3]){const p=corners[j];edgePositions.push(p.x,height(p.x,p.z)+.135,p.z);}
      }
      if(edgePositions.length){const edge=new THREE.BufferGeometry();edge.setAttribute('position',new THREE.Float32BufferAttribute(edgePositions,3));edge.computeVertexNormals();edgeBuilder.add(edge,pasture?'#9eae81':fallow?'#ae9d80':'#baad87');edge.dispose();}
      // Broken hedgerows mark selected boundaries. The gaps are intentional;
      // roadside gates and building approaches must remain easy to see.
      if((i+seed)%3===0)continue;
      for(let t=8;t<length-8;t+=8){
        const n=hash(`${field.id}:${i}:${Math.round(t)}`);if(n%7<3)continue;
        const p={x:a.x+dx*t+nx*5,z:a.z+dz*t+nz*5};
        if(!insideField(p,polygon)||!clearRoad(p)||!clearSite(p)||polygon.some((q,j)=>fieldEdgeDistance(p,q,polygon[(j+1)%polygon.length])<2.2))continue;
        hedges.push({...p,angle:Math.atan2(dx,dz),length:3.7+(n%20)/10,height:.70+(n%8)/10});
      }
    }
    const edgeGeometry=edgeBuilder.build();
    if(edgeGeometry.attributes.position.count){const mat=new THREE.MeshStandardMaterial({vertexColors:true,roughness:1,side:THREE.DoubleSide}),edgeMesh=new THREE.Mesh(edgeGeometry,mat);edgeMesh.receiveShadow=true;group.add(edgeMesh);resources.push(edgeGeometry,mat);metadata.triangles+=edgeGeometry.attributes.position.count/3;}else edgeGeometry.dispose();
  }
  if(hedges.length){
    const geometry=new THREE.CapsuleGeometry(.7,1.2,2,6);geometry.rotateX(Math.PI/2);geometry.translate(0,.7,0);
    const material=new THREE.MeshStandardMaterial({color:'#70875e',roughness:1}),mesh=new THREE.InstancedMesh(geometry,material,hedges.length),dummy=new THREE.Object3D();
    hedges.forEach((p,i)=>{dummy.position.set(p.x,height(p.x,p.z),p.z);dummy.rotation.set(0,p.angle,0);dummy.scale.set(1,p.height/1.4,p.length/2.6);dummy.updateMatrix();mesh.setMatrixAt(i,dummy.matrix);mesh.setColorAt(i,new THREE.Color(i%3?'#a6b792':'#c2c8a1'));});
    mesh.castShadow=true;mesh.receiveShadow=true;mesh.computeBoundingSphere();group.add(mesh);resources.push(geometry,material);metadata.hedgePatches=hedges.length;metadata.triangles+=(geometry.index?.count||geometry.attributes.position.count)/3*hedges.length;
  }
  // Saved commons are shared open land, never an extension of the neighboring
  // private gardens. Their quiet grass and narrow gravel walk remain un-fenced.
  // Three merged batches serve every common; none has its own draw call.
  const commonGrass=[],commonColors=[],commonWalk=[],commonSeating=new GeometryBuilder();
  const seat=new GeometryBuilder();
  for(const x of[-.70,.70])seat.box('#58695a',x,.28,0,.10,.56,.50);
  for(let i=0;i<3;i++)seat.box('#ad9876',0,.58,-.18+i*.18,1.85,.09,.13);
  seat.box('#a18d6e',0,.87,.23,1.85,.48,.08);
  const seatGeometry=seat.build();
  for(const common of commons){
    const polygon=common.polygon,center={x:polygon.reduce((sum,p)=>sum+p.x,0)/polygon.length,z:polygon.reduce((sum,p)=>sum+p.z,0)/polygon.length};
    let edge;
    polygon.forEach((a,i)=>{const b=polygon[(i+1)%polygon.length],length=Math.hypot(b.x-a.x,b.z-a.z);if(!edge||length>edge.length)edge={a,b,length};});
    if(!edge?.length)continue;
    const ux=(edge.b.x-edge.a.x)/edge.length,uz=(edge.b.z-edge.a.z)/edge.length,vx=-uz,vz=ux;
    const local=(u,v)=>({x:center.x+ux*u+vx*v,z:center.z+uz*u+vz*v});
    const along=polygon.map(p=>(p.x-center.x)*ux+(p.z-center.z)*uz),min=Math.min(...along),max=Math.max(...along);
    const tintA=new THREE.Color('#9caf80'),tintB=new THREE.Color('#a1b485');
    for(const triangle of THREE.ShapeUtils.triangulateShape(polygon.map(p=>new THREE.Vector2(p.x,p.z)),[])){
      const [a,b,c]=triangle.map(i=>polygon[i]),steps=Math.max(1,Math.ceil(Math.max(Math.hypot(a.x-b.x,a.z-b.z),Math.hypot(a.x-c.x,a.z-c.z),Math.hypot(b.x-c.x,b.z-c.z))/12));
      const at=(i,j)=>({x:a.x+(b.x-a.x)*i/steps+(c.x-a.x)*j/steps,z:a.z+(b.z-a.z)*i/steps+(c.z-a.z)*j/steps});
      const push=p=>{const u=(p.x-center.x)*ux+(p.z-center.z)*uz,color=tintA.clone().lerp(tintB,.5+.5*Math.sin(u*Math.PI/12));commonGrass.push(p.x,height(p.x,p.z)+.12,p.z);commonColors.push(color.r,color.g,color.b);};
      for(let i=0;i<steps;i++)for(let j=0;j<steps-i;j++){[at(i,j),at(i+1,j),at(i,j+1)].forEach(push);if(i+j<steps-1)[at(i+1,j),at(i+1,j+1),at(i,j+1)].forEach(push);}
    }
    let segments=0;
    for(let u=min+.025;u<max-.025;u+=4){
      const end=Math.min(u+4,max-.025),corners=[local(u,-.65),local(end,-.65),local(end,.65),local(u,.65)];
      if(!corners.every(p=>insideField(p,polygon)&&clearSite(p)))continue;
      for(const i of[0,1,2,0,2,3]){const p=corners[i];commonWalk.push(p.x,height(p.x,p.z)+.17,p.z);}segments++;
    }
    if(segments)metadata.commonPaths++;
    // Join the common's end to the nearest actual sidewalk across the public
    // verge. Never cross a private parcel, facility or the carriageway itself.
    for(const [u,sign] of [[min+.025,-1],[max-.025,1]]){
      const start=local(u,0);let nearest;
      for(const road of town.roads||[])for(let i=1;i<road.points.length;i++){
        const a=road.points[i-1],b=road.points[i],dx=b.x-a.x,dz=b.z-a.z,t=Math.max(0,Math.min(1,((start.x-a.x)*dx+(start.z-a.z)*dz)/(dx*dx+dz*dz||1)));
        const q={x:a.x+dx*t,z:a.z+dz*t},distance=Math.hypot(q.x-start.x,q.z-start.z),length=distance-streetWidth(road)/2-1.9;
        if(length<=0||length>12||((q.x-start.x)*ux+(q.z-start.z)*uz)*sign<distance*.96)continue;
        if(!nearest||length<nearest.length)nearest={length,dx:(q.x-start.x)/distance,dz:(q.z-start.z)/distance};
      }
      if(!nearest)continue;
      const vertices=[],steps=Math.ceil(nearest.length/2),nx=-nearest.dz*.65,nz=nearest.dx*.65;let valid=true;
      for(let i=0;i<steps;i++){
        const corners=[[i/steps,1],[i/steps,-1],[(i+1)/steps,-1],[(i+1)/steps,1]].map(([t,side])=>({x:start.x+nearest.dx*nearest.length*t+nx*side,z:start.z+nearest.dz*nearest.length*t+nz*side}));
        if(!corners.every(p=>clearSite(p)&&(town.parcels||[]).every(parcel=>!parcel.polygon?.length||!insideField(p,parcel.polygon)))){valid=false;break;}
        for(const j of[0,1,2,0,2,3]){const p=corners[j];vertices.push(p.x,height(p.x,p.z)+.17,p.z);}
      }
      if(valid){commonWalk.push(...vertices);metadata.commonEntrances++;}
    }
    // One small resting place leaves the centerline and backyard approaches
    // open. The entire seat and its clearance must fit the actual common.
    const resting=local(0,2.1),seatFits=[[-1.3,1.5],[1.3,1.5],[1.3,2.8],[-1.3,2.8]].map(([u,v])=>local(u,v)).every(p=>insideField(p,polygon)&&clearSite(p));
    if(seatFits){
      const transformed=seatGeometry.clone().rotateY(-Math.atan2(uz,ux)).translate(resting.x,height(resting.x,resting.z)+.14,resting.z);
      commonSeating.positions.push(...transformed.attributes.position.array);commonSeating.normals.push(...transformed.attributes.normal.array);commonSeating.colors.push(...transformed.attributes.color.array);transformed.dispose();metadata.commonBenches++;
    }
  }
  seatGeometry.dispose();
  function commonBatch(positions,colors,color,tag){
    if(!positions.length)return;
    const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));if(colors)geometry.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));geometry.computeVertexNormals();
    const material=new THREE.MeshStandardMaterial({color,vertexColors:!!colors,roughness:1,side:THREE.DoubleSide}),mesh=new THREE.Mesh(geometry,material);mesh.receiveShadow=true;mesh.userData[tag]=true;group.add(mesh);resources.push(geometry,material);metadata.triangles+=positions.length/9;
  }
  commonBatch(commonGrass,commonColors,'#ffffff','atlasCommonGreen');commonBatch(commonWalk,null,'#c0b699','atlasCommonWalk');
  const seatingGeometry=commonSeating.build();
  if(seatingGeometry.attributes.position.count){const material=new THREE.MeshStandardMaterial({vertexColors:true,roughness:1}),mesh=new THREE.Mesh(seatingGeometry,material);mesh.castShadow=true;mesh.receiveShadow=true;mesh.userData.atlasCommonSeating=true;group.add(mesh);resources.push(seatingGeometry,material);metadata.triangles+=seatingGeometry.attributes.position.count/3;}else seatingGeometry.dispose();
  return {metadata,fieldPolygons,commonPolygons,containsFarmland:p=>fieldPolygons.some(poly=>insideField(p,poly)),containsCommons:p=>commonPolygons.some(poly=>insideField(p,poly)),destroy(){group.removeFromParent();resources.forEach(r=>r.dispose());}};
}
