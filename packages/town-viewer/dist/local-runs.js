import {SimulationLibrary} from './simulation-library.js';
import {proposalInput} from './setup-agent.js';
import {installYearPage} from './year-page.js';
import {installWorkspace} from './workspace.js';
import {installProcess,parseRoute as parseProcessRoute} from './process.js';
import {installDataPage} from './data-page.js';
import {scorecardMarkup} from './worklists.js';
import {LocalPlan,seedPatterns} from './local-year.js';
import {LocalUtility} from './local-workspace.js';
import {isApp,localRequest} from './local-session.js';
import {installShareFiles} from './share-file.js';
import {updateLocalMonitor} from './local-monitor.js';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function revisionState(jobs,modelId){const rows=jobs.filter(j=>j.recipe.modelId===modelId).sort((a,b)=>b.revision-a.revision);return {latest:rows[0],viewing:rows.find(j=>j.status==='complete'),next:(rows[0]?.revision||0)+1,rows};}
export function formatETA(seconds){return seconds==null?'Learning this run’s pace…':seconds<60?'About a minute remaining':`About ${Math.ceil(seconds/60)} minutes remaining`;}
export const districtURL=runKey=>'./runs.html?run='+encodeURIComponent('/runs/'+runKey+'/');
export const STATUS_TEXT={queued:'Queued',running:'Running',complete:'Complete',failed:'Needs attention'};
export function localProposal(model){const clean=proposalInput(model);return {...clean,episodes:seedPatterns(clean.episodes||[],model.id),execution:'local',totalHomes:model.totalHomes||model.homes,summary:model.summary||'Explore the whole utility on this computer.'};}
export function savedDecisions(job){const qualify=(value,district,key='')=>Array.isArray(value)?value.map(v=>qualify(v,district,key)):value&&typeof value==='object'?Object.fromEntries(Object.entries(value).map(([k,v])=>[k,qualify(v,district,k)])):typeof value==='string'&&/^[A-Z][A-Z0-9_]*-/.test(value)&&/Ids?$/.test(key)?district+'::'+value:value;
 return Object.entries(job.recipe.request.actionsByDistrict||{}).flatMap(([district,actions])=>actions.map(a=>qualify(a,district))).sort((a,b)=>a.day.localeCompare(b.day));}
if(typeof document!=='undefined'){
 const $=id=>document.getElementById(id),q=new URLSearchParams(location.search),api=(q.get('engine')||'').replace(/\/$/,'')+'/api',library=new SimulationLibrary();
 const processMarkup=$('local-process').innerHTML;
 const modelId=q.get('model');let model=library.get(modelId||''),jobs=[],status=null,busy=false,refreshing=false,error='',connectionError='',renderKey='',process=null,client=null,year=null,workspace=null,data=null,mounted='',page='',routeTicket=0;
 const toast=message=>{$('local-year-note').textContent=message;$('toast').textContent=message;$('toast').classList.add('visible');setTimeout(()=>$('toast').classList.remove('visible'),6000);};
 const files=installShareFiles({api,library,onMessage:toast,onImported:s=>location.href='./local-runs.html?model='+encodeURIComponent(s.id)});
 const proposal=()=>localProposal(model);
 function save(){model=library.get(modelId)||model;renderControls();}
 function reset(id){const old=$(id),next=old.cloneNode(false);old.replaceWith(next);return next;}
 function mount(){if(!model)return;const done=revisionState(jobs,modelId).viewing,key=done?.jobId||'plan';if(key===mounted)return;mounted=key;
  if(done){client=new LocalUtility({job:done,model,library,api,onSave:save});
   year=installYearPage({root:reset('year-root'),getClient:()=>client,getSimulation:()=>model,toast});
   workspace=installWorkspace({root:reset('workspace-root'),getClient:()=>client,toast,onProcess:c=>{location.hash='#/process/'+Number(String(c.readDate||c.createdAt).slice(5,7));}});
   $('local-process').innerHTML=processMarkup;process=installProcess({getClient:()=>client,toast});$('process-back').onclick=()=>{location.hash='#/workspace';};
   data=installDataPage({root:reset('data-root'),getClient:()=>client,toast});
  }else{client=new LocalPlan({library,id:modelId,api,onSave:save});year=installYearPage({plan:true,root:reset('year-root'),getClient:()=>client,getSimulation:()=>model,toast});}
  route(true);
 }
 function renderTop(){if(!model){$('local-root').innerHTML='<h1>Command Center</h1><p>Choose a simulation from <a href="./">your library</a>.</p>';return;}
  $('config-link').href='./?edit='+encodeURIComponent(modelId)+(q.get('engine')?'&engine='+encodeURIComponent(q.get('engine')):'');
  $('local-root').innerHTML=`<div class="offline-context"><div><span class="section-kicker">YOUR UTILITY · ON THIS COMPUTER</span><h1>${esc(model.name)}</h1><p>${Number(model.totalHomes||model.homes).toLocaleString()} homes · one workspace · model year 2026</p></div><div class="offline-context-actions"><button id="export-file" class="outline-btn">Export simulation</button><button id="import-file" class="small-link">Import</button></div></div>`;
  $('export-file').onclick=()=>files.exportSimulation(model);$('import-file').onclick=()=>files.importSimulation();
 }
 function renderControls(){if(!model)return;const state=revisionState(jobs,modelId),live=!!state.viewing;
  $('local-run').innerHTML=`<div class="offline-run-bar"><div><strong>${live?'Interactive utility workspace':'Ready for your first run'}</strong><p>${live?'Click a day in the Command Center to change the year. Work cases, inspect bills, and compare results across your entire utility.':'Run the utility once, then explore and change any part of the year here.'}</p>${state.latest?.status==='failed'?`<p role="alert">${esc(state.latest.error)}</p>`:''}</div><label class="run-through">${live?'Archive results through':'Run through'}<input id="run-asof" type="date" min="2026-01-01" max="2026-12-31" value="${esc(model.asOf||'2026-03-31')}"></label><button id="queue-run" class="primary-btn" ${busy||!isApp()||state.latest?.status==='running'||state.latest?.status==='queued'?'disabled':''}>${busy?'Checking…':state.latest?.status==='running'?'Engine running…':state.latest?.status==='queued'?'Queued…':live?'Save a new revision':'Run utility'}</button>${status?.paused?'<button id="resume-queue" class="outline-btn">Resume</button>':''}</div>${error||connectionError?`<p role="alert" class="year-error">${esc(error||connectionError)}</p>`:''}${!isApp()?'<p role="alert">Open this workspace from the Utility Studio launcher to use the local engine.</p>':''}`;
  $('queue-run').onclick=queue;$('run-asof').onchange=e=>{client?.setAsOf(e.target.value);model=library.update(model.id,{asOf:e.target.value});route(true);};
  if($('resume-queue'))$('resume-queue').onclick=async()=>{await localRequest('pause',{paused:false});refresh();};
  const detail=$('revision-root').querySelector('details')?.open;
  $('revision-root').innerHTML=`<details class="offline-history" ${detail?'open':''}><summary>Saved revisions${state.rows.length?' · '+state.rows.length:''}</summary><p>Each revision preserves its inputs and results. Current edits are saved with this simulation.</p>${state.rows.map(j=>`<div class="revision-row"><strong>Revision ${j.revision}</strong><span>${esc(STATUS_TEXT[j.status])}</span><span>${esc(j.recipe.request.asOf)}</span>${j.status==='complete'?`<details><summary>Checkpoint archives & timings</summary><p>Processing checkpoints keep memory bounded. The main workspace combines every checkpoint.</p><div class="checkpoint-links">${j.result.districts.map(d=>`<a href="${districtURL(d.runKey)}" target="_blank" rel="noopener">${esc(d.id)} · ${d.homes.toLocaleString()} homes ↗</a>`).join('')}</div></details>`:j.status==='failed'?`<button class="small-link" data-retry="${j.jobId}">Retry</button>`:''}</div>`).join('')}</details>`;
  $('revision-root').querySelectorAll('[data-retry]').forEach(b=>b.onclick=async()=>{await localRequest('jobs/'+b.dataset.retry+'/retry',{});refresh();});
 }
 async function queue(){if(busy)return;busy=true;error='';renderControls();try{
  // Preserve existing record identities when saving later revisions.
  const prior=revisionState(jobs,modelId).viewing,chunkSize=prior?.recipe.chunkSize||10000;
  await localRequest('jobs',{proposal:proposal(),modelId,chunkSize,actions:client?.actions||model.actions||[]});await refresh();
 }catch(e){error=e.message;}finally{busy=false;renderControls();}}
 async function route(force=false){const target=location.hash.match(/^#\/(year|workspace|data|scorecard|process)/)?.[1]||'year';if(!force&&page===target&&target==='year')return;page=target;const ticket=++routeTicket;
  for(const [name,id] of Object.entries({year:'local-year',workspace:'local-workspace',data:'local-data',process:'local-process',scorecard:'local-scorecard'}))$(id).hidden=name!==page;
  document.querySelectorAll('[data-page]').forEach(a=>{if(a.dataset.page===page)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  if(page==='year'){year?.open('#/year');return;}
  if(!client?.localUtility){const root=page==='scorecard'||page==='process'?$('local-'+page):$(page+'-root');root.innerHTML='<div class="offline-empty"><h2>Your whole utility will be here</h2><p>Run the first revision from the Command Center to open interactive results.</p><a href="#/year">Go to Command Center →</a></div>';return;}
  if(page==='process'){process.open(parseProcessRoute(location.hash));return;}if(page==='workspace'){workspace.open(location.hash);return;}if(page==='data'){data.open(location.hash);return;}
  try{const score=await client.scorecard();if(ticket===routeTicket)$('local-scorecard').innerHTML='<h1>VEE scorecard</h1>'+scorecardMarkup(score);}catch(e){if(ticket===routeTicket)$('local-scorecard').textContent=e.message;}
 }
 async function refresh(){if(refreshing)return;refreshing=true;try{
  if(isApp()){status=await localRequest('status');if(modelId)jobs=(await localRequest('jobs?model='+encodeURIComponent(modelId))).jobs;
   if(!model){const j=revisionState(jobs,modelId).viewing||revisionState(jobs,modelId).latest;if(j)model=library.save({...library.create(),...j.recipe.proposal,id:modelId,status:'ready',execution:'local',homes:j.recipe.homes,totalHomes:j.recipe.homes,actions:savedDecisions(j)});}}
  connectionError='';updateLocalMonitor($('local-monitor'),status);const next=JSON.stringify([model?.name,model?.asOf,error,status?.paused,jobs.map(j=>[j.jobId,j.status])]);if(next!==renderKey&&!['INPUT','SELECT','TEXTAREA'].includes(document.activeElement?.tagName)){renderKey=next;renderTop();renderControls();}mount();
 }catch(e){connectionError=e.message;renderKey='';renderControls();}finally{refreshing=false;}}
 window.addEventListener('hashchange',()=>route());await refresh();setInterval(refresh,2500);
}
