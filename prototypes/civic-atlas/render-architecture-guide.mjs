// Render camera-calibrated architecture references for painted sprite production.
// This uses the application's actual geometry, not a separate inferred camera.
import {mkdir, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||new URL('../../out/civic-atlas/browser/node_modules/playwright-core/index.mjs',import.meta.url).href);
const output=process.env.ATLAS_GUIDE_OUTPUT||fileURLToPath(new URL('../../out/civic-atlas/art-guides/',import.meta.url));
const stories=Number(process.env.ATLAS_GUIDE_STORIES||1);
const commercial=process.env.ATLAS_GUIDE_KIND==='commercial';
await mkdir(output,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage','--enable-unsafe-swiftshader','--no-proxy-server']});
try{
  const page=await browser.newPage();
  await page.goto((process.env.ATLAS_URL||'http://127.0.0.1:8040')+'/style.css');
  const result=await page.evaluate(async ({stories,commercial})=>{
    const THREE=await import('/viewer/vendor/three.module.js');
    const {buildingGeometry}=await import('/map-buildings.js');
    const cell=512,width=cell*4,height=cell*2;
    const renderer=new THREE.WebGLRenderer({alpha:true,antialias:true,preserveDrawingBuffer:true});
    renderer.setSize(width,height);renderer.setClearColor(0,0);
    renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=.92;
    const scene=new THREE.Scene();
    scene.add(new THREE.HemisphereLight('#edf4fa','#9da995',1.4));
    const sun=new THREE.DirectionalLight('#fff3dc',2.75);sun.position.set(-.45,.68,.3).multiplyScalar(50);scene.add(sun);
    const viewHeight=commercial?36:stories===1?22:25;
    const camera=new THREE.OrthographicCamera(-viewHeight/2,viewHeight/2,viewHeight/2,-viewHeight/2,.1,200);
    const target=new THREE.Vector3(0,commercial?3:stories===1?2:3,0);
    camera.position.copy(target).add(new THREE.Vector3(.16,1.20,.82).normalize().multiplyScalar(60));camera.lookAt(target);camera.updateMatrixWorld();
    const columns=[0,-Math.PI/2,Math.PI,Math.PI/2];
    renderer.setScissorTest(true);
    const tiles=[];
    for(let row=0;row<2;row++)for(let column=0;column<4;column++){
      const family=commercial?(column<2?'brick_shop':'restaurant'):(stories===1?'cottage':'craftsman');
      const home=commercial?{id:'CALIBRATION-'+family,width:14.96,depth:24,height:row===0?4.3:6.9,stories:row+1,roof:'flat'}:{id:'CALIBRATION-'+row,width:12,depth:9,height:stories===1?3.7:6.3,stories,roof:row===0?'gable':'hip'};
      const geometry=buildingGeometry(family,home);
      const material=new THREE.MeshStandardMaterial({vertexColors:true,roughness:.9});
      const mesh=new THREE.Mesh(geometry,material);mesh.rotation.y=commercial?(column%2===0?0:Math.PI):columns[column];scene.add(mesh);
      renderer.setViewport(column*cell,(1-row)*cell,cell,cell);renderer.setScissor(column*cell,(1-row)*cell,cell,cell);renderer.clear();renderer.render(scene,camera);
      tiles.push({row,column,family,frontage:commercial?(column%2===0?'+Z':'-Z'):['+Z','-X','-Z','+X'][column],...home});
      scene.remove(mesh);geometry.dispose();material.dispose();
    }
    const image=renderer.domElement.toDataURL('image/png');renderer.dispose();
    return {image,metadata:{width,height,columns:4,rows:2,viewHeight,cameraDirection:[.16,1.20,.82],targetY:target.y,tiles}};
  },{stories,commercial});
  const name=commercial?'architecture-guide-commercial':`architecture-guide-${stories}-storey`;
  await writeFile(`${output}/${name}.png`,Buffer.from(result.image.split(',')[1],'base64'));
  await writeFile(`${output}/${name}.json`,JSON.stringify(result.metadata,null,2)+'\n');
  console.log(`${output}/${name}.png`);
}finally{await browser.close();}
