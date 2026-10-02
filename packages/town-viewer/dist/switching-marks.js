// Switching during a repair, read from the engine timeline (nothing is decided here):
// - a water or gas section isolation: the valves the crew closed (`section.isolated` valveIds, closedEdgeIds), from
//   the isolation until the service is restored;
// - an electric back-feed: each normally-open tie closed for it (`incidents[].ties`, or the older single `tie`), from
//   closedAt until openedAt;
// - the sectionalising switches the crew opened to bound the faulted section (`switch.opened` until `switch.closed`,
//   else `incidents[].isolation` from the isolation until restoration);
// - the protective device that tripped (`protection.operated`): open until the crew re-closes it once the faulted
//   section is isolated (`fault.isolated`), or until restoration when the fault sits on the device's own span or the
//   engine says it was not re-closed (`reclosedDeviceEdgeId: null`, `isolation.deviceReclosed: false`).
// On the map, the switched edges are redrawn in a state colour and a ring marks each switched device, with its
// utility layer. Device positions come from the engine's equipment entries (a recloser by its node's parent edge).
import * as THREE from './vendor/three.module.js';
import {EdgeOverlay} from './edge-overlay.js';
import {zoomStep} from './lens-marks.js';
export const SWITCH_COLORS={valve:'#d24b3f',tie:'#2f7fd8',device:'#f08c2e',switch:'#c2378a'};
const UTILS=['electric','water','gas'],until=v=>v==null?Infinity:v,TRACKED=new Set(['protection.operated','fault.isolated','section.isolated']);
// The timeline's switching as time intervals [from, to).
export function switchingIntervals({incidents=[],events=[]}={}){
 const byIncident=new Map(),switches=new Map();for(const e of events||[]){const id=e.correlationId??e.payload?.incidentId;if(e.eventType==='switch.opened'||e.eventType==='switch.closed'){if(!switches.has(id))switches.set(id,[]);switches.get(id).push(e);continue;}if(!TRACKED.has(e.eventType))continue;if(!byIncident.has(id))byIncident.set(id,{});const seen=byIncident.get(id);seen[e.eventType]??=e;}
 const out=[];
 for(const i of incidents||[]){const ev=byIncident.get(i.id)||{},restored=until(i.restoredAt),trip=ev['protection.operated'],edgeId=trip?.payload?.edgeId??i.device?.edgeId,kind=trip?.payload?.kind??i.device?.kind;
  const iso=ev['fault.isolated'],stays=edgeId===i.edgeId||iso?.payload?.reclosedDeviceEdgeId===null||i.isolation?.deviceReclosed===false;
  if(edgeId&&kind&&kind!=='conductor')out.push({type:'device',incidentId:i.id,utility:'electric',edgeId,kind,from:trip?.at??i.createdAt,to:stays?restored:until(iso?.at??i.isolatedAt??restored)});
  const sw=switches.get(i.id);if(sw?.length){const open=new Map();for(const e of [...sw].sort((a,b)=>a.at-b.at)){const q=e.payload||{},k=q.edgeId;if(e.eventType==='switch.opened')open.set(k,{type:'switch',incidentId:i.id,utility:'electric',id:q.id,edgeId:k,kind:q.kind,from:e.at,to:restored});else if(open.has(k)){out.push({...open.get(k),to:e.at});open.delete(k);}}out.push(...open.values());}
  else if(i.isolation?.method==='switches'&&i.isolatedAt!=null)for(const q of [i.isolation.upstream,...(i.isolation.downstream||[])])if(q?.edgeId)out.push({type:'switch',incidentId:i.id,utility:'electric',id:q.id,edgeId:q.edgeId,kind:q.kind,from:i.isolatedAt,to:restored});
  const section=ev['section.isolated'];if(section)out.push({type:'isolation',incidentId:i.id,utility:i.utility,valveIds:section.payload?.valveIds||[],edgeIds:section.payload?.closedEdgeIds||[],from:section.at,to:restored});
  for(const tie of i.ties?.length?i.ties:i.tie?[i.tie]:[])if(tie?.edgeId)out.push({type:'tie',incidentId:i.id,utility:'electric',edgeId:tie.edgeId,from:tie.closedAt,to:until(tie.openedAt)});}
 return out;}
// What is switched at time t (seconds since midnight of the run day), with a key that changes only when it does.
export function switchingAt(intervals,t){const s={devices:[],valves:[],edges:[],ties:[],switches:[],key:''};
 for(const iv of intervals||[]){if(!(t>=iv.from&&t<iv.to))continue;if(iv.type==='device')s.devices.push({edgeId:iv.edgeId,kind:iv.kind,incidentId:iv.incidentId});else if(iv.type==='switch')s.switches.push({id:iv.id,edgeId:iv.edgeId,kind:iv.kind,incidentId:iv.incidentId});else if(iv.type==='tie')s.ties.push({edgeId:iv.edgeId,incidentId:iv.incidentId});else{for(const id of iv.valveIds)s.valves.push({id,utility:iv.utility,incidentId:iv.incidentId});for(const edgeId of iv.edgeIds)s.edges.push({utility:iv.utility,edgeId});}}
 s.key=[...s.devices.map(d=>'d:'+d.edgeId),...s.valves.map(v=>'v:'+v.id),...s.edges.map(e=>'e:'+e.utility+':'+e.edgeId),...s.ties.map(x=>'t:'+x.edgeId),...s.switches.map(x=>'w:'+x.edgeId)].join(',');return s;}
// Legend rows for what is switched now.
export function switchingRows(s){const rows=[];if(s?.valves.length||s?.edges.length)rows.push({color:SWITCH_COLORS.valve,label:'valve closed · section isolated',shape:'ring',count:s.valves.length});
 if(s?.ties.length)rows.push({color:SWITCH_COLORS.tie,label:'tie closed · back-feed',shape:'line',count:s.ties.length});if(s?.devices.length)rows.push({color:SWITCH_COLORS.device,label:`${s.devices.every(d=>d.kind==='fuse')?'fuse':s.devices.every(d=>d.kind==='recloser')?'recloser':'protective device'} open · tripped`,shape:'ring',count:s.devices.length});if(s?.switches?.length)rows.push({color:SWITCH_COLORS.switch,label:'switch open · section isolated',shape:'ring',count:s.switches.length});return rows;}
export class SwitchingMarks{
 constructor(root,town,pathData,heightAt){this.heightAt=heightAt;this.overlay=new EdgeOverlay(root,pathData,{radius:1.9,renderOrder:5});this.layers={electric:true};this.intervals=[];this.source=null;this.state=switchingAt([],0);this.key=null;
  this.at=new Map();for(const u of UTILS){const net=town.networks?.[u],nodes=new Map((net?.nodes||[]).map(n=>[n.id,n]));for(const q of net?.equipment||[]){if(!Number.isFinite(q.x)||!Number.isFinite(q.z))continue;if(u==='electric'?!['fuse','recloser','tie_switch','sectionalising_switch'].includes(q.kind):q.kind!=='valve')continue;if(q.id)this.at.set(u+':id:'+q.id,q);const edge=q.edgeId??nodes.get(q.nodeId)?.parentEdgeId;if(edge&&!this.at.has(u+':edge:'+edge))this.at.set(u+':edge:'+edge,q);}}
  this.rings=new THREE.InstancedMesh(new THREE.RingGeometry(3.4,4.8,28),new THREE.MeshBasicMaterial({transparent:true,opacity:.95,side:THREE.DoubleSide,depthTest:false,toneMapped:false}),Math.max(16,this.at.size));this.rings.count=0;this.rings.frustumCulled=false;this.rings.renderOrder=5;root.add(this.rings);this.dummy=new THREE.Object3D();this.color=new THREE.Color();this.ringCount=0;}
 // A switched edge's ring: its equipment entry when the engine lists one, else the middle of the edge.
 spot(u,edgeId){const q=this.at.get(u+':edge:'+edgeId);if(q)return q;const p=this.overlay.piecesOf(u,edgeId);if(!p.length)return null;const s=p[Math.floor(p.length/2)];return {x:(s.a.x+s.b.x)/2,z:(s.a.z+s.b.z)/2};}
 update(ops){if(!ops)return;const source=ops.incidents;if(source!==this.source||source?.length!==this.sourceLength||ops.events!==this.sourceEvents){this.source=source;this.sourceLength=source?.length;this.sourceEvents=ops.events;this.intervals=switchingIntervals(ops);}this.state=switchingAt(this.intervals,ops.time);this.draw();}
 setLayers(layers){this.layers={...layers};this.draw();}
 draw(){const s=this.state,L=this.layers,key=s.key+'|'+UTILS.map(u=>L[u]?1:0).join('');if(key===this.key)return;this.key=key;const edges=[],rings=[];
  for(const e of s.edges)if(L[e.utility])edges.push([e.utility,e.edgeId,SWITCH_COLORS.valve]);
  for(const v of s.valves){const q=L[v.utility]&&this.at.get(v.utility+':id:'+v.id);if(q)rings.push([q,SWITCH_COLORS.valve]);}
  if(L.electric){for(const [list,color] of [[s.ties,SWITCH_COLORS.tie],[s.devices,SWITCH_COLORS.device],[s.switches||[],SWITCH_COLORS.switch]])for(const x of list){edges.push(['electric',x.edgeId,color]);const p=(x.id&&this.at.get('electric:id:'+x.id))||this.spot('electric',x.edgeId);if(p)rings.push([p,color]);}}
  this.overlay.set(edges);this.spots=rings.slice(0,this.rings.instanceMatrix.count);this.spots.forEach(([,c],i)=>this.rings.setColorAt(i,this.color.set(c)));this.rings.count=this.ringCount=this.spots.length;if(this.rings.instanceColor)this.rings.instanceColor.needsUpdate=true;this.place();}
 zoom(distance){this.overlay.zoom(distance);const k=zoomStep(distance);if(k===this.scale)return;this.scale=k;this.place();}
 place(){const d=this.dummy,k=this.scale||1;(this.spots||[]).forEach(([p],i)=>{d.position.set(p.x,this.heightAt(p.x,p.z)+.45,p.z);d.rotation.set(-Math.PI/2,0,0);d.scale.setScalar(k);d.updateMatrix();this.rings.setMatrixAt(i,d.matrix);});this.rings.instanceMatrix.needsUpdate=true;}
}
