const $=id=>document.getElementById(id);
let state=null,pending=null,storageKey=null,busy=false,loading=false,stale=true,identityChanged=false,storageReady=true;
let timer=null,readController=null,closed=false,readError=false;
const labels={idle:'Not started',running:'Running',paused:'Paused',completed:'Completed',cancelled:'Cancelled',failed:'Needs attention'};
function message(text,error=false){$('message').textContent=text;$('message').className=error?'error':'';}
function previousDay(value){
 const parsed=new Date(value+'T00:00:00Z');if(Number.isNaN(parsed.getTime()))return '—';
 parsed.setUTCDate(parsed.getUTCDate()-1);return parsed.toISOString().slice(0,10);
}
function nextDay(value){
 const parsed=new Date(value+'T00:00:00Z');if(Number.isNaN(parsed.getTime()))return '';
 parsed.setUTCDate(parsed.getUTCDate()+1);return parsed.toISOString().slice(0,10);
}
function unavailable(){return !state?.environmentId||state.managed||!!state.unavailableReason;}
function workerUnavailable(){return state?.workerEnabled===false||!!state?.workerError;}
function controls(){
 const blocked=busy||!!pending||stale||identityChanged||!storageReady||unavailable();
 const status=state?.status;
 $('start').disabled=loading||blocked||workerUnavailable()||!['idle','completed','cancelled'].includes(status);
 $('targetDate').disabled=blocked||!['idle','completed','cancelled'].includes(status);
 $('reason').disabled=busy||!!pending||identityChanged||!storageReady||unavailable();
 $('pause').disabled=loading||blocked||status!=='running';
 $('resume').disabled=loading||blocked||workerUnavailable()||!['paused','failed'].includes(status);
 $('cancel').disabled=loading||blocked||!['running','paused','failed'].includes(status);
 $('refresh').disabled=loading||busy||identityChanged;
 $('retry').hidden=!pending;$('retry').disabled=busy||loading||identityChanged||unavailable()||(workerUnavailable()&&['start','resume'].includes(pending?.action));
}
function render(){
 $('identity').textContent=state.environmentId?`Environment ${state.environmentId}`:'No initialized world';
 $('runState').textContent=workerUnavailable()&&state.status==='running'?'Waiting for server':labels[state.status]||'Unavailable';
 $('completedThrough').textContent=state.through?previousDay(state.through):'—';
 $('target').textContent=state.targetDate||'No target saved';
 $('nextDay').textContent=state.through||'—';$('revision').textContent=state.revision??'—';
 $('fieldState').textContent=state.fieldConfigured?'Enabled before each day':'Not configured';
 $('fieldState').title=state.fieldOwnerId?`Saved field owner: ${state.fieldOwnerId}`:'';
 const progress=state.progress||{},completed=Number(progress.completedDays)||0,total=Number(progress.totalDays)||0;
 $('progress').value=total?Math.min(100,Math.max(0,completed/total*100)):0;
 $('progressText').textContent=total?`${completed} of ${total} planned days completed · ${Number(progress.remainingDays)||0} remaining.`:'No run is scheduled.';
 const failure=state.error?typeof state.error==='string'?state.error:JSON.stringify(state.error):'';
 const workerFailure=workerUnavailable()?`The automatic runner is unavailable${state.workerError?' ('+String(state.workerError)+')':''}. Restart the local server to restore its supervised runner before starting or resuming. Saved progress is retained; you can still pause or cancel an existing run.`:'';
 $('failure').hidden=!failure&&!workerFailure;
 $('failure').textContent=[workerFailure,failure?`Saved failure: ${failure}`:''].filter(Boolean).join(' ');
 const phase=state.phase?String(state.phase).replaceAll('_',' '):'No active checkpoint';
 $('cause').textContent=failure||state.workerError||phase;
 $('unavailable').hidden=!unavailable();
 $('unavailableReason').textContent=state.unavailableReason||(state.managed?'This world is controlled by the shared runtime. Continue its authenticated schedule there. Local cruise control cannot advance it.':'Initialize a saved world in World controls first.');
 $('targetDate').min=state.through?nextDay(state.through):'';
 if(!$('targetDate').value)$('targetDate').value=state.targetDate||$('targetDate').min;
 const hints={idle:'Choose a stopping date to begin.',running:'The local server owns this run. Pause or cancel remaining days when needed.',
  paused:'The run is paused at its saved checkpoint. Resume to continue toward the same target.',
  failed:'Resolve the recorded cause, then resume. Cancel releases the remaining schedule while keeping completed work.',
  completed:'The stopping date was reached. Choose a later date to start another run.',
  cancelled:'Remaining days were cancelled. Choose a date to start a new run.'};
 $('controlHelp').textContent=unavailable()?'Use the controlling runtime shown above.':workerUnavailable()?'Start and resume are disabled until the server runner is restored. Pause and cancellation remain available for a saved run.':hints[state.status]||'Refresh to recover the saved run state.';
 $('updated').textContent=`Status checked at ${new Date().toLocaleTimeString()}. Updates pause while this page is hidden.`;
 controls();
}
async function request(body,signal){
 const response=await fetch('/api/cruise',body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal}:{cache:'no-store',signal});
 const data=await response.json();
 if(!response.ok){const error=Error(data.error||'Cruise-control request failed.');error.rejected=response.status>=400&&response.status<500;throw error;}
 return data;
}
function schedule(){
 clearTimeout(timer);timer=null;
 if(!closed&&!identityChanged&&document.visibilityState==='visible')timer=setTimeout(()=>refresh(false),2000);
}
async function refresh(manual=false){
 clearTimeout(timer);timer=null;
 if(loading||busy||closed||identityChanged){schedule();return;}
 loading=true;readController=new AbortController();controls();
 const timeout=setTimeout(()=>readController?.abort(),10000);
 try{
  const next=await request(null,readController.signal);
  if(next.schemaVersion!=='world-cruise/1')throw Error('Unsupported cruise-control response. Reload after updating the server.');
  if(state&&(state.worldFingerprint!==next.worldFingerprint||state.environmentId!==next.environmentId)){
   identityChanged=true;throw Error('World identity changed. Reload this page before changing the schedule.');
  }
  state=next;stale=false;const recoveredRead=readError;readError=false;
  if(!storageKey&&state.worldFingerprint){
   storageKey='world-cruise-pending:'+state.worldFingerprint;
   try{
    pending=JSON.parse(sessionStorage.getItem(storageKey)||'null');
    if(pending&&(pending.worldFingerprint!==state.worldFingerprint||pending.environmentId!==state.environmentId))throw Error('Retained command belongs to another world.');
   }catch(error){storageReady=false;throw Error('Could not read retained commands safely. Enable session storage and reload. '+error.message);}
  }
  render();
  if(pending)message('A retained command needs its result confirmed. Retry the same command; progress may already reflect it.');
  else if(!storageReady)message('Session storage is unavailable. Enable it and reload before changing the schedule.',true);
  else if(manual||recoveredRead||$('message').textContent.startsWith('Loading'))message(unavailable()?'This world cannot run local cruise control. See the guidance below.':'Saved run status is current.');
 }catch(error){
  if(error.name!=='AbortError'||document.visibilityState==='visible'){
   stale=true;readError=true;message(error.name==='AbortError'?'Status request timed out. Refresh before changing the schedule.':error.message,true);
  }
 }finally{
  clearTimeout(timeout);readController=null;loading=false;controls();schedule();
 }
}
function clearPending(){pending=null;try{sessionStorage.removeItem(storageKey);}catch{/* A stale stored retry remains safe to replay. */}}
async function send(action){
 if(busy||loading||identityChanged||unavailable())return;
 if(workerUnavailable()&&['start','resume'].includes(pending?.action||action)){
  message('Restart the local server to restore its automatic runner before starting or resuming.',true);return;
 }
 clearTimeout(timer);timer=null;
 if(!pending){
  if(stale||!storageReady)return;
  const reason=$('reason').value.trim();if(!reason){message('Enter a reason for the schedule change.',true);return;}
  const allowed={start:['idle','completed','cancelled'],pause:['running'],resume:['paused','failed'],cancel:['running','paused','failed']};
  if(!allowed[action]?.includes(state.status))return;
  pending={schemaVersion:'world-cruise/1',commandId:crypto.randomUUID(),environmentId:state.environmentId,
   worldFingerprint:state.worldFingerprint,actorId:'world-admin',expectedRevision:state.revision,
   effectiveDate:state.through,action,reason,causalReference:'local-cruise-controls'};
  if(action==='start')pending.targetDate=$('targetDate').value;
  try{sessionStorage.setItem(storageKey,JSON.stringify(pending));}
  catch{pending=null;storageReady=false;message('Enable session storage and reload so commands can be retained for retry.',true);controls();schedule();return;}
 }
 busy=true;controls();message('Recording the cruise-control command…');
 const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000);
 try{
  await request(pending,controller.signal);clearPending();message('Command accepted. Saved progress will update here.');
 }catch(error){
  if(error.rejected)clearPending();
  message((error.name==='AbortError'?'Command response timed out.':error.message)+(pending?' The outcome is uncertain. Retry the retained command.':' Refresh status before trying the action again.'),true);
 }finally{
  clearTimeout(timeout);
  busy=false;controls();
  // A read can reconcile progress, but never drives another world day.
  await refresh(false);
 }
}
$('startForm').onsubmit=event=>{event.preventDefault();send('start');};
for(const action of ['pause','resume','cancel'])$(action).onclick=()=>send(action);
$('retry').onclick=()=>send();$('refresh').onclick=()=>refresh(true);
document.addEventListener('visibilitychange',()=>{
 clearTimeout(timer);timer=null;
 if(document.visibilityState==='visible')refresh(false);else readController?.abort();
});
window.addEventListener('pagehide',()=>{closed=true;clearTimeout(timer);readController?.abort();});
window.addEventListener('pageshow',()=>{if(closed){closed=false;refresh(false);}});
controls();refresh(false);
