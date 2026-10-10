import * as THREE from '/viewer/vendor/three.module.js';
import {hash} from '/viewer/lowpoly.js';

function inside(p,polygon){let hit=false;for(let i=0,j=polygon.length-1;i<polygon.length;j=i++){const a=polygon[i],b=polygon[j];if((a.z>p.z)!==(b.z>p.z)&&p.x<(b.x-a.x)*(p.z-a.z)/(b.z-a.z)+a.x)hit=!hit;}return hit;}
function distance(p,a,b){const dx=b.x-a.x,dz=b.z-a.z,t=Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.z-a.z)*dz)/(dx*dx+dz*dz||1)));return Math.hypot(p.x-a.x-dx*t,p.z-a.z-dz*t);}

// These small surface illustrations are decoration fitted to retained physical
// parcels. They do not add garden, irrigation, patio or vegetation records.
function gardenTile(kind){
  const canvas=document.createElement('canvas');canvas.width=512;canvas.height=256;const c=canvas.getContext('2d');
  const ellipse=(x,y,rx,ry,color)=>{c.fillStyle=color;c.beginPath();c.ellipse(x,y,rx,ry,0,0,Math.PI*2);c.fill();};
  c.fillStyle=kind==='patio'?'#b6aa90':'#75694e';c.beginPath();c.roundRect(8,8,496,240,kind==='flowers'?70:12);c.fill();c.save();c.clip();
  for(let i=0;i<8000;i++){const n=hash(`${kind}:grain:${i}`),x=n%512,y=(n>>>10)%256;c.fillStyle=`rgba(${n%2?'235,227,205':'43,46,34'},.05)`;c.fillRect(x,y,1.5,1.5);}
  if(kind==='patio'){
    c.strokeStyle='#928e7b';c.lineWidth=2;
    for(let y=10;y<248;y+=48){c.beginPath();c.moveTo(9,y);c.lineTo(503,y);c.stroke();for(let x=(y%96<48?8:46);x<504;x+=82){c.beginPath();c.moveTo(x,y);c.lineTo(x,y+48);c.stroke();}}
    ellipse(406,78,32,26,'rgba(59,66,47,.22)');ellipse(399,68,26,22,'#d7c9a6');ellipse(399,68,22,18,'#c8b890');
    for(const [x,y]of[[351,66],[440,70]]){c.fillStyle='#6b7760';c.fillRect(x-10,y-16,20,30);c.fillStyle='#b6b394';c.fillRect(x-8,y-15,16,6);}
  }
  const planted=kind==='patio'?8:kind==='vegetables'?54:75;
  for(let i=0;i<planted;i++){
    const n=hash(`${kind}:plant:${i}`),x=kind==='vegetables'?45+(i%9)*52:kind==='patio'?27+(i%4)*152:36+n%440,y=kind==='vegetables'?31+Math.floor(i/9)*38:kind==='patio'?25+Math.floor(i/4)*204:40+(n>>>10)%170;
    const radius=kind==='vegetables'?12:12+n%11;
    ellipse(x+5,y+5,radius+2,radius*.78,'rgba(28,41,26,.3)');
    for(let leaf=0;leaf<5;leaf++){const a=leaf*2.4;ellipse(x+Math.cos(a)*radius*.42,y+Math.sin(a)*radius*.32,radius*.68,radius*.52,['#576e42','#71894e','#8b9a60','#657d4b'][n%4]);}
    if(kind==='flowers'&&n%3!==0)for(let j=0;j<4;j++){const a=j*2.4;ellipse(x+Math.cos(a)*6,y+Math.sin(a)*5,2.6,2.2,['#d9cb91','#c5b2c0','#bb8f7e','#e6ddd0'][n%4]);}
  }
  c.restore();const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;texture.anisotropy=8;return texture;
}

export function renderParcelGardens(scene,town){
  const parcels=new Map((town.parcels||[]).map(p=>[p.premiseId,p.polygon])),buildings=new Map((town.buildings||[]).flatMap(b=>(b.premiseIds||[]).map(id=>[id,b.footprint?.polygon])));
  const batches=new Map(['flowers','patio','vegetables'].map(kind=>[kind,{positions:[],uv:[],count:0}]));
  const roads=town.roads.flatMap(r=>r.points.slice(1).map((b,i)=>({a:r.points[i],b,width:r.pavementWidthM||8})));
  for(const home of town.premises){
    if(home.premiseType!=='residential')continue;
    const polygon=parcels.get(home.id),footprint=buildings.get(home.id);if(!polygon||!footprint||!home.front)continue;
    const seed=hash(home.id),dx=home.front.x-home.x,dz=home.front.z-home.z,len=Math.hypot(dx,dz);if(len<1)continue;
    const forward={x:dx/len,z:dz/len},right={x:forward.z,z:-forward.x};
    const project=(p,axis)=>(p.x-home.x)*axis.x+(p.z-home.z)*axis.z;
    const front=Math.max(...footprint.map(p=>project(p,forward))),back=Math.min(...footprint.map(p=>project(p,forward)));
    const left=Math.min(...footprint.map(p=>project(p,right))),rightEdge=Math.max(...footprint.map(p=>project(p,right)));
    const point=(x,z)=>({x:home.x+right.x*x+forward.x*z,z:home.z+right.z*x+forward.z*z});
    const safe=p=>inside(p,polygon)&&polygon.every((a,i)=>distance(p,a,polygon[(i+1)%polygon.length])>.35)&&!inside(p,footprint)&&footprint.every((a,i)=>distance(p,a,footprint[(i+1)%footprint.length])>.15)&&roads.every(s=>distance(p,s.a,s.b)>s.width/2+2)&&distance(p,home,home.front)>1.35;
    function patch(kind,cx,cz,width,depth){
      // Check the whole patch, including its edges, before adding its surface.
      for(let z=0;z<=4;z++)for(let x=0;x<=4;x++)if(!safe(point(cx+(x/4-.5)*width,cz+(z/4-.5)*depth)))return false;
      const batch=batches.get(kind),nx=Math.max(1,Math.ceil(width/1.4)),nz=Math.max(1,Math.ceil(depth/1.4));
      for(let z=0;z<nz;z++)for(let x=0;x<nx;x++)for(const [u,v]of[[x/nx,z/nz],[(x+1)/nx,z/nz],[(x+1)/nx,(z+1)/nz],[x/nx,z/nz],[(x+1)/nx,(z+1)/nz],[x/nx,(z+1)/nz]]){
        const p=point(cx+(u-.5)*width,cz+(v-.5)*depth);batch.positions.push(p.x,scene.heightAt(p.x,p.z)+.115,p.z);batch.uv.push(u,v);
      }
      batch.count++;return true;
    }
    // Foundation planting frames the door without covering the saved access.
    if(seed%6!==0){
      const width=Math.max(1.5,(rightEdge-left)/2-2.5);
      patch('flowers',left+width/2+.35,front+1.0,width,1.25);
      patch('flowers',rightEdge-width/2-.35,front+1.0,width,1.25);
    }
    // Some yards stay simple lawn. Others have one coherent rear program.
    if(seed%5===0)patch('patio',(left+rightEdge)/2-1.8,back-3.1,5.0,4.8);
    else if(seed%4===0)patch('vegetables',seed%2?left+1.9:rightEdge-1.9,back-3.4,3.3,4.1);
    else if(seed%3===0)patch('flowers',rightEdge+1.2,(front+back)/2,1.6,Math.max(2,(front-back)*.65));
  }
  const textures=[];let patches=0;
  for(const [kind,batch]of batches){
    if(!batch.count)continue;patches+=batch.count;const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(batch.positions,3));geometry.setAttribute('uv',new THREE.Float32BufferAttribute(batch.uv,2));geometry.computeVertexNormals();
    const texture=gardenTile(kind);textures.push(texture);const mesh=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({map:texture,transparent:true,alphaTest:.05,side:THREE.DoubleSide,roughness:1}));mesh.receiveShadow=true;mesh.userData.atlasGarden=true;scene.root.add(mesh);
  }
  return{patches,destroy(){textures.forEach(t=>t.dispose());}};
}
