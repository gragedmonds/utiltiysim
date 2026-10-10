/** Conservative design-study envelopes in metres, not zoning or engineering
 * approval. Operational records are never inferred from a successful fit.
 * Building ranges are independent of setbacks/access: never stretch artwork
 * to consume a parcel. A failed variant should give way to a smaller one.
 */
export const SITE_RULES=Object.freeze({
 cottage:{min:[7,8],max:[16,18],side:2,rear:4,front:5,access:'Pedestrian approach; vehicle access needs a separate driveway check.'},
 craftsman:{min:[9,9],max:[20,22],side:2.5,rear:5,front:6,access:'Front approach and garden clearance; do not cover the sidewalk.'},
 townhouse:{min:[5,10],max:[9,20],side:0,rear:5,front:4,access:'Party-wall frontage requires explicit adjacent-unit ownership.'},
 apartment:{min:[18,16],max:[60,45],side:4,rear:10,front:8,access:'Shared entry and service space; courtyard, parking and fire access need separate checks.'},
 storefront:{min:[5,8],max:[24,35],side:0,rear:5,front:2,access:'Public entrance at sidewalk; rear/side delivery route must remain connected.'},
 depot:{min:[18,14],max:[60,45],side:4,rear:4,front:14,access:'Light service vehicles: reserve a forecourt, then validate swept paths and gate width.'},
 industrial:{min:[24,20],max:[120,90],side:6,rear:8,front:28,access:'Reserve freight court; truck swept paths, loading and pedestrian separation remain required.'},
});
function onSegment(p,a,b){const cross=(p.x-a.x)*(b.z-a.z)-(p.z-a.z)*(b.x-a.x);return Math.abs(cross)<1e-7&&p.x>=Math.min(a.x,b.x)-1e-7&&p.x<=Math.max(a.x,b.x)+1e-7&&p.z>=Math.min(a.z,b.z)-1e-7&&p.z<=Math.max(a.z,b.z)+1e-7;}
function inside(p,poly){let hit=false;for(let i=0,j=poly.length-1;i<poly.length;j=i++){const a=poly[i],b=poly[j];if(onSegment(p,a,b))return true;if((a.z>p.z)!==(b.z>p.z)&&p.x<(b.x-a.x)*(p.z-a.z)/(b.z-a.z)+a.x)hit=!hit;}return hit;}
function intersectionT(a,b,c,d){const x=b.x-a.x,z=b.z-a.z,u=d.x-c.x,v=d.z-c.z,den=x*v-z*u;if(Math.abs(den)<1e-10)return null;const t=((c.x-a.x)*v-(c.z-a.z)*u)/den,s=((c.x-a.x)*z-(c.z-a.z)*x)/den;return t>0&&t<1&&s>=0&&s<=1?t:null;}
function contained(shape,lot){
 if(!shape.every(p=>inside(p,lot)))return false;
 // Check every interval split by boundary intersections, including concave
 // notches whose edges can cross an envelope with all four corners inside.
 return shape.every((a,i)=>{const b=shape[(i+1)%shape.length],ts=[0,1];for(let j=0;j<lot.length;j++){const t=intersectionT(a,b,lot[j],lot[(j+1)%lot.length]);if(t!==null)ts.push(t);}ts.sort((a,b)=>a-b);return ts.slice(1).every((v,j)=>{const t=(v+ts[j])/2;return inside({x:a.x+(b.x-a.x)*t,z:a.z+(b.z-a.z)*t},lot);});});
}
export function assessSiteFit({family,width,depth,x,z,yaw=0},lot){
 const rule=SITE_RULES[family],invalid=!rule||![width,depth,x,z,yaw].every(Number.isFinite)||!Array.isArray(lot)||lot.length<3||!lot.every(p=>Number.isFinite(p.x)&&Number.isFinite(p.z));
 if(invalid)return{fits:false,reason:'Missing or invalid site geometry',designOnly:true};
 if(width<rule.min[0]||depth<rule.min[1])return{fits:false,reason:'Building is below the minimum size for this family',designOnly:true};
 if(width>rule.max[0]||depth>rule.max[1])return{fits:false,reason:'Building exceeds the maximum size for this family',designOnly:true};
 const c=Math.cos(yaw),s=Math.sin(yaw),point=(u,v)=>({x:x+u*c+v*s,z:z-u*s+v*c});
 const rectangle=(left,right,back,front)=>[point(left,back),point(right,back),point(right,front),point(left,front)];
 const footprint=rectangle(-width/2,width/2,-depth/2,depth/2),envelope=rectangle(-width/2-rule.side,width/2+rule.side,-depth/2-rule.rear,depth/2+rule.front);
 const footprintFits=contained(footprint,lot),fits=footprintFits&&contained(envelope,lot);
 return{fits,footprintFits,footprint,envelope,reason:fits?'Building and initial access envelope fit; route and engineering checks still required':footprintFits?'Building fits, but its access or clearance envelope does not':'Building footprint leaves the parcel',access:rule.access,designOnly:true};
}
export function chooseFittingAsset(candidates,lot){
 // Order is caller preference, not a demand or density optimization. Never
 // shrink a failed candidate or silently turn a home into another premise use.
 for(const candidate of candidates){const fit=assessSiteFit(candidate,lot);if(fit.fits)return{candidate,fit};}
 return null;
}
