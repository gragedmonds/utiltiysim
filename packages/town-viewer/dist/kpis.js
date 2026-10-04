// The KPI catalogue in the Studio: what a simulation can watch (GET /api/m2c/kpis), the chips that pick figures in
// the wizard and in the conversation, how a figure is shown, and a run's figures (POST /api/m2c/kpis). The engine
// owns the definitions, the thresholds (the `kpi` run-settings group) and the measuring; the pages only present.
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const cache=new Map();
export async function fetchKpiCatalogue(api,{town=null,fetchImpl=globalThis.fetch}={}){const key=api+'|'+(town||'');if(cache.has(key))return cache.get(key);
 const r=await fetchImpl(api+'/m2c/kpis'+(town?'?town='+encodeURIComponent(town):''),{signal:AbortSignal.timeout(15000)});if(!r.ok)throw Error('The KPI catalogue is unavailable ('+r.status+').');const data=await r.json();cache.set(key,data);return data;}
// The figures that belong to the chosen goals (every figure for "everything" or no goals), catalogue order.
export function kpisForGoals(catalogue,goals){const want=new Set(goals||[]);const all=catalogue?.kpis||[];if(!want.size||want.has('everything'))return all;return all.filter(k=>k.goals.some(g=>want.has(g)));}
export const familyTitle=(catalogue,id)=>catalogue?.families?.find(f=>f.id===id)?.title||id;
// A figure as text: shares as percentages, days and minutes with their unit, rates per 1,000 accounts.
export function formatKpi(value,unit){if(value==null||Number.isNaN(Number(value)))return '—';const v=Number(value);
 switch(unit){case 'share':return (v*100).toFixed(v*100>=99.95||v*100<10?1:1)+'%';case 'days':return v.toFixed(1)+' days';case 'minutes':return v.toFixed(0)+' min';case 'seconds':return v.toFixed(0)+' s';case 'per_1000_accounts_year':return v.toFixed(v>=100?0:1)+' /1,000 a year';case 'per_1000_accounts':return v.toFixed(1)+' /1,000';case 'currency_per_account':return '$'+v.toFixed(2)+' /account';default:return String(v);}}
export const unitLabel=unit=>({share:'share',days:'days',minutes:'minutes',seconds:'seconds',per_1000_accounts_year:'per 1,000 accounts a year',per_1000_accounts:'per 1,000 accounts',currency_per_account:'$ per account',count:'count'})[unit]||unit;
// Chips: a row of toggles for the figures a goal set offers; `selected` are the ids already chosen.
export function kpiChips(kpis,selected=[],{name='kpi'}={}){const on=new Set(selected);return kpis.map(k=>`<label class="kpi-chip${on.has(k.id)?' is-on':''}" title="${esc(k.definition)}"><input type="checkbox" name="${esc(name)}" value="${esc(k.id)}" ${on.has(k.id)?'checked':''}><span>${esc(k.title)}</span><small>${esc(unitLabel(k.unit))}</small></label>`).join('');}
// Autofill for the conversation: the figures whose title, id or family matches the last words being typed.
export function matchKpis(catalogue,text,{limit=6}={}){const all=catalogue?.kpis||[];const tail=String(text||'').toLowerCase().split(/[.,;!?\n]/).pop().trim();if(tail.length<3)return [];
 const words=tail.split(/\s+/).slice(-4);const probe=words.join(' ');
 const score=k=>{const hay=(k.title+' '+k.id.replaceAll('_',' ')+' '+k.family).toLowerCase();if(hay.includes(probe))return 4;
  if(words.some((_,i)=>{const p=words.slice(i).join(' ');return p.length>=5&&hay.includes(p);}))return 3;  // the last words so far ("bills on", "days to")
  const hits=words.filter(w=>w.length>=3&&hay.includes(w)).length;return hits>=Math.min(2,words.length)?2:hits===1&&words.length===1?1:0;};
 return all.map(k=>[score(k),k]).filter(([s])=>s>0).sort((a,b)=>b[0]-a[0]).slice(0,limit).map(([,k])=>k);}
// The message with the figure's exact title in place of the words that named it ("…watch the bills on" →
// "…watch the Bills on time "): the longest run of trailing words the title contains, else the trailing words it
// contains one by one, else nothing is replaced and the title is appended.
export function withKpiTitle(text,k){const parts=String(text||'').split(/([.,;!?\n])/);const tail=parts.pop();const words=tail.trim()?tail.trim().split(/\s+/):[];const hay=(k.title+' '+k.id.replaceAll('_',' ')).toLowerCase();
 let n=0;for(let i=Math.min(4,words.length);i>0&&!n;i--){const p=words.slice(-i).join(' ').toLowerCase();if(p.length>=3&&hay.includes(p))n=i;}
 if(!n)while(n<words.length&&words[words.length-1-n].length>=3&&hay.includes(words[words.length-1-n].toLowerCase()))n++;
 return (parts.join('')+' '+[...words.slice(0,words.length-n),k.title].join(' ')).replace(/\s+/g,' ').trimStart()+' ';}
// The chosen figures as the proposal summary says them.
export function watchLine(catalogue,ids){const names=(ids||[]).map(id=>catalogue?.kpis?.find(k=>k.id===id)?.title||id);return names.length?'Watching: '+names.join(' · '):'';}
// A run's figures for the chosen ids, through the meter-to-cash client's request body.
export async function fetchKpiValues(api,body,{fetchImpl=globalThis.fetch}={}){const r=await fetchImpl(api+'/m2c/kpis',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(120000)});
 if(!r.ok){let d='';try{d=(await r.json()).detail;}catch{}throw Error(typeof d==='string'&&d?d:'The figures could not be computed ('+r.status+').');}return r.json();}
// The strip of chosen figures: value, unit, and the threshold it counts with when it has one.
export function kpiStrip(catalogue,ids,values,{thresholds={},href=null}={}){const rows=(ids||[]).map(id=>catalogue?.kpis?.find(k=>k.id===id)).filter(Boolean);if(!rows.length)return '';
 return `<section class="kpi-strip" aria-label="Your KPIs"><div class="kpi-strip-head"><h3>Your KPIs</h3>${href?`<a href="${esc(href)}">Glossary ↗</a>`:''}</div><div class="kpi-tiles">${rows.map(k=>{const v=values?values[k.id]:undefined;const th=k.thresholds.map(p=>{const t=thresholds[p];return t==null?'':`${p.split('.').pop().replaceAll('_',' ')} ${t}`;}).filter(Boolean).join(' · ');
  return `<article class="kpi-tile" data-kpi="${esc(k.id)}"><span>${esc(k.title)}</span><strong>${v===undefined?'…':esc(formatKpi(v,k.unit))}</strong><small>${esc(k.better==='lower'?'lower is better':'higher is better')}${th?' · '+esc(th):''}</small></article>`;}).join('')}</div></section>`;}
