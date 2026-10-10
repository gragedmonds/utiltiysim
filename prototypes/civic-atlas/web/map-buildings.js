import * as THREE from '/viewer/vendor/three.module.js';
import {GeometryBuilder, roofGeometry, hash} from '/viewer/lowpoly.js';

/**
 * Original Civic Atlas architectural assets. All geometry is in actual meters,
 * centered on the recorded footprint, ground at y=0, frontage towards local +Z.
 * home.height is the eaves/wall height (matching the shared viewer convention).
 * Roofs, cornices and steeples extend above it; minor eaves extend beyond footprint.
 * Assets are visual representations, never additional building or utility records.
 * Use MeshStandardMaterial({vertexColors:true, roughness:.9}) and rotate/translate
 * to the recorded home orientation. The caller owns disposal and picking metadata.
 */
export const BUILDING_FAMILIES = Object.freeze(['cottage','craftsman','townhouse','apartment','brick_shop','restaurant','school','church','utility_depot','pump_house']);

const aliases={bungalow:'craftsman',rowhouse:'townhouse',rowhouses:'townhouse',apartments:'apartment',shop:'brick_shop',shops:'brick_shop',commercial:'brick_shop',cafe:'restaurant',depot:'utility_depot',industrial:'utility_depot'};
const palettes=[
  {wall:'#e3ddcb',trim:'#f4efdf',roof:'#576675',accent:'#688271'},
  {wall:'#cbd9cf',trim:'#f3eedf',roof:'#536a72',accent:'#506c67'},
  {wall:'#dec9b3',trim:'#f7edda',roof:'#776b60',accent:'#687b83'},
  {wall:'#d8dfda',trim:'#f8f0dd',roof:'#667b7c',accent:'#8b6556'},
  {wall:'#cdd9df',trim:'#f7f0df',roof:'#586b7c',accent:'#6d8168'}
];
const BRICK=['#b77e63','#a96c55','#bc927b','#bd9a7c'];
const glass='#587b84',glassLight='#8ba6a8',foundation='#a49f8f',stone='#e0d3b9',shadow='#344b50';

export function buildingGeometry(family,home={}){
  family=aliases[family]||family;
  if(!BUILDING_FAMILIES.includes(family))family='cottage';
  const seed=hash(String(home.id||family)),p=palettes[seed%palettes.length];
  const w=Math.max(3,Number(home.width)||11),d=Math.max(3,Number(home.depth)||12),h=Math.max(2.8,Number(home.height)||5);
  const stories=Math.max(1,Math.min(6,Number(home.stories)||Number(home.storeys)||1)),b=new GeometryBuilder();
  const box=(color,x,y,z,sx,sy,sz)=>b.box(color,x,y,z,Math.max(.025,sx),Math.max(.025,sy),Math.max(.025,sz));
  const roof=(x,y,z,rw,rd,rh,color=p.roof,hip=false)=>{const g=roofGeometry(hip?1:0);b.add(g,color,x,y,z,rw,rh,rd);g.dispose();};
  const gable=(x,y,z,rw,rh,color=p.wall)=>{
    const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute([x-rw/2,y,z,x+rw/2,y,z,x,y+rh,z],3));g.computeVertexNormals();b.add(g,color);g.dispose();
  };
  const slope=(color,x,y,z,sx,sy,sz,rx)=>{const g=new THREE.BoxGeometry(1,1,1);b.add(g,color,x,y,z,sx,sy,sz,rx);g.dispose();};
  function window(x,y,z,ww=1.1,hh=1.5,side=0,shutters=false){
    // side=0 front/back; side=+/-1 x-facing walls. Tiny solid panes are pickable
    // with the body, avoiding transparent-surface sorting at overview scale.
    const frame=(color,dx,dy,dz,fw,fh,fd)=>side===2?box(color,x+dx,y+dy,z-dz,fw,fh,fd):side?box(color,x+dz*side,y+dy,z+dx,fd,fh,fw):box(color,x+dx,y+dy,z+dz,fw,fh,fd);
    frame(p.trim,0,0,0,ww+.22,hh+.22,.13);
    frame(glass,0,0,.09,ww,hh,.07);
    frame(glassLight,-ww*.22,hh*.13,.135,ww*.32,hh*.60,.025);
    frame(p.trim,0,0,.16,.075,hh,.045);
    frame(p.trim,0,0,.16,ww,.065,.045);
    frame(stone,0,-hh/2-.12,.10,ww+.36,.14,.28);
    if(shutters)for(const sign of [-1,1])frame(p.accent,sign*(ww/2+.25),0,.015,.29,hh+.06,.13);
  }
  function door(x,y,z,dw=1.1,dh=2.15,color=p.accent){
    box(p.trim,x,y+dh/2+.08,z,dw+.25,dh+.16,.16);box(color,x,y+dh/2,z+.10,dw,dh,.10);
    box(glass,x,y+dh*.73,z+.17,dw*.57,dh*.28,.035);box('#d6b979',x+dw*.33,y+dh*.44,z+.20,.08,.08,.05);
  }
  function courses(x,y,z,cw,ch,cd,color=p.wall){
    box(color,x,y+ch/2,z,cw,ch,cd);
    box(foundation,x,y+.20,z,cw+.09,.4,cd+.09);
    box(p.trim,x,y+ch-.08,z,cw+.19,.18,cd+.19);
  }
  function sideWindows(x,depth,height,count=3,side=1){
    for(let floor=0;floor<stories;floor++)for(let j=0;j<count;j++)window(x,(floor+.55)*height/stories,(-.5+(j+.5)/count)*depth,.85,Math.min(1.4,height/stories*.48),side);
  }
  function steps(x,z,width=2,level=.54){for(let i=0;i<3;i++)box(stone,x,level*(3-i)/6,z+i*.35,width,level*(3-i)/3,.40);}
  function chimney(x,z,y,scale=1){box('#ab7964',x,y+.8*scale,z,.65*scale,1.6*scale,.8*scale);box(stone,x,y+1.62*scale,z,.85*scale,.15*scale,1*scale);box(shadow,x,y+1.71*scale,z,.49*scale,.03,.61*scale);}
  function dormer(x,y,z,ww=1.8){box(p.wall,x,y+.57,z,ww,1.15,1.35);roof(x,y+1.15,z,ww+.27,1.65,.70);gable(x,y+1.15,z+.69,ww,.63);window(x,y+.56,z+.70,ww*.58,.72);}
  function flatRoof(x,y,z,rw,rd){
    box('#7b8987',x,y+.10,z,rw,.20,rd);
    for(const sign of [-1,1]){box(p.wall,x+sign*(rw/2-.12),y+.43,z,.24,.7,rd);box(stone,x+sign*(rw/2-.12),y+.80,z,.35,.12,rd+.13);box(p.wall,x,y+.43,z+sign*(rd/2-.12),rw,.7,.24);box(stone,x,y+.80,z+sign*(rd/2-.12),rw+.13,.12,.35);}
  }
  function hvac(x,y,z,scale=1){box('#b6bcb5',x,y+.38*scale,z,1.4*scale,.75*scale,1.8*scale);box('#677d7a',x,y+.78*scale,z,1.05*scale,.07,1.4*scale);for(let i=0;i<4;i++)box('#d3d5c9',x,y+.83*scale,z+(.35-i*.24)*scale,1.05*scale,.025,.035);}

  if(family==='cottage'||family==='craftsman'){
    const craft=family==='craftsman',variant=seed%5,bodyD=d*.76,bodyZ=-d*.12,bodyH=h;
    const suppliedRoof=String(home.roof||'').toLowerCase(),flat=suppliedRoof.includes('flat'),hip=suppliedRoof.includes('hip')||(!suppliedRoof&&craft);
    const longRidge=w>bodyD*1.16&&variant!==2,roofH=Math.min(2.25,(longRidge?bodyD:w)*.28);
    const roofColor=['#62727e','#657b76','#897967','#68767b','#77847e'][variant];
    courses(0,0,bodyZ,w,bodyH,bodyD);
    // Solid contrasting fascia, hips and bargeboards are the architectural
    // drawing at town zoom; texture grain is secondary. Local beam geometry
    // follows roof planes, so decoration cannot float above the building.
    function beam(color,a,c,width=.12){
      const v=new THREE.Vector3(...c).sub(new THREE.Vector3(...a)),g=new THREE.BoxGeometry(width,v.length(),width);
      g.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,1,0),v.clone().normalize()));
      g.translate((a[0]+c[0])/2,(a[1]+c[1])/2,(a[2]+c[2])/2);b.add(g,color);g.dispose();
    }
    function dressedRoof(x,y,z,rw,rd,rh,isHip=hip,across=false){
      const localW=across?rd:rw,localD=across?rw:rd;
      const g=roofGeometry(isHip?1:0);b.add(g,roofColor,x,y,z,localW,rh,localD,0,across?Math.PI/2:0);g.dispose();
      const point=(lx,ly,lz)=>across?[x+lz,y+ly,z-lx]:[x+lx,y+ly,z+lz];
      const ridgeEnd=isHip?localD*.23:localD*.5;
      beam('#9caaa2',point(0,rh,-ridgeEnd),point(0,rh,ridgeEnd),.13);
      for(const sign of [-1,1]){
        beam(p.trim,point(sign*localW/2,-.045,-localD/2),point(sign*localW/2,-.045,localD/2),.19);
        if(isHip){for(const edge of [-1,1])beam('#879990',point(sign*localW/2,.015,edge*localD/2),point(0,rh,edge*ridgeEnd),.10);}
        else {
          for(const edge of [-1,1])beam(p.trim,point(sign*localW/2,0,edge*localD/2),point(0,rh,edge*localD/2),.17);
          const end=new THREE.BufferGeometry();const vertices=[point(-localW/2,-.01,sign*(localD/2-.025)),point(localW/2,-.01,sign*(localD/2-.025)),point(0,rh-.09,sign*(localD/2-.025))];end.setAttribute('position',new THREE.Float32BufferAttribute(vertices.flat(),3));end.computeVertexNormals();b.add(end,p.wall);end.dispose();
        }
      }
      // A few subtle courses articulate the wide uninterrupted planes; they
      // are geometry-level roof seams, not additional operational equipment.
      if(!isHip)for(const sign of [-1,1])for(let row=1;row<4;row++){
        const t=row/4;beam('#7c8b87',point(sign*localW/2*(1-t),rh*t+.012,-localD/2+.08),point(sign*localW/2*(1-t),rh*t+.012,localD/2-.08),.032);
      }
    }
    if(flat)flatRoof(0,bodyH,bodyZ,w+.15,bodyD+.15);else dressedRoof(0,bodyH,bodyZ,w+.50,bodyD+.50,roofH,hip,longRidge);
    const frontZ=bodyZ+bodyD/2,porchD=d*.24,porchZ=d/2-porchD/2;
    const bay=variant===1||variant===3,bayW=w*.28,bayX=variant===1?w*.36:-w*.36;
    const porchW=w*(bay?.57:craft?.89:variant===4?.82:.58),porchX=bay?-Math.sign(bayX)*w*.15:0,porchH=Math.min(2.8,h/stories*.79);
    if(bay){
      const bayH=stories>1?h/stories:h*.94;
      courses(bayX,0,porchZ,bayW,bayH,porchD,p.wall);
      if(flat)flatRoof(bayX,bayH,porchZ,bayW,porchD);else dressedRoof(bayX,bayH,porchZ,bayW+.30,porchD+.32,Math.min(1.1,bayW*.27),hip);
      window(bayX,bayH*.52,d/2+.035,Math.min(1.75,bayW*.58),Math.min(1.6,bayH*.46),0,true);
    }
    box(stone,porchX,.22,porchZ,porchW,.44,porchD);
    const frontPosts=craft||variant===4?3:2;
    for(let i=0;i<frontPosts;i++){
      const px=porchX+(-.5+i/(frontPosts-1))*(porchW-.38);
      box('#c6bba2',px,.58,porchZ+porchD/2-.20,.48,.74,.48);
      box(p.trim,px,(porchH+.75)/2,porchZ+porchD/2-.20,.29,porchH-.75,.29);
      box(p.trim,px,porchH-.20,porchZ+porchD/2-.20,.48,.14,.48);
    }
    box(p.trim,porchX,porchH-.08,porchZ+porchD/2-.15,porchW+.10,.28,.25);
    if(flat||variant===0||variant===4){slope(roofColor,porchX,porchH+.18,porchZ,porchW+.38,.17,porchD+.38,.17);box(p.trim,porchX,porchH-.02,d/2+.17,porchW+.38,.16,.15);}
    else dressedRoof(porchX,porchH,porchZ,porchW+.38,porchD+.38,Math.min(1.18,porchW*.18),hip);
    // Railings stop either side of the entrance, leaving a real clear approach.
    const entrance=porchX+(frontPosts===3?porchW*.21:0);
    for(const sign of [-1,1]){
      const start=sign<0?porchX-porchW/2+.15:entrance+.65,end=sign<0?entrance-.65:porchX+porchW/2-.15;
      if(end-start>.35){box(p.trim,(start+end)/2,1.10,d/2-.20,end-start,.09,.09);for(let x=start;x<end;x+=.45)box(p.trim,x,.78,d/2-.20,.055,.62,.055);}
    }
    door(entrance,.42,frontZ+.035,1.15,Math.min(2.2,h/stories*.68));steps(entrance,d/2+.10,Math.min(2.3,porchW*.40),.45);
    const frontY=Math.min(h*.48,h/stories*.57);
    for(const x of [-w*.30,w*.30])if(!bay||Math.sign(x)!==Math.sign(bayX))window(x,frontY,frontZ+.04,Math.min(1.5,w*.16),Math.min(1.65,h/stories*.47),0,true);
    for(let floor=1;floor<stories;floor++)for(const x of [-w*.28,w*.28])window(x,(floor+.52)*h/stories,frontZ+.04,Math.min(1.45,w*.16),Math.min(1.5,h/stories*.46),0,true);
    // Rear and side elevations are equally complete because the fixed camera
    // sees both street orientations. No blank facades on north-facing plots.
    sideWindows(-w/2-.03,bodyD*.73,bodyH,Math.max(2,Math.round(d/4.5)),-1);sideWindows(w/2+.03,bodyD*.73,bodyH,Math.max(2,Math.round(d/4.5)),1);
    for(let floor=0;floor<stories;floor++)for(const x of [-w*.29,w*.29])window(x,(floor+.55)*h/stories,bodyZ-bodyD/2-.035,Math.min(1.5,w*.17),Math.min(1.6,h/stories*.46),2,variant%2===0);
    for(const sign of [-1,1]){box(p.trim,sign*(w/2-.08),h/2,frontZ+.015,.17,h,.14);box(p.trim,sign*(w/2-.08),h/2,bodyZ-bodyD/2-.015,.17,h,.14);}
    if(!flat&&longRidge&&(variant===0||variant===2||variant===4)){
      // A dormer stays within the documented decorative roof allowance and
      // uses the same roof family; it does not add a modelled storey.
      const dw=Math.min(3.0,w*.27),dy=h+roofH*.28,dz=bodyZ+bodyD*.19;
      box(p.wall,0,dy+.48,dz,dw,.96,Math.min(1.8,bodyD*.30));
      dressedRoof(0,dy+.96,dz,dw+.26,Math.min(1.8,bodyD*.30)+.25,.65,hip);
      window(0,dy+.47,dz+Math.min(1.8,bodyD*.30)/2+.03,dw*.62,.69);
    }
    chimney(-w*.27,bodyZ-bodyD*.20,bodyH+roofH*.32,.74);
    // Broad plinth and restrained siding courses establish material scale.
    for(let y=.9;y<bodyH-.4;y+=.62)for(const sign of [-1,1])box('#c8c9bb',sign*(w/2+.012),y,bodyZ,.028,.025,bodyD);
  } else if(family==='townhouse'){
    const units=Math.max(2,Math.min(5,Math.round(w/5.1))),uw=w/units;
    for(let i=0;i<units;i++){
      const x=-w/2+uw*(i+.5),color=[BRICK[0],'#d8c7a7','#c7d4ce',BRICK[2]][(i+seed)%4];
      courses(x,0,0,uw-.04,h,d*.9,color);flatRoof(x,h,0,uw-.03,d*.9);
      box(p.trim,x,h-.32,d*.455,uw,.30,.34);
      for(let floor=0;floor<stories;floor++)for(const sx of [-1,1]){if(floor===0&&sx===-1)continue;window(x+sx*uw*.23,(floor+.57)*h/stories,d*.455,.90,Math.min(1.5,h/stories*.46));}
      door(x-uw*.23,.42,d*.455,Math.min(1.0,uw*.24),Math.min(2.2,h/stories*.8),['#466a64','#536c83','#805e4b'][i%3]);
      steps(x-uw*.23,d*.47,uw*.42,.46);hvac(x,h+.22,-d*.20,.7);
      for(const sign of [-1,1])box(stone,x+sign*(uw/2-.13),h/2,d*.452,.19,h,.16);
    }
    sideWindows(-w/2-.03,d*.74,h,3,-1);sideWindows(w/2+.03,d*.74,h,3,1);
  } else if(family==='apartment'){
    courses(0,0,0,w,h,d,'#d3c2a6');flatRoof(0,h,0,w,d);
    const columns=Math.max(3,Math.min(7,Math.round(w/3.6)));
    for(let floor=0;floor<stories;floor++){
      const fy=(floor+.55)*h/stories;box(stone,0,(floor+1)*h/stories-.15,d/2+.08,w+.15,.22,.25);
      for(let i=0;i<columns;i++){
        const x=(-.5+(i+.5)/columns)*w;if(floor===0&&i===Math.floor(columns/2))continue;
        window(x,fy,d/2+.025,Math.min(1.5,w/columns*.55),Math.min(1.6,h/stories*.50));
        if(floor>0&&i%2===0){const bw=w/columns*.83,y=floor*h/stories+.12;box(stone,x,y,d/2+.46,bw,.17,.94);box('#6d8079',x,y+.80,d/2+.87,bw,.10,.09);for(let j=0;j<5;j++)box('#6d8079',x+(-.5+j/4)*bw,y+.43,d/2+.87,.045,.8,.045);}
      }
    }
    door(0,0,d/2+.04,1.8,2.5);box(p.accent,0,2.85,d/2+.6,3.5,.2,1.4);
    sideWindows(-w/2-.03,d*.85,h,Math.max(3,Math.round(d/3.5)),-1);sideWindows(w/2+.03,d*.85,h,Math.max(3,Math.round(d/3.5)),1);
    hvac(-w*.25,h+.25,-d*.20,1.25);hvac(w*.20,h+.25,d*.10,.9);
    box('#e3d9c7',w*.20,h+.8,-d*.25,w*.22,1.6,d*.23);
  } else if(family==='brick_shop'||family==='restaurant'){
    const restaurant=family==='restaurant',variant=seed%4;
    const brick=[BRICK[0],'#b88c6a','#a56d56','#c5b394'][variant];
    const cornice=['#e9dcc0','#d9caae','#eedec4','#e7d9bc'][variant];
    const awning=['#537d69','#996956','#56717f','#b29765'][(seed>>>3)%4];
    const roofing=['#879282','#a6a28e','#737f7c','#b2aa90'][variant];
    const frontDepth=d*(variant===1?.45:.56),frontZ=d/2-frontDepth/2;
    // Some shop families include a lower rear service annex. This articulates
    // the same recorded footprint and maximum wall height, not extra floors.
    const stepped=variant===1||variant===3,rearDepth=d-frontDepth,rearZ=-d/2+rearDepth/2,rearH=stepped?h*(stories>1?.66:.83):h;
    function shopRoof(x,y,z,rw,rd,front=false){
      box(roofing,x,y+.10,z,rw,.20,rd);
      for(const sign of [-1,1]){box(brick,x+sign*(rw/2-.15),y+.36,z,.3,.56,rd);box(cornice,x+sign*(rw/2-.15),y+.67,z,.40,.13,rd+.08);}
      box(brick,x,y+.36,z-rd/2+.15,rw,.56,.30);box(cornice,x,y+.67,z-rd/2+.15,rw+.08,.13,.40);
      if(front){box(brick,x,y+.48,z+rd/2-.15,rw,.8,.30);box(cornice,x,y+.91,z+rd/2-.15,rw+.20,.16,.52);}
      // A recessed roof field and coping border read clearly from the fixed
      // camera, while preserving the source's flat-roof classification.
      box(['#8c9989','#b7ad90','#718583','#a9a18b'][variant],x,y+.215,z,rw-.95,.025,rd-.95);
    }
    if(stepped){courses(0,0,frontZ,w,h,frontDepth,brick);courses(0,0,rearZ,w,rearH,rearDepth,brick);shopRoof(0,h,frontZ,w,frontDepth,true);shopRoof(0,rearH,rearZ,w,rearDepth);}
    else {courses(0,0,0,w,h,d,brick);shopRoof(0,h,0,w,d,true);}
    // False-front parapets vary the street silhouette without a pitched roof.
    const crownW=w*[.42,.64,.80,.48][variant],crownH=[.55,1.05,.32,.85][variant];
    box(brick,variant===3?-w*.18:0,h+1.02+crownH/2,d/2-.15,crownW,crownH,.34);
    box(cornice,variant===3?-w*.18:0,h+1.08+crownH,d/2-.15,crownW+.25,.14,.58);
    box(cornice,0,h-.20,d/2+.12,w+.30,.32,.45);
    box(cornice,0,h-.60,d/2+.09,w+.13,.12,.29);
    const storefrontH=Math.min(2.9,h*(stories>1?.45:.65)),bays=variant%2?3:2,bayW=w/bays;
    for(let i=0;i<bays;i++){
      const x=(-.5+(i+.5)/bays)*w;
      box(p.trim,x,storefrontH/2+.18,d/2+.02,bayW-.32,storefrontH,.18);
      box(glass,x,storefrontH/2+.20,d/2+.13,bayW-.59,storefrontH-.28,.08);
      box('#a3b8b1',x-bayW*.18,storefrontH*.60,d/2+.19,bayW*.23,storefrontH*.48,.025);
      box(p.trim,x,storefrontH/2+.20,d/2+.22,.10,storefrontH,.06);
      box(cornice,x,.26,d/2+.22,bayW-.25,.38,.16);
      // Broad shop canopies are visible at town zoom. Restrained striping is
      // reserved for restaurants so the commercial street has a coherent rhythm.
      const aw=bayW-.24,az=d/2+.64,ay=storefrontH+.48;
      slope(awning,x,ay,az,aw,.15,1.65,.20);box(awning,x,ay-.23,az+.77,aw,.35,.10);
      if(restaurant)for(let stripe=0;stripe<5;stripe++)slope('#e9dfc6',x-aw/2+(stripe+.5)*aw/5,ay+.08,az,aw/10,.026,1.65,.20);
      if(i<bays-1)box(cornice,x+bayW/2,h*.48,d/2+.045,.24,h*.96,.27);
    }
    door(w*(variant%2?.28:-.28),0,d/2+.28,1.18,Math.min(2.4,storefrontH),shadow);
    if(stories>1)for(let floor=1;floor<stories;floor++)for(let i=0;i<bays*2;i++){
      const x=(-.5+(i+.5)/(bays*2))*w;
      window(x,(floor+.55)*h/stories,d/2+.035,Math.min(1.40,w/(bays*2)*.57),Math.min(1.70,h/stories*.52));
      if(variant===2)box(cornice,x,(floor+.55)*h/stories+.94,d/2+.12,1.55,.15,.28);
    }
    // Solid signboard is graphic architecture only; no invented business name.
    box(awning,0,storefrontH+.95,d/2+.13,w*.56,.48,.19);
    for(const sign of [-1,1]){box(cornice,sign*(w/2-.17),h/2,d/2+.06,.30,h,.28);box(cornice,sign*(w/2-.17),h+.49,d/2-.13,.54,.95,.57);}
    function skylight(x,y,z,sw,sd){
      box(cornice,x,y+.24,z,sw+.25,.32,sd+.25);box('#749291',x,y+.43,z,sw,.14,sd);
      for(let i=0;i<4;i++)box('#c4cbb9',x+(-.5+i/3)*sw,y+.52,z,.065,.045,sd);
      box('#c4cbb9',x,y+.52,z,sw,.045,.065);
    }
    if(variant===0||variant===2){
      skylight(0,h,-d*.02,w*.35,d*.23);
      if(variant===2)skylight(0,h,-d*.30,w*.35,d*.15);
      hvac(-w*.30,h+.22,-d*.33,.95);
    }else {
      skylight(w*.05,h,frontZ,w*.38,frontDepth*.28);
      const screenW=w*.46,screenD=rearDepth*.40,screenZ=rearZ;
      hvac(-w*.08,rearH+.24,screenZ,1.12);
      for(const sign of [-1,1])box('#849180',sign*screenW/2,rearH+.85,screenZ,.16,1.30,screenD);
      box('#849180',0,rearH+.85,screenZ-screenD/2,screenW,1.30,.16);
      for(let row=0;row<4;row++)box('#b3baa5',0,rearH+.34+row*.32,screenZ-screenD/2-.09,screenW,.055,.035);
    }
    if(restaurant)chimney(w*.30,-d*.32,rearH,.85);
    // Side elevations get structural piers and rear service windows so the
    // back of a shop remains recognisably a building, not a featureless box.
    for(const sign of [-1,1]){
      for(const z of [-d*.34,0,d*.32])box(cornice,sign*(w/2+.01),rearH*.47,z,.11,rearH*.94,.28);
      window(sign*(w/2+.03),rearH*.55,-d*.25,1.8,1.2,sign);
    }
  } else if(family==='school'){
    const centerW=w*.30,wingW=w*.35,wingH=h*.75;
    courses(0,0,.02*d,centerW,h,d,BRICK[0]);roof(0,h,.02*d,centerW+.7,d+.7,Math.min(2.4,centerW*.25),p.roof,true);
    for(const sign of [-1,1]){
      const x=sign*w*.325;courses(x,0,-d*.10,wingW,wingH,d*.75,'#dac8a6');roof(x,wingH,-d*.10,wingW+.5,d*.75+.5,1.5,p.roof,true);
      const windows=Math.max(3,Math.round(wingW/3.8));for(let floor=0;floor<stories;floor++)for(let i=0;i<windows;i++)window(x+(-.5+(i+.5)/windows)*wingW*.88,(floor+.55)*wingH/stories,d*.275+.03,Math.min(1.6,wingW/windows*.60),Math.min(1.6,wingH/stories*.54));
    }
    door(0,.28,d*.52+.025,Math.min(2.2,centerW*.4),2.55);box(stone,0,3.13,d*.52+.1,centerW*.83,.45,.38);
    for(const x of [-centerW*.29,centerW*.29])box(stone,x,1.72,d*.52+.12,.4,3,.40);
    if(h>5)window(0,h*.73,d*.52+.035,1.75,1.6);steps(0,d*.52+.4,centerW*.75,.3);
    const flag=new THREE.CylinderGeometry(.045,.065,5.5,5);b.add(flag,'#b1b1a3',w*.43,2.75,d*.41);flag.dispose();box('#678d99',w*.43+.48,4.70,d*.41,.95,.65,.05);
  } else if(family==='church'){
    const naveW=w*.72,naveD=d*.86,naveZ=-d*.06,rh=Math.min(4,w*.38);
    courses(0,0,naveZ,naveW,h,naveD,'#e4ddca');roof(0,h,naveZ,naveW+.65,naveD+.65,rh,'#6b7a7d');gable(0,h,naveZ+naveD/2+.02,naveW,rh*.90,'#e4ddca');
    const tw=w*.32,tz=d*.32,th=h+rh*.64;courses(0,0,tz,tw,th,d*.27,'#d5c7ac');box(stone,0,th-.3,tz,tw+.28,.35,d*.27+.28);
    for(const sign of [-1,1]){box(shadow,sign*tw*.27,th-1.0,tz+d*.135+.02,tw*.22,.8,.04);box(stone,sign*tw*.27,th-.45,tz+d*.135+.05,tw*.27,.10,.11);}
    const spire=new THREE.ConeGeometry(tw*.78,Math.max(2.5,tw*1.55),4);b.add(spire,'#66817f',0,th+Math.max(2.5,tw*1.55)/2,tz,1,1,1,0,Math.PI/4);spire.dispose();
    door(0,.3,tz+d*.135+.04,Math.min(1.8,tw*.62),2.65,'#7b6753');steps(0,tz+d*.135+.3,tw*.88,.3);
    for(const sign of [-1,1])for(let i=0;i<4;i++)window(sign*(naveW/2+.025),h*.54,(-.40+i*.23)*naveD,1.0,Math.min(2.9,h*.57),sign);
  } else if(family==='pump_house'){
    courses(0,0,0,w,h,d,'#c8c6b1');roof(0,h,0,w+.7,d+.7,Math.min(2.2,w*.18),'#65817b',true);
    const gateW=Math.min(3,w*.26);box(stone,-w*.18,h*.33,d/2+.06,gateW+.4,h*.62,.18);box('#587971',-w*.18,h*.31,d/2+.18,gateW,h*.58,.10);
    box(stone,-w*.18,h*.33,d/2+.25,.08,h*.6,.06);window(w*.28,h*.55,d/2+.04,Math.min(2.8,w*.18),1.0);
    for(const sign of [-1,1]){window(sign*(w/2+.025),h*.57,-d*.2,1.5,1.2,sign);for(let i=0;i<5;i++)box('#647e73',sign*(w/2+.05),h*.62+i*.13,d*.23,.09,.07,d*.22);}
    // Distinct utility architecture, without inventing visible pipe connections.
    box('#59766a',0,h*.87,d/2+.06,w*.47,.32,.08);chimney(-w*.33,-d*.28,h,.50);
  } else if(family==='utility_depot'){
    courses(0,0,0,w,h,d,'#c1c8be');flatRoof(0,h,0,w,d);
    const bays=Math.max(2,Math.min(5,Math.round(w/5.8))),bw=w/bays;
    for(let i=0;i<bays;i++){
      const x=(-.5+(i+.5)/bays)*w,dh=Math.min(3.9,h*.76);box(stone,x,dh/2+.1,d/2+.045,bw*.78,dh+.2,.18);box('#67827b',x,dh/2,d/2+.15,bw*.69,dh,.08);
      for(let y=.45;y<dh;y+=.4)box('#a7b4a5',x,y,d/2+.21,bw*.66,.035,.035);
      box(glass,x,dh*.76,d/2+.22,bw*.50,.38,.035);
      for(const sign of [-1,1])box('#c9ab64',x+sign*bw*.40,.55,d/2+.35,.14,1.1,.14);
    }
    for(const sign of [-1,1])for(let i=0;i<3;i++)window(sign*(w/2+.02),h*.66,(-.33+i*.33)*d,1.6,.75,sign);
    hvac(-w*.27,h+.22,0,1.4);hvac(w*.26,h+.22,-d*.22,1.1);
    // Raised north-light volumes give a recognisable workshop silhouette.
    for(let i=0;i<2;i++){const z=(-.22+i*.43)*d;box('#afb9b2',0,h+.65,z,w*.40,1.1,d*.17);slope('#627a7b',0,h+1.18,z,w*.43,.12,d*.20,-.20);box(glass,0,h+.82,z+d*.087,w*.34,.50,.05);}
    box('#496f73',0,h*.91,d/2+.11,w*.38,.4,.11);
  }
  if(home.solar){
    const flat=['apartment','townhouse','brick_shop','restaurant','utility_depot'].includes(family)||String(home.roof).includes('flat');
    const rh=Math.min(3,w*.30),panel=new THREE.BoxGeometry(1,1,1),x=flat?-w*.20:w*.23,y=flat?h+.96:h+rh*.59,z=-d*.15,rz=flat?0:-Math.atan2(rh,w*.5);
    b.add(panel,'#304f62',x,y,z,Math.min(3.2,w*.28),.10,Math.min(4,d*.33),0,0,rz);
    for(let i=0;i<3;i++)b.add(panel,'#9baeb0',x,y+.07,z+(-1+i)*Math.min(4,d*.33)/3,Math.min(3.2,w*.28),.025,.035,0,0,rz);
    panel.dispose();
  }
  const geometry=b.build();geometry.computeBoundingBox();
  // Wall height remains authoritative; compact roof ornaments to a consistent
  // decorative allowance rather than changing physical storey heights.
  const excess=geometry.boundingBox.max.y-h;
  if(excess>2.5){const positions=geometry.attributes.position;for(let i=0;i<positions.count;i++){const y=positions.getY(i);if(y>h)positions.setY(i,h+(y-h)*2.5/excess);}positions.needsUpdate=true;geometry.computeVertexNormals();geometry.computeBoundingBox();geometry.computeBoundingSphere();}
geometry.userData={family,sourcePremiseId:home.id,units:'meters',front:'+Z',decorativeArchitecture:true};return geometry;
}
