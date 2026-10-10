import {renderCityDesign,CITY_FAMILIES,worldProfile,townDestinations} from './city-design.js';
import {renderOverview} from './overview.js';
import {AtlasMap} from './map.js';
import {SCHOOL_BLOCK,RESIDENTIAL_BLOCKS} from './map-block-plate.js';
import {propertyPreview} from './map-preview.js';
const $=id=>document.getElementById(id);
const esc=value=>String(value??'Not recorded').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const nf=new Intl.NumberFormat('en');
const unit=value=>esc(value==='m3'?'m³':value);
const fmt=value=>Number.isFinite(Number(value))&&value!==null?nf.format(Number(value)):'Not recorded';
const day=value=>value?new Date(value+'T12:00:00Z').toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'}):'No completed days';
const shortDay=value=>new Date(value+'T12:00:00Z').toLocaleDateString('en-US',{month:'short',day:'numeric',timeZone:'UTC'});
const paths={
 layers:'m3 8 9-5 9 5-9 5z M3 12l9 5 9-5 M3 16l9 5 9-5',
 overview:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
 map:'m3 5 6-2 6 2 6-2v16l-6 2-6-2-6 2z M9 3v16 M15 5v16',
 sliders:'M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6',
 activity:'M2 12h5l3-8 4 16 3-8h5',
 connections:'M9 5h6 M5 9v6 M19 9v6 M9 19h6 M3 3h6v6H3z M15 3h6v6h-6z M3 15h6v6H3z M15 15h6v6h-6z',
 info:'M12 10v7 M12 7h.01 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
 help:'M9 9a3 3 0 1 1 5 2c-2 1-2 2-2 3 M12 17h.01 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
 search:'M21 21l-5-5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
 water:'M12 2C9 7 5 11 5 15a7 7 0 0 0 14 0c0-4-4-8-7-13z M8 15c0 2 1 3 3 3',
 electric:'m13 2-9 12h7l-1 8 10-13h-8z',
 gas:'M13 2c2 5-1 6-1 9 3-1 3-3 3-4 4 4 5 6 5 9a8 8 0 0 1-16 0c0-4 4-6 4-10 0 3 1 4 3 5',
 fit:'M3 9V3h6 M15 3h6v6 M21 15v6h-6 M9 21H3v-6',
 target:'M12 2v4 M12 18v4 M2 12h4 M18 12h4 M19 12a7 7 0 1 1-14 0 7 7 0 0 1 14 0 M14 12a2 2 0 1 1-4 0 2 2 0 0 1 4 0',
 calendar:'M4 5h16v16H4z M8 2v6 M16 2v6 M4 10h16',
 play:'m8 4 12 8-12 8z',
 pencil:'m4 16-1 5 5-1L21 7l-4-4z M14 6l4 4',
 home:'m3 10 9-7 9 7 M5 9v12h14V9 M9 21v-7h6v7',
 people:'M16 21v-3c0-3-2-4-6-4s-6 1-6 4v3 M14 6a4 4 0 1 1-8 0 4 4 0 0 1 8 0 M17 3c5 0 5 7 0 7 M19 14c3 1 3 3 3 7',
 weather:'M7 16a4 4 0 1 1 1-8 6 6 0 0 1 11 3 3 3 0 1 1 0 6H7 M5 3l1 2 M2 8h2 M11 1v2',
 check:'m5 12 4 4L19 6',
};
function icon(name){return `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name]||paths.info}"/></svg>`;}
function icons(root=document){root.querySelectorAll('[data-icon]').forEach(el=>el.innerHTML=icon(el.dataset.icon));}
let town,state,map,selected,detail,requestVersion=0,page='welcome',busy=false,filter='days';
let toastTimer,mapImage;
let stateStale=false;
const geographyCaption=()=>worldProfile(town,state).caption;
function toast(message){$('toast').textContent=message;$('toast').classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.remove('visible'),4500);}
async function api(path,options){const response=await fetch('/atlas/api/'+path,{...options,headers:{'Content-Type':'application/json',...options?.headers}});const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'The request could not be completed.');return data;}
function route(next,replace=false){
 if(!['welcome','map','overview','configure','activity','connections','city-design'].includes(next))next='welcome';
 page=next;
 document.body.dataset.view=next;
 document.querySelectorAll('.page').forEach(el=>el.hidden=el.id!==next+'-page');
 document.querySelectorAll('nav [data-page]').forEach(el=>{el.classList.toggle('active',el.dataset.page===next);if(el.dataset.page===next)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
 $('page-title').textContent={welcome:'Welcome',map:'Town map',overview:'Overview',configure:'Configure',activity:'Activity',connections:'Connections','city-design':'City design'}[next];
 map?.setVisible(next==='map');
 if(next!=='map')window.scrollTo(0,0);
 if(!replace&&location.hash!=='#'+next)history.pushState(null,'','#'+next);
}
function heading(eyebrow,title,description,action=''){return `<div class="content-heading"><div><span class="eyebrow">${eyebrow}</span><h1>${title}</h1><p>${description}</p></div>${action}</div>`;}
function stat(label,value,note){return `<div class="stat-card"><span>${label}</span><b>${fmt(value)}</b><small>${note}</small></div>`;}
function row(label,value){return `<div class="data-row"><span>${label}</span><strong>${value}</strong></div>`;}
function weather(){
 const days=[...state.daysHistory].reverse();if(!days.length)return '<p>No weather recorded yet.</p>';
 const min=Math.min(...days.map(d=>d.temperature))-2,max=Math.max(...days.map(d=>d.temperature))+2;
 const points=days.map((d,i)=>`${20+i*460/Math.max(1,days.length-1)},${125-(d.temperature-min)/(max-min)*100}`).join(' ');
 return `<svg class="weather-chart" viewBox="0 0 500 150" role="img" aria-label="Recorded daily temperature, ${days.length} days"><defs><linearGradient id="weather-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#6daaa0" stop-opacity=".22"/><stop offset="100%" stop-color="#6daaa0" stop-opacity="0"/></linearGradient></defs><path d="M20 40H480M20 85H480M20 130H480" stroke="#e9eeea" fill="none"/><polygon points="20,140 ${points} 480,140" fill="url(#weather-fill)"/><polyline points="${points}" fill="none" stroke="#378780" stroke-width="2.5" stroke-linejoin="round"/></svg><div class="chart-dates"><span>${day(days[0].day)}</span><span>${day(days.at(-1).day)}</span></div>`;
}
function dayEvents(limit=5){return state.daysHistory.slice(0,limit).map(d=>`<div class="event-row"><span class="event-icon">${icon('check')}</span><div><strong>A physical day completed</strong><p>${fmt(d.observations)} observations recorded · ${fmt(d.temperature)} °C</p></div><small>${shortDay(d.day)}</small></div>`).join('');}
function refreshViews(){
 const profile=worldProfile(town,state);
 $('city-design-page').innerHTML=renderCityDesign(town,{esc,state});
 document.querySelectorAll('.world-switch strong,.header-world,.saved-world-card h3').forEach(el=>el.textContent=profile.name);
 document.querySelector('.world-avatar').textContent=profile.name.charAt(0).toUpperCase();
 document.querySelector('.welcome-resume').innerHTML=`Resume ${esc(profile.name)} <span>→</span>`;
 document.querySelector('#map-page h1').textContent=profile.name+' · Town map';
 const population=town.premises.filter(p=>p.premiseType==='residential'&&p.occupied).reduce((sum,p)=>sum+(p.occupants||0),0);
 const roadsKm=town.roads.reduce((sum,r)=>sum+r.lengthM,0)/1000;
 $('hero-homes').textContent=fmt(town.homes);$('hero-people').textContent=fmt(population);
 if(!map?.drawing)$('map-caption-text').textContent=geographyCaption();
 $('activity-count').textContent=fmt(state.days);
 $('map-date').textContent=day(state.lastCompletedDay);
 $('map-next-date').textContent='Next day: '+day(state.through);
 $('global-clock').textContent=stateStale?'State unavailable · last known records':`${busy?'Advancing':state.clockOwner==='local-cruise'?'Cruise control':state.managedDelivery?'Shared clock':'Manual clock'} · saved through ${day(state.lastCompletedDay)}`;
 $('global-clock').classList.toggle('state-stale',stateStale);
 $('saved-world-summary').textContent=`${profile.label} · daily history saved locally`;
 $('saved-world-date').textContent=day(state.lastCompletedDay);
 $('day-history').innerHTML=state.daysHistory.slice(0,7).reverse().map(d=>`<div class="history-day" title="${esc(d.observations)} observations, ${esc(d.temperature)} °C"><span></span>${shortDay(d.day)}</div>`).join('');
 const advance=`<button class="primary advance-button" ${busy||state.managedDelivery||state.manualAdvanceAllowed===false?'disabled':''}>${icon('play')}${busy?'Simulating…':'Simulate next day'}</button>`;
 $('overview-page').innerHTML=renderOverview({town,state,population,roadsKm,advance,mapImage,day,fmt,icon,esc,dayEvents,weather});
 const cfg=town.config?.town||{};
 const assumptionNames={annual_meter_drift:['Annual meter drift',v=>`${fmt(v*100)}% / year`],annual_meter_failure:['Annual meter failure assumption',v=>`${fmt(v*100)}% / year`],daily_weather_spread_c:['Daily weather spread',v=>`${fmt(v)} °C`],summer_mean_c:['Summer mean temperature',v=>`${fmt(v)} °C`],winter_mean_c:['Winter mean temperature',v=>`${fmt(v)} °C`]};
 $('configure-page').innerHTML=heading('CURRENT CONFIGURATION','What makes this world tick.','The saved town and its active daily model, in one place. Configuration is read-only in this first prototype.')+
 `<div class="configuration-state"><span class="status-good">Current · saved</span><span>Read-only inspection</span><span>Map sketches stay separate from active settings</span></div><div class="config-grid"><div class="panel"><h2>Town & geography</h2><p>${esc(profile.description)}</p>${row('Street pattern',esc(profile.pattern))}${row('Homes / all premises',`${fmt(town.homes)} / ${fmt(town.count)}`)}${row('Road network',`${roadsKm.toFixed(1)} km`)}${row('Terrain relief',`${fmt(cfg.terrain_relief_m)} m`)}${row('Geography',esc(profile.label))}${Array.isArray(town.parks)?row('Saved parks',fmt(town.parks.length)):''}${row(profile.authored?'Model seed':'Seed',esc(town.seed))}<button class="inspector-button" data-page="map">Inspect this geography <span>→</span></button></div><div class="panel"><h2>People & properties</h2><p>Population and homes are distinct model quantities.</p>${row('Residential occupants',fmt(population))}${row('Occupied residential properties',fmt(town.premises.filter(p=>p.premiseType==='residential'&&p.occupied).length))}${row('Nonresidential premises',fmt(town.count-town.homes))}${row('Shops & commercial premises',fmt(town.premises.filter(p=>p.premiseType==='commercial').length))}${row('Community facilities',fmt(town.premises.filter(p=>p.premiseType==='institutional').length))}${row('Industrial premises',fmt(town.premises.filter(p=>p.buildingType==='industrial').length))}${row('Model path','Durable Living World')}${row('Runtime model',esc(state.modelVersion))}${row('Clock owner',state.clockOwner==='local-cruise'?'Local cruise control':state.managedDelivery?'Shared runtime':'Local manual control')}<div class="notice">Studio annual replay and staffing settings belong to a separate execution path. They are not controls for this world's clock.</div></div><div class="panel"><h2>Weather & device assumptions</h2><p>Illustrative assumptions, not a calibrated forecast.</p>${Object.entries(state.settings).map(([k,v])=>row(esc(assumptionNames[k]?.[0]||k.replaceAll('_',' ')),assumptionNames[k]?assumptionNames[k][1](v):fmt(v))).join('')}</div><div class="panel"><h2>Room to grow</h2><p>The full product has more domain workflows. These are not yet connected to the Civic Atlas shell.</p>${row('Infrastructure','Faults · risk · water mains')}${row('People','Occupancy · awareness · finances')}${row('Field work','Assignments · visits · reports')}${row('Development','Existing serviced premises')}<div class="notice warning">Road drawing is a planning sketch. Greenfield construction, automatic parcels, new houses, and utility commissioning are future backend work.</div></div></div>`;
 renderActivity();
 const connections=[['Virtual Systems','Operational consumers learn through observations and authorized evidence.'],['Utility Billing One','Billing workflows within the intended connected ecosystem.'],['M2C App Data Agent','The intended data handoff to downstream analysis.'],['M2C Celonis App','Process analysis within the wider ecosystem.'],['UCascade','A separate application in the intended operational loop.'],['M2C_SEW · Portlet','A navigation entry to connected applications.']];
 $('connections-page').innerHTML=heading('THE CONNECTED ECOSYSTEM','One world. Different responsibilities.','Explore the intended application landscape. No live external integrations are configured in this prototype.')+`<div class="ecosystem-flow panel"><div class="flow-title"><span class="eyebrow">INTENDED DATA EXCHANGE</span><span class="pill">Architecture · not live status</span></div><div class="flow-track"><span>Virtual Systems</span><b>→</b><span>Utility Billing One</span><b>→</b><span>M2C App Data Agent</span><b>→</b><span>M2C Celonis App</span><b>→</b><span>UCascade</span></div><p>Virtual Systems also feeds the M2C App Data Agent. UCascade feeds back to Utility Billing One. M2C_SEW · Portlet provides navigation to M2C Celonis App and UCascade.</p></div><div class="connection-grid">${connections.map(([name,desc],i)=>`<div class="connection-card"><span class="connection-symbol">${icon(i===0?'connections':i===1?'overview':'activity')}</span><h2>${name}</h2><p>${desc}</p><span class="pill">○ Not configured</span></div>`).join('')}</div><h2 class="section-title">Follow the evidence, not just the connection.</h2><div class="panel"><p>Physical event → available observation → submitted message → transport receipt → recipient processing. Each stage needs its own evidence and effective time.</p><div class="notice">${fmt(state.observations)} observations are stored in ${esc(profile.name)}. A saved observation does not imply that an operational system has received or processed it.</div></div>`;
 document.querySelectorAll('.advance-button').forEach(b=>{b.disabled=busy||state.managedDelivery||state.manualAdvanceAllowed===false;b.title=state.manualAdvanceAllowed===false?(state.clockReason||'The runtime controls this clock.'):`Commit the physical day ${day(state.through)}`;b.innerHTML=icon('play')+(busy?'Simulating…':'Simulate next day');});
 icons();
}
function renderActivity(){
 const dayRows=state.daysHistory.map(d=>`<tr><td>${day(d.day)}</td><td>Physical day completed</td><td>${fmt(d.observations)} observations</td><td>${fmt(d.temperature)} °C</td><td><span class="status-good">Saved</span></td></tr>`).join('');
 const events=state.events.map(e=>`<tr><td>${day(e.day)}</td><td>${esc(e.type.replace(/([a-z])([A-Z])/g,'$1 $2'))}</td><td colspan="2">${esc(e.subject)}</td><td><span class="status-good">Recorded</span></td></tr>`).join('');
 $('activity-page').innerHTML=heading('DURABLE PHYSICAL HISTORY','See what actually happened.',`${fmt(state.observations)} observations across ${fmt(state.days)} completed days. History persists when the world is reopened.`,`<button class="primary advance-button" ${busy||state.managedDelivery||state.manualAdvanceAllowed===false?'disabled':''}>${icon('play')}${busy?'Simulating…':'Simulate next day'}</button>`)+`<div class="activity-filter"><button data-filter="days" class="${filter==='days'?'active':''}">Completed days</button><button data-filter="events" class="${filter==='events'?'active':''}">World events</button></div><div class="panel"><h2>${filter==='days'?'A daily record of the world':'The physical event journal'}</h2><p>${filter==='days'?'Latest 30 days · UTC physical-day boundaries':'Latest 40 events · original world identities'}</p><div class="table-scroll"><table class="activity-table"><thead><tr><th>PHYSICAL DATE</th><th>EVENT</th><th>${filter==='days'?'OBSERVATIONS':'SUBJECT'}</th><th>${filter==='days'?'WEATHER':''}</th><th>STATE</th></tr></thead><tbody>${(filter==='days'?dayRows:events)||'<tr><td colspan="5" class="empty-table">No records have been committed yet.</td></tr>'}</tbody></table></div></div><div class="notice">Daily history is a record of committed outcomes. Historical rewind and animated replay are not part of this prototype.</div>`;
}
const houseSVG=`<svg viewBox="0 0 200 130" aria-hidden="true"><path d="m30 98 71-32 76 33-72 27z" fill="#bdceb4"/><path d="m61 60 43 17v37L61 96z" fill="#eeeae0"/><path d="m104 77 40-23v38l-40 22z" fill="#dadfce"/><path d="m48 64 35-42 45 14-24 42z" fill="#657c7b"/><path d="m104 78 24-42 30 19-15 6z" fill="#405e69"/><path d="m76 77 11 4v15l-11-4z m37 7 9-5v14l-9 5z m17-10 8-5v14l-8 5z" fill="#86a5a2"/><path d="m91 90 9 4v16l-9-4z" fill="#769181"/><path d="m60 106 17-7 26 13-17 8z" fill="#dedcc9"/><path d="m161 90 0-35" stroke="#817e5c" stroke-width="4"/><ellipse cx="161" cy="52" rx="16" ry="23" fill="#789d70"/><ellipse cx="166" cy="47" rx="13" ry="16" fill="#96b181"/></svg>`;
// These compact illustrations describe the saved building category; they are not images of the asset.
function propertySchematic(home){
 const type=home.buildingType||'';
 if(type==='detached'||(!type&&home.premiseType==='residential'))return houseSVG;
 const base='<path d="m19 100 82-35 81 35-82 28z" fill="#c7d4bd"/><path d="m39 59 64 24v35L39 93z" fill="#ede8d9"/><path d="m103 83 60-27v35l-60 27z" fill="#d0d7cb"/><path d="m39 59 61-27 63 24-60 27z" fill="#6e8585"/>';
 const storefront='<path d="m40 75 62 24v10L40 85z" fill="#2c8a85"/><path d="m47 86 14 5v15l-14-5z m22 8 14 5v15l-14-5z" fill="#9bb8b3"/><path d="m89 101 9 3v14l-9-3z" fill="#486e70"/><path d="m42 73 60 23v5L42 78z" fill="#bed6c5"/><path d="m112 87 16-7v17l-16 7z m24-11 15-7v17l-15 7z" fill="#91ada5"/>';
 const industrial='<path d="m48 76 20 8v20l-20-8z m31 12 16 6v20l-16-6z" fill="#809597"/><path d="m114 85 35-15v26l-35 15z" fill="#829599"/><path d="m59 52 12 4V25l-12-4z" fill="#b59d86"/><path d="m71 56 9-4V21l-9 4z" fill="#8f8f7d"/><path d="m59 21 9-4 12 4-9 4z" fill="#536a6e"/><path d="m117 88 29-12 m-29 18 29-12 m-29 18 29-12" fill="none" stroke="#b3c1bb" stroke-width="2"/>';
 const school='<path d="m47 76 10 4v10l-10-4z m17 7 10 4v10l-10-4z m17 7 10 4v10l-10-4z m-34 2 10 4v10l-10-4z m17 7 10 4v10l-10-4z" fill="#84a8a8"/><path d="m111 87 11-5v13l-11 5z m17-8 11-5v13l-11 5z m17-8 10-4v13l-10 4z" fill="#81a3a4"/><path d="m84 102 11 4v10l-11-4z" fill="#47777a"/><path d="M98 53V15" stroke="#7a8c81" stroke-width="2"/><path d="m99 15 21 6-21 5z" fill="#d29166"/><circle cx="102" cy="66" r="7" fill="#ecede1"/><path d="M102 61v5l4 2" stroke="#668282" fill="none" stroke-width="1.5"/>';
 const depot='<path d="m47 77 21 8v22l-21-8z m30 11 20 8v21l-20-8z" fill="#8a9c91"/><path d="m50 84 15 6 m-15 2 15 6 m-15 2 15 6 m15-12 14 6 m-14 2 14 6" fill="none" stroke="#bfcbc0" stroke-width="2"/><path d="m115 82 30-13v12l-30 13z" fill="#83a6a2"/>';
 const pump='<path d="m62 85 20 7v24l-20-8z" fill="#578181"/><path d="m115 91 0 20 39-17v-13" stroke="#73a6aa" stroke-width="6" fill="none"/><path d="m129 47 7 3V32l-7-3z" fill="#9fb6b0"/><path d="m136 50 5-3V29l-5 3z" fill="#6d9090"/><path d="m87 62 9 3v12l-9-3z" fill="#a6c1b4"/>';
 const generic='<path d="m49 76 15 5v14l-15-5z m25 9 15 5v14l-15-5z m39 2 15-7v14l-15 7z m24-11 15-7v14l-15 7z" fill="#88aaa7"/>';
 const detail={storefront,industrial,school,depot,pump_house:pump}[type]||generic;
 const family=['storefront','industrial','school','depot','pump_house'].includes(type)?type:'building';
 return `<svg viewBox="0 0 200 130" aria-hidden="true" data-schematic="${family}">${base}${detail}</svg>`;
}
function emptyInspector(){
 $('inspector-content').innerHTML=`<div class="inspector-head"><div class="property-preview">${houseSVG}</div><span class="eyebrow">A CLOSER LOOK</span><h2>Every property<br>has a story.</h2><p>Select a building on the map or search for an address to explore its physical records.</p></div><div class="inspector-section"><h3>${icon('map')}Your town at a glance</h3>${row('Homes',fmt(town.homes))}${row('All premises',fmt(town.count))}${Array.isArray(town.parks)?row('Saved parks',fmt(town.parks.length)):''}${row('Physical meters',fmt(state.assets))}<button id="sample-property" class="inspector-button">Explore a residential property <span>→</span></button></div><div class="inspector-section"><h3>${icon('info')}Living World · administrator</h3><p class="inspector-note">This map inspects physical truth. These records are not automatically known to operational systems.</p></div>`;
}
async function selectProperty(home,focus=false){
 const version=++requestVersion;selected=home;detail=null;map.select(home);if(map.layer==='town')$('legend-text').textContent=home.address+' · selected property';if(focus)map.focus(home,true);
 $('search-results').hidden=true;$('map-search').value='';
 $('inspector-content').innerHTML=`<div class="inspector-head"><span class="eyebrow">PROPERTY RECORD</span><h2>${esc(home.address)}</h2><p>Opening saved physical records…</p></div>`;
 try{const data=await api('premises/'+encodeURIComponent(home.id));if(version!==requestVersion)return;detail=data;renderProperty();}
 catch(error){if(version===requestVersion){$('inspector-content').innerHTML=`<div class="inspector-head"><h2>Records unavailable</h2><p>${esc(error.message)}</p><button class="inspector-button" id="retry-property">Retry <span>↻</span></button></div>`;}}
}
function renderProperty(utility){
 if(!detail)return;utility??=(map.layer==='town'?'water':map.layer);const a=detail.assets.find(a=>a.commodity===utility),p=detail.premise;
 $('inspector-content').innerHTML=`<div class="inspector-head has-selection"><div style="display:flex;justify-content:space-between;align-items:center"><span class="eyebrow">PROPERTY RECORD</span><button id="close-inspector" aria-label="Clear property selection">×</button></div><div class="property-identity"><div id="selected-property-preview" class="property-preview" title="Schematic fallback while the saved-property preview loads">${propertySchematic(selected)}<span class="schematic-label">SCHEMATIC</span></div><div><h2>${esc(p.address)}</h2><p class="property-character">${esc(selected.buildingType.replaceAll('_',' '))} · ${esc(selected.premiseType)}</p></div></div><div class="property-state"><span class="pill">${p.occupied?'Occupied':'Vacant'}</span><span>${selected.premiseType==='residential'?`${fmt(p.occupants)} ${p.occupants===1?'resident':'residents'}`:'Nonresidential property'}</span></div></div><div class="asset-tabs">${['water','electric','gas'].map(u=>`<button data-asset="${u}" class="${u===utility?'active':''}">${u==='electric'?'Electric':u[0].toUpperCase()+u.slice(1)}</button>`).join('')}</div><div class="inspector-section"><h3>${icon(utility)}${utility==='electric'?'Electricity':utility[0].toUpperCase()+utility.slice(1)} service</h3>${a?`<div class="data-row"><span>Device condition</span><span class="${a.condition==='healthy'?'status-good':'status-warn'}">${esc(a.condition)}</span></div><span class="eyebrow" style="font-size:8px;margin-top:19px">RECORDED DAILY USE</span><div class="reading-value">${fmt(a.observed_quantity)} <small>${unit(a.unit)}</small></div><p class="inspector-note">${day(detail.lastCompletedDay)} · ${esc(a.observed_status||'No observation')}</p>${row('Physical use',`${fmt(a.true_quantity)} ${unit(a.unit)}`)}${row('Meter',esc(a.id))}${row('Installed',esc(a.installed))}`:'<p class="inspector-note">No physical meter is recorded for this service.</p>'}</div><div class="inspector-section"><h3>${icon(selected.premiseType==='residential'?'home':'overview')}Physical property</h3>${row('Occupancy',p.occupied?'Occupied':'Vacant')}${selected.premiseType==='residential'?row('Residents',fmt(p.occupants)):row('Property use',esc(selected.premiseType))}${row('Floor area',`${fmt(p.floorAreaM2)} m²`)}${row('Built',esc(selected.yearBuilt))}${row('Property reference',esc(p.id))}${selected.buildingType==='church'&&town.atlasDesign?.churchDemandModel?`<p class="inspector-note">${esc(town.atlasDesign.churchDemandModel)}</p>`:''}<button class="inspector-button" id="property-history">See world activity <span>→</span></button></div><div class="inspector-section"><p class="inspector-note">Administrator physical truth · live flow and pressure measurements are not provided here. <span id="property-preview-note">Schematic shown while the saved-property preview loads.</span></p></div>`;
 loadPropertyPreview(selected);
}
async function loadPropertyPreview(home){
 const container=$('selected-property-preview'),note=$('property-preview-note');
 try{
  const source=await propertyPreview(map,home);
  if(!container?.isConnected||selected?.id!==home.id||$('selected-property-preview')!==container)return;
  const preview=new Image();preview.alt=`Saved map view of ${home.address}`;preview.src=source;
  preview.dataset.premiseId=home.id;preview.width=256;preview.height=256;
  container.replaceChildren(preview);container.classList.add('rendered-property-preview');
  container.title=`${home.address} · rendered from saved map geometry`;
  if(note?.isConnected)note.textContent='Property thumbnail rendered from saved map geometry.';
 }catch{
  if(!container?.isConnected||selected?.id!==home.id)return;
  container.title='Saved-property preview unavailable; building category shown schematically';
  if(note?.isConnected)note.textContent='Property preview unavailable; the labeled illustration is schematic.';
 }
}
async function advance(){
 if(busy)return;if(state.manualAdvanceAllowed===false||state.managedDelivery){toast(state.clockReason||'This world clock is controlled by its runtime.');return;}busy=true;refreshViews();
 try{state=await api('advance',{method:'POST',body:JSON.stringify({townId:town.id,expectedThrough:state.through})});stateStale=false;refreshViews();if(selected)await selectProperty(selected);toast(`${day(state.lastCompletedDay)} completed. The world's records are saved.`);}
 catch(error){toast(error.message);try{state=await api('state');stateStale=false;}catch{stateStale=true;}}
 finally{busy=false;refreshViews();}
}
function sketchChanged(draft,drawing){
 $('sketch-tools').hidden=!drawing;$('map-legend').hidden=drawing;
 $('build-mode').classList.toggle('active',drawing);$('explore-mode').classList.toggle('active',!drawing);
 $('map-caption-text').textContent=drawing?'Planning draft · world geometry unchanged':geographyCaption();
 $('frontage').checked=draft.residentialFrontage;
 const length=draft.points.slice(1).reduce((sum,p,i)=>sum+Math.hypot(p.x-draft.points[i].x,p.z-draft.points[i].z),0);
 $('sketch-length').textContent=Math.round(length)+' m';$('sketch-points').textContent=draft.points.length+' points';
 $('undo-sketch').disabled=!draft.points.length;$('clear-sketch').disabled=!draft.points.length;$('export-sketch').disabled=draft.points.length<2;
}
function visitPlace(id){
 const destination=townDestinations(town).find(p=>p.id===id);
 if(destination){
  route('map');map.setDrawing(false);
  if(destination.home){selectProperty(destination.home,true);return;}
  ++requestVersion;selected=null;detail=null;map.clearSelection();emptyInspector();
  const xs=destination.area.polygon.map(p=>p.x),zs=destination.area.polygon.map(p=>p.z);
  map.focus({x:(Math.min(...xs)+Math.max(...xs))/2,z:(Math.min(...zs)+Math.max(...zs))/2,width:Math.max(...xs)-Math.min(...xs),depth:Math.max(...zs)-Math.min(...zs)},true);
  $('legend-text').textContent=destination.name+' · '+destination.note;
  return;
 }
 const block=id==='school-block'?{...SCHOOL_BLOCK,label:'School neighborhood'}:RESIDENTIAL_BLOCKS.find(b=>b.id===id);
 if(block&&worldProfile(town,state).reference&&block.ids.every(id=>town.premises.some(p=>p.id===id))){
  route('map');map.setDrawing(false);++requestVersion;selected=null;detail=null;
  map.clearSelection();emptyInspector();
  const xs=block.polygon.map(p=>p.x),zs=block.polygon.map(p=>p.z);
  map.focus({...block.center,width:Math.max(...xs)-Math.min(...xs),depth:Math.max(...zs)-Math.min(...zs)},true);
  $('legend-text').textContent=block.label+' · '+block.ids.length+' saved properties';return;
 }
 const family=CITY_FAMILIES.find(f=>f.id===id);
 const home=id==='depot'?town.premises.find(p=>p.buildingType==='depot'):family?.match?town.premises.find(family.match):null;
 const park=family?.park?town.atlasDesign?.parks?.find(p=>p.kind===family.park):null;
 if(!home&&!park)return;
 route('map');map.setDrawing(false);
 if(home){selectProperty(home,true);return;}
 ++requestVersion;selected=null;detail=null;map.clearSelection();emptyInspector();
 const xs=park.polygon.map(p=>p.x),zs=park.polygon.map(p=>p.z);
 map.focus({x:(Math.min(...xs)+Math.max(...xs))/2,z:(Math.min(...zs)+Math.max(...zs))/2,width:Math.max(...xs)-Math.min(...xs),depth:Math.max(...zs)-Math.min(...zs)},true);
 $('legend-text').textContent=park.name+' · saved park, illustrated amenities';
}
function bind(){
 const places=CITY_FAMILIES.filter(f=>f.match?town.premises.some(f.match):town.atlasDesign?.parks?.some(p=>p.kind===f.park));
 $('place-tour').innerHTML='<option value="">Choose a destination…</option>'+places.map(f=>`<option value="${f.id}">${esc(f.park?town.atlasDesign.parks.find(p=>p.kind===f.park).name:f.tag)}</option>`).join('')+(town.premises.some(p=>p.buildingType==='depot')?'<option value="depot">Utility operations depot</option>':'');
 if(worldProfile(town,state).reference&&SCHOOL_BLOCK.ids.every(id=>town.premises.some(p=>p.id===id)))$('place-tour').add(new Option('School neighborhood · whole block','school-block'));
 if(worldProfile(town,state).reference){
  const samples=document.createElement('optgroup');samples.label='Residential block samples';
  for(const block of RESIDENTIAL_BLOCKS)if(block.ids.every(id=>town.premises.some(p=>p.id===id)))samples.append(new Option(block.label,block.id));
  if(samples.children.length)$('place-tour').append(samples);
 }
 const destinations=townDestinations(town);
 for(const group of new Set(destinations.map(p=>p.group))){
  const options=document.createElement('optgroup');options.label=group;
  for(const place of destinations.filter(p=>p.group===group))options.append(new Option(place.name,place.id));
  $('place-tour').append(options);
 }
 $('place-tour').onchange=e=>{visitPlace(e.target.value);e.target.value='';};
 const artStatus=$('map-art-status'),canvasHost=$('map-canvas');
 const updateArtStatus=()=>{
  const mode=canvasHost.dataset.blockArt,count=Number(canvasHost.dataset.blockCount);
  const artToggle=$('map-art-toggle');
  artToggle.disabled=!map.blockArtStats?.ready;
  artToggle.setAttribute('aria-pressed',String(Boolean(map.blockArtStats?.enabled)));
  artToggle.title=map.blockArtStats?.ready?(map.blockArtStats.enabled?'Use individual assets':'Use illustrated blocks'):'Illustrated blocks unavailable for this world';
  artStatus.hidden=!['loading','ready','fallback'].includes(mode);
  artStatus.parentElement.classList.toggle('with-art-status',!artStatus.hidden);
  artStatus.dataset.state=mode||'native';
  artStatus.textContent=mode==='ready'
   ?`Experimental artwork · ${Number.isInteger(count)&&count>0?`${count} saved area${count===1?'':'s'}`:'saved areas'}`
   :mode==='fallback'?'Experimental artwork unavailable · native assets'
   :mode==='loading'?'Experimental artwork · loading':'';
 };
 const artObserver=new MutationObserver(updateArtStatus);
 artObserver.observe(canvasHost,{attributes:true,attributeFilter:['data-block-art','data-block-count']});
 map.abort.signal.addEventListener('abort',()=>artObserver.disconnect(),{once:true});
 updateArtStatus();
 document.addEventListener('click',e=>{
  const scrollButton=e.target.closest('[data-scroll-target]');if(scrollButton){$(scrollButton.dataset.scrollTarget)?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});return;}
  const cityFilter=e.target.closest('[data-city-filter]');if(cityFilter){document.querySelectorAll('[data-city-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b===cityFilter)));document.querySelectorAll('[data-city-group]').forEach(card=>card.hidden=cityFilter.dataset.cityFilter!=='all'&&card.dataset.cityGroup!==cityFilter.dataset.cityFilter);return;}
  const cityExample=e.target.closest('[data-city-example]');if(cityExample){visitPlace(cityExample.dataset.cityExample);return;}
  const pageButton=e.target.closest('[data-page]');if(pageButton){route(pageButton.dataset.page);return;}
  if(e.target.closest('#map-art-toggle')){map.setBlockArtwork(!map.blockArtStats?.enabled);updateArtStatus();return;}
  if(e.target.closest('.advance-button')){advance();return;}
  const layer=e.target.closest('[data-layer]');if(layer){map.setLayer(layer.dataset.layer);document.querySelectorAll('[data-layer]').forEach(b=>b.classList.toggle('active',b===layer));$('legend-text').textContent=layer.dataset.layer==='town'?(selected?selected.address+' · selected property':'Select a property to explore'):`${layer.textContent.trim()} network · topology, not live flow`;document.querySelector('.legend-line').style.background={town:'#659785',water:'#149faf',electric:'#e5a735',gas:'#a783d8'}[layer.dataset.layer];renderProperty();return;}
  const asset=e.target.closest('[data-asset]');if(asset){renderProperty(asset.dataset.asset);return;}
  const filterButton=e.target.closest('[data-filter]');if(filterButton){filter=filterButton.dataset.filter;renderActivity();return;}
  const result=e.target.closest('[data-property]');if(result){selectProperty(town.premises.find(p=>p.id===result.dataset.property),true);return;}
  if(e.target.closest('#sample-property')){selectProperty(town.premises.find(p=>p.premiseType==='residential'),true);return;}
  if(e.target.closest('#close-inspector')){++requestVersion;selected=null;detail=null;map.clearSelection();emptyInspector();if(map.layer==='town')$('legend-text').textContent='Select a property to explore';return;}
  if(e.target.closest('#retry-property')&&selected){selectProperty(selected);return;}
  if(e.target.closest('#property-history')){route('activity');return;}
 });
 $('explore-mode').onclick=()=>map.setDrawing(false);$('build-mode').onclick=()=>map.setDrawing(true);
 $('fit-map').onclick=()=>map.home();$('zoom-in').onclick=()=>map.zoom(.8);$('zoom-out').onclick=()=>map.zoom(1.25);
 $('find-selection').onclick=()=>selected?map.focus(selected,true):toast('Select a property first, or search for an address.');
 $('undo-sketch').onclick=()=>{map.points.pop();map.updateDraft();};$('clear-sketch').onclick=()=>{map.points=[];map.updateDraft();};
 $('frontage').onchange=e=>{map.frontage=e.target.checked;map.updateDraft();};
 $('export-sketch').onclick=()=>{const blob=new Blob([JSON.stringify(map.draft(),null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=worldProfile(town,state).name.toLowerCase().replace(/[^a-z0-9]+/g,'-')+'-road-sketch.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Planning draft exported. No simulation records changed.');};
 $('map-search').oninput=e=>{
  const q=e.target.value.trim().toLowerCase();$('search-results').hidden=!q;$('map-search').setAttribute('aria-expanded',String(Boolean(q)));
  const matches=town.premises.filter(p=>[p.address,p.id,p.name,p.buildingType?.replaceAll('_',' '),p.premiseType].filter(Boolean).join(' ').toLowerCase().includes(q)).slice(0,12);
  $('search-results').innerHTML=matches.length?matches.map(p=>`<button data-property="${esc(p.id)}"><span>${esc(p.address)}</span><small>${esc(p.premiseType)}</small></button>`).join(''):'<p>No properties match that search.</p>';
 };
 $('map-search').onkeydown=e=>{if(e.key==='Enter')$('search-results').querySelector('button')?.click();if(e.key==='Escape')$('search-results').hidden=true;if(e.key==='ArrowDown'){$('search-results').querySelector('button')?.focus();e.preventDefault();}};
 document.addEventListener('click',e=>{if(!e.target.closest('.search-wrap'))$('search-results').hidden=true;});
 const dialog=$('help-dialog');
 $('map-search').setAttribute('aria-controls','search-results');$('map-search').setAttribute('aria-expanded','false');$('about-button').onclick=$('help-button').onclick=()=>dialog.showModal();
 document.querySelectorAll('.close-dialog').forEach(b=>b.onclick=()=>dialog.close());
 $('input-mode').onchange=e=>{map.inputMode=e.target.value;try{localStorage.setItem('civic-atlas:input',e.target.value);}catch{}};
 try{const saved=localStorage.getItem('civic-atlas:input');if(['auto','mouse','trackpad'].includes(saved)){$('input-mode').value=saved;map.inputMode=saved;}}catch{}
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&page==='map'&&!dialog.open){$('search-results').hidden=true;map.setDrawing(false);}if(e.key==='/'&&page==='map'&&!e.target.closest('input,textarea,select')&&!dialog.open){e.preventDefault();$('map-search').focus();}});
 window.addEventListener('popstate',()=>route(location.hash.slice(1),true));
 window.addEventListener('pagehide',()=>map.destroy(),{once:true});
}
async function boot(){
 icons();
 try{
  const data=await api('bootstrap');town=data.snapshot;state=data.state;
  $('app').hidden=false;$('welcome-page').hidden=true;$('map-page').hidden=false;
  map=new AtlasMap($('map-canvas'),town,{onSelect:selectProperty,onSketch:sketchChanged,notify:toast,initialView:worldProfile(town,state).initialView,art:new URLSearchParams(location.search).get('art')||worldProfile(town,state).defaultArt});
  await map.visualReady;
  await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
  mapImage=map.capture();
  emptyInspector();refreshViews();bind();
  $('boot').hidden=true;route(location.hash.slice(1)||'welcome',true);
  const place=new URLSearchParams(location.search).get('place');if(place&&location.hash==='#map')visitPlace(place);
  document.body.dataset.ready='true';
  // Read-only diagnostics for repeatable browser acceptance checks.
  window.atlasDiagnostics=()=>({townId:town.id,grass:map.grassArt,artwork:{enabled:Boolean(map.blockArtStats?.enabled),count:map.blockArtStats?.count||0,totalBlocks:map.blockArtStats?.totalBlocks,readyCount:map.blockArtStats?.readyCount,fallbackCount:map.blockArtStats?.fallbackCount,textureCount:map.blockArtStats?.textureCount,templates:map.blockArtStats?.templates?.map(t=>({...t}))||[],rejected:map.blockArtStats?.rejected?.map(r=>({...r}))||[],areas:map.blockPlates?.map(p=>({...p.stats}))||[]},selectedId:selected?.id,through:state.through,drawing:map.drawing,draft:map.draft(),camera:map.scene.camera.position.toArray(),target:map.scene.controls.target.toArray(),projection:map.scene.camera.isOrthographicCamera?'orthographic':'perspective',cameraZoom:map.scene.camera.zoom,frustum:map.scene.camera.isOrthographicCamera?[map.scene.camera.left,map.scene.camera.right,map.scene.camera.top,map.scene.camera.bottom]:null,renderer:map.scene.performanceState()});
 }catch(error){$('app').hidden=true;$('boot-message').textContent='The world could not open: '+error.message;$('retry').hidden=false;console.error(error);}
}
boot();
