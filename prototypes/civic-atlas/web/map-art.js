import * as THREE from '/viewer/vendor/three.module.js';
import {GeometryBuilder} from '/viewer/lowpoly.js';
import {streetWidth} from '/viewer/roads.js';
import {frontageAccessQuad,pavementQuad} from './map-road-access.js';

function convexHull(points){
  const ordered=[...points].sort((a,b)=>a.x-b.x||a.z-b.z),cross=(o,a,b)=>(a.x-o.x)*(b.z-o.z)-(a.z-o.z)*(b.x-o.x),lower=[],upper=[];
  for(const p of ordered){while(lower.length>1&&cross(lower.at(-2),lower.at(-1),p)<=0)lower.pop();lower.push(p);}
  for(const p of ordered.toReversed()){while(upper.length>1&&cross(upper.at(-2),upper.at(-1),p)<=0)upper.pop();upper.push(p);}
  lower.pop();upper.pop();return lower.concat(upper);
}

// Joined intersection surfacing removes overlapping legacy sidewalk ribbons.
// All paths and widths still come from the saved street graph.
export function refineStreetSurfaces(scene,town){
  for(const mesh of scene.root.children)if(mesh.isMesh&&[1,2].includes(mesh.userData.atlasSurface))mesh.visible=false;
  const asphalt=[],sidewalk=[],curbs=[],paint=[],nodes=new Map();
  const vertex=(out,p,y)=>out.push(p.x,scene.heightAt(p.x,p.z)+y,p.z);
  const patch=(out,points,y)=>{
    if(points.length<3)return;
    for(const tri of THREE.ShapeUtils.triangulateShape(points.map(p=>new THREE.Vector2(p.x,p.z)),[])){
      const [a,b,c]=tri.toReversed().map(i=>points[i]),n=Math.max(1,Math.ceil(Math.max(Math.hypot(a.x-b.x,a.z-b.z),Math.hypot(a.x-c.x,a.z-c.z),Math.hypot(b.x-c.x,b.z-c.z))/3));
      const p=(i,j)=>({x:a.x+(b.x-a.x)*i/n+(c.x-a.x)*j/n,z:a.z+(b.z-a.z)*i/n+(c.z-a.z)*j/n});
      for(let i=0;i<n;i++)for(let j=0;j<n-i;j++){for(const q of[p(i,j),p(i+1,j),p(i,j+1)])vertex(out,q,y);if(i+j<n-1)for(const q of[p(i+1,j),p(i+1,j+1),p(i,j+1)])vertex(out,q,y);}
    }
  };
  const ribbon=(out,a,b,width,y)=>{
    const dx=b.x-a.x,dz=b.z-a.z,length=Math.hypot(dx,dz);if(length<.01)return;
    const nx=-dz/length,nz=dx/length,rows=Math.ceil(length/3),columns=Math.ceil(width/3),p=(i,j)=>({x:a.x+dx*i/rows+nx*(j/columns-.5)*width,z:a.z+dz*i/rows+nz*(j/columns-.5)*width});
    for(let i=0;i<rows;i++)for(let j=0;j<columns;j++){const points=[p(i,j),p(i,j+1),p(i+1,j+1),p(i+1,j)];for(const index of[0,1,2,0,2,3])vertex(out,points[index],y);}
  };
  for(const road of town.roads)for(const reverse of[false,true]){
    const points=reverse?[...road.points].reverse():road.points,a=points[0],b=points[1];if(!b)continue;const length=Math.hypot(b.x-a.x,b.z-a.z),key=`${a.x.toFixed(2)}:${a.z.toFixed(2)}`;
    if(!nodes.has(key))nodes.set(key,{...a,arms:[]});nodes.get(key).arms.push({dx:(b.x-a.x)/length,dz:(b.z-a.z)/length,width:streetWidth(road),major:road.roadClass==='arterial'});
  }
  const junctions=[...nodes.values()].filter(n=>n.arms.length>2||(n.arms.length===2&&n.arms[0].dx*n.arms[1].dx+n.arms[0].dz*n.arms[1].dz>-.90));
  junctions.forEach(n=>n.reach=Math.max(...n.arms.map(a=>a.width))/2+5);
  for(const road of town.roads){
    const width=streetWidth(road);
    for(let i=1;i<road.points.length;i++){
      const a=road.points[i-1],b=road.points[i],dx=b.x-a.x,dz=b.z-a.z,length=Math.hypot(dx,dz);if(length<.01)continue;
      ribbon(sidewalk,a,b,width+4,.055);ribbon(asphalt,a,b,width,.17);
      for(const side of[-1,1])for(let d=0;d<length;d+=2){
        const p={x:a.x+dx*d/length-dz/length*width/2*side,z:a.z+dz*d/length+dx/length*width/2*side},q={x:a.x+dx*Math.min(length,d+2)/length-dz/length*width/2*side,z:a.z+dz*Math.min(length,d+2)/length+dx/length*width/2*side};
        if(junctions.some(n=>Math.hypot(p.x-n.x,p.z-n.z)<n.reach+1))continue;ribbon(curbs,p,q,.27,.205);
      }
    }
  }
  const pavement=town.roads.flatMap(road=>road.points.slice(1).map((b,i)=>pavementQuad(road.points[i],b,streetWidth(road))).filter(Boolean));
  for(const node of junctions){
    const hull=extra=>convexHull(node.arms.flatMap(a=>[-1,1].map(side=>({x:node.x+a.dx*node.reach-a.dz*(a.width/2+extra)*side,z:node.z+a.dz*node.reach+a.dx*(a.width/2+extra)*side}))));
    patch(sidewalk,hull(2),.07);const inner=hull(0);patch(asphalt,inner,.18);pavement.push(inner);
    for(let i=0;i<inner.length;i++){
      const a=inner[i],b=inner[(i+1)%inner.length],mid={x:(a.x+b.x)/2-node.x,z:(a.z+b.z)/2-node.z};
      if(node.arms.some(arm=>mid.x*arm.dx+mid.z*arm.dz>node.reach-.5&&Math.abs(mid.x*arm.dz-mid.z*arm.dx)<arm.width/2+.1))continue;ribbon(curbs,a,b,.27,.215);
    }
    if(node.arms.length<3||!node.arms.some(a=>a.major))continue;
    for(const arm of node.arms){
      const along=node.reach+2.7;
      for(let x=-arm.width/2+1;x<arm.width/2-1;x+=1.1){
        const p={x:node.x+arm.dx*along-arm.dz*x,z:node.z+arm.dz*along+arm.dx*x};
        ribbon(paint,{x:p.x-arm.dx*1.2,z:p.z-arm.dz*1.2},{x:p.x+arm.dx*1.2,z:p.z+arm.dz*1.2},.52,.23);
      }
    }
  }
  for(const [positions,color,texture]of[[sidewalk,'#c5c8ba',2],[asphalt,'#7e898a',1],[curbs,'#e2e0cf',null],[paint,'#eae7d7',null]]){
    const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geometry.computeVertexNormals();
    const mesh=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color,roughness:1,side:THREE.DoubleSide}));if(texture!==null)mesh.userData.atlasSurface=texture;mesh.receiveShadow=true;scene.root.add(mesh);
  }
  // The shared viewer's civic access mesh starts at the saved road centerline.
  // Clip its decorative pavement to the real road edge, preserving the saved
  // route and entrance. Keep the mesh identity for artwork fallback toggles.
  const accessMesh=scene.townDressing?.meshes.find(mesh=>mesh.isMesh&&!mesh.isInstancedMesh);
  if(accessMesh){
    const access=[],premises=new Map(town.premises.map(p=>[p.id,p])),roads=new Map(town.roads.map(r=>[r.id,{...r,width:streetWidth(r)}]));
    let accepted=0,omitted=0;const quads=[];
    for(const site of scene.townDressing.plan.landmarks){
      if(!site.access)continue;
      const home=premises.get(site.premiseId),quad=frontageAccessQuad(site.access,roads.get(home?.roadId),site.kind==='park'?2:3.2,pavement);
      if(!quad){omitted++;continue;}patch(access,quad,.20);quads.push({premiseId:site.premiseId,polygon:quad});accepted++;
    }
    const geometry=new THREE.BufferGeometry(),color=new THREE.Color('#9eaaa6').toArray();geometry.setAttribute('position',new THREE.Float32BufferAttribute(access,3));geometry.setAttribute('color',new THREE.Float32BufferAttribute(access.map((_,i)=>color[i%3]),3));geometry.computeVertexNormals();
    accessMesh.geometry.dispose();accessMesh.geometry=geometry;
    accessMesh.userData.atlasAccess={accepted,omitted,source:'saved-frontage',quads};
  }
  // Decorative traffic furniture is proportional to this small rural center.
  // Saved electrical poles and utility equipment are separate and untouched.
  const signals=scene.townDressing?.plan.signals,signalMesh=scene.townDressing?.meshes[4];
  if(town.atlasDesign&&signals?.length&&signalMesh){
    const shops=town.premises.filter(p=>p.premiseType==='commercial'),center=shops.length?{x:shops.reduce((sum,p)=>sum+p.x,0)/shops.length,z:shops.reduce((sum,p)=>sum+p.z,0)/shops.length}:town.atlasDesign.focus;
    const nearest=[...signals].sort((a,b)=>Math.hypot(a.junction.x-center.x,a.junction.z-center.z)-Math.hypot(b.junction.x-center.x,b.junction.z-center.z))[0].junction;
    signals.forEach((signal,i)=>{if(Math.hypot(signal.junction.x-nearest.x,signal.junction.z-nearest.z)>1)signalMesh.setMatrixAt(i,new THREE.Matrix4().makeScale(0,0,0));});signalMesh.instanceMatrix.needsUpdate=true;signalMesh.computeBoundingSphere();
  }
}

// Decorative rendering only: no roads, properties or network records are created.
export function addStreetMarkings(scene,town) {
  const vertices=[];
  for(const road of town.roads){
    if(!['arterial','collector'].includes(road.roadClass))continue;
    let along=0;
    const total=road.lengthM||road.length;
    for(let i=1;i<road.points.length;i++){
      const a=road.points[i-1],b=road.points[i],dx=b.x-a.x,dz=b.z-a.z,length=Math.hypot(dx,dz);
      if(length<.01)continue;
      // A short gap at segment junctions keeps paint away from intersections.
      for(let d=0;d<length;d+=.8){
        const here=along+d,end=Math.min(d+.8,length);
        if(here<12||here>total-12||here%9>4)continue;
        const px=a.x+dx*d/length,pz=a.z+dz*d/length,qx=a.x+dx*end/length,qz=a.z+dz*end/length;
        const nx=-dz/length*.16,nz=dx/length*.16;
        for(const [x,z]of [[px+nx,pz+nz],[px-nx,pz-nz],[qx-nx,qz-nz],[px+nx,pz+nz],[qx-nx,qz-nz],[qx+nx,qz+nz]])vertices.push(x,scene.heightAt(x,z)+.24,z);
      }
      along+=length;
    }
  }
  const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));
  const mesh=new THREE.Mesh(geo,new THREE.MeshBasicMaterial({color:'#f1edda',side:THREE.DoubleSide,transparent:true,opacity:.72,depthWrite:false}));
  scene.root.add(mesh);
}

export function softenTrees(scene){
  for(let kind=0;kind<3;kind++){
    const mesh=scene.townDressing?.meshes[kind];if(!mesh)continue;
    const b=new GeometryBuilder(),trunk=new THREE.CylinderGeometry(.22,.35,2.8,6),crown=kind===2?new THREE.ConeGeometry(2,4.8,10):new THREE.SphereGeometry(2.35,10,8);
    b.add(trunk,'#88775c',0,1.4,0);
    b.add(crown,kind===2?'#527e5e':kind?'#90b386':'#719b77',0,kind===2?4:3.75,0,1,kind===1?1.10:.96,1);
    trunk.dispose();crown.dispose();mesh.geometry.dispose();mesh.geometry=b.build();mesh.computeBoundingSphere();
  }
}

export function makeStreetLabels(element,scene,town){
  const byName=new Map();
  for(const r of town.roads)if(r.name&&(!byName.has(r.name)||(r.lengthM||r.length)>(byName.get(r.name).lengthM||byName.get(r.name).length)))byName.set(r.name,r);
  const labels=[...byName.values()].map(road=>{
    const points=road.points,i=Math.floor((points.length-1)/2),a=points[i],b=points[i+1]||a;
    const x=(a.x+b.x)/2,z=(a.z+b.z)/2;
    const el=document.createElement('span');el.textContent=road.name;el.setAttribute('aria-hidden','true');
    el.style.cssText='position:absolute;pointer-events:none;z-index:1;white-space:nowrap;font:600 10px Arial,sans-serif;letter-spacing:.3px;color:#354f50;text-shadow:0 1px 3px #fff,0 -1px 3px #fff;transform-origin:center;';
    element.append(el);
    return {el,position:new THREE.Vector3(x,scene.heightAt(x,z)+1,z),next:new THREE.Vector3(b.x,scene.heightAt(b.x,b.z)+1,b.z),priority:road.roadClass==='arterial'?0:road.roadClass==='collector'?1:2};
  });
  const design=town.atlasDesign;
  if(design){
    const places=[...(design.neighborhoods||[]).map(p=>({...p,kind:'district'})),...(design.parks||[]).map(p=>({name:p.name,kind:'park',x:(Math.min(...p.polygon.map(q=>q.x))+Math.max(...p.polygon.map(q=>q.x)))/2,z:Math.min(...p.polygon.map(q=>q.z))*.12+Math.max(...p.polygon.map(q=>q.z))*.88}))];
    if(design.river?.centerline?.length){const p=design.river.centerline[Math.floor(design.river.centerline.length/2)];places.push({...p,name:design.river.name,kind:'river'});}
    for(const p of places){
      const el=document.createElement('span');el.textContent=p.name;el.setAttribute('aria-hidden','true');
      el.style.cssText=`position:absolute;pointer-events:none;z-index:1;white-space:nowrap;font:600 11px Georgia,serif;letter-spacing:.3px;color:${p.kind==='river'?'#365e70':'#4d674e'};text-shadow:0 1px 3px #fff,0 -1px 3px #fff;`;
      element.append(el);labels.push({el,position:new THREE.Vector3(p.x,scene.heightAt(p.x,p.z)+1,p.z),next:new THREE.Vector3(p.x+1,scene.heightAt(p.x,p.z)+1,p.z),priority:p.kind==='district'?1:-1,fixed:true});
    }
  }
  function update(){
    const w=element.clientWidth,h=element.clientHeight,distance=scene.camera.position.distanceTo(scene.controls.target),boxes=[];
    const sorted=labels.map(label=>{const p=label.position.clone().project(scene.camera),q=label.next.clone().project(scene.camera);return {...label,p,q,x:(p.x*.5+.5)*w,y:(-p.y*.5+.5)*h};}).sort((a,b)=>a.priority-b.priority||Math.hypot(a.x-w/2,a.y-h/2)-Math.hypot(b.x-w/2,b.y-h/2));
    for(const l of sorted){
      l.el.hidden=true;
      if(distance>scene.span*1.3||l.p.z>1||l.x<90||l.x>w-100||l.y<65||l.y>h-65||boxes.length>=8)continue;
      const width=l.el.textContent.length*5.7+16,box={x:l.x-width/2,y:l.y-18,w:width,h:36};
      if(boxes.some(b=>box.x<b.x+b.w&&box.x+box.w>b.x&&box.y<b.y+b.h&&box.y+box.h>b.y))continue;
      let angle=l.fixed?0:Math.atan2(-(l.q.y-l.p.y)*h,(l.q.x-l.p.x)*w)*180/Math.PI;
      if(angle>90)angle-=180;if(angle< -90)angle+=180;
      l.el.hidden=false;l.el.style.left=l.x+'px';l.el.style.top=l.y+'px';l.el.style.transform=`translate(-50%,-50%) rotate(${angle}deg)`;boxes.push(box);
    }
  }
  return {update,destroy(){labels.forEach(l=>l.el.remove());}};
}

const seedHash=value=>{let n=2166136261;for(const c of String(value)){n^=c.charCodeAt(0);n=Math.imul(n,16777619);}return n>>>0;};
function texture(kind){
  const canvas=document.createElement('canvas');canvas.width=canvas.height=128;
  const ctx=canvas.getContext('2d');ctx.fillStyle='#ffffff';ctx.fillRect(0,0,128,128);
  for(let y=0;y<128;y+=2)for(let x=0;x<128;x+=2){const v=241+seedHash(`${kind}:${x}:${y}`)%15;ctx.fillStyle=`rgb(${v},${v},${v})`;ctx.fillRect(x,y,2,2);}
  if(kind==='roof')for(let y=0;y<128;y+=16){ctx.fillStyle='#d8dbda';ctx.fillRect(0,y,128,1);for(let x=(y%32?0:16);x<128;x+=32){ctx.fillStyle='#e4e6e5';ctx.fillRect(x,y,1,16);}}
  if(kind==='siding')for(let y=0;y<128;y+=12){ctx.fillStyle='#e0e3de';ctx.fillRect(0,y,128,1);}
  const map=new THREE.CanvasTexture(canvas);map.colorSpace=THREE.SRGBColorSpace;map.wrapS=map.wrapT=THREE.RepeatWrapping;map.anisotropy=4;return map;
}
function inside(p,polygon){let result=false;for(let i=0,j=polygon.length-1;i<polygon.length;j=i++){const a=polygon[i],b=polygon[j];if((a.z>p.z)!==(b.z>p.z)&&p.x<(b.x-a.x)*(p.z-a.z)/(b.z-a.z)+a.x)result=!result;}return result;}
function segmentDistance(p,a,b){const dx=b.x-a.x,dz=b.z-a.z,t=Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.z-a.z)*dz)/(dx*dx+dz*dz||1)));return Math.hypot(p.x-a.x-t*dx,p.z-a.z-t*dz);}

// Yards are drawn from retained parcel polygons. Planting and fences are visual
// dressing, like the shared viewer's trees; they create no vegetation/asset records.
export function enrichNeighborhood(scene,town){
  const parcels=new Map((town.parcels||[]).map(p=>[p.premiseId,p]));
  const lawnPositions=[],lawnColors=[],lawnUV=[],border=[],hedges=[],shrubs=[],trees=[];
  const lawns=['#91aa7d','#a5b88c','#879f77','#b0bc94','#96ad83'];
  const roads=town.roads.flatMap(r=>r.points.slice(1).map((b,i)=>({a:r.points[i],b,width:r.pavementWidthM||8})));
  const nearRoad=(p,r)=>roads.some(s=>segmentDistance(p,s.a,s.b)<s.width/2+r+2);
  const buildingPolygons=(town.buildings||[]).map(b=>b.footprint?.polygon).filter(Boolean);
  const existingTrees=scene.townDressing?.plan.trees||[];
  const safe=(p,r,polygon)=>!existingTrees.some(t=>Math.hypot(p.x-t.x,p.z-t.z)<r+2*(t.scale||1))&&inside(p,polygon)&&polygon.every((a,i)=>segmentDistance(p,a,polygon[(i+1)%polygon.length])>r)&&!nearRoad(p,r)&&!buildingPolygons.some(poly=>inside(p,poly)||poly.some((a,i)=>segmentDistance(p,a,poly[(i+1)%poly.length])<r+1));
  for(const home of town.premises){
    const polygon=parcels.get(home.id)?.polygon;if(!polygon||polygon.length<3)continue;
    const residential=home.premiseType==='residential',seed=seedHash(home.id),color=new THREE.Color(residential?lawns[seed%lawns.length]:'#b8b9a5');
    const contour=polygon.map(p=>new THREE.Vector2(p.x,p.z)),triangles=THREE.ShapeUtils.triangulateShape(contour,[]);
    for(const triangle of triangles)for(const i of triangle){const p=polygon[i];lawnPositions.push(p.x,scene.heightAt(p.x,p.z)+.02,p.z);lawnUV.push(p.x/11,p.z/11);lawnColors.push(color.r,color.g,color.b);}
    const front=home.front||home;
    for(let i=0;i<polygon.length;i++){
      const a=polygon[i],b=polygon[(i+1)%polygon.length],length=Math.hypot(b.x-a.x,b.z-a.z),mid={x:(a.x+b.x)/2,z:(a.z+b.z)/2};
      if(length<2)continue;
      border.push(a.x,scene.heightAt(a.x,a.z)+.10,a.z,b.x,scene.heightAt(b.x,b.z)+.10,b.z);
      if(residential&&length>5&&!nearRoad(mid,1)&&Math.hypot(mid.x-front.x,mid.z-front.z)>12&&seed%3!==0){
        const steps=Math.ceil(length/5);for(let j=0;j<steps;j++){
          const t=(j+.5)/steps,p={x:a.x+(b.x-a.x)*t,z:a.z+(b.z-a.z)*t};
          if(!nearRoad(p,1))hedges.push({x:p.x,z:p.z,length:length/steps-.15,angle:Math.atan2(b.x-a.x,b.z-a.z),tone:seed%3});
        }
      }
    }
    if(!residential)continue;
    const minX=Math.min(...polygon.map(p=>p.x)),maxX=Math.max(...polygon.map(p=>p.x)),minZ=Math.min(...polygon.map(p=>p.z)),maxZ=Math.max(...polygon.map(p=>p.z));
    const chosen=[];
    const treeLimit=seed%3===0?2:1;
    for(let i=0;i<48&&chosen.length<treeLimit+2;i++){
      const h=seedHash(`${home.id}:yard:${i}`),p={x:minX+(h%1000)/1000*(maxX-minX),z:minZ+((h>>>10)%1000)/1000*(maxZ-minZ)};
      const asTree=chosen.length<treeLimit,radius=asTree?2.5:1.0;
      // Leave the recorded frontage/access corridor clear.
      if(!safe(p,radius,polygon)||segmentDistance(p,home,front)<radius+2||chosen.some(q=>Math.hypot(p.x-q.x,p.z-q.z)<radius+2.5))continue;
      chosen.push(p);if(asTree)trees.push({...p,scale:1.03+(h%40)/100});else shrubs.push({...p,scale:.8+(h%30)/100});
    }
  }
  const lawnGeo=new THREE.BufferGeometry();lawnGeo.setAttribute('position',new THREE.Float32BufferAttribute(lawnPositions,3));lawnGeo.setAttribute('color',new THREE.Float32BufferAttribute(lawnColors,3));lawnGeo.setAttribute('uv',new THREE.Float32BufferAttribute(lawnUV,2));lawnGeo.computeVertexNormals();
  const grass=texture('grass'),roof=texture('roof'),siding=texture('siding');
  const lawn=new THREE.Mesh(lawnGeo,new THREE.MeshStandardMaterial({vertexColors:true,map:grass,side:THREE.DoubleSide,roughness:1}));lawn.receiveShadow=true;scene.root.add(lawn);
  lawn.userData.atlasSurface=0;
  if(lawnPositions.length){scene.houseMeshes.plot.visible=false;scene.pickMeshes=scene.pickMeshes.filter(m=>m!==scene.houseMeshes.plot);}
  const borderGeo=new THREE.BufferGeometry();borderGeo.setAttribute('position',new THREE.Float32BufferAttribute(border,3));scene.root.add(new THREE.LineSegments(borderGeo,new THREE.LineBasicMaterial({color:'#d1d1b7',transparent:true,opacity:.60,depthWrite:false})));
  const detail=new THREE.Group();scene.root.add(detail);
  const dummy=new THREE.Object3D();
  function instances(geo,items,mat,transform){const mesh=new THREE.InstancedMesh(geo,mat,items.length);items.forEach((p,i)=>{dummy.position.set(p.x,scene.heightAt(p.x,p.z),p.z);dummy.rotation.set(0,p.angle||0,0);dummy.scale.setScalar(p.scale||1);transform?.(dummy,p);dummy.updateMatrix();mesh.setMatrixAt(i,dummy.matrix);});mesh.castShadow=true;mesh.receiveShadow=true;mesh.computeBoundingSphere();detail.add(mesh);return mesh;}
  const hedgeMaterial=new THREE.MeshStandardMaterial({color:'#6f885c',roughness:1});
  const hedge=new THREE.CapsuleGeometry(.43,.48,2,6);hedge.rotateX(Math.PI/2);hedge.translate(0,.43,0);
  instances(hedge,hedges,hedgeMaterial,(d,p)=>{d.scale.set(.8,.68+p.tone*.10,p.length/1.34);});
  instances(new THREE.IcosahedronGeometry(.9,1),shrubs,new THREE.MeshStandardMaterial({color:'#7c975e',roughness:1}),(d,p)=>d.position.y+=.65);
  const b=new GeometryBuilder(),trunk=new THREE.CylinderGeometry(.17,.28,3,6),leaf=new THREE.SphereGeometry(1,9,7);
  b.add(trunk,'#8a7964',0,1.5,0);
  for(const [x,y,z,s,c]of [[0,4,0,2,'#71986b'],[-1.1,3.6,.4,1.4,'#83a576'],[.9,4.5,-.3,1.5,'#8cae7c'],[.3,3.5,1,1.5,'#648a61']])b.add(leaf,c,x,y,z,s,s*.95,s);
  trunk.dispose();leaf.dispose();instances(b.build(),trees,new THREE.MeshStandardMaterial({vertexColors:true,roughness:1})).userData.atlasTreeKind=0;
  const roofColors=['#626b70','#827b6e','#637572','#8e7663','#55666d','#7b8076'];
  for(const mesh of scene.roofBatches){
    const pos=mesh.geometry.attributes.position,uv=[];for(let i=0;i<pos.count;i++)uv.push(pos.getX(i)*3,pos.getZ(i)*3);
    mesh.geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));mesh.material.map=roof;mesh.material.needsUpdate=true;
    mesh.userData.premiseIndices.forEach((index,i)=>mesh.setColorAt(i,new THREE.Color(roofColors[seedHash(town.premises[index].id)%roofColors.length])));if(mesh.instanceColor)mesh.instanceColor.needsUpdate=true;
  }
  const walls=scene.houseMeshes.walls;walls.material.map=siding;walls.material.needsUpdate=true;
  const wallColors=['#efe8d9','#d9dfd5','#e1d5bf','#d4dedd','#f0eee4'];
  walls.userData.premiseIndices.forEach((index,i)=>walls.setColorAt(i,new THREE.Color(wallColors[seedHash(town.premises[index].id)%wallColors.length])));walls.instanceColor.needsUpdate=true;
  return {update(){detail.visible=scene.camera.position.distanceTo(scene.controls.target)<scene.span*1.1;},destroy(){grass.dispose();roof.dispose();siding.dispose();},stats:{parcels:parcels.size,yardTrees:trees.length,shrubs:shrubs.length,hedgeSegments:hedges.length}};
}
