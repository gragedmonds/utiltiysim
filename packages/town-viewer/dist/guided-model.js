import {schemaFields,parseField,servedServices,same} from './schema-form.js';
import {STAFFING,staffingBase,suggestedStaffing,applySuggestedStaffing,markStaffingEdited} from './setup-utility.js';

export const BUCKET={town:'townOverrides',run:'settings',operations:'operations',world:'worldSettings'};
export const at=(obj,path)=>path.split('.').reduce((v,k)=>v?.[k],obj);
export function put(obj,path,value){const keys=path.split('.');let o=obj;for(const k of keys.slice(0,-1))o=o[k]??={};o[keys.at(-1)]=structuredClone(value);}
export function flatten(obj,prefix='',out={}){for(const [key,value] of Object.entries(obj||{})){const path=prefix?prefix+'.'+key:key;if(value&&typeof value==='object'&&!Array.isArray(value))flatten(value,path,out);else out[path]=value;}return out;}
export function fieldsFor(data,draft={}){
 const town={...data.defaults.town,customers_billing:{...data.defaults.town.customers_billing,...draft.townOverrides?.customers_billing}};
 return Object.entries(data.schemas).flatMap(([scope,schema])=>schemaFields(schema,{groups:scope==='town'?(k,g)=>g['x-applies']!=='run':null,services:servedServices(town)}).map(f=>({...f,scope,id:scope+':'+f.path})));
}
export function pagesFor(data,fields){
 const descriptors=data.wizard.pages,assigned=new Set(),out=[],fieldIds=new Set(fields.map(f=>f.id));
 for(const p of descriptors.filter(p=>p.kind!=='review')){
  const chosen=fields.filter(f=>!assigned.has(f.id)&&(p.match||[]).some(prefix=>fieldIds.has(prefix)?f.id===prefix:f.id.startsWith(prefix)));
  chosen.forEach(f=>assigned.add(f.id));
  if(!chosen.length&&!p.kind)continue;
  // A bounded number of controls per page; additional engine fields add pages, never disappear.
  for(let n=0;n<Math.max(1,chosen.length);n+=4)out.push({...p,id:p.id+(n?'-'+(n/4+1):''),label:p.label+(n?' · '+(n/4+1):''),presets:n?[]:p.presets,fields:chosen.slice(n,n+4)});
 }
 const leftovers=fields.filter(f=>!assigned.has(f.id));
 for(const key of new Set(leftovers.map(f=>f.scope+':'+f.group))){const group=leftovers.filter(f=>f.scope+':'+f.group===key);for(let n=0;n<group.length;n+=4)out.push({id:'extra-'+key.replace(':','-')+'-'+n,section:group[0].scope==='town'?'Networks':group[0].scope==='world'?'Meters':'Studio year',mode:group[0].scope==='town'?undefined:group[0].scope==='world'?'world':'studio',title:group[0].groupTitle,label:group[0].groupTitle+(n?' · '+(n/4+1):''),fields:group.slice(n,n+4),note:'Additional settings supplied by this version of the engine.'});}
 out.push({...descriptors.find(p=>p.kind==='review'),fields:[]});return out;
}
export function initialize(draft,data,{local=false,fresh=false}={}){
 if(!draft.guidedSetup){
  const pins={};if(!fresh)for(const [scope,bucket] of Object.entries(BUCKET))for(const path of Object.keys(flatten(draft[bucket])))pins[scope+':'+path]=true;
  draft.guidedSetup={version:1,page:'identity',mode:fresh&&local?'world':'studio',pins,choices:{},suggestions:{}};
 }
 const state=draft.guidedSetup;state.pins??={};state.choices??={};state.suggestions??={};state.pace??=fresh?'quick':'full';
 draft.goals?.length||(draft.goals=['everything']);draft.name||='My utility';
 return state;
}
export function visiblePages(pages,state,catalogue){const modePages=pages.filter(p=>!p.mode||p.mode===state.mode);return state.pace==='quick'?modePages.filter(p=>(catalogue.quickPages||['identity','services','size','region','meter-mix','review']).includes(p.id)):modePages;}
export function changePace(draft,pace,pages,catalogue){if(!['quick','full'].includes(pace))throw Error('Choose Quick setup or Full setup.');const state=draft.guidedSetup;state.pace=pace;if(!visiblePages(pages,state,catalogue).some(p=>p.id===state.page))state.page='identity';}
export function valueOf(draft,data,field){if(field.scope==='town'&&field.path==='town.houses'&&draft.guidedSetup?.mode==='studio'&&draft.execution==='local'&&draft.totalHomes)return draft.totalHomes;const exact=at(draft[BUCKET[field.scope]],field.path);return exact===undefined?at(data.defaults[field.scope],field.path)??field.default:exact;}
export function fieldAt(fields,id){
 const direct=fields.find(f=>f.id===id);if(direct)return direct;
 const parent=fields.find(f=>f.children&&id.startsWith(f.id+'.'));const child=parent?.children.find(c=>id===parent.id+'.'+c.key);
 return child?{...child,scope:parent.scope,path:parent.path+'.'+child.key,id,disabled:parent.disabled||child.disabled}:null;
}
export function setValue(draft,data,fields,id,raw,{pin=true}={}){
 const f=fieldAt(fields,id);if(!f||f.disabled)throw Error('This setting is unavailable for the selected services.');
 const previous=valueOf(draft,data,f);
 const districtTotal=id==='town:town.houses'&&draft.guidedSetup.mode==='studio'&&draft.execution==='local';
 const result=parseField(districtTotal?{...f,max:500000}:f,raw);if(!result.ok)throw Error(result.error);
 if(id==='town:town.houses'&&draft.guidedSetup.mode==='world'&&result.value>data.homeLimit)throw Error(`A saved world supports at most ${data.homeLimit.toLocaleString()} homes. Choose Studio year for larger district runs.`);
 if(f.type==='enum'&&!f.options.includes(result.value))throw Error('Choose one of the listed options.');
 put(draft[BUCKET[f.scope]]??={},f.path,districtTotal?Math.min(result.value,data.homeLimit||10000):result.value);
 if(pin)draft.guidedSetup.pins[id]=true;
 if(pin&&STAFFING.some(s=>id==='run:'+s.path))markStaffingEdited(draft,f.path);
 if(id==='town:town.houses'){
  draft.homes=result.value;draft.totalHomes=draft.execution==='local'?result.value:null;
  if(previous!==result.value){
   // Staffing repeats in each district, rather than scaling to the whole run total.
   const base=staffingBase(data.defaults.run),homes=draft.townOverrides.town.houses,want=suggestedStaffing(homes,base);
   for(const s of STAFFING){
    const staffId='run:'+s.path;
    draft.guidedSetup.suggestions[staffId]=want[s.key];
    if(Object.entries(draft.guidedSetup.pins).some(([key,pinned])=>pinned&&(staffId===key||staffId.startsWith(key+'.'))))markStaffingEdited(draft,s.path);
   }
   applySuggestedStaffing(draft,homes,base);
  }
 }
 draft.configDirty=true;draft.agentSummaryDirty=!!draft.agentProposal;return result.value;
}
export function applyChoice(draft,data,fields,page,choice){
 const state=draft.guidedSetup;state.choices[page]=choice.id;const skipped=[];
 for(const [id,value] of Object.entries(choice.values||{})){
  state.suggestions[id]=structuredClone(value);
  if(Object.keys(state.pins).some(key=>state.pins[key]&&(id===key||id.startsWith(key+'.')||key.startsWith(id+'.')))){skipped.push(id);continue;}
  const f=fieldAt(fields,id);if(!f||f.disabled)continue;
  setValue(draft,data,fields,id,value,{pin:false});
 }
 return skipped;
}
export function resetValue(draft,data,fields,id){
 const state=draft.guidedSetup,f=fieldAt(fields,id);if(!f)return;
 const value=Object.hasOwn(state.suggestions,id)?state.suggestions[id]:at(data.defaults[f.scope],f.path)??f.default;
 setValue(draft,data,fields,id,value,{pin:false});for(const key of Object.keys(state.pins))if(key===id||key.startsWith(id+'.'))delete state.pins[key];
 if(STAFFING.some(s=>id==='run:'+s.path)){
  markStaffingEdited(draft,f.path,false);
  draft.staffing.applied??={};draft.staffing.applied[f.path]=value;
 }
}
export function regionChoice(region){
 const values=Object.fromEntries(Object.entries(flatten(region.overrides)).map(([k,v])=>['town:'+k,v]));
 if(region.overrides.weather){const w=region.overrides.weather;values['world:weather.winter_mean_c']=w.winter.mean_c;values['world:weather.summer_mean_c']=w.summer.mean_c;values['world:weather.daily_weather_spread_c']=(w.winter.sd_c+w.summer.sd_c)/2;}
 return {id:region.id,label:region.name,values};
}
export function meterMix(draft,data){const ami=valueOf(draft,data,{scope:'town',path:'ami.ami_route_share'}),amr=valueOf(draft,data,{scope:'town',path:'ami.amr_route_share'});return [ami*100,amr*100,(1-ami-amr)*100].map(v=>Math.round(v*1e8)/1e8);}
export function moveBoundary(mix,index,percent){const [a,b]=mix;const end=a+b,v=Math.max(0,Math.min(100,percent));return index===0?[Math.min(v,end),end-Math.min(v,end),100-end]:[a,Math.max(v,a)-a,100-Math.max(v,a)];}
export function setMix(draft,data,fields,mix,{pin=true}={}){
 if(mix.length!==3||mix.some(v=>!Number.isFinite(v)||v<0||v>100)||Math.abs(mix.reduce((a,b)=>a+b,0)-100)>1e-7)throw Error('AMI, AMR and Manual must total 100%.');
 setValue(draft,data,fields,'town:ami.ami_route_share',mix[0]/100,{pin});setValue(draft,data,fields,'town:ami.amr_route_share',mix[1]/100,{pin});
}
export function changedFields(draft,data,fields){return fields.filter(f=>!same(valueOf(draft,data,f),at(data.defaults[f.scope],f.path)??f.default));}
export function sliderFor(f,value){
 if(!['number','integer'].includes(f.type)||value===null||!Number.isFinite(value))return null;
 const percent=f.min===0&&f.max===1&&!f.unit,scale=percent?100:1;
 let min=f.min??(f.xmin!=null?f.xmin+(f.type==='integer'?1:.01):Math.min(0,value)),max=f.max??(f.xmax!=null?f.xmax-(f.type==='integer'?1:.01):Math.max(10,Math.ceil(Math.abs(value)*2)));
 // Slider rails are a convenient window; exact entry always accepts the engine's full bounds.
 if(max-min>100000)max=Math.max(100,Math.abs(value)*2);
 if(f.window){min=Math.max(min,f.window[0]);max=Math.min(max,f.window[1]);if(f.min==null&&f.xmin==null)min=f.window[0];if(f.max==null&&f.xmax==null)max=f.window[1];}
 min=Math.min(min,value);max=Math.max(max,value);
 return {min:min*scale,max:max*scale,scale,step:f.type==='integer'?1:percent?.1:Math.max(.001,Math.pow(10,Math.floor(Math.log10(Math.max(max-min,.01)))-3)),suffix:percent?'%':f.unit};
}
