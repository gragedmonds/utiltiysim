import {RunBundle,SavedM2C} from './run-bundle.js';
import {installYearPage} from './year-page.js';
import {installDataPage} from './data-page.js';
import {scorecardMarkup,money,num} from './worklists.js';
import {escapeText as e} from './customer-view.js';

export function filterWorklist(rows,{queue='',search=''}={}){
 const needle=search.trim().toLowerCase();return rows.filter(r=>(!queue||r.queue===queue)&&(!needle||[r.caseId,r.address,r.premiseId,r.accountId,r.meterId].join(' ').toLowerCase().includes(needle)));
}
export function overviewMarkup(manifest,aggregates){
 const town=manifest.towns[0],summary=aggregates.towns[0].summary,k=summary.kpis;
 return `<article class="run-card"><span class="section-kicker">SAVED THROUGH ${e(manifest.asOf)}</span><h2>${e(town.name||town.id)}</h2><p>${num(town.accounts)} accounts · ${num(town.registers)} registers · Engine ${e(manifest.engineVersion)}</p><p class="run-key">${e(manifest.runKey)}</p><div class="run-metrics"><div>Reads<strong>${num(k.reads)}</strong></div><div>Open cases<strong>${num(k.casesOpen)}</strong></div><div>Cost<strong>${money(k.costs.total)}</strong></div><div>Carry<strong>${money(k.carry)}</strong></div></div><p>Tables are saved as of ${e(manifest.asOf)}. There are ${manifest.worklistDates.length} month-end worklist snapshots, including the export date. Files are checked against the manifest before they are displayed.</p><div class="run-actions"><a class="primary-btn" href="#/year">Explore the year</a><a class="outline-btn" href="#/data">Browse tables</a><a class="outline-btn" href="#/workspace">View worklists</a><button class="small-link" id="run-inputs" type="button">Download run inputs</button><button class="small-link" id="run-verify" type="button">Verify all files</button></div></article>`;
}

if(typeof document!=='undefined'){
 const $=id=>document.getElementById(id);let bundle=null,client=null,year=null,data=null,openTicket=0,viewTicket=0,toastTimer;
 let work={date:null,queue:'',search:'',page:1,rows:[],caseId:null};
 function toast(message){$('toast').textContent=message;$('toast').classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.remove('visible'),5000);}
 function status(message,error=false){$('run-status').textContent=message;$('run-status').classList.toggle('run-error',error);}
 function download(value,name){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 function resetRoot(id){const old=$(id),fresh=old.cloneNode(false);old.replaceWith(fresh);return fresh;}
 async function openBundle(loader,{base=null}={}){
  const ticket=++openTicket;status('Opening saved results…');
  try{
   const next=await loader(),aggregates=await next.read('aggregates.json');
   if(aggregates.schemaVersion!=='run-aggregates/1.0'||aggregates.runKey!==next.manifest.runKey||aggregates.asOf!==next.manifest.asOf)throw Error('Aggregates do not belong to this saved run.');
   if(ticket!==openTicket)return;bundle=next;client=new SavedM2C(bundle);work={date:client.asOf,queue:'',search:'',page:1,rows:[],caseId:null};
   year=installYearPage({getClient:()=>client,toast,root:resetRoot('year-root')});
   data=installDataPage({getClient:()=>client,toast,root:resetRoot('data-root')});
   $('run-overview').innerHTML=overviewMarkup(bundle.manifest,aggregates);
   $('run-context').hidden=false;$('run-context').textContent=`${bundle.manifest.towns[0].name||client.townId} · saved through ${client.asOf} · ${bundle.manifest.runKey.slice(0,12)} · read-only`;
   $('run-inputs').onclick=()=>download(client.export(),bundle.manifest.runKey+'-inputs.json');
   $('run-verify').onclick=async ev=>{const current=bundle,button=ev.currentTarget;button.disabled=true;try{const count=await current.verify();toast(`${count} saved files verified.`);}catch(err){toast(err.message);}finally{button.disabled=false;}};
   const url=new URL(location.href);if(base)url.searchParams.set('run',base);else url.searchParams.delete('run');history.replaceState(null,'',url);status('Run opened. No engine connection is needed.');await route();
  }catch(err){if(ticket===openTicket)status(err.message,true);}
 }
 function empty(id){$(id).innerHTML='<h1>Open a saved run</h1><p>Choose a run folder on the <a href="#/runs">Runs page</a> to see its archived results.</p>';}
 function renderWorklist(){
  const manifest=bundle.manifest,selected=filterWorklist(work.rows,work),pages=Math.max(1,Math.ceil(selected.length/100));work.page=Math.min(work.page,pages);
  const rows=selected.slice((work.page-1)*100,work.page*100),queues=[...new Set(work.rows.map(r=>r.queue).filter(Boolean))].sort(),caseRow=work.rows.find(r=>r.caseId===work.caseId);
  $('workspace-view').innerHTML=`<span class="section-kicker">SAVED WORKLIST SNAPSHOTS</span><h1>Workspace</h1><p>Open cases as they stood on each saved date. Select a case to inspect the archived row. Decisions and full record drill-downs need the live engine.</p><div class="run-work-tools"><label>Snapshot <select id="run-work-date">${manifest.worklistDates.map(d=>`<option${d===work.date?' selected':''}>${e(d)}</option>`).join('')}</select></label><label>Queue <select id="run-work-queue"><option value="">All queues</option>${queues.map(q=>`<option value="${e(q)}"${q===work.queue?' selected':''}>${e(q.replaceAll('_',' '))}</option>`).join('')}</select></label><label>Find <input id="run-work-search" type="search" value="${e(work.search)}" placeholder="Case, address or account"></label></div><p>${num(selected.length)} of ${num(work.rows.length)} open cases · ${e(work.date)}</p><div class="run-work-table"><table><thead><tr><th>Case</th><th>Queue</th><th>Exception</th><th>Address</th><th>Age (workdays)</th><th>Impact</th><th>Status</th></tr></thead><tbody>${rows.map(r=>`<tr><td><button data-case="${e(r.caseId)}" type="button">${e(r.caseId)}</button></td><td>${e(r.queue)}</td><td>${e(r.label)}</td><td>${e(r.address)}</td><td>${num(r.ageDays)}</td><td>${money(r.impact)}</td><td>${e(r.status)}</td></tr>`).join('')||'<tr><td colspan="7">No open cases match this selection.</td></tr>'}</tbody></table></div><div class="run-actions"><button type="button" class="small-link" id="run-work-prev"${work.page<=1?' disabled':''}>Previous</button><span>Page ${work.page} of ${pages}</span><button type="button" class="small-link" id="run-work-next"${work.page>=pages?' disabled':''}>Next</button></div>${caseRow?`<article class="run-case"><h2>${e(caseRow.caseId)}</h2><dl>${[['Exception',caseRow.label],['Address',caseRow.address],['Account',caseRow.accountId],['Meter',caseRow.meterId],['Read date',caseRow.readDate],['Observed',caseRow.observed],['Expected',caseRow.expected],['Status',caseRow.status],['Assignee',caseRow.assignee]].map(([k,v])=>`<dt>${e(k)}</dt><dd>${e(v??'—')}</dd>`).join('')}</dl></article>`:''}`;
  $('run-work-date').onchange=ev=>{work.date=ev.target.value;work.page=1;work.caseId=null;loadWorkspace();};
  $('run-work-queue').onchange=ev=>{work.queue=ev.target.value;work.page=1;work.caseId=null;renderWorklist();};
  $('run-work-search').oninput=ev=>{const input=ev.target,pos=input.selectionStart;work.search=input.value;work.page=1;renderWorklist();$('run-work-search').focus();$('run-work-search').setSelectionRange(pos,pos);};
  $('run-work-prev').onclick=()=>{work.page--;renderWorklist();};$('run-work-next').onclick=()=>{work.page++;renderWorklist();};
  $('workspace-view').querySelectorAll('[data-case]').forEach(b=>b.onclick=()=>{work.caseId=b.dataset.case;renderWorklist();});
 }
 async function loadWorkspace(){const ticket=++viewTicket;try{const saved=await client.worklist(work.date);if(ticket!==viewTicket)return;work.rows=saved.rows;renderWorklist();}catch(err){if(ticket===viewTicket)$('workspace-view').innerHTML='<p class="run-error" role="alert">'+e(err.message)+'</p>';}}
 async function route(){
  const page=location.hash.match(/^#\/(year|data|workspace|scorecard)(?:\/|$)/)?.[1]||'runs';++viewTicket;
  for(const name of ['runs','year','data','workspace','scorecard'])$(name+'-view').hidden=name!==page;
  document.querySelectorAll('[data-tab]').forEach(a=>{if(a.dataset.tab===page)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  if(page==='runs')return;if(!client){empty(page==='year'?'year-root':page==='data'?'data-root':page+'-view');return;}
  if(page==='year'){await year.open('#/year');return;}if(page==='data'){await data.open(location.hash);return;}if(page==='workspace'){await loadWorkspace();return;}
  const ticket=viewTicket;try{const score=await client.scorecard();if(ticket===viewTicket)$('scorecard-view').innerHTML='<span class="section-kicker">SAVED SIMULATION TRUTH</span><h1>VEE scorecard</h1>'+scorecardMarkup(score);}catch(err){if(ticket===viewTicket)$('scorecard-view').innerHTML='<p class="run-error" role="alert">'+e(err.message)+'</p>';}
 }
 $('run-folder').onclick=()=>$('run-files').click();$('run-files').onchange=ev=>{const files=Array.from(ev.target.files);if(files.length)openBundle(()=>RunBundle.fromFiles(files));ev.target.value='';};
 $('run-url-form').onsubmit=ev=>{ev.preventDefault();const base=$('run-url').value.trim();openBundle(()=>RunBundle.fromURL(base),{base});};
 window.addEventListener('hashchange',route);route();const base=new URLSearchParams(location.search).get('run');if(base){$('run-url').value=new URL(base,location.href).href;openBundle(()=>RunBundle.fromURL(base),{base});}
}
