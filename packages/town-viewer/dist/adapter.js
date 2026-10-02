/** Viewer contract v1. Pure adapters: never generate demand, readings, bills or incidents. */
export const UTILITIES = ['electric', 'water', 'gas'];
export const PALETTE = { electric:0xe5a735, water:0x149faf, gas:0xa783d8 };
const finite = (v, name) => { if (!Number.isFinite(v)) throw new Error(`${name} must be finite.`); return v; };
const text = (v, name) => { if (typeof v !== 'string' || !v.length) throw new Error(`${name} is required.`); return v; };
const list = (v, name) => { if (!Array.isArray(v)) throw new Error(`${name} must be an array.`); return v; };
const unique = (values, name) => { const seen = new Set(); for (const v of values) { text(v, name); if (seen.has(v)) throw new Error(`Duplicate ${name}: ${v}`); seen.add(v); } return seen; };
const nullable = (v, name) => v === null ? null : finite(v, name);
const date = (v, name) => { text(v,name);if(!/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(v)||!Number.isFinite(Date.parse(v)))throw new Error(`${name} requires an ISO timestamp with timezone.`);return v; };
function point(p, name) { finite(p?.x, `${name}.x`); finite(p?.z, `${name}.z`); if(p.elevationM!==undefined)finite(p.elevationM,`${name}.elevationM`); }

export function heightSampler(terrain, legacyFallback) {
 const h = terrain?.heightmap || terrain;
 if (!h) { if (legacyFallback) return legacyFallback; throw new Error('Engine snapshot requires terrain heightmap.'); }
 if (!Number.isInteger(h.cols)||h.cols<2||!Number.isInteger(h.rows)||h.rows<2) throw new Error('Heightmap rows/cols must be integers ≥ 2.');
 if(h.cols*h.rows>4_000_000)throw new Error('Heightmap exceeds the viewer limit (4 million cells).');
 finite(h.cellSizeM,'heightmap.cellSizeM');if(h.cellSizeM<=0)throw new Error('Heightmap cell size must be positive.');
 finite(h.originX,'heightmap.originX');finite(h.originZ,'heightmap.originZ');
 if(h.order!==undefined&&h.order!=='row-major-z-positive')throw new Error('Heightmap must use row-major-z-positive ordering.');
 list(h.values,'heightmap.values');if(h.values.length!==h.rows*h.cols)throw new Error('Heightmap value count does not match dimensions.');h.values.forEach(v=>finite(v,'heightmap value'));
 // Explicitly clamp the small border used by the renderer. No geometry rescaling.
 return (x,z)=>{const fx=Math.max(0,Math.min(h.cols-1,(x-h.originX)/h.cellSizeM)),fz=Math.max(0,Math.min(h.rows-1,(z-h.originZ)/h.cellSizeM));const ix=Math.min(h.cols-2,Math.floor(fx)),iz=Math.min(h.rows-2,Math.floor(fz)),tx=fx-ix,tz=fz-iz;const v=h.values,i=iz*h.cols+ix;return (v[i]*(1-tx)+v[i+1]*tx)*(1-tz)+(v[i+h.cols]*(1-tx)+v[i+h.cols+1]*tx)*tz;};
}

export function inspectSnapshot(snapshot, {legacyTerrain}={}) {
 if(!snapshot||!['utility-town/1.0','utility-town/2.0'].includes(snapshot.schemaVersion))throw new Error('Expected utility-town/1.0 or utility-town/2.0 snapshot.');
 text(snapshot.id,'town id');const legacy=snapshot.schemaVersion==='utility-town/1.0';
 const homes=list(snapshot.premises,'premises');if(homes.length<1||homes.length>15000||snapshot.count!==homes.length)throw new Error('Premise count must match count and be 1–15,000 (including nonresidential premises).');
 unique(homes.map(h=>h.id),'premise id');
 for(const h of homes){point(h,'premise');for(const k of ['width','depth','height']){finite(h[k],`premise.${k}`);if(h[k]<=0)throw new Error(`Premise ${k} must be positive.`);}for(const k of ['angle','side','roofTone','solarKW'])finite(h[k],`premise.${k}`);if(![-1,1].includes(h.side))throw new Error('Premise side must be -1 or 1.');if(!h.services||typeof h.services!=='object')throw new Error('Premise services are required.');}
 const bounds=snapshot.bounds;for(const k of ['minX','maxX','minZ','maxZ'])finite(bounds?.[k],`bounds.${k}`);if(bounds.maxX<=bounds.minX||bounds.maxZ<=bounds.minZ)throw new Error('Invalid map bounds.');
 for(const r of list(snapshot.roads,'roads')){const points=list(r.points,'road.points');if(points.length<2)throw new Error('Road geometry needs two points.');points.forEach(p=>point(p,'road point'));}
 const networks={};
 for(const u of UTILITIES){const n=snapshot.networks?.[u];if(!n)throw new Error(`Missing ${u} network.`);const nodes=list(n.nodes,`${u}.nodes`),edges=list(n.edges,`${u}.edges`);const nodeIds=unique(nodes.map(n=>n.id),`${u} node id`),edgeIds=unique(edges.map(e=>e.id),`${u} edge id`);
  const sources=n.sourceIds||[n.sourceId];unique(sources,`${u} source id`);sources.forEach(id=>{if(!nodeIds.has(id))throw new Error(`Unknown source ${id}.`);});
  for(const node of nodes)point(node,`${u} node`);
  for(const e of edges){if(!nodeIds.has(e.from)||!nodeIds.has(e.to))throw new Error(`Dangling edge ${e.id}.`);if(e.enabled!==undefined&&typeof e.enabled!=='boolean')throw new Error(`Invalid enabled flag ${e.id}.`);finite(e.lengthM,'edge.lengthM');if(e.lengthM<0)throw new Error('Edge length cannot be negative.');const ps=list(e.points,'edge.points');if(ps.length<2)throw new Error(`Edge ${e.id} needs geometry.`);ps.forEach(p=>point(p,'edge point'));}
  const served=new Set(nodes.filter(n=>n.kind==='meter').flatMap(n=>[n.premiseId,n.servicePointId].filter(Boolean)));for(const h of homes)if(h.services[u]&&!served.has(h.id)&&!served.has(h.services[u]))throw new Error(`No network meter node for ${h.id}/${u}.`);
  if(n.unit!==(u==='electric'?'kW':'m3/h'))throw new Error(`${u} flow unit must remain SI (${u==='electric'?'kW':'m3/h'}).`);
  networks[u]={nodes:new Map(nodes.map(n=>[n.id,n])),edges:new Map(edges.map(e=>[e.id,e])),sources:new Set(sources),edgeIds:[...edgeIds]};
 }
 if(!legacy){text(snapshot.topologyRevision,'topologyRevision');text(snapshot.indexRevision,'indexRevision');if(snapshot.source?.utilityOffsets!=='geometry')throw new Error('2.0 geometry must declare source.utilityOffsets="geometry".');}
 const sampleHeight=heightSampler(snapshot.terrain,legacy?legacyTerrain:undefined);
 return {snapshot,legacy,networks,sampleHeight,topologyRevision:snapshot.topologyRevision||'legacy-1',indexRevision:snapshot.indexRevision||'legacy-1'};
}

/** Loop-safe connectivity route. This is not a hydraulic solution or a complete set of flow paths. */
export function traceConnection(snapshot,premiseId,utility,enabledOverrides=null){
 const net=snapshot.networks[utility],home=snapshot.premises.find(h=>h.id===premiseId);if(!home?.services[utility])return {connected:false,edges:[],reason:'No service'};
 const target=net.nodes.find(n=>n.kind==='meter'&&(n.premiseId===premiseId||n.servicePointId===home.services[utility]));if(!target)return {connected:false,edges:[],reason:'Meter node missing'};
 const sources=new Set(net.sourceIds||[net.sourceId]),adj=new Map(net.nodes.map(n=>[n.id,[]]));
 for(const edge of net.edges){const active=enabledOverrides?.get(edge.id)??edge.enabled??(edge.normallyOpen!==true);if(!active)continue;adj.get(edge.from)?.push({edge,next:edge.to});adj.get(edge.to)?.push({edge,next:edge.from});}
 for(const a of adj.values())a.sort((a,b)=>a.edge.id.localeCompare(b.edge.id));
 const queue=[target.id],visited=new Set(queue),parents=new Map();let source=null;
 for(let i=0;i<queue.length;i++){const current=queue[i];if(sources.has(current)){source=current;break;}for(const {edge,next} of adj.get(current)||[]){if(visited.has(next))continue;visited.add(next);parents.set(next,{towardMeter:current,edge});queue.push(next);}}
 if(!source)return {connected:false,edges:[],reason:'Isolated from all sources',mode:'connectivity'};
 const path=[];let id=source;while(id!==target.id){const p=parents.get(id);path.push(p.edge);id=p.towardMeter;}
 return {connected:true,sourceId:source,edges:path,reason:null,mode:'connectivity'};
}

export function geometryOffset(snapshot,utility){return snapshot.source?.utilityOffsets==='geometry'?0:utility==='water'?2.8:utility==='gas'?-2.8:0;}
export function displayQuantity(value,unit,commodity,profile='ontario'){
 if(value===null||value===undefined)return {value:null,unit:commodity==='gas'&&profile==='ontario'?(unit==='m3/h'?'CCF/h':'CCF'):unit};
 finite(value,'display value');if(commodity==='gas'&&profile==='ontario'&&['m3','m3/h'].includes(unit))return {value:value/2.831685,unit:unit==='m3/h'?'CCF/h':'CCF'};
 return {value,unit:unit.replace('m3','m³')};
}
export function validateClock(c){
 if(!c)return null;date(c.simTime,'clock.simTime');text(c.timezone,'clock.timezone');try{new Intl.DateTimeFormat('en',{timeZone:c.timezone}).format();}catch{throw new Error('Unknown clock timezone.');}
 if(c.sunElevationDeg!==undefined){finite(c.sunElevationDeg,'sunElevationDeg');if(c.sunElevationDeg< -90||c.sunElevationDeg>90)throw new Error('Sun elevation is out of range.');}
 if(c.sunAzimuthDeg!==undefined)finite(c.sunAzimuthDeg,'sunAzimuthDeg');
 if(c.moonPhase!==undefined&&(finite(c.moonPhase,'moonPhase')<0||c.moonPhase>1))throw new Error('Moon phase must be from 0 to 1.');
 return {...c};
}

export class StateReceiver {
 constructor(inspection){this.inspection=inspection;this.frame=null;this.lastSequence=-1;this.runId=null;this.flow=null;}
 validate(frame){
  const {snapshot,topologyRevision,indexRevision}=this.inspection;
  if(frame?.schemaVersion!=='utility-state/1.0')throw new Error('Expected utility-state/1.0 frame.');
  if(frame.townId!==snapshot.id)throw new Error('State belongs to another town.');
  if(frame.topologyRevision!==topologyRevision||frame.indexRevision!==indexRevision)throw new Error('State revision mismatch. Load its matching snapshot first.');
  text(frame.simulationId,'simulationId');if(!Number.isInteger(frame.sequence)||frame.sequence<0)throw new Error('Invalid frame sequence.');if(frame.complete!==true)throw new Error('Only complete frames are supported.');date(frame.simTime,'simTime');
  const result={homes:new Map(snapshot.premises.map(h=>[h.id,{electric:null,water:null,gas:null}]))};
  for(const u of UTILITIES){const f=frame.networks?.[u],known=this.inspection.networks[u].edges;if(!f||f.unit!==snapshot.networks[u].unit)throw new Error(`Missing ${u} state or mismatched units.`);const ids=list(f.edgeIds,`${u}.edgeIds`),values=list(f.flows,`${u}.flows`);unique(ids,`${u} frame edge id`);if(ids.length!==known.size||values.length!==ids.length||ids.some(id=>!known.has(id)))throw new Error(`Incomplete or unknown ${u} edge index.`);
   const enabled=f.enabled??ids.map(id=>known.get(id).enabled??!known.get(id).normallyOpen);if(!Array.isArray(enabled)||enabled.length!==ids.length||enabled.some(x=>typeof x!=='boolean'))throw new Error(`Invalid ${u} enabled array.`);
   const edgeFlows=new Map(),edgeEnabled=new Map();ids.forEach((id,i)=>{edgeFlows.set(id,nullable(values[i],`${u} flow`));edgeEnabled.set(id,enabled[i]);if(!enabled[i]&&values[i]!==null&&values[i]!==0)throw new Error(`Disabled edge ${id} has nonzero flow.`);});result[u]={source:nullable(f.sourceFlow,`${u}.sourceFlow`),unit:f.unit,edgeFlows,edgeEnabled};
  }
  if(frame.premises){const ids=list(frame.premises.ids,'premise ids');unique(ids,'frame premise id');if(ids.length!==snapshot.premises.length||ids.some(id=>!result.homes.has(id)))throw new Error('Premise frame index mismatch.');for(const u of UTILITIES){const vals=list(frame.premises[u],`premises.${u}`);if(vals.length!==ids.length)throw new Error('Premise array length mismatch.');ids.forEach((id,i)=>result.homes.get(id)[u]=nullable(vals[i],`premise ${u} flow`));}}
  const clock=validateClock(frame.clock);if(clock&&clock.simTime!==frame.simTime)throw new Error('Clock timestamp differs from frame timestamp.');
  return {flow:result,clock};
 }
 accept(frame){const validated=this.validate(frame);if(this.runId!==null&&this.runId!==frame.simulationId)throw new Error('New simulation run requires an explicit replay reset.');if(frame.sequence<=this.lastSequence)throw new Error('Stale or duplicate frame.');if(this.frame&&Date.parse(frame.simTime)<Date.parse(this.frame.simTime))throw new Error('Rewind requires an explicit replay reset.');this.frame=frame;this.runId=frame.simulationId;this.lastSequence=frame.sequence;this.flow=validated.flow;return validated;}
 reset(){this.frame=null;this.flow=null;this.lastSequence=-1;this.runId=null;}
}

/** Pure visual interpolation of engine trajectories; never invents a road route. */
export function interpolateTrajectory(trajectory,simTime){
 const points=list(trajectory?.points,'trajectory.points');if(!points.length)return null;let previous=-Infinity;for(const p of points){point(p,'trajectory point');const ms=Date.parse(date(p.at,'trajectory.at'));if(ms<=previous)throw new Error('Trajectory timestamps must strictly increase.');previous=ms;}
 const t=Date.parse(date(simTime,'simTime'));if(t<Date.parse(points[0].at)||t>Date.parse(points.at(-1).at))return null;
 for(let i=1;i<points.length;i++){const a=points[i-1],b=points[i],ta=Date.parse(a.at),tb=Date.parse(b.at);if(t<=tb){const f=(t-ta)/(tb-ta);return {x:a.x+(b.x-a.x)*f,z:a.z+(b.z-a.z)*f,angle:Math.atan2(b.z-a.z,b.x-a.x)};}}
 return {...points.at(-1),angle:0};
}
