// The KPI glossary: every figure the engine can watch, what it means and how it is counted, the windows it counts
// with (settings you can change), the settings and scenarios that move it, the figures next to it, and where it
// shows. Everything on the page comes from the engine (GET /api/m2c/kpis, /m2c/settings, /m2c/scenarios); opened
// from a simulation (?simulation=<id>&town=<ref>), its chosen figures come first and its own windows are shown.
import {fetchKpiCatalogue,unitLabel,familyTitle} from './kpis.js';
import {SimulationLibrary,studioURL} from './simulation-library.js';
import './local-session.js';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// Settings as the schema titles them: group.key → {title, group title, unit}; nested paths fall back to the leaf.
export function settingIndex(schema){const out={},defs=schema?.$defs||{},resolve=n=>{const ref=n?.$ref||(n?.allOf||[]).find(a=>a.$ref)?.$ref;return ref?defs[ref.split('/').pop()]||n:n;};
 for(const [g,group] of Object.entries(schema?.properties||{})){const grp=resolve(group);for(const [k,f] of Object.entries(grp?.properties||{})){out[g+'.'+k]={title:f.title||k,group:group.title||grp.title||g,unit:f['x-unit']||''};
  const sub=resolve(f)?.properties||{};for(const [s2,f2] of Object.entries(sub))out[g+'.'+k+'.'+s2]={title:(f.title||k)+' · '+(f2.title||s2),group:group.title||grp.title||g,unit:f2['x-unit']||''};}}return out;}
const dirWord=(d,better)=>d>0?'raises it':'lowers it';
// One figure's card.
export function kpiCard(k,{catalogue,settings={},scenarios={},thresholds={},mine=false,configHref=null}={}){
 const th=k.thresholds.map(p=>{const t=thresholds[p]||{};return `<li><b>${esc(t.title||p)}</b>: ${esc(t.value??'—')} ${esc(t.unit||'')}${t.description?` <span class="dir">${esc(t.description)}</span>`:''}</li>`;}).join('');
 const sets=k.settings.map(s=>{const m=settings[s.path]||{};return `<li>${esc(m.title||s.path)}<span class="dir">${esc(m.group?m.group+' · ':'')}${dirWord(s.direction,k.better)}</span></li>`;}).join('');
 const scs=(k.scenarios||[]).map(id=>`<li>${esc(scenarios[id]?.title||id)}</li>`).join('');
 const rel=(k.related||[]).map(id=>`<li><a href="#${esc(id)}">${esc(catalogue?.kpis?.find(x=>x.id===id)?.title||id)}</a></li>`).join('');
 return `<article class="kpi-card${mine?' is-mine':''}" id="${esc(k.id)}"><header><h3>${esc(k.title)}</h3><span class="kpi-unit">${esc(unitLabel(k.unit))} · ${k.better==='context'?'context measure':esc(k.better)+' is better'}</span>${k.twin?'<span class="kpi-twin">a digital-twin figure</span>':''}${mine?'<span class="kpi-twin">watched in this simulation</span>':''}</header><p class="kpi-def">${esc(k.definition)}</p><code class="kpi-formula">${esc(k.formula)}</code>${th?`<div class="kpi-window"><b>Counts with</b> ${configHref?`(<a href="${esc(configHref)}">change in Config</a>)`:'(a run setting: KPI definitions in Config)'}<ul>${th}</ul></div>`:''}<div class="kpi-grid"><div><h4>Moved by</h4>${sets?`<ul>${sets}</ul>`:'<p class="glossary-empty">Follow its source records in Variable dependencies.</p>'}</div><div><h4>Scenarios that move it</h4>${scs?`<ul>${scs}</ul>`:'<p class="glossary-empty">None in the library.</p>'}</div><div><h4>Read with</h4>${rel?`<ul>${rel}</ul>`:'<p class="glossary-empty">—</p>'}</div><div><h4>Where it shows</h4><ul>${k.where.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></div></div></article>`;}
export function billingReportsMarkup(catalogue,filter=''){
 const q=filter.trim().toLowerCase(),reports=(catalogue.billingReports||[]).filter(r=>!q||(r.code+' '+r.title+' '+r.note).toLowerCase().includes(q));
 if(!reports.length)return '';
 const status={available:'Available',partial:'Partial match',needs_data:'Needs source data'};
 return `<section class="glossary-family billing-report-coverage" id="billing-reports"><h2>Billing report coverage</h2><p>Every report in your inventory, with the engine figures and tables that support it. Partial matches explain the model’s limits.</p><div class="billing-report-scroll"><table><thead><tr><th>Report</th><th>Coverage</th><th>Measures and data</th></tr></thead><tbody>${reports.map(r=>`<tr><th><code>${esc(r.code)}</code><br>${esc(r.title)}</th><td><span class="report-status is-${esc(r.status)}">${status[r.status]||esc(r.status)}</span></td><td>${r.kpis.map(id=>`<a href="#${esc(id)}">${esc(catalogue.kpis.find(k=>k.id===id)?.title||id)}</a>`).join(' · ')}${r.table?`<div class="report-table">Data → ${esc(r.table==='billingAudit'?'Monthly billing audit':r.table.replace(/([A-Z])/g,' $1'))}</div>`:''}${r.note?`<p>${esc(r.note)}</p>`:''}</td></tr>`).join('')}</tbody></table></div></section>`;
}
export function glossaryMarkup(catalogue,{settings={},scenarios={},thresholds=null,mine=[],simulation=null,configHref=null,filter=''}={}){
 const th=thresholds||catalogue.thresholds||{};const q=filter.trim().toLowerCase();
 const reportKpis=new Set((catalogue.billingReports||[]).filter(r=>(r.code+' '+r.title+' '+r.note).toLowerCase().includes(q)).flatMap(r=>r.kpis));
 const show=k=>!q||reportKpis.has(k.id)||(k.title+' '+k.definition+' '+k.family+' '+k.id).toLowerCase().includes(q);
 const windows=Object.entries(th).map(([p,t])=>`<tr><th>${esc(t.title||p)}</th><td>${esc(t.value??'—')} ${esc(t.unit||'')}</td><td>${esc(t.description||'')}</td></tr>`).join('');
 const families=catalogue.families.map(f=>{const rows=catalogue.kpis.filter(k=>k.family===f.id&&show(k));if(!rows.length)return '';return `<section class="glossary-family" id="family-${esc(f.id)}"><h2>${esc(f.title)}</h2><p>${esc(f.text)}</p>${rows.map(k=>kpiCard(k,{catalogue,settings,scenarios,thresholds:th,mine:mine.includes(k.id),configHref})).join('')}</section>`;}).join('');
 return `<h1>What the numbers mean.</h1><p class="lead">Every figure Utility Studio can watch, how it is counted, the window it counts with, and what moves it. The figures come from the engine's replay of the year; the windows are run settings, so "a bill is on time within 3 days" is yours to change.</p>${simulation?`<div class="glossary-mine"><h2>${esc(simulation.name||'This simulation')}</h2>${mine.length?`Watching ${mine.map(id=>`<a href="#${esc(id)}">${esc(catalogue.kpis.find(k=>k.id===id)?.title||id)}</a>`).join(' · ')}. The windows below are this simulation's.`:'No figures chosen yet: pick them on the setup page, or let Claude propose them.'}</div>`:''}<ul class="glossary-toc">${catalogue.billingReports?.length?'<li><a href="#billing-reports">Billing report coverage</a></li>':''}${catalogue.families.map(f=>`<li><a href="#family-${esc(f.id)}">${esc(f.title)}</a></li>`).join('')}</ul><div class="glossary-tools"><input id="glossary-filter" type="search" placeholder="Find a figure, report code or word" value="${esc(filter)}" aria-label="Find a figure"></div><section class="glossary-windows"><h2>The windows the figures count with</h2><table><tbody>${windows}</tbody></table></section>${billingReportsMarkup(catalogue,filter)}${families||'<p class="glossary-empty">Nothing matches.</p>'}`;}
if(typeof document!=='undefined'){
 const root=document.getElementById('glossary-root'),q=new URLSearchParams(location.search),api=(q.get('engine')||'').replace(/\/$/,'')+'/api';
 let simulation=null;try{if(q.get('simulation'))simulation=new SimulationLibrary().get(q.get('simulation'));}catch{}
 const town=q.get('town')||simulation?.townRef||null;
 if(simulation){const back=document.getElementById('back-link');back.href=studioURL(simulation);back.textContent='Back to '+(simulation.name||'the simulation')+' ↗';}
 const settingsOf=async()=>{try{const r=await fetch(api+'/m2c/settings'+(town?'?town='+encodeURIComponent(town):''));return r.ok?await r.json():null;}catch{return null;}};
 const townSchemaOf=async()=>{try{const r=await fetch(api+'/config/schema');return r.ok?await r.json():null;}catch{return null;}};
 const scenariosOf=async()=>{try{const r=await fetch(api+'/m2c/scenarios');return r.ok?Object.fromEntries((await r.json()).scenarios.map(s=>[s.id,s])):{};}catch{return {};}};
 // The simulation's own windows: the catalogue for its town, then its locked run settings over the defaults.
 const thresholdsOf=cat=>{const th=structuredClone(cat.thresholds||{});for(const [p,t] of Object.entries(th)){const [g,k]=p.split('.');const v=simulation?.settings?.[g]?.[k];if(v!=null)t.value=v;}return th;};
 (async()=>{try{const [catalogue,settingsSchema,townSchema,scenarios]=await Promise.all([fetchKpiCatalogue(api,{town}),settingsOf(),townSchemaOf(),scenariosOf()]);
   const settings={...settingIndex(townSchema),...settingIndex(settingsSchema?.schema||settingsSchema)},configHref=simulation?(simulation.execution==='local'?'./?edit='+encodeURIComponent(simulation.id):'./studio.html?simulation='+encodeURIComponent(simulation.id)+'&town='+encodeURIComponent(simulation.townRef||'')+'#/config/m2c'):null;
   const draw=filter=>{root.innerHTML=glossaryMarkup(catalogue,{settings,scenarios,thresholds:thresholdsOf(catalogue),mine:simulation?.kpis||[],simulation,configHref,filter});const f=document.getElementById('glossary-filter');f.oninput=()=>{const at=f.selectionStart;draw(f.value);const g=document.getElementById('glossary-filter');g.focus();g.setSelectionRange(at,at);};};
   draw('');if(location.hash)document.getElementById(location.hash.slice(1))?.scrollIntoView();}
  catch(e){root.innerHTML=`<h1>The glossary couldn’t load.</h1><p role="alert">${esc(e.message)}</p><p>Open it from Utility Studio, where the engine is running.</p>`;}})();
}
