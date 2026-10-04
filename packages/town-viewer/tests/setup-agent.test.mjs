import test from 'node:test';
import assert from 'node:assert/strict';
import {applyAgentProposal,proposalInput,supportsVoice,renderMarkdown,composerKey,progressNote,logMarkup,tailMarkup,readAgentStream,installSetupAgent,USE_DEFAULTS} from '../dist/setup-agent.js';
import {EngineM2C} from '../dist/m2c.js';
import {EngineOperations} from '../dist/engine-operations.js';

const proposal={name:'Recovery',purpose:'Reduce backlog',preset:'village',region:'Ontario',seed:'repeat-me',asOf:'2026-05-28',summary:'A recovery plan.',assumptions:[],limitations:[],townOverrides:{},settings:{process:{analysts:2}},operations:{crews:{fieldCrews:3}},opsSettings:{fieldCrews:3},townRef:'village',townId:'town-1',townName:'Village',homes:480,changes:[],episodes:[{id:'EP-1',title:'RPA off',from:'2026-04-01',to:'2026-04-30',ramp:0,settings:{process:{rpa_coverage:0}}}]};
function memory(){const m=new Map();return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v)};}
test('reviewed proposals populate a draft without replacing identity or conversation',()=>{
 const old={id:'sim-1',status:'draft',name:'Old',agent:{messages:[{role:'user',content:'Help'}]},createdAt:'today'};
 const updated=applyAgentProposal(old,proposal);
 assert.equal(updated.id,'sim-1');assert.equal(updated.status,'draft');assert.equal(updated.step,3);assert.equal(updated.scenarioId,'custom');assert.equal(updated.createdAt,'today');assert.equal(updated.agent.messages.length,1);
 assert.deepEqual(updated.settings,{process:{analysts:2}});assert.equal(old.name,'Old');
 assert.throws(()=>applyAgentProposal({...old,status:'ready'},proposal),/new simulation/);
});
test('revalidation sends only configuration inputs, stripping derived fields and episode IDs',()=>{
 const input=proposalInput({...proposal,secret:'do not send',townRef:'anything'});
 assert.equal(input.townRef,undefined);assert.equal(input.opsSettings,undefined);assert.equal(input.secret,undefined);assert.equal(input.episodes[0].id,undefined);assert.equal(proposal.episodes[0].id,'EP-1');
});
test('agent settings reach both engine clients and saved user changes win when reopening',()=>{
 const store=memory(),draft=applyAgentProposal({id:'sim-1',status:'draft'},proposal);
 const m=new EngineM2C({townRef:draft.townRef,townId:draft.townId,simulationId:draft.id,storage:store,initial:draft});
 assert.deepEqual(m.body().settings,proposal.settings);assert.equal(m.body().episodes[0].from,'2026-04-01');assert.equal(m.body().seed,'repeat-me');
 m.setSettings({process:{analysts:4}});const reopened=new EngineM2C({townId:draft.townId,simulationId:draft.id,storage:store,initial:draft});assert.equal(reopened.settings.process.analysts,4);
 const ops=new EngineOperations({id:draft.townId},{simulationId:draft.id,storage:store,initial:draft.opsSettings});assert.equal(ops.settings.fieldCrews,3);
 store.setItem('utility-town-ops-settings:simulation:sim-1:town-1','null');assert.equal(new EngineOperations({id:draft.townId},{simulationId:draft.id,storage:store,initial:draft.opsSettings}).settings,null,'an explicit reset stays reset on reopen');
});
test('voice feature detection supports standard and prefixed browsers, with typing fallback',()=>{
 assert.equal(supportsVoice({}),false);assert.equal(supportsVoice({SpeechRecognition:class{}}),true);assert.equal(supportsVoice({webkitSpeechRecognition:class{}}),true);
});

test('Year context includes live settings and existing episodes while omitting conversation metadata',async()=>{
 const {runInput,currentRunInput,inflictInput,BASELINE_TOPICS}=await import('../dist/setup-agent.js');
 const m=new EngineM2C({townRef:'village',townId:'town-1',storage:memory(),initial:proposal});
 m.setSettings({process:{analysts:5}});
 const context=runInput({...currentRunInput(m,'2026-06-01'),agent:{messages:[{role:'user',content:'Private history'}]},actions:[{id:'ACT-1'}]});
 assert.equal(context.settings.process.analysts,5);assert.equal(context.startDate,'2026-06-01');assert.equal(context.episodes[0].id,'EP-1');assert.equal(context.agent,undefined);assert.equal(context.actions,undefined);
 const tweak=inflictInput({name:'Half staff',summary:'Six weeks',episodes:proposal.episodes,runTo:'2026-05-28',townOverrides:{bad:true}});
 assert.equal(tweak.runTo,undefined);assert.equal(tweak.townOverrides,undefined);assert.equal(BASELINE_TOPICS.length,8);
});

// ---- chat guide ------------------------------------------------------------------------------------------------------
const tick=()=>new Promise(r=>setTimeout(r,5));
const settle=async()=>{for(let i=0;i<6;i++)await tick();};
/** Enough of a DOM for the guide: each selector resolves to one stub element until the root is rebuilt. */
function fakeRoot(){const els=new Map(),root={html:'',querySelectorAll:()=>[]};
 const make=sel=>({sel,innerHTML:'',value:'',textContent:'',placeholder:'',className:'',title:'',disabled:false,hidden:false,style:{},dataset:{},attrs:{},scrollTop:0,scrollHeight:900,clientHeight:300,focused:0,
  focus(){this.focused++;},setAttribute(k,v){this.attrs[k]=String(v);},insertAdjacentHTML(_,html){this.innerHTML+=html;}});
 Object.defineProperty(root,'innerHTML',{get(){return this.html;},set(v){this.html=v;els.clear();}});
 root.querySelector=sel=>{if(sel==='#agent-retry'&&!els.get('#agent-tail')?.innerHTML.includes('id="agent-retry"'))return null;if(!els.has(sel))els.set(sel,make(sel));return els.get(sel);};
 return root;}
function controlledStream(){let controller;const body=new ReadableStream({start(c){controller=c;}});const enc=new TextEncoder();
 return {response:new Response(body,{headers:{'content-type':'text/event-stream'}}),push:t=>controller.enqueue(enc.encode(t)),end:()=>controller.close()};}
const event=e=>`data: ${JSON.stringify(e)}\n\n`;
function guide({replies,mode='setup',draft={status:'draft'},onApply=()=>{}}){const calls=[],state={draft,saves:0};
 const fetchImpl=async(url,opts={})=>{calls.push({url,opts,body:opts.body?JSON.parse(opts.body):null});if(url.endsWith('/status'))return Response.json({available:true});const next=replies.shift();return typeof next==='function'?next():next;};
 const root=fakeRoot();
 const close=installSetupAgent({root,api:'http://engine/api',mode,getDraft:()=>state.draft,onSave:s=>{state.draft={...state.draft,agent:s};state.saves++;},onApply,onBack(){},fetchImpl,pause:0});
 const $=sel=>root.querySelector(sel),type=text=>{const input=$('#agent-input');input.value=text;input.oninput({target:input});};
 const key=(shiftKey=false)=>{let prevented=false;$('#agent-input').onkeydown({key:'Enter',shiftKey,preventDefault(){prevented=true;}});return prevented;};
 return {root,$,calls,state,close,type,key,chats:()=>calls.filter(c=>c.url.endsWith('/chat'))};}

test('Enter sends and Shift+Enter starts a new line; IME composition never sends',()=>{
 assert.equal(composerKey({key:'Enter'}),'send');assert.equal(composerKey({key:'Enter',shiftKey:true}),'newline');
 assert.equal(composerKey({key:'Enter',isComposing:true}),null);assert.equal(composerKey({key:'Enter',keyCode:229}),null);assert.equal(composerKey({key:'a'}),null);
});

test('your message shows at once with typing dots, then the reply streams in after a humanised progress note',async()=>{
 const stream=controlledStream(),g=guide({replies:[stream.response]});await settle();
 g.type('We are in Ontario');
 assert.equal(g.key(true),false,'Shift+Enter keeps typing');assert.equal(g.chats().length,0);
 assert.equal(g.key(),true,'Enter sends');
 const log=g.$('#agent-log'),tail=g.$('#agent-tail'),input=g.$('#agent-input');
 assert.match(log.innerHTML,/agent-msg user"><span class="sr-only">You: <\/span><p>We are in Ontario<\/p>/,'optimistic bubble before any reply');
 assert.match(tail.innerHTML,/agent-typing[^]*agent-dots/,'typing indicator while waiting');
 assert.equal(input.value,'');assert.ok(input.focused>0,'composer keeps focus');assert.equal(g.$('#agent-send').disabled,true);
 assert.equal(g.state.draft.agent.messages.at(-1).content,'We are in Ontario','saved before the reply arrives');
 await tick();
 const sent=g.chats()[0];assert.match(sent.opts.headers.Accept,/text\/event-stream/);assert.deepEqual(sent.body.messages,[{role:'user',content:'We are in Ontario'}]);
 stream.push(event({type:'progress',stage:'inspect',labels:['Meter reading','Billing & collections']}));await settle();
 assert.match(tail.innerHTML,/agent-msg guide note[^]*Hey, I’ll look into those knobs — meter reading and billing &amp; collections…/);
 stream.push(event({type:'delta',text:'Got it — **Ont'}));await settle();
 assert.match(tail.innerHTML,/id="agent-stream"[^]*Got it — \*\*Ont/);assert.match(tail.innerHTML,/agent-dots/);
 stream.push(event({type:'progress',stage:'validate'}));await settle();assert.match(tail.innerHTML,/Making sure it all fits…/);
 stream.push(event({type:'delta',text:'ario**.'})+event({type:'done',schemaVersion:'setup-agent/1.0',message:'Got it — **Ontario**.',proposal:null}));stream.end();await settle();
 assert.match(log.innerHTML,/Got it — <strong>Ontario<\/strong>\./);assert.equal(tail.innerHTML,'');
 assert.deepEqual(g.state.draft.agent.messages.map(m=>m.note?'note':m.role),['user','note','assistant'],'the progress note stays in the conversation');
 assert.ok(log.innerHTML.indexOf('look into those knobs')<log.innerHTML.indexOf('<strong>Ontario'));
 g.close();
});

test('progress notes never reach the model, and a failed reply keeps your message with a Retry',async()=>{
 const g=guide({replies:[
  ()=>new Response(event({type:'progress',stage:'inspect',labels:[]})+event({type:'done',message:'Which city?',proposal:null}),{headers:{'content-type':'text/event-stream'}}),
  ()=>Response.json({detail:'Claude is busy or the provider limit was reached. Try again shortly.'},{status:429}),
  ()=>Response.json({schemaVersion:'setup-agent/1.0',message:'Thanks — **Cobourg** it is.',proposal:null})]});
 await settle();g.type('Ontario');g.key();await settle();
 g.type('Cobourg');g.key();await settle();
 assert.deepEqual(g.chats()[1].body.messages,[{role:'user',content:'Ontario'},{role:'assistant',content:'Which city?'},{role:'user',content:'Cobourg'}]);
 const tail=g.$('#agent-tail');
 assert.match(tail.innerHTML,/agent-msg guide error" role="alert">[^]*Claude is busy[^]*id="agent-retry"/);
 assert.match(g.$('#agent-log').innerHTML,/<p>Cobourg<\/p>/,'the sent text stays in the thread');
 assert.equal(g.state.draft.agent.messages.at(-1).content,'Cobourg');
 g.$('#agent-retry').onclick();await settle();
 assert.deepEqual(g.chats()[2].body.messages,g.chats()[1].body.messages,'retry resends the same conversation');
 assert.match(g.$('#agent-log').innerHTML,/Thanks — <strong>Cobourg<\/strong> it is\./,'plain JSON replies still work');assert.equal(tail.innerHTML,'');
 g.close();
});

test('a proposal arrives after a friendly lead-in, applies with progress bubbles, and the defaults chip keeps typed text',async()=>{
 const p={name:'Recovery',goals:['vee','reading'],summary:'A recovery plan.',townName:'Village',homes:480,region:'Ontario',asOf:'2026-05-28',episodes:[],assumptions:[],limitations:[],changes:[],settings:{}};
 const applied=[];
 const g=guide({replies:[()=>Response.json({message:'Here is a setup to review.',proposal:p}),()=>Response.json({proposal:{...p,name:'Recovery (checked)'}})],onApply:x=>applied.push(x)});
 await settle();g.type('half-typed thought');
 assert.match(g.$('#agent-quick').innerHTML,/Just use sensible defaults/);
 g.$('#agent-defaults').onclick();await settle();
 assert.equal(g.chats()[0].body.messages[0].content,USE_DEFAULTS);assert.equal(g.$('#agent-input').value,'half-typed thought');
 const log=g.$('#agent-log').innerHTML;
 assert.match(log,/Here is a setup to review\.[^]*agent-msg guide note"><span class="sr-only">Claude: <\/span><p>Great — okay, here’s what I’ll tweak:<\/p>/);
 assert.match(g.$('#agent-proposal').innerHTML,/PROPOSED SETUP · VALIDATED[^]*Use this setup →/);
 assert.equal(g.$('#agent-quick').innerHTML,'','no defaults shortcut while a proposal is waiting');
 const done=g.$('#agent-apply').onclick();assert.match(g.$('#agent-tail').innerHTML,/On it — giving those settings a final check…[^]*agent-dots/);
 await done;
 assert.equal(applied[0].name,'Recovery (checked)');assert.deepEqual(g.calls.find(c=>c.url.endsWith('/validate')).body.goals,['vee','reading'],'test goals travel with the reviewed proposal');
 assert.equal(g.state.draft.agent.messages.at(-1).content,'Done — your settings are in. Give them a quick review next.');assert.equal(g.state.draft.agent.proposal,null);
 g.close();
});

test('guide text renders light markdown and never trusts model HTML',()=>{
 const html=renderMarkdown('Hi <img src=x onerror=alert(1)> & "you"\n\n1. **Scale** — homes\n2. *Service* uses `rpa_coverage<1>`\n\n- a\n- keep process.rpa_coverage_x as is\n\n**<script>alert(1)</script>**');
 assert.ok(!/<img|<script/.test(html));assert.match(html,/<p>Hi &lt;img src=x onerror=alert\(1\)&gt; &amp; &quot;you&quot;<\/p>/);
 assert.match(html,/<ol><li><strong>Scale<\/strong> — homes<\/li><li><em>Service<\/em> uses <code>rpa_coverage&lt;1&gt;<\/code><\/li><\/ol>/);
 assert.match(html,/<ul><li>a<\/li><li>keep process.rpa_coverage_x as is<\/li><\/ul>/);
 assert.match(html,/<p><strong>&lt;script&gt;alert\(1\)&lt;\/script&gt;<\/strong><\/p>/);
 assert.equal(renderMarkdown('3. third\n   still third'),'<ol start="3"><li>third<br>still third</li></ol>');
 assert.equal(renderMarkdown('One\nTwo\n\nThree'),'<p>One<br>Two</p><p>Three</p>');
 assert.equal(renderMarkdown('5 * 3 * 2 and a_b_c'),'<p>5 * 3 * 2 and a_b_c</p>');
 const bubbles=logMarkup([{role:'user',content:'<b>me</b>'},{role:'assistant',content:'**hi**'},{role:'assistant',content:'<i>note</i>',note:true}]);
 assert.match(bubbles,/<p>&lt;b&gt;me&lt;\/b&gt;<\/p>/);assert.equal(bubbles.match(/agent-who/g).length,1,'one name per run of guide messages');
 assert.match(bubbles,/note"><span class="sr-only">Claude: <\/span><p>&lt;i&gt;note&lt;\/i&gt;<\/p>/);
 assert.match(tailMarkup({error:'<b>x</b>',canRetry:true}),/role="alert">[^]*&lt;b&gt;x&lt;\/b&gt;[^]*Retry/);
});

test('progress bubbles are short, humanised and deterministic',()=>{
 const labels=['Meter-to-cash process','VEE rules','Contact centre','Field work'];
 assert.equal(progressNote('inspect',{labels,turn:0}),'Hey, I’ll look into those knobs — meter-to-cash process, VEE rules and contact centre…');
 assert.equal(progressNote('inspect',{labels,turn:0}),progressNote('inspect',{labels,turn:3}),'same turn position, same words');
 assert.notEqual(progressNote('inspect',{labels,turn:1}),progressNote('inspect',{labels,turn:0}),'wording varies between turns');
 assert.equal(progressNote('inspect'),'Hey, I’ll look into those knobs…');
 assert.equal(progressNote('proposal'),'Great — okay, here’s what I’ll tweak:');
 assert.equal(progressNote('applied'),'Done — your settings are in. Give them a quick review next.');
 assert.equal(progressNote('applied',{inflict:true}),'Done — the new periods are in.');
 for(const stage of ['drafting','validate','repair','apply','running'])assert.ok(progressNote(stage).length<70,stage);
});

test('server-sent replies are read across arbitrary chunk boundaries, with in-band errors',async()=>{
 const text=event({type:'progress',stage:'inspect',labels:['Billing & collections']})+event({type:'delta',text:'Hel'})+event({type:'reset'})+event({type:'delta',text:'Hello\nthere'})+event({type:'done',schemaVersion:'setup-agent/1.0',message:'Hello\nthere',proposal:null});
 const chunks=[];for(let i=0;i<text.length;i+=7)chunks.push(text.slice(i,i+7));
 const response=new Response(new ReadableStream({start(c){for(const t of chunks)c.enqueue(new TextEncoder().encode(t));c.close();}}));
 const seen=[];const reply=await readAgentStream(response,e=>seen.push(e.type));
 assert.deepEqual(seen,['progress','delta','reset','delta']);assert.deepEqual(reply,{schemaVersion:'setup-agent/1.0',message:'Hello\nthere',proposal:null});
 await assert.rejects(readAgentStream(new Response(event({type:'error',status:504,detail:'Claude took too long to reply.'}))),/took too long/);
 await assert.rejects(readAgentStream(new Response(event({type:'delta',text:'Hal'}))),/interrupted/);
});

test('the setup guide opens on the selected test goals, or asks what to test',async()=>{
 const focused=guide({draft:{status:'draft',goals:['vee','reading']},replies:[]});await settle();
 assert.match(focused.$('#agent-log').innerHTML,/We’ll focus on validation &amp; estimation \(VEE\) and meter reading\. What outcome would you like to test/);assert.match(focused.root.innerHTML,/<li>What to test<\/li>/);focused.close();
 const open=guide({replies:[]});await settle();assert.match(open.$('#agent-log').innerHTML,/What would you like to test—operations day/);open.close();
});

test('the Year scenario guide keeps its context and suggested start in the chat',async()=>{
 const run={townRef:'village',settings:{},episodes:[{id:'EP-1'}],asOf:'2026-03-31',startDate:'2026-06-01',name:'Sim',region:'',purpose:''};
 const g=guide({mode:'inflict',draft:run,replies:[()=>Response.json({message:'How long should it last?',proposal:null})]});await settle();
 assert.match(g.$('#agent-log').innerHTML,/Suggested start: <strong>2026-06-01<\/strong> · 1 existing period kept/);
 assert.equal(g.$('#agent-quick').innerHTML,'');
 g.type('Half staff from June');g.key();await settle();
 assert.equal(g.chats()[0].body.mode,'inflict');assert.equal(g.chats()[0].body.currentRun.startDate,'2026-06-01');
 assert.match(g.$('#agent-log').innerHTML,/How long should it last\?/);
 g.close();
});

test('goal ids read as names in the guide', async () => {
 const {goalNames}=await import('../dist/setup-agent.js');
 assert.equal(goalNames(['vee','reading']),'validation & estimation (VEE) and meter reading');
 assert.equal(goalNames(['contact']),'the contact centre');
 assert.equal(goalNames(['a','b_c','fieldwork']),'a, b c and field work & maintenance');
});
