// Execute the shipped administrator screen with controlled HTTP and session storage.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import vm from 'node:vm';

const source=await readFile(new URL('../utilsim/world/field_reporting.js',import.meta.url),'utf8');
const html=await readFile(new URL('../utilsim/world/field_reporting.html',import.meta.url),'utf8');
const item=(id='A1',overrides={})=>({assignment:{assignmentId:id,operation:'repair-water-leak',assetId:'WATER1',
 crewId:'crew-plumbing',orderId:'ORDER1',orderRevision:3,scheduledDate:'2026-01-02',reportDelayDays:2},
 state:'accepted',actualOutcome:null,claimedOutcome:null,policyRevision:0,reportMode:'automatic',workMode:'perform',
 visitDate:null,reportId:null,reportAvailableDate:null,reportTransport:null,canConfigure:true,canSubmit:false,
 submitActorId:'crew-plumbing',...overrides});
const manual=()=>item('A1',{state:'executed',actualOutcome:'not_attempted',policyRevision:2,reportMode:'manual',
 workMode:'inspect-only',visitDate:'2026-01-02',canConfigure:false,canSubmit:true});
const key='field-reporting-pending:'+JSON.stringify(['TEST','saved-world','field-owner']);
async function screen({items=[item()],storage=new Map(),nextAfter=null}={}){
 const elements=new Map(),posted=[],reads=[],timers=new Map();let timerId=0,mode='ok',readError=null;
 let record={schemaVersion:'field-reporting/1',modelVersion:'field-reporting/1',environmentId:'TEST',worldFingerprint:'saved-world',
  ownerId:'field-owner',actorId:'world-admin',through:'2026-01-04',items,nextAfter};
 const element=id=>{
  assert.ok(html.includes(`id="${id}"`),`Shipped HTML must contain #${id}`);
  if(!elements.has(id))elements.set(id,{value:id==='claimedOutcome'?'completed':'',disabled:false,hidden:false,textContent:'',innerHTML:'',className:''});
  return elements.get(id);
 };
 const context=vm.createContext({AbortController,document:{getElementById:element},
  sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>{if(mode==='storage-fail')throw Error('Storage unavailable');storage.set(k,v);},removeItem:k=>storage.delete(k)},
  crypto:{randomUUID:()=>`command-${posted.length+1}`},setTimeout:callback=>{timers.set(++timerId,callback);return timerId;},clearTimeout:id=>timers.delete(id),
  fetch:async(url,options)=>{
   if(options?.method==='POST'){
    posted.push(JSON.parse(options.body));
    if(mode==='lost')throw Error('Lost response');
    if(mode==='timeout'){const error=Error('Timed out');error.name='AbortError';throw error;}
    if(mode==='reject')return {ok:false,status:409,json:async()=>({error:'Policy revision changed.'})};
    return {ok:true,status:200,json:async()=>({status:'completed'})};
   }
   reads.push(url);if(readError)throw Error(readError);
   return {ok:true,status:200,json:async()=>structuredClone(record)};
  }});
 await new vm.Script(`(async()=>{${source}\n})()`).runInContext(context);
 return {element,posted,reads,storage,timers,setMode(value){mode=value;},setReadError(value){readError=value;},setRecord(value){record={...record,...value};},
  async click(id){await element(id).onclick();},async configure(){await element('policyForm').onsubmit({preventDefault(){}});},
  async submit(){await element('reportForm').onsubmit({preventDefault(){}});},select(id){element('assignmentSelect').value=id;element('assignmentSelect').onchange();}};
}

test('legacy automatic assignments remain default; configure uses revision and admin identity',async()=>{
 const ui=await screen();
 assert.equal(ui.element('reportMode').value,'automatic');assert.equal(ui.element('workMode').value,'perform');
 assert.equal(ui.element('workMode').disabled,true);assert.equal(ui.element('submitReport').disabled,true);
 ui.element('reportMode').value='manual';ui.element('reportMode').onchange();ui.element('workMode').value='inspect-only';
 await ui.configure();
 assert.deepEqual(ui.posted[0],{schemaVersion:'field-reporting/1',commandId:'command-1',environmentId:'TEST',worldFingerprint:'saved-world',
  actorId:'world-admin',effectiveDate:'2026-01-04',action:'configure',causalReference:'local-field-reporting-admin',assignmentId:'A1',
  expectedRevision:0,reportMode:'manual',workMode:'inspect-only'});
 assert.equal(ui.timers.size,0);
});

test('actual nonrepair and false completion remain separate; submission uses assigned crew',async()=>{
 const ui=await screen({items:[manual()]});
 assert.match(ui.element('physicalResult').textContent,/repair not attempted/);
 assert.match(ui.element('reportStatus').textContent,/Awaiting crew submission/);
 assert.equal(ui.element('configure').disabled,true);assert.equal(ui.element('submitReport').disabled,false);
 await ui.configure();assert.equal(ui.posted.length,0);
 await ui.submit();assert.equal(ui.posted[0].actorId,'crew-plumbing');assert.equal(ui.posted[0].outcome,'completed');
 assert.equal(ui.posted[0].expectedRevision,2);assert.equal(Object.hasOwn(ui.posted[0],'actualOutcome'),false);
 assert.equal(Object.hasOwn(ui.posted[0],'observations'),false);
 ui.setRecord({items:[{...manual(),claimedOutcome:'completed',reportId:'REPORT1',reportAvailableDate:'2026-01-06',canSubmit:false,
  reportTransport:{state:'received',attempts:2,lastError:null}}]});await ui.click('refresh');
 assert.match(ui.element('physicalResult').textContent,/repair not attempted/);
 assert.match(ui.element('reportStatus').textContent,/Submitted claim: completed/);
 assert.match(ui.element('transportStatus').textContent,/Transport receipt recorded/);
 assert.match(ui.element('transportStatus').textContent,/not enterprise acceptance/);
 await ui.submit();assert.equal(ui.posted.length,1);
});

test('lost configure response survives reload and retries original payload after policy changes',async()=>{
 const ui=await screen();ui.element('reportMode').value='manual';ui.element('reportMode').onchange();ui.element('workMode').value='inspect-only';
 ui.setMode('lost');await ui.configure();const original=ui.posted[0];
 assert.equal(ui.element('retry').hidden,false);assert.equal(ui.element('assignmentSelect').disabled,true);
 const reopened=await screen({storage:ui.storage,items:[item('A1',{policyRevision:1,reportMode:'manual',workMode:'inspect-only'})]});
 assert.equal(reopened.element('workMode').value,'inspect-only');
 await reopened.click('retry');assert.deepEqual(reopened.posted,[original]);assert.equal(reopened.storage.size,0);
});

test('lost report response survives reload after report exists and retries exact original claim',async()=>{
 const ui=await screen({items:[manual()]});ui.element('claimedOutcome').value='not_found';ui.setMode('timeout');await ui.submit();
 assert.match(ui.element('message').textContent,/timed out/);const original=ui.posted[0];
 const reopened=await screen({storage:ui.storage,items:[{...manual(),claimedOutcome:'not_found',reportId:'REPORT1',canSubmit:false}]});
 assert.equal(reopened.element('claimedOutcome').value,'not_found');assert.equal(reopened.element('submitReport').disabled,true);
 assert.equal(reopened.element('retry').disabled,false);await reopened.click('retry');assert.deepEqual(reopened.posted,[original]);
});

test('pagination selects only loaded assignments while pending retry retains offpage identity',async()=>{
 const ui=await screen({items:[item('A1'),item('A2')],nextAfter:25});ui.select('A2');
 await ui.configure();assert.equal(ui.posted[0].assignmentId,'A2');
 ui.setRecord({items:[item('A26')],nextAfter:50});await ui.click('next');
 assert.equal(ui.element('assignmentSelect').value,'A26');assert.equal(ui.reads.at(-1),'/api/field-reporting?limit=25&after=25');
 ui.setMode('lost');await ui.configure();const original=ui.posted.at(-1);
 const reopened=await screen({storage:ui.storage});assert.match(reopened.element('pendingDetails').textContent,/A26/);
 await reopened.click('retry');assert.deepEqual(reopened.posted,[original]);
});

test('read failure blocks commands until refresh; world or owner changes block retained retries',async()=>{
 const ui=await screen();ui.setReadError('Status unavailable');await ui.click('refresh');
 assert.equal(ui.element('configure').disabled,true);assert.equal(ui.element('refresh').disabled,false);
 await ui.configure();assert.equal(ui.posted.length,0);
 ui.setReadError(null);await ui.click('refresh');assert.equal(ui.element('configure').disabled,false);
 ui.setMode('lost');await ui.configure();ui.setRecord({ownerId:'different-owner'});await ui.click('refresh');
 assert.match(ui.element('message').textContent,/owner changed/);assert.equal(ui.element('retry').disabled,true);
 await ui.click('retry');assert.equal(ui.posted.length,1);
});

test('rejected command is visible and releases retry; unavailable storage prevents mutation',async()=>{
 const ui=await screen();ui.setMode('reject');await ui.configure();
 assert.match(ui.element('message').textContent,/Policy revision changed/);assert.equal(ui.storage.size,0);
 assert.equal(ui.element('retry').hidden,true);
 ui.setMode('storage-fail');await ui.configure();assert.equal(ui.posted.length,1);assert.equal(ui.element('configure').disabled,true);
 const corrupt=await screen({storage:new Map([[key,'{"action":"submit"}']])});
 assert.match(corrupt.element('message').textContent,/retained commands safely/);await corrupt.submit();assert.equal(corrupt.posted.length,0);
});

test('selection hydrates saved policy, prevents automatic inspect-only, and escapes labels',async()=>{
 const second=item('A<&2',{policyRevision:5,reportMode:'manual',workMode:'inspect-only'});
 const ui=await screen({items:[item(),second]});ui.select('A<&2');
 assert.equal(ui.element('reportMode').value,'manual');assert.equal(ui.element('workMode').value,'inspect-only');
 ui.element('reportMode').value='automatic';ui.element('reportMode').onchange();assert.equal(ui.element('workMode').value,'perform');
 assert.match(ui.element('history').innerHTML,/A&lt;&amp;2/);assert.doesNotMatch(ui.element('history').innerHTML,/A<&2/);
 await ui.configure();assert.equal(ui.posted[0].expectedRevision,5);
 assert.equal(ui.posted[0].assignmentId,'A<&2');
});

test('empty or unconfigured owner has refresh recovery and no automatic mutation',async()=>{
 const ui=await screen({items:[]});assert.equal(ui.element('configure').disabled,true);assert.equal(ui.element('submitReport').disabled,true);
 await ui.configure();await ui.submit();assert.equal(ui.posted.length,0);assert.match(ui.element('assignmentDetails').textContent,/No accepted assignments/);
 ui.setRecord({items:[manual()]});await ui.click('refresh');assert.equal(ui.element('submitReport').disabled,false);
 assert.ok(ui.reads.every(url=>url.startsWith('/api/field-reporting?limit=25&after=')));
});

test('world-committed visit awaiting field recovery is shown as actual work and can submit once',async()=>{
 const ui=await screen({items:[{...manual(),state:'accepted'}]});
 assert.match(ui.element('physicalResult').textContent,/repair not attempted/);
 assert.match(ui.element('reportStatus').textContent,/Awaiting crew submission/);
 assert.equal(ui.element('configure').disabled,true);assert.equal(ui.element('submitReport').disabled,false);
 await ui.submit();assert.equal(ui.posted.length,1);assert.equal(ui.posted[0].action,'submit');
});

test('phase results and submitted claims describe the assigned stage without asserting repair or full supply',async()=>{
 for(const [operation,label] of [['isolate-water-main','Isolation completed'],['repair-water-main','Main repaired; valves remain closed'],['restore-water-main','Restoration completed; wider supply not verified']]){
  const saved={...manual(),assignment:{...manual().assignment,operation},actualOutcome:'completed',claimedOutcome:'completed',reportId:'phase-report',canSubmit:false,phase:{predecessorAssignmentId:'preceding-phase'}};
  const ui=await screen({items:[saved]});
  assert.ok(ui.element('physicalResult').textContent.includes(label));assert.ok(ui.element('reportStatus').textContent.includes(label));
  assert.ok(ui.element('completedClaim').textContent.includes(label));assert.match(ui.element('phaseDetails').textContent,/preceding-phase/);
  assert.ok(ui.element('history').innerHTML.includes(label));assert.doesNotMatch(ui.element('physicalResult').textContent,/Repair completed/);
 }
});

test('false phase completion remains a claim and pending successor displays physical blocker',async()=>{
 const saved={...manual(),assignment:{...manual().assignment,operation:'isolate-water-main'},claimedOutcome:'completed',reportId:'false-report',canSubmit:false,phase:{predecessorAssignmentId:null}};
 const ui=await screen({items:[saved]});assert.match(ui.element('physicalResult').textContent,/assigned phase not performed/);
 assert.match(ui.element('reportStatus').textContent,/Isolation completed/);
 const waiting={...item(),assignment:{...item().assignment,operation:'repair-water-main'},phase:{predecessorAssignmentId:'isolation-1'},blockedReason:'Waiting for committed physical predecessor.'};
 ui.setRecord({items:[waiting]});await ui.click('refresh');
 assert.match(ui.element('phaseDetails').textContent,/Waiting for committed physical predecessor/);
 assert.equal(ui.element('submitReport').disabled,true);
});
