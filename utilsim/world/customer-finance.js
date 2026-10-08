const $ = id => document.getElementById(id);
let state = null, pending = null, busy = false;
const storageKey = 'world-customer-finance-pending';
function message(value, error=false) { $('message').textContent=value; $('message').className=error?'error':''; }
async function request(path, body) {
  const response=await fetch(path, body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{cache:'no-store'});
  const data=await response.json();
  if (!response.ok) { const error=Error(data.error||'Request failed'); error.rejected=response.status>=400&&response.status<500; throw error; }
  return data;
}
function controls() {
  for (const field of document.querySelectorAll('input,select,button')) field.disabled=busy||!!pending;
  for (const field of document.querySelectorAll('#policy input,#policy select,#policy button,#credit input,#credit button')) field.disabled=busy||!!pending||!state||state.cohortBlocked;
  $('retry').hidden=!pending; $('retry').disabled=busy;
  if (state?.configured) { $('policy').elements.recipientRef.disabled=true; $('policy').elements.cashCents.disabled=true; }
}
async function load(premise) {
  const next=await request('/api/customer-finance?premise='+encodeURIComponent(premise));
  if (state && state.worldFingerprint!==next.worldFingerprint) throw Error('World identity changed. Reload this page.');
  state=next;
  $('identity').textContent=`${state.environmentId} · ${state.premiseId} · world through ${state.through} · revision ${state.revision}`;
  $('overview').hidden=$('settings').hidden=false; $('creditSection').hidden=!state.configured;
  $('knowledge').textContent=state.cohortBlocked?'Occupancy has changed or is vacant. New behavior is blocked; earlier payment confirmations can still be recorded.':!state.configured?'No customer cash profile is configured.':state.knownOutstandingCents===0?'No outstanding amount is known from delivered documents. A trusted simulated delivery must supply invoice evidence before payment behavior can occur.':'Delivered invoice evidence is available. Intentions reserve cash; provider confirmations update the known balance.';
  $('balances').replaceChildren();
  if(state.configured) for(const [key,label] of [['cashCents','Customer cash'],['reservedCashCents','Reserved for intentions'],['netSettledCashCents','Net confirmed settlements'],['knownOutstandingCents','Known outstanding']]) {
    const tile=document.createElement('p'), value=document.createElement('strong');
    value.textContent=new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(state[key]/100);
    tile.append(label,value); $('balances').append(tile);
  }
  const form=$('policy').elements;
  form.recipientRef.value=state.recipientRef||''; form.cashCents.value=state.cashCents||0;
  form.active.checked=state.policy?.active||false;
  for(const key of ['customerKind','essentialReserveCents','maxPaymentCents','paymentProbability']) form[key].value=state.policy?.[key]??({customerKind:'household',essentialReserveCents:0,maxPaymentCents:10000,paymentProbability:1}[key]);
  controls();
}
async function send(action) {
  if(busy) return;
  if(!pending) {
    const form=$(action==='credit'?'credit':'policy').elements;
    pending={schemaVersion:'world-customer-finance/1',commandId:crypto.randomUUID(),environmentId:state.environmentId,runId:state.runId,worldFingerprint:state.worldFingerprint,actorId:'world-admin',expectedRevision:state.revision,effectiveDate:state.through,action,premiseId:state.premiseId,reason:form.reason.value.trim(),causalReference:'local-world-controls'};
    if(action==='credit') pending.amountCents=Number(form.amountCents.value);
    else {
      Object.assign(pending,{active:form.active.checked,customerKind:form.customerKind.value,recipientRef:form.recipientRef.value.trim()});
      for(const key of ['cashCents','essentialReserveCents','maxPaymentCents','paymentProbability']) pending[key]=Number(form[key].value);
    }
    try { sessionStorage.setItem(storageKey,JSON.stringify(pending)); }
    catch { pending=null; message('Enable session storage so commands can be retained for retry.',true); return; }
  }
  busy=true; controls(); message('Saving customer cash scenario…');
  try {
    await request('/api/customer-finance',pending);
    const premise=pending.premiseId; pending=null; sessionStorage.removeItem(storageKey);
    await load(premise); message('Saved. Advance the world to evaluate behavior against delivered invoice knowledge.');
  } catch(error) {
    if(error.rejected) { pending=null; sessionStorage.removeItem(storageKey); }
    message(error.message+(pending?' Outcome uncertain. Retry the retained command.':' Load the premise again before editing.'),true);
  } finally { busy=false; controls(); }
}
$('lookup').onsubmit=async event=>{event.preventDefault(); busy=true; controls(); try { await load($('lookup').elements.premise.value.trim()); message('Customer scenario loaded.'); } catch(error){message(error.message,true);} finally{busy=false;controls();}};
$('policy').onsubmit=event=>{event.preventDefault();send('configure');};
$('credit').onsubmit=event=>{event.preventDefault();send('credit');};
$('retry').onclick=()=>send();
try { pending=JSON.parse(sessionStorage.getItem(storageKey)||'null'); if(pending) message('A retained customer cash command needs confirmation. Retry the same command.'); }
catch { message('Session storage could not be read. Enable it before changing customer cash.',true); }
controls();
