// Which piece of Astra's isometric art (assets/town/isometric, baked into iso/atlas.webp) draws each engine object, and
// which of its views faces the camera. Everything here is a pure function of engine fields: building type, storeys,
// roof, era, solar, and the direction from the house to its street. A generated town therefore fixes its own
// picture: every browser draws the same house, in the same style, facing the same street.
export const VIEWS=['ne','nw','sw','se']; // cameras at SW, SE, NE and NW of the town; rotating steps through them
// Screen = M·(east, south) in metres, as [m11,m12,m21,m22]; a height h lifts a point by h on screen.
export const MATRIX={top:[1,0,0,1],ne:[.866,.866,-.5,.5],nw:[.866,-.866,.5,.5],sw:[-.866,-.866,.5,-.5],se:[-.866,.866,-.5,-.5]};
// Bearing from the town to each camera, in the same east/south frame as a premise's facing.
export const CAMERA_BEARING={ne:3*Math.PI/4,nw:Math.PI/4,sw:-Math.PI/4,se:-3*Math.PI/4};
export const wrap=a=>Math.atan2(Math.sin(a),Math.cos(a));
// The batch-2 studies are drawn front-right, front-left, rear-left, rear-right: the same quarters as the house banks.
const STUDY_VIEW={ne:'front-right',nw:'front-left',se:'rear-left',sw:'rear-right'};
export const DIAGONAL=new Set(['cottage','brick_hip2','ranch_hip']);
export const STUDY=new Set(['industrial','depot','substation','pump_station','water_tower','city_gate','bucket_truck','water_truck','gas_truck','meter_van','ami_meter_module','gas_meter_module']);
// Which way each overhead (top) sprite's front door points in the artwork, before it is turned to face its street.
const ROOF_FRONT={cottage:3*Math.PI/4,ranch_hip:3*Math.PI/4};
const COMMERCIAL=new Set(['storefront','commercial','office','retail','restaurant','school','church','apartment','apartments','institutional','mixed']);
const FACILITY={elevated_tank:'water_tower',tank:'water_tower',substation:'substation',pump_station:'pump_station',pump_house:'pump_station',city_gate:'city_gate',city_gate_regulator:'city_gate',depot:'depot',industrial:'industrial',school:'commercial'};
export function hashUnit(s){let h=2166136261;for(const c of String(s))h=Math.imul(h^c.charCodeAt(0),16777619);return (h>>>0)/4294967296;}
// The direction a premise's front door faces: toward its street frontage point, else from the engine's angle and side.
export function facingOf(p){const f=p?.front;if(f&&Number.isFinite(f.x)&&Number.isFinite(f.z)&&(f.x!==p.x||f.z!==p.z))return Math.atan2(f.z-p.z,f.x-p.x);if(Number.isFinite(p?.angle)){const s=p.side===-1?-1:1;return Math.atan2(-Math.cos(p.angle)*s,Math.sin(p.angle)*s);}return Math.PI/2;}
// A house facing a diagonal (NE, SE, SW, NW) is drawn from the diagonal families, whose art faces the camera square
// on; one facing a cardinal direction uses the three-quarter banks. Both look the same from every camera.
export function isDiagonal(facing){const q=Math.PI/2,d=((facing%q)+q)%q;return Math.abs(d-q/2)<q/4;}
export function premiseArt(h,facing=facingOf(h)){
 const type=h?.buildingType||h?.premiseType||'';if(FACILITY[type]&&type!=='school')return FACILITY[type];
 if(COMMERCIAL.has(type)||(h?.premiseType&&h.premiseType!=='residential')||h?.roof==='flat')return 'commercial';
 if(h?.solar||h?.solarKW>0)return 'solar2';
 const diagonal=isDiagonal(facing);
 if((h?.stories||1)>=2)return diagonal?'brick_hip2':h.era==='pre_1945'||hashUnit(h.uid||h.id)<.5?'victorian2':'brick2';
 return h?.roof==='hip'?(diagonal?'ranch_hip':'bungalow_hip'):(diagonal?'cottage':'bungalow_gable');
}
export const facilityArt=kind=>FACILITY[kind]||null;
export const crewArt=kind=>({electric:'bucket_truck',water:'water_truck',gas:'gas_truck'})[kind]||'meter_van';
// The sprite for a family seen from a view, for an object whose front faces `facing`.
export function spriteName(family,view,facing){
 if(view==='top')return family+(STUDY.has(family)?'.overhead':'.top');
 const r=wrap(CAMERA_BEARING[view]-facing);
 if(DIAGONAL.has(family))return family+'.'+['front','side-b','rear','side-a'][(Math.round(r/(Math.PI/2))+4)%4];
 const bank=r>=0?(r<Math.PI/2?'nw':'sw'):(r>-Math.PI/2?'ne':'se');return family+'.'+(STUDY.has(family)?STUDY_VIEW[bank]:bank);
}
// Overhead sprites are turned on the map so their front door points at the street.
export const topRotation=(family,facing)=>facing-(ROOF_FRONT[family]??Math.PI/2);
export function project(view,dx,dz,h=0){const m=MATRIX[view];return [m[0]*dx+m[1]*dz,m[2]*dx+m[3]*dz-h];}
export function unproject(view,sx,sy){const [a,b,c,d]=MATRIX[view],det=a*d-b*c;return [(d*sx-b*sy)/det,(-c*sx+a*sy)/det];}
