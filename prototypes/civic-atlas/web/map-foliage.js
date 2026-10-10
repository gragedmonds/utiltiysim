import * as THREE from '/viewer/vendor/three.module.js';

// A fixed aerial camera allows an illustrated tree to retain leaf-level detail
// at neighborhood scale. Only the skin changes: locations and river/road masks
// come from the existing decorative planting plan, never from the artwork.
function cropTree(source,column,row,columns,rows){
  const w=Math.floor(source.width/columns),h=Math.floor(source.height/rows);
  const canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;
  const ctx=canvas.getContext('2d',{willReadFrequently:true});
  ctx.drawImage(source,column*w,row*h,w,h,0,0,w,h);
  const data=ctx.getImageData(0,0,w,h).data;
  let left=w,top=h,right=0,bottom=0;
  for(let y=0;y<h;y++)for(let x=0;x<w;x++)if(data[(y*w+x)*4+3]>32){left=Math.min(left,x);right=Math.max(right,x);top=Math.min(top,y);bottom=Math.max(bottom,y);}
  if(left>=right||top>=bottom)throw new Error('Foliage atlas contains an empty cell.');
  left=Math.max(0,left-3);top=Math.max(0,top-3);right=Math.min(w-1,right+3);bottom=Math.min(h-1,bottom+3);
  const out=document.createElement('canvas');out.width=right-left+1;out.height=bottom-top+1;
  out.getContext('2d').drawImage(canvas,left,top,out.width,out.height,0,0,out.width,out.height);
  const texture=new THREE.CanvasTexture(out);texture.colorSpace=THREE.SRGBColorSpace;
  texture.anisotropy=4;
  return {texture,aspect:out.height/out.width};
}

function contactShadow(){
  const c=document.createElement('canvas');c.width=c.height=64;
  const ctx=c.getContext('2d'),g=ctx.createRadialGradient(32,32,1,32,32,30);
  g.addColorStop(0,'rgba(26,45,29,.28)');g.addColorStop(.4,'rgba(26,45,29,.20)');g.addColorStop(1,'rgba(26,45,29,0)');
  ctx.fillStyle=g;ctx.fillRect(0,0,64,64);
  return new THREE.CanvasTexture(c);
}

export async function installIllustratedFoliage(scene,{url,columns=3,rows=2,signal}={}){
  const texture=await new THREE.TextureLoader().loadAsync(url);
  if(signal?.aborted){texture.dispose();return null;}
  const cells=Array.from({length:columns*rows},(_,i)=>cropTree(texture.image,i%columns,Math.floor(i/columns),columns,rows));
  texture.dispose();
  const sources=[];
  scene.root.traverse(mesh=>{if(mesh.isInstancedMesh&&mesh.userData.atlasTreeKind!==undefined)sources.push(mesh);});
  const plants=[],matrix=new THREE.Matrix4(),position=new THREE.Vector3(),rotation=new THREE.Quaternion(),scale=new THREE.Vector3();
  for(const source of sources){
    for(let i=0;i<source.count;i++){
      source.getMatrixAt(i,matrix);matrix.decompose(position,rotation,scale);
      if(scale.x<.001||scale.y<.001)continue; // Existing source masks remain authoritative.
      const seed=Math.abs(Math.round(position.x*73856093+position.z*19349663));
      // Mostly broadleaf crowns, with occasional evergreen and pale birch.
      const grove=source.userData.atlasGrove===true,species=grove?source.userData.atlasTreeKind:seed%13<10?seed%3:3+seed%3;
      plants.push({x:position.x,y:position.y,z:position.z,scale:scale.x,species,seed,grove});
    }
    source.visible=false;
  }
  const group=new THREE.Group();group.name='Illustrated foliage';group.userData.visualOnly=true;scene.root.add(group);
  const dummy=new THREE.Object3D(),batches=[];
  const quad=new THREE.PlaneGeometry(1,1);quad.translate(0,.5,0);
  const facing=scene.camera.quaternion.clone();
  cells.forEach((cell,species)=>{
    const trees=plants.filter(p=>p.species===species);
    const mesh=new THREE.InstancedMesh(quad,new THREE.MeshBasicMaterial({map:cell.texture,alphaTest:.12,side:THREE.DoubleSide,toneMapped:false}),trees.length);
    trees.forEach((p,i)=>{
      const width=6.4*p.scale;
      dummy.position.set(p.x,p.y+.06,p.z);dummy.quaternion.copy(facing);
      dummy.scale.set(width,width*cell.aspect,1);dummy.updateMatrix();mesh.setMatrixAt(i,dummy.matrix);
      const shade=p.grove?.82+(p.seed%12)/100:.92;mesh.setColorAt(i,new THREE.Color().setRGB(shade*.94,Math.min(1,shade*1.07),shade*1.02));
    });
    mesh.computeBoundingSphere();mesh.userData.visualOnly=true;group.add(mesh);
    const faded=new THREE.InstancedMesh(quad,new THREE.MeshBasicMaterial({map:cell.texture,alphaTest:.035,transparent:true,opacity:.20,depthWrite:false,side:THREE.DoubleSide,toneMapped:false}),trees.length);
    faded.count=0;faded.renderOrder=3;faded.frustumCulled=false;group.add(faded);
    const matrices=trees.map((p,i)=>{const m=new THREE.Matrix4();mesh.getMatrixAt(i,m);return m;});batches.push({mesh,faded,trees,matrices,aspect:cell.aspect});
  });
  const shadowMap=contactShadow(),shadowGeometry=new THREE.PlaneGeometry(1,1);shadowGeometry.rotateX(-Math.PI/2);
  const shadows=new THREE.InstancedMesh(shadowGeometry,new THREE.MeshBasicMaterial({map:shadowMap,transparent:true,depthWrite:false,toneMapped:false}),plants.length);
  plants.forEach((p,i)=>{
    const size=5.8*p.scale;dummy.position.set(p.x+.5,p.y+.08,p.z+.5);dummy.quaternion.identity();dummy.scale.set(size,1,size*.8);dummy.updateMatrix();shadows.setMatrixAt(i,dummy.matrix);
  });
  shadows.computeBoundingSphere();group.add(shadows);
  const shadowMatrices=plants.map((p,i)=>{const m=new THREE.Matrix4();shadows.getMatrixAt(i,m);return m;});
  const right=new THREE.Vector3(1,0,0).applyQuaternion(facing),up=new THREE.Vector3(0,1,0).applyQuaternion(facing),zero=new THREE.Matrix4().makeScale(0,0,0);
  const setSelected=home=>{
    const obscured=new Set();
    let bounds=null;
    if(home){
      const base=new THREE.Vector3(home.x,home.elevationM??scene.heightAt(home.x,home.z),home.z),angle=-home.angle,c=Math.cos(angle),s=Math.sin(angle),xs=[],ys=[];
      for(const x of[-home.width/2-1.3,home.width/2+1.3])for(const z of[-home.depth/2-1.3,home.depth/2+1.3])for(const y of[0,home.height+3]){
        const point=base.clone().add(new THREE.Vector3(x*c+z*s,y,-x*s+z*c));xs.push(point.dot(right));ys.push(point.dot(up));
      }
      if(home.front){const p=new THREE.Vector3(home.front.x,scene.heightAt(home.front.x,home.front.z),home.front.z);xs.push(p.dot(right));ys.push(p.dot(up));}
      bounds={minX:Math.min(...xs)-1,maxX:Math.max(...xs)+1,minY:Math.min(...ys)-1,maxY:Math.max(...ys)+1};
    }
    for(const batch of batches){
      let count=0;
      batch.trees.forEach((p,i)=>{
        const base=new THREE.Vector3(p.x,p.y+.06,p.z),width=6.4*p.scale,x=base.dot(right),y=base.dot(up),overlap=bounds&&x+width/2>bounds.minX&&x-width/2<bounds.maxX&&y+width*batch.aspect>bounds.minY&&y<bounds.maxY;
        batch.mesh.setMatrixAt(i,overlap?zero:batch.matrices[i]);
        if(overlap){batch.faded.setMatrixAt(count++,batch.matrices[i]);obscured.add(p);}
      });
      batch.mesh.instanceMatrix.needsUpdate=true;batch.mesh.computeBoundingSphere();batch.faded.count=count;batch.faded.instanceMatrix.needsUpdate=true;
    }
    plants.forEach((p,i)=>shadows.setMatrixAt(i,obscured.has(p)?zero:shadowMatrices[i]));shadows.instanceMatrix.needsUpdate=true;shadows.computeBoundingSphere();
    scene.renderRequested=true;
    return obscured.size;
  };
  scene.renderRequested=true;scene.renderer.shadowMap.needsUpdate=true;
  return {trees:plants.length,batches:cells.length+1,setSelected,destroy(){group.removeFromParent();for(const cell of cells)cell.texture.dispose();shadowMap.dispose();quad.dispose();shadowGeometry.dispose();group.children.forEach(m=>m.material.dispose());}};
}
