// Viewer-independent regression: run the actual screen script with a tiny DOM.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import vm from 'node:vm';

const source=await readFile(new URL('../utilsim/world/field_execution.js',import.meta.url),'utf8');
function element(value=''){return {value,disabled:false,hidden:false,textContent:'',className:'',dataset:{}};}
async function screen(crews){
 const elements=Object.fromEntries(['message','retry','next','identity','today','crews','history','run','refresh','first'].map(id=>[id,element()]));
 const weekdays={...element('0,1,2,3,4'),options:[],append(option){this.options.push(option);option.remove=()=>{this.options=this.options.filter(item=>item!==option);};}};
 for(const value of ['0,1,2,3,4','0,1,2,3,4,5,6',''])weekdays.append(element(value));
 elements.crew={elements:{crewId:element('crew-plumbing'),dailyCapacity:element('1'),weekdays}};
 elements.assignment={elements:{scheduledDate:element()}};
 const posted=[];
 let record={worldFingerprint:'fingerprint',ownerId:'field-owner',environmentId:'run',through:'2026-01-01',crews,items:[],nextAfter:null};
 const context=vm.createContext({
  document:{getElementById:id=>elements[id],querySelectorAll:()=>[],createElement:()=>element()},
  sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},crypto:{randomUUID:()=>`command-${posted.length}`},
  fetch:async(_path,options)=>{if(options?.method==='POST'){posted.push(JSON.parse(options.body));return {ok:true,json:async()=>({status:'completed'})};}return {ok:true,json:async()=>record};},
 });
 await new vm.Script(`(async()=>{${source}\n})()`).runInContext(context);
 return {elements,posted,setRecord(value){record={...record,...value};},
  async save(){await elements.crew.onsubmit({preventDefault(){},target:elements.crew});},
  async refresh(){await elements.refresh.onclick();}};
}

test('saved every-day crew capacity and schedule load and survive a save',async()=>{
 const ui=await screen([{id:'crew-plumbing',revision:4,daily_capacity:7,weekdays:[0,1,2,3,4,5,6],skills:['plumbing']}]);
 assert.equal(Number(ui.elements.crew.elements.dailyCapacity.value),7);
 assert.equal(ui.elements.crew.elements.weekdays.value,'0,1,2,3,4,5,6');
 await ui.save();
 assert.equal(ui.posted[0].dailyCapacity,7);
 assert.deepEqual(ui.posted[0].weekdays,[0,1,2,3,4,5,6]);
 assert.equal(ui.posted[0].expectedRevision,4);
});

test('selecting custom or off-shift crew preserves exact days and zero capacity',async()=>{
 const crews=[{id:'crew-plumbing',revision:1,daily_capacity:7,weekdays:[0,1,2,3,4,5,6],skills:['plumbing']},
  {id:'weekends',revision:8,daily_capacity:2,weekdays:[6,5],skills:['plumbing','custom-skill']},
  {id:'paused',revision:3,daily_capacity:0,weekdays:[],skills:[]}];
 const ui=await screen(crews),f=ui.elements.crew.elements;
 f.crewId.value='weekends';f.crewId.onchange();
 assert.equal(f.weekdays.value,'6,5');assert.equal(Number(f.dailyCapacity.value),2);
 assert.equal(f.weekdays.options.length,4);
 await ui.save();
 assert.deepEqual(ui.posted[0].weekdays,[6,5]);assert.deepEqual(ui.posted[0].skills,['plumbing','custom-skill']);
 assert.equal(ui.posted[0].expectedRevision,8);
 await ui.refresh();assert.equal(f.weekdays.options.length,4);
 f.crewId.value='paused';f.crewId.onchange();
 assert.equal(f.weekdays.value,'');assert.equal(Number(f.dailyCapacity.value),0);
 assert.equal(f.weekdays.options.length,3);
 await ui.save();assert.deepEqual(ui.posted[1].weekdays,[]);assert.equal(ui.posted[1].dailyCapacity,0);
});

test('refresh uses latest saved values and custom schedule can be changed explicitly',async()=>{
 const crew={id:'saved-crew',revision:2,daily_capacity:3,weekdays:[1,3],skills:['plumbing']};
 const ui=await screen([crew]),f=ui.elements.crew.elements;
 assert.equal(f.crewId.value,'saved-crew');assert.equal(f.weekdays.value,'1,3');
 ui.setRecord({crews:[{...crew,revision:3,daily_capacity:9,weekdays:[2,4]}]});
 await ui.refresh();assert.equal(Number(f.dailyCapacity.value),9);assert.equal(f.weekdays.value,'2,4');
 f.weekdays.value='0,1,2,3,4';f.dailyCapacity.value='4';
 await ui.save();assert.deepEqual(ui.posted[0].weekdays,[0,1,2,3,4]);assert.equal(ui.posted[0].dailyCapacity,4);
 assert.equal(ui.posted[0].expectedRevision,3);
});
