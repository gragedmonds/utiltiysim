import test from 'node:test';
import assert from 'node:assert/strict';
import {LocalPlan,patternSeed,seedPatterns,episodeInput,revisionChanges,runPlan} from '../dist/local-year.js';
import {SimulationLibrary} from '../dist/simulation-library.js';
import {episodeDates} from '../dist/m2c.js';
import {draftEpisode,strikeDraft,episodeStrikes,episodeSpans} from '../dist/year-page.js';
import {proposalInput} from '../dist/setup-agent.js';
function memory(){const m=new Map();return {get length(){return m.size;},key:i=>[...m.keys()][i],getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v),removeItem:k=>m.delete(k)};}
const HEADEND={id:'headend_hiccups',title:'Head-end hiccups',episodes:[{title:'Head end down',startOffset:0,durationDays:182,ramp:0,settings:{reading:{ami_missed_read:0.9}},pattern:{kind:'spikes',count:6,length:[1,2],strength:[0.7,1]}}]};
const STAFF={id:'half_staff',title:'Half staff',episodes:[{title:'Half the analysts',startOffset:0,durationDays:30,ramp:0,settings:{process:{analysts:'*0.5'}}}]};
// A large local simulation as the guided setup saves it (execution 'local', 25,000 homes).
function localModel(extra={}){const library=new SimulationLibrary(memory()),s=library.save({...library.create(),id:'model-a',name:'Regional utility',status:'ready',execution:'local',preset:'small_town',townRef:'small_town',homes:25000,totalHomes:25000,summary:'Year scenarios',...extra});return {library,s};}
// As the panel inflicts a scenario: its episodes for the day, through the "When it strikes" controls.
const inflictDraft=(sc,day)=>episodeDates(sc,day).map(d=>draftEpisode({...d,to:d.to||'',strike:strikeDraft(d.pattern)}).episode);
const reply=(status,body)=>({ok:status<300,status,json:async()=>body});

test('sporadic episodes of a local simulation share one pattern seed; steady ones and own seeds are kept',()=>{
 assert.equal(patternSeed('model-a'),'local:model-a');assert.equal(patternSeed('x'.repeat(100)).length,64);
 const steady={title:'Steady',from:'2026-02-01',to:null,settings:{process:{analysts:1}}},own={title:'Own',from:'2026-03-01',settings:{},pattern:{kind:'days',share:.2,seed:'mine'}},plain={title:'Plain',from:'2026-01-05',settings:{},pattern:{kind:'spikes',count:2}};
 const out=seedPatterns([steady,own,plain],'model-a');
 assert.equal(out[0],steady);assert.ok(!('pattern' in out[0]));assert.equal(out[1],own);assert.deepEqual(out[2].pattern,{kind:'spikes',count:2,seed:'local:model-a'});
 assert.ok(!('seed' in plain.pattern),'the caller\'s episode is not changed');assert.deepEqual(seedPatterns(undefined,'m'),[]);
});

test('the plan client keeps the year\'s episodes with the simulation: ids, order, seeds, saves',()=>{
 const {library}=localModel();let saves=0;const plan=new LocalPlan({library,id:'model-a',onSave:()=>saves++});
 assert.equal(plan.year,2026);assert.equal(plan.readOnly,false);assert.equal(plan.townRef,'small_town');assert.deepEqual(plan.episodes,[]);
 const [hiccups]=inflictDraft(HEADEND,'2026-01-12').map(ep=>plan.addEpisode(ep)),[half]=inflictDraft(STAFF,'2026-01-05').map(ep=>plan.addEpisode(ep));
 assert.deepEqual([hiccups.id,half.id],['EP-1','EP-2']);assert.deepEqual(plan.episodes.map(e=>e.id),['EP-2','EP-1'],'sorted by start');
 assert.deepEqual(hiccups.pattern,{kind:'spikes',count:6,length:[1,2],strength:[0.7,1],workdays:true,independent:false,seed:'local:model-a'});
 assert.ok(!('pattern' in half));assert.equal(saves,2);assert.deepEqual(library.get('model-a').episodes,plan.episodes);
 // Edit: a new pattern is seeded again; null makes it steady; a patch without the key keeps it.
 plan.updateEpisode('EP-1',{pattern:{kind:'days',share:.2,strength:[1,1],workdays:true,independent:false}});assert.equal(library.get('model-a').episodes[1].pattern.seed,'local:model-a');
 plan.updateEpisode('EP-1',{title:'Head end down (edited)'});assert.equal(plan.episodes[1].pattern.share,.2);
 plan.updateEpisode('EP-2',{pattern:null});assert.ok(!('pattern' in plan.episodes[0]));
 plan.setAsOf('2026-07-11');assert.equal(library.get('model-a').asOf,'2026-07-11');
 assert.equal(plan.removeEpisode('EP-2'),true);assert.equal(plan.removeEpisode('EP-2'),false);
 assert.equal(plan.addEpisode(inflictDraft(STAFF,'2026-04-06')[0]).id,'EP-2','the highest id plus one, as the Command Center\'s client');
 plan.clearEpisodes();assert.deepEqual(library.get('model-a').episodes,[]);
 // A simulation rebuilt from a job's recipe has episodes without ids (and steady ones with pattern null).
 const rebuilt=localModel({episodes:[{title:'A',from:'2026-02-02',to:null,ramp:0,settings:{},pattern:null},{id:'EP-4',title:'B',from:'2026-01-05',to:null,ramp:0,settings:{}}]});
 const again=new LocalPlan({library:rebuilt.library,id:'model-a'});assert.deepEqual(again.episodes.map(e=>[e.id,e.title,'pattern' in e]),[['EP-4','B',false],['EP-5','A',false]]);
 assert.throws(()=>new LocalPlan({library,id:'missing'}),/no longer in this browser/);
});

test('the plan asks the engine for the days struck (no run) and the calendar matches them like the trend\'s',async()=>{
 const {library}=localModel();const calls=[];let answer=null;
 const fetchImpl=async(url,init)=>{calls.push([url,init&&JSON.parse(init.body)]);return answer;};
 const plan=new LocalPlan({library,id:'model-a',api:'http://engine/api',fetchImpl});
 assert.deepEqual(await plan.preview(),{episodes:[]});assert.equal(calls.length,0,'nothing to ask');
 const ep=plan.addEpisode(inflictDraft(HEADEND,'2026-01-12')[0]);
 answer=reply(200,{schemaVersion:'m2c-episode-preview/1.0',year:2026,episodes:[{id:ep.id,title:ep.title,from:ep.from,to:ep.to,pattern:{...ep.pattern},hits:[['2026-01-20',0.81],['2026-03-03',1]]}]});
 const preview=await plan.preview();
 assert.equal(calls[0][0],'http://engine/api/m2c/episodes/preview');assert.deepEqual(calls[0][1],{town:'small_town',year:2026,episodes:[{id:'EP-1',title:'Head end down',from:'2026-01-12',to:'2026-07-12',ramp:0,settings:{reading:{ami_missed_read:0.9}},pattern:ep.pattern}]});
 assert.deepEqual(episodeStrikes(preview,plan.episodes).get('EP-1'),[['2026-01-20',0.81],['2026-03-03',1]]);
 await plan.preview();assert.equal(calls.length,1,'the same episodes are asked once');
 // An edited pattern (another shape) no longer matches an older answer: its days are not drawn from it.
 plan.updateEpisode('EP-1',{pattern:{kind:'days',share:.2,strength:[1,1],workdays:true,independent:false}});assert.equal(episodeStrikes(preview,plan.episodes).size,0);
 assert.equal(episodeSpans(plan.episodes,1).length,1);
 answer=reply(422,{detail:'episode EP-1: 9 spikes do not fit in 3 working days'});
 await assert.rejects(plan.preview(),e=>e.status===422&&e.detail==='episode EP-1: 9 spikes do not fit in 3 working days');
 // A reply that lands after a newer request is dropped.
 let release;const slow=new Promise(r=>release=r);let n=0;
 plan.fetchImpl=async()=>{n++;if(n===1){await slow;}return reply(200,{episodes:[]});};
 plan.updateEpisode('EP-1',{title:'One'});const first=plan.preview();plan.updateEpisode('EP-1',{title:'Two'});const second=plan.preview();release();
 await assert.rejects(first,e=>e.superseded);assert.deepEqual(await second,{episodes:[]});
});

test('a change since the latest revision makes a new revision to run; no change: it is up to date',()=>{
 const {library}=localModel();const plan=new LocalPlan({library,id:'model-a'});
 const current=()=>{const p=proposalInput(library.get('model-a'));return {...p,episodes:seedPatterns(p.episodes,'model-a'),totalHomes:25000};};
 // The recipe's proposal as prepare_recipe writes it: the pydantic defaults filled in, no ids, steady pattern null.
 const recipeOf=p=>({modelId:'model-a',proposal:{execution:'local',goals:['everything'],purpose:'',region:'',seed:'',asOf:'2026-03-31',townOverrides:{},settings:{},operations:{},assumptions:[],limitations:[],...p,episodes:(p.episodes||[]).map(ep=>({to:null,ramp:0,pattern:null,...ep}))}});
 const job=(revision,p)=>({jobId:'job'+revision,revision,status:'manual',recipe:recipeOf(p)});
 let rp=runPlan([],'model-a',current());assert.equal(rp.next,1);assert.equal(rp.upToDate,false);assert.match(rp.message,/Run revision 1 to download/);
 const one=job(1,current());rp=runPlan([one,{...job(9,current()),recipe:{...recipeOf(current()),modelId:'other'}}],'model-a',current());
 assert.equal(rp.latest,one);assert.equal(rp.upToDate,true);assert.deepEqual(rp.changes,[]);assert.match(rp.message,/Revision 1 is up to date/);
 plan.addEpisode(inflictDraft(HEADEND,'2026-01-12')[0]);plan.setAsOf('2026-07-12');
 rp=runPlan([one],'model-a',current());assert.equal(rp.next,2);assert.deepEqual(rp.changes,['Head end down added','results through 12 Jul 2026']);
 assert.equal(rp.message,'Changed since revision 1: Head end down added; results through 12 Jul 2026. Run revision 2 to download the new job.');
 assert.match(runPlan([one],'model-a',current(),{sync:true}).message,/Run revision 2 to queue the new job\.$/);
 const two=job(2,current());assert.equal(runPlan([one,two],'model-a',current()).upToDate,true,'the job JSON round trip keeps it equal');
 assert.equal(runPlan([one,JSON.parse(JSON.stringify(two))],'model-a',current()).upToDate,true);
 plan.updateEpisode('EP-1',{pattern:{kind:'days',share:.2,strength:[1,1],workdays:true,independent:false}});
 assert.deepEqual(runPlan([one,two],'model-a',current()).changes,['Head end down changed']);
 plan.removeEpisode('EP-1');assert.deepEqual(runPlan([one,two],'model-a',current()).changes,['Head end down removed']);
 // Other inputs, and a revision whose sporadic pattern had no seed (its districts struck different days).
 assert.deepEqual(revisionChanges({...current(),settings:{process:{analysts:3}},totalHomes:50000},recipeOf(current()).proposal),['homes changed','run settings changed']);
 const unseeded={...current(),episodes:[{title:'X',from:'2026-02-02',settings:{},pattern:{kind:'days',share:.2}}]};
 assert.deepEqual(revisionChanges({...unseeded,episodes:seedPatterns(unseeded.episodes,'model-a')},unseeded),['X changed']);
 assert.deepEqual(episodeInput({title:'T',from:'2026-01-01',settings:{a:{b:1}}}),{title:'T',from:'2026-01-01',to:null,ramp:0,settings:{a:{b:1}},pattern:null});
});
