import {mkdir,writeFile} from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||new URL('../../out/civic-atlas/browser/node_modules/playwright-core/index.mjs',import.meta.url).href);
const base=process.env.ATLAS_URL||'http://127.0.0.1:8041';
const output=process.env.ATLAS_GUIDE_OUTPUT||'out/civic-atlas-town500/guides';
const requested=process.env.ATLAS_TEMPLATE||'all';
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage','--enable-unsafe-swiftshader','--no-proxy-server']});
try{
 const page=await browser.newPage({viewport:{width:1600,height:1000}});
 await page.goto(base+'/block-study.html?art=native');
 await page.waitForSelector('body[data-ready=true]',{timeout:180000});
 const keys=await page.evaluate(requested=>{
  const definitions=window.blockStudy.town.atlasDesign.blockTemplates;
  const keys=requested==='all'?Object.keys(definitions):requested.split(',');
  if(keys.some(key=>!definitions[key]))throw Error('Unknown template');return keys;
 },requested);
 for(const templateId of keys){
  const result=await page.evaluate(async templateId=>{
   const THREE=await import('/viewer/vendor/three.module.js');
   const {TEMPLATE_SCHEMA,templateSourceSignature,templateCamera}=await import('/map-town-plates.js');
   const {map,town}=window.blockStudy,s=map.scene,definition=town.atlasDesign.blockTemplates[templateId];
   const members=town.atlasDesign.blocks.filter(b=>b.templateId===templateId),block=members[0];
   const signature=templateSourceSignature(town,block);
   const mismatches=members.filter(b=>templateSourceSignature(town,b)!==signature).map(b=>b.id);
   if(mismatches.length)throw Error('Template instances differ: '+mismatches.join(','));
   const {camera,target}=templateCamera(map,block,definition),width=1536,height=1024;
   const buffer=new THREE.WebGLRenderTarget(width,height,{colorSpace:THREE.SRGBColorSpace,samples:4}),renderer=s.renderer,old=renderer.getRenderTarget(),pixels=new Uint8Array(width*height*4);
   const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;const ctx=canvas.getContext('2d');
   const project=(p,y=s.heightAt(p.x,p.z))=>{const q=new THREE.Vector3(p.x,y,p.z).project(camera);return{x:(q.x+1)*width/2,y:(1-q.y)*height/2};};
   function capture(){
    renderer.setRenderTarget(buffer);renderer.render(s.scene,camera);renderer.readRenderTargetPixels(buffer,0,0,width,height,pixels);renderer.setRenderTarget(old);
    const frame=ctx.createImageData(width,height);for(let y=0;y<height;y++)frame.data.set(pixels.subarray((height-y-1)*width*4,(height-y)*width*4),y*width*4);ctx.putImageData(frame,0,0);return canvas.toDataURL('image/png');
   }
   const image=capture();
   function outline(points,color,dash,widthPx=2){ctx.strokeStyle=color;ctx.lineWidth=widthPx;ctx.setLineDash(dash);ctx.beginPath();points.map(p=>project(p)).forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.closePath();ctx.stroke();}
   outline(block.polygon,'#ff00c0',[12,8],4);
   const anchors=block.premiseIds.map((id,slot)=>{
    const p=town.premises.find(p=>p.id===id),b=town.buildings.find(b=>b.premiseIds?.includes(id)),parcel=town.parcels.find(p=>p.premiseId===id);
    outline(parcel.polygon,'#00ffff',[5,5]);outline(b.footprint.polygon,'#ff228c',[]);
    return{slot:slot+1,id,address:p.address,buildingType:p.buildingType,stories:p.stories,roof:p.roof,solar:p.solar,solarKW:p.solarKW,hasPool:p.hasPool,width:p.width,depth:p.depth,height:p.height,
     front:p.front,frontPixel:project(p.front),footprint:b.footprint.polygon,parcel:parcel.polygon,...project(p,p.elevationM+p.height*.5)};
   });
   ctx.setLineDash([]);ctx.font='bold 19px sans-serif';
   for(const a of anchors){ctx.fillStyle='white';ctx.fillRect(a.x-17,a.y-17,34,25);ctx.fillStyle='#b00070';ctx.fillText(String(a.slot),a.x-9,a.y+2);}
   const guide=canvas.toDataURL('image/png');buffer.dispose();
   return{image,guide,metadata:{schemaVersion:TEMPLATE_SCHEMA,templateId,cameraDirection:map.direction.toArray(),frame:{center:{x:0,z:0},viewHeight:definition.viewHeight,aspect:definition.aspect},polygon:definition.polygon,signature,
    sourceTownId:town.id,sourceBlockId:block.id,target:target.toArray(),width,height,anchors,placements:members.length}};
  },templateId);
  const folder=`${output}/${templateId}`;await mkdir(folder,{recursive:true});
  for(const [name,value]of[['guide',result.image],['registration',result.guide]])await writeFile(`${folder}/${name}.png`,Buffer.from(value.split(',')[1],'base64'));
  await writeFile(`${folder}/metadata.json`,JSON.stringify(result.metadata,null,2)+'\n');
  console.log(JSON.stringify({templateId,folder,placements:result.metadata.placements,anchors:result.metadata.anchors.map(a=>({slot:a.slot,id:a.id,stories:a.stories,roof:a.roof,solar:a.solar,pool:a.hasPool}))}));
 }
}finally{await browser.close();}
