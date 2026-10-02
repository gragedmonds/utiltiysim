// Map lenses: one analytic view at a time over the map (Network, Voltage, Pressure, Cases). Each paints a flat disc
// under every premise in a class colour, and Voltage also rings transformers by loading. Colours and thresholds live
// here; the values come from the engine's frames (voltage, pressure, loading) and the meter-to-cash summary.
import * as THREE from './vendor/three.module.js';

export const LENSES=[['network','Network'],['voltage','Voltage'],['pressure','Pressure'],['cases','Cases']];
export const DEFAULT_THRESHOLDS={vLow:114,vHigh:126,vWarnLow:117,vWarnHigh:124,waterMin:275,waterHigh:550,gasLow:1.0,txHot:1.0,txWarm:0.8};
const C={bad:'#d24b3f',warn:'#e2a43a',ok:'#4f9d5d',high:'#3f7fd0',mp:'#8a6fd1',none:'#9fb1bd'};
export const CASE_COLORS=['#4f9d5d','#3f7fd0','#e2a43a','#d24b3f','#8a5cc7']; // clean, estimated, open case, escalated, field order

// The class colour of one premise's value under a lens (null: draw nothing).
export function lensColor(lens,value,t=DEFAULT_THRESHOLDS,utility='water'){
 if(value==null||Number.isNaN(value))return null;
 if(lens==='voltage')return value<t.vLow||value>t.vHigh?C.bad:value<t.vWarnLow||value>t.vWarnHigh?C.warn:C.ok;
 if(lens==='pressure'){if(utility==='gas')return value>=50?C.mp:value<t.gasLow?C.bad:value<1.5?C.warn:C.ok;return value<t.waterMin?C.bad:value>t.waterHigh?C.high:value<t.waterMin+70?C.warn:C.ok;}
 if(lens==='cases')return CASE_COLORS[value]??null;
 return null;
}
export function loadingColor(loading,t=DEFAULT_THRESHOLDS){return loading==null?null:loading>t.txHot?C.bad:loading>t.txWarm?C.warn:null;}
export function lensLegend(lens,t=DEFAULT_THRESHOLDS,utility='water',caseLegend=['clean','estimated','open case','escalated','field order']){
 if(lens==='voltage')return [[C.ok,`${t.vWarnLow}–${t.vWarnHigh} V`],[C.warn,`${t.vLow}–${t.vWarnLow} or ${t.vWarnHigh}–${t.vHigh} V`],[C.bad,`outside ${t.vLow}–${t.vHigh} V (ANSI A)`],[C.warn,'transformer > '+Math.round(t.txWarm*100)+'%','ring'],[C.bad,'transformer > '+Math.round(t.txHot*100)+'%','ring']];
 if(lens==='pressure')return utility==='gas'?[[C.ok,'1.5–1.74 kPa (7" w.c.)'],[C.warn,`${t.gasLow}–1.5 kPa`],[C.bad,`below ${t.gasLow} kPa`],[C.mp,'medium-pressure service']]:[[C.ok,`${t.waterMin+70}–${t.waterHigh} kPa`],[C.warn,`${t.waterMin}–${t.waterMin+70} kPa`],[C.bad,`below ${t.waterMin} kPa (40 psi)`],[C.high,`above ${t.waterHigh} kPa`]];
 if(lens==='cases')return caseLegend.map((label,i)=>[CASE_COLORS[i],label]);
 return [];
}
// Counts per legend colour, for the legend panel.
export function tally(colors){const n={};for(const c of colors)if(c)n[c]=(n[c]||0)+1;return n;}

export class LensMarks{
 constructor(root,town,heightAt){
  this.heightAt=heightAt;this.index=new Map(town.premises.map(h=>[h.id,h]));const cap=Math.max(1,town.premises.length);
  const material=()=>new THREE.MeshBasicMaterial({transparent:true,opacity:.88,side:THREE.DoubleSide,depthTest:false,toneMapped:false});
  this.discs=new THREE.InstancedMesh(new THREE.CircleGeometry(1.9,16),material(),cap);this.rings=new THREE.InstancedMesh(new THREE.RingGeometry(3.2,4.3,24),material(),512);
  for(const m of [this.discs,this.rings]){m.count=0;m.frustumCulled=false;m.renderOrder=2;root.add(m);}this.dummy=new THREE.Object3D();this.color=new THREE.Color();
 }
 // entries: [premiseId, colour]; assets: {x, z, color}
 set(entries=[],assets=[]){const d=this.dummy;let n=0;
  for(const [id,color] of entries){if(!color||n>=this.discs.instanceMatrix.count)continue;const h=this.index.get(id);if(!h)continue;const p=h.front||h;d.position.set(p.x,this.heightAt(p.x,p.z)+.26,p.z);d.rotation.set(-Math.PI/2,0,0);d.scale.setScalar(1);d.updateMatrix();this.discs.setMatrixAt(n,d.matrix);this.discs.setColorAt(n++,this.color.set(color));}
  let k=0;for(const a of assets){if(!a.color||k>=this.rings.instanceMatrix.count)continue;d.position.set(a.x,this.heightAt(a.x,a.z)+.4,a.z);d.rotation.set(-Math.PI/2,0,0);d.scale.setScalar(1);d.updateMatrix();this.rings.setMatrixAt(k,d.matrix);this.rings.setColorAt(k++,this.color.set(a.color));}
  for(const [m,c] of [[this.discs,n],[this.rings,k]]){m.count=c;m.instanceMatrix.needsUpdate=true;if(m.instanceColor)m.instanceColor.needsUpdate=true;}
  this.count=n;this.assetCount=k;
 }
 clear(){this.set([],[]);}
}
