// The map's lens control (top right, under the clock): Network (no lens), Voltage, Pressure and Cases, one at a time,
// remembered in this browser. A lens paints premise classes from the engine's frame (meter-to-cash status for Cases)
// with a legend that counts each class, and redraws on every new frame, time scrub, layer and lens change (the scene
// reports frames and layers through onViewChange). Lenses that need the engine are disabled without one. Overloaded
// lines and the switching of a repair in progress (switching-marks.js) add their rows to the same legend.
import {LENSES,buildLens,legendRows,lensIndex,lensThresholds,onLensThresholds,setLensThresholds} from './lens-marks.js';
import {switchingIntervals,switchingAt,switchingRows} from './switching-marks.js';
const KEY='utility-town-lens';
const NEEDS={voltage:'Needs the live engine: service voltage and loading come from its power flow.',pressure:'Needs the live engine: service pressure comes from its hydraulics.',cases:'Needs the live engine: premise status comes from its meter-to-cash run.'};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const count=n=>Number(n||0).toLocaleString('en-CA');
// The meter-to-cash run a summary belongs to (town, view date, actions, settings, the map's outages).
export function m2cRunKey(m){return m?[m.townId,m.asOf,m.actions?.length||0,JSON.stringify(m.settings||null),m.outageKey?.()||''].join('|'):null;}
export function frameClock(frame){const c=frame?.clock,at=c?.simTime||frame?.simTime;if(!at)return null;try{return new Intl.DateTimeFormat('en-GB',{timeZone:c?.timezone||'America/Toronto',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(at));}catch{return null;}}
// getContext() → {town, flow, utility, m2c, ops, engine, frame}
export function installMapLens({scene,getContext,panel=globalThis.document?.getElementById('lens-panel'),storage=globalThis.localStorage}){
 if(!panel||!scene)return null;
 let chosen='network';try{chosen=storage?.getItem(KEY)||'network';}catch{}if(!LENSES.some(([id])=>id===chosen))chosen='network';
 const tabs=panel.querySelector('.lens-tabs'),legend=panel.querySelector('.lens-legend');tabs.replaceChildren();
 const buttons=LENSES.map(([id,label])=>{const b=document.createElement('button');b.type='button';b.dataset.lens=id;b.textContent=label;b.onclick=()=>{if(b.disabled)return;if(b.getAttribute('aria-pressed')==='true'){panel.classList.toggle('lens-collapsed');return;}panel.classList.remove('lens-collapsed');chosen=id;try{storage?.setItem(KEY,id);}catch{}refresh(true);};tabs.append(b);return b;});
 let summary=null,summaryKey=null,pending=null,failed=null,failure='',queued=false,last=null,source=null,intervals=[],built=null;
 const available=(id,c)=>id==='network'||(id==='cases'?!!c.m2c:!!c.engine||(id==='voltage'?!!c.flow?.voltage:!!c.flow?.pressure));
 function ensureSummary(c){const key=m2cRunKey(c.m2c);if(!key||key===summaryKey||key===pending||key===failed)return;pending=key;
  c.m2c.summary().then(s=>{if(pending!==key)return;pending=null;summary=s;summaryKey=key;refresh(true);}).catch(e=>{if(pending!==key)return;pending=null;if(e.superseded){setTimeout(()=>refresh(true),400);return;}failed=key;failure=e.message;refresh(true);});}
 function switching(c){const ops=c.ops;if(!ops?.engine)return null;if(ops.incidents!==source){source=ops.incidents;intervals=switchingIntervals(ops);}return switchingAt(intervals,ops.time);}
 function note(lens,c){const at=frameClock(c.frame),frame=at?` · engine frame ${at}`:'';
  if(lens==='voltage')return built.available?`Service voltage, 120 V base · loading of transformers and lines${frame}`:'Waiting for the engine\'s next frame…';
  if(lens==='pressure')return built.available?`${built.utility==='gas'?'Gas':'Water'} service pressure, kPa gauge${frame}`:'Waiting for the engine\'s next frame…';
  if(lens==='cases'){const key=m2cRunKey(c.m2c);if(failed===key)return 'Meter-to-cash: '+failure;if(!built.available)return 'Loading the meter-to-cash run…';return `Meter-to-cash status · as of ${summary?.asOf||c.m2c?.asOf||'the run\'s last day'}${pending?' · updating…':''}`;}
  return '';}
 // The town's service-voltage limits come with every engine frame (electric.voltage_min_pu/max_pu × 120 V).
 function syncVoltageLimits(frame){const v=frame?.premises?.voltageLimits,t=lensThresholds();if(!v||!Number.isFinite(v.min)||!Number.isFinite(v.max)||(t.vLow===v.min&&t.vHigh===v.max))return;setLensThresholds({...t,vLow:v.min,vHigh:v.max,vWarnLow:v.min+3,vWarnHigh:v.max-2});}
 function refresh(force=false){queued=false;const c=getContext?.();if(!c?.town)return;syncVoltageLimits(c.frame);const lens=available(chosen,c)?chosen:'network';if(lens==='cases')ensureSummary(c);
  const sw=switching(c),t=lensThresholds(),key=[c.town.id,lens,c.utility,summaryKey,pending,failed,sw?.key||''].join('|');if(!force&&last&&last.key===key&&last.flow===c.flow&&last.frame===c.frame)return;last={key,flow:c.flow,frame:c.frame};
  const own=summaryKey&&summaryKey.startsWith(c.town.id+'|')?summary:null;built=buildLens(lens,{flow:c.flow,utility:c.utility,summary:lens==='cases'?own:null,index:lensIndex(c.town),t});scene.setLens(built);
  for(const b of buttons){const id=b.dataset.lens,ok=available(id,c);b.disabled=!ok;b.title=!ok?NEEDS[id]:id===lens&&id!=='network'?'Click again to hide or show the legend':'';b.setAttribute('aria-pressed',String(id===lens));}
  const rows=[...legendRows(built,{t,caseLegend:own?.premises?.legend}),...switchingRows(sw)],text=note(lens,c);
  legend.innerHTML=rows.map(r=>`<div class="lens-row"><span class="lens-swatch ${r.shape}" style="${r.shape==='ring'?'color':'background'}:${r.color}"></span><span>${esc(r.label)}</span><span class="lens-count">${count(r.count)}</span></div>`).join('')+(text?`<div class="lens-note">${esc(text)}</div>`:'');}
 scene.onViewChange=()=>{if(queued)return;queued=true;queueMicrotask(()=>refresh());};
 onLensThresholds(()=>refresh(true));
 // The meter-to-cash run can change away from the map (Configuration, Workspace actions, outages): check for it.
 setInterval(()=>{if(globalThis.document?.hidden||chosen!=='cases')return;const c=getContext?.();const key=m2cRunKey(c?.m2c);if(key&&key!==summaryKey&&key!==pending&&key!==failed)refresh();},1500);
 panel.hidden=false;refresh(true);
 const api={refresh,get lens(){return last?.key.split('|')[1]||chosen;},get built(){return built;},select(id){const b=buttons.find(b=>b.dataset.lens===id);if(b&&!b.disabled)b.click();return !!b&&!b.disabled;}};
 if(new URLSearchParams(globalThis.location?.search||'').has('debug'))globalThis.__utilityLens=api;
 return api;
}
