import * as THREE from '/viewer/vendor/three.module.js';

// Original atlas pixels remain untouched on disk. Normalize the diffuse tiles
// to retain Civic Atlas's material palette while adding authored surface detail.
function tile(source,index){
  const width=Math.floor(source.width/3),height=Math.floor(source.height/2),c=document.createElement('canvas');c.width=width;c.height=height;
  const ctx=c.getContext('2d',{willReadFrequently:true});ctx.drawImage(source,(index%3)*width,Math.floor(index/3)*height,width,height,0,0,width,height);
  const pixels=ctx.getImageData(0,0,width,height),mean=[0,0,0];
  for(let i=0;i<pixels.data.length;i+=4)for(let k=0;k<3;k++)mean[k]+=pixels.data[i+k]/(width*height);
  for(let i=0;i<pixels.data.length;i+=4){for(let k=0;k<3;k++)pixels.data[i+k]=Math.min(255,Math.max(100,230*Math.pow(pixels.data[i+k]/Math.max(1,mean[k]),index===0?.42:.85)));pixels.data[i+3]=255;}
  ctx.putImageData(pixels,0,0);const texture=new THREE.CanvasTexture(c);texture.colorSpace=THREE.SRGBColorSpace;texture.wrapS=texture.wrapT=THREE.RepeatWrapping;texture.anisotropy=8;return texture;
}

export async function installMaterialAtlas(scene,{url,signal}={}){
  const source=await new THREE.TextureLoader().loadAsync(url);
  if(signal?.aborted){source.dispose();return null;}
  const textures=Array.from({length:6},(_,i)=>tile(source.image,i));source.dispose();
  const materials=new Set();
  scene.root.traverse(mesh=>{
    if(!mesh.isMesh||Array.isArray(mesh.material))return;
    if(mesh.userData.atlasSurface!==undefined){
      const uv=[],position=mesh.geometry.attributes.position,size=mesh.userData.atlasSurface===0?2.2:4;
      for(let i=0;i<position.count;i++)uv.push(position.getX(i)/size,position.getZ(i)/size);
      mesh.geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));
      mesh.material.map=textures[mesh.userData.atlasSurface];mesh.material.needsUpdate=true;
    }
    if(mesh.material.userData.atlasArchitecture)materials.add(mesh.material);
  });
  for(const material of materials){material.userData.atlasTextures=textures;material.needsUpdate=true;}
  scene.renderRequested=true;
  return {tiles:textures.length,destroy(){textures.forEach(texture=>texture.dispose());}};
}
