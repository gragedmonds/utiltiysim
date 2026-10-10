// Presentation geometry only. Saved frontage, road and entrance coordinates stay
// unchanged. A driveway mouth meets the pavement edge, never its centerline.
export function pavementQuad(a,b,width){
  const length=Math.hypot(b.x-a.x,b.z-a.z);if(length<.001)return null;
  const nx=-(b.z-a.z)/length*width/2,nz=(b.x-a.x)/length*width/2;
  return [{x:a.x+nx,z:a.z+nz},{x:a.x-nx,z:a.z-nz},{x:b.x-nx,z:b.z-nz},{x:b.x+nx,z:b.z+nz}];
}

// Separating-axis test; touching an edge is permitted, crossing it is not.
export function convexOverlap(a,b){
  for(const poly of[a,b])for(let i=0;i<poly.length;i++){
    const p=poly[i],q=poly[(i+1)%poly.length],nx=-(q.z-p.z),nz=q.x-p.x,length=Math.hypot(nx,nz);
    if(length<.001)continue;
    const pa=a.map(v=>(v.x*nx+v.z*nz)/length),pb=b.map(v=>(v.x*nx+v.z*nz)/length);
    if(Math.max(...pa)<=Math.min(...pb)+.001||Math.max(...pb)<=Math.min(...pa)+.001)return false;
  }
  return true;
}

export function frontageAccessQuad(access,road,halfWidth,pavement=[]){
  if(!access||!road?.points?.length||!Number.isFinite(road.width)||road.width<=0)return null;
  const [a,b]=access,dx=b.x-a.x,dz=b.z-a.z,length=Math.hypot(dx,dz);
  if(length<.01)return null;
  const lateral={x:-dz/length*halfWidth,z:dx/length*halfWidth};
  let nearest=null;
  for(let i=1;i<road.points.length;i++){
    const p=road.points[i-1],q=road.points[i],sx=q.x-p.x,sz=q.z-p.z,n=Math.hypot(sx,sz);if(n<.001)continue;
    const t=Math.max(0,Math.min(1,((a.x-p.x)*sx+(a.z-p.z)*sz)/(n*n))),distance=Math.hypot(a.x-p.x-sx*t,a.z-p.z-sz*t);
    if(!nearest||distance<nearest.distance)nearest={p,nx:-sz/n,nz:sx/n,distance};
  }
  if(!nearest)return null;
  let {p,nx,nz}=nearest;
  if((b.x-p.x)*nx+(b.z-p.z)*nz<0){nx=-nx;nz=-nz;}
  const travel=dx*nx+dz*nz;if(travel<.001)return null;
  // Intersect each driveway side with the same curb half-plane. Moving the
  // whole mouth by the furthest corner's clearance leaves a triangular gap
  // on an oblique approach; independent intersections make a flush trapezoid.
  const mouth=side=>{
    const corner={x:a.x+lateral.x*side,z:a.z+lateral.z*side};
    const from=(corner.x-p.x)*nx+(corner.z-p.z)*nz,t=(road.width/2-from)/travel;
    // Do not extend an access behind its recorded start to invent a connection.
    if(t<-.000001||t>=1)return null;
    return {x:corner.x+dx*Math.max(0,t),z:corner.z+dz*Math.max(0,t)};
  };
  const left=mouth(1),right=mouth(-1);if(!left||!right)return null;
  const quad=[left,right,{x:b.x-lateral.x,z:b.z-lateral.z},{x:b.x+lateral.x,z:b.z+lateral.z}];
  // Reject ambiguous junctions or a route crossing another carriageway. A
  // future site planner can propose a new access; artwork cannot move it.
  return pavement.some(polygon=>convexOverlap(quad,polygon))?null:quad;
}
