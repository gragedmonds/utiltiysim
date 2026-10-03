// The Configuration page as one document: four sections (Town & meters, Process & costs, Scenario, Engine & data)
// on a single scrolling page, with a sidebar that lists each section and the setting groups inside it. A sidebar
// entry scrolls to its target; the entry for whatever is on screen is marked as you scroll. The old tab routes
// (#/config/town, /m2c, /scenarios, /data) still work: they open the page and scroll to that section.
export const SECTIONS=[{id:'town',title:'Town & meters'},{id:'m2c',title:'Process & costs'},{id:'scenarios',title:'Scenario'},{id:'data',title:'Engine & data'},{id:'guide',title:'Engine guide'}];
export const ROUTE=/^#\/(?:settings|config)(?:\/(town|scenarios|data|m2c|guide))?$/;
export const sectionFor=hash=>hash?.match(ROUTE)?.[1]||'town';
export const hashFor=section=>'#/config/'+(SECTIONS.some(s=>s.id===section)?section:'town');
const slug=s=>String(s||'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');
// What the sidebar lists, read off the page: every section and the setting groups (schema cards) it holds right now.
// Cards get stable ids (cfg-<section>-<group>) so the sidebar can scroll to them.
export function navModel(page){
 return SECTIONS.map(s=>{const pane=page.querySelector(`[data-settings-pane="${s.id}"]`);if(!pane)return {...s,anchor:'cfg-'+s.id,groups:[]};pane.id||=('cfg-'+s.id);
  const groups=[...pane.querySelectorAll('.schema-group')].filter(c=>!c.hidden).map(c=>{const key=c.dataset.group||slug(c.querySelector('h3')?.textContent);c.id||=`cfg-${s.id}-${key}`;const n=[...c.querySelectorAll('.schema-field')].filter(r=>!r.hidden).length,changed=Number((c.querySelector('.schema-badge')?.textContent||'').split(' ')[0])||0;return {id:c.id,title:c.querySelector('h3')?.firstChild?.textContent?.trim()||key,count:n,changed};});
  return {...s,anchor:pane.id,groups};});
}
// The sidebar's markup for a model; `active` is the id of the entry on screen.
export function navMarkup(model,active=null){
 const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
 return model.map(s=>`<div class="cfg-nav-section"><button type="button" class="cfg-nav-head${active===s.anchor?' is-active':''}" data-target="${esc(s.anchor)}" data-section="${esc(s.id)}">${esc(s.title)}</button>${s.groups.length?`<div class="cfg-nav-groups">${s.groups.map(g=>`<button type="button" class="cfg-nav-item${active===g.id?' is-active':''}" data-target="${esc(g.id)}">${esc(g.title)}${g.changed?`<span class="cfg-nav-changed" title="${g.changed} changed">${g.changed}</span>`:''}</button>`).join('')}</div>`:''}</div>`).join('');
}
// Field popovers: one open at a time, closed by a click elsewhere or Escape.
export function bindPopovers(root){
 const close=()=>{for(const b of root.querySelectorAll('.schema-info[aria-expanded="true"]')){b.setAttribute('aria-expanded','false');b.closest('.has-pop')?.classList.remove('is-open');}};
 root.addEventListener('click',e=>{const b=e.target.closest('.schema-info');if(!b||!root.contains(b)){if(!e.target.closest('.schema-pop'))close();return;}e.preventDefault();const open=b.getAttribute('aria-expanded')==='true';close();if(!open){b.setAttribute('aria-expanded','true');b.closest('.has-pop')?.classList.add('is-open');}});
 root.addEventListener('keydown',e=>{if(e.key==='Escape')close();});
 return close;
}
// Wires the sidebar to the page: clicks scroll, scrolling marks, refresh() re-reads the groups after a form renders.
export function installConfigNav({page,nav,onSection=()=>{}}){
 let model=[],active=null,observer=null,ticking=false,pending=null; // pending: the section a route asked for, until the person scrolls or picks another entry
 const render=()=>{nav.innerHTML=navMarkup(model,active);};
 function spy(){if(ticking)return;ticking=true;requestAnimationFrame(()=>{ticking=false;const top=page.getBoundingClientRect().top+8;let best=null;for(const s of model){for(const t of [s.anchor,...s.groups.map(g=>g.id)]){const el=document.getElementById(t);if(!el||el.hidden)continue;const r=el.getBoundingClientRect();if(r.top<=top+60)best=t;}}
  if(best&&best!==active){active=best;for(const b of nav.querySelectorAll('[data-target]'))b.classList.toggle('is-active',b.dataset.target===best);const sec=model.find(s=>s.anchor===best||s.groups.some(g=>g.id===best));if(sec)onSection(sec.id);}});}
 function refresh(){model=navModel(page);render();if(pending)jump('cfg-'+pending,{smooth:false});spy();}
 function jump(id,{smooth=true}={}){const el=document.getElementById(id);if(!el)return false;const d=el.closest('details');if(d&&!d.open)d.open=true;el.scrollIntoView({block:'start',behavior:smooth?'smooth':'auto'});return true;}
 nav.addEventListener('click',e=>{const b=e.target.closest('[data-target]');if(!b)return;e.preventDefault();pending=null;jump(b.dataset.target);});
 for(const ev of ['wheel','touchmove','keydown','pointerdown'])page.addEventListener(ev,e=>{if(ev!=='pointerdown'||!nav.contains(e.target))pending=null;},{passive:true});
 page.addEventListener('scroll',spy,{passive:true});
 if(typeof MutationObserver!=='undefined'){observer=new MutationObserver(()=>{clearTimeout(refresh.t);refresh.t=setTimeout(refresh,80);});observer.observe(page,{childList:true,subtree:true,attributeFilter:['hidden','open']});}
 return {refresh,jump,section(id){pending=id;return jump('cfg-'+id,{smooth:false});},get pending(){return pending;},get model(){return model;},destroy(){observer?.disconnect();}};
}
