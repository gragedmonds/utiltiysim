import test from 'node:test';
import assert from 'node:assert/strict';
import {schemaFields,parseField,overridesFrom,changeList,fieldMatches,same} from '../dist/schema-form.js';
import {isTownGroup,inferSchema,townValues,fullConfig,newSeed,generateCapability,requestTown,HOSTED_NOTE,townLabel} from '../dist/town-config.js';

// A slice of the engine's SimConfig schema: $ref groups with x-order and x-applies, a per-era object, a season,
// a rate-block list, a nullable seed, an exclusive bound, and settings the engine marks not modelled or deprecated.
const schema={properties:{name:{type:'string',default:'custom'},billing:{$ref:'#/$defs/BillingConfig'},housing:{$ref:'#/$defs/HousingConfig'},seeds:{$ref:'#/$defs/SeedsConfig'},weather:{$ref:'#/$defs/WeatherConfig'}},
 $defs:{
  SeedsConfig:{title:'Seeds','x-applies':'town','x-order':0,properties:{master:{type:'string',title:'Master',default:'WHITBY-042'},weather:{anyOf:[{type:'string'},{type:'null'}],default:null,title:'Weather',description:'Re-roll the weather.','x-advanced':true}}},
  HousingConfig:{title:'Housing & households','x-applies':'town','x-order':2,properties:{
   electric_heat_rate:{$ref:'#/$defs/EraValues',default:{pre_1945:.1,postwar:.14,modern:.18},description:'Share of houses heated electrically.','x-effects':['winter peak']},
   household_size_weights:{type:'array',items:{type:'number'},default:[.28,.34,.15,.15,.06,.02],title:'Household Size Weights'},
   basement_rate:{type:'number',minimum:0,maximum:1,default:.6,description:'Share with a basement.','x-status':'not-modelled','x-status-reason':'Loads do not use basements yet.'},
   lot_rule:{type:'string',default:'a','x-deprecated':'Use lot_frontage_m.'}}},
  WeatherConfig:{title:'Weather','x-applies':'town','x-order':7,properties:{winter:{$ref:'#/$defs/SeasonTemp',description:'Winter.',default:{mean_c:-4.5,sd_c:6.5,min_c:-28,max_c:12}},hour:{type:'number',minimum:0,exclusiveMaximum:24,default:8}}},
  BillingConfig:{title:'Billing','x-applies':'run','x-order':16,properties:{electric_blocks:{type:'array',items:{$ref:'#/$defs/RateBlock'},default:[{up_to:600,price:.098},{up_to:null,price:.116}],'x-unit':'$/kWh'}}},
  EraValues:{title:'EraValues',type:'object',additionalProperties:false,description:'A value per era.',properties:{pre_1945:{title:'Pre 1945',type:'number'},postwar:{title:'Postwar',type:'number'},modern:{title:'Modern',type:'number'}},required:['pre_1945','postwar','modern']},
  SeasonTemp:{title:'SeasonTemp',type:'object',properties:{mean_c:{title:'Mean C',type:'number'},sd_c:{title:'Sd C',type:'number'},min_c:{title:'Min C',type:'number'},max_c:{title:'Max C',type:'number'}}},
  RateBlock:{title:'RateBlock',type:'object',additionalProperties:false,properties:{up_to:{anyOf:[{type:'number'},{type:'null'}],title:'Up To'},price:{type:'number',title:'Price'}},required:['up_to','price']}}};

test('groups come in x-order; the town form leaves out run groups and top-level scalars',()=>{
 assert.deepEqual([...new Set(schemaFields(schema).map(f=>f.group))],['seeds','housing','weather','billing']);
 const town=schemaFields(schema,{groups:isTownGroup});
 assert.deepEqual([...new Set(town.map(f=>f.group))],['seeds','housing','weather']);
 assert.equal(town.find(f=>f.path==='seeds.master').default,'WHITBY-042');
});

test('nested objects become labelled sub-values that keep the reference sibling description and default',()=>{
 const f=schemaFields(schema).find(f=>f.path==='housing.electric_heat_rate');
 assert.equal(f.type,'object');assert.equal(f.title,'Electric heat rate');assert.equal(f.description,'Share of houses heated electrically.');assert.deepEqual(f.effects,['winter peak']);
 assert.deepEqual(f.children.map(c=>[c.key,c.title,c.type]),[['pre_1945','Pre-1945','number'],['postwar','Post-war','number'],['modern','Modern','number']]);
 assert.deepEqual(parseField(f,{pre_1945:'0.1',postwar:'0.2',modern:'0.3'}),{ok:true,value:{pre_1945:.1,postwar:.2,modern:.3}});
 assert.deepEqual(parseField(f,{pre_1945:'0.1',postwar:'',modern:'0.3'}),{ok:false,error:'Post-war: Enter a number.'});
 const season=schemaFields(schema).find(f=>f.path==='weather.winter');assert.deepEqual(season.children.map(c=>c.title),['Mean','Std dev','Min','Max']);
 // Changes count per sub-value against the town's own config; overrides carry the whole object.
 const base={housing:{electric_heat_rate:{pre_1945:.1,postwar:.14,modern:.18}}},values={housing:{electric_heat_rate:{modern:.3,postwar:.14,pre_1945:.1}}},fields=schemaFields(schema);
 assert.deepEqual(changeList(fields,values,base),['housing.electric_heat_rate.modern']);
 assert.deepEqual(overridesFrom(fields,values,base),{housing:{electric_heat_rate:{modern:.3,postwar:.14,pre_1945:.1}}});
 assert.deepEqual(changeList(fields,base,base),[]);assert.equal(same({a:1,b:[1,2]},{b:[1,2],a:1}),true);
});

test('lists are JSON checked against their item schema',()=>{
 const fields=schemaFields(schema),w=fields.find(f=>f.path==='housing.household_size_weights'),blocks=fields.find(f=>f.path==='billing.electric_blocks');
 assert.equal(w.type,'json');assert.equal(blocks.type,'json');assert.equal(blocks.unit,'$/kWh');
 assert.deepEqual(parseField(w,'[0.5, 0.5]'),{ok:true,value:[.5,.5]});
 assert.deepEqual(parseField(w,'[0.5, "x"]'),{ok:false,error:'Item 2 must be a number.'});
 assert.deepEqual(parseField(w,'{"a":1}'),{ok:false,error:'Enter a JSON list, for example [1, 2].'});
 assert.deepEqual(parseField(w,'[1,'),{ok:false,error:'Enter valid JSON.'});
 assert.equal(parseField(blocks,'[{"up_to":600,"price":0.1},{"up_to":null,"price":0.12}]').ok,true);
 assert.deepEqual(parseField(blocks,'[{"up_to":600}]'),{ok:false,error:'Item 1 needs "price".'});
 assert.deepEqual(parseField(blocks,'[{"up_to":"lots","price":1}]'),{ok:false,error:'Item 1: "up_to" has the wrong type.'});
 assert.deepEqual(parseField(blocks,'[{"up_to":1,"price":1,"tier":2}]'),{ok:false,error:'Item 1: unknown key "tier".'});
});

test('not-modelled and deprecated settings stay visible but disabled with the reason',()=>{
 const fields=schemaFields(schema),b=fields.find(f=>f.path==='housing.basement_rate'),d=fields.find(f=>f.path==='housing.lot_rule');
 assert.deepEqual([b.disabled,b.status,b.reason],[true,'not-modelled','Loads do not use basements yet.']);
 assert.deepEqual([d.disabled,d.status,d.reason],[true,'deprecated','Use lot_frontage_m.']);
 assert.equal(fields.find(f=>f.path==='housing.household_size_weights').disabled,false);
 const grouped=schemaFields({properties:{g:{title:'G','x-status':'not-modelled',properties:{a:{type:'number'}}}}});assert.deepEqual([grouped[0].disabled,grouped[0].reason],[true,'Not modelled by the engine yet.']);
});

test('nullable seeds, exclusive bounds and the setting search',()=>{
 const fields=schemaFields(schema),seed=fields.find(f=>f.path==='seeds.weather'),hour=fields.find(f=>f.path==='weather.hour');
 assert.deepEqual([seed.type,seed.nullable,seed.title,seed.advanced],['text',true,'Weather',true]);
 assert.deepEqual(parseField(seed,''),{ok:true,value:null});assert.deepEqual(parseField(seed,'STORMY'),{ok:true,value:'STORMY'});
 assert.deepEqual(parseField(hour,'24'),{ok:false,error:'Less than 24.'});assert.deepEqual(parseField(hour,'23.5'),{ok:true,value:23.5});
 const heat=fields.find(f=>f.path==='housing.electric_heat_rate');
 assert.equal(fieldMatches(heat,'heat'),true);assert.equal(fieldMatches(heat,'electric_heat'),true);assert.equal(fieldMatches(heat,'modern heated'),true);assert.equal(fieldMatches(heat,'pool'),false);assert.equal(fieldMatches(heat,''),true);
});

test('a snapshot without a published schema still edits: types and nesting read off its config',()=>{
 const config={name:'ayr',seeds:{master:'WHITBY-042',weather:null},housing:{electric_heat_rate:{pre_1945:.1,postwar:.14,modern:.18},household_size_weights:[.5,.5],ac:true},vee:{high_ratio:2}};
 const s=inferSchema(config),f=schemaFields(s,{groups:isTownGroup});
 assert.deepEqual([...new Set(f.map(x=>x.group))],['seeds','housing']);
 assert.deepEqual(f.map(x=>[x.path,x.type]),[['seeds.master','text'],['seeds.weather','text'],['housing.electric_heat_rate','object'],['housing.household_size_weights','json'],['housing.ac','boolean']]);
 const values=townValues(config,s);assert.deepEqual(Object.keys(values),['seeds','housing']);values.housing.electric_heat_rate.modern=.3;
 assert.equal(config.housing.electric_heat_rate.modern,.18,'editing never touches the loaded town');
 const full=fullConfig(config,values);assert.equal(full.name,'ayr');assert.deepEqual(full.vee,{high_ratio:2});assert.equal(full.housing.electric_heat_rate.modern,.3);
 assert.equal(townLabel({source:{label:'Ayr street snapshot'}}),'Ayr');assert.equal(townLabel({name:'Elora'}),'Elora');
});

test('a new seed keeps the prefix, is shown, and never repeats the current one',()=>{
 assert.equal(newSeed('WHITBY-042',()=>0),'WHITBY-AAAAAA');
 let i=0;const seq=[0,0,0,0,0,0,.5,.5,.5,.5,.5,.5],rnd=()=>seq[i++%seq.length];assert.equal(newSeed('X-AAAAAA',rnd),'X-SSSSSS');
 assert.match(newSeed('WHITBY-042'),/^WHITBY-[A-Z2-9]{6}$/);assert.match(newSeed(''),/^TOWN-[A-Z2-9]{6}$/);assert.match(newSeed('ayr town'),/^AYRTOWN-/);
});

test('generation is offered only where the engine can build towns',async()=>{
 const ok=async()=>({ok:true}),missing=async()=>({ok:false,status:404});
 assert.deepEqual(await generateCapability('/api',{status:'ok',capabilities:{generate:true}},missing),{ok:true});
 assert.deepEqual(await generateCapability('/api',{status:'ok',capabilities:{generate:false}},ok),{ok:false,reason:HOSTED_NOTE});
 assert.deepEqual(await generateCapability('/api',{status:'ok',engine:'hosted',towns:['ayr']},ok),{ok:false,reason:HOSTED_NOTE});
 assert.deepEqual(await generateCapability('/api',{status:'ok',towns:['ayr']},ok),{ok:true});
 assert.equal((await generateCapability('/api',{status:'ok',towns:['ayr']},missing)).ok,false);
 assert.match((await generateCapability('/api',null,ok)).reason,/No engine is connected/);
 assert.match(HOSTED_NOTE,/cannot build towns/);
});

test('generate posts the full config, polls until ready and reports engine refusals',async()=>{
 const calls=[],states=['building','building','ready'],fake=async(url,opts={})=>{calls.push([opts.method||'GET',url,opts.body?JSON.parse(opts.body):null]);
  if(opts.method==='POST')return {ok:true,status:202,json:async()=>({townId:'town-abc12345',status:'building'})};return {ok:true,status:200,json:async()=>({townId:'town-abc12345',status:states.shift()})};};
 const seen=[];const tid=await requestTown('http://e/api',{seeds:{master:'X'}},{fetchImpl:fake,sleep:async()=>{},onStatus:s=>seen.push(s.status)});
 assert.equal(tid,'town-abc12345');assert.deepEqual(calls[0],['POST','http://e/api/towns',{config:{seeds:{master:'X'}}}]);
 assert.deepEqual(calls.slice(1).map(c=>c[1]),Array(3).fill('http://e/api/towns/town-abc12345'));assert.deepEqual(seen,['building','building','building','ready']);
 const ready=async()=>({ok:true,status:201,json:async()=>({townId:'town-1',status:'ready'})});assert.equal(await requestTown('/api',{},{fetchImpl:ready}),'town-1');
 const named=async()=>({ok:true,status:201,json:async()=>({townId:'town-1',ref:'ayr~eNqrVs',status:'ready'})});assert.equal(await requestTown('/api',{},{fetchImpl:named}),'ayr~eNqrVs','the reference wins: any engine instance rebuilds it');
 await assert.rejects(requestTown('/api',{},{fetchImpl:async()=>({ok:false,status:405,json:async()=>({})})}),e=>e.unsupported===true);
 await assert.rejects(requestTown('/api',{},{fetchImpl:async()=>({ok:false,status:422,json:async()=>({detail:[{loc:['body','config','town','houses'],msg:'Input should be less than or equal to 10000'}]})})}),/Engine 422: town\.houses: Input should be less than or equal to 10000/);
 await assert.rejects(requestTown('/api',{},{fetchImpl:async()=>({ok:false,status:422,json:async()=>({townId:'town-9',status:'failed',error:'ValueError: no roads'})})}),/could not build this town: ValueError: no roads/);
 let n=0;const lost=async(url,o={})=>o.method==='POST'?{ok:true,status:202,json:async()=>({townId:'town-2',status:'building'})}:{ok:false,status:404,json:async()=>({status:n++?'unknown':'building'})};
 await assert.rejects(requestTown('/api',{},{fetchImpl:lost,sleep:async()=>{}}),/no longer knows town-2/);
});
