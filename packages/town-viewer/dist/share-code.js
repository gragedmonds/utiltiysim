// Simulation codes: one simulation's complete inputs (town, homes, seed, settings, map-day settings, results date and
// every episode on the year, starting and inflicted) as one uppercase code (utilsim/share.py) to paste into another
// copy of Utility Studio. The engine makes and reads them (POST /api/share/encode, /decode): the pages only show,
// copy and paste.
import {applyAgentProposal,proposalInput} from './setup-agent.js';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// What the engine encodes for a saved simulation: the wizard's inputs as the record holds them, plus what the
// simulation actually runs with when it has moved on from the wizard: its town reference (the exact town), the
// locked run settings and seed, the map-day settings, the results date and 2026's episodes.
export function codeInput(s){const p=proposalInput(s);
 return {...p,execution:s.execution==='local'?'local':'hosted',totalHomes:s.execution==='local'?Number(s.totalHomes||s.homes)||undefined:undefined,
  name:s.name||'Untitled simulation',townRef:s.townRef||undefined,settings:s.settings||{},seed:s.seed||'',asOf:s.asOf||'2026-03-31',
  opsSettings:s.opsSettings||undefined,episodes:(s.episodes||[]).map(({id,scenario,...ep})=>ep)};}
// The record an imported code becomes: a ready simulation that opens unlocked, so every setting can be reviewed and
// changed before it starts (a large one opens its run page instead).
export function importedRecord(fresh,proposal){const s=applyAgentProposal({...fresh,status:'draft'},proposal);
 return {...s,status:'ready',locked:false,step:3,wizardVersion:3,environmentProfile:'custom',configDirty:false,agentSummaryDirty:false,agentProposal:undefined,scenarioTitle:proposal.episodes?.length?'Imported scenarios':'Normal operations'};}
// A code in groups of five, as the engine shows it; pasted text may come back in any shape.
export const groupedCode=code=>{const c=String(code||'').replace(/[^A-Za-z0-9]/g,'').toUpperCase();return c?[c.slice(0,4),...(c.slice(4).match(/.{1,5}/g)||[])].join('-'):'';};
export async function fetchCode(api,s,fetchImpl=globalThis.fetch){const r=await fetchImpl(api+'/share/encode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(codeInput(s)),signal:AbortSignal.timeout(20000)});
 const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'This simulation could not be turned into a code.');return data;}
export async function decodeCode(api,code,fetchImpl=globalThis.fetch){const r=await fetchImpl(api+'/share/decode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:String(code||'').trim()}),signal:AbortSignal.timeout(20000)});
 const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'This code could not be read.');return data.proposal;}
// The dialog both pages use: Copy code shows a simulation's code; Import code takes one and saves the simulation.
export function installShareCodes({host=document.body,api,library,onImported=()=>{},fetchImpl}={}){
 const dialog=document.createElement('dialog');dialog.className='code-dialog';host.append(dialog);
 const close=()=>{dialog.close();dialog.innerHTML='';};
 function copyButton(text){const b=document.createElement('button');b.type='button';b.className='primary';b.textContent='Copy code';b.onclick=async()=>{try{await navigator.clipboard.writeText(text);b.textContent='Copied';}catch{b.textContent='Select the code and copy it';}};return b;}
 async function showCode(s){dialog.innerHTML=`<form method="dialog" class="code-form"><div class="eyebrow">SIMULATION CODE</div><h2>${esc(s.name||'Untitled simulation')}</h2><p role="status">Making the code…</p><div class="code-actions"><button type="submit" class="secondary">Close</button></div></form>`;dialog.showModal();
  try{const data=await fetchCode(api,s,fetchImpl);const form=dialog.querySelector('form');form.querySelector('p').remove();
   const code=document.createElement('textarea');code.readOnly=true;code.className='code-text';code.rows=Math.min(8,Math.ceil(data.chars/48)+1);code.value=data.grouped;code.setAttribute('aria-label','Simulation code');code.onclick=()=>code.select();
   const note=document.createElement('p');note.className='field-note';note.textContent=`${data.chars} characters. Paste it into Import code on another computer’s Utility Studio: the same town, settings, seed, dates and every scenario on the year come across. Case, spaces and dashes don’t matter.`;
   form.querySelector('h2').after(code,note);form.querySelector('.code-actions').prepend(copyButton(data.code));code.focus();code.select();}
  catch(e){const p=dialog.querySelector('p');if(p){p.setAttribute('role','alert');p.textContent=e.message;}}}
 function importCode(){dialog.innerHTML=`<form class="code-form"><div class="eyebrow">IMPORT A SIMULATION</div><h2>Paste a simulation code</h2><label for="code-input">Code <span>starts with UTS1</span></label><textarea id="code-input" class="code-text" rows="4" autocomplete="off" spellcheck="false" placeholder="UTS1-…"></textarea><p class="field-note">The simulation is added to this browser’s list with every setting, its seed and its scenarios, ready to review and start.</p><p id="code-message" role="alert"></p><div class="code-actions"><button type="submit" class="primary">Import</button><button type="button" class="secondary" data-close>Cancel</button></div></form>`;dialog.showModal();
  const form=dialog.querySelector('form'),input=form.querySelector('#code-input'),message=form.querySelector('#code-message');form.querySelector('[data-close]').onclick=close;input.focus();
  form.onsubmit=async e=>{e.preventDefault();const button=form.querySelector('[type=submit]');button.disabled=true;message.textContent='Checking the code…';
   try{const p=await decodeCode(api,input.value,fetchImpl);const s=library.save(importedRecord(library.create(),p));close();onImported(s);}
   catch(err){message.textContent=err.message;button.disabled=false;}};}
 dialog.addEventListener('close',()=>{dialog.innerHTML='';});
 return {showCode,importCode,close};
}
