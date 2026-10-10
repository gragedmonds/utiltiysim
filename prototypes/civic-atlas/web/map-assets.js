import * as THREE from '/viewer/vendor/three.module.js';
import {GeometryBuilder,hash,roofGeometry} from '/viewer/lowpoly.js';

// These are illustrative asset skins. Source positions, footprints, categories,
// heights, occupancy and every simulation record remain unchanged.
export function leafyTree(kind=0){
  const b=new GeometryBuilder(),trunk=new THREE.CylinderGeometry(.16,.31,3.6,7),leaf=new THREE.SphereGeometry(1,9,7);
  b.add(trunk,kind===1?'#b9b9a0':'#796d58',0,1.8,0);
  const shapes=kind===0?[[0,3.8,0,1.6,1.5,1.5],[-1,3.5,.5,1.1,1.25,1.15],[.9,3.7,.6,1.25,1.35,1.1],[.4,4.8,-.3,1.3,1.15,1.25],[-.75,4.4,-.8,1.25,1.1,1.1],[.7,3.3,-.9,1.15,1.0,1.1]]:
    kind===1?[[0,4.2,0,1.35,1.9,1.2],[-.85,4.3,.2,1,1.5,.9],[.75,4.8,-.2,.95,1.45,1.0],[.2,5.6,.1,.9,1.15,.9],[-.6,3.5,-.7,.95,1.3,.9]]:
    [[0,4,0,1.7,1.5,1.55],[-.9,4.1,.4,1.2,1.25,1.25],[.8,4.3,.7,1.2,1.2,1.1],[.65,4.9,-.4,1.3,1.15,1.25],[-.8,4.9,-.3,1.05,1.1,1.15]];
  const colors=kind===0?['#60844f','#739959','#62854c','#8ca56a','#769a59','#597b49']:kind===1?['#8cab6c','#779858','#95b473','#a0b97c','#719052']:['#4f7955','#608961','#678f64','#81a075','#6d956d'];
  shapes.forEach((p,i)=>b.add(leaf,colors[i%colors.length],...p));
  trunk.dispose();leaf.dispose();return b.build();
}
export function replaceTreeAssets(scene){
  scene.townDressing?.meshes.slice(0,3).forEach((mesh,i)=>{
    mesh.userData.atlasTreeKind=i;
    mesh.userData.atlasBaseTrees=true;
    mesh.geometry.dispose();mesh.geometry=leafyTree(i);mesh.material=mesh.material.clone();mesh.material.flatShading=false;mesh.material.roughness=1;mesh.computeBoundingSphere();
  });
}

function civicGeometry(type,stories,variant){
  const b=new GeometryBuilder(),brick=['#ac8068','#c0ac8d','#b99880'][variant],trim='#e9e3cf',glass='#6d8c90',roof='#6f7876';
  const pane=(x,y,z,w,h,side=0)=>{
    const ry=side===0?Math.PI:side*Math.PI/2;
    b.plane(trim,x,y,z,w+.014,h+.018,0,ry).plane(glass,x+side*.002,y,z-(side===0?.002:0),w,h,0,ry);
  };
  if(type==='storefront'){
    b.box(brick,0,.47,0,.96,.94,.92).box(roof,0,.953,0,.98,.026,.94);
    for(const x of [-.473,.473])b.box(trim,x,.989,0,.025,.070,.95);
    for(const z of [-.463,.463])b.box(trim,0,.989,z,.98,.070,.025);
    const awning=['#486e68','#8f5546','#566881'][variant],shopHeight=stories>1?.42:.72;
    for(const x of[-.28,.28])pane(x,shopHeight*.47,-.465,.29,shopHeight*.62);
    pane(0,shopHeight*.45,-.465,.13,shopHeight*.82);
    b.box(awning,0,shopHeight*.96,-.50,.9,.026,.15).box(trim,0,shopHeight*1.10,-.465,.73,.08,.025);
    if(stories>1)for(const x of[-.31,-.10,.10,.31])pane(x,.73,-.465,.11,.23);
    for(const x of[-.28,.22]){b.box('#b1b3a5',x,.993,.15,.12,.085,.15).box('#626f6c',x,1.038,.15,.10,.007,.11);}
    // Brick courses make the side walls readable at property scale.
    for(let y=.09;y<.9;y+=.075)for(const x of[-.484,.484])b.box('#987e67',x,y,0,.002,.004,.88);
  } else if(type==='school'){
    b.box('#be9d7a',0,.40,.20,.92,.80,.47).box('#b3a181',-.34,.31,-.16,.24,.62,.42).box('#b3a181',.34,.31,-.16,.24,.62,.42);
    b.box(roof,0,.81,.20,.94,.025,.49).box(roof,-.34,.63,-.16,.26,.025,.44).box(roof,.34,.63,-.16,.26,.025,.44);
    for(const y of[.27,.59])for(let x=-.4;x<.44;x+=.1)pane(x,y,-.037,.065,.19);
    for(const x of[-.34,.34])for(let z=-.31;z<.05;z+=.1)b.plane(glass,x+(x<0?.122:-.122),.34,z,.065,.23,0,x<0?Math.PI/2:-Math.PI/2);
    b.box(trim,0,.15,-.12,.25,.025,.17).box('#497d7d',0,.49,-.1,.22,.03,.14);
    for(const x of[-.10,.10])b.box('#a5aba0',x,.24,-.15,.007,.46,.007);
    pane(0,.21,-.042,.17,.31);
    for(const x of[-.28,.25])b.box('#a3aca3',x,.87,.22,.09,.10,.13);
  } else if(type==='pump_house'){
    b.box('#c9baa0',0,.40,0,.88,.80,.86).box('#697b7b',0,.825,0,.94,.045,.92);
    pane(-.22,.46,-.435,.18,.25);b.box('#5e7774',.2,.27,-.439,.2,.52,.012);
    for(let y=.13;y<.65;y+=.08)b.box('#7f8e87',-.448,y,.10,.016,.013,.3);
    b.box('#a7b0a5',.18,.89,.15,.16,.09,.23);
  } else {
    // Depots and industrial customers remain their own real categories.
    const depot=type==='depot',wall=depot?'#b3ad99':'#a4b1aa';
    b.box(wall,0,.44,0,.96,.88,.94).box(roof,0,.895,0,.99,.03,.97);
    for(let x=-.4;x<=.41;x+=depot?.24:.20){b.box('#778780',x,.29,-.477,.16,.53,.008);for(let y=.07;y<.52;y+=.065)b.box('#bac0b3',x,y,-.484,.16,.006,.003);}
    for(const x of[-.487,.487])for(let z=-.43;z<.45;z+=.085)b.box('#899b91',x,.46,z,.004,.83,.007);
    for(const x of[-.29,.28])for(const z of[-.19,.20])b.box('#b8c7c5',x,.924,z,.13,.025,.23).box('#789391',x,.938,z,.11,.006,.20);
    b.box('#c8c5b1',.32,.33,-.22,.25,.66,.48);pane(.32,.4,-.466,.17,.24);
    for(const x of[-.35,0,.30])b.box('#9aa99f',x,.95,.32,.1,.10,.13);
  }
  return b.build();
}

export function replaceCivicAssets(scene,town){
  const supported=new Set(['storefront','school','industrial','depot','pump_house']);
  const homes=town.premises.filter(p=>supported.has(p.buildingType));
  const indices=new Map(town.premises.map((p,i)=>[p.id,i]));
  for(const mesh of scene.townDressing?.meshes||[]){
    const ids=mesh.userData.premiseIndices;
    if(ids?.some(i=>supported.has(town.premises[i]?.buildingType))){mesh.visible=false;scene.pickMeshes=scene.pickMeshes.filter(m=>m!==mesh);}
  }
  const groups=new Map();for(const p of homes){const variant=hash(p.id)%3,key=`${p.buildingType}:${p.stories}:${variant}`;if(!groups.has(key))groups.set(key,{type:p.buildingType,stories:p.stories||1,variant,homes:[]});groups.get(key).homes.push(p);}
  for(const g of groups.values()){
    const mesh=new THREE.InstancedMesh(civicGeometry(g.type,g.stories,g.variant),new THREE.MeshStandardMaterial({vertexColors:true,roughness:.9,side:THREE.DoubleSide}),g.homes.length),dummy=new THREE.Object3D();
    mesh.userData.premiseIndices=g.homes.map(p=>indices.get(p.id));
    g.homes.forEach((p,i)=>{dummy.position.set(p.x,p.elevationM??scene.heightAt(p.x,p.z),p.z);dummy.rotation.set(0,-p.angle+(p.side===-1?Math.PI:0),0);dummy.scale.set(p.width,p.height,p.depth);dummy.updateMatrix();mesh.setMatrixAt(i,dummy.matrix);});
    mesh.castShadow=true;mesh.receiveShadow=true;mesh.computeBoundingSphere();scene.root.add(mesh);scene.pickMeshes.push(mesh);
  }
}

export function addResidentialCharacter(scene,town){
  const b=new GeometryBuilder(),gable=roofGeometry(0);
  const meshes=[];
  // Decoration stays at the retained facade/roof envelope. It does not add rooms.
  for(const p of town.premises.filter(p=>p.premiseType==='residential'&&p.buildingType==='detached')){
    const local=new GeometryBuilder(),old=p.yearBuilt<1945,tall=p.stories>1,style=hash(p.id)%3,roofColor=['#697071','#877966','#60716b'][style];
    const trim=old?'#e6deca':'#e9e9dc';
    if(tall&&p.roof==='gable'){
      // A small rooflight/dormer expresses the existing attic, with no floor-area claim.
      local.box(trim,0,p.height+.52,-p.depth*.16,p.width*.22,.95,p.depth*.25);
      local.add(gable,roofColor,0,p.height+1.0,-p.depth*.16,p.width*.25,.5,p.depth*.29);
      local.plane('#64878a',0,p.height+.57,-p.depth*.286,p.width*.12,.5,0,Math.PI);
    }
    const porchWidth=p.width*(old?.52:.30),front=-p.depth/2-.40;
    local.box('#ccc6b2',0,.15,front,porchWidth,.28,.9);
    local.box(trim,0,tall?2.5:2.35,front,porchWidth+.18,.13,1.05);
    for(const x of[-porchWidth*.43,porchWidth*.43])local.box(trim,x,1.2,front-.3,.13,2.4,.13);
    if(old)for(const side of[-1,1])for(let y=.6;y<p.height-.4;y+=tall?2.75:4){
      const x=side*p.width*.28;for(const sx of[-1,1])local.box('#687e72',x+sx*p.width*.083,y+.8,-p.depth/2-.03,p.width*.035,.95,.055);
    }
    const geo=local.build(),mat=new THREE.MeshStandardMaterial({vertexColors:true,roughness:.9,side:THREE.DoubleSide});
    const mesh=new THREE.Mesh(geo,mat);mesh.position.set(p.x,p.elevationM??scene.heightAt(p.x,p.z),p.z);mesh.rotation.y=-p.angle+(p.side===-1?Math.PI:0);mesh.updateMatrix();
    const transformed=geo.clone().applyMatrix4(mesh.matrix);b.positions.push(...transformed.attributes.position.array);b.normals.push(...transformed.attributes.normal.array);b.colors.push(...transformed.attributes.color.array);transformed.dispose();geo.dispose();mat.dispose();
  }
  gable.dispose();
  const mesh=new THREE.Mesh(b.build(),new THREE.MeshStandardMaterial({vertexColors:true,roughness:.9,side:THREE.DoubleSide}));mesh.castShadow=true;mesh.receiveShadow=true;scene.root.add(mesh);meshes.push(mesh);
  return {update(){mesh.visible=scene.camera.position.distanceTo(scene.controls.target)<scene.span*.85;}};
}

function contains(p,polygon){let yes=false;for(let i=0,j=polygon.length-1;i<polygon.length;j=i++){const a=polygon[i],b=polygon[j];if((a.z>p.z)!==(b.z>p.z)&&p.x<(b.x-a.x)*(p.z-a.z)/(b.z-a.z)+a.x)yes=!yes;}return yes;}
function distToSegment(p,a,b){const dx=b.x-a.x,dz=b.z-a.z,t=Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.z-a.z)*dz)/(dx*dx+dz*dz||1)));return Math.hypot(p.x-a.x-t*dx,p.z-a.z-t*dz);}
const smooth=t=>t*t*(3-2*t);
function noise(x,z){const a=Math.floor(x),b=Math.floor(z),fx=smooth(x-a),fz=smooth(z-b),n=(i,j)=>(hash(`${i}:${j}`)%1000)/1000;return (n(a,b)*(1-fx)+n(a+1,b)*fx)*(1-fz)+(n(a,b+1)*(1-fx)+n(a+1,b+1)*fx)*fz;}
export function groundTexture(scene,town){
  const canvas=document.createElement('canvas');canvas.width=canvas.height=256;const ctx=canvas.getContext('2d'),pixels=ctx.createImageData(256,256);
  for(let z=0;z<256;z++)for(let x=0;x<256;x++){
    const broad=noise(x/55,z/55),fine=noise(x/9,z/9),grain=(hash(`${x}:grain:${z}`)%15)/15;
    const value=Math.round(204+broad*30+fine*12+grain*7),i=(z*256+x)*4;
    pixels.data[i]=value;pixels.data[i+1]=value;pixels.data[i+2]=value;pixels.data[i+3]=255;
  }
  ctx.putImageData(pixels,0,0);const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;texture.wrapS=texture.wrapT=THREE.RepeatWrapping;texture.anisotropy=4;
  const ground=scene.root.children.find(m=>m.isMesh&&m.geometry.type==='PlaneGeometry');
  if(ground){
    ground.userData.atlasSurface=0;
    const b=town.bounds;texture.repeat.set((b.maxX-b.minX)/180,(b.maxZ-b.minZ)/180);ground.material.map=texture;ground.material.needsUpdate=true;
    const pos=ground.geometry.attributes.position,colors=[];
    for(let i=0;i<pos.count;i++){const x=pos.getX(i),z=pos.getZ(i),n=noise(x/140,z/140),c=new THREE.Color('#9eb484').lerp(new THREE.Color('#799866'),n*.62);colors.push(c.r,c.g,c.b);}
    ground.geometry.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));
  }
  return texture;
}

export function renderParks(scene,town){
  const group=new THREE.Group();scene.root.add(group);
  const parkPlants=[],benches=[],pathVertices=[],lawnVertices=[],lawnColors=[],centers=[],amenities=[],allPaths=[],clearings=[];
  const existing=scene.townDressing?.plan.trees||[];
  const facilityPads=(town.facilities||[]).map(f=>f.polygon).filter(p=>p?.length>=3);
  const clearPad=(p,margin=0)=>facilityPads.every(polygon=>!contains(p,polygon)&&polygon.every((a,i)=>distToSegment(p,a,polygon[(i+1)%polygon.length])>margin));
  const pointsFor=(park)=>park.polygon.filter((p,i,a)=>!i||Math.hypot(p.x-a[i-1].x,p.z-a[i-1].z)>.02);
  for(const park of town.parks||[]){
    const polygon=pointsFor(park);if(polygon.length<3)continue;
    const box={minX:Math.min(...polygon.map(p=>p.x)),maxX:Math.max(...polygon.map(p=>p.x)),minZ:Math.min(...polygon.map(p=>p.z)),maxZ:Math.max(...polygon.map(p=>p.z))};
    const center={x:(box.minX+box.maxX)/2,z:(box.minZ+box.maxZ)/2};centers.push({...center,id:park.id});
    const parkKind=town.atlasDesign?.parks?.find(p=>p.id===park.id)?.kind;
    const field=parkKind==='recreation'?{...center,width:Math.min(56,(box.maxX-box.minX)*.55),depth:Math.min(32,(box.maxZ-box.minZ)*.43)}:null;
    if(field)amenities.push(field);
    for(const triangle of THREE.ShapeUtils.triangulateShape(polygon.map(p=>new THREE.Vector2(p.x,p.z)),[])){
      const [a,b,c]=triangle.map(i=>polygon[i]),n=Math.max(1,Math.ceil(Math.max(Math.hypot(a.x-b.x,a.z-b.z),Math.hypot(a.x-c.x,a.z-c.z),Math.hypot(b.x-c.x,b.z-c.z))/10));
      const point=(i,j)=>({x:a.x+(b.x-a.x)*i/n+(c.x-a.x)*j/n,z:a.z+(b.z-a.z)*i/n+(c.z-a.z)*j/n});
      const push=p=>{const color=new THREE.Color('#8cac69').multiplyScalar(.95+noise(p.x/30,p.z/30)*.12);lawnVertices.push(p.x,scene.heightAt(p.x,p.z)+.075,p.z);lawnColors.push(color.r,color.g,color.b);};
      for(let i=0;i<n;i++)for(let j=0;j<n-i;j++){for(const p of[point(i,j),point(i+1,j),point(i,j+1)])push(p);if(i+j<n-1)for(const p of[point(i+1,j),point(i+1,j+1),point(i,j+1)])push(p);}
    }
    const inset=polygon.map(p=>({x:center.x+(p.x-center.x)*.83,z:center.z+(p.z-center.z)*.83})),pathPieces=[],rounded=[];
    const mix=(a,b,t)=>({x:a.x+(b.x-a.x)*t,z:a.z+(b.z-a.z)*t});
    for(let i=0;i<inset.length;i++){
      const corner=inset[i],start=mix(corner,inset[(i-1+inset.length)%inset.length],.14),end=mix(corner,inset[(i+1)%inset.length],.14);
      for(let j=0;j<=6;j++){const t=j/6;rounded.push({x:(1-t)**2*start.x+2*(1-t)*t*corner.x+t*t*end.x,z:(1-t)**2*start.z+2*(1-t)*t*corner.z+t*t*end.z});}
    }
    const walk=(points,allowOutside=false)=>{
      for(let i=1;i<points.length;i++){
        const a=points[i-1],b=points[i],length=Math.hypot(b.x-a.x,b.z-a.z);if(length<.05)continue;
        const steps=Math.ceil(length/2),dx=(b.x-a.x)/steps,dz=(b.z-a.z)/steps,nx=-dz/Math.hypot(dx,dz)*.95,nz=dx/Math.hypot(dx,dz)*.95;
        for(let j=0;j<steps;j++){
          const p={x:a.x+dx*j,z:a.z+dz*j},q={x:p.x+dx,z:p.z+dz},corners=[[p.x+nx,p.z+nz],[p.x-nx,p.z-nz],[q.x-nx,q.z-nz],[q.x+nx,q.z+nz]];
          if(!corners.every(([x,z])=>(allowOutside||contains({x,z},polygon))&&clearPad({x,z},.5)))continue;
          pathPieces.push({a:p,b:q});for(const k of[0,1,2,0,2,3]){const [x,z]=corners[k];pathVertices.push(x,scene.heightAt(x,z)+.16,z);}
        }
      }
    };
    walk([...rounded,rounded[0]]);
    const curve=points=>new THREE.CatmullRomCurve3(points.map(p=>new THREE.Vector3(p.x,0,p.z))).getPoints(28).map(p=>({x:p.x,z:p.z}));
    const width=box.maxX-box.minX,depth=box.maxZ-box.minZ;
    if(parkKind==='riverfront')walk(curve([{x:box.maxX-width*.085,z:center.z+depth*.22},{x:center.x+width*.12,z:center.z+depth*.12},{x:center.x-width*.12,z:center.z-depth*.12},{x:box.minX+width*.085,z:center.z-depth*.27}]));
    if(field){
      walk(curve([{x:box.maxX-width*.085,z:center.z+depth*.28},{x:field.x+field.width/2+10,z:center.z+depth*.21},{x:field.x+field.width/2+8,z:field.z+field.depth*.20}]));
      clearings.push({x:center.x,z:box.minZ+depth*.12,rx:width*.20,rz:depth*.19});
      clearings.push({x:box.maxX-width*.11,z:center.z+depth*.27,rx:width*.13,rz:depth*.18});
    }
    // An entry path joins the nearest real sidewalk without crossing traffic.
    let entry=null;
    for(let i=0;i<polygon.length;i++){
      const edge=mix(polygon[i],polygon[(i+1)%polygon.length],.5);
      for(const road of town.roads)for(let j=1;j<road.points.length;j++){
        const a=road.points[j-1],b=road.points[j],dx=b.x-a.x,dz=b.z-a.z,t=Math.max(0,Math.min(1,((edge.x-a.x)*dx+(edge.z-a.z)*dz)/(dx*dx+dz*dz||1))),front={x:a.x+dx*t,z:a.z+dz*t},distance=Math.hypot(front.x-edge.x,front.z-edge.z),endDistance=distance-(road.pavementWidthM||8)/2-1;
        if(endDistance>0&&endDistance<28&&(!entry||endDistance<entry.distance))entry={edge,front,distance:endDistance,total:distance};
      }
    }
    if(entry){const start=mix(center,entry.edge,.83),end=mix(entry.edge,entry.front,entry.distance/entry.total);walk([start,entry.edge,end],true);}
    allPaths.push(...pathPieces);
    for(let i=0;i<180;i++){
      const n=hash(`${park.id}:plant:${i}`),p={x:box.minX+(n%10000)/10000*(box.maxX-box.minX),z:box.minZ+((n>>>13)%10000)/10000*(box.maxZ-box.minZ)};
      // Concentrate planting in groves and at the edge, leaving an open lawn.
      const cluster=noise(p.x/23,p.z/23);if(clearings.some(c=>((p.x-c.x)/c.rx)**2+((p.z-c.z)/c.rz)**2<1))continue;if(field&&Math.abs(p.x-field.x)<field.width/2+5&&Math.abs(p.z-field.z)<field.depth/2+5)continue;if(cluster<.43||!contains(p,polygon)||!clearPad(p,6)||polygon.some((a,j)=>distToSegment(p,a,polygon[(j+1)%polygon.length])<4)||pathPieces.some(s=>distToSegment(p,s.a,s.b)<4)||existing.some(t=>Math.hypot(t.x-p.x,t.z-p.z)<4)||parkPlants.some(t=>Math.hypot(t.x-p.x,t.z-p.z)<4.4))continue;
      parkPlants.push({...p,kind:n%3,scale:1.05+(n%55)/100});
    }
    for(let i=0;i<pathPieces.length;i+=Math.max(1,Math.floor(pathPieces.length/5))){
      const {a,b}=pathPieces[i],dx=b.x-a.x,dz=b.z-a.z,len=Math.hypot(dx,dz),p={x:a.x-dz/len*2.1,z:a.z+dx/len*2.1,angle:Math.atan2(dx,dz)};
      if(contains(p,polygon)&&clearPad(p,1.5))benches.push(p);
    }
  }
  function mesh(positions,colors,color){const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));if(colors)g.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));g.computeVertexNormals();const m=new THREE.Mesh(g,new THREE.MeshStandardMaterial({color:color||'#fff',vertexColors:!!colors,roughness:1,side:THREE.DoubleSide}));m.userData.atlasSurface=colors?0:2;m.receiveShadow=true;group.add(m);}
  mesh(lawnVertices,lawnColors);mesh(pathVertices,null,'#aaa58d');
  const padVertices=[];
  for(const polygon of facilityPads.filter(poly=>(town.parks||[]).some(park=>poly.some(p=>contains(p,park.polygon))))){
    for(const triangle of THREE.ShapeUtils.triangulateShape(polygon.map(p=>new THREE.Vector2(p.x,p.z)),[]))for(const index of triangle.toReversed()){
      const p=polygon[index];padVertices.push(p.x,scene.heightAt(p.x,p.z)+.12,p.z);
    }
  }
  mesh(padVertices,null,'#b7baa9');
  const dummy=new THREE.Object3D();
  for(let kind=0;kind<3;kind++){
    const plants=parkPlants.filter(p=>p.kind===kind),m=new THREE.InstancedMesh(leafyTree(kind),new THREE.MeshStandardMaterial({vertexColors:true,roughness:1}),plants.length);
    m.userData.atlasTreeKind=kind;
    plants.forEach((p,i)=>{dummy.position.set(p.x,scene.heightAt(p.x,p.z),p.z);dummy.rotation.set(0,(hash(p.x)%628)/100,0);dummy.scale.setScalar(p.scale);dummy.updateMatrix();m.setMatrixAt(i,dummy.matrix);});m.castShadow=true;m.receiveShadow=true;m.computeBoundingSphere();group.add(m);
  }
  const bench=new GeometryBuilder();bench.box('#a18b6b',0,.53,0,2,.16,.6).box('#a18b6b',0,.95,.24,2,.6,.12);for(const x of[-.75,.75])bench.box('#5c6a5c',x,.25,0,.12,.5,.45);
  const seating=new THREE.InstancedMesh(bench.build(),new THREE.MeshStandardMaterial({vertexColors:true,roughness:1}),benches.length);
  benches.forEach((p,i)=>{dummy.position.set(p.x,scene.heightAt(p.x,p.z),p.z);dummy.rotation.set(0,p.angle,0);dummy.scale.setScalar(1);dummy.updateMatrix();seating.setMatrixAt(i,dummy.matrix);});seating.castShadow=true;seating.computeBoundingSphere();group.add(seating);
  // Paths and the recreation lawn are authored landscape decoration, not assets
  // with invented meters, occupants, route edges or operating capacities.
  hideDressingTrees(scene,p=>!clearPad(p,5)||clearings.some(c=>((p.x-c.x)/c.rx)**2+((p.z-c.z)/c.rz)**2<1)||allPaths.some(s=>distToSegment(p,s.a,s.b)<3)||amenities.some(f=>Math.abs(p.x-f.x)<f.width/2+4&&Math.abs(p.z-f.z)<f.depth/2+4));
  const recreation=new GeometryBuilder();
  for(const f of amenities){
    const home={x:f.x,z:f.z+f.depth*.42},radius=Math.min(f.width*.51,f.depth*1.02),base=radius*.30;
    const patch=(points,color,offset=.16)=>{
      const geometry=new THREE.BufferGeometry(),vertices=[];
      for(const triangle of THREE.ShapeUtils.triangulateShape(points.map(p=>new THREE.Vector2(p.x,p.z)),[])){
        const [a,b,c]=triangle.toReversed().map(index=>points[index]),n=Math.max(1,Math.ceil(Math.max(Math.hypot(a.x-b.x,a.z-b.z),Math.hypot(a.x-c.x,a.z-c.z),Math.hypot(b.x-c.x,b.z-c.z))/3));
        const point=(i,j)=>({x:a.x+(b.x-a.x)*i/n+(c.x-a.x)*j/n,z:a.z+(b.z-a.z)*i/n+(c.z-a.z)*j/n});
        const push=p=>vertices.push(p.x,scene.heightAt(p.x,p.z)+offset,p.z);
        for(let i=0;i<n;i++)for(let j=0;j<n-i;j++){for(const p of[point(i,j),point(i+1,j),point(i,j+1)])push(p);if(i+j<n-1)for(const p of[point(i+1,j),point(i+1,j+1),point(i,j+1)])push(p);}
      }
      geometry.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));geometry.computeVertexNormals();recreation.add(geometry,color);geometry.dispose();
    };
    for(let band=0;band<7;band++){
      const a=-Math.PI*.78+band*Math.PI*.56/7,b=-Math.PI*.78+(band+1)*Math.PI*.56/7;
      patch([home,{x:home.x+Math.cos(a)*radius,z:home.z+Math.sin(a)*radius},{x:home.x+Math.cos(b)*radius,z:home.z+Math.sin(b)*radius}],band%2?'#87a769':'#7b9d61');
    }
    const diamond=[home,{x:home.x-base,z:home.z-base},{x:home.x,z:home.z-base*2},{x:home.x+base,z:home.z-base}];
    patch(diamond,'#c9a477',.20);
    const center={x:home.x,z:home.z-base};
    patch(diamond.map(p=>({x:center.x+(p.x-center.x)*.67,z:center.z+(p.z-center.z)*.67})),'#88a467',.23);
    for(const p of diamond)recreation.box('#efe9d6',p.x,scene.heightAt(p.x,p.z)+.30,p.z,.65,.06,.65);
    for(const side of[-1,1]){
      const end={x:home.x+side*radius*.7,z:home.z-radius*.7},dx=end.x-home.x,dz=end.z-home.z,length=Math.hypot(dx,dz),nx=-dz/length*.10,nz=dx/length*.10;
      patch([{x:home.x+nx,z:home.z+nz},{x:end.x+nx,z:end.z+nz},{x:end.x-nx,z:end.z-nz},{x:home.x-nx,z:home.z-nz}],'#e9e5cb',.27);
    }
    const mound=new THREE.CylinderGeometry(.85,.85,.08,16);recreation.add(mound,'#c3a079',center.x,scene.heightAt(center.x,center.z)+.28,center.z);mound.dispose();
    const x=f.x+f.width/2+8,z=f.z+f.depth*.20,y=scene.heightAt(x,z);
    recreation.box('#d4c6a7',x,y+.2,z,6.4,.4,5.2);
    for(const dx of[-2.7,2.7])for(const dz of[-2.1,2.1])recreation.box('#8d866c',x+dx,y+1.6,z+dz,.20,2.8,.20);
    const roof=roofGeometry(1);recreation.add(roof,'#647b71',x,y+3,z,7,1.4,6);roof.dispose();
    recreation.box('#a8916a',x,y+.85,z,3,.18,1.2);
  }
  const amenityMesh=new THREE.Mesh(recreation.build(),new THREE.MeshStandardMaterial({vertexColors:true,roughness:1}));amenityMesh.castShadow=true;amenityMesh.receiveShadow=true;group.add(amenityMesh);
  return {centers,trees:parkPlants.length,parks:centers.length};
}

export function renderAtlasDesign(scene,town){
  const design=town.atlasDesign;if(!design)return;
  const group=new THREE.Group();scene.root.add(group);
  const river=design.river;
  function strip(points,width,color,offset){
    const positions=[];
    for(let i=1;i<points.length;i++){
      const a=points[i-1],b=points[i],dx=b.x-a.x,dz=b.z-a.z,length=Math.hypot(dx,dz);if(length<.01)continue;
      const nx=-dz/length*width/2,nz=dx/length*width/2,steps=Math.ceil(length/6);
      for(let j=0;j<steps;j++){
        const p={x:a.x+dx*j/steps,z:a.z+dz*j/steps},q={x:a.x+dx*(j+1)/steps,z:a.z+dz*(j+1)/steps};
        for(const [x,z]of[[p.x+nx,p.z+nz],[p.x-nx,p.z-nz],[q.x-nx,q.z-nz],[p.x+nx,p.z+nz],[q.x-nx,q.z-nz],[q.x+nx,q.z+nz]])positions.push(x,scene.heightAt(x,z)+offset,z);
      }
    }
    const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));g.computeVertexNormals();const m=new THREE.Mesh(g,new THREE.MeshStandardMaterial({color,roughness:.9,side:THREE.DoubleSide}));m.receiveShadow=true;group.add(m);return m;
  }
  if(river?.polygon?.length){
    const polygon=river.polygon;
    // Triangulate the authored river polygon; no river is invented for other worlds.
    const positions=[],colors=[];
    for(const triangle of THREE.ShapeUtils.triangulateShape(polygon.map(p=>new THREE.Vector2(p.x,p.z)),[])){
      const [a,b,c]=triangle.map(i=>polygon[i]),n=Math.max(1,Math.ceil(Math.max(Math.hypot(a.x-b.x,a.z-b.z),Math.hypot(a.x-c.x,a.z-c.z),Math.hypot(b.x-c.x,b.z-c.z))/12));
      const point=(i,j)=>({x:a.x+(b.x-a.x)*i/n+(c.x-a.x)*j/n,z:a.z+(b.z-a.z)*i/n+(c.z-a.z)*j/n});
      const push=p=>{
        const centerline=river.centerline||[],bank=centerline.length>1?Math.max(0,(river.widthM||68)/2-Math.min(...centerline.slice(1).map((b,i)=>distToSegment(p,centerline[i],b)))):Math.min(...polygon.map((a,i)=>distToSegment(p,a,polygon[(i+1)%polygon.length]))),depth=Math.min(1,bank/(6+noise(p.x/20,p.z/20)*4));
        const color=new THREE.Color('#4c9398').lerp(new THREE.Color('#2d6d88'),depth).multiplyScalar(.88+noise(p.x/18,p.z/28)*.22);
        positions.push(p.x,scene.heightAt(p.x,p.z)+.15,p.z);colors.push(color.r,color.g,color.b);
      };
      for(let i=0;i<n;i++)for(let j=0;j<n-i;j++){for(const p of[point(i,j),point(i+1,j),point(i,j+1)])push(p);if(i+j<n-1)for(const p of[point(i+1,j),point(i+1,j+1),point(i,j+1)])push(p);}
    }
    const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));g.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));g.computeVertexNormals();group.add(new THREE.Mesh(g,new THREE.MeshStandardMaterial({vertexColors:true,roughness:.38,metalness:.08,side:THREE.DoubleSide})));
    // Restrained static ripples are illustration, not simulated current.
    const ripple=[];
    for(let i=0;i<(river.centerline||[]).length;i++){
      const p=river.centerline[i];for(let j=0;j<3;j++){
        const z=p.z+j*4-4,x=p.x+(j-1)*3;if(!contains({x,z},polygon))continue;
        ripple.push(x-2,scene.heightAt(x,z)+.18,z,x+2,scene.heightAt(x,z)+.18,z);
      }
    }
    // Clusters along the saved banks give the river an edge without changing its channel.
    const bankTrees=[],roads=town.roads.flatMap(r=>r.points.slice(1).map((b,i)=>({a:r.points[i],b,width:r.pavementWidthM||8}))),existing=scene.townDressing?.plan.trees||[];
    for(let i=0;i<polygon.length;i++){
      const a=polygon[i],b=polygon[(i+1)%polygon.length],dx=b.x-a.x,dz=b.z-a.z,length=Math.hypot(dx,dz);if(length<2)continue;
      for(let d=0;d<length;d+=9){
        const key=hash(`${i}:bank:${d}`),x=a.x+dx*d/length,z=a.z+dz*d/length;if(noise(x/25,z/25)<.43)continue;
        for(const side of[-1,1]){
          const offset=6+(key%80)/10,p={x:x-dz/length*offset*side,z:z+dx/length*offset*side};
          if(contains(p,polygon)||roads.some(s=>distToSegment(p,s.a,s.b)<s.width/2+5)||town.premises.some(h=>Math.hypot(p.x-h.x,p.z-h.z)<Math.hypot(h.width,h.depth)/2+5)||existing.some(t=>Math.hypot(p.x-t.x,p.z-t.z)<5)||bankTrees.some(t=>Math.hypot(p.x-t.x,p.z-t.z)<6))continue;
          bankTrees.push({...p,kind:key%3,scale:1.0+(key%70)/100});
        }
      }
    }
    const plant=new THREE.Object3D();
    for(let kind=0;kind<3;kind++){
      const trees=bankTrees.filter(p=>p.kind===kind),mesh=new THREE.InstancedMesh(leafyTree(kind),new THREE.MeshStandardMaterial({vertexColors:true,roughness:1}),trees.length);
      mesh.userData.atlasTreeKind=kind;
      trees.forEach((p,i)=>{plant.position.set(p.x,scene.heightAt(p.x,p.z),p.z);plant.scale.setScalar(p.scale);plant.updateMatrix();mesh.setMatrixAt(i,plant.matrix);});mesh.castShadow=true;mesh.receiveShadow=true;mesh.computeBoundingSphere();group.add(mesh);
    }
    const rg=new THREE.BufferGeometry();rg.setAttribute('position',new THREE.Float32BufferAttribute(ripple,3));group.add(new THREE.LineSegments(rg,new THREE.LineBasicMaterial({color:'#d3e6e1',transparent:true,opacity:.38,depthWrite:false})));
  }
  const rails=new GeometryBuilder();
  for(const bridge of design.bridges||[]){
    const points=bridge.points,width=bridge.widthM||12;if(!points?.length)continue;
    strip(points,width+1.8,'#d4d0bd',.38).userData.atlasSurface=2;strip(points,width,'#7e898a',.42).userData.atlasSurface=1;
    for(let i=1;i<points.length;i++){
      const a=points[i-1],b=points[i],dx=b.x-a.x,dz=b.z-a.z,length=Math.hypot(dx,dz);if(length<.01)continue;
      for(let d=2;d<length-2;d+=10){const end=Math.min(length-2,d+4),t=(d+end)/2/length,x=a.x+dx*t,z=a.z+dz*t,dash=new THREE.BoxGeometry(.17,.018,end-d);rails.add(dash,'#e9e8d8',x,scene.heightAt(x,z)+.49,z,1,1,1,0,Math.atan2(dx,dz));dash.dispose();}
      const steps=Math.max(1,Math.ceil(length/3));
      for(const side of[-1,1]){
        const nx=-dz/length*(width/2+.4)*side,nz=dx/length*(width/2+.4)*side;
        for(let j=0;j<=steps;j++){
          const x=a.x+dx*j/steps+nx,z=a.z+dz*j/steps+nz,y=scene.heightAt(x,z);rails.box('#a9ad9f',x,y+1.15,z,.26,1.5,.26);
        }
        const x=(a.x+b.x)/2+nx,z=(a.z+b.z)/2+nz,box=new THREE.BoxGeometry(.18,.20,length);rails.add(box,'#bfc4b4',x,scene.heightAt(x,z)+1.92,z,1,1,1,0,Math.atan2(dx,dz));box.dispose();
        const plinth=new THREE.BoxGeometry(.72,.56,length);rails.add(plinth,'#b1b4a7',x,scene.heightAt(x,z)+.72,z,1,1,1,0,Math.atan2(dx,dz));plinth.dispose();
        for(const end of[a,b]){
          const px=end.x+nx,pz=end.z+nz,y=scene.heightAt(px,pz);
          rails.box('#a1aba3',px,y+1.43,pz,2.05,2.1,2.05).box('#d1d1bd',px,y+2.57,pz,2.4,.22,2.4);
        }
      }
    }
  }
  const railMesh=new THREE.Mesh(rails.build(),new THREE.MeshStandardMaterial({vertexColors:true,roughness:.8}));railMesh.castShadow=true;railMesh.receiveShadow=true;group.add(railMesh);
}

export function hideDressingTrees(scene,predicate){
  for(let kind=0;kind<3;kind++){
    const mesh=scene.townDressing?.meshes[kind];if(!mesh)continue;
    const plants=scene.townDressing.plan.trees.filter(p=>p.kind===kind),matrix=new THREE.Matrix4().makeScale(0,0,0);
    plants.forEach((p,i)=>{if(predicate(p))mesh.setMatrixAt(i,matrix);});mesh.instanceMatrix.needsUpdate=true;mesh.computeBoundingSphere();
  }
}
export function applyBuildingFamilies(scene,town,geometryFor){
  const families=town.atlasDesign?.buildingFamilies;if(!families)return null;
  const matched=new Set(town.premises.map((p,i)=>families[p.id]?i:-1).filter(i=>i>=0));
  const previous=[scene.houseMeshes.walls,...scene.roofBatches,scene.houseMeshes.solar,...scene.townDressing.meshes.filter(m=>m.userData.premiseIndices)];
  const zero=new THREE.Matrix4().makeScale(0,0,0);
  for(const mesh of previous){const indices=mesh.userData.premiseIndices||[];indices.forEach((p,i)=>{if(matched.has(p))mesh.setMatrixAt(i,zero);});mesh.instanceMatrix.needsUpdate=true;mesh.computeBoundingSphere();}
  // The authored asset includes its own doors/windows, so the generic detail pass
  // must not draw through it. Reference fixtures assign every house a family.
  scene.houseDetails?.setEnabled(false);
  const material=new THREE.MeshStandardMaterial({vertexColors:true,roughness:.87,side:THREE.DoubleSide}),groups=new Map(),dummy=new THREE.Object3D();
  const roofMap=roofSurfaceTexture();
  material.userData.atlasArchitecture=true;
  material.onBeforeCompile=shader=>{
    shader.uniforms.atlasRoofSurface={value:roofMap};
    shader.vertexShader='attribute float atlasBrick; varying float atlasBrickWall; varying vec3 atlasPosition; varying vec3 atlasNormal;\n'+shader.vertexShader;
    shader.vertexShader=shader.vertexShader.replace('#include <begin_vertex>','#include <begin_vertex>\natlasPosition=position; atlasNormal=normal; atlasBrickWall=atlasBrick;');
    const textures=material.userData.atlasTextures;
    let uniforms='uniform sampler2D atlasRoofSurface;',detail='if(atlasNormal.y>.45) diffuseColor.rgb*=texture2D(atlasRoofSurface,atlasPosition.xz/6.0).rgb;';
    if(textures){
      for(const [name,index]of[['atlasAsphalt',1],['atlasSlate',3],['atlasBrickMap',4],['atlasSiding',5]]){shader.uniforms[name]={value:textures[index]};uniforms+=` uniform sampler2D ${name};`;}
      detail=`if(atlasNormal.y>.45){diffuseColor.rgb*=atlasNormal.y>.94?texture2D(atlasAsphalt,atlasPosition.xz/4.0).rgb:texture2D(atlasSlate,atlasPosition.xz/3.0).rgb;}else{vec2 facade=vec2(abs(atlasNormal.x)>.5?atlasPosition.z:atlasPosition.x,atlasPosition.y);vec3 surface=atlasBrickWall>.5?texture2D(atlasBrickMap,facade/vec2(1.6,1.0)).rgb:texture2D(atlasSiding,facade/vec2(3.0,1.5)).rgb;diffuseColor.rgb*=mix(vec3(1.0),surface,.65);}`;
    }
    shader.fragmentShader=uniforms+' varying float atlasBrickWall; varying vec3 atlasPosition; varying vec3 atlasNormal;\n'+shader.fragmentShader;
    shader.fragmentShader=shader.fragmentShader.replace('#include <color_fragment>','#include <color_fragment>\n'+detail);
  };
  material.customProgramCacheKey=()=>material.userData.atlasTextures?'atlas-materials/1':'atlas-roof/1';
  town.premises.forEach((p,i)=>{const family=families[p.id];if(!family)return;const variant=hash(p.id)%(['brick_shop','restaurant'].includes(family)?20:5),key=[family,p.width,p.depth,p.height,p.stories,p.roof,p.solar?1:0,variant].join(':');if(!groups.has(key))groups.set(key,{family,home:p,items:[]});groups.get(key).items.push({home:p,index:i});});
  let triangles=0;
  for(const g of groups.values()){
    const geometry=geometryFor(g.family,g.home),mesh=new THREE.InstancedMesh(geometry,material,g.items.length);mesh.userData.premiseIndices=g.items.map(p=>p.index);
    mesh.userData.atlasBuilding=true;
    geometry.setAttribute('atlasBrick',new THREE.Float32BufferAttribute(new Float32Array(geometry.attributes.position.count).fill(['brick_shop','restaurant','school'].includes(g.family)?1:0),1));
    g.items.forEach(({home:p},i)=>{dummy.position.set(p.x,p.elevationM??scene.heightAt(p.x,p.z),p.z);dummy.rotation.set(0,-p.angle+(p.side===-1?Math.PI:0)+Math.PI,0);dummy.scale.setScalar(1);dummy.updateMatrix();mesh.setMatrixAt(i,dummy.matrix);});
    mesh.castShadow=true;mesh.receiveShadow=true;mesh.computeBoundingSphere();scene.root.add(mesh);scene.pickMeshes.push(mesh);triangles+=(geometry.index?.count||geometry.attributes.position.count)/3*g.items.length;
  }
  if(town.atlasDesign.river?.polygon)hideDressingTrees(scene,p=>contains(p,town.atlasDesign.river.polygon));
  return {buildings:matched.size,families:new Set(Object.values(families)).size,batches:groups.size,triangles,destroy(){roofMap.dispose();}};
}

function roofSurfaceTexture(){
  const c=document.createElement('canvas');c.width=c.height=128;const ctx=c.getContext('2d'),data=ctx.createImageData(128,128);
  for(let y=0;y<128;y++)for(let x=0;x<128;x++){
    const i=(y*128+x)*4,v=224+hash(`${x}:roof:${y}`)%28;
    data.data[i]=data.data[i+1]=data.data[i+2]=v;data.data[i+3]=255;
  }
  ctx.putImageData(data,0,0);ctx.strokeStyle='rgba(77,85,78,.15)';ctx.lineWidth=1;
  for(const x of[0,64,127]){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,128);ctx.stroke();}
  const texture=new THREE.CanvasTexture(c);texture.wrapS=texture.wrapT=THREE.RepeatWrapping;texture.colorSpace=THREE.SRGBColorSpace;texture.anisotropy=4;return texture;
}

export function renderTownCenter(scene,town){
  const shops=town.premises.filter(p=>['brick_shop','restaurant'].includes(town.atlasDesign?.buildingFamilies?.[p.id]));
  if(!shops.length)return;
  const ids=new Set(shops.map(p=>p.id)),paving=[],joints=[],furniture=new GeometryBuilder();
  const point=(p,tangent,normal,x,z)=>({x:p.x+tangent.x*x+normal.x*z,z:p.z+tangent.z*x+normal.z*z});
  const quad=points=>{
    const vertices=points.map(p=>new THREE.Vector3(p.x,scene.heightAt(p.x,p.z)+.27,p.z));
    if(new THREE.Vector3().crossVectors(vertices[1].clone().sub(vertices[0]),vertices[2].clone().sub(vertices[0])).y<0)vertices.reverse();
    for(const i of[0,1,2,0,2,3])paving.push(...vertices[i].toArray());
  };
  for(const p of shops){
    const dx=p.front.x-p.x,dz=p.front.z-p.z,length=Math.hypot(dx,dz),normal={x:dx/length,z:dz/length},tangent={x:-normal.z,z:normal.x};
    const road=town.roads.reduce((best,r)=>{const distance=Math.min(...r.points.slice(1).map((b,i)=>distToSegment(p.front,r.points[i],b)));return !best||distance<best.distance?{road:r,distance}:best;},null)?.road;
    const start=p.depth/2-.1,end=length-(road?.pavementWidthM||14)/2-.25,halfWidth=p.width/2+1.5;
    if(end<=start)continue;
    quad([point(p,tangent,normal,-halfWidth,start),point(p,tangent,normal,halfWidth,start),point(p,tangent,normal,halfWidth,end),point(p,tangent,normal,-halfWidth,end)]);
    for(let z=start+1.4;z<end;z+=2.2){const a=point(p,tangent,normal,-halfWidth,z),b=point(p,tangent,normal,halfWidth,z);joints.push(a.x,scene.heightAt(a.x,a.z)+.29,a.z,b.x,scene.heightAt(b.x,b.z)+.29,b.z);}
    for(let x=-halfWidth+2;x<halfWidth;x+=2.2){const a=point(p,tangent,normal,x,start),b=point(p,tangent,normal,x,end);joints.push(a.x,scene.heightAt(a.x,a.z)+.29,a.z,b.x,scene.heightAt(b.x,b.z)+.29,b.z);}
    for(const side of[-1,1]){
      const pos=point(p,tangent,normal,side*(halfWidth-1.8),end-2.0),y=scene.heightAt(pos.x,pos.z);
      furniture.box('#b5ab90',pos.x,y+.40,pos.z,1.55,.78,1.55).box('#5d7751',pos.x,y+.85,pos.z,1.33,.37,1.33);
    }
    const pos=point(p,tangent,normal,-halfWidth+3.3,start+2.0),y=scene.heightAt(pos.x,pos.z),angle=Math.atan2(tangent.z,tangent.x);
    const bench=new THREE.BoxGeometry(2.1,.16,.65);furniture.add(bench,'#867763',pos.x,y+.57,pos.z,1,1,1,0,-angle);bench.dispose();
  }
  // Replace the old centerline-to-door ribbons, which visually crossed traffic
  // lanes and split this shared pedestrian frontage into isolated driveways.
  const legacyAccess=scene.townDressing?.meshes.find((m,i)=>i>=12&&!m.isInstancedMesh);
  if(legacyAccess)legacyAccess.visible=false;
  for(const landmark of scene.townDressing?.plan.landmarks||[]){
    if(!landmark.access||ids.has(landmark.premiseId))continue;
    const [a,b]=landmark.access,dx=b.x-a.x,dz=b.z-a.z,length=Math.hypot(dx,dz);if(length<1)continue;
    const nx=-dz/length*1.8,nz=dx/length*1.8;
    quad([{x:a.x+nx,z:a.z+nz},{x:b.x+nx,z:b.z+nz},{x:b.x-nx,z:b.z-nz},{x:a.x-nx,z:a.z-nz}]);
  }
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(paving,3));geometry.computeVertexNormals();
  const mesh=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color:'#c4bdab',roughness:1}));mesh.userData.atlasSurface=2;mesh.receiveShadow=true;scene.root.add(mesh);
  const lineGeometry=new THREE.BufferGeometry();lineGeometry.setAttribute('position',new THREE.Float32BufferAttribute(joints,3));scene.root.add(new THREE.LineSegments(lineGeometry,new THREE.LineBasicMaterial({color:'#a9a593',transparent:true,opacity:.45,depthWrite:false})));
  const props=new THREE.Mesh(furniture.build(),new THREE.MeshStandardMaterial({vertexColors:true,roughness:1}));props.castShadow=true;props.receiveShadow=true;scene.root.add(props);
}

export function renderWaterTowers(scene,town){
  for(const facility of town.facilities||[]){
    if(facility.kind!=='elevated_tank')continue;
    // The facility and its site are persisted physical records. The shell's
    // dimensions and paintwork are an illustrative skin, not rated capacity.
    const b=new GeometryBuilder(),steel='#c7d5cf',rail='#728e87',foot=5.8,deck=18;
    const rod=(a,c,r,color=steel)=>{
      const from=new THREE.Vector3(...a),to=new THREE.Vector3(...c),delta=to.clone().sub(from),g=new THREE.CylinderGeometry(r,r,delta.length(),8);
      g.applyMatrix4(new THREE.Matrix4().compose(from.add(to).multiplyScalar(.5),new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,1,0),delta.normalize()),new THREE.Vector3(1,1,1)));b.add(g,color);g.dispose();
    };
    for(const x of[-foot,foot])for(const z of[-foot,foot]){
      rod([x,.4,z],[x*.72,deck,z*.72],.27);
      b.box('#aeb7a7',x,.35,z,2.1,.65,2.1);
    }
    for(const sign of[-1,1])for(const [low,high]of[[1,9],[9,17]]){
      const r0=foot*(1-.28*low/deck),r1=foot*(1-.28*high/deck);
      rod([-r0,low,sign*r0],[r1,high,sign*r1],.09,rail);rod([r0,low,sign*r0],[-r1,high,sign*r1],.09,rail);
      rod([sign*r0,low,-r0],[sign*r1,high,r1],.09,rail);rod([sign*r0,low,r0],[sign*r1,high,-r1],.09,rail);
    }
    const bowl=new THREE.SphereGeometry(7,24,14,0,Math.PI*2,Math.PI/2,Math.PI/2);b.add(bowl,steel,0,20,0,1,.45,1);bowl.dispose();
    const body=new THREE.CylinderGeometry(7,7,5,32);b.add(body,'#d8e1d8',0,22.3,0);body.dispose();
    const band=new THREE.CylinderGeometry(7.025,7.025,1.05,32,1,true);b.add(band,'#528c8b',0,22.8,0);band.dispose();
    const dome=new THREE.SphereGeometry(7.05,32,12,0,Math.PI*2,0,Math.PI/2);b.add(dome,'#8fa9a0',0,24.8,0,1,.30,1);dome.dispose();
    const platform=new THREE.CylinderGeometry(7.55,7.55,.22,32);b.add(platform,rail,0,19.7,0);platform.dispose();
    const riser=new THREE.CylinderGeometry(.4,.4,19,10);b.add(riser,steel,0,9.8,0);riser.dispose();
    for(let i=0;i<24;i++){const a=i*Math.PI/12,x=Math.cos(a)*7.35,z=Math.sin(a)*7.35;rod([x,19.8,z],[x,20.75,z],.055,rail);}
    const ring=new THREE.TorusGeometry(7.35,.065,5,32);b.add(ring,rail,0,20.75,0,1,1,1,Math.PI/2);ring.dispose();
    const model=new THREE.Mesh(b.build(),new THREE.MeshStandardMaterial({vertexColors:true,roughness:.68}));model.position.set(facility.x,scene.heightAt(facility.x,facility.z),facility.z);model.castShadow=true;model.receiveShadow=true;model.userData.facilityId=facility.id;scene.root.add(model);
  }
}
