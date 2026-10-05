import {localRequest} from './local-session.js';
import {loadingMessage} from './load-messages.js';
import {engineScene} from './engine-monitor.js';
import {ENGINE_SCENES,sceneIndexAt} from './engine-scenes.js';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function stopTarget(status){return status?.active?.jobId?{path:'jobs/'+status.active.jobId+'/stop',body:{},id:status.active.jobId}:status?.analysis?.analysisId?{path:'analysis/stop',body:{analysisId:status.analysis.analysisId},id:status.analysis.analysisId}:null;}
export async function stopLocalWork(status,request=localRequest){const target=stopTarget(status);if(!target)throw Error('This run has already finished.');const result=await request(target.path,target.body);return result.stopped??result.jobs?.some(j=>j.jobId===target.id&&['stopping','cancelled'].includes(j.status))??false;}
export function monitorMarkup(status,sceneIndex=0){const a=status?.active,p=a?.progress||status?.analysis||{},name=a?.name||status?.analysis?.name||'Your utility';
 const total=p.total||0,done=p.completed||0,ratio=total?Math.min(100,100*done/total):0;
 return `<button class="local-monitor-toggle" type="button" aria-expanded="true"><span class="engine-dot"></span><strong>${a?.stopping||p.stopping?'Stopping simulation…':'Your utility is in motion'}</strong><span class="monitor-fold">−</span></button><div class="local-monitor-body"><div class="engine-scene">${engineScene(sceneIndex)}</div><div class="monitor-title">${esc(name)}</div><p class="monitor-stage">${esc((p.stage||'Preparing the engine').replaceAll('.',' · ').replaceAll('_',' '))}</p><div class="monitor-track ${total?'':'indeterminate'}" role="progressbar" aria-label="Completed processing checkpoints" ${total?`aria-valuenow="${done}" aria-valuemin="0" aria-valuemax="${total}"`:''}><i style="width:${total?ratio:30}%"></i></div><div class="monitor-stats"><span>${p.totalHomes?Number(p.totalHomes).toLocaleString()+' homes · one utility':status?.analysis?'Updating your workspace':'Running on this computer'}</span><strong>${total?`${done} / ${total}`:'Working'}</strong></div><p class="monitor-estimate">${p.etaSeconds!=null?(p.etaSeconds<60?'Less than a minute remaining':`About ${Math.ceil(p.etaSeconds/60)} min remaining`):p.overrun?'Taking longer than the estimate · still working':p.activeSeconds?`${Math.floor(p.activeSeconds)}s elapsed · learning this run’s pace`:'Preparing the first estimate…'}</p>${p.etaBasis?`<p class="monitor-basis">${esc(p.etaBasis)}</p>`:''}<div class="monitor-actions">${stopTarget(status)?`<button type="button" class="monitor-stop" ${a?.stopping||p.stopping?'disabled':''}>${a?.stopping||p.stopping?'Stopping…':'Stop simulation'}</button>`:''}<a class="monitor-link" href="./local-runs.html?model=${encodeURIComponent(a?.modelId||status?.analysis?.modelId||'')}">Command Center →</a></div><p class="monitor-stop-note" role="status">${a?.stopping||p.stopping?'Stopping the current work. Your setup and saved revisions are safe.':''}</p></div>`;
}
export function updateLocalMonitor(host,status,now=Date.now()){const active=!!(status?.active||status?.analysis),target=stopTarget(status);
 if(!active&&host.dataset.stopPending)return;
 if(host.dataset.stopRequested&&target?.id!==host.dataset.stopRequested){
  delete host.dataset.stopRequested;
  if(!active){host.hidden=false;host.innerHTML='<div class="monitor-stopped" role="status"><strong>Simulation stopped</strong><p>Your setup and previously saved results are safe. Retry the stopped revision or run the analysis again when ready.</p><button type="button" class="monitor-dismiss">Dismiss</button></div>';host.querySelector('button').onclick=()=>{host.innerHTML='';host.hidden=true;delete host.dataset.stopped;};host.dataset.stopped='true';return;}
 }
 if(!active&&host.dataset.stopped)return;
 if(active&&host.dataset.stopped){delete host.dataset.stopped;host.innerHTML='';}
 host.hidden=!active;if(!active){delete host.dataset.sceneStarted;delete host.dataset.frame;delete host.dataset.scene;return;}
 host.dataset.sceneStarted??=String(now);
 const sceneIndex=sceneIndexAt(now-Number(host.dataset.sceneStarted)),frame=String(sceneIndex);
 const key=JSON.stringify([status.active,status.analysis,host.dataset.stopRequested,host.dataset.stopPending,frame,Math.floor(now/6500)]);if(host.dataset.frame===key)return;host.dataset.frame=key;
 if(!host.firstChild){host.innerHTML=monitorMarkup(status,sceneIndex);}
 else{
  const next=document.createElement('div');next.innerHTML=monitorMarkup(status,sceneIndex);
  host.querySelector('.local-monitor-toggle').replaceWith(next.querySelector('.local-monitor-toggle'));
  const currentBody=host.querySelector('.local-monitor-body'),nextBody=next.querySelector('.local-monitor-body');
  // Keep the running SVG connected: moving it out and back restarts CSS animations.
  if(host.dataset.scene!==frame)currentBody.querySelector('.engine-scene').replaceWith(nextBody.querySelector('.engine-scene'));
  for(const child of [...currentBody.children])if(!child.classList.contains('engine-scene'))child.remove();
  currentBody.append(...[...nextBody.children].filter(child=>!child.classList.contains('engine-scene')));
 }
 host.dataset.scene=frame;host.querySelector('.engine-scene').setAttribute('aria-label',ENGINE_SCENES[sceneIndex].name);host.querySelector('.engine-scene-caption').textContent=loadingMessage(now);
 const button=host.querySelector('button'),body=host.querySelector('.local-monitor-body'),fold=host.querySelector('.monitor-fold');
 const sync=()=>{const open=host.dataset.collapsed!=='true';body.hidden=!open;button.setAttribute('aria-expanded',String(open));fold.textContent=open?'−':'+';};
 button.onclick=()=>{host.dataset.collapsed=String(host.dataset.collapsed!=='true');sync();};sync();
 const stop=host.querySelector('.monitor-stop');if(stop){
  if(host.dataset.stopRequested||host.dataset.stopPending){stop.disabled=true;stop.textContent='Stopping…';}
  stop.onclick=async()=>{stop.disabled=true;stop.textContent='Stopping…';host.dataset.stopPending=target.id;
   host.querySelector('.monitor-stop-note').textContent='Stopping the current work. Your setup and saved revisions are safe.';
   try{if(await stopLocalWork(status))host.dataset.stopRequested=target.id;else host.querySelector('.monitor-stop-note').textContent='This work has already finished.';}catch(e){stop.disabled=false;stop.textContent='Stop simulation';host.querySelector('.monitor-stop-note').textContent=e.message;}finally{delete host.dataset.stopPending;}
  };
 }
}
