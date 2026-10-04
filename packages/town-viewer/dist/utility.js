// Utility: a batch of districts as one utility (`utilsim batch-run`, utility-batch/1.0), read-only.
// Route: utility.html?batch=/batches/<jobKey>/ (web/serve.mjs serves <store>/batches/ beside <store>/runs/).
// Reads the batch folder's job.json, rollup.json (the finished districts' months and days added up), staffing.json
// (shared staffing: the pools, home teams, staff per district and day, the coordinator's predicted waiting) and
// network.json (connected networks: the shared assets and each district's upstream events), plus each listed
// district's run manifest for its accounts and registers. Every district opens in the run viewer
// (runs.html?run=/runs/<runKey>/). Nothing here recomputes a run: it adds up, ranks and draws what the batch wrote.
import {RunBundle} from './run-bundle.js';
import {niceTicks,fmtTick,SERIES,QUEUES} from './year-page.js';
import {money,num} from './worklists.js';
import {escapeText as e} from './customer-view.js';
import {prettyKey} from './schema-form.js';

export const BATCH_VERSION='utility-batch/1.0',STAFFING_VERSION='utility-staffing/1.0',NETWORK_VERSION='utility-network/1.0';
export const PAGE_SIZE=50,TOP=8,OTHER_COLOR='#9b97a9';
export const POOLS={analysts:'Analysts',supervisors:'Supervisors',agents:'Contact agents',crew_meter:'Meter crews',crew_electric:'Electric crews',crew_water:'Water crews',crew_gas:'Gas crews',crew_construction:'Construction crews'};
const PEOPLE=new Set(['analysts','supervisors','agents']);
export const UTILITIES=['electric','water','gas'];
// The first three validated palette slots (they pass all pairs), fixed per utility: colour follows the utility.
export const UTILITY_COLORS={electric:SERIES[1],water:SERIES[0],gas:SERIES[2]};
export const ASSET_KINDS={circuit:'Transmission circuit',plant:'Treatment plant',main:'Transmission main',gate:'Gate station'};
const CREWS=['meter','electric','water','gas','construction','emergency'];
const MAX_FILE=256*1024*1024,MONTHS=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const INT=new Intl.NumberFormat('en-CA',{maximumFractionDigits:0}),ONE=new Intl.NumberFormat('en-CA',{maximumFractionDigits:1}),THREE=new Intl.NumberFormat('en-CA',{maximumFractionDigits:3});
const finite=v=>typeof v==='number'&&Number.isFinite(v);
const cmp=(a,b)=>{a=String(a??'');b=String(b??'');return a<b?-1:a>b?1:0;};
const sum=a=>Array.isArray(a)?a.reduce((s,v)=>s+(finite(v)?v:0),0):null;
export const poolLabel=p=>POOLS[p]||prettyKey(String(p));
export const dayDate=(start,i)=>new Date(Date.parse(start+'T12:00:00Z')+i*86400000).toISOString().slice(0,10);
export const longDay=day=>new Intl.DateTimeFormat('en-GB',{weekday:'short',day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}).format(new Date(day+'T12:00:00Z')).replace(',','');
export function fmt(v,kind){if(!finite(v))return '—';switch(kind){case 'money':return money(v);case 'pct':return (v*100).toFixed(1)+'%';case 'crew':return THREE.format(v);case 'num':return ONE.format(v);default:return INT.format(v);}}
const clock=s=>finite(s)?`${String(Math.floor(s/3600)%24).padStart(2,'0')}:${String(Math.floor(s/60)%60).padStart(2,'0')}`:'—';

// ---- the batch folder ------------------------------------------------------------------------------------------
export function batchURL(raw,origin=globalThis.location?.href){const url=new URL(raw,origin);if(!['http:','https:'].includes(url.protocol))throw Error('Use an HTTP or HTTPS batch folder URL.');url.search='';url.hash='';if(!url.pathname.endsWith('/'))url.pathname+='/';return url;}
// A district's run folder beside the batch (<store>/runs/<runKey>/), and the run viewer's link to it.
export const runBase=(base,runKey)=>/^[a-f0-9]{64}$/.test(String(runKey||''))?new URL('../../runs/'+runKey+'/',base):null;
export function runLink(base,runKey,origin=base){const u=runBase(base,runKey);if(!u)return null;const target=u.origin===new URL(origin).origin?u.pathname:u.href;return 'runs.html?run='+encodeURIComponent(target).replaceAll('%2F','/').replaceAll('%3A',':');}
export async function readBatchFile(base,name,{fetchImpl=globalThis.fetch,optional=false}={}){
 let r;try{r=await fetchImpl(new URL(name,base));}catch{throw Error('Batch file unreachable: '+name);}
 if(!r.ok){if(optional&&r.status===404)return null;throw Error(`Batch file unavailable (${r.status}): ${name}`);}
 const text=await r.text();if(text.length>MAX_FILE)throw Error('Batch file is too large: '+name);
 try{return JSON.parse(text);}catch{throw Error('Damaged batch file: '+name);}
}
export const MISSING={rollup:'The utility totals (rollup.json) are not written yet. The batch writes them each time it pauses or finishes.',staffing:'The shared staffing plan (staffing.json) is not written yet. The coordinator writes it after the first pass over every district.',network:'The network layout (network.json) is missing from this batch folder.'};
// job.json is required; the other files fail softly, each with its own message in `problems`.
export async function loadBatch(base,{fetchImpl=globalThis.fetch}={}){
 const job=await readBatchFile(base,'job.json',{fetchImpl});
 if(job?.schemaVersion!==BATCH_VERSION||!Array.isArray(job.districts)||!job.inputs)throw Error('Unsupported batch. Expected '+BATCH_VERSION+'.');
 const key=base.pathname.split('/').filter(Boolean).at(-1);if(/^[a-f0-9]{64}$/.test(key||'')&&job.key&&job.key!==key)throw Error('This job.json belongs to another batch.');
 const shared=job.inputs.staffing==='shared',connected=job.inputs.network==='connected',problems={};
 const soft=async(id,name,version)=>{try{const v=await readBatchFile(base,name,{fetchImpl,optional:true});if(v==null){problems[id]=MISSING[id];return null;}if(v.schemaVersion!==version)throw Error(`Unsupported ${name}. Expected ${version}.`);return v;}catch(err){problems[id]=err.message;return null;}};
 const [rollup,staffing,network]=await Promise.all([soft('rollup','rollup.json',BATCH_VERSION),shared?soft('staffing','staffing.json',STAFFING_VERSION):null,connected?soft('network','network.json',NETWORK_VERSION):null]);
 return {job,rollup,staffing,network,shared,connected,problems};
}

// ---- figures ---------------------------------------------------------------------------------------------------
// The batch's headline figures: the utility from job.json, the year's totals from rollup.months (receivable and
// backlog at the last month) and rollup.daily (contacts; answered of the calls that reached the queue; outages).
export function utilityKpis({job,rollup=null,staffing=null,network=null}){
 const months=(rollup?.months||[]).slice().sort((a,b)=>a.month-b.month),last=months.at(-1),d=rollup?.daily||{},c=d.contact||{},districts=job?.districts||[];
 const answered=sum(c.answered),abandoned=sum(c.abandoned),mo=k=>months.length?sum(months.map(m=>m.billing?.[k])):null,cs=k=>months.length?sum(months.map(m=>m.cases?.[k])):null;
 return {homes:job?.homes??rollup?.totalHomes??null,completedHomes:districts.filter(x=>x.result).reduce((s,x)=>s+(x.homes||0),0),districts:districts.length,completed:districts.filter(x=>x.result).length,firstPass:districts.filter(x=>x.probe&&!x.result).length,
  accounts:rollup?.accounts??null,registers:rollup?.registers??null,status:job?.status??null,asOf:rollup?.asOf??job?.inputs?.request?.asOf??null,
  staffing:job?.inputs?.staffing==='shared'?'shared':'independent',floatShare:staffing?.floatShare??job?.inputs?.floatShare??null,network:job?.inputs?.network==='connected'?'connected':'independent',
  billed:mo('billed'),collected:mo('collected'),receivable:last?.billing?.receivable??null,overdue:last?.billing?.overdue??null,lastMonth:last?.month??null,
  casesOpened:cs('opened'),casesResolved:cs('resolved'),backlog:last?.cases?.backlog??null,
  contacts:c.contacts?sum(c.contacts):null,answered,abandoned,answeredPct:answered+abandoned>0?answered/(answered+abandoned):null,
  outages:Object.fromEntries(UTILITIES.filter(u=>d.outages?.[u]).map(u=>[u,sum(d.outages[u].customerHours)])),
  events:network?upstreamEvents(network).length:null};
}
// The network's events once each (a district's list repeats an event that reached it): its asset (from the id
// UP-<asset>-<YYYYMMDD>, else the asset of that utility feeding exactly those districts), its hours and the districts
// it reached in the layout's order; by day, start and id.
export function upstreamEvents(network){
 const assets=new Map((network?.assets||[]).map(a=>[a.id,a])),pos=new Map((network?.districts||[]).map((d,i)=>[d,i])),rank=d=>pos.get(d)??Infinity,byId=new Map();
 for(const [district,up] of Object.entries(network?.upstream||{}))for(const ev of up?.events||[]){if(!ev||typeof ev.id!=='string')continue;let row=byId.get(ev.id);
  if(!row){const m=/^UP-(.+)-\d{8}$/.exec(ev.id);row={id:ev.id,asset:m&&assets.has(m[1])?m[1]:null,utility:ev.utility??null,day:ev.day??null,start:finite(ev.start)?ev.start:null,end:finite(ev.end)?ev.end:null,label:ev.label??'',districts:[]};byId.set(ev.id,row);}
  if(!row.districts.includes(district))row.districts.push(district);}
 const order=list=>list.slice().sort((a,b)=>rank(a)-rank(b)||cmp(a,b));
 return [...byId.values()].map(r=>{r.districts=order(r.districts);if(!r.asset){const want=r.districts.join('\n');r.asset=[...assets.values()].find(a=>a.utility===r.utility&&order(a.districts||[]).join('\n')===want)?.id??null;}
  r.kind=assets.get(r.asset)?.kind??null;r.hours=r.start!=null&&r.end!=null?(r.end-r.start)/3600:null;return r;}).sort((a,b)=>cmp(a.day,b.day)||(a.start??0)-(b.start??0)||cmp(a.id,b.id));
}
export function networkLayout(network,events=upstreamEvents(network)){const count=new Map();for(const ev of events)if(ev.asset)count.set(ev.asset,(count.get(ev.asset)||0)+1);
 return (network?.assets||[]).map(a=>({id:a.id,kind:a.kind,utility:a.utility,districts:[...(a.districts||[])],events:count.get(a.id)||0}));}
// District ids in the layout's order, neighbours run together: "district-0001 – district-0004, district-0006".
export function districtSpan(ids,order=[]){const pos=new Map(order.map((d,i)=>[d,i])),runs=[];
 for(const id of [...new Set(ids)].sort((a,b)=>(pos.get(a)??Infinity)-(pos.get(b)??Infinity)||cmp(a,b))){const p=pos.get(id),last=runs.at(-1);if(last&&p!=null&&last.end+1===p){last.ids.push(id);last.end=p;}else runs.push({ids:[id],end:p??NaN});}
 return runs.map(r=>r.ids.length>2?`${r.ids[0]} – ${r.ids.at(-1)}`:r.ids.join(', ')).join(', ');}
// One pool of the shared staffing, per day: the top districts by staff-days (in district order, so a district keeps
// its colour while the set holds) and the rest folded into "Other"; each district's home team, the days it had more
// than its home team (float staff) and its mean; the pool and float team; the predicted work waiting, all districts.
export function stackPool(staffing,pool,top=TOP){const rows=staffing?.staff?.[pool],info=staffing?.pools?.[pool],ids=staffing?.districts||[];if(!Array.isArray(rows)||!info)return null;
 const days=Math.max(0,...rows.map(r=>Array.isArray(r)?r.length:0)),val=(i,t)=>{const v=rows[i]?.[t];return finite(v)?v:0;};
 const districts=ids.map((id,i)=>{const home=finite(info.home?.[i])?info.home[i]:0;let total=0,floatDays=0;for(let t=0;t<days;t++){const v=val(i,t);total+=v;if(v>home+1e-9)floatDays++;}return {id,i,home,total,mean:days?total/days:0,floatDays};});
 const keep=new Set(districts.slice().sort((a,b)=>b.total-a.total||a.i-b.i).slice(0,districts.length>top?top:districts.length).map(d=>d.i)),rest=districts.filter(d=>!keep.has(d.i));
 const series=districts.filter(d=>keep.has(d.i)).map((d,k)=>({id:d.id,label:d.id,color:SERIES[k%SERIES.length],values:Array.from({length:days},(_,t)=>val(d.i,t))}));
 if(rest.length)series.push({id:null,label:`Other (${rest.length} district${rest.length===1?'':'s'})`,color:OTHER_COLOR,values:Array.from({length:days},(_,t)=>rest.reduce((s,d)=>s+val(d.i,t),0))});
 for(const d of districts)d.color=series.find(s=>s.id===d.id)?.color??OTHER_COLOR;
 const pw=staffing?.predictedWaiting?.[pool],predicted=Array.from({length:days},(_,t)=>ids.reduce((s,_,i)=>s+(finite(pw?.[i]?.[t])?pw[i][t]:0),0));
 return {pool,label:poolLabel(pool),people:PEOPLE.has(pool),total:finite(info.total)?info.total:null,float:finite(info.float)?info.float:null,days,series,districts,predicted,folded:rest.length};}
export function paged(rows,page=1,size=PAGE_SIZE){const total=rows.length,pages=Math.max(1,Math.ceil(total/size)),p=Math.min(Math.max(1,Math.floor(Number(page))||1),pages);return {rows:rows.slice((p-1)*size,p*size),page:p,pages,total,from:total?(p-1)*size+1:0,to:Math.min(total,p*size)};}
// The districts table's rows: identity, size, how far the batch got with it, its home team and float days per pool
// (and on any pool) and the upstream events that reached it.
export function districtRows(job,{staffing=null,network=null}={}){const at=new Map((staffing?.districts||[]).map((d,i)=>[d,i])),pools=Object.keys(staffing?.pools||{});
 return (job?.districts||[]).map(d=>{const i=at.get(d.id),team={},floatDays={};let any=null;
  if(i!=null){const above=new Set();for(const p of pools){const home=staffing.pools[p].home?.[i],row=staffing.staff?.[p]?.[i]||[];team[p]=finite(home)?home:null;if(!finite(home)){floatDays[p]=null;continue;}let n=0;row.forEach((v,t)=>{if(finite(v)&&v>home+1e-9){n++;above.add(t);}});floatDays[p]=n;}any=above.size;}
  return {id:d.id,homes:d.homes??null,premises:d.probe?.premises??null,runKey:d.result?.runKey??null,status:d.result?'done':d.probe?'first pass':'waiting',team,floatDays,floatDaysAny:any,events:network?(network.upstream?.[d.id]?.events||[]).length:null};});}

// ---- day-by-day charts -----------------------------------------------------------------------------------------
// Small multiples over the year's days, x by month. `agg` says how a month (and the year) reads a series: its sum,
// its last day or its peak day. Colours are fixed per entity (queue, crew type, utility).
const ser=(label,values,color,scale)=>({label,values,color,scale});
export const DAY_CHARTS=[
 {id:'waiting',title:'Work waiting',unit:'cases waiting for analysts and supervisors at the day’s end',kind:'line',fmt:'int',agg:'max',series:d=>[ser('Analysts',d.staff?.analysts?.waiting,SERIES[0]),ser('Supervisors',d.staff?.supervisors?.waiting,SERIES[1])]},
 {id:'oldest',title:'Oldest work waiting',unit:'days, the oldest case waiting anywhere in the utility',kind:'line',fmt:'num',agg:'max',series:d=>[ser('Analysts',d.staff?.analysts?.oldestDays,SERIES[0]),ser('Supervisors',d.staff?.supervisors?.oldestDays,SERIES[1])]},
 {id:'crews',title:'Crew work waiting',unit:'hours of released field work waiting, by crew type',kind:'area',fmt:'num',agg:'max',series:d=>CREWS.map((c,k)=>ser(prettyKey(c),d.crews?.[c]?.waitingMin,SERIES[k],1/60))},
 {id:'contacts',title:'Calls answered and abandoned',unit:'calls that reached the agents’ queue, a day',kind:'line',fmt:'int',agg:'sum',series:d=>[ser('Answered',d.contact?.answered,SERIES[0]),ser('Abandoned',d.contact?.abandoned,SERIES[1])]},
 {id:'outages',title:'Outage customer-hours',unit:'customer-hours without service, on the day each outage began',kind:'bars',fmt:'int',agg:'sum',series:d=>UTILITIES.map(u=>ser(prettyKey(u),d.outages?.[u]?.customerHours,UTILITY_COLORS[u]))},
 {id:'backlog',title:'Case backlog by queue',unit:'open cases at the day’s end',kind:'area',fmt:'int',agg:'end',series:d=>{const keys=[...Object.keys(QUEUES),...Object.keys(d.queues||{}).filter(q=>!(q in QUEUES)).sort()];return keys.map((q,k)=>ser(QUEUES[q]||prettyKey(q.toLowerCase()),d.queues?.[q]?.backlog,k<SERIES.length?SERIES[k]:OTHER_COLOR));}},
];
export const AGG_LABEL={sum:'year total',end:'at year end',max:'peak day'},AGG_MONTH={sum:'monthly totals',end:'at each month’s end',max:'each month’s peak day'};
export function summarize(values,agg){const vs=(values||[]).filter(finite);if(!vs.length)return null;return agg==='sum'?vs.reduce((a,b)=>a+b,0):agg==='end'?vs.at(-1):Math.max(...vs);}
// A chart over `days` days from `start`: the series that have figures (scaled), each day's top (the stack's sum or
// the highest line) and the y scale.
export function dayModel(spec,start,days){
 const series=(spec.series||[]).filter(s=>Array.isArray(s?.values)).map(s=>({label:s.label,color:s.color||OTHER_COLOR,values:Array.from({length:days},(_,i)=>finite(s.values[i])?s.values[i]*(s.scale??1):null)}));
 const stacked=spec.kind!=='line',tops=Array.from({length:days},(_,i)=>{let t=null;for(const s of series){const v=s.values[i];if(v!=null)t=stacked?(t??0)+Math.max(0,v):Math.max(t??v,v);}return t;});
 let peak=0;for(const v of tops)if(v!=null&&v>peak)peak=v;
 return {...spec,series,start,days,tops,stacked,...niceTicks(peak)};
}
export function dayCharts(daily){if(!daily?.start||!(daily.days>0))return [];return DAY_CHARTS.map(c=>dayModel({...c,series:c.series(daily)},daily.start,daily.days));}
export function monthStarts(start,days){const out=[];for(let i=0;i<days;i++){const d=dayDate(start,i);if(i===0||d.endsWith('-01'))out.push({i,month:Number(d.slice(5,7))});}return out;}
// The table twin of a chart: one row a month, each series read by the chart's `agg`.
export function monthRows(model){const by=new Map();for(let i=0;i<model.days;i++){const m=dayDate(model.start,i).slice(0,7);if(!by.has(m))by.set(m,[]);by.get(m).push(i);}
 return [...by].map(([month,idx])=>({month,values:model.series.map(s=>summarize(idx.map(i=>s.values[i]),model.agg))}));}
export function readout(model,i){const day=dayDate(model.start,i),rows=model.series.map(s=>[s.label,s.values[i],s.color]);if(model.stacked&&model.series.length>1)rows.push(['Total',model.tops[i],null]);return {day,rows};}
export const GEOM={w:320,h:150,left:44,right:10,top:10,bottom:22};
const tickKind=f=>f==='money'?'money':f==='pct'?'pct':'';
export function daySvg(model,{id='ut',geom=GEOM}={}){const g=geom,pw=g.w-g.left-g.right,ph=g.h-g.top-g.bottom,n=Math.max(1,model.days),slot=pw/n,f=v=>Number(v.toFixed(2));
 const x=i=>f(g.left+(i+.5)*slot),y=v=>f(g.top+ph-(Math.max(0,v)/model.max)*ph);
 const grid=model.ticks.map(t=>`<line class="yr-grid" x1="${g.left}" x2="${g.w-g.right}" y1="${y(t)}" y2="${y(t)}"/><text class="yr-tick" x="${g.left-6}" y="${f(y(t)+3)}" text-anchor="end">${e(fmtTick(t,tickKind(model.fmt)))}</text>`).join('');
 const ms=monthStarts(model.start,model.days),xl=ms.map((m,k)=>{const a=g.left+m.i*slot,b=k+1<ms.length?g.left+ms[k+1].i*slot:g.left+pw;return `<line class="ut-mtick" x1="${f(a)}" x2="${f(a)}" y1="${g.top+ph}" y2="${g.top+ph+4}"/><text class="yr-tick" x="${f((a+b)/2)}" y="${g.h-7}" text-anchor="middle">${MONTHS[m.month-1][0]}</text>`;}).join('');
 let marks='';
 if(model.kind==='line'){for(const s of model.series){let d='',pen=false;s.values.forEach((v,i)=>{if(v==null){pen=false;return;}d+=`${pen?'L':'M'}${x(i)} ${y(v)}`;pen=true;});if(d)marks+=`<path class="yr-line ut-line" d="${d}" stroke="${s.color}"/>`;}}
 else if(model.kind==='area'){let base=new Array(model.days).fill(0);for(const s of model.series){const top=base.map((b,i)=>b+Math.max(0,s.values[i]??0));if(top.some((v,i)=>v>base[i]))marks+=`<path class="ut-area" d="M${top.map((v,i)=>`${x(i)} ${y(v)}`).join(' L')} L${base.map((v,i)=>`${x(i)} ${y(v)}`).reverse().join(' L')} Z" fill="${s.color}"/>`;base=top;}}
 else{const bw=f(Math.max(.6,slot*.85));for(let i=0;i<model.days;i++){let b=0;for(const s of model.series){const v=s.values[i];if(!(v>0))continue;const y0=y(b),y1=y(b+v);marks+=`<rect x="${f(x(i)-bw/2)}" y="${y1}" width="${bw}" height="${f(Math.max(.6,y0-y1))}" fill="${s.color}"/>`;b+=v;}}}
 return `<svg class="yr-svg ut-svg" viewBox="0 0 ${g.w} ${g.h}" role="group" aria-labelledby="${id}-t"><title id="${id}-t">${e(model.title)}</title>${grid}<line class="yr-axis" x1="${g.left}" x2="${g.w-g.right}" y1="${g.top+ph}" y2="${g.top+ph}"/>${xl}${marks}<line class="ut-cross" x1="0" x2="0" y1="${g.top}" y2="${g.top+ph}" visibility="hidden"/><rect class="ut-hit" x="${g.left}" y="${g.top}" width="${f(pw)}" height="${ph}" fill="transparent" tabindex="0" aria-label="${e(model.title)}, day by day. Arrow keys move a day, Page Up and Page Down a month."/></svg>`;}
export function monthTable(model){const rows=monthRows(model);return `<table><thead><tr><th>Month</th>${model.series.map(s=>`<th>${e(s.label)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr><td>${MONTHS[Number(r.month.slice(5,7))-1]}</td>${r.values.map(v=>`<td>${fmt(v,model.fmt)}</td>`).join('')}</tr>`).join('')}</tbody></table><p class="yr-note">${e(AGG_MONTH[model.agg]||'')}</p>`;}
// A chart card: title, unit, the headline (the stack's or first line's year figure), the chart, legend and table.
export function chartCard(model,key){const head=summarize(model.stacked?model.tops:model.series[0]?.values,model.agg);
 if(!model.series.length||head==null)return `<article class="yr-card ut-card"><header><div><h3>${e(model.title)}</h3><p>${e(model.unit)}</p></div></header><p class="ut-empty">No figures for this in the batch.</p></article>`;
 const legend=model.series.length>1?`<ul class="yr-legend">${model.series.map(s=>`<li><i class="${model.kind==='line'?'is-line':''}" style="background:${s.color}"></i>${e(s.label)} <strong>${fmt(summarize(s.values,model.agg),model.fmt)}</strong></li>`).join('')}</ul>`:'';
 const flat=model.tops.every(v=>v==null||v===0)?'<p class="yr-note">Zero on every day of the year.</p>':'';
 return `<article class="yr-card ut-card" data-chart="${e(key)}"><header><div><h3>${e(model.title)}</h3><p>${e(model.unit)}</p></div><div class="yr-latest"><strong>${fmt(head,model.fmt)}</strong>${e(model.stacked?AGG_LABEL[model.agg]:`${model.series[0].label}, ${AGG_LABEL[model.agg]}`)}</div></header>${daySvg(model,{id:'ut-'+key.replace(/[^a-z0-9-]/gi,'-')})}<div class="yr-tip" hidden></div>${flat}${legend}<details class="yr-table"><summary>Table</summary><div class="ut-twin">${monthTable(model)}</div></details></article>`;}

// ---- page sections ---------------------------------------------------------------------------------------------
const tile=(label,value,sub='')=>`<div><span>${e(label)}</span><strong>${value}</strong>${sub?`<small>${sub}</small>`:''}</div>`;
export function statusMarkup(job){const n=(job?.districts||[]).length,done=(job?.districts||[]).filter(d=>d.result).length;if(job?.status==='complete'&&done===n)return '';
 const first=(job?.districts||[]).filter(d=>d.probe&&!d.result).length,what={paused:'paused',running:'still running',finalizing:'finishing',queued:'queued'}[job?.status]||'not complete';
 return `<div class="ut-banner" role="note"><strong>This batch is ${e(what)}.</strong> ${num(done)} of ${num(n)} districts are finished${first?`, ${num(first)} more through the first pass`:''}. The figures cover the finished districts only. ${job?.status==='paused'?'Run the same batch-run command again to resume it.':'Reload this page to see later districts.'}</div>`;}
export function kpiMarkup(k,{rollup=true}={}){rollup=rollup&&(k.lastMonth!=null||k.contacts!=null);const mon=k.lastMonth&&k.lastMonth<12?`at the end of ${MONTHS[k.lastMonth-1]}`:'at year end';
 const util=[tile('Homes',num(k.homes),k.completedHomes!==k.homes?`${num(k.completedHomes)} finished`:''),tile('Districts',k.completed===k.districts?num(k.districts):`${num(k.completed)} of ${num(k.districts)}`,k.completed===k.districts?'all finished':'finished'),tile('Accounts',num(k.accounts),k.completed<k.districts?'in finished districts':''),tile('Registers',num(k.registers),k.completed<k.districts?'in finished districts':''),
  tile('Staffing',k.staffing==='shared'?'Shared':'Independent',k.staffing==='shared'?(finite(k.floatShare)?`one workforce, float share ${Math.round(k.floatShare*100)}%`:'one workforce'):'each district its own team'),tile('Network',k.network==='connected'?'Connected':'Independent',k.network==='connected'?(k.events!=null?`${num(k.events)} upstream event${k.events===1?'':'s'}`:'shared upstream assets'):'no shared upstream assets')];
 const year=rollup?[tile('Billed',money(k.billed)),tile('Collected',money(k.collected)),tile('Receivable',money(k.receivable),e(mon)+(finite(k.overdue)?` · ${money(k.overdue)} overdue`:'')),tile('Cases opened',num(k.casesOpened),finite(k.casesResolved)?`${num(k.casesResolved)} resolved`:''),tile('Case backlog',num(k.backlog),e(mon)),
  tile('Contacts',num(k.contacts),finite(k.answered)?`${num(k.answered)} answered, ${num(k.abandoned)} abandoned`:''),tile('Answered',k.answeredPct==null?'—':fmt(k.answeredPct,'pct'),'of the calls that reached the agents'),
  ...UTILITIES.filter(u=>u in k.outages).map(u=>tile(`${prettyKey(u)} outages`,num(Math.round(k.outages[u])),'customer-hours'))]:[];
 return `<h2 class="ut-sub">The utility</h2><div class="ut-kpis">${util.join('')}</div>${rollup?`<h2 class="ut-sub">The year${k.asOf?` to ${e(k.asOf)}`:''}</h2><div class="ut-kpis">${year.join('')}</div>`:''}`;}
export function poolOptions(staffing,pool){return Object.keys(staffing?.pools||{}).sort((a,b)=>(Object.keys(POOLS).indexOf(a)+1||99)-(Object.keys(POOLS).indexOf(b)+1||99)).map(p=>`<option value="${e(p)}"${p===pool?' selected':''}>${e(poolLabel(p))}</option>`).join('');}
// The chosen pool's two charts: staff per district per day (stacked) and the predicted work waiting (hours).
export function staffModels(staffing,pool,start='2026-01-01'){const s=stackPool(staffing,pool);if(!s)return null;
 return {s,alloc:dayModel({id:'alloc',title:`${s.label} per district`,unit:s.people?'people working in each district, a day':'crews working in each district, a day',kind:'area',fmt:s.people?'int':'crew',agg:'max',series:s.series},start,s.days),
  pred:dayModel({id:'pred',title:'Predicted work waiting',unit:`hours of ${s.label.toLowerCase()} work the coordinator predicted still waiting, all districts`,kind:'line',fmt:'num',agg:'max',series:[{label:'Predicted waiting',values:s.predicted,color:SERIES[0],scale:pool==='agents'?1/3600:1/60}]},start,s.days)};}
export function staffMarkup(staffing,models,{keys={alloc:'staff-alloc',pred:'staff-pred'}}={}){if(!models)return '<p class="ut-empty">The plan has no such pool.</p>';const {s,alloc,pred}=models,unit=s.people?'int':'crew',share=s.total?s.float/s.total:null;
 const team=`<article class="yr-card ut-card ut-team"><header><div><h3>Home teams</h3><p>${e(s.label)}: the team based in each district, and the days it had more (float staff)</p></div></header><div class="ut-team-table"><table><thead><tr><th>District</th><th>Home team</th><th>Days with float</th><th>Mean a day</th></tr></thead><tbody>${s.districts.map(d=>`<tr><td><i style="background:${d.color}"></i>${e(d.id)}</td><td>${fmt(d.home,unit)}</td><td>${num(d.floatDays)}</td><td>${fmt(d.mean,s.people?'num':'crew')}</td></tr>`).join('')}</tbody></table></div>${s.folded?`<p class="yr-note">The chart shows the ${TOP} districts with the most staff-days; ${num(s.folded)} more are in “Other”.</p>`:''}</article>`;
 return `<p class="ut-float"><strong>Float team ${fmt(s.float,unit)} of ${fmt(s.total,unit)} ${e(s.label.toLowerCase())}</strong>${share!=null?` (${Math.round(share*100)}%)`:''}; home teams ${fmt(s.total!=null&&s.float!=null?s.total-s.float:null,unit)}.${finite(staffing?.floatShare)?` Float share asked: ${Math.round(staffing.floatShare*100)}%.`:''}</p><div class="year-trends ut-staff-grid">${chartCard(alloc,keys.alloc)}${team}${chartCard(pred,keys.pred)}</div>`;}
export function districtsMarkup(rows,{page=1,pool=null,manifests=new Map(),base,origin,shared=false,connected=false}={}){const pg=paged(rows,page),label=pool?poolLabel(pool):'';
 const cell=(row,k)=>{const m=row.runKey?manifests.get(row.runKey):null;if(!row.runKey)return '—';if(!m)return '<span class="ut-pending">…</span>';if(m.error)return `<span title="${e(m.error)}">—</span>`;return num(m[k]);};
 const head=`<th>District</th><th>Run</th><th>Status</th><th>Homes</th><th>Premises</th><th>Accounts</th><th>Registers</th>${shared?`<th>Home ${e(label.toLowerCase())}</th><th>Float days, ${e(label.toLowerCase())}</th><th>Float days, any pool</th>`:''}${connected?'<th>Upstream events</th>':''}`;
 const body=pg.rows.map(r=>{const link=r.runKey&&base?runLink(base,r.runKey,origin):null;return `<tr><td>${e(r.id)}</td><td>${link?`<a class="ut-runlink" href="${e(link)}">Open run</a>`:'—'}</td><td>${e(r.status==='done'?'Finished':r.status==='first pass'?'First pass done':'Waiting')}</td><td>${num(r.homes)}</td><td>${num(r.premises)}</td><td>${cell(r,'accounts')}</td><td>${cell(r,'registers')}</td>${shared?`<td>${fmt(r.team[pool],PEOPLE.has(pool)?'int':'crew')}</td><td>${num(r.floatDays[pool])}</td><td>${num(r.floatDaysAny)}</td>`:''}${connected?`<td>${num(r.events)}</td>`:''}</tr>`;}).join('');
 return `<div class="run-work-table ut-table"><table><thead><tr>${head}</tr></thead><tbody>${body||`<tr><td colspan="12">This batch lists no districts.</td></tr>`}</tbody></table></div><div class="run-actions ut-pager"><button type="button" class="small-link" data-page="${pg.page-1}"${pg.page<=1?' disabled':''}>Previous</button><span>${pg.total?`${num(pg.from)}–${num(pg.to)} of ${num(pg.total)} districts · page ${pg.page} of ${pg.pages}`:'No districts'}</span><button type="button" class="small-link" data-page="${pg.page+1}"${pg.page>=pg.pages?' disabled':''}>Next</button></div>`;}
// True when every district has the same storm seed: one weather over the utility.
export const sharedWeather=network=>{const seeds=Object.values(network?.upstream||{}).map(u=>u?.stormSeed).filter(Boolean);return seeds.length>1&&seeds.every(x=>x===seeds[0]);};
// The year's upstream events on one lane per utility (a mark from the event's start for its duration), the events
// table and the layout: which districts each shared asset feeds.
export function eventsMarkup(network,{start='2026-01-01',days=365}={}){const evs=upstreamEvents(network),lay=networkLayout(network,evs),order=network?.districts||[],t0=Date.parse(start+'T00:00:00Z');
 const lanes=UTILITIES.filter(u=>lay.some(a=>a.utility===u)||evs.some(ev=>ev.utility===u)),ms=monthStarts(start,days);
 const at=ev=>((Date.parse(ev.day+'T00:00:00Z')-t0)/86400000+(ev.start??0)/86400);
 const strip=lanes.map(u=>`<div class="ut-lane"><span>${e(prettyKey(u))}</span><svg viewBox="0 0 ${days} 10" preserveAspectRatio="none" aria-hidden="true">${ms.map(m=>`<line x1="${m.i}" x2="${m.i}" y1="0" y2="10"/>`).join('')}${evs.filter(ev=>ev.utility===u&&ev.day).map(ev=>`<rect x="${Number(at(ev).toFixed(3))}" y="1.5" width="${Number(Math.max(2,(ev.hours??0)/24).toFixed(3))}" height="7" rx=".6" fill="${UTILITY_COLORS[u]||OTHER_COLOR}"><title>${e(ev.label)} · ${e(ev.day)} · ${fmt(ev.hours,'num')} h</title></rect>`).join('')}</svg></div>`).join('');
 const axis=`<div class="ut-lane ut-axis"><span></span><div>${ms.map(m=>`<i style="left:${Number((m.i/days*100).toFixed(2))}%">${MONTHS[m.month-1][0]}</i>`).join('')}</div></div>`;
 const table=evs.length?`<div class="run-work-table ut-table"><table><thead><tr><th>Date</th><th>Starts</th><th>Duration</th><th>Asset</th><th>Utility</th><th>Event</th><th>Districts reached</th></tr></thead><tbody>${evs.map(ev=>`<tr><td>${e(ev.day)}</td><td>${clock(ev.start)}</td><td>${ev.hours==null?'—':fmt(ev.hours,'num')+' h'}${ev.end!=null&&ev.end>=86400?' <small>(into the next day)</small>':''}</td><td>${e(ev.asset??'—')}${ev.kind?` <small>${e(ASSET_KINDS[ev.kind]||ev.kind)}</small>`:''}</td><td>${e(prettyKey(ev.utility||'—'))}</td><td>${e(ev.label)}</td><td>${num(ev.districts.length)}: ${e(districtSpan(ev.districts,order))}</td></tr>`).join('')}</tbody></table></div>`:'<p class="ut-empty">No upstream events this year: every shared asset kept supplying its districts.</p>';
 const layout=`<div class="run-work-table ut-table"><table><thead><tr><th>Asset</th><th>Kind</th><th>Utility</th><th>Feeds</th><th>Events</th></tr></thead><tbody>${lay.map(a=>`<tr><td>${e(a.id)}</td><td>${e(ASSET_KINDS[a.kind]||a.kind||'—')}</td><td>${e(prettyKey(a.utility||'—'))}</td><td>${num(a.districts.length)}: ${e(districtSpan(a.districts,order))}</td><td>${num(a.events)}</td></tr>`).join('')||'<tr><td colspan="5">The layout lists no shared assets.</td></tr>'}</tbody></table></div>`;
 return `<p class="ut-lede">${num(evs.length)} event${evs.length===1?'':'s'} on the shared assets this year, each reaching every district the asset feeds as that district’s upstream input.${sharedWeather(network)?' The districts share one weather (storm days and hours), each with its own faults.':''}</p>${lanes.length?`<div class="ut-timeline" role="img" aria-label="${e(`${evs.length} upstream events over the year, by utility; listed in the table below`)}">${strip}${axis}</div>`:''}${table}<h3 class="ut-h3">Layout</h3>${layout}`;}

// ---- the page --------------------------------------------------------------------------------------------------
if(typeof document!=='undefined'){
 const $=id=>document.getElementById(id);let S=null,openTicket=0,tableTicket=0;const charts=new Map(),cursor=new Map();
 function status(message,error=false){$('ut-status').textContent=message;$('ut-status').classList.toggle('run-error',error);$('ut-status').setAttribute('role',error?'alert':'status');}
 const notice=msg=>`<p class="ut-notice" role="note">${e(msg)}</p>`;
 function register(models){for(const [key,model] of models)charts.set(key,model);}
 function staffSection(){const {staffing}=S;if(!staffing)return notice(S.problems.staffing||MISSING.staffing);
  const keys={alloc:'staff-alloc',pred:'staff-pred'},models=staffModels(staffing,S.pool,S.rollup?.daily?.start||'2026-01-01');if(models)register([[keys.alloc,models.alloc],[keys.pred,models.pred]]);
  return `<div class="run-work-tools"><label>Pool <select id="ut-pool">${poolOptions(staffing,S.pool)}</select></label></div><div id="ut-staff-body">${staffMarkup(staffing,models,{keys})}</div>`;}
 function renderStaff(){const el=$('ut-staff');if(el){el.innerHTML=staffSection();$('ut-pool')?.addEventListener('change',ev=>{S.pool=ev.target.value;renderStaff();renderDistricts();});}}
 function renderDistricts(){const el=$('ut-districts-body');if(!el)return;S.page=paged(S.rows,S.page).page;el.innerHTML=districtsMarkup(S.rows,{page:S.page,pool:S.pool,manifests:S.manifests,base:S.base,origin:location.href,shared:!!S.staffing,connected:!!S.network});loadManifests();}
 // Accounts and registers from each listed district's run manifest (validated like the run viewer's), page by page.
 async function loadManifests(){const ticket=++tableTicket,want=paged(S.rows,S.page).rows.filter(r=>r.runKey&&!S.manifests.has(r.runKey));if(!want.length)return;const base=S.base;
  await Promise.all(want.map(async r=>{let v;try{const m=(await RunBundle.fromURL(runBase(base,r.runKey).href)).manifest,t=m.towns[0];if(m.runKey!==r.runKey)throw Error('The run manifest belongs to another run.');v={accounts:t.accounts,registers:t.registers};}catch(err){v={error:err.message};}if(S?.base===base)S.manifests.set(r.runKey,v);}));
  if(ticket===tableTicket&&S?.base===base)renderDistricts();}
 function render(){const {job,rollup,staffing,network,problems}=S,k=utilityKpis({job,rollup,staffing,network}),models=dayCharts(rollup?.daily);charts.clear();cursor.clear();
  register(models.map(m=>['day-'+m.id,m]));
  const daysHtml=!rollup?notice(problems.rollup||MISSING.rollup):models.length?`<div class="year-trends">${models.map(m=>chartCard(m,'day-'+m.id)).join('')}</div>`:notice('No district has finished yet, so the utility has no days to show.');
  const evStart=rollup?.daily?.start||(k.asOf?k.asOf.slice(0,4)+'-01-01':'2026-01-01'),evDays=rollup?.daily?.days||Math.round((Date.parse((Number(evStart.slice(0,4))+1)+'-01-01')-Date.parse(evStart))/86400000);
  $('ut-root').innerHTML=`<header class="ut-head"><span class="section-kicker">UTILITY${k.asOf?' · SAVED THROUGH '+e(k.asOf):''}</span><h1>A utility of ${num(k.districts)} district${k.districts===1?'':'s'}</h1><p>${e(rollup?.note||'')}</p><p class="run-key">Batch ${e(job.key||'')}</p></header>${statusMarkup(job)}
   <section class="ut-section" aria-label="Key figures">${kpiMarkup(k,{rollup:!!rollup})}${!rollup?notice(problems.rollup||MISSING.rollup):k.lastMonth==null&&k.contacts==null?notice('No district has finished yet: the year’s totals come with the first finished district.'):''}</section>
   <section class="ut-section" aria-labelledby="ut-days-h"><h2 id="ut-days-h">The utility day by day</h2><p class="ut-lede">Every finished district’s days added up; the oldest waiting work is the oldest anywhere. Point at a chart, or focus it and use the arrow keys, to read a day; each chart’s table has its months.</p>${daysHtml}</section>
   ${S.shared?`<section class="ut-section" aria-labelledby="ut-staff-h"><h2 id="ut-staff-h">Staff allocation</h2><p class="ut-lede">One workforce: each district keeps a home team and the coordinator sends the float team, each working day, where the work still waits. Choose a pool.</p><div id="ut-staff"></div></section>`:''}
   <section class="ut-section" aria-labelledby="ut-districts-h"><h2 id="ut-districts-h">Districts</h2><p class="ut-lede">Each district is a full saved run: open it in the run viewer for its year, tables and worklists.${S.staffing?' Home team and float days are for the pool chosen above.':''}</p><div id="ut-districts-body"></div></section>
   ${S.connected?`<section class="ut-section" aria-labelledby="ut-events-h"><h2 id="ut-events-h">Upstream events</h2>${network?eventsMarkup(network,{start:evStart,days:evDays}):notice(problems.network||MISSING.network)}</section>`:''}`;
  renderStaff();renderDistricts();
  $('ut-context').hidden=false;$('ut-context').textContent=`${num(k.districts)} districts · ${num(k.homes)} homes${k.asOf?` · saved through ${k.asOf}`:''} · ${String(job.key||'').slice(0,12)} · read-only`;
  document.title=`Utility of ${k.districts} districts · Utility Studio`;}
 async function openBatch(raw){const ticket=++openTicket;status('Opening the batch…');
  try{const base=batchURL(raw),data=await loadBatch(base);if(ticket!==openTicket)return;
   const pools=Object.keys(data.staffing?.pools||{});S={...data,base,pool:pools.includes('analysts')?'analysts':pools[0]||null,page:1,manifests:new Map(),rows:districtRows(data.job,{staffing:data.staffing,network:data.network})};
   $('ut-open').hidden=true;render();const url=new URL(location.href);url.searchParams.set('batch',raw);history.replaceState(null,'',url);
   const soft=Object.values(data.problems);status(soft.length?`Batch opened; ${soft.length} file${soft.length===1?' is':'s are'} missing or unreadable (see below).`:'Batch opened. No engine connection is needed.');
  }catch(err){if(ticket===openTicket){status(err.message,true);$('ut-open').hidden=false;}}}
 // The crosshair: one day, every series; pointer, or keyboard on the focused chart.
 function show(hit,i){const card=hit.closest('[data-chart]'),model=charts.get(card?.dataset.chart);if(!model)return;i=Math.max(0,Math.min(model.days-1,i));cursor.set(card.dataset.chart,i);
  const g=GEOM,slot=(g.w-g.left-g.right)/Math.max(1,model.days),cx=g.left+(i+.5)*slot,svg=hit.ownerSVGElement,line=svg.querySelector('.ut-cross'),tip=card.querySelector('.yr-tip'),r=readout(model,i);
  line.setAttribute('x1',cx);line.setAttribute('x2',cx);line.setAttribute('visibility','visible');
  const head=document.createElement('strong');head.textContent=longDay(r.day);tip.replaceChildren(head,...r.rows.map(([label,v,color])=>{const row=document.createElement('div'),key=document.createElement('i'),b=document.createElement('b'),l=document.createElement('span');if(color)key.style.background=color;b.textContent=fmt(v,model.fmt);l.textContent=label;row.append(key,b,l);return row;}));
  const pct=cx/g.w,box=svg.getBoundingClientRect(),cardBox=card.getBoundingClientRect();tip.hidden=false;tip.classList.toggle('is-left',pct<.25);tip.classList.toggle('is-right',pct>.75);tip.style.left=(box.left-cardBox.left+pct*box.width).toFixed(1)+'px';}
 function hide(hit){const card=hit.closest('[data-chart]');card?.querySelector('.ut-cross')?.setAttribute('visibility','hidden');const tip=card?.querySelector('.yr-tip');if(tip)tip.hidden=true;}
 const root=$('ut-root');
 const point=ev=>{const hit=ev.target.closest?.('.ut-hit');if(!hit)return;const card=hit.closest('[data-chart]'),model=charts.get(card?.dataset.chart);if(!model)return;const r=hit.ownerSVGElement.getBoundingClientRect(),vx=(ev.clientX-r.left)*GEOM.w/r.width;show(hit,Math.floor((vx-GEOM.left)/((GEOM.w-GEOM.left-GEOM.right)/model.days)));};
 root.addEventListener('pointermove',point);root.addEventListener('pointerdown',point);
 root.addEventListener('pointerout',ev=>{const hit=ev.target.closest?.('.ut-hit');if(hit&&document.activeElement!==hit)hide(hit);});
 root.addEventListener('focusin',ev=>{const hit=ev.target.closest?.('.ut-hit');if(!hit)return;const key=hit.closest('[data-chart]')?.dataset.chart,model=charts.get(key);if(model)show(hit,cursor.get(key)??Math.max(0,model.tops.findLastIndex(v=>v!=null)));});
 root.addEventListener('focusout',ev=>{const hit=ev.target.closest?.('.ut-hit');if(hit)hide(hit);});
 root.addEventListener('keydown',ev=>{const hit=ev.target.closest?.('.ut-hit');if(!hit)return;const key=hit.closest('[data-chart]')?.dataset.chart,model=charts.get(key);if(!model)return;const i=cursor.get(key)??0,step={ArrowLeft:-1,ArrowRight:1,PageUp:-30,PageDown:30}[ev.key];
  if(step!=null){ev.preventDefault();show(hit,i+step);}else if(ev.key==='Home'){ev.preventDefault();show(hit,0);}else if(ev.key==='End'){ev.preventDefault();show(hit,model.days-1);}});
 root.addEventListener('click',ev=>{const b=ev.target.closest?.('[data-page]');if(!b||b.disabled||!S)return;S.page=Number(b.dataset.page);renderDistricts();$('ut-districts-h')?.scrollIntoView({block:'start'});});
 $('ut-url-form').onsubmit=ev=>{ev.preventDefault();openBatch($('ut-url').value.trim());};
 const batch=new URLSearchParams(location.search).get('batch');if(batch){$('ut-url').value=new URL(batch,location.href).href;openBatch(batch);}else{$('ut-open').hidden=false;}
}
