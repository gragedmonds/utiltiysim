import {summaryMarkup,editProposalInput,collectEditedProposal,summaryNeedsRefresh,KPI_TITLES} from './proposal-summary.js';
import {isApp,localRequest} from './local-session.js';
import {fetchKpiCatalogue,matchKpis,watchLine,withKpiTitle} from './kpis.js';
// The engine's test goals by id (utilsim/config/goals.py), for the guide's opening line.
const GOAL_NAMES={operations:'the operations day',reading:'meter reading',vee:'validation & estimation (VEE)',billing:'billing quality',collections:'payments & collections',fieldwork:'field work & maintenance',contact:'the contact centre',everything:'everything'};
export function goalNames(ids){const n=(ids||[]).map(id=>GOAL_NAMES[id]||String(id).replaceAll('_',' '));return n.length>1?n.slice(0,-1).join(', ')+' and '+n.at(-1):n.join('');}
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const PROPOSAL_FIELDS=['execution','totalHomes','name','goals','purpose','region','preset','seed','asOf','townOverrides','settings','operations','episodes','kpis','metricHistory','summary','assumptions','limitations'];
export function proposalInput(proposal){return Object.fromEntries(PROPOSAL_FIELDS.filter(k=>proposal[k]!==undefined).map(k=>[k,k==='episodes'?proposal[k].map(({id,scenario,...ep})=>ep):proposal[k]]));}
export function applyAgentProposal(draft,p){if(draft.status!=='draft')throw Error('Create a new simulation to apply a new setup.');return {...draft,...proposalInput(p),townRef:p.townRef,townId:p.townId,townName:p.townName,homes:p.homes,opsSettings:p.opsSettings,episodes:p.episodes,scenarioId:'custom',scenarioTitle:p.name,agentProposal:p,step:3};}
export function inflictInput(p){return Object.fromEntries(['name','summary','episodes','assumptions','limitations'].filter(k=>p[k]!==undefined).map(k=>[k,p[k]]));}
export function runInput(p){return Object.fromEntries(['townRef','settings','episodes','asOf','startDate','name','region','purpose'].map(k=>[k,p[k]]));}
export function currentRunInput(m,startDate){return {townRef:m.townRef,settings:m.settings||{},episodes:m.episodes,asOf:m.asOf||'2026-03-31',startDate:startDate||m.asOf||'2026-03-31'};}
export const BASELINE_TOPICS=['What to test','Place & service area','Utility & scale','Meters & reads','Team & workflow','Billing & cash','Starting pressures','What-if & recovery'];
export const USE_DEFAULTS='Use sensible defaults for anything I haven’t covered, and propose a baseline setup.';
export function supportsVoice(host=globalThis){return !!(host.SpeechRecognition||host.webkitSpeechRecognition);}

// ---- chat text: light, safe markdown -------------------------------------------------------------------------------
// Text is HTML-escaped first; only our own tags are added afterwards, so model text can never inject markup.
function inline(escaped){const code=[];return escaped.replace(/`([^`\n]+)`/g,(_,c)=>{code.push(c);return `\u0000${code.length-1}\u0000`;})
 .replace(/\*\*(?=\S)([^\n]*?\S)\*\*|__(?=\S)([^\n]*?\S)__/g,(_,a,b)=>`<strong>${a??b}</strong>`)
 .replace(/(^|[^\w*])\*(?=[^\s*])([^*\n]*?[^\s*])\*(?![\w*])/g,'$1<em>$2</em>').replace(/(^|[^\w])_(?=[^\s_])([^_\n]*?[^\s_])_(?!\w)/g,'$1<em>$2</em>')
 .replace(/\u0000(\d+)\u0000/g,(_,i)=>`<code>${code[i]}</code>`);}
export function renderMarkdown(text){let html='',para=[],list=null;
 const flushPara=()=>{if(para.length)html+=`<p>${para.map(inline).join('<br>')}</p>`;para=[];};
 const flushList=()=>{if(list)html+=`<${list.tag}${list.start>1?` start="${list.start}"`:''}>${list.items.map(lines=>`<li>${lines.map(inline).join('<br>')}</li>`).join('')}</${list.tag}>`;list=null;};
 for(const line of esc(String(text??'').replace(/\r\n?/g,'\n')).split('\n')){
  const item=line.match(/^\s*(?:([-*•+])|(\d{1,3})[.)])\s+(\S.*)$/),heading=line.match(/^\s*#{1,6}\s+(\S.*)$/);
  if(item){const tag=item[1]?'ul':'ol';flushPara();if(list?.tag!==tag){flushList();list={tag,start:Number(item[2]||1),items:[]};}list.items.push([item[3]]);}
  else if(!line.trim()){flushPara();flushList();}
  else if(list&&/^\s{2,}\S/.test(line))list.items.at(-1).push(line.trim());
  else if(heading){flushPara();flushList();html+=`<p><strong>${inline(heading[1])}</strong></p>`;}
  else{flushList();para.push(line);}
 }
 flushPara();flushList();return html;}
const plain=text=>String(text??'').replace(/[*_`#]/g,'');

// ---- chat behaviour helpers ----------------------------------------------------------------------------------------
/** Enter sends; Shift+Enter (and IME composition) keeps typing. */
export function composerKey(e){if(e.key!=='Enter'||e.isComposing||e.keyCode===229)return null;return e.shiftKey?'newline':'send';}
const lower=t=>/^[A-Z][a-z]/.test(t)?t[0].toLowerCase()+t.slice(1):t;
const listing=labels=>{const l=labels.slice(0,3).map(lower);return l.length<2?l.join(''):l.slice(0,-1).join(', ')+' and '+l.at(-1);};
/** Short, friendly progress messages from the guide. Deterministic: the wording varies by turn, never at random. */
export function progressNote(stage,{labels=[],turn=0,inflict=false}={}){const pick=list=>list[Math.abs(turn)%list.length],what=listing(labels);
 switch(stage){
  case 'inspect':return pick([`Hey, I’ll look into those knobs${what?` — ${what}`:''}…`,`Okay — let me check the ${what||'relevant'} settings…`,`One sec, pulling up the ${what||'relevant'} dials…`]);
  case 'drafting':return inflict?'Sketching out the new periods…':'Putting the numbers together…';
  case 'validate':return 'Making sure it all fits…';
  case 'repair':return 'One value was out of range — fixing it…';
  case 'proposal':return pick(inflict?['Great — okay, here’s what I’ll tweak:','Okay, here’s the change I’d make:','Right — here’s what I’d add to the Year:']:['Great — okay, here’s what I’ll tweak:','Okay, here’s the setup I’d go with:','Right — here’s what I’d set up:']);
  case 'apply':return inflict?'On it — checking those periods against the current Year…':'On it — giving those settings a final check…';
  case 'running':return 'Looks good — adding those periods and recalculating the Year…';
  case 'applied':return inflict?'Done — the new periods are in.':'Done — your settings are in. Give them a quick review next.';
  default:return '';
 }}
const WHO='<div class="agent-who" aria-hidden="true"><span class="agent-avatar">C</span>Claude</div>';
/** Committed conversation: guide bubbles on the left (name on the first of a run), yours on the right. */
export function logMarkup(rows,previous=null){let html='',last=previous;
 for(const m of rows){if(m.role==='user'){html+=`<div class="agent-msg user"><span class="sr-only">You: </span><p>${esc(m.content)}</p></div>`;last='user';continue;}
  html+=`${last==='assistant'?'':WHO}<div class="agent-msg guide${m.note?' note':''}"><span class="sr-only">Claude: </span>${m.note?`<p>${esc(m.content)}</p>`:renderMarkdown(m.content)}</div>`;last='assistant';}
 return html;}
/** What's happening right now: progress notes, the reply as it streams, typing dots, or an error with Retry. */
export function tailMarkup({live=null,error='',canRetry=false,after=null}={}){let html='',last=after;
 const guide=(cls,body,attrs='')=>{const out=`${last==='assistant'?'':WHO}<div class="agent-msg guide${cls}"${attrs}><span class="sr-only">Claude: </span>${body}</div>`;last='assistant';return out;};
 if(live){for(const n of live.notes||[])html+=guide(' note',`<p>${esc(n.content)}</p>`);
  if(live.text)html+=guide(' is-streaming',renderMarkdown(live.text),' id="agent-stream"');
  if(live.typing!==false)html+=guide(' agent-typing',`<span class="agent-dots" aria-hidden="true"><i></i><i></i><i></i></span>${live.caption?`<span class="agent-typing-text">${esc(live.caption)}</span>`:'<span class="sr-only">Claude is typing…</span>'}`);}
 if(error)html+=guide(' error',`<p>${esc(error)}</p>${canRetry?'<button type="button" class="agent-retry" id="agent-retry">Retry</button>':''}`,' role="alert"');
 return html;}

/** Read a chat reply: server-sent events (progress, text deltas, then done or error), or a plain JSON reply. */
export async function readAgentStream(response,onEvent=()=>{}){const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',result=null;
 const handle=chunk=>{const data=chunk.split(/\r?\n/).filter(l=>l.startsWith('data:')).map(l=>l.slice(5).replace(/^ /,'')).join('\n');if(!data)return;let event;
  try{event=JSON.parse(data);}catch{throw Error('The setup assistant sent an unreadable reply. Please try again.');}
  if(event.type==='done'){const {type,...reply}=event;result=reply;}else if(event.type==='error')throw Object.assign(Error(typeof event.detail==='string'?event.detail:'The setup assistant could not finish. Please try again.'),{status:event.status});else onEvent(event);};
 try{for(;;){const {value,done}=await reader.read();buffer+=decoder.decode(value||new Uint8Array(),{stream:!done});let at;
   while((at=buffer.search(/\r?\n\r?\n/))>=0){const gap=buffer.slice(at).match(/^\r?\n\r?\n/)[0].length;handle(buffer.slice(0,at));buffer=buffer.slice(at+gap);}
   if(done)break;}
  if(buffer.trim())handle(buffer);
 }catch(e){reader.cancel?.().catch?.(()=>{});throw e;}
 if(!result)throw Error('The reply was interrupted. Retry your message.');
 return result;}

const ICON={send:'<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false"><path d="M12 19V5M5.5 11.5 12 5l6.5 6.5" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
 mic:'<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false"><rect x="9" y="3" width="6" height="11" rx="3" fill="none" stroke="currentColor" stroke-width="2"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
 stop:'<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/></svg>'};

export function installSetupAgent({root,api,getDraft,onSave,onApply,onBack,mode='setup',fetchImpl=globalThis.fetch.bind(globalThis),pause=650}){
 const inflict=mode==='inflict',$=sel=>root.querySelector(sel);
 const state=structuredClone(getDraft().agent||{messages:[],proposal:null,input:'',readAloud:false});state.messages||=[];state.input||='';
 let kpiCatalogue=null;fetchKpiCatalogue(api,{fetchImpl}).then(c=>{kpiCatalogue=c;Object.assign(KPI_TITLES,Object.fromEntries(c.kpis.map(k=>[k.id,k.title])));paintAutofill();}).catch(()=>{});
 let resized=null,available=null,busy=false,applying=false,error=state.pending?'The previous reply was interrupted. Retry your last message.':'',alive=true,recognition=null,listening=false,partial='',voiceBase='',live=null,pinned=true,painted=-1;
 const controller=new AbortController();
 const save=()=>{if(alive)onSave(structuredClone(state));};
 const talk=()=>state.messages.filter(m=>!m.note).map(({role,content})=>({role,content}));
 const turnNo=()=>state.messages.filter(m=>m.role==='user').length;
 const note=(content,stage)=>({role:'assistant',content,note:true,...(stage?{stage}:{})});
 const opening=()=>inflict?['What would you like to change in this simulation? Tell me the tweak, when it starts, and roughly how long it should last.',`Suggested start: **${getDraft().startDate}** · ${(getDraft().episodes||[]).length} existing period${(getDraft().episodes||[]).length===1?'':'s'} kept. You can ask for another start date.`]
  :['Hi! I’ll ask a few questions at a time: what you want to test, then where you are and how things work today. Then I’ll shape the setup.',getDraft().goals?.length?`We’ll focus on ${goalNames(getDraft().goals)}. What outcome would you like to test, and where is your service area?`:'What would you like to test—operations day, meter reading, VEE, billing, collections, field work, contact centre, or everything?'];
 const rows=()=>[...opening().map(content=>({role:'assistant',content})),...state.messages];
 function fail(e){if(e.name==='AbortError'||!alive)return;error=e.message||'The assistant could not finish. Please try again.';paint();}
 async function request(path,body,onEvent){const r=await fetchImpl(api+'/setup-agent/'+path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json',...(onEvent?{Accept:'text/event-stream, application/json'}:{})}:undefined,body:body?JSON.stringify(body):undefined,signal:controller.signal});
  if(onEvent&&r.ok&&r.body&&/text\/event-stream/i.test(r.headers?.get?.('content-type')||''))return readAgentStream(r,onEvent);
  let data;try{data=await r.json();}catch{throw Error('The setup assistant is unavailable. Your manual setup is still available.');}if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'The setup request could not be accepted. Please shorten your message and try again.');return data;}
 function stopVoice(){recognition?.stop();}
 function speak(text){if(!state.readAloud||!globalThis.speechSynthesis)return;speechSynthesis.cancel();const utterance=new SpeechSynthesisUtterance(plain(text));utterance.lang='en-CA';speechSynthesis.speak(utterance);}
 function setInput(text){state.input=text;const input=$('#agent-input');if(input){input.value=text;autosize(input);}paintControls();}
 function autosize(input){if(!input?.style||input.scrollHeight==null)return;input.style.height='';if(!input.value)return;input.style.height='auto';input.style.height=Math.min(input.scrollHeight,160)+'px';}
 function voice(){if(listening){stopVoice();return;}const Speech=globalThis.SpeechRecognition||globalThis.webkitSpeechRecognition;if(!Speech)return;globalThis.speechSynthesis?.cancel();const current=recognition=new Speech();recognition.lang=navigator.language||'en-CA';recognition.continuous=true;recognition.interimResults=true;voiceBase=state.input||'';partial='';
  recognition.onstart=()=>{if(recognition!==current)return;listening=true;paintControls();};
  recognition.onresult=e=>{if(recognition!==current)return;const heard=Array.from(e.results,r=>r[0].transcript).join(' ');partial=heard;setInput((voiceBase+' '+heard).trim());};
  recognition.onerror=e=>{if(recognition!==current)return;error=e.error==='not-allowed'?'Microphone access was declined. You can type your answer instead.':e.error==='no-speech'?'No speech was detected. Try again or type your answer.':'Voice input stopped. You can keep typing.';listening=false;paint();};
  recognition.onend=()=>{if(recognition!==current)return;recognition=null;listening=false;if(partial)state.input=(voiceBase+' '+partial).trim();try{save();}catch(e){error=e.message;}setInput(state.input);paintTail();$('#agent-input')?.focus();};
  try{recognition.start();}catch{error='Voice input could not start. You can type instead.';paint();}
 }
 function onEvent(event,turn){if(!alive||!live)return;
  if(event.type==='delta'){live.text+=event.text||'';live.caption='';}
  else if(event.type==='reset')live.text='';
  else if(event.type==='progress'){if(event.stage==='inspect'){live.labels=[...new Set([...(live.labels||[]),...(event.labels||[])])];const content=progressNote('inspect',{labels:live.labels,turn,inflict}),seen=live.notes.find(n=>n.stage==='inspect');if(seen)seen.content=content;else live.notes.push({stage:'inspect',content});live.caption='';}
   else live.caption=progressNote(event.stage,{turn,inflict});}
  paintTail();}
 async function send(retry=false,preset=''){if(busy||applying||!available)return;stopVoice();const text=(preset||state.input).trim();
  if(!retry){if(!text)return;if(talk().length>=48){error='This conversation has reached its limit. Start a new conversation below.';paintTail();return;}state.messages.push({role:'user',content:text});if(!preset)setInput('');state.proposal=null;}
  else if(talk().at(-1)?.role!=='user')return;
  const turn=turnNo()-1;busy=true;state.pending=true;error='';pinned=true;live={notes:[],text:'',caption:''};
  try{save();}catch(e){error=e.message;}paint();$('#agent-input')?.focus();
  try{const context=inflict?structuredClone(runInput(getDraft())):proposalInput(getDraft());
   const data=await request('chat',{schemaVersion:'setup-agent/1.0',mode,messages:talk(),...(inflict?{currentRun:context}:{draft:context})},event=>onEvent(event,turn));if(!alive)return;
   state.messages.push(...live.notes.map(n=>note(n.content,n.stage)),{role:'assistant',content:data.message},...(data.proposal?[note(progressNote('proposal',{turn,inflict}),'proposal')]:[]));
   state.proposal=data.proposal||null;state.summaryDirty=false;state.proposalContext=inflict&&data.proposal?context:null;state.pending=false;speak(data.message);
  }catch(e){if(e.name!=='AbortError')error=e.message||'The assistant could not finish. Please try again.';}
  finally{busy=false;live=null;if(alive){state.pending=false;try{save();}catch(e){error=e.message;}paint();if(state.proposal)revealProposal();}}
 }
 async function apply(){if(!state.proposal||applying||busy||state.summaryDirty)return;const proposal=state.proposal,kept=state.messages.length;applying=true;error='';pinned=true;live={notes:[{content:progressNote('apply',{inflict})}],text:'',caption:''};
  try{stopVoice();paint();const context=inflict?structuredClone(runInput(getDraft())):null;if(inflict&&JSON.stringify(context)!==JSON.stringify(state.proposalContext))throw Error('The simulation changed after this proposal. Send a new message to review tweaks against its latest settings.');const result=await request(inflict?'inflict/validate':'validate',inflict?{currentRun:context,proposal:inflictInput(proposal)}:proposalInput(proposal));if(inflict&&JSON.stringify(context)!==JSON.stringify(runInput(getDraft())))throw Error('The simulation changed while checking. Send a new message before inflicting.');if(!alive)return;
   if(inflict){live.notes.push({content:progressNote('running',{inflict})});paintTail();await onApply(result.proposal);if(alive){state.messages.push(note(progressNote('applied',{inflict}),'applied'));state.proposal=null;save();}return;}
   live={notes:[...live.notes,{content:progressNote('applied')}],text:'',typing:false};paintTail();if(pause)await new Promise(done=>setTimeout(done,pause));if(!alive)return;
   state.messages.push(note(progressNote('applied'),'applied'));state.proposal=null;state.summaryDirty=false;save();await onApply(result.proposal);
  }catch(e){if(alive){state.messages.length=kept;state.proposal=proposal;try{save();}catch{}}fail(e);}finally{applying=false;live=null;if(alive)paint();}}
 async function recheck(){if(applying||busy)return;let candidate;try{candidate=collectEditedProposal(state.proposal,root);}catch(e){error=e.message;paintTail();return;}state.proposal=candidate;applying=true;error='';paint();try{const context=inflict?structuredClone(runInput(getDraft())):null;if(inflict&&JSON.stringify(context)!==JSON.stringify(state.proposalContext))throw Error('The simulation changed. Send a new message to review its latest settings.');const result=await request(inflict?'inflict/validate':'validate',inflict?{currentRun:context,proposal:inflictInput(candidate)}:proposalInput(candidate));if(!alive)return;state.proposal=result.proposal;state.summaryDirty=false;save();}catch(e){error=e.message;}finally{applying=false;if(alive)paint();}}
 function proposalMarkup(p){if(!p)return '';const pairs=Object.entries(p.settings||{}).flatMap(([g,fields])=>Object.entries(fields).map(([key,value])=>`${g}.${key}: ${JSON.stringify(value)}`));return `<section class="agent-proposal" aria-label="${inflict?'Proposed tweak':'Proposed setup'}"><span class="agent-kicker">${inflict?'PROPOSED TWEAK · VALIDATED':'PROPOSED SETUP · VALIDATED'}</span><h2>${esc(p.name)}</h2><p>${esc(p.summary)}</p><dl>${inflict?`<div><dt>Add to current Year</dt><dd>${p.episodes.length} new period${p.episodes.length===1?'':'s'}</dd></div><div><dt>Analyse through</dt><dd>${esc(p.runTo)}</dd></div>`:`<div><dt>Town</dt><dd>${esc(p.townName)} · ${Number(p.homes).toLocaleString()} homes</dd></div><div><dt>Region context</dt><dd>${esc(p.region||'Not specified')}</dd></div><div><dt>Open Year at</dt><dd>${esc(p.asOf)}</dd></div>`}</dl>${p.episodes.length?`<h3>How the year unfolds</h3><ol>${p.episodes.map(ep=>`<li><strong>${esc(ep.title)}</strong><span>${esc(ep.from)} → ${esc(ep.to||'2026-12-31')}</span></li>`).join('')}</ol>`:'<p>Baseline operations throughout the year.</p>'}${p.assumptions?.length?`<h3>${p.summary.startsWith('Updated configuration')?'Conversation assumptions (edited inputs take precedence)':'Assumptions'}</h3><ul>${p.assumptions.map(t=>`<li>${esc(t)}</li>`).join('')}</ul>`:''}<details><summary>Model limits</summary><ul>${p.limitations.map(t=>`<li>${esc(t)}</li>`).join('')}</ul></details>${summaryMarkup(p,{disabled:busy||applying,dirty:state.summaryDirty})}<details><summary>${inflict?'Inspect exact episode settings':`Inspect configuration changes (${p.changes.length})`}</summary><ul>${(p.changes||[]).map(c=>`<li><code>${esc(c.path)}</code><br>${esc(JSON.stringify(c.before))} → ${esc(JSON.stringify(c.after))}</li>`).join('')}</ul>${pairs.length?`<p>Base run settings</p><pre>${esc(pairs.join('\n'))}</pre>`:''}${p.episodes.map(ep=>`<p>${esc(ep.title)}</p><pre>${esc(JSON.stringify(ep.settings,null,2))}</pre>`).join('')}</details><button id="agent-apply" class="primary" type="button" ${busy||applying||state.summaryDirty?'disabled':''}>${applying?'Checking configuration…':inflict?'Inflict & run to period end →':'Use this setup →'}</button><p class="field-note">${inflict?'Adds the reviewed periods and recalculates Year. Existing episodes and base settings are kept.':'This fills in your draft. You’ll review it before opening Year.'}</p></section>`;}
 // ---- painting: the shell is built once, so the composer keeps focus, caret and half-typed text --------------------
 function shell(){root.innerHTML=`<div class="agent-chat${inflict?' is-inflict':''}"><header class="agent-heading"><span class="agent-avatar agent-avatar-lg" aria-hidden="true">C</span><div class="agent-title"><span class="agent-kicker">CLAUDE · ${inflict?'SCENARIO GUIDE':'SETUP GUIDE'}</span><h1>${inflict?'Talk through a tweak.':'Let’s build your baseline.'}</h1></div><button type="button" id="agent-back" class="text-button">${inflict?'Back to Year':'Back to manual setup'}</button></header>${inflict?'':`<ul class="agent-topics" aria-label="Baseline interview topics">${BASELINE_TOPICS.map(t=>`<li>${esc(t)}</li>`).join('')}</ul>`}<div id="agent-notice"></div><div class="agent-thread" id="agent-thread"><div class="agent-log" id="agent-log" role="log" aria-live="polite" aria-label="${inflict?'Scenario':'Setup'} conversation"></div><div id="agent-proposal"></div><div class="agent-tail" id="agent-tail" aria-live="polite"></div></div><form id="agent-form" class="agent-composer" novalidate><div class="agent-quick" id="agent-quick"></div><div class="agent-autofill" id="agent-autofill" hidden aria-live="polite"></div><div class="agent-compose-row"><label for="agent-input" class="sr-only">Message the ${inflict?'scenario':'setup'} guide</label><textarea id="agent-input" rows="1" maxlength="4000" enterkeyhint="send" autocomplete="off" aria-describedby="agent-hint"></textarea><button type="button" class="agent-icon-button" id="agent-voice"></button><button type="submit" class="agent-send" id="agent-send" aria-label="Send message" title="Send (Enter)">${ICON.send}</button></div><p class="agent-hint" id="agent-hint" role="status"></p><div class="agent-compose-meta">${globalThis.speechSynthesis?`<label class="agent-read"><input type="checkbox" id="agent-read" ${state.readAloud?'checked':''}> Read replies aloud</label>`:''}<button class="text-button" id="agent-reset" type="button">Start a new conversation</button></div></form></div>`;
  $('#agent-back').onclick=()=>{try{save();onBack();}catch(e){fail(e);}};
  $('#agent-form').onsubmit=e=>{e.preventDefault();send();};
  const input=$('#agent-input');input.value=state.input;autosize(input);
  input.oninput=e=>{state.input=e.target.value;autosize(input);paintControls();paintAutofill();try{save();}catch(err){error=err.message;paintTail();}};
  input.onkeydown=e=>{if(composerKey(e)==='send'){e.preventDefault();send();}};
  $('#agent-voice').onclick=voice;
  const read=$('#agent-read');if(read)read.onchange=()=>{state.readAloud=read.checked;if(!read.checked)globalThis.speechSynthesis?.cancel();save();};
  $('#agent-reset').onclick=()=>{stopVoice();state.messages=[];state.proposal=null;state.proposalContext=null;state.summaryDirty=false;state.pending=false;error='';setInput('');try{save();}catch(e){error=e.message;}painted=-1;paint();};
  const thread=$('#agent-thread');thread.onscroll=()=>{pinned=thread.scrollHeight-thread.scrollTop-thread.clientHeight<80;};
  // Keep the newest message in view when the panel resizes, e.g. when a phone keyboard opens.
  if(globalThis.ResizeObserver){resized=new ResizeObserver(()=>{if(pinned)scrollEnd();});resized.observe(thread);}
 }
 function paint(){if(!alive)return;if(summaryNeedsRefresh(state.proposal))state.summaryDirty=true;
  $('#agent-notice').innerHTML=available===false?`<div class="help-card"><strong>The setup guide isn’t connected yet.</strong><p>${isApp()?'Talk it through needs an internet connection and an Anthropic API key, kept in this computer’s secure storage. Everything else in Utility Studio works without one.':inflict?'You can still pick scenarios from the Year library.':'You can use the starter setups while the assistant is being connected.'}</p>${isApp()?'<form id="agent-key-form" class="agent-key"><label for="agent-key">Anthropic API key</label><input id="agent-key" type="password" autocomplete="off" spellcheck="false" placeholder="sk-ant-…" required><button type="submit" class="secondary">Save key</button><p id="agent-key-message" role="alert"></p></form>':''}</div>`:'';
  const keyForm=$('#agent-key-form');if(keyForm)keyForm.onsubmit=async e=>{e.preventDefault();const m=$('#agent-key-message'),key=$('#agent-key').value.trim();m.textContent='Saving…';try{await localRequest('claude-key',{key});const data=await request('status');available=data.available;m.textContent=available?'':'Saved, but the assistant still reports unavailable.';if(available)paint();}catch(err){m.textContent=err.message;}};
  paintLog();paintProposal();paintTail(false);paintControls();if(pinned)scrollEnd();}
 function paintLog(){const log=$('#agent-log'),all=rows();
  if(painted<0||all.length<painted||!log.insertAdjacentHTML)log.innerHTML=logMarkup(all);else if(all.length>painted)log.insertAdjacentHTML('beforeend',logMarkup(all.slice(painted),all[painted-1]?.role));
  painted=all.length;}
 function paintTail(follow=true){if(!alive)return;const tail=$('#agent-tail');tail.innerHTML=tailMarkup({live,error,canRetry:!busy&&!applying&&talk().at(-1)?.role==='user',after:state.proposal?null:rows().at(-1)?.role});tail.setAttribute?.('aria-busy',live?.text?'true':'false');
  const retry=$('#agent-retry');if(retry)retry.onclick=()=>send(true);if(follow&&pinned)scrollEnd();}
 function paintProposal(){$('#agent-proposal').innerHTML=proposalMarkup(state.proposal);if(!state.proposal)return;
  root.querySelectorAll('[data-summary-change]').forEach(input=>input.oninput=()=>{state.summaryDirty=true;try{state.proposal=editProposalInput(state.proposal,Number(input.dataset.summaryChange),input.value);save();}catch{}$('.summary-status').textContent='Edits need checking. Recheck to update the summary before applying.';$('[data-summary-recheck]').hidden=false;$('#agent-apply').disabled=true;});
  const check=$('[data-summary-recheck]');if(check)check.onclick=recheck;const button=$('#agent-apply');if(button)button.onclick=apply;}
 function paintControls(){const input=$('#agent-input'),sendButton=$('#agent-send'),voiceButton=$('#agent-voice'),started=talk().length>0,narrow=!!globalThis.matchMedia?.('(max-width: 600px)').matches;
  input.placeholder=listening?'Listening…':started?(inflict?'Reply, or describe another tweak…':'Type your reply…'):narrow?(inflict?'Describe the tweak…':'Type your answer…'):(inflict?'e.g. Half the billing team is out for six weeks from April…':'e.g. We’re in Ontario, and our billing team is struggling to keep up…');
  sendButton.disabled=!available||busy||applying||listening||!state.input.trim();
  voiceButton.disabled=!supportsVoice()||busy||applying;voiceButton.className='agent-icon-button'+(listening?' is-listening':'');voiceButton.innerHTML=listening?ICON.stop:ICON.mic;
  voiceButton.setAttribute?.('aria-label',listening?'Stop listening':'Speak');voiceButton.title=listening?'Stop listening':supportsVoice()?'Speak':'Voice isn’t available in this browser';voiceButton.setAttribute?.('aria-pressed',String(listening));
  const hint=$('#agent-hint'),hintText=listening?'Listening… speak, then press stop to review your words before sending.':`${narrow?'':'Enter to send · Shift+Enter for a new line. '}${supportsVoice()?'Voice uses your browser’s speech service.':'Voice isn’t available in this browser.'} Sent messages and ${inflict?'the current Year configuration':'your draft configuration'} go to Anthropic.`;if(hint.textContent!==hintText)hint.textContent=hintText;
  $('#agent-reset').disabled=busy||applying;
  $('#agent-quick').innerHTML=!inflict&&available&&!busy&&!applying&&!state.proposal&&!state.messages.some(m=>m.stage==='proposal')?`<button type="button" class="agent-chip" id="agent-defaults">${started?'Skip ahead — use defaults for the rest':'Just use sensible defaults'}</button>`:'';
  const defaults=$('#agent-defaults');if(defaults)defaults.onclick=()=>send(false,USE_DEFAULTS);}
 // KPI autofill: while a figure is being named, its catalogue matches show above the box; a click puts the exact
 // name in, so Claude and the person mean the same number.
 function paintAutofill(){const box=$('#agent-autofill');if(!box)return;const matches=listening||busy||applying?[]:matchKpis(kpiCatalogue,state.input);
  box.innerHTML=matches.length?`<span class="agent-autofill-label">KPI</span>${matches.map(k=>`<button type="button" class="agent-chip agent-kpi" data-kpi="${esc(k.id)}" title="${esc(k.definition)}">${esc(k.title)}</button>`).join('')}`:'';box.hidden=!matches.length;
  box.onclick=ev=>{const b=ev.target?.closest?.('[data-kpi]');if(!b)return;const k=kpiCatalogue.kpis.find(x=>x.id===b.dataset.kpi);if(!k)return;setInput(withKpiTitle(state.input,k));box.hidden=true;$('#agent-input')?.focus();};}
 function scrollEnd(){const thread=$('#agent-thread');if(thread&&thread.scrollHeight!=null)thread.scrollTop=thread.scrollHeight;}
 function revealProposal(){const thread=$('#agent-thread'),intro=$('#agent-log')?.lastElementChild;if(!thread||!intro||intro.offsetTop==null)return;thread.scrollTop=Math.max(0,intro.offsetTop-thread.clientHeight*0.35);pinned=false;}
 shell();paint();if(globalThis.matchMedia?.('(pointer: fine)').matches)$('#agent-input').focus();
 request('status').then(data=>{if(alive){available=data.available;paint();}}).catch(e=>{available=false;fail(e);});
 return ()=>{alive=false;controller.abort();resized?.disconnect();if(recognition){recognition.onend=null;recognition.onresult=null;recognition.onerror=null;recognition.onstart=null;recognition.abort();}globalThis.speechSynthesis?.cancel();};
}
