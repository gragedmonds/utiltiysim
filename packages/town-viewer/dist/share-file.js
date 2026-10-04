// Simulation files: one simulation's complete inputs (town, homes, seed, settings, map-day settings, results date and
// every episode on the year, starting and inflicted) as one small JSON file (utilsim/share.py) to copy to another
// Utility Studio. The engine writes and reads them (POST /api/share/export, /import) and names each one with three
// words, an animal in the middle ("brave-otter-harbour"), that follow from the simulation's inputs: the pages only
// download, pick and show.
import {applyAgentProposal,proposalInput} from './setup-agent.js';
export const FILE_SUFFIX='.utilitysim.json';
// What the engine exports for a saved simulation: the wizard's inputs as the record holds them, plus what the
// simulation actually runs with when it has moved on from the wizard: its town reference (the exact town), the
// locked run settings and seed, the map-day settings, the results date and 2026's episodes.
export function fileInput(s){const p=proposalInput(s);
 return {...p,execution:s.execution==='local'?'local':'hosted',totalHomes:s.execution==='local'?Number(s.totalHomes||s.homes)||undefined:undefined,
  name:s.name||'Untitled simulation',townRef:s.townRef||undefined,settings:s.settings||{},seed:s.seed||'',asOf:s.asOf||'2026-03-31',
  opsSettings:s.opsSettings||undefined,episodes:(s.episodes||[]).map(({id,scenario,...ep})=>ep)};}
// The record an imported file becomes: a ready simulation that opens unlocked, so every setting can be reviewed and
// changed before it starts (a large one opens its run page instead). The handle stays on the card.
export function importedRecord(fresh,proposal,handle=''){const s=applyAgentProposal({...fresh,status:'draft'},proposal);
 return {...s,status:'ready',locked:false,step:3,wizardVersion:3,environmentProfile:'custom',configDirty:false,agentSummaryDirty:false,agentProposal:undefined,handle:handle||undefined,scenarioTitle:proposal.episodes?.length?'Imported scenarios':'Normal operations'};}
// The three words as a label: brave-otter-harbour → Brave Otter Harbour.
export const handleLabel=h=>String(h||'').split('-').filter(Boolean).map(w=>w[0].toUpperCase()+w.slice(1)).join(' ');
export async function exportFile(api,s,fetchImpl=globalThis.fetch){const r=await fetchImpl(api+'/share/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(fileInput(s)),signal:AbortSignal.timeout(20000)});
 const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'This simulation could not be exported.');return data;}
export async function importFile(api,file,fetchImpl=globalThis.fetch){const r=await fetchImpl(api+'/share/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(file),signal:AbortSignal.timeout(20000)});
 const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'This simulation file could not be read.');return data;}
export function parseFileText(text){let value;try{value=JSON.parse(text);}catch{throw Error('This is not a Utility Studio simulation file.');}if(!value||typeof value!=='object'||Array.isArray(value))throw Error('This is not a Utility Studio simulation file.');return value;}
// Both pages: Export downloads the simulation's file (and remembers its handle on the record); Import picks a file
// and saves the simulation. `onMessage` hears what happened; `onImported` gets the saved record.
export function installShareFiles({host=document.body,api,library,onImported=()=>{},onMessage=()=>{},fetchImpl}={}){
 const input=document.createElement('input');input.type='file';input.accept='.json,application/json';input.hidden=true;host.append(input);
 function download(value,name){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 async function exportSimulation(s){onMessage('Preparing the simulation file…');try{const data=await exportFile(api,s,fetchImpl);download(data.file,data.filename);if(library.get(s.id))library.update(s.id,{handle:data.file.handle});onMessage(`Saved ${data.filename}: “${handleLabel(data.file.handle)}” holds this simulation’s town, settings, seed, dates and scenarios. Import it in Utility Studio on another computer.`);return data;}catch(e){onMessage(e.message);return null;}}
 function importSimulation(){input.value='';input.onchange=async()=>{const f=input.files[0];if(!f)return;if(f.size>2000000){onMessage('Choose a Utility Studio simulation file (a small JSON file).');return;}onMessage('Checking the simulation file…');
   try{const data=await importFile(api,parseFileText(await f.text()),fetchImpl);const s=library.save(importedRecord(library.create(),data.proposal,data.handle));onImported(s);}catch(e){onMessage(e.message);}};input.click();}
 return {exportSimulation,importSimulation};
}
