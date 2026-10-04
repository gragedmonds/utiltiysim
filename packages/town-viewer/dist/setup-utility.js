// The wizard's utility stage as pure functions: which services the utility provides, and staffing that follows its size.
// Services: customers_billing.services lists what the utility provides in the town, any of electricity, water and gas
// (at least one). Each card is a real toggle on it; the last one on cannot be switched off. Serving all three leaves
// the key out of the town overrides, so the town (and its id) stays the default one. Not serving a service is not a
// town without that network: another utility runs it, its mains still lie under the streets and the utility's
// settings for it do not apply. Having no gas mains at all is a physical choice, gas.all_electric_district_share = 1
// in Advanced, and it only bites from the engine's gasDistrictMinHomes: a smaller town is one district, which keeps
// its gas mains whatever the share. A utility left with gas alone needs gas mains, or it has no customers.
// Staffing: billing analysts and contact-centre agents are whole people. The engine defaults fit the small_town
// reference town (1,900 homes), so a suggestion scales linearly with homes, rounds and keeps at least one. A value
// someone typed (or chose in the conversation) is never replaced; draft.staffing.edited records the typed ones.
// Field crews are already per 1,000 premises and scale with the town by themselves.
import {SERVICE_KEYS,SERVICES_PATH,serviceNames} from './schema-form.js';
export {SERVICES_PATH};
export const STAFFING_REFERENCE_HOMES=1900;
export const STAFFING=[
 {key:'analysts',path:'process.analysts',label:'Billing analysts',one:'billing analyst',many:'billing analysts',base:2,max:200},
 {key:'agents',path:'contact.agents',label:'Contact-centre agents',one:'contact-centre agent',many:'contact-centre agents',base:1,max:500}];
export const GAS_PATH='gas.all_electric_district_share';
export const SERVICES=[{key:'electric',label:'Electricity',icon:'ϟ'},{key:'water',label:'Water',icon:'≈'},{key:'gas',label:'Natural gas',icon:'♧'}];
const at=(o,path)=>path.split('.').reduce((v,k)=>v?.[k],o);
const fmt=n=>Number(n).toLocaleString('en-US');
const cap=s=>s.charAt(0).toUpperCase()+s.slice(1);

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
// Older drafts switched gas off with the gas share (the old select's value, a services object, or the share itself):
// that meant no gas mains, so it stays the physical share = 1. The utility's services are not invented from it.
export function migrateServices(draft){const v=draft.services;if(v==null)return draft;delete draft.services;
 const gas=typeof v==='string'?legacyServices(v).gas:v&&typeof v==='object'&&v.gas!==undefined?!!v.gas:true;
 if(at(draft.townOverrides,GAS_PATH)===undefined&&!gas){draft.townOverrides||={};draft.townOverrides.gas={...draft.townOverrides.gas,all_electric_district_share:1};}
 return draft;}
// The services after ticking (on) or unticking `key`, in canonical order.
export const toggleService=(served,key,on)=>SERVICE_KEYS.filter(k=>k===key?on:served.includes(k));
// Town overrides with the utility's services: the key is left out when it provides all three (the default town), and
// a customers_billing group left empty goes too. Returns a new object.
export function withServices(overrides,served){const out=structuredClone(overrides||{}),cb={...out.customers_billing};
 if(SERVICE_KEYS.every(k=>served.includes(k)))delete cb.services;else cb.services=SERVICE_KEYS.filter(k=>served.includes(k));
 if(Object.keys(cb).length)out.customers_billing=cb;else delete out.customers_billing;return out;}
// Whether the town has gas mains: a share of districts without them below 1, or a town of one district (which keeps them).
export const hasGasMains=({share,homes,gasMinHomes=null}={})=>share!==1||(Number.isFinite(gasMinHomes)&&Number(homes)<gasMinHomes);
// Each service's card: on (your utility provides it), its line, and locked (it cannot be switched off) with why: the
// last service on, or one whose loss would leave a gas-only utility in a town without gas mains.
export function servicesState({served=SERVICE_KEYS,share,homes,gasMinHomes=null}={}){const on=SERVICE_KEYS.filter(k=>served.includes(k)),mains=hasGasMains({share,homes,gasMinHomes}),out={served:on,gasMains:mains};
 for(const k of SERVICE_KEYS){const isOn=on.includes(k),rest=on.filter(x=>x!==k),last=isOn&&!rest.length,gasAlone=isOn&&!mains&&rest.length===1&&rest[0]==='gas';
  out[k]={on:isOn,locked:last||gasAlone,line:isOn?'Served by your utility':'Another utility serves this',note:last?'Your only service':gasAlone?'Kept: no gas mains':'',
   reason:last?'Your utility provides at least one service. Tick another before switching this one off.':gasAlone?'This town has no gas mains, so a gas-only utility would have no customers. Keep this service, or give some districts gas mains in Advanced.':''};}
 return out;}
// The line under the cards: what not providing a service means, gas mains, and where the physical gas share lives.
export function servicesNote(state,{gasMinHomes=null}={}){const off=SERVICE_KEYS.filter(k=>!state[k].on),many=off.length>1,out=[];
 out.push(off.length?`${cap(serviceNames(off,'and'))} ${many?'come':'comes'} from another utility: ${many?'their networks stay':'its network stays'} on the map, with no accounts, meters, bills or crews of yours, and ${many?'their':'its'} settings do not apply.`
  :'Untick a service another utility provides here: its network stays on the map, and its settings show as not applicable.');
 if(!state.gas.on&&state.gasMains)out.push('Gas mains still run under the streets: they are another utility’s.');
 if(state.gas.on&&!state.gasMains)out.push(state.served.length===1?'This town has no gas mains, so a gas-only utility has no customers: lower the share of districts without gas mains in Advanced.':'This town has no gas mains (Advanced), so no home takes your gas.');
 out.push(`Advanced sets the share of districts without gas mains${Number.isFinite(gasMinHomes)?`; a town under ${fmt(gasMinHomes)} homes is one district and keeps its gas mains`:''}.`);
 return out.join(' ');}
// The services for the review: "Electricity · Water · Natural gas", or "Electricity only; water and gas by another utility".
export function servicesSummary(state){const on=SERVICE_KEYS.filter(k=>state[k].on),off=SERVICE_KEYS.filter(k=>!state[k].on&&(k!=='gas'||state.gasMains)),noMains=!state.gasMains;
 const text=off.length||on.length<SERVICE_KEYS.length?`${cap(serviceNames(on,'and'))} only${off.length?`; ${serviceNames(off,'and')} by another utility`:''}`:'Electricity · Water · Natural gas';
 return text+(noMains?(state.gas.on?' · no gas mains (all-electric heating)':'; no gas mains'):'');}
export function staffingSummary(settings,base={}){return STAFFING.map(s=>{const v=at(settings,s.path)??(Number.isFinite(base[s.key])?base[s.key]:s.base);return `${fmt(v)} ${v===1?s.one:s.many}`;}).join(' · ');}
