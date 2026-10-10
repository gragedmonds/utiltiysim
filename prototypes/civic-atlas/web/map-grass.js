import * as THREE from '/viewer/vendor/three.module.js';

// One world-space turf palette for terrain, verges, private lawns and parks.
// Original vertex colors only identify vegetated triangles; paved civic parcels
// stay paved. Fixed metre-scale variation cannot slide during pan/zoom, and
// standard lighting/shadows remain active. Artwork pixels remain unchanged.
export function installGrassPalette(scene){
  const materials=new Set();let surfaces=0;
  scene.root.traverse(mesh=>{
    if(!mesh.isMesh||mesh.userData.atlasSurface!==0||Array.isArray(mesh.material))return;
    const colors=mesh.geometry.attributes.color;if(!colors)return;
    const mask=new Float32Array(colors.count);
    for(let i=0;i<colors.count;i++)mask[i]=colors.getY(i)>colors.getX(i)*1.10&&colors.getY(i)>colors.getZ(i)*1.12?1:0;
    if(!mask.some(Boolean))return;
    mesh.geometry.setAttribute('atlasTurfMask',new THREE.Float32BufferAttribute(mask,1));
    surfaces++;materials.add(mesh.material);
  });
  for(const material of materials){
    material.onBeforeCompile=shader=>{
      shader.uniforms.atlasTurfLight={value:new THREE.Color('#7a8d3c')};
      shader.uniforms.atlasTurfDark={value:new THREE.Color('#5e712b')};
      shader.vertexShader='attribute float atlasTurfMask; varying float atlasTurf; varying vec2 atlasGroundXZ;\n'+shader.vertexShader;
      shader.vertexShader=shader.vertexShader.replace('#include <begin_vertex>','#include <begin_vertex>\natlasTurf=atlasTurfMask; atlasGroundXZ=(modelMatrix*vec4(position,1.0)).xz;');
      shader.fragmentShader=`uniform vec3 atlasTurfLight; uniform vec3 atlasTurfDark; varying float atlasTurf; varying vec2 atlasGroundXZ;
float atlasGrassHash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
float atlasGrassNoise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.0-2.0*f);return mix(mix(atlasGrassHash(i),atlasGrassHash(i+vec2(1,0)),f.x),mix(atlasGrassHash(i+vec2(0,1)),atlasGrassHash(i+vec2(1,1)),f.x),f.y);}
`+shader.fragmentShader;
      shader.fragmentShader=shader.fragmentShader.replace('#include <color_fragment>',`vec3 atlasTextureColor=diffuseColor.rgb;
#include <color_fragment>
if(atlasTurf>.5){
 float broad=atlasGrassNoise(atlasGroundXZ/31.0),turfPatch=atlasGrassNoise(atlasGroundXZ/5.0),fine=atlasGrassNoise(atlasGroundXZ/.85);
 float variation=clamp(.22+broad*.40+turfPatch*.32,0.0,1.0);
 vec3 turf=mix(atlasTurfDark,atlasTurfLight,variation);
 float grain=mix(.90,1.09,fine);
 // Restrained mowing variation sits over irregular fine grain, never stripes
 // mapped separately per parcel or a repeating giant texture square.
 float mowing=1.0+.024*sin((atlasGroundXZ.x+atlasGroundXZ.y*.18)*.8);
 diffuseColor.rgb=turf*mix(vec3(.90),atlasTextureColor,.42)*grain*mowing;
}`);
    };
    material.customProgramCacheKey=()=> 'civic-unified-grass/1';material.needsUpdate=true;
  }
  scene.renderRequested=true;return{surfaces,materials:materials.size};
}
