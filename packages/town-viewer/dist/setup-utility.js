// The wizard's utility stage as pure functions: which services the town has, and staffing that follows its size.
// Services: the engine always serves electricity and water. Natural gas follows gas.all_electric_district_share,
// exactly as the old "Services in this town" select did: 1 = no gas mains (all-electric heating), anything else =
// gas districts. A town smaller than the engine's gasDistrictMinHomes is drawn as one district, which keeps its gas
// mains whatever the share, so gas shows locked on there.
// Staffing: billing analysts and contact-centre agents are whole people. The engine defaults fit the small_town
// reference town (1,900 homes), so a suggestion scales linearly with homes, rounds and keeps at least one. A value
// someone typed (or chose in the conversation) is never replaced; draft.staffing.edited records the typed ones.
// Field crews are already per 1,000 premises and scale with the town by themselves.
export const STAFFING_REFERENCE_HOMES=1900;
export const STAFFING=[
 {key:'analysts',path:'process.analysts',label:'Billing analysts',one:'billing analyst',many:'billing analysts',base:2,max:200},
 {key:'agents',path:'contact.agents',label:'Contact-centre agents',one:'contact-centre agent',many:'contact-centre agents',base:1,max:500}];
export const GAS_PATH='gas.all_electric_district_share';
export const SERVICES=[{key:'electric',label:'Electricity',icon:'ϟ'},{key:'water',label:'Water',icon:'≈'},{key:'gas',label:'Natural gas',icon:'♧'}];
const at=(o,path)=>path.split('.').reduce((v,k)=>v?.[k],o);
const fmt=n=>Number(n).toLocaleString('en-US');

// {analysts, agents} for a town of `homes` homes. `base`: the engine's defaults for the reference town.
export function suggestedStaffing(homes,base={}){const n=Number(homes),scale=Number.isFinite(n)&&n>0?n/STAFFING_REFERENCE_HOMES:0;
 return Object.fromEntries(STAFFING.map(s=>{const b=Number.isFinite(base[s.key])?base[s.key]:s.base;return [s.key,Math.min(s.max,Math.max(1,Math.round(b*scale)))];}));}
// The engine's run defaults ({process:{analysts}, contact:{agents}}) as suggestedStaffing's base.
export const staffingBase=run=>Object.fromEntries(STAFFING.map(s=>[s.key,at(run,s.path)]).filter(([,v])=>Number.isFinite(v)));
function staffing(draft){const st=draft.staffing&&typeof draft.staffing==='object'?draft.staffing:{};st.edited||={};st.applied||={};return draft.staffing=st;}
export const staffingEdited=(draft,path)=>!!draft?.staffing?.edited?.[path];
export function markStaffingEdited(draft,path,edited=true){const st=staffing(draft);if(edited)st.edited[path]=true;else delete st.edited[path];}
// Puts the suggestion for `homes` into draft.settings for every staffing value nobody chose: one that is still the
// engine default (absent) or the suggestion last put there. A suggestion equal to the default is left out, so the run
// settings stay as they were for the reference town. Mutates the draft; returns the paths whose value changed.
export function applySuggestedStaffing(draft,homes,base={}){const st=staffing(draft),want=suggestedStaffing(homes,base),changed=[];
 for(const s of STAFFING){if(st.edited[s.path])continue;const [g,k]=s.path.split('.'),cur=draft.settings?.[g]?.[k];
  if(cur!==undefined&&cur!==st.applied[s.path])continue;
  const v=want[s.key],def=Number.isFinite(base[s.key])?base[s.key]:s.base;draft.settings||={};
  if(v===def){if(draft.settings[g]){const {[k]:_,...rest}=draft.settings[g];if(Object.keys(rest).length)draft.settings[g]=rest;else delete draft.settings[g];}}
  else draft.settings[g]={...draft.settings[g],[k]:v};
  st.applied[s.path]=v;if((cur??def)!==v)changed.push(s.path);}
 return changed;}
export function staffingHint(s,homes,value,base){const v=suggestedStaffing(homes,base)[s.key];return {suggested:v,text:`Suggested for ${fmt(homes)} homes: ${fmt(v)}`,differs:Number(value)!==v};}
export function crewHint(per1000,homes){const n=Number(per1000)*Number(homes)/1000;if(!Number.isFinite(n))return '';const v=n<10?Math.round(n*10)/10:Math.round(n);return `About ${fmt(v)} ${v===1?'crew':'crews'} at ${fmt(homes)} homes, more with shops and other sites`;}

// The old select's values: 'mixed' (electricity + water + gas districts) and 'electric' (all-electric heating).
export function legacyServices(value){return {electric:true,water:true,gas:value!=='electric'};}
// A draft that stored the select's value (or a services object) keeps that choice as the gas share it stood for.
export function migrateServices(draft){const v=draft.services;if(v==null)return draft;delete draft.services;
 const gas=typeof v==='string'?legacyServices(v).gas:v&&typeof v==='object'&&v.gas!==undefined?!!v.gas:true;
 if(at(draft.townOverrides,GAS_PATH)===undefined&&!gas){draft.townOverrides||={};draft.townOverrides.gas={...draft.townOverrides.gas,all_electric_district_share:1};}
 return draft;}
// Each service's card: on (served), locked (the engine cannot switch it off at this size) and why.
export function servicesState({share,homes,gasMinHomes=null}={}){const small=Number.isFinite(gasMinHomes)&&Number(homes)<gasMinHomes,chosen=share!==1;
 return {electric:{on:true,locked:true,note:'Always served'},water:{on:true,locked:true,note:'Always served'},
  gas:{on:small||chosen,chosen,locked:small,note:small?'Always served at this size':'',
   reason:small?`A town under ${fmt(gasMinHomes)} homes is one gas district, and it keeps its gas mains.`:''}};}
export const gasShareFor=(on,restore=.15)=>on?(Number.isFinite(restore)&&restore!==1?restore:.15):1;
export function servicesSummary(state){return state.gas.on?'Electricity · Water · Natural gas':'Electricity · Water · all-electric heating (no gas)';}
export function staffingSummary(settings,base={}){return STAFFING.map(s=>{const v=at(settings,s.path)??(Number.isFinite(base[s.key])?base[s.key]:s.base);return `${fmt(v)} ${v===1?s.one:s.many}`;}).join(' · ');}
