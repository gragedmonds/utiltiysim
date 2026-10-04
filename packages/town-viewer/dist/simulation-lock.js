// Locking a simulation's settings. A new simulation opens on the Config page unlocked (record `locked: false`): every
// setting is editable and a bar offers "Lock in settings and start simulation". Locking saves the run settings into the
// record with `locked: true` and `lockedAt`, and the simulation starts in the Command Center. From then on Config is a
// display of the settings: inputs are disabled, editing controls hidden, and the client stores refuse setting and
// seed changes. Episodes (dated scenario changes from the Command Center) stay allowed: they are run input, not the
// base settings. A record saved before locking existed has no flag and counts as locked, so it opens as it did.
export const LOCKED_MESSAGE='Settings are locked for this simulation. Start a new simulation to change them.';
export const isLocked=s=>!!s&&s.locked!==false;
// Studio routes an unlocked simulation may show: the Config page (its lock-in page) only.
export const allowedUnlocked=hash=>/^#\/(?:settings|config)(?:\/[a-z0-9]+)?$/.test(hash||'');
// Values in a nested settings object: a group of three changed values counts three.
export function leafCount(v){if(!v||typeof v!=='object'||Array.isArray(v))return v===undefined?0:1;return Object.values(v).reduce((n,x)=>n+leafCount(x),0);}
// How many settings differ from the defaults, by where they apply: the town (generation), the year (meter-to-cash run)
// and the map's operations day.
export function settingCounts({townOverrides,settings,opsSettings}={}){const town=leafCount(townOverrides||{}),year=leafCount(settings||{}),map=leafCount(opsSettings||{});return {town,year,map,total:town+year+map};}
export function lockSummary(c){if(!c.total)return 'Every setting is at its default.';
 const parts=[[c.town,'town'],[c.year,'year'],[c.map,'map day']].filter(([n])=>n).map(([n,w])=>`${n} ${w}`);
 return `${c.total} setting${c.total===1?' differs':'s differ'} from the defaults (${parts.join(' · ')}).`;}
// The record patch that locks a simulation with the settings it runs on.
export function lockPatch({settings=null,opsSettings=null,seed=''}={},now=new Date()){return {locked:true,lockedAt:now.toISOString(),settings:settings||{},opsSettings:opsSettings||null,seed:seed||''};}
export function lockedDate(s){const d=new Date(s?.lockedAt||'');return Number.isNaN(d.getTime())?'':d.toLocaleDateString('en-CA',{year:'numeric',month:'short',day:'numeric'});}
export function lockedBanner(s){const d=lockedDate(s);return `Settings are locked for this simulation${d?` (locked ${d})`:''}. Start a new simulation to change them.`;}
// A store's guard: throws when its simulation is locked.
export function assertUnlocked(store){if(store?.locked)throw Error(LOCKED_MESSAGE);}
// The Config page's side of it. Unlocked: the lock-in bar with its summary, and the other Studio tabs disabled.
// Locked: the banner, every form control on the page disabled (re-applied whenever a form renders again) and, through
// CSS (#settings-page.is-locked), the editing and reset controls hidden. Returns {sync}: call it when the counts move.
export function installSettingsLock({page,nav,getSimulation,getCounts,canLock=()=>'',onLock,toast=()=>{}}){
 const $=id=>document.getElementById(id),main=page.querySelector('.cfg-main'),OPEN=['nav-simulations','nav-config'];
 const lockInputs=()=>{for(const el of main.querySelectorAll('input,select,textarea'))if(!el.disabled){el.disabled=true;el.dataset.lockedInput='';}};
 function sync(){const s=getSimulation(),locked=!!s&&isLocked(s),open=!!s&&!locked;
  page.classList.toggle('is-locked',locked);$('cfg-lock-bar').hidden=!open;$('cfg-locked-banner').hidden=!locked;
  if(open)$('cfg-lock-summary').textContent=lockSummary(getCounts());
  if(locked){$('cfg-locked-text').textContent=lockedBanner(s);lockInputs();}
  for(const a of nav?.querySelectorAll('a')||[]){const off=open&&!OPEN.includes(a.id);a.classList.toggle('is-disabled',off);
   if(off){a.setAttribute('aria-disabled','true');a.title='Lock in your settings to start the simulation';}else if(a.hasAttribute('aria-disabled')){a.removeAttribute('aria-disabled');a.removeAttribute('title');}}}
 if(typeof MutationObserver!=='undefined')new MutationObserver(()=>{const s=getSimulation();if(s&&isLocked(s))lockInputs();}).observe(main,{childList:true,subtree:true});
 nav?.addEventListener('click',e=>{const a=e.target.closest('a[aria-disabled="true"]');if(!a)return;e.preventDefault();e.stopImmediatePropagation();toast('Lock in your settings to start the simulation.');$('cfg-lock-btn').focus();},true);
 $('cfg-lock-btn').onclick=async()=>{const why=canLock();if(why){toast(why);return;}const b=$('cfg-lock-btn');b.disabled=true;try{await onLock();}catch(e){toast(e.message);}finally{b.disabled=false;sync();}};
 return {sync};
}
