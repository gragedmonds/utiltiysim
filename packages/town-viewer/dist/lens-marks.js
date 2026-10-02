// Map lenses: one analytic view at a time over the map (Network, Voltage, Pressure, Cases). Each paints a flat disc
// under every premise in a class colour, and Voltage also rings transformers by loading. Colours and thresholds live
// here; the values come from the engine's frames (voltage, pressure, loading) and the meter-to-cash summary.
import * as THREE from './vendor/three.module.js';

export const LENSES=[['network','Network'],['voltage','Voltage'],['pressure','Pressure'],['cases','Cases']];
export const DEFAULT_THRESHOLDS={vLow:114,vHigh:126,vWarnLow:117,vWarnHigh:124,waterMin:275,waterHigh:550,gasLow:1.0,txHot:1.0,txWarm:0.8,lineHot:1.0,lineWarm:0.8};
// The thresholds in force: one place to override them (Configuration may bind these); listeners redraw the map.
let current={...DEFAULT_THRESHOLDS};const watchers=new Set();
export function setLensThresholds(overrides){current={...DEFAULT_THRESHOLDS,...(overrides||{})};for(const f of watchers)f(current);return current;}
export function lensThresholds(){return current;}
export function onLensThresholds(f){watchers.add(f);return ()=>watchers.delete(f);}
const C={bad:'#d24b3f',warn:'#e2a43a',ok:'#4f9d5d',high:'#3f7fd0',mp:'#8a6fd1',none:'#9fb1bd'};
export const CASE_COLORS=['#4f9d5d','#3f7fd0','#e2a43a','#d24b3f','#8a5cc7']; // clean, estimated, open case, escalated, field order

// The class colour of one premise's value under a lens (null: draw nothing).
export function lensColor(lens,value,t=current,utility='water'){
 if(value==null||Number.isNaN(value))return null;
 if(lens==='voltage')return value<t.vLow||value>t.vHigh?C.bad:value<t.vWarnLow||value>t.vWarnHigh?C.warn:C.ok;
 if(lens==='pressure'){if(utility==='gas')return value>=50?C.mp:value<t.gasLow?C.bad:value<1.5?C.warn:C.ok;return value<t.waterMin?C.bad:value>t.waterHigh?C.high:value<t.waterMin+70?C.warn:C.ok;}
 if(lens==='cases')return CASE_COLORS[value]??null;
 return null;
}
export function loadingColor(loading,t=current){return loading==null?null:loading>t.txHot?C.bad:loading>t.txWarm?C.warn:null;}
export function lensLegend(lens,t=current,utility='water',caseLegend=['clean','estimated','open case','escalated','field order']){
 if(lens==='voltage')return [[C.ok,`${t.vWarnLow}–${t.vWarnHigh} V`],[C.warn,`${t.vLow}–${t.vWarnLow} or ${t.vWarnHigh}–${t.vHigh} V`],[C.bad,`outside ${t.vLow}–${t.vHigh} V (ANSI A)`],[C.warn,'transformer > '+Math.round(t.txWarm*100)+'%','ring'],[C.bad,'transformer > '+Math.round(t.txHot*100)+'%','ring']];
 if(lens==='pressure')return utility==='gas'?[[C.ok,'1.5–1.74 kPa (7" w.c.)'],[C.warn,`${t.gasLow}–1.5 kPa`],[C.bad,`below ${t.gasLow} kPa`],[C.mp,'medium-pressure service']]:[[C.ok,`${t.waterMin+70}–${t.waterHigh} kPa`],[C.warn,`${t.waterMin}–${t.waterMin+70} kPa`],[C.bad,`below ${t.waterMin} kPa (40 psi)`],[C.high,`above ${t.waterHigh} kPa`]];
 if(lens==='cases')return caseLegend.map((label,i)=>[CASE_COLORS[i],label]);
 return [];
}
// Counts per legend colour, for the legend panel.
export function tally(colors){const n={};for(const c of colors)if(c)n[c]=(n[c]||0)+1;return n;}
// Lines by loading: amber above lineWarm (with the Voltage lens only), red above lineHot (always: overloads stay visible).
export function lineColor(loading,warm=true,t=current){return loading==null?null:loading>t.lineHot?C.bad:warm&&loading>t.lineWarm?C.warn:null;}
// Per town, once: transformers (the node at the transformer end of each transformer edge) and the line edges that
// can show loading (supply, trunk and distribution; not transformer drops or services).
const INDEX=new WeakMap();
export function lensIndex(town){let ix=INDEX.get(town);if(ix)return ix;const net=town?.networks?.electric,nodes=new Map((net?.nodes||[]).map(n=>[n.id,n])),transformers=[],lineEdges=[];
 for(const e of net?.edges||[]){if(e.kind==='transformer'){const n=[nodes.get(e.to),nodes.get(e.from)].find(n=>n?.kind==='transformer');if(n)transformers.push({id:n.id,edgeId:e.id,x:n.x,z:n.z,ratingKVA:e.ratingKVA??null});}else if(e.kind!=='service')lineEdges.push(e.id);}
 ix={transformers,lineEdges};INDEX.set(town,ix);return ix;}
// What a lens paints for one frame (pure): premise discs [id, colour], transformer rings {id, x, z, color}, loaded
// line edges [edgeId, colour], and the counts per colour for the legend. `available` is false when the frame lacks
// the lens's data (no engine, or the engine did not send it).
export function buildLens(lens,{flow=null,utility='electric',summary=null,index={transformers:[],lineEdges:[]},t=current}={}){
 const out={lens,entries:[],assets:[],lines:[],counts:{},ringCounts:{},lineCounts:{},available:true,utility:null};
 if(lens==='voltage'){if(!flow?.voltage)out.available=false;else{for(const [id,v] of flow.voltage){const c=lensColor('voltage',v,t);if(c)out.entries.push([id,c]);}if(flow.loading)for(const tx of index.transformers){const c=loadingColor(flow.loading.get(tx.edgeId),t);if(c)out.assets.push({id:tx.id,x:tx.x,z:tx.z,color:c});}}}
 else if(lens==='pressure'){const u=utility==='gas'?'gas':'water',m=flow?.pressure?.[u];out.utility=u;if(!m)out.available=false;else for(const [id,v] of m){const c=lensColor('pressure',v,t,u);if(c)out.entries.push([id,c]);}}
 else if(lens==='cases'){const p=summary?.premises;if(!p?.ids)out.available=false;else p.ids.forEach((id,i)=>{const c=lensColor('cases',p.status[i],t);if(c)out.entries.push([id,c]);});}
 if(flow?.loading)for(const id of index.lineEdges){const c=lineColor(flow.loading.get(id),lens==='voltage',t);if(c)out.lines.push([id,c]);}
 out.counts=tally(out.entries.map(e=>e[1]));out.ringCounts=tally(out.assets.map(a=>a.color));out.lineCounts=tally(out.lines.map(l=>l[1]));return out;}
// Legend rows [{color, label, shape: 'disc'|'ring'|'line', count}] for a built lens; overloaded lines show with any lens.
export function legendRows(built,{t=current,caseLegend}={}){const lens=built.lens,rows=(built.available?lensLegend(lens,t,built.utility||'water',caseLegend):[]).map(([color,label,shape='disc'])=>({color,label,shape,count:(shape==='ring'?built.ringCounts:built.counts)[color]||0}));
 if(lens==='voltage'&&built.available)rows.push({color:C.warn,label:`line > ${Math.round(t.lineWarm*100)}% loaded`,shape:'line',count:built.lineCounts[C.warn]||0});
 if(lens==='voltage'&&built.available||built.lineCounts[C.bad])rows.push({color:C.bad,label:`line > ${Math.round(t.lineHot*100)}% (overloaded)`,shape:'line',count:built.lineCounts[C.bad]||0});
 return rows;}

// Map marks scale by camera distance in half steps, 1× up close to 6× at town zoom.
export function zoomStep(distance){return Math.min(6,Math.max(1,Math.round((distance||0)/150)/2));}
export class LensMarks{
 constructor(root,town,heightAt){
  this.heightAt=heightAt;this.index=new Map(town.premises.map(h=>[h.id,h]));const cap=Math.max(1,town.premises.length);
  const material=()=>new THREE.MeshBasicMaterial({transparent:true,opacity:.88,side:THREE.DoubleSide,depthTest:false,toneMapped:false});
  this.discs=new THREE.InstancedMesh(new THREE.CircleGeometry(1.9,10),material(),cap);this.rings=new THREE.InstancedMesh(new THREE.RingGeometry(3.2,4.3,24),material(),Math.max(512,(town.networks?.electric?.nodes||[]).filter(n=>n.kind==='transformer').length));
  for(const m of [this.discs,this.rings]){m.count=0;m.frustumCulled=false;m.renderOrder=2;root.add(m);}this.dummy=new THREE.Object3D();this.color=new THREE.Color();
 }
 // entries: [premiseId, colour]; assets: {x, z, color}
 set(entries=[],assets=[]){const P=this.points={discs:[],rings:[]};let n=0;
  for(const [id,color] of entries){if(!color||n>=this.discs.instanceMatrix.count)continue;const h=this.index.get(id);if(!h)continue;const p=h.front||h;P.discs.push(p.x,this.heightAt(p.x,p.z)+.26,p.z);this.discs.setColorAt(n++,this.color.set(color));}
  let k=0;for(const a of assets){if(!a.color||k>=this.rings.instanceMatrix.count)continue;P.rings.push(a.x,this.heightAt(a.x,a.z)+.4,a.z);this.rings.setColorAt(k++,this.color.set(a.color));}
  for(const [m,c] of [[this.discs,n],[this.rings,k]]){m.count=c;if(m.instanceColor)m.instanceColor.needsUpdate=true;}
  this.count=n;this.assetCount=k;this.place();
 }
 // Marks grow with distance so a lens still reads at town zoom (re-placed only when the zoom step changes).
 zoom(distance){const k=zoomStep(distance);if(k===this.scale)return;this.scale=k;this.place();}
 place(){const d=this.dummy,k=this.scale||1;for(const [m,pts] of [[this.discs,this.points?.discs||[]],[this.rings,this.points?.rings||[]]]){for(let i=0;i<pts.length/3;i++){d.position.set(pts[i*3],pts[i*3+1],pts[i*3+2]);d.rotation.set(-Math.PI/2,0,0);d.scale.setScalar(k);d.updateMatrix();m.setMatrixAt(i,d.matrix);}m.instanceMatrix.needsUpdate=true;}}
 clear(){this.set([],[]);}
}
