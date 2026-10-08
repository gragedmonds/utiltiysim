// Actual field screen behavior with controlled HTTP/storage and a minimal DOM.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import vm from 'node:vm';

const source=await readFile(new URL('../utilsim/world/field_execution.js',import.meta.url),'utf8');
const names={plumbing:'skillPlumbing',electric:'skillElectric',gas:'skillGas',sewer:'skillSewer'};
const makeElement=(value='')=>({value,disabled:false,hidden:false,textContent:'',className:'',dataset:{},checked:false});
const crew={id:'crew-plumbing',revision:8,daily_capacity:2,weekdays:[1,3,6],skills:['plumbing','electric','gas','sewer']};
async function screen({crews=[crew],items=[],storage=new Map()}={}){
 const elements=Object.fromEntries(['message','retry','next','identity','today','crews','history','run','refresh','first',
  'assetLabel','operationHelp','operationSource'].map(id=>[id,makeElement()]));
 const weekdays={...makeElement(),options:[],append(option){this.options.push(option);option.remove=()=>{this.options=this.options.filter(item=>item!==option);};}};
 for(const value of ['0,1,2,3,4','0,1,2,3,4,5,6',''])weekdays.append(makeElement(value));
 elements.crew={elements:{crewId:makeElement('crew-plumbing'),dailyCapacity:makeElement('1'),weekdays,
  ...Object.fromEntries(Object.values(names).map(name=>[name,makeElement()]))}};
 elements.assignment={elements:{assignmentId:makeElement('A1'),crewId:makeElement('crew-plumbing'),
  operation:makeElement('repair-water-leak'),assetId:makeElement('water-meter'),orderId:makeElement('ORDER1'),
  orderRevision:makeElement('1'),scheduledDate:makeElement(),reportDelayDays:makeElement('2')}};
 const posted=[];let loseReply=false;
 let record={worldFingerprint:'fixture',ownerId:'field-owner',environmentId:'TEST',through:'2026-01-01',crews,items,nextAfter:null};
 const context=vm.createContext({document:{getElementById:id=>elements[id],querySelectorAll:()=>[
  ...Object.values(elements.crew.elements),...Object.values(elements.assignment.elements)],createElement:()=>makeElement()},
  sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
  crypto:{randomUUID:()=>`command-${posted.length+1}`},fetch:async(_url,options)=>{
   if(options?.method==='POST'){
    posted.push(JSON.parse(options.body));if(loseReply){loseReply=false;throw Error('Lost command response');}
    return {ok:true,json:async()=>({status:'accepted'})};
   }
   return {ok:true,json:async()=>record};
  }});
 await new vm.Script(`(async()=>{${source}\n})()`).runInContext(context);
 return {elements,posted,storage,loseNextReply(){loseReply=true;},setRecord(value){record={...record,...value};},
  async saveCrew(){await elements.crew.onsubmit({preventDefault(){},target:elements.crew});},
  async accept(){await elements.assignment.onsubmit({preventDefault(){},target:elements.assignment});},
  async retry(){await elements.retry.onclick();},async refresh(){await elements.refresh.onclick();}};
}

test('editable multiskill crew preserves custom weekdays, capacity and current revision',async()=>{
 const ui=await screen(),f=ui.elements.crew.elements;
 assert.ok(Object.values(names).every(name=>f[name].checked));assert.equal(f.weekdays.value,'1,3,6');
 assert.equal(f.dailyCapacity.value,2);assert.match(ui.elements.crews.textContent,/plumbing, electric, gas, sewer/);
 f.skillPlumbing.checked=false;f.skillGas.checked=false;await ui.saveCrew();
 assert.deepEqual(ui.posted[0].skills,['electric','sewer']);assert.deepEqual(ui.posted[0].weekdays,[1,3,6]);
 assert.equal(ui.posted[0].expectedRevision,8);assert.equal(ui.posted[0].dailyCapacity,2);
 ui.setRecord({crews:[{...crew,revision:9,skills:['electric','sewer'],weekdays:[6,5],daily_capacity:4}]});await ui.refresh();
 assert.equal(f.weekdays.value,'6,5');assert.equal(f.dailyCapacity.value,4);assert.equal(f.skillPlumbing.checked,false);
 await ui.saveCrew();assert.deepEqual(ui.posted[1].skills,['electric','sewer']);assert.deepEqual(ui.posted[1].weekdays,[6,5]);
 assert.equal(ui.posted[1].expectedRevision,9);
});

test('saved empty skills and offshift capacity stay empty; a genuinely new crew defaults to plumbing',async()=>{
 const ui=await screen({crews:[{...crew,skills:[],weekdays:[],daily_capacity:0}]}),f=ui.elements.crew.elements;
 assert.ok(Object.values(names).every(name=>!f[name].checked));assert.equal(f.weekdays.value,'');
 await ui.saveCrew();assert.deepEqual(ui.posted[0].skills,[]);assert.deepEqual(ui.posted[0].weekdays,[]);
 assert.equal(ui.posted[0].dailyCapacity,0);
 f.crewId.value='new-crew';f.crewId.onchange();assert.equal(f.skillPlumbing.checked,true);
 assert.ok(['skillElectric','skillGas','skillSewer'].every(name=>!f[name].checked));
 await ui.saveCrew();assert.deepEqual(ui.posted[1].skills,['plumbing']);assert.equal(ui.posted[1].expectedRevision,0);
});

test('all four operations submit exact target identity and expose correct source inspection',async()=>{
 const ui=await screen(),f=ui.elements.assignment.elements;
 const cases=[['repair-water-leak','water-meter','Water service meter ID','/water-faults'],
  ['restore-electric-supply','electric-edge','Electric network edge ID','/network-faults?commodity=electric'],
  ['restore-gas-supply','gas-edge','Gas network edge ID','/network-faults?commodity=gas'],
  ['clear-sewer-blockage','SEWER-SP-stable','Sewer service point ID','/sewer']];
 for(const [i,[operation,target,label,url]] of cases.entries()){
  f.operation.value=operation;f.operation.onchange();assert.equal(f.assetId.value,'');
  assert.equal(ui.elements.assetLabel.textContent,label);assert.equal(ui.elements.operationSource.href,url);
  f.assetId.value=target;f.assignmentId.value=`A${i}`;await ui.accept();
  assert.equal(ui.posted[i].operation,operation);assert.equal(ui.posted[i].assetId,target);
  assert.equal(ui.posted[i].reportDelayDays,2);assert.equal(ui.posted[i].actorId,'world-admin');
  assert.equal(ui.posted[i].schemaVersion,'field-world-execution/1');
  assert.equal(Object.hasOwn(ui.posted[i],'faultId'),false);
 }
 assert.match(ui.elements.operationHelp.textContent,/No sewer meter/);
});

test('lost multiskill configure reply restores exact pending form and retries same command after reload',async()=>{
 const ui=await screen(),f=ui.elements.crew.elements;
 f.skillPlumbing.checked=false;f.skillElectric.checked=false;f.weekdays.value='0,1,2,3,4,5,6';f.dailyCapacity.value='7';
 ui.loseNextReply();await ui.saveCrew();const original=ui.posted[0];
 assert.equal(ui.elements.retry.hidden,false);assert.equal(ui.storage.size,1);
 const reopened=await screen({storage:ui.storage}),restored=reopened.elements.crew.elements;
 assert.equal(restored.skillPlumbing.checked,false);assert.equal(restored.skillElectric.checked,false);
 assert.equal(restored.skillGas.checked,true);assert.equal(restored.skillSewer.checked,true);
 assert.equal(restored.weekdays.value,'0,1,2,3,4,5,6');assert.equal(Number(restored.dailyCapacity.value),7);
 await reopened.retry();assert.deepEqual(reopened.posted[0],original);assert.equal(reopened.storage.size,0);
});

test('lost gas assignment reply restores its target label and retries its original operation after reload',async()=>{
 const ui=await screen(),f=ui.elements.assignment.elements;
 f.operation.value='restore-gas-supply';f.operation.onchange();f.assetId.value='saved-gas-edge';
 ui.loseNextReply();await ui.accept();const original=ui.posted[0];
 const reopened=await screen({storage:ui.storage});
 assert.equal(reopened.elements.assignment.elements.operation.value,'restore-gas-supply');
 assert.equal(reopened.elements.assignment.elements.assetId.value,'saved-gas-edge');
 assert.equal(reopened.elements.assetLabel.textContent,'Gas network edge ID');
 await reopened.retry();assert.deepEqual(reopened.posted[0],original);
});

test('assignment rows display operation and required skill without changing shared capacity',async()=>{
 const operations=['repair-water-leak','restore-electric-supply','restore-gas-supply','clear-sewer-blockage'];
 const items=operations.map((operation,index)=>({state:'accepted',messages:[],result:null,assignment:{operation,
  assignmentId:`A${index}`,orderId:`O${index}`,orderRevision:1,assetId:`target${index}`,crewId:'crew-plumbing',scheduledDate:'2026-01-01'}}));
 const ui=await screen({items});
 for(const skill of Object.keys(names))assert.ok(ui.elements.history.innerHTML.includes(`Skill: ${skill}`));
 for(const label of ['Repair water leak','Restore electric supply','Restore gas supply','Clear sewer blockage'])assert.ok(ui.elements.history.innerHTML.includes(label));
 assert.match(ui.elements.crews.textContent,/2 visits\/day shared across/);
});

test('late manual reports use message schema instead of immutable visit result report ID',async()=>{
 const item={state:'executed',assignment:{operation:'repair-water-leak',assignmentId:'A1',orderId:'O1',orderRevision:1,
  assetId:'water',crewId:'crew-plumbing',scheduledDate:'2026-01-01'},
  result:{outcome:'completed',effectiveDate:'2026-01-01',reportId:null},messages:[
   {id:'ack',schema:'field-ack/1',state:'received',available_day:'2026-01-01',attempts:1},
   {id:'manual-report',schema:'field-report/1',state:'pending',available_day:'2026-01-04',attempts:0}]};
 const ui=await screen({items:[item]});
 assert.equal((ui.elements.history.innerHTML.match(/Dispatch acknowledgement:/g)||[]).length,1);
 assert.equal((ui.elements.history.innerHTML.match(/Report:/g)||[]).length,1);
 assert.equal(item.result.reportId,null);
});
