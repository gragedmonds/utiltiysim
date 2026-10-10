import * as THREE from '/viewer/vendor/three.module.js';
import {hash} from '/viewer/lowpoly.js';

/**
 * Optional calibrated architectural artwork for the fixed Civic Atlas camera.
 * Atlas contract: four columns +Z, -X, -Z, +X frontage; row 0 one-storey
 * gable house, row 1 hip house. Pass stories:2 for the separate two-storey atlas.
 * With kind:commercial: columns brick_shop +Z/-Z, restaurant +Z/-Z;
 * rows one/two storeys. Empty margins must be transparent.
 * Geometry remains authoritative for picking, shadow casting and unsupported
 * premises. Artwork never changes identities, dimensions, use or connections.
 *
 * createBuildingSprites(scene, town, {url, calibrated:true}) returns a handle
 * immediately; await handle.ready before screenshots. Without an explicitly
 * calibrated atlas it leaves the normal geometry intact. Experimental artwork
 * can be inspected with allowUncalibratedPreview:true, never the default.
 */
export function createBuildingSprites(scene,town,options={}){
  const commercial=options.kind==='commercial',atlasStories=commercial?null:options.stories===2?2:1;
  const stats={ready:false,enabled:false,replaced:0,eligible:0,unsupported:0,stories:atlasStories,reason:'awaiting artwork'};
  const group=new THREE.Group();group.name='atlas-illustrated-houses';group.visible=false;
  const replacements=[],owned=[],proxies=[],spriteBatches=[],coveredMeshes=new Map();
  let disposed=false,active=false,wanted=options.enabled!==false,texture;
  const zero=new THREE.Matrix4().makeScale(0,0,0),dummy=new THREE.Object3D();
  const normalize=a=>Math.atan2(Math.sin(a),Math.cos(a));
  function apply(value){
    value=Boolean(value)&&stats.ready&&!disposed;
    if(value===active)return;
    for(const entry of replacements){entry.mesh.setMatrixAt(entry.slot,value?zero:entry.matrix);entry.mesh.instanceMatrix.needsUpdate=true;}
    for(const mesh of new Set(replacements.map(r=>r.mesh)))mesh.computeBoundingSphere();
    for(const [mesh,originalVisibility]of coveredMeshes)mesh.visible=value?false:originalVisibility;
    group.visible=value;
    for(const proxy of proxies)proxy.visible=value;
    active=value;stats.enabled=value;scene.renderRequested=true;if(scene.renderer?.shadowMap)scene.renderer.shadowMap.needsUpdate=true;
  }
  function destroy(){
    apply(false);disposed=true;group.removeFromParent();
    scene.pickMeshes=scene.pickMeshes.filter(mesh=>!proxies.includes(mesh));
    for(const proxy of proxies)proxy.removeFromParent();
    for(const item of owned)item.dispose();texture?.dispose();
  }
  function cells(image){
    const canvas=document.createElement('canvas');canvas.width=image.width;canvas.height=image.height;
    const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(image,0,0);
    const rgba=ctx.getImageData(0,0,image.width,image.height).data,result=[];
    for(let row=0;row<2;row++)for(let col=0;col<4;col++){
      const left=Math.round(col*image.width/4),right=Math.round((col+1)*image.width/4),top=Math.round(row*image.height/2),bottom=Math.round((row+1)*image.height/2);
      let x0=right,x1=left,y0=bottom,y1=top;
      for(let y=top+1;y<bottom-1;y++)for(let x=left+1;x<right-1;x++)if(rgba[(y*image.width+x)*4+3]>64){x0=Math.min(x0,x);x1=Math.max(x1,x);y0=Math.min(y0,y);y1=Math.max(y1,y);}
      if(x1<=x0||y1<=y0)throw Error(`House atlas cell ${row},${col} has no visible artwork.`);
      result.push({u0:(x0-.5)/image.width,u1:(x1+1.5)/image.width,v0:1-(y1+1.5)/image.height,v1:1-(y0-.5)/image.height});
    }
    return result;
  }
  function projectedEnvelope(home,geometry){
    const ground=new THREE.Vector3(home.x,home.elevationM??scene.heightAt(home.x,home.z),home.z);
    const right=new THREE.Vector3(1,0,0).applyQuaternion(scene.camera.quaternion),up=new THREE.Vector3(0,1,0).applyQuaternion(scene.camera.quaternion);
    const angle=-home.angle+(home.side===-1?Math.PI:0)+Math.PI,c=Math.cos(angle),s=Math.sin(angle);
    let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
    // Project the retained architecture itself, including its eaves/porch,
    // rather than stretching to the too-tall corners of an imagined roof box.
    const positions=geometry.attributes.position;
    for(let i=0;i<positions.count;i++){
      const x=positions.getX(i),y=positions.getY(i),z=positions.getZ(i),p=new THREE.Vector3(x*c+z*s,y,-x*s+z*c),sx=p.dot(right),sy=p.dot(up);
      minX=Math.min(minX,sx);maxX=Math.max(maxX,sx);minY=Math.min(minY,sy);maxY=Math.max(maxY,sy);
    }
    const position=ground.clone().addScaledVector(right,(minX+maxX)/2).addScaledVector(up,(minY+maxY)/2);
    // A camera-facing card otherwise puts its lower edge underground when the
    // footprint has depth. Move only along the viewing normal: screen position,
    // scale and footprint registration remain unchanged, but terrain cannot
    // slice through the painted facade. Source geometry still supplies shadows.
    const normal=new THREE.Vector3(0,0,1).applyQuaternion(scene.camera.quaternion);
    const bottomY=position.y-Math.abs(up.y)*(maxY-minY)/2-Math.abs(right.y)*(maxX-minX)/2;
    if(bottomY<ground.y+.10&&normal.y>.05)position.addScaledVector(normal,(ground.y+.10-bottomY)/normal.y);
    return {position,width:maxX-minX,height:maxY-minY};
  }
  const ready=(async()=>{
    if(!options.url){stats.reason='no architectural atlas configured';return null;}
    if(!options.calibrated&&!options.allowUncalibratedPreview){stats.reason='atlas awaits camera calibration';return null;}
    try{
      texture=await new THREE.TextureLoader().loadAsync(options.url);if(disposed){texture.dispose();return null;}
      texture.colorSpace=THREE.SRGBColorSpace;texture.anisotropy=4;
      const crops=cells(texture.image),families=town.atlasDesign?.buildingFamilies||{},targets=new Map();
      const maxAngle=(options.maxAngleDegrees??12)*Math.PI/180,refAspect=options.referenceAspect??(commercial?14.96/24:12/9);
      town.premises.forEach((home,index)=>{
        const family=families[home.id],stories=Number(home.stories||1);
        const supported=commercial
          ? ['brick_shop','restaurant'].includes(family)&&[1,2].includes(stories)&&home.roof==='flat'
          : home.premiseType==='residential'&&family===(atlasStories===2?'craftsman':'cottage')&&stories===atlasStories&&['gable','hip'].includes(home.roof);
        if(!supported||home.solar){stats.unsupported++;return;}
        const ratio=home.width/home.depth/refAspect;if(Math.max(ratio,1/ratio)>(options.maxAspectDistortion??1.45)){stats.unsupported++;return;}
        const yaw=normalize(-home.angle+(home.side===-1?Math.PI:0)+Math.PI),angles=commercial?[0,Math.PI]:[0,-Math.PI/2,Math.PI,Math.PI/2];
        let col=0;for(let i=1;i<angles.length;i++)if(Math.abs(normalize(yaw-angles[i]))<Math.abs(normalize(yaw-angles[col])))col=i;
        if(Math.abs(normalize(yaw-angles[col]))>maxAngle){stats.unsupported++;return;}
        const tile=commercial?(stories===2?4:0)+(family==='restaurant'?2:0)+col:(home.roof==='hip'?4:0)+col;
        targets.set(index,{home,index,tile});
      });
      stats.eligible=targets.size;
      const pickMaterial=new THREE.MeshBasicMaterial({colorWrite:false,depthWrite:false});owned.push(pickMaterial);
      scene.root.traverse(mesh=>{
        if(!mesh.isInstancedMesh||!mesh.userData.atlasBuilding)return;
        const picked=[];
        (mesh.userData.premiseIndices||[]).forEach((index,slot)=>{
          if(!targets.has(index))return;
          const matrix=new THREE.Matrix4();mesh.getMatrixAt(slot,matrix);
          replacements.push({mesh,slot,matrix});picked.push({index,matrix});targets.get(index).geometry=mesh.geometry;
        });
        if(!picked.length)return;
        if(picked.length===mesh.count)coveredMeshes.set(mesh,mesh.visible);
        // Colorless source geometry retains exact ray hits and physical shadows.
        // Unlike hiding the source mesh, this cannot turn clicks into road hits.
        const proxy=new THREE.InstancedMesh(mesh.geometry,pickMaterial,picked.length);
        proxy.userData.premiseIndices=picked.map(p=>p.index);proxy.userData.atlasSpritePicking=true;
        picked.forEach((p,i)=>proxy.setMatrixAt(i,p.matrix));proxy.castShadow=true;proxy.visible=false;proxy.computeBoundingSphere();proxies.push(proxy);
      });
      const represented=new Set(proxies.flatMap(p=>p.userData.premiseIndices));
      const material=new THREE.MeshBasicMaterial({map:texture,alphaTest:.25,side:THREE.DoubleSide,toneMapped:false});owned.push(material);
      if(!commercial&&options.materialVariation!==false){
        // Material variation is bounded and stable per premise. Preserve baked
        // shading, glazing and masonry detail; change only compatible painted
        // siding/slate tones, never the source roof family or building shape.
        material.onBeforeCompile=shader=>{
          shader.vertexShader='attribute float atlasVariant; attribute vec2 atlasLocalUV; varying float atlasMaterialVariant; varying vec2 atlasArtUV;\n'+shader.vertexShader;
          shader.vertexShader=shader.vertexShader.replace('#include <begin_vertex>','#include <begin_vertex>\natlasMaterialVariant=atlasVariant; atlasArtUV=atlasLocalUV;');
          shader.fragmentShader='varying float atlasMaterialVariant; varying vec2 atlasArtUV;\n'+shader.fragmentShader;
          shader.fragmentShader=shader.fragmentShader.replace('#include <map_fragment>',`#include <map_fragment>
            vec3 atlasRoofTint=vec3(1.0), atlasWallTint=vec3(1.0);
            if(atlasMaterialVariant>3.5){atlasRoofTint=vec3(.95,1.08,.89);atlasWallTint=vec3(.96,1.02,.94);}
            else if(atlasMaterialVariant>2.5){atlasRoofTint=vec3(1.10,1.04,.92);atlasWallTint=vec3(1.03,.99,.91);}
            else if(atlasMaterialVariant>1.5){atlasRoofTint=vec3(.96,1.03,1.08);atlasWallTint=vec3(.92,1.01,1.04);}
            else if(atlasMaterialVariant>.5){atlasRoofTint=vec3(1.18,1.02,.83);atlasWallTint=vec3(1.04,1.015,.96);}
            float atlasLuma=dot(diffuseColor.rgb,vec3(.2126,.7152,.0722));
            float atlasRoofMask=smoothstep(.34,.57,atlasArtUV.y)*(1.0-smoothstep(.015,.075,diffuseColor.r-diffuseColor.b));
            float atlasWallMask=smoothstep(.27,.55,atlasLuma)*(1.0-atlasRoofMask);
            diffuseColor.rgb*=mix(vec3(1.0),atlasRoofTint,atlasRoofMask*.85);
            diffuseColor.rgb*=mix(vec3(1.0),atlasWallTint,atlasWallMask*.70);
          `);
        };
        material.customProgramCacheKey=()=> 'atlas-house-material-variation/1';
      }else if(commercial&&options.materialVariation!==false){
        material.onBeforeCompile=shader=>{
          shader.vertexShader='attribute float atlasVariant; attribute vec2 atlasLocalUV; varying float atlasMaterialVariant; varying vec2 atlasArtUV;\n'+shader.vertexShader;
          shader.vertexShader=shader.vertexShader.replace('#include <begin_vertex>','#include <begin_vertex>\natlasMaterialVariant=atlasVariant; atlasArtUV=atlasLocalUV;');
          shader.fragmentShader='varying float atlasMaterialVariant; varying vec2 atlasArtUV;\n'+shader.fragmentShader;
          shader.fragmentShader=shader.fragmentShader.replace('#include <map_fragment>',`#include <map_fragment>
            vec3 atlasAwningTint=vec3(1.0);
            if(atlasMaterialVariant>3.5)atlasAwningTint=vec3(.90,1.10,.90);
            else if(atlasMaterialVariant>2.5)atlasAwningTint=vec3(1.85,.78,1.10);
            else if(atlasMaterialVariant>1.5)atlasAwningTint=vec3(1.55,1.02,.80);
            else if(atlasMaterialVariant>.5)atlasAwningTint=vec3(.70,.91,1.48);
            float atlasAwningMask=(1.0-smoothstep(.25,.42,atlasArtUV.y))*smoothstep(.02,.18,(diffuseColor.g-diffuseColor.r)/max(diffuseColor.g,.015))*smoothstep(.02,.16,(diffuseColor.g-diffuseColor.b)/max(diffuseColor.g,.015));
            diffuseColor.rgb*=mix(vec3(1.0),atlasAwningTint,atlasAwningMask*.90);
          `);
        };
        material.customProgramCacheKey=()=> 'atlas-commercial-awning-variation/1';
      }

      for(let tile=0;tile<8;tile++){
        const homes=[...targets.values()].filter(t=>t.tile===tile&&represented.has(t.index));if(!homes.length)continue;
        const crop=crops[tile],geometry=new THREE.PlaneGeometry(1,1),uv=geometry.attributes.uv;
        geometry.setAttribute('atlasLocalUV',uv.clone());geometry.setAttribute('atlasVariant',new THREE.InstancedBufferAttribute(new Float32Array(homes.map(({home})=>hash(home.id)%5)),1));
        for(let i=0;i<uv.count;i++)uv.setXY(i,crop.u0+uv.getX(i)*(crop.u1-crop.u0),crop.v0+uv.getY(i)*(crop.v1-crop.v0));
        owned.push(geometry);const mesh=new THREE.InstancedMesh(geometry,material,homes.length);mesh.name=`atlas-house-art-${tile}`;
        homes.forEach(({home,geometry:sourceGeometry},i)=>{const envelope=projectedEnvelope(home,sourceGeometry);dummy.position.copy(envelope.position);dummy.quaternion.copy(scene.camera.quaternion);dummy.scale.set(envelope.width,envelope.height,1);dummy.updateMatrix();mesh.setMatrixAt(i,dummy.matrix);});
        mesh.computeBoundingSphere();mesh.userData.atlasHouseArtwork=true;group.add(mesh);spriteBatches.push(mesh);
      }
      for(const proxy of proxies){scene.root.add(proxy);scene.pickMeshes.push(proxy);}
      scene.root.add(group);stats.replaced=represented.size;stats.hiddenSourceBatches=coveredMeshes.size;stats.ready=true;stats.reason=options.calibrated?'calibrated artwork':'uncalibrated development preview';apply(wanted);
      return {stats};
    }catch(error){stats.reason=String(error.message||error);destroy();return null;}
  })();
  return {ready,stats,setEnabled(value){wanted=Boolean(value);apply(wanted);},update(){},destroy};
}
