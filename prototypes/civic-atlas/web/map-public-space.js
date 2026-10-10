import * as THREE from '/viewer/vendor/three.module.js';
import {GeometryBuilder,roofGeometry} from '/viewer/lowpoly.js';

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
