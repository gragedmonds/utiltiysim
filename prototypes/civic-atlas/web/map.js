import * as THREE from '/viewer/vendor/three.module.js';
import {TownScene} from '/viewer/scene.js';
import {inspectSnapshot} from '/viewer/adapter.js';
import {buildingGeometry} from './map-buildings.js';
import {installIllustratedFoliage} from './map-foliage.js';
import {installMaterialAtlas} from './map-materials.js';
import {naturalizeLandscape,renderNaturalBanks} from './map-landscape.js';
import {installGrassPalette} from './map-grass.js';
import {renderParcelGardens} from './map-gardens.js';
import {createBuildingSprites} from './map-building-sprites.js';
import {replaceTreeAssets,replaceCivicAssets,addResidentialCharacter,groundTexture,renderParks,renderAtlasDesign,applyBuildingFamilies,renderTownCenter,renderWaterTowers} from './map-assets.js';
import {addStreetMarkings,softenTrees,makeStreetLabels,enrichNeighborhood,refineStreetSurfaces} from './map-art.js';

export class AtlasMap {
  constructor(element, town, {onSelect, onSketch, notify, initialView, art = new URLSearchParams(location.search).get('art') || 'native'}) {
    inspectSnapshot(town);
    this.el = element; this.town = town; this.initialView = initialView; this.art = art; this.onSelect = onSelect; this.onSketch = onSketch; this.notify = notify;
    this.inputMode = 'auto'; this.drawing = false; this.space = false; this.frontage = true;
    this.abort = new AbortController(); this.points = [];
    this.scene = new TownScene(element, result => { if (!this.drawing && result.home) onSelect(result.home); }, 'full', {renderOnDemand:true});
    const s = this.scene;
    s.play = false; s.load(town, {demo:false});
    // Fixed illustrated aerial: parallel projection keeps near and far houses
    // the same size. The retained distance is a logical zoom scale only.
    const oldCamera=s.camera;
    s.camera=new THREE.OrthographicCamera(-1,1,1,-1,.5,s.span*15);
    s.camera.position.copy(oldCamera.position);s.camera.quaternion.copy(oldCamera.quaternion);
    s.controls.object=s.camera;
    const resize=s.resize.bind(s);
    s.resize=()=>{resize();this.updateProjection();};
    s.controls.enableRotate = false;
    // Atlas owns pointer gestures, so sketching and navigation cannot compete.
    s.controls.enabled = false;
    s.controls.mouseButtons.RIGHT = null;
    s.controls.screenSpacePanning = false;
    s.controls.enableDamping = false;
    s.renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
    s.scene.background.set('#dce4d8');
    s.ambient.intensity = 1.40; s.sun.intensity = 2.75;
    s.ambient.color.set('#edf4fa');s.ambient.groundColor.set('#9da995');
    s.sun.position.y=s.center.y+s.span*.68;
    s.sun.color.set('#fff3dc');
    s.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    s.renderer.toneMappingExposure = .92;
    s.sun.shadow.normalBias = .35;
    s.sun.shadow.bias = -.00012;
    s.sun.shadow.mapSize.set(4096, 4096);
    s.renderer.shadowMap.autoUpdate=false;
    s.renderer.shadowMap.needsUpdate=true;
    this.direction = new THREE.Vector3(.16, 1.20, .82).normalize();
    this.plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -s.center.y);
    this.ray = new THREE.Raycaster();
    this.canvas = s.renderer.domElement;
    this.canvas.tabIndex = 0;
    this.canvas.setAttribute('aria-label', 'Brookfield map. Drag to pan; use arrow keys, plus and minus to navigate.');
    this.styleTown();
    this.setLayer('town');
    this.home(true);
    this.bind();
    try {
      const saved = JSON.parse(localStorage.getItem(this.storageKey()) || 'null');
      if (saved?.schemaVersion === 'civic-atlas-road-sketch/1' && saved.townId === town.id &&
          Array.isArray(saved.points) && saved.points.length <= 200 && saved.points.every(p => this.validPoint(p))) {
        this.points = saved.points; this.frontage = saved.residentialFrontage === true;
      }
    } catch { /* An unavailable or damaged browser draft never blocks the map. */ }
    this.redrawDraft();
  }
  storageKey() { return `civic-atlas:sketch:${this.town.id}`; }
  validPoint(p) { const b=this.town.bounds; return p && Number.isFinite(p.x) && Number.isFinite(p.z) && p.x>=b.minX && p.x<=b.maxX && p.z>=b.minZ && p.z<=b.maxZ; }
  styleTown() {
    const s=this.scene;
    // Presentation-only color treatment. Preserve every engine footprint and orientation.
    const roofs=['#465d68','#64746f','#91715f','#526c76'];
    s.roofBatches.forEach((mesh, family) => {
      mesh.material.color.set('#ffffff');
      for(let i=0;i<mesh.count;i++) {
        const old=new THREE.Color(); mesh.getColorAt(i,old);
        mesh.setColorAt(i,new THREE.Color(roofs[family]).multiplyScalar(.9+old.r*.25));
      }
      if(mesh.instanceColor)mesh.instanceColor.needsUpdate=true;
    });
    s.houseMeshes.walls.material.color.set('#fffdf3');
    // Soften the terrain; vertex variation adds texture without inventing geographic features.
    const ground=s.root.children.find(o=>o.isMesh && o.geometry?.type==='PlaneGeometry');
    if(ground) {
      const pos=ground.geometry.attributes.position, colors=[];
      for(let i=0;i<pos.count;i++) {
        const tone=Math.sin(pos.getX(i)*.018)*Math.cos(pos.getZ(i)*.021)*.022;
        const c=new THREE.Color('#9bb89b').multiplyScalar(1+tone); colors.push(c.r,c.g,c.b);
      }
      ground.geometry.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));
      ground.material.color.set('#ffffff'); ground.material.vertexColors=true;
    }
    // Architectural detail must be recalculated on a still frame after each camera change.
    s.onAnimation=()=>{
      const detail=s.houseDetails,key=detail?.lastKey;
      detail?.update(this.detailCamera(),this.el.clientHeight*1.8,performance.now(),true);
      if(detail?.lastKey!==key)s.renderer.shadowMap.needsUpdate=true;
      this.streetLabels?.update();this.neighborhoodArt?.update();this.residentialArt?.update();
    };
    // The shared viewer's non-indexed road ribbons have reversed winding. Correct it
    // locally so the visible surface receives daylight instead of underside lighting.
    for(const mesh of s.root.children){
      if(!mesh.isMesh||mesh.isInstancedMesh||mesh.geometry.type!=='BufferGeometry')continue;
      const color=mesh.material.color?.getHexString();
      if(!['9eaaa6','d8d8cd'].includes(color))continue;
      const pos=mesh.geometry.attributes.position;
      for(let i=0;i<pos.count;i+=3){
        const x=pos.getX(i+1),y=pos.getY(i+1),z=pos.getZ(i+1);
        pos.setXYZ(i+1,pos.getX(i+2),pos.getY(i+2),pos.getZ(i+2));pos.setXYZ(i+2,x,y,z);
      }
      pos.needsUpdate=true;mesh.geometry.computeVertexNormals();
      mesh.material.color.set(color==='9eaaa6'?'#89989a':'#e2e0d4');
      mesh.userData.atlasSurface=color==='9eaaa6'?1:2;
    }
    s.townDressing?.meshes.forEach(m=>{m.castShadow=true;});
    replaceTreeAssets(s);refineStreetSurfaces(s,this.town);addStreetMarkings(s,this.town);
    if(this.town.atlasDesign?.buildingFamilies)this.authoredAssets=applyBuildingFamilies(s,this.town,buildingGeometry);
    else {replaceCivicAssets(s,this.town);this.residentialArt=addResidentialCharacter(s,this.town);}
    this.groundMap=groundTexture(s,this.town);this.parkArt=renderParks(s,this.town);this.bankArt=renderNaturalBanks(s,this.town);renderAtlasDesign(s,this.town);
    renderTownCenter(s,this.town);
    renderWaterTowers(s,this.town);
    for(const utility of ['water','electric','gas']){
      const main=s.networkGroups[utility];main.material.opacity=.98;main.material.toneMapped=false;
      s.lineGroups[utility].material.toneMapped=false;
      s.serviceGroups[utility].material.opacity=.7;s.serviceGroups[utility].material.toneMapped=false;
      if(utility==='water'){main.material.color.set('#36bad7');s.lineGroups[utility].material.color.set('#36bad7');s.serviceGroups[utility].material.color.set('#61cadd');}
    }
    // Address labels belong to selection/search; avoid overlapping legacy shop chips.
    s.markers=s.markers.filter(marker=>{if(marker.landmark){marker.el.remove();return false;}return true;});
    this.streetLabels=makeStreetLabels(this.el,s,this.town);
    this.neighborhoodArt=enrichNeighborhood(s,this.town);
    this.gardenArt=renderParcelGardens(s,this.town);
    this.landscapeArt=naturalizeLandscape(s,this.town);
    this.el.dataset.foliage='loading';
    this.foliageReady=installIllustratedFoliage(s,{url:'./assets/civic-foliage-atlas.png',signal:this.abort.signal}).then(art=>{
      this.illustratedFoliage=art;if(art){this.el.dataset.foliage='ready';art.setSelected(this.selected);}return art;
    }).catch(error=>{
      this.el.dataset.foliage='fallback';console.warn('Illustrated foliage unavailable; using geometry.',error);
      return null;
    });
    this.el.dataset.materials='loading';
    this.materialReady=installMaterialAtlas(s,{url:'./assets/civic-material-atlas.png',signal:this.abort.signal}).then(art=>{
      this.materialArt=art;if(art)this.el.dataset.materials='ready';this.grassArt=installGrassPalette(s);return art;
    }).catch(error=>{
      this.grassArt=installGrassPalette(s);this.el.dataset.materials='fallback';console.warn('Illustrated materials unavailable; using procedural surfaces.',error);return null;
    });
    this.buildingSprites=createBuildingSprites(s,this.town,{url:'./assets/civic-houses-one-storey.png',calibrated:true});
    this.buildingReady=this.buildingSprites.ready.then(art=>{this.el.dataset.buildings=art?'ready':'fallback';this.request();return art;});
    this.twoStoreySprites=createBuildingSprites(s,this.town,{url:'./assets/civic-houses-two-storey.png',stories:2,calibrated:true});
    this.commercialSprites=createBuildingSprites(s,this.town,{url:'./assets/civic-commercial-atlas.png',kind:'commercial',calibrated:true});
    this.visualReady=Promise.all([this.foliageReady,this.materialReady,this.buildingReady,this.twoStoreySprites.ready,this.commercialSprites.ready]);
    if(this.art==='blocks'){
      const nativeReady=this.visualReady;
      this.el.dataset.blockArt='loading';this.el.dataset.blockCount='0';
      this.blockArtStats={ready:false,enabled:false,count:0,reason:'Experimental neighborhood illustrations are loading'};
      this.blockReady=nativeReady.then(()=>this.loadBlockArtwork());
      this.visualReady=Promise.all([nativeReady,this.blockReady]);
    }
    s.renderRequested=true;
  }
  async loadBlockArtwork(){
    try{
      const {createBlockPlate,BLOCK,SECOND_BLOCK,COMMERCIAL_BLOCK,PARK_BLOCK,SCHOOL_BLOCK,DEPOT_BLOCK}=await import('./map-block-plate.js');
      if(this.abort.signal.aborted)return null;
      this.blockPlates=[
        createBlockPlate(this,{block:BLOCK,metadataUrl:'./assets/civic-block-pine-willow.json',imageUrl:'./assets/civic-block-pine-willow.png',signal:this.abort.signal}),
        createBlockPlate(this,{block:SECOND_BLOCK,metadataUrl:'./assets/civic-block-oak-birch.json',imageUrl:'./assets/civic-block-oak-birch.png',manageOverlays:false,signal:this.abort.signal}),
        createBlockPlate(this,{block:COMMERCIAL_BLOCK,metadataUrl:'./assets/civic-block-main-north.json',imageUrl:'./assets/civic-block-main-north.png',manageOverlays:false,signal:this.abort.signal}),
        createBlockPlate(this,{block:PARK_BLOCK,metadataUrl:'./assets/civic-block-maple-park.json',imageUrl:'./assets/civic-block-maple-park.png',manageOverlays:false,signal:this.abort.signal}),
        createBlockPlate(this,{block:SCHOOL_BLOCK,metadataUrl:'./assets/civic-block-school.json',imageUrl:'./assets/civic-block-school.png',manageOverlays:false,signal:this.abort.signal}),
        createBlockPlate(this,{block:DEPOT_BLOCK,metadataUrl:'./assets/civic-block-depot.json',imageUrl:'./assets/civic-block-depot.png',manageOverlays:false,signal:this.abort.signal}),
      ];
      await Promise.all(this.blockPlates.map(plate=>plate.ready));
      if(this.abort.signal.aborted)return null;
      if(!this.blockPlates.every(plate=>plate.stats.ready))throw Error(this.blockPlates.find(plate=>!plate.stats.ready)?.stats.reason||'Block illustration is unavailable');
      if(!this.blockPlates.every(plate=>plate.setEnabled(true)))throw Error('Block illustration no longer matches the saved geography');
      Object.assign(this.blockArtStats,{ready:true,enabled:true,count:this.blockPlates.length,reason:'Experimental illustrations of saved blocks'});
      this.el.dataset.blockArt='ready';this.el.dataset.blockCount=String(this.blockPlates.length);this.refreshBlockOverlays();
      return this.blockArtStats;
    }catch(error){
      this.blockPlates?.forEach(plate=>plate.setEnabled(false));
      if(this.abort.signal.aborted)return null;
      Object.assign(this.blockArtStats,{ready:false,enabled:false,count:0,reason:error.message});
      this.el.dataset.blockArt='fallback';this.el.dataset.blockCount='0';this.request();
      return this.blockArtStats;
    }
  }
  setBlockArtwork(enabled){
    if(!this.blockArtStats?.ready)return false;
    const results=this.blockPlates.map(plate=>plate.setEnabled(enabled));
    const active=Boolean(enabled)&&results.every(Boolean);
    if(!active)this.blockPlates.forEach(plate=>plate.setEnabled(false));
    this.blockArtStats.enabled=active;
    this.el.dataset.blockArt=active?'ready':'native';
    this.el.dataset.blockCount=active?String(this.blockPlates.length):'0';
    this.request();return active;
  }
  refreshBlockOverlays(){this.blockPlates?.[0]?.liftOverlays();}
  worldAt(clientX,clientY) {
    const r=this.canvas.getBoundingClientRect();
    this.scene.camera.updateMatrixWorld();
    this.ray.setFromCamera(new THREE.Vector2((clientX-r.left)/r.width*2-1,-(clientY-r.top)/r.height*2+1),this.scene.camera);
    // Iterate against actual saved terrain rather than drawing on a flat plane at town center.
    const plane=this.plane.clone();
    let point=this.ray.ray.intersectPlane(plane,new THREE.Vector3());
    for(let i=0;point&&i<5;i++){plane.constant=-this.scene.heightAt(point.x,point.z);point=this.ray.ray.intersectPlane(plane,new THREE.Vector3());}
    return point;
  }
  request() { this.scene.renderRequested=true; }
  updateProjection(){
    const s=this.scene;if(!s?.camera.isOrthographicCamera)return;
    const height=s.camera.position.distanceTo(s.controls.target)*.65;
    const aspect=Math.max(1,this.el.clientWidth)/Math.max(1,this.el.clientHeight);
    s.camera.left=-height*aspect/2;s.camera.right=height*aspect/2;
    s.camera.top=height/2;s.camera.bottom=-height/2;s.camera.updateProjectionMatrix();
    this.updateUtilityWidths();
    this.updateParcelStroke();
    this.request();
  }
  updateUtilityWidths(force=false){
    const s=this.scene;if(!s?.camera.isOrthographicCamera)return;
    const metrePerPixel=(s.camera.top-s.camera.bottom)/Math.max(1,this.el.clientHeight),key=metrePerPixel.toFixed(6);
    if(!force&&key===this.utilityWidthKey)return;this.utilityWidthKey=key;
    const matrix=new THREE.Matrix4(),position=new THREE.Vector3(),rotation=new THREE.Quaternion(),scale=new THREE.Vector3();
    const resize=(mesh,pixels)=>{
      if(!mesh)return;const radius=metrePerPixel*pixels/2;
      for(let i=0;i<mesh.count;i++){mesh.getMatrixAt(i,matrix);matrix.decompose(position,rotation,scale);scale.x=scale.z=radius;matrix.compose(position,rotation,scale);mesh.setMatrixAt(i,matrix);}
      mesh.instanceMatrix.needsUpdate=true;mesh.computeBoundingSphere();
    };
    for(const utility of ['water','electric','gas']){resize(s.networkGroups[utility],2.4);resize(s.serviceGroups[utility],1.1);}
    resize(s.trace,4);
  }
  updateParcelStroke(){
    if(!this.parcelEdge||!this.parcelPolygon)return;
    const s=this.scene,vertices=[],radius=(s.camera.top-s.camera.bottom)/Math.max(1,this.el.clientHeight)*1.1,polygon=this.parcelPolygon;
    for(let i=0;i<polygon.length;i++){
      const a=polygon[i],b=polygon[(i+1)%polygon.length],dx=b.x-a.x,dz=b.z-a.z,length=Math.hypot(dx,dz);if(length<.01)continue;
      const nx=-dz/length*radius,nz=dx/length*radius;
      for(const [x,z]of[[a.x+nx,a.z+nz],[a.x-nx,a.z-nz],[b.x-nx,b.z-nz],[a.x+nx,a.z+nz],[b.x-nx,b.z-nz],[b.x+nx,b.z+nz]])vertices.push(x,s.heightAt(x,z)+1.0,z);
    }
    this.parcelEdge.geometry.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));this.parcelEdge.geometry.computeBoundingSphere();
  }
  detailCamera(){
    const s=this.scene,c=s.camera;if(!c.isOrthographicCamera)return c;
    // The shared detail selector expects a perspective factor / distance. Feed
    // its actual orthographic frustum plus a distant equivalent eye so that
    // selection follows pixels per world metre, independent of near/far depth.
    const distance=s.span*1000,viewHeight=(c.top-c.bottom)/c.zoom;
    c.updateMatrixWorld();
    return {projectionMatrix:c.projectionMatrix,matrixWorldInverse:c.matrixWorldInverse,
      position:s.controls.target.clone().addScaledVector(this.direction,distance),
      fov:2*Math.atan(viewHeight/(2*distance))*180/Math.PI,updateMatrixWorld:()=>c.updateMatrixWorld()};
  }
  home(neighborhood=false) {
    const s=this.scene,b=this.town.bounds,aspect=Math.max(1,this.el.clientWidth)/Math.max(1,this.el.clientHeight);
    const right=new THREE.Vector3(this.direction.z,0,-this.direction.x).normalize(),up=this.direction.clone().cross(right);
    const width=b.maxX-b.minX,depth=b.maxZ-b.minZ;
    const projectedWidth=Math.abs(right.x)*width+Math.abs(right.z)*depth;
    const projectedHeight=Math.abs(up.x)*width+Math.abs(up.z)*depth+40;
    const fitDistance=Math.max(projectedHeight,projectedWidth/aspect)*1.12/.65;
    const reference=this.town.atlasDesign;
    const distance=neighborhood?(reference?(this.initialView?.viewHeightM||reference.focus?.viewHeightM||reference.viewHeightM||440)/.65:s.span*.46):fitDistance;
    s.controls.target.copy(s.center);
    if(neighborhood&&this.parkArt.centers.length){
      const park=this.parkArt.centers[0],school=this.town.premises.find(p=>p.buildingType==='school');
      const x=school?(park.x+school.x)/2:park.x,z=school?(park.z+school.z)/2:park.z;
      s.controls.target.set(x,s.heightAt(x,z),z);
    }
    if(neighborhood&&reference){const focus=this.initialView||reference.focus||{x:75,z:-10};s.controls.target.set(focus.x,s.heightAt(focus.x,focus.z),focus.z);}
    s.camera.position.copy(s.controls.target).addScaledVector(this.direction,distance);
    s.controls.minDistance=65; s.controls.maxDistance=Math.max(s.span*3,fitDistance*1.1);
    s.controls.update(); this.updateProjection();this.request();
  }
  focus(home, close=false) {
    const s=this.scene;
    let distance=s.camera.position.distanceTo(s.controls.target);
    if(close){
      const polygon=this.town.parcels?.find(p=>p.premiseId===home.id)?.polygon;
      const width=polygon?Math.max(...polygon.map(p=>p.x))-Math.min(...polygon.map(p=>p.x)):home.width||20;
      const depth=polygon?Math.max(...polygon.map(p=>p.z))-Math.min(...polygon.map(p=>p.z)):home.depth||20;
      const right=new THREE.Vector3(this.direction.z,0,-this.direction.x).normalize(),up=this.direction.clone().cross(right);
      const projectedWidth=Math.abs(right.x)*width+Math.abs(right.z)*depth;
      const projectedHeight=Math.abs(up.x)*width+Math.abs(up.z)*depth+(home.height||8);
      const aspect=Math.max(.4,this.el.clientWidth/Math.max(1,this.el.clientHeight));
      // Inspect the actual property with enough surrounding street context to
      // stay oriented; a school and a cottage should not share a fixed zoom.
      const viewHeight=Math.max(96,projectedHeight*1.8,projectedWidth/aspect*1.8);
      distance=THREE.MathUtils.clamp(viewHeight/.65,s.controls.minDistance,s.controls.maxDistance);
    }
    s.controls.target.set(home.x,s.heightAt(home.x,home.z),home.z);
    s.camera.position.copy(s.controls.target).addScaledVector(this.direction,distance);
    s.controls.update();this.updateProjection();this.request();
  }
  zoom(factor,clientX,clientY) {
    const s=this.scene,r=this.canvas.getBoundingClientRect();
    clientX??=r.left+r.width/2; clientY??=r.top+r.height/2;
    const before=this.worldAt(clientX,clientY);
    const distance=THREE.MathUtils.clamp(s.camera.position.distanceTo(s.controls.target)*factor,s.controls.minDistance,s.controls.maxDistance);
    s.camera.position.copy(s.controls.target).addScaledVector(this.direction,distance);
    s.controls.update();this.updateProjection();
    const after=this.worldAt(clientX,clientY);
    if(before&&after) { const shift=before.sub(after);s.camera.position.add(shift);s.controls.target.add(shift); }
    this.clampPan();this.request();
  }
  pan(dx,dy) {
    const r=this.canvas.getBoundingClientRect(), a=this.worldAt(r.left+r.width/2,r.top+r.height/2),b=this.worldAt(r.left+r.width/2+dx,r.top+r.height/2+dy);
    if(a&&b) {const shift=a.sub(b);this.scene.camera.position.add(shift);this.scene.controls.target.add(shift);this.clampPan();this.request();}
  }
  clampPan() {
    const s=this.scene,b=this.town.bounds,t=s.controls.target,old=t.clone();
    t.x=THREE.MathUtils.clamp(t.x,b.minX-s.span*.2,b.maxX+s.span*.2);
    t.z=THREE.MathUtils.clamp(t.z,b.minZ-s.span*.2,b.maxZ+s.span*.2);
    s.camera.position.add(t.clone().sub(old));s.controls.update();
  }
  bind() {
    const signal=this.abort.signal,c=this.canvas;
    c.addEventListener('wheel',e=>{
      e.preventDefault();e.stopImmediatePropagation();
      const trackpad=this.inputMode==='trackpad'||(this.inputMode==='auto'&&e.deltaMode===0&&(Math.abs(e.deltaX)>.1||Math.abs(e.deltaY)<45));
      const units=e.deltaMode===1?16:e.deltaMode===2?c.clientHeight:1;
      if(e.ctrlKey || !trackpad) this.zoom(Math.exp(THREE.MathUtils.clamp(e.deltaY*units,-120,120)*.002),e.clientX,e.clientY);
      else this.pan(-e.deltaX*units,-e.deltaY*units);
    },{capture:true,passive:false,signal});
    c.addEventListener('contextmenu',e=>e.preventDefault(),{signal});
    c.addEventListener('pointerdown',e=>{
      if(e.button!==0&&e.button!==1)return;
      e.preventDefault();e.stopImmediatePropagation();c.focus({preventScroll:true});
      if(this.gesture)return;
      this.gesture={id:e.pointerId,x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY,
        pan:!this.drawing||this.space||e.button===1,moved:false};
      c.setPointerCapture(e.pointerId);c.style.cursor=this.gesture.pan?'grabbing':'crosshair';
    },{capture:true,signal});
    c.addEventListener('pointermove',e=>{
      const g=this.gesture;
      if(g&&g.id===e.pointerId){
        e.preventDefault();e.stopImmediatePropagation();
        const distance=Math.hypot(e.clientX-g.startX,e.clientY-g.startY);
        if(distance>5)g.moved=true;
        if(g.pan&&g.moved)this.pan(e.clientX-g.x,e.clientY-g.y);
        g.x=e.clientX;g.y=e.clientY;
      }
      if(this.drawing&&!g){
        const point=this.worldAt(e.clientX,e.clientY);
        this.hoverPoint=point&&this.snap(point);this.redrawDraft();
      }
    },{capture:true,signal});
    c.addEventListener('pointerup',e=>{
      e.preventDefault();e.stopImmediatePropagation();
      const g=this.gesture;if(!g||g.id!==e.pointerId)return;
      this.gesture=null;if(c.hasPointerCapture(e.pointerId))c.releasePointerCapture(e.pointerId);
      c.style.cursor=this.drawing&&!this.space?'crosshair':'grab';
      if(g.moved)return;
      if(this.drawing&&!g.pan)this.addPoint(e.clientX,e.clientY);
      else if(!this.drawing&&e.button===0)this.scene.pick(e);
    },{capture:true,signal});
    c.addEventListener('click',e=>e.stopImmediatePropagation(),{capture:true,signal});
    c.addEventListener('pointercancel',()=>{this.gesture=null;this.hoverPoint=null;this.redrawDraft();},{capture:true,signal});
    c.addEventListener('pointerleave',()=>{this.hoverPoint=null;if(this.drawing)this.redrawDraft();},{signal});
    c.addEventListener('keydown',e=>{
      if(e.ctrlKey||e.metaKey||e.altKey)return;
      if(e.code==='Space'){this.space=true;e.preventDefault();c.style.cursor='grab';return;}
      if(e.key==='+'||e.key==='=')this.zoom(.8);
      else if(e.key==='-')this.zoom(1.25);
      else if(e.key.startsWith('Arrow'))this.pan(e.key==='ArrowLeft'?65:e.key==='ArrowRight'?-65:0,e.key==='ArrowUp'?65:e.key==='ArrowDown'?-65:0);
      else if(e.key==='Enter'){
        const t=this.scene.controls.target;
        const home=[...this.town.premises].sort((a,b)=>Math.hypot(a.x-t.x,a.z-t.z)-Math.hypot(b.x-t.x,b.z-t.z))[0];
        this.onSelect(home);
      }else if(e.key==='Escape')this.setDrawing(false);
      else return;
      e.preventDefault();
    },{signal});
    const release=()=>{this.space=false;c.style.cursor=this.drawing?'crosshair':'grab';};
    c.addEventListener('keyup',e=>{if(e.code==='Space')release();},{signal});
    c.addEventListener('blur',()=>{release();this.gesture=null;},{signal});
    c.style.cursor='grab';
  }
  addPoint(x,y) {
    if(this.points.length>=200){this.notify('This sketch supports up to 200 points.');return;}
    let p=this.worldAt(x,y);if(!p)return;p=this.snap(p);
    if(!this.validPoint(p)){this.notify('Keep the road sketch inside this world.');return;}
    if(this.points.length&&Math.hypot(p.x-this.points.at(-1).x,p.z-this.points.at(-1).z)<5)return;
    this.points.push({x:Math.round(p.x*100)/100,z:Math.round(p.z*100)/100});
    this.hoverPoint=null;this.updateDraft();
  }
  snap(p) {
    let best=p,dist=14;
    for(const road of this.town.roads)for(let i=1;i<road.points.length;i++){
      const a=road.points[i-1],b=road.points[i],dx=b.x-a.x,dz=b.z-a.z;
      const t=THREE.MathUtils.clamp(((p.x-a.x)*dx+(p.z-a.z)*dz)/(dx*dx+dz*dz||1),0,1);
      const candidate={x:a.x+t*dx,z:a.z+t*dz},d=Math.hypot(candidate.x-p.x,candidate.z-p.z);
      if(d<dist){dist=d;best=candidate;}
    }
    for(const q of this.points){const d=Math.hypot(q.x-p.x,q.z-p.z);if(d<dist){dist=d;best=q;}}
    return best;
  }
  select(home) {
    this.clearParcelHighlight();this.selected=home;
    this.illustratedFoliage?.setSelected(home);
    const s=this.scene;s.select(home,this.layer==='town'?'water':this.layer,false);
    this.updateUtilityWidths(true);
    if(s.trace){s.trace.material.toneMapped=false;if(this.layer==='water'||this.layer==='town')s.trace.material.color.set('#58dbea');}
    const polygon=this.town.parcels?.find(p=>p.premiseId===home.id)?.polygon;
    if(polygon?.length>2){
      s.selection.visible=false;
      const color={town:'#00b8cd',water:'#00b8dd',electric:'#e4a727',gas:'#b077d0'}[this.layer];
      const vertices=[],triangles=THREE.ShapeUtils.triangulateShape(polygon.map(p=>new THREE.Vector2(p.x,p.z)),[]);
      for(const triangle of triangles)for(const index of triangle){const p=polygon[index];vertices.push(p.x,s.heightAt(p.x,p.z)+.35,p.z);}
      this.parcelHighlight=new THREE.Group();s.root.add(this.parcelHighlight);
      const fillGeo=new THREE.BufferGeometry();fillGeo.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));
      const fill=new THREE.Mesh(fillGeo,new THREE.MeshBasicMaterial({color,transparent:true,opacity:.13,depthWrite:false,side:THREE.DoubleSide}));fill.renderOrder=4;this.parcelHighlight.add(fill);
      const edgeVertices=[];
      for(let i=0;i<polygon.length;i++){
        const a=polygon[i],b=polygon[(i+1)%polygon.length],dx=b.x-a.x,dz=b.z-a.z,length=Math.hypot(dx,dz);if(length<.01)continue;
        const nx=-dz/length*.27,nz=dx/length*.27;
        for(const [x,z]of [[a.x+nx,a.z+nz],[a.x-nx,a.z-nz],[b.x-nx,b.z-nz],[a.x+nx,a.z+nz],[b.x-nx,b.z-nz],[b.x+nx,b.z+nz]])edgeVertices.push(x,s.heightAt(x,z)+.5,z);
      }
      const edgeGeo=new THREE.BufferGeometry();edgeGeo.setAttribute('position',new THREE.Float32BufferAttribute(edgeVertices,3));
      const edge=new THREE.Mesh(edgeGeo,new THREE.MeshBasicMaterial({color,side:THREE.DoubleSide,depthTest:true,toneMapped:false}));edge.renderOrder=6;this.parcelHighlight.add(edge);this.parcelEdge=edge;this.parcelPolygon=polygon;this.updateParcelStroke();
    }
    this.refreshBlockOverlays();this.request();
  }
  clearParcelHighlight(){if(this.parcelHighlight){this.scene.root.remove(this.parcelHighlight);this.parcelHighlight.traverse(o=>{o.geometry?.dispose();o.material?.dispose();});this.parcelHighlight=null;}this.parcelEdge=null;this.parcelPolygon=null;}
  clearSelection() {this.selected=null;this.illustratedFoliage?.setSelected(null);this.clearParcelHighlight();this.scene.clearSelection();this.refreshBlockOverlays();}
  setLayer(layer) {
    this.layer=layer;
    this.scene.setLayers({water:layer==='water',electric:layer==='electric',gas:layer==='gas'});
    if(this.selected)this.select(this.selected);
    this.refreshBlockOverlays();
  }
  setDrawing(value) {
    this.drawing=value;this.hoverPoint=null;this.gesture=null;this.canvas.style.cursor=value?'crosshair':'grab';this.el.classList.toggle('sketching',value);this.redrawDraft();
    this.onSketch?.(this.draft(),value);
  }
  draft() {return {schemaVersion:'civic-atlas-road-sketch/1',townId:this.town.id,coordinateSystem:this.town.source.coordinateSystem,points:this.points,residentialFrontage:this.frontage,committed:false};}
  updateDraft() {
    try{localStorage.setItem(this.storageKey(),JSON.stringify(this.draft()));}catch{this.notify('Browser storage is unavailable. Export the draft to keep it.');}
    this.redrawDraft();this.onSketch?.(this.draft(),this.drawing);
  }
  redrawDraft() {
    const s=this.scene;
    if(this.draftGroup){s.root.remove(this.draftGroup);this.draftGroup.traverse(o=>{o.geometry?.dispose();o.material?.dispose();});}
    this.draftGroup=new THREE.Group();s.root.add(this.draftGroup);
    if(!this.drawing){this.request();return;}
    const preview=this.hoverPoint&&this.validPoint(this.hoverPoint)?this.hoverPoint:null;
    const raw=[...this.points,...(preview?[preview]:[])];
    const pts=raw.map(p=>new THREE.Vector3(p.x,s.heightAt(p.x,p.z)+1,p.z));
    if(pts.length>1){
      // The block illustrations also use the transparent pass. Draft line and
      // point markers must join that pass for their higher renderOrder to work.
      const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),new THREE.LineDashedMaterial({color:'#af6c29',dashSize:6,gapSize:3,transparent:true,opacity:1,depthTest:false,depthWrite:false}));
      line.computeLineDistances();line.renderOrder=30;this.draftGroup.add(line);
      // Sketch ribbons follow terrain. Frontage is a suggestion, not generated parcels.
      for(let i=1;i<pts.length;i++){
        this.draftRibbon(pts[i-1],pts[i],8,'#bd8b52',.45);
        if(this.frontage)this.draftRibbon(pts[i-1],pts[i],42,'#80a16f',.20);
      }
    }
    for(let i=0;i<pts.length;i++){
      const marker=new THREE.Mesh(new THREE.SphereGeometry(i===pts.length-1&&preview?1.8:2.3,10,6),new THREE.MeshBasicMaterial({color:preview&&i===pts.length-1?'#fff6d9':'#af6c29',transparent:true,opacity:1,depthTest:false,depthWrite:false}));
      marker.position.copy(pts[i]);marker.renderOrder=31;this.draftGroup.add(marker);
    }
    this.request();
  }
  draftRibbon(a,b,width,color,opacity){
    const s=this.scene,dx=b.x-a.x,dz=b.z-a.z,len=Math.hypot(dx,dz);if(len<.01)return;
    const nx=-dz/len*width/2,nz=dx/len*width/2,vertices=[];
    const steps=Math.max(1,Math.ceil(len/12));
    for(let i=0;i<steps;i++){
      const p={x:a.x+dx*i/steps,z:a.z+dz*i/steps},q={x:a.x+dx*(i+1)/steps,z:a.z+dz*(i+1)/steps};
      for(const [x,z]of [[p.x+nx,p.z+nz],[p.x-nx,p.z-nz],[q.x-nx,q.z-nz],[p.x+nx,p.z+nz],[q.x-nx,q.z-nz],[q.x+nx,q.z+nz]])vertices.push(x,s.heightAt(x,z)+.8,z);
    }
    const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));
    const mesh=new THREE.Mesh(geo,new THREE.MeshBasicMaterial({color,transparent:true,opacity,side:THREE.DoubleSide,depthWrite:false}));
    mesh.renderOrder=20;this.draftGroup.add(mesh);
  }
  capture() {const s=this.scene;s.renderer.render(s.scene,s.camera);return this.canvas.toDataURL('image/png');}
  setVisible(value) {this.scene.suspended=!value;if(value){this.scene.resize();this.request();}}
  destroy(){this.abort.abort();this.blockPlates?.forEach(plate=>plate.destroy());this.streetLabels?.destroy();this.neighborhoodArt?.destroy();this.gardenArt?.destroy();this.illustratedFoliage?.destroy();this.materialArt?.destroy();this.buildingSprites?.destroy();this.twoStoreySprites?.destroy();this.commercialSprites?.destroy();this.authoredAssets?.destroy();this.bankArt?.destroy();this.landscapeArt?.destroy();this.groundMap?.dispose();this.scene.destroy();}
}
