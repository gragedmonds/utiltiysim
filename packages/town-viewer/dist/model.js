// Utility Town v1.0.0: deterministic geography, utility graphs and simulation fixtures.
// All units are explicit. Streets are generic (the engine's synthetic small town); utility assets are synthetic.
import {prepareDemoNetwork} from './roads.js';
export const VERSION = '1.1.0';
export const UTILS = ['electric','water','gas'];
export const LABELS = {electric:'Electricity',water:'Water',gas:'Gas'};
export const COLORS = {electric:0xe5a735,water:0x149faf,gas:0xa783d8};
export function hash(s){let h=2166136261;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619);}return h>>>0;}
export function rng(key){let a=hash(key);return()=>{a+=0x6D2B79F5;let t=a;t=Math.imul(t^t>>>15,t|1);t^=t+Math.imul(t^t>>>7,t|61);return((t^t>>>14)>>>0)/4294967296;};}
export const round=(v,p=3)=>Math.round(v*10**p)/10**p;
export const distance=(a,b)=>Math.hypot(a.x-b.x,a.z-b.z);
export const terrain=(x,z)=>2.7*Math.sin(x/280)*Math.cos(z/320)+1.3*Math.sin((x+z)/170);
const lerp=(a,b,t)=>({x:a.x+(b.x-a.x)*t,z:a.z+(b.z-a.z)*t});
function polyLength(ps){let l=0;for(let i=1;i<ps.length;i++)l+=distance(ps[i-1],ps[i]);return l;}
export function onPath(ps,t){let target=Math.max(0,Math.min(1,t))*polyLength(ps);for(let i=1;i<ps.length;i++){let len=distance(ps[i-1],ps[i]);if(target<=len||i===ps.length-1){let p=lerp(ps[i-1],ps[i],len?target/len:0);return {...p,angle:Math.atan2(ps[i].z-ps[i-1].z,ps[i].x-ps[i-1].x)};}target-=len;}return {...ps[0],angle:0};}
function slicePath(ps,a,b){let len=polyLength(ps),travel=0;const out=[onPath(ps,a)];for(let i=1;i<ps.length;i++){travel+=distance(ps[i-1],ps[i]);if(travel>len*a+0.001&&travel<len*b-0.001)out.push(ps[i]);}out.push(onPath(ps,b));return out.map(({x,z})=>({x:round(x),z:round(z)}));}
// A street graph as nodes (lat/lon) and ways (highway class, name): demo-streets.json, written by the engine.
export function parseStreets(raw){
 if(!raw||!Array.isArray(raw.elements))throw Error('The street file needs elements: nodes and road ways.');
 if(raw.elements.length>100000)throw Error('The street file has more than 100,000 elements.');
 const coord=new Map(),ways=[];for(const e of raw.elements){if(e.type==='node'&&Number.isFinite(e.lat)&&Number.isFinite(e.lon))coord.set(String(e.id),{lat:e.lat,lon:e.lon});}
 for(const e of raw.elements){if(e.type!=='way'||!['primary','secondary','tertiary','residential','unclassified','living_street','service'].includes(e.tags?.highway))continue;let ids=e.nodes?.map(String);if(e.geometry){ids=e.geometry.map((p,i)=>String(e.nodes?.[i]??`${p.lat},${p.lon}`));e.geometry.forEach((p,i)=>{if(p&&Number.isFinite(p.lat)&&Number.isFinite(p.lon))coord.set(ids[i],p);});}if(ids?.length>1&&ids.every(id=>coord.has(id))){let runs=[[]];for(const id of ids){const p=coord.get(id),b=raw.bbox;const inside=!b||(p.lon>=b[0]&&p.lat>=b[1]&&p.lon<=b[2]&&p.lat<=b[3]);if(inside)runs.at(-1).push(id);else if(runs.at(-1).length)runs.push([]);}runs.filter(r=>r.length>1).forEach((run,i)=>ways.push({id:String(e.id)+'-'+i,ids:run,name:e.tags.name||'Local road',class:e.tags.highway}));}}
 if(!ways.length)throw Error('No supported roads with complete geometry were found.');
 const used=new Set(ways.flatMap(w=>w.ids)),values=[...used].map(id=>coord.get(id));
 const lat=values.reduce((a,b)=>a+b.lat,0)/values.length,lon=values.reduce((a,b)=>a+b.lon,0)/values.length;
 const points=new Map([...used].map(id=>{const p=coord.get(id);return[id,{id,x:(p.lon-lon)*111320*Math.cos(lat*Math.PI/180),z:-(p.lat-lat)*111320}];}));
 const adj=new Map([...used].map(id=>[id,[]])),segments=[];
 const duplicate=new Set();
 for(const w of ways)for(let i=1;i<w.ids.length;i++){const a=w.ids[i-1],b=w.ids[i],key=[a,b].sort().join(':');if(a===b||duplicate.has(key)||distance(points.get(a),points.get(b))<0.01)continue;duplicate.add(key);const s={id:`road-${w.id}-${i}`,a,b,name:w.name,class:w.class};segments.push(s);adj.get(a).push(s);adj.get(b).push(s);}
 // Isolated fragments at snapshot boundary must not silently become disconnected services.
 let seen=new Set(),largest=[];for(const id of used){if(seen.has(id))continue;let comp=[id];seen.add(id);for(let i=0;i<comp.length;i++)for(const e of adj.get(comp[i])||[]){let v=e.a===comp[i]?e.b:e.a;if(!seen.has(v)){seen.add(v);comp.push(v);}}if(comp.length>largest.length)largest=comp;}
 const connected=new Set(largest),keep=new Set(largest.filter(id=>adj.get(id).length!==2));if(!keep.size)keep.add(largest[0]);
 const consumed=new Set(),roads=[];
 for(const start of [...keep].sort())for(const first of adj.get(start)||[]){if(consumed.has(first.id))continue;let next=first.a===start?first.b:first.a;let ps=[points.get(start),points.get(next)],e=first;consumed.add(e.id);while(!keep.has(next)){let following=adj.get(next).find(s=>s.id!==e.id);if(!following||consumed.has(following.id))break;consumed.add(following.id);e=following;next=e.a===next?e.b:e.a;ps.push(points.get(next));}if(start!==next)roads.push({id:`r-${roads.length}`,a:start,b:next,points:ps,name:first.name,class:first.class,length:polyLength(ps)});}
 const nodeIds=new Set(roads.flatMap(r=>[r.a,r.b]));
 return {nodes:[...nodeIds].sort().map(id=>points.get(id)),roads,origin:{lat,lon},omittedNodes:used.size-connected.size,sourceHash:hash(JSON.stringify(raw)).toString(16),label:raw.label||'Generic streets',snapshotDate:raw.generatorVersion?`generator ${raw.generatorVersion}`:'generated'};
}
function roadTree(geo){
 const adj=new Map(geo.nodes.map(n=>[n.id,[]]));for(const r of geo.roads){adj.get(r.a).push(r);adj.get(r.b).push(r);}
 const root=[...geo.nodes].sort((a,b)=>(a.x+a.z*.2)-(b.x+b.z*.2)||a.id.localeCompare(b.id))[0];
 const seen=new Set([root.id]),queue=[root.id],roads=[];
 for(let i=0;i<queue.length;i++)for(const r of [...adj.get(queue[i])].sort((a,b)=>a.id.localeCompare(b.id))){let next=r.a===queue[i]?r.b:r.a;if(seen.has(next))continue;seen.add(next);queue.push(next);roads.push({...r,a:queue[i],b:next,points:r.a===queue[i]?r.points:[...r.points].reverse()});}
 const picked=new Set(roads.map(r=>r.id));for(const r of geo.roads){if(!picked.has(r.id))roads.push({...r,b:`closed-${r.id}`});}
 return {root,roads};
}
function candidates(roads,seed){
 const lots=[],spatial=new Map(),random=rng(seed+':lots');
 const roadIndex=new Map();for(const r of roads)for(let i=1;i<r.points.length;i++){const a=r.points[i-1],b=r.points[i];for(let x=Math.floor((Math.min(a.x,b.x)-16)/40);x<=Math.floor((Math.max(a.x,b.x)+16)/40);x++)for(let z=Math.floor((Math.min(a.z,b.z)-16)/40);z<=Math.floor((Math.max(a.z,b.z)+16)/40);z++){const key=`${x}:${z}`;if(!roadIndex.has(key))roadIndex.set(key,[]);roadIndex.get(key).push([a,b]);}}
 const offRoad=p=>(roadIndex.get(`${Math.floor(p.x/40)}:${Math.floor(p.z/40)}`)||[]).every(([a,b])=>{const dx=b.x-a.x,dz=b.z-a.z,t=Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.z-a.z)*dz)/(dx*dx+dz*dz)));return Math.hypot(p.x-a.x-t*dx,p.z-a.z-t*dz)>15;});
 const safe=(p)=>{let gx=Math.floor(p.x/17),gz=Math.floor(p.z/17);for(let dx=-1;dx<=1;dx++)for(let dz=-1;dz<=1;dz++)for(const a of spatial.get(`${gx+dx}:${gz+dz}`)||[])if(distance(a,p)<19)return false;let key=`${gx}:${gz}`;if(!spatial.has(key))spatial.set(key,[]);spatial.get(key).push(p);return true;};
 for(const r of roads){let length=polyLength(r.points);for(let d=19;d<length-19;d+=23){let t=d/length,at=onPath(r.points,t);for(const side of [-1,1]){let offset=19+random()*2.5;let p={x:at.x-Math.sin(at.angle)*offset*side,z:at.z+Math.cos(at.angle)*offset*side};if(offRoad(p)&&safe(p))lots.push({...p,angle:at.angle,side,roadId:r.id,t,front:{x:at.x,z:at.z},rank:random()});}}}
 return lots.sort((a,b)=>a.rank-b.rank);
}
function expandDistricts(source,count){
 const tiles=Math.ceil(count/1400);if(tiles===1)return {...source,districtTiles:1};
 const cols=Math.ceil(Math.sqrt(tiles)),rows=Math.ceil(tiles/cols),xs=source.nodes.map(n=>n.x),zs=source.nodes.map(n=>n.z),w=Math.max(...xs)-Math.min(...xs)+100,d=Math.max(...zs)-Math.min(...zs)+100,nodes=[],roads=[],tileNodes=[];
 for(let k=0;k<tiles;k++){let ox=(k%cols-(cols-1)/2)*w,oz=(Math.floor(k/cols)-(rows-1)/2)*d,ns=source.nodes.map(n=>({...n,id:`D${k}-${n.id}`,x:n.x+ox,z:n.z+oz}));nodes.push(...ns);tileNodes.push(ns);roads.push(...source.roads.map(r=>({...r,id:`D${k}-${r.id}`,a:`D${k}-${r.a}`,b:`D${k}-${r.b}`,points:r.points.map(p=>({x:p.x+ox,z:p.z+oz}))})));}
 for(let k=1;k<tiles;k++){let previous=k%cols?k-1:k-cols;let aa,bb,best=Infinity;for(const a of tileNodes[previous])for(const b of tileNodes[k]){let dist=distance(a,b);if(dist<best){aa=a;bb=b;best=dist;}}roads.push({id:`connector-${k}`,a:aa.id,b:bb.id,points:[aa,bb],length:best,name:'District Link',class:'tertiary'});}
 return {...source,nodes,roads,districtTiles:tiles};
}
export function createTown(source,{seed='TOWN-042',count=480}={}){
 seed=String(seed).trim().slice(0,64);count=Number(count);if(!seed)throw Error('Enter a seed.');if(!Number.isInteger(count)||count<20||count>10000)throw Error('Choose between 20 and 10,000 homes.');
 const baseSource=source;source=expandDistricts(source,count);
 const original=source.roads.reduce((s,r)=>s+r.length,0);
 let scale=Math.max(.52,count*31/original),geo,tree,lots;
 for(let attempt=0;attempt<8;attempt++){geo={...source,nodes:source.nodes.map(n=>({...n,x:n.x*scale,z:n.z*scale})),roads:source.roads.map(r=>({...r,points:r.points.map(p=>({x:p.x*scale,z:p.z*scale})),length:r.length*scale}))};tree=roadTree(geo);lots=candidates(tree.roads,seed);if(lots.length>=count)break;scale*=Math.max(1.13,count/Math.max(1,lots.length)*1.03);}
 if(lots.length<count)throw Error('This street extract cannot fit the requested number of houses. Choose a larger area.');
 const id=`town-${hash(`${VERSION}:${seed}:${count}:${source.sourceHash}`).toString(16)}`;
 const roadMap=new Map(geo.roads.map(r=>[r.id,r]));
 const homes=lots.slice(0,count).map((p,i)=>{const hid=`P-${String(i+1).padStart(5,'0')}`,random=rng(`${seed}:home:${hid}`);return{id:hid,buildingId:`B-${hid}`,accountId:`CA-${hid}`,address:`${i+1} ${roadMap.get(p.roadId).name}`,x:round(p.x),z:round(p.z),angle:p.angle,side:p.side,roadId:p.roadId,t:p.t,front:p.front,width:8+random()*3,depth:10+random()*4,height:random()<.65?6.3:3.7,occupants:1+Math.floor(random()*5),occupied:random()>.045,solar:random()<.24,solarKW:round(4+random()*6,1),electricHeat:random()<.23,dailyKWh:round(15+random()*20,2),dailyWaterM3:round(.2+random()*.65),dailyGasM3:round(1.2+random()*4.8),roofTone:random(),billingCycle:1+Math.floor(random()*4),services:{}};});
 // Every premise has water and electricity; gas is absent on all-electric homes.
 const town={sourceSnapshot:baseSource,schemaVersion:'utility-town/1.0',generatorVersion:VERSION,id,seed,count,source:{...source,roads:undefined,nodes:undefined,scale:round(scale,6),syntheticUtilities:true,syntheticBuildings:true,coordinateSystem:'local metres; x east, z south',attribution:'Synthetic geography',license:'generated'},roads:geo.roads,premises:homes,networks:{},buildings:[],servicePoints:[],meters:[],registers:[],installations:[],accounts:[],contracts:[],tariffAssignments:[],bounds:{minX:Math.min(...geo.nodes.map(n=>n.x))-130,maxX:Math.max(...geo.nodes.map(n=>n.x))+110,minZ:Math.min(...geo.nodes.map(n=>n.z))-100,maxZ:Math.max(...geo.nodes.map(n=>n.z))+100}};
 const validFrom='2026-01-01T00:00:00Z';
 for(const h of homes){town.buildings.push({id:h.buildingId,premiseIds:[h.id],footprint:{widthM:h.width,depthM:h.depth},heightM:h.height});town.accounts.push({id:h.accountId,businessPartnerId:`BP-${h.id}`,currency:'CAD'});for(const u of UTILS){if(u==='gas'&&h.electricHeat)continue;const sp=`SP-${h.id}-${u}`,meter=`M-${h.id}-${u}`,installation=`IN-${h.id}-${u}`,contract=`C-${h.id}-${u}`;h.services[u]=sp;town.servicePoints.push({id:sp,premiseId:h.id,commodity:u,meterId:meter,installationId:installation,status:'active',validFrom,validTo:null});town.meters.push({id:meter,servicePointId:sp,technology:'AMI',manufacturer:'Synthetic',registerIds:[`${meter}-import`,...(u==='electric'&&h.solar?[`${meter}-export`]:[])],multiplier:1,registerDigits:8,installedAt:validFrom,removedAt:null});town.registers.push({id:`${meter}-import`,meterId:meter,direction:'import',unit:u==='electric'?'kWh':'m3',precision:3},...(u==='electric'&&h.solar?[{id:`${meter}-export`,meterId:meter,direction:'export',unit:'kWh',precision:3}]:[]));town.installations.push({id:installation,servicePointId:sp,premiseId:h.id,division:u,timezone:'America/Toronto',readCycle:h.billingCycle});town.contracts.push({id:contract,installationId:installation,accountId:h.accountId,validFrom,validTo:null,status:'active'});town.tariffAssignments.push({contractId:contract,tariffId:`DEMO-${u.toUpperCase()}`,validFrom,validTo:null,rates:null,status:'unconfigured'});}}
 for(const [ui,u] of UTILS.entries()){
  const nodes=[],edges=[],nodeMap=new Map();
  const addNode=(node)=>{node.x=round(node.x);node.z=round(node.z);node.elevationM=round(terrain(node.x,node.z));nodes.push(node);nodeMap.set(node.id,node);return node;};
  const addEdge=(a,b,kind,points,extra={})=>{let edge={id:`${u}-E${edges.length}`,commodity:u,from:a.id,to:b.id,kind,points:points||[{x:a.x,z:a.z},{x:b.x,z:b.z}],lengthM:round(polyLength(points||[a,b])),...extra};edges.push(edge);b.parentEdgeId=edge.id;return edge;};
  const off={x:tree.root.x-110,z:tree.root.z+(ui-1)*85},supply=addNode({id:`${u}-supply`,kind:'external_supply',label:{electric:'Regional grid · 69 kV',water:'Treated water supply',gas:'Regional gas supply'}[u],...off});
  const station=addNode({id:`${u}-station`,kind:{electric:'substation',water:'pump_station',gas:'city_gate_regulator'}[u],label:{electric:'West substation',water:'West pumping station',gas:'West pressure station'}[u],x:off.x+45,z:off.z});
  const rootNode=addNode({id:`${u}-J-${tree.root.id}`,kind:'junction',x:tree.root.x,z:tree.root.z});
  addEdge(supply,station,'supply',null,u==='electric'?{voltageKV:69,placement:'overhead'}:{diameterIn:u==='water'?16:8,placement:'underground',depthM:u==='water'?1.8:1.0});
  addEdge(station,rootNode,'trunk',null,u==='electric'?{voltageKV:12.47,placement:'overhead'}:{diameterIn:u==='water'?(count>2000?24:10):6,placement:'underground',depthM:u==='water'?1.8:1});
  const byRoad=new Map();for(const h of homes){if(!h.services[u])continue;if(!byRoad.has(h.roadId))byRoad.set(h.roadId,[]);byRoad.get(h.roadId).push(h);}
  for(const road of tree.roads){let start=nodeMap.get(`${u}-J-${road.a}`);let end=addNode({id:`${u}-J-${road.b}`,kind:road.b.startsWith('closed-')?'closed_tie':'junction',...road.points.at(-1)});const homeList=(byRoad.get(road.id)||[]).sort((a,b)=>a.t-b.t||a.id.localeCompare(b.id));let taps=[];
   if(u==='electric'){for(let i=0;i<homeList.length;i+=8){const batch=homeList.slice(i,i+8);taps.push({t:batch[Math.floor(batch.length/2)].t,homes:batch});}}
   else taps=homeList.map(h=>({t:h.t,homes:[h]}));
   let prev=start,prevT=0;
   const main={roadId:road.id,placement:u==='electric'?(hash(road.id)%3===0?'overhead':'underground'):'underground',...(u==='electric'?{voltageKV:12.47}:{diameterIn:u==='water'?(road.class==='residential'?6:count>2000?16:10):(road.class==='residential'?2:4),depthM:u==='water'?1.8:1})};
   for(let j=0;j<taps.length;j++){
    const tap=taps[j],at=onPath(road.points,tap.t),junction=addNode({id:`${u}-T-${road.id}-${j}`,kind:'junction',x:at.x,z:at.z});addEdge(prev,junction,'distribution',slicePath(road.points,prevT,tap.t),main);prev=junction;prevT=tap.t;
    let secondary=junction;
    if(u==='electric'){secondary=addNode({id:`${u}-TX-${road.id}-${j}`,kind:'transformer',label:'Neighbourhood transformer',x:at.x-Math.sin(at.angle)*8,z:at.z+Math.cos(at.angle)*8,ratingKVA:50,primaryKV:12.47,secondaryKV:.24});addEdge(junction,secondary,'transformer',null,{voltageKV:12.47,secondaryVoltageKV:.24,placement:main.placement,ratingKVA:50});}
    for(const h of tap.homes){let meterNode=addNode({id:`${u}-N-${h.id}`,kind:'meter',premiseId:h.id,servicePointId:h.services[u],x:h.x,z:h.z});let servicePath=u==='electric'?[secondary,{x:at.x,z:at.z},...slicePath(road.points,Math.min(tap.t,h.t),Math.max(tap.t,h.t)).filter((_,i)=>i>0),{x:h.front.x,z:h.front.z},meterNode]:[junction,meterNode];if(u==='electric'&&h.t<tap.t)servicePath=[secondary,...slicePath(road.points,h.t,tap.t).reverse(),meterNode];addEdge(secondary,meterNode,'service',servicePath.map(p=>({x:p.x,z:p.z})),u==='electric'?{voltageKV:.24,phase:['A','B','C'][hash(h.id)%3],placement:main.placement}:{diameterIn:.75,placement:'underground',depthM:u==='water'?1.5:.8,...(u==='gas'?{regulator:'service pressure regulator'}:{})});}
   }
   addEdge(prev,end,'distribution',slicePath(road.points,prevT,1),main);
  }
  town.networks[u]={commodity:u,sourceId:supply.id,stationId:station.id,nodes,edges,topology:'radial demonstration network',unit:u==='electric'?'kW':'m3/h',assumptions:{losses:'excluded',pressureVoltageSolution:'not solved',nominalSizing:'illustrative; not capacity validated'}};
 }
 prepareDemoNetwork(town,terrain);town.validation=validateTown(town);return town;
}
export function validateTown(town){let errors=[],seen=new Set();let totalEdges=0;for(const u of UTILS){const net=town.networks[u],ids=new Set(net.nodes.map(n=>n.id)),reached=new Set([net.sourceId]),adj=new Map();for(const e of net.edges){totalEdges++;if(!ids.has(e.from)||!ids.has(e.to))errors.push(`Dangling edge ${e.id}`);if(!adj.has(e.from))adj.set(e.from,[]);adj.get(e.from).push(e.to);if(!Number.isFinite(e.lengthM)||e.lengthM<0)errors.push(`Invalid length ${e.id}`);}let q=[net.sourceId];for(let i=0;i<q.length;i++)for(const id of adj.get(q[i])||[])if(!reached.has(id)){reached.add(id);q.push(id);}for(const n of net.nodes)if(!reached.has(n.id))errors.push(`Disconnected node ${n.id}`);for(const h of town.premises)if(h.services[u]&&!reached.has(`${u}-N-${h.id}`))errors.push(`Disconnected service ${h.id}`);if(net.edges.length!==net.nodes.length-1)errors.push(`Not a tree: ${u}`);}
 for(const collection of [town.premises,town.buildings,town.accounts,town.servicePoints,town.meters,town.registers,town.installations,town.contracts])for(const row of collection){if(seen.has(row.id))errors.push(`Duplicate id ${row.id}`);seen.add(row.id);}return {valid:errors.length===0,errors,connectedServices:town.servicePoints.length,networkEdges:totalEdges,checks:['Unique identifiers','Source reachability','All active services connected','Valid edge endpoints','Radial topology']};}
export function demand(h,hour,scenario='normal',target=null){
 const occupied=h.occupied?1:.09,solar=Math.max(0,Math.sin((hour-6)/12*Math.PI))*h.solarKW*(h.solar?1:0),morning=Math.exp(-(((hour-7.5)/2)**2)),evening=Math.exp(-(((hour-19)/3)**2));
 let load=h.dailyKWh/24*(.42+1.15*morning+1.65*evening)*occupied;
 let water=h.dailyWaterM3/24*(.22+2.0*morning+1.8*evening)*occupied;
 let gas=h.dailyGasM3/24*(.35+1.3*morning+.8*evening)*occupied;
 if(scenario==='leak'&&h.id===target)water+=.65;
 let generation=solar;
 if(scenario==='outage'){load=0;generation=0;}
 return {electric:load-generation,water,gas:h.services.gas?gas:0,loadKW:load,generationKW:generation,importKW:Math.max(0,load-generation),exportKW:Math.max(0,generation-load)};
}
const flowTopologyCache=new WeakMap();
export function flows(town,hour,scenario='normal',target=null){
 let cached=flowTopologyCache.get(town);if(!cached){cached={};for(const u of UTILS){const net=town.networks[u],index=new Map(net.nodes.map((n,i)=>[n.id,i])),adj=new Map();for(const e of net.edges){if(!adj.has(e.from))adj.set(e.from,[]);adj.get(e.from).push(e);}const q=[net.sourceId],ordered=[];for(let i=0;i<q.length;i++)for(const e of adj.get(q[i])||[]){ordered.push({e,a:index.get(e.from),b:index.get(e.to)});q.push(e.to);}cached[u]={ordered,index,source:index.get(net.sourceId)};}flowTopologyCache.set(town,cached);}
 const result={},values=new Map(town.premises.map(h=>[h.id,demand(h,hour,scenario,target)]));
 for(const u of UTILS){const net=town.networks[u],c=cached[u],totals=new Float64Array(net.nodes.length);net.nodes.forEach((n,i)=>{if(n.premiseId)totals[i]=values.get(n.premiseId)[u];});const edgeFlows=new Map();for(let i=c.ordered.length-1;i>=0;i--){const {e,a,b}=c.ordered[i],v=totals[b];edgeFlows.set(e.id,v);totals[a]+=v;}result[u]={source:totals[c.source],edgeFlows,unit:net.unit};}result.homes=values;return result;
}
export function traceService(town,premiseId,utility){const net=town.networks[utility],edges=new Map(net.edges.map(e=>[e.to,e])),path=[];let node=`${utility}-N-${premiseId}`;while(edges.has(node)){let e=edges.get(node);path.push(e);node=e.from;if(path.length>net.edges.length)throw Error('Invalid network cycle');}return path.reverse();}
export function monthlyReads(town,h,month=6){ // month=6 means June -> July; observed reads are separately editable fixtures.
 const out=[];for(const u of UTILS){if(!h.services[u])continue;for(const direction of u==='electric'&&h.solar?['import','export']:['import']){
 const unit=u==='electric'?'kWh':'m3',meterId=`M-${h.id}-${u}`,reg=`${meterId}-${direction}`,base=1000+hash(reg+town.seed)%50000;
 let prior=base,consumption=0;
 for(let m=1;m<=month;m++){let dayTotal=0;for(let hour=0;hour<24;hour++){const d=demand(h,hour+.5);dayTotal+=u==='electric'?(direction==='import'?d.importKW:d.exportKW):d[u];}let days=new Date(Date.UTC(2026,m,0)).getUTCDate();let seasonal=u==='gas'?1+.7*Math.cos((m-1)/12*Math.PI*2):u==='water'?1+.1*Math.sin((m-3)/12*Math.PI*2):1;const volume=round(dayTotal*days*seasonal);if(m<month)prior+=volume;else consumption=volume;}
 const from=new Date(Date.UTC(2026,month-1,1)).toISOString(),to=new Date(Date.UTC(2026,month,1)).toISOString();prior=round(prior);const value=round(prior+consumption);
 out.push({id:`READ-${town.id}-${reg}-${to.slice(0,10)}`,schemaVersion:'meter-read/1.0',simulationId:town.id,premiseId:h.id,servicePointId:h.services[u],installationId:`IN-${h.id}-${u}`,meterId,registerId:reg,contractId:`C-${h.id}-${u}`,accountId:h.accountId,commodity:u,direction,unit,periodStart:from,periodEnd:to,readAt:to,previousReadAt:from,previousRegisterValue:prior,registerValue:value,consumption:round(value-prior),multiplier:1,readType:'actual',readStatus:'received',source:'synthetic-AMI',reasonCode:null,consecutiveEstimates:0,occupied:h.occupied,moveInAt:null,moveOutAt:null,sapValidationCode:null,veeStatus:'not_processed',billingDocumentId:null,invoiceId:null,truth:{registerValue:value,consumption:round(value-prior)},idempotencyKey:`${town.id}:${reg}:${to}`});}}
 return out;
}
export function exportTown(town){return {...town,simulation:{timezone:'America/Toronto',epoch:'2026-07-15T04:00:00Z',tickSeconds:300,physics:'mass/energy balance without pressure, voltage, losses or transients'},sampleReads:town.premises.flatMap(h=>monthlyReads(town,h)),billingDocuments:[],invoices:[],handoff:{version:'1.0',status:'fixtures_only',vee:'Not connected',billing:'Not connected',invoice:'Not connected',pendingConfiguration:['Rate schedules','Proration','Taxes','Net-metering settlement','Billing calendar','Gas energy conversion','SAP VEE code mapping']}};}
