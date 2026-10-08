// Execute the shipped screen with controlled HTTP responses and a minimal DOM.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import vm from 'node:vm';

const source=await readFile(new URL('../utilsim/world/cruise.js',import.meta.url),'utf8');
const defaults={schemaVersion:'world-cruise/1',environmentId:'TEST',worldFingerprint:'saved-world',revision:7,
 through:'2026-01-05',targetDate:'2026-02-01',status:'paused',phase:'idle',error:null,
 managed:false,unavailableReason:null,fieldConfigured:true,workerEnabled:true,workerError:null,
 progress:{completedDays:4,totalDays:31,remainingDays:27}};
const settle=()=>new Promise(resolve=>setImmediate(resolve));
async function screen(overrides={},retained=null){
 const elements=new Map(),storage=new Map(),posted=[],timeouts=new Map();let timerId=0;
 let record={...defaults,...overrides},reply={ok:true,status:200,data:{status:'accepted'}},getError=null;
 if(retained)storage.set('world-cruise-pending:saved-world',JSON.stringify(retained));
 const element=id=>{
  if(!elements.has(id))elements.set(id,{value:id==='reason'?'Recovery scenario':'',disabled:false,hidden:false,textContent:'',className:''});
  return elements.get(id);
 };
 const context=vm.createContext({AbortController,
  document:{getElementById:element,visibilityState:'visible',addEventListener(){}},window:{addEventListener(){}},
  sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
  crypto:{randomUUID:()=>`request-${posted.length+1}`},setTimeout:callback=>{timeouts.set(++timerId,callback);return timerId;},
  clearTimeout:id=>timeouts.delete(id),
  fetch:async(_url,options)=>{
   if(options?.method==='POST'){posted.push(JSON.parse(options.body));return {ok:reply.ok,status:reply.status,json:async()=>reply.data};}
   if(getError)throw Error(getError);
   return {ok:true,status:200,json:async()=>({...record})};
  },
 });
 new vm.Script(source).runInContext(context);await settle();
 return {element,posted,storage,
  setRecord(value){record={...record,...value};},setReply(value){reply=value;},setGetError(value){getError=value;},
  async click(id){await element(id).onclick();await settle();},
  async start(){element('startForm').onsubmit({preventDefault(){}});await settle();}};
}

test('missing field binding blocks resume but permits safe idle cancellation request',async()=>{
 const ui=await screen({fieldConfigured:false,unavailableReason:'Configured field store or owner changed during cruise.'});
 assert.equal(ui.element('resume').disabled,true);
 assert.equal(ui.element('cancel').disabled,false);
 assert.equal(ui.element('reason').disabled,false);
 await ui.click('cancel');
 assert.equal(ui.posted.length,1);
 assert.equal(ui.posted[0].action,'cancel');
 assert.equal(ui.posted[0].expectedRevision,7);
 assert.equal(ui.posted[0].effectiveDate,'2026-01-05');
 assert.equal(ui.posted[0].worldFingerprint,'saved-world');
});

test('shared runtime added midrun permits pause and cancel without allowing new advancement',async()=>{
 const ui=await screen({status:'running',managed:true,unavailableReason:'Managed observation delivery is controlled by the shared runtime.'});
 assert.equal(ui.element('pause').disabled,false);assert.equal(ui.element('cancel').disabled,false);
 assert.equal(ui.element('start').disabled,true);assert.equal(ui.element('resume').disabled,true);
 await ui.click('pause');assert.equal(ui.posted[0].action,'pause');
 ui.setRecord({status:'paused',revision:8});await ui.click('refresh');
 assert.equal(ui.element('resume').disabled,true);await ui.click('resume');assert.equal(ui.posted.length,1);
 await ui.click('cancel');assert.equal(ui.posted[1].action,'cancel');assert.equal(ui.posted[1].expectedRevision,8);
});

test('retained cancellation remains retryable despite unavailable field configuration',async()=>{
 const retained={schemaVersion:'world-cruise/1',commandId:'lost-reply',environmentId:'TEST',worldFingerprint:'saved-world',
  actorId:'world-admin',expectedRevision:7,effectiveDate:'2026-01-05',action:'cancel',reason:'Original recovery request',causalReference:'test'};
 const ui=await screen({unavailableReason:'Restore the configured field store.'},retained);
 assert.equal(ui.element('retry').disabled,false);assert.equal(ui.element('cancel').disabled,true);
 await ui.click('retry');assert.deepEqual(ui.posted,[retained]);assert.equal(ui.storage.size,0);
});

test('backend refusal of unsafe pending-field cancellation remains visible and keeps saved ownership',async()=>{
 const ui=await screen({status:'failed',phase:'field-pending',unavailableReason:'Configured field store is missing.'});
 const error='Restore the original field store to reconcile committed visits before cancelling.';
 ui.setReply({ok:false,status:422,data:{error}});
 await ui.click('cancel');
 assert.equal(ui.posted[0].action,'cancel');assert.match(ui.element('message').textContent,/Restore the original field store/);
 assert.equal(ui.element('runState').textContent,'Needs attention');
 assert.equal(ui.element('cancel').disabled,false);assert.equal(ui.element('resume').disabled,true);
 assert.equal(ui.storage.size,0);
});

test('world identity change and failed refresh still block new cancellation',async()=>{
 const ui=await screen({unavailableReason:'Configured field store is missing.'});
 ui.setGetError('Status offline');await ui.click('refresh');
 assert.equal(ui.element('cancel').disabled,true);await ui.click('cancel');assert.equal(ui.posted.length,0);
 ui.setGetError(null);ui.setRecord({worldFingerprint:'another-world'});await ui.click('refresh');
 assert.equal(ui.element('cancel').disabled,true);await ui.click('cancel');assert.equal(ui.posted.length,0);
 assert.match(ui.element('message').textContent,/World identity changed/);
});

test('worker failure prevents start and resume but leaves cancellation available',async()=>{
 const ui=await screen({workerEnabled:false,workerError:'RuntimeError'});
 assert.equal(ui.element('resume').disabled,true);assert.equal(ui.element('cancel').disabled,false);
 await ui.click('resume');assert.equal(ui.posted.length,0);
 await ui.click('cancel');assert.equal(ui.posted[0].action,'cancel');
 ui.setRecord({status:'cancelled',revision:8});await ui.click('refresh');
 assert.equal(ui.element('start').disabled,true);await ui.start();assert.equal(ui.posted.length,1);
});
