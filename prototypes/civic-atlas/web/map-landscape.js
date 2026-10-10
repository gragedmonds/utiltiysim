import * as THREE from '/viewer/vendor/three.module.js';
import {hash,GeometryBuilder} from '/viewer/lowpoly.js';

const smooth=t=>t*t*(3-2*t);
function noise(x,z){const a=Math.floor(x),b=Math.floor(z),fx=smooth(x-a),fz=smooth(z-b),n=(i,j)=>(hash(`${i}:land:${j}`)%1000)/1000;return(n(a,b)*(1-fx)+n(a+1,b)*fx)*(1-fz)+(n(a,b+1)*(1-fx)+n(a+1,b+1)*fx)*fz;}
function contains(p,polygon){let yes=false;for(let i=0,j=polygon.length-1;i<polygon.length;j=i++){const a=polygon[i],b=polygon[j];if((a.z>p.z)!==(b.z>p.z)&&p.x<(b.x-a.x)*(p.z-a.z)/(b.z-a.z)+a.x)yes=!yes;}return yes;}
function distance(p,a,b){const dx=b.x-a.x,dz=b.z-a.z,t=Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.z-a.z)*dz)/(dx*dx+dz*dz||1)));return Math.hypot(p.x-a.x-t*dx,p.z-a.z-t*dz);}
const roadSegments=town=>town.roads.flatMap(r=>r.points.slice(1).map((b,i)=>({a:r.points[i],b,width:r.pavementWidthM||8})));

// Landscape dressing follows saved shoreline, roads, parks and sites. These
// groves/ground covers are illustration, not added utility or property records.
export function naturalizeLandscape(scene,town){
  const river=town.atlasDesign?.river;if(!river?.polygon)return null;
  const roads=roadSegments(town),polygon=river.polygon,parks=town.parks||[],pads=(town.facilities||[]).map(f=>f.polygon).filter(Boolean),parcels=(town.parcels||[]).map(p=>p.polygon),bounds=town.bounds;
  const occupied=p=>town.premises.some(h=>Math.hypot(p.x-h.x,p.z-h.z)<Math.hypot(h.width,h.depth)/2+4);
  const clear=p=>p.x>bounds.minX+5&&p.x<bounds.maxX-5&&p.z>bounds.minZ+5&&p.z<bounds.maxZ-5&&!contains(p,polygon)&&!occupied(p)&&!pads.some(poly=>contains(p,poly))&&parcels.every(poly=>!contains(p,poly)&&poly.every((a,i)=>distance(p,a,poly[(i+1)%poly.length])>2))&&roads.every(s=>distance(p,s.a,s.b)>s.width/2+4);
  const plants=[],groves=[];
  for(let i=0;i<polygon.length;i++){
    const a=polygon[i],b=polygon[(i+1)%polygon.length],dx=b.x-a.x,dz=b.z-a.z,length=Math.hypot(dx,dz);if(length<1)continue;
    const sign=contains({x:(a.x+b.x)/2-dz/length,z:(a.z+b.z)/2+dx/length},polygon)?-1:1,nx=-dz/length*sign,nz=dx/length*sign;
    for(let d=0;d<length;d+=14){
      const x=a.x+dx*d/length,z=a.z+dz*d/length,density=noise(x/70,z/85);
      if(density<.35)continue;
      const root={x:x+nx*(6+density*9),z:z+nz*(6+density*9)};
      if(!clear(root)||parks.some(p=>contains(root,p.polygon)))continue;
      groves.push({...root,radius:17+density*8});
      for(let k=0;k<7;k++){
        const seed=hash(`river-grove:${i}:${d}:${k}`),angle=(seed%6283)/1000,radius=4+(seed>>>8)%150/10,p={x:root.x+Math.cos(angle)*radius,z:root.z+Math.sin(angle)*radius};
        if(!clear(p)||parks.some(park=>contains(p,park.polygon))||plants.some(q=>Math.hypot(p.x-q.x,p.z-q.z)<4.2))continue;
        plants.push({...p,scale:1.4+(seed%90)/100,kind:Math.floor(noise(p.x/35,p.z/35)*3)%3});
      }
    }
  }
  // Broad irregular woodland pockets further from the river create a deliberate
  // town edge instead of hundreds of evenly dispersed ornamental dots.
  const riverX=river.centerline.reduce((sum,p)=>sum+p.x,0)/river.centerline.length;
  for(let z=bounds.minZ+25;z<bounds.maxZ-25;z+=44){
    const root={x:riverX-90-noise(z/90,3)*45,z:z+noise(z/60,8)*18},density=noise(z/105,2);
    if(density<.30||!clear(root))continue;groves.push({...root,radius:27+density*12});
    for(let i=0;i<16;i++){
      const seed=hash(`woodland:${z}:${i}`),angle=(seed%6283)/1000,radius=Math.sqrt(((seed>>>7)%1000)/1000)*36,p={x:root.x+Math.cos(angle)*radius,z:root.z+Math.sin(angle)*radius};
      if(!clear(p)||plants.some(q=>Math.hypot(p.x-q.x,p.z-q.z)<4.8))continue;plants.push({...p,scale:1.45+(seed%80)/100,kind:Math.floor(noise(p.x/45,p.z/45)*3)%3});
    }
  }
  const matrix=new THREE.Matrix4(),position=new THREE.Vector3();
  for(const source of scene.townDressing?.meshes.slice(0,3)||[]){
    for(let i=0;i<source.count;i++){
      source.getMatrixAt(i,matrix);position.setFromMatrixPosition(matrix);
      if(position.x<riverX-40&&roads.every(s=>distance(position,s.a,s.b)>s.width/2+15)&&!groves.some(g=>Math.hypot(position.x-g.x,position.z-g.z)<g.radius*1.2))source.setMatrixAt(i,new THREE.Matrix4().makeScale(0,0,0));
    }
    source.instanceMatrix.needsUpdate=true;source.computeBoundingSphere();
  }
  const dummy=new THREE.Object3D();
  for(let kind=0;kind<3;kind++){
    const items=plants.filter(p=>p.kind===kind),mesh=new THREE.InstancedMesh(new THREE.SphereGeometry(2.8,8,6),new THREE.MeshStandardMaterial({color:'#769065',roughness:1}),items.length);
    mesh.geometry.translate(0,4,0);mesh.userData.atlasTreeKind=kind;mesh.userData.atlasGrove=true;
    items.forEach((p,i)=>{dummy.position.set(p.x,scene.heightAt(p.x,p.z),p.z);dummy.scale.setScalar(p.scale);dummy.updateMatrix();mesh.setMatrixAt(i,dummy.matrix);});mesh.computeBoundingSphere();scene.root.add(mesh);
  }
  // A terrain-conforming translucent understorey layer joins nearby crowns into
  // wooded places. Saved lawn/park/pavement surfaces cover this ground treatment.
  const ground=scene.root.children.find(m=>m.isMesh&&m.geometry.type==='PlaneGeometry'&&m.userData.atlasSurface===0);
  let texture=null;
  if(ground){
    const c=document.createElement('canvas');c.width=c.height=1536;const ctx=c.getContext('2d'),w=bounds.maxX-bounds.minX,d=bounds.maxZ-bounds.minZ;
    const pixel=p=>({x:(p.x-bounds.minX)/w*c.width,y:(bounds.maxZ-p.z)/d*c.height});
    for(const grove of groves){
      const p=pixel(grove),radius=grove.radius/w*c.width;
      for(let k=0;k<4;k++){
        const seed=hash(`${grove.x}:ground:${k}`),x=p.x+(seed%21)-10,y=p.y+((seed>>>8)%21)-10,r=radius*(.7+(seed%35)/100),g=ctx.createRadialGradient(x,y,0,x,y,r);
        g.addColorStop(0,'rgba(49,69,44,.65)');g.addColorStop(.5,'rgba(76,95,53,.42)');g.addColorStop(1,'rgba(105,118,71,0)');ctx.fillStyle=g;ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();
      }
    }
    texture=new THREE.CanvasTexture(c);texture.colorSpace=THREE.SRGBColorSpace;
    const geometry=ground.geometry.clone(),pos=geometry.attributes.position,uv=[];
    for(let i=0;i<pos.count;i++){pos.setY(i,pos.getY(i)+.04);uv.push((pos.getX(i)-bounds.minX)/w,(pos.getZ(i)-bounds.minZ)/d);}
    geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));
    const mesh=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial({map:texture,transparent:true,depthWrite:false,toneMapped:false}));mesh.renderOrder=1;scene.root.add(mesh);
  }
  return {groves:groves.length,trees:plants.length,destroy(){texture?.dispose();}};
}

export function renderNaturalBanks(scene,town){
  const polygon=town.atlasDesign?.river?.polygon;if(!polygon)return null;
  const positions=[],colors=[],uv=[],roads=roadSegments(town),stones=[],reeds=[];
  let along=0;
  for(let i=0;i<polygon.length;i++){
    const a=polygon[i],b=polygon[(i+1)%polygon.length],dx=b.x-a.x,dz=b.z-a.z,length=Math.hypot(dx,dz);if(length<.01)continue;
    const sign=contains({x:(a.x+b.x)/2-dz/length,z:(a.z+b.z)/2+dx/length},polygon)?-1:1,nx=-dz/length*sign,nz=dx/length*sign;
    const steps=Math.max(1,Math.ceil(length/2.5));
    const ring=(t,k)=>{
      const x=a.x+dx*t,z=a.z+dz*t,n=noise(x/12,z/12),offset=[.06,.55+n*1.5,2.5+n*5,7+n*8][k];
      return{x:x+nx*offset,z:z+nz*offset,u:k/3,v:(along+length*t)/34,n};
    };
    for(let j=0;j<steps;j++)for(let k=0;k<3;k++){
      const points=[ring(j/steps,k),ring((j+1)/steps,k),ring((j+1)/steps,k+1),ring(j/steps,k+1)];
      if(points.some(p=>contains(p,polygon)||roads.some(s=>distance(p,s.a,s.b)<s.width/2+.7)))continue;
      for(const index of[0,1,2,0,2,3]){
        const p=points[index],wet=new THREE.Color('#536f64'),pebble=new THREE.Color('#afa78a'),grass=new THREE.Color('#7f9865');
        const color=p.u<.34?wet.clone().lerp(pebble,p.n*.5):p.u<.67?pebble.clone().lerp(grass,noise(p.x/18,p.z/18)):grass;
        positions.push(p.x,scene.heightAt(p.x,p.z)+.055,p.z);colors.push(color.r,color.g,color.b);uv.push(p.u,p.v);
      }
    }
    // Uneven riparian pockets are sampled along the saved bank rather than
    // only at polygon vertices; long channel segments need the same detail.
    for(let d=8;d<length;d+=19){
      const mid={x:a.x+dx*d/length,z:a.z+dz*d/length},patch=noise(mid.x/19,mid.z/27),seed=hash(`river-edge-pocket:${i}:${d}`);
      if(patch<.44||seed%5===0)continue;
      const root={x:mid.x+nx*(1.3+patch*2),z:mid.z+nz*(1.3+patch*2)};
      for(let k=0;k<7+seed%6;k++){
        const n=hash(`${i}:${d}:stone:${k}`),p={x:root.x+((n%130)/10-6.5)*dx/length+nx*((n>>>7)%28)/10,z:root.z+((n%130)/10-6.5)*dz/length+nz*((n>>>7)%28)/10};
        if(contains(p,polygon)||roads.some(s=>distance(p,s.a,s.b)<s.width/2+2))continue;
        if(k%2)stones.push({...p,scale:.55+(n%95)/100,angle:(n%628)/100});else reeds.push({...p,scale:.7+(n%60)/100,angle:(n%628)/100});
      }
    }
    along+=length;
  }
  const c=document.createElement('canvas');c.width=128;c.height=512;const ctx=c.getContext('2d'),data=ctx.createImageData(c.width,c.height);
  for(let y=0;y<c.height;y++)for(let x=0;x<c.width;x++){
    const i=(y*c.width+x)*4,grain=180+hash(`bank:${x}:${y}`)%75,u=x/(c.width-1),edge=.78+noise(y/50,2)*.18;
    data.data[i]=data.data[i+1]=data.data[i+2]=grain;data.data[i+3]=255*(u<.55?1:Math.max(0,(edge-u)/(edge-.55)));
  }
  ctx.putImageData(data,0,0);const texture=new THREE.CanvasTexture(c);texture.colorSpace=THREE.SRGBColorSpace;texture.wrapT=THREE.RepeatWrapping;texture.anisotropy=8;
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geometry.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));geometry.computeVertexNormals();
  const mesh=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({map:texture,vertexColors:true,roughness:1,transparent:true,depthWrite:false,side:THREE.DoubleSide}));mesh.receiveShadow=true;scene.root.add(mesh);
  const dummy=new THREE.Object3D(),rockGeometry=new THREE.IcosahedronGeometry(1,1),rockMesh=new THREE.InstancedMesh(rockGeometry,new THREE.MeshStandardMaterial({color:'#879586',roughness:1}),stones.length);
  stones.forEach((p,i)=>{dummy.position.set(p.x,scene.heightAt(p.x,p.z)+.22,p.z);dummy.rotation.set(.08,p.angle,.13);dummy.scale.set(p.scale*1.3,p.scale*.43,p.scale*.75);dummy.updateMatrix();rockMesh.setMatrixAt(i,dummy.matrix);rockMesh.setColorAt(i,new THREE.Color().setScalar(.84+(i%5)*.04));});rockMesh.castShadow=true;rockMesh.receiveShadow=true;rockMesh.computeBoundingSphere();scene.root.add(rockMesh);
  const grass=new GeometryBuilder(),blade=new THREE.CylinderGeometry(.018,.045,1.15,4);
  for(let k=0;k<13;k++){const angle=k*2.4,radius=.10+(k%4)*.18;grass.add(blade,k%3?'#7d8d54':'#a6a172',Math.cos(angle)*radius,.54,Math.sin(angle)*radius,1,.7+(k%5)*.12,1,.12*Math.cos(angle),0,.12*Math.sin(angle));}
  blade.dispose();const reedMesh=new THREE.InstancedMesh(grass.build(),new THREE.MeshStandardMaterial({vertexColors:true,roughness:1}),reeds.length);
  reeds.forEach((p,i)=>{dummy.position.set(p.x,scene.heightAt(p.x,p.z)+.08,p.z);dummy.rotation.set(0,p.angle,0);dummy.scale.setScalar(p.scale);dummy.updateMatrix();reedMesh.setMatrixAt(i,dummy.matrix);});reedMesh.castShadow=true;reedMesh.receiveShadow=true;reedMesh.computeBoundingSphere();scene.root.add(reedMesh);
  return {destroy(){texture.dispose();}};
}
