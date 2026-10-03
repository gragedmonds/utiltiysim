// Year: the calendar of the simulated year 2026, the episodes inflicted on it and the month-by-month trends of the run.
// An episode is a scenario from the engine's library (GET /api/m2c/scenarios) applied from a day the analyst clicks;
// episodes are run input like actions and settings (EngineM2C.episodes, on every request), so the engine replays the
// year with them (first request after a change: 5–15 s) and POST /api/m2c/trend returns the twelve months' figures.
// This page draws the calendar and the charts, edits episodes and formats; nothing here computes a figure.
// Route: #/year.
import {engineNotice} from './workspace.js';
import {bindPopovers} from './config-page.js';
import {episodeDates,YEAR_END} from './m2c.js';
import {fmtCell} from './data-page.js';
import {prettyKey} from './schema-form.js';
export const ROUTE=/^#\/year$/;
export const YEAR=2026;
export const MAX_EPISODES=40;
export function parseYearRoute(hash){return ROUTE.test(String(hash||''))?{year:YEAR}:null;}
export function yearHash(){return '#/year';}
const e=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const INT=new Intl.NumberFormat('en-CA',{maximumFractionDigits:0});
const MONTHS=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'],WEEKDAYS=['M','T','W','T','F','S','S'];
const addDays=(day,n)=>new Date(Date.parse(day+'T12:00:00Z')+n*86400000).toISOString().slice(0,10);
const isDay=d=>/^\d{4}-\d{2}-\d{2}$/.test(String(d||''))&&!Number.isNaN(Date.parse(d+'T12:00:00Z'));
export const longDay=day=>new Intl.DateTimeFormat('en-GB',{weekday:'short',day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}).format(new Date(day+'T12:00:00Z')).replace(',','');
export const shortDay=day=>new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'short',timeZone:'UTC'}).format(new Date(day+'T12:00:00Z'));
export const rangeLabel=ep=>`${shortDay(ep.from)} – ${ep.to&&ep.to<YEAR_END?shortDay(ep.to):'year end'}`;
// ---- the calendar model ----------------------------------------------------------------------------------------
// Twelve months with their weekday offset (Monday first: 0..6 for the 1st) and day count, for a 7-column grid.
export function calendarModel(year=YEAR){return MONTHS.map((label,i)=>{const first=new Date(Date.UTC(year,i,1)),days=new Date(Date.UTC(year,i+1,0)).getUTCDate(),offset=(first.getUTCDay()+6)%7;
 const mm=String(i+1).padStart(2,'0');return {month:i+1,label,days,offset,weeks:Math.ceil((offset+days)/7),start:`${year}-${mm}-01`,end:`${year}-${mm}-${String(days).padStart(2,'0')}`};});}
// The day ranges (1-based, inside the month) each episode covers in a month, in episode order; `to` null runs to the
// year end. `index` is the episode's position in the list (its colour), `lane` its row under this month.
export function episodeSpans(episodes,month){const mo=typeof month==='number'?calendarModel()[month-1]:month;if(!mo)return [];const out=[];
 for(let index=0;index<(episodes||[]).length;index++){const ep=episodes[index];if(!ep?.from)continue;const to=ep.to||YEAR_END;if(ep.from>mo.end||to<mo.start)continue;
  const from=ep.from<mo.start?1:Number(ep.from.slice(8,10)),last=to>mo.end?mo.days:Number(to.slice(8,10));
  out.push({id:ep.id,index,lane:out.length,from,to:last,startsHere:ep.from>=mo.start,endsHere:to<=mo.end});}
 return out;}
// Episode colours: the dataviz palette rotated to open on the Studio's violet; past eight an episode reuses a colour
// (the legend and the bar's label still tell them apart).
export const EPISODE_COLORS=['#4a3aa7','#e34948','#2a78d6','#eb6834','#1baf7a','#eda100','#e87ba4','#008300'];
export const episodeColor=i=>EPISODE_COLORS[((i%EPISODE_COLORS.length)+EPISODE_COLORS.length)%EPISODE_COLORS.length];
// ---- settings values -------------------------------------------------------------------------------------------
// An episode setting as typed: true/false and plain numbers set the value; a leading *, + or - is an operator on the
// base value ("*0.5", "+2", "-1"), kept as text for the engine. Anything else stays text (an enum value); the engine validates.
export function parseSettingValue(raw){if(typeof raw!=='string')return raw;const s=raw.trim();if(s==='')return undefined;
 if(s==='true')return true;if(s==='false')return false;const op=s.match(/^([*+-])\s*(\d+(?:\.\d+)?)$/);if(op)return op[1]+op[2];
 const n=Number(s);return s!==''&&Number.isFinite(n)?n:s;}
// A panel draft (dates, ramp and settings rows as typed) as one episode, or the first thing wrong with it.
export function draftEpisode(d){if(!isDay(d.from)||!d.from.startsWith(YEAR+'-'))return {error:`Start must be a ${YEAR} date.`};
 const to=d.to?String(d.to).trim():'';if(to&&(!isDay(to)||!to.startsWith(YEAR+'-')))return {error:`End must be a ${YEAR} date, or blank for the year end.`};if(to&&to<d.from)return {error:'End is before the start.'};
 const ramp=d.ramp===''||d.ramp==null?0:Number(d.ramp);if(!Number.isInteger(ramp)||ramp<0)return {error:'Ramp is a whole number of days.'};
 const settings={};for(const [g,keys] of Object.entries(d.settings||{}))for(const [k,raw] of Object.entries(keys||{})){const v=parseSettingValue(raw);if(v===undefined)return {error:`${g}.${k} needs a value.`};(settings[g]||={})[k]=v;}
 if(!Object.keys(settings).length)return {error:'An episode changes at least one setting.'};
 return {episode:{title:String(d.title||'').trim()||d.scenario||'Episode',scenario:d.scenario||null,from:d.from,to:to&&to<YEAR_END?to:null,ramp,settings}};}
// Settings as rows for the panel: [group, key, value as text].
export const settingRows=settings=>Object.entries(settings||{}).flatMap(([g,keys])=>Object.entries(keys||{}).map(([k,v])=>[g,k,v==null?'':String(v)]));
// ---- the trend charts ------------------------------------------------------------------------------------------
// Small multiples over the twelve months; one card per KPI family. Series colours follow the validated dataviz palette
// in fixed slot order (the first series of every chart is slot 1). `pick` reads a figure the engine wrote.
export const SERIES=['#2a78d6','#eb6834','#1baf7a','#eda100','#e87ba4','#008300','#4a3aa7','#e34948'];
export const QUEUES={VEE_REVIEW:'VEE review',ESTIMATION:'Estimation',SUPERVISOR:'Supervisor',FIELD:'Field',BILLING:'Billing',COLLECTIONS:'Collections'};
export const PHASES=['overdue','reminder','overdue notice','winter moratorium','dunning hold','payment arrangement','disconnection notice','disconnected']; // `current` accounts are not in collections: shown as a note, not stacked
const queueLabel=q=>QUEUES[q]||prettyKey(String(q).toLowerCase());
// The contact centre's reason groups and reasons (utilsim/m2c/contact.py), as the trend's byGroup and byReason keys.
export const CONTACT_GROUPS={billing:'Billing',payments:'Payments & collections',service:'Service orders',emergency:'Outages & emergencies',complaints:'Complaints'};
export const CONTACT_REASONS={high_bill:'High bill',bill_question:'Bill question',bill_wrong:'Bill wrong',back_bill:'Back bill',balance:'Balance',password:'Online account',payment_arrangement:"Can't pay",payment_problem:'Payment problem',disconnection:'Disconnected',move_in:'Start service',move_out:'Stop service',new_connection:'New connection',meter_access:'Meter access',outage:'Outage report',gas_odour:'Gas odour',complaint:'Complaint'};
// The field work programmes (utilsim/m2c/fieldwork.py), as the trend's field.byProgram and field.backlog keys.
export const FIELD_PROGRAMS={emergency:'Customer emergencies',service:'Service orders',meter:'Meter maintenance',maintenance:'Preventative maintenance',construction:'Capital construction'};
const hoursOrDash=v=>v==null?'—':Number(v).toLocaleString('en-CA',{maximumFractionDigits:1});
export const CHARTS=[
 {id:'backlog',title:'Case backlog',unit:'open cases at month end',kind:'line',fmt:'int',series:[{label:'Backlog',pick:m=>m.cases?.backlog}],detail:m=>Object.entries(m.cases?.byQueue||{}).map(([q,v])=>[queueLabel(q),v])},
 {id:'cases',title:'Cases opened and resolved',unit:'cases in the month',kind:'line',fmt:'int',series:[{label:'Opened',pick:m=>m.cases?.opened},{label:'Resolved',pick:m=>m.cases?.resolved}]},
 {id:'reads',title:'Reads missed and estimated',unit:'share of scheduled reads',kind:'line',fmt:'pct',series:[{label:'Missed',pick:m=>m.reads?.missedPct},{label:'Estimated',pick:m=>m.reads?.estimatedPct}]},
 {id:'cost',title:'Cost and carry',unit:'dollars in the month (labour, system, CX) and carried',kind:'line',fmt:'money',series:[{label:'Cost',pick:m=>m.cost?.total},{label:'Carry',pick:m=>m.cost?.carry}]},
 {id:'blocked',title:'Billing blocked',unit:'documents blocked in the month',kind:'bars',fmt:'int',series:[{label:'Blocked',pick:m=>m.billing?.blocked}]},
 {id:'cash',title:'Invoiced and collected',unit:'dollars in the month',kind:'line',fmt:'money',series:[{label:'Invoiced',pick:m=>m.billing?.invoiced},{label:'Collected',pick:m=>m.billing?.collected}]},
 {id:'ar',title:'Receivable and overdue',unit:'dollars at month end',kind:'line',fmt:'money',series:[{label:'Receivable',pick:m=>m.billing?.receivable},{label:'Overdue',pick:m=>m.billing?.overdue}]},
 {id:'dunning',title:'Dunning',unit:'events in the month',kind:'stack',fmt:'int',series:[{label:'Reminders',pick:m=>m.collections?.reminders},{label:'Notices',pick:m=>m.collections?.notices},{label:'Disconnect notices',pick:m=>m.collections?.disconnectNotices},{label:'Disconnected',pick:m=>m.collections?.disconnected}]},
 {id:'phases',title:'Accounts in collections',unit:'accounts at month end, by phase',kind:'stack',fmt:'int',series:PHASES.map(p=>({label:prettyKey(p),pick:m=>m.collections?.phases?.[p]})),detail:m=>m.collections?.phases?.current==null?[]:[['Current (not in collections)',m.collections.phases.current]]},
 {id:'contacts',title:'Contacts',unit:'contacts in the month, by reason group',kind:'stack',fmt:'int',series:Object.entries(CONTACT_GROUPS).map(([g,label])=>({label,pick:m=>m.contact?.byGroup?.[g]})),detail:m=>Object.entries(m.contact?.byReason||{}).filter(([,v])=>v).sort((a,b)=>b[1]-a[1]).slice(0,6).map(([k,v])=>[CONTACT_REASONS[k]||prettyKey(k),v])},
 {id:'service',title:'Answered in target and hung up',unit:'share of calls that reached the agents',kind:'line',fmt:'pct',series:[{label:'In target',pick:m=>m.contact?.serviceLevelPct},{label:'Hung up',pick:m=>m.contact?.abandonedPct}],detail:m=>m.contact?[['Average wait (s)',m.contact.asaS??'—'],['Call backs',m.contact.callbacks],['Occupancy',m.contact.occupancyPct==null?'—':Math.round(m.contact.occupancyPct*100)+'%']]:[]},
 {id:'contactCost',title:'Contact centre cost',unit:'dollars in the month (agents, self-service, hang-ups, dispatch)',kind:'line',fmt:'money',series:[{label:'Cost',pick:m=>m.contact?.cost?.total}]},
 {id:'fieldDone',title:'Field work completed',unit:'work orders completed in the month, by programme',kind:'stack',fmt:'int',series:Object.entries(FIELD_PROGRAMS).map(([p,label])=>({label,pick:m=>m.field?.byProgram?.[p]})),detail:m=>m.field?[['Created',m.field.created],['Remote (AMI)',m.field.remote],['Crew hours',hoursOrDash(m.field.hours)],['Overtime hours',hoursOrDash(m.field.overtimeHours)]]:[]},
 {id:'fieldBacklog',title:'Field backlog',unit:'released orders open at month end, by programme',kind:'stack',fmt:'int',series:Object.entries(FIELD_PROGRAMS).map(([p,label])=>({label,pick:m=>m.field?.backlog?.[p]})),detail:m=>m.field?[['Overdue',m.field.overdue],['Crew utilisation',m.field.utilisationPct==null?'—':Math.round(m.field.utilisationPct*100)+'%']]:[]},
 {id:'fieldOnTime',title:'Field work on time',unit:'share of orders completed by their due date',kind:'line',fmt:'pct',series:[{label:'On time',pick:m=>m.field?.onTimePct}],detail:m=>m.field?[['Emergency response (min)',m.field.responseMin??'—'],['Response, slowest 10% (min)',m.field.responseP90Min??'—'],['Days to complete',m.field.daysToComplete??'—']]:[]},
 {id:'fieldCost',title:'Field work cost',unit:'dollars in the month (crew labour, overtime included, and materials)',kind:'stack',fmt:'money',series:[{label:'Labour',pick:m=>m.field?.cost?.labour},{label:'Materials',pick:m=>m.field?.cost?.materials}]},
];
// Clean axis ticks from 0 to a rounded maximum (1, 2, 2.5, 5 × 10^k steps, about four intervals).
export function niceTicks(max,n=4){const m=Number(max)>0?Number(max):0;if(!m)return {max:1,ticks:[0,1]};const raw=m/n,p=10**Math.floor(Math.log10(raw)),step=[1,2,2.5,5,10].map(s=>s*p).find(s=>s>=raw*.8);
 const top=Math.ceil(m/step-1e-9)*step,digits=Math.max(0,-Math.floor(Math.log10(step)))+1,ticks=[];for(let t=0;t<=top+step/2;t+=step)ticks.push(Number(t.toFixed(digits)));return {max:Number(top.toFixed(digits)),ticks};}
// A line through the months that have a figure; a gap where a month has none (a lone point draws as a dot).
export function linePath(values,x,y){let d='',run=0;for(let i=0;i<values.length;i++){const v=values[i];if(v==null){if(run===1)d+=` L${x(i-1)} ${y(values[i-1])}`;run=0;continue;}d+=`${d?' ':''}${run?'L':'M'}${x(i)} ${y(v)}`;run++;}
 if(run===1)d+=` L${x(values.length-1)} ${y(values[values.length-1])}`;return d;}
// A column with a 4px rounded cap and a square foot on the baseline.
export function barPath(x,y,w,h,r=4){if(h<=0)return '';const rr=Math.min(r,h/2,w/2),f=n=>Number(n.toFixed(2));return `M${f(x)} ${f(y+h)} V${f(y+rr)} Q${f(x)} ${f(y)} ${f(x+rr)} ${f(y)} H${f(x+w-rr)} Q${f(x+w)} ${f(y)} ${f(x+w)} ${f(y+rr)} V${f(y+h)} Z`;}
// Axis ticks, compact: $812K, $1.2M, 6.4K, 2.8%.
export function fmtTick(v,kind){if(v==null)return '';const n=Number(v);if(kind==='pct')return (n*100).toFixed(n*100>=10||n===0?0:1).replace(/\.0$/,'')+'%';
 const sign=n<0?'-':'',a=Math.abs(n),c=a>=1e6?(a/1e6).toFixed(a>=1e7?0:1).replace(/\.0$/,'')+'M':a>=1e3?(a/1e3).toFixed(a>=1e4?0:1).replace(/\.0$/,'')+'K':kind==='money'?String(Math.round(a)):String(Number(a.toFixed(2)));return sign+(kind==='money'?'$':'')+c;}
// Values in full, like the Data tab's cells; shares with one decimal.
export function fmtValue(v,kind){if(v==null)return '—';if(kind==='pct')return (Number(v)*100).toFixed(1)+'%';return fmtCell(v,{kind});}
// A chart's series over the twelve months (null where the engine wrote no figures: months after the run date), its
// scale and its latest month. The month holding the run date comes with figures up to that day and `complete: false`:
// drawn, and marked partial.
export function chartModel(chart,months){const idx=Array.from({length:12},(_,i)=>(months||[]).find(m=>m?.month===i+1)||null);
 const series=chart.series.map((s,k)=>({label:s.label,color:SERIES[k%SERIES.length],values:idx.map(m=>{if(!m)return null;const v=s.pick(m);return typeof v==='number'&&Number.isFinite(v)?v:null;})}));
 const tops=idx.map((_,i)=>{const vs=series.map(s=>s.values[i]).filter(v=>v!=null);if(!vs.length)return null;return chart.kind==='stack'?vs.reduce((a,b)=>a+b,0):Math.max(...vs);});
 const partial=idx.map((m,i)=>!!m&&m.complete===false&&tops[i]!=null);let latest=-1;for(let i=11;i>=0;i--)if(tops[i]!=null){latest=i;break;}
 return {...chart,series,tops,partial,latest,months:idx,...niceTicks(Math.max(0,...tops.filter(v=>v!=null)))};}
export const monthLabel=(model,i)=>MONTHS[i]+(model.partial[i]?` (to ${shortDay(model.months[i].end)})`:'');
// What a month says, as text (the hover readout, the hit target's label, the table row).
export function readout(model,i){const m=model.months[i];if(!m||model.tops[i]==null)return `${MONTHS[i]}: no figures yet`;
 const parts=model.series.filter(s=>s.values[i]!=null).map(s=>`${s.label} ${fmtValue(s.values[i],model.fmt)}`),extra=(model.detail?.(m)||[]).map(([k,v])=>`${k} ${fmtValue(v,'int')}`);
 return `${monthLabel(model,i)}: ${parts.join(' · ')}${extra.length?' · '+extra.join(' · '):''}`;}
export function describeChart(model){const n=model.tops.filter(v=>v!=null).length,li=model.latest;if(li<0)return `${model.title}, ${model.unit}. No figures yet.`;
 return `${model.title}, ${model.unit}. ${n} month${n===1?'':'s'}, ${MONTHS[model.tops.findIndex(v=>v!=null)]} to ${MONTHS[li]} ${YEAR}${model.partial[li]?`, ${MONTHS[li]} to the run date only`:''}. Latest, ${readout(model,li)}.`;}
export const GEOM={w:320,h:150,left:44,right:10,top:10,bottom:22};
// Inline SVG for one chart: hairline grid and ticks, episode bands, the run date, the marks, and one hit target per month.
export function chartSvg(model,{asOf=null,episodes=[],id='yr'}={}){const g=GEOM,pw=g.w-g.left-g.right,ph=g.h-g.top-g.bottom,slot=pw/12,cal=calendarModel(),f=n=>Number(n.toFixed(2));
 const x=i=>f(g.left+(i+.5)*slot),y=v=>f(g.top+ph-(v/model.max)*ph),dayX=day=>{if(!day||day>YEAR_END)return g.left+pw;const mi=Number(day.slice(5,7))-1,d=Number(day.slice(8,10));return f(g.left+(mi+(d-1)/cal[mi].days)*slot);};
 const grid=model.ticks.map(t=>`<line class="yr-grid" x1="${g.left}" x2="${g.w-g.right}" y1="${y(t)}" y2="${y(t)}"/><text class="yr-tick" x="${g.left-6}" y="${f(y(t)+3)}" text-anchor="end">${e(fmtTick(t,model.fmt))}</text>`).join('');
 const xl=MONTHS.map((m,i)=>`<text class="yr-tick" x="${x(i)}" y="${g.h-7}" text-anchor="middle">${m[0]}</text>`).join('');
 const bands=episodes.map((ep,k)=>{const a=dayX(ep.from),b=ep.to&&ep.to<YEAR_END?dayX(addDays(ep.to,1)):g.left+pw;return b<=a?'':`<rect class="yr-band" x="${a}" y="${g.top}" width="${f(b-a)}" height="${ph}" fill="${episodeColor(k)}"><title>${e(ep.title)} · ${e(rangeLabel(ep))}</title></rect>`;}).join('');
 const run=asOf&&asOf.startsWith(YEAR+'-')?`<line class="yr-run" x1="${dayX(asOf)}" x2="${dayX(asOf)}" y1="${g.top}" y2="${g.top+ph}"><title>Run date ${e(asOf)}</title></line>`:'';
 let marks='';
 if(model.kind==='line'){for(const s of model.series){const d=linePath(s.values,x,y);if(!d)continue;marks+=`<path class="yr-line" d="${d}" stroke="${s.color}"/>`;const li=model.latest;if(li>=0&&s.values[li]!=null)marks+=`<circle cx="${x(li)}" cy="${y(s.values[li])}" r="6" fill="#fff"/>`+(model.partial[li]?`<circle cx="${x(li)}" cy="${y(s.values[li])}" r="3" fill="#fff" stroke="${s.color}" stroke-width="2"/>`:`<circle cx="${x(li)}" cy="${y(s.values[li])}" r="4" fill="${s.color}"/>`);}}
 else{const bw=Math.min(24,slot-6);for(let i=0;i<12;i++){if(model.tops[i]==null)continue;const segs=model.series.map(s=>[s,s.values[i]]).filter(([,v])=>v>0);if(!segs.length)continue;let base=g.top+ph;
  segs.forEach(([s,v],k)=>{const h=(v/model.max)*ph,top=base-h,last=k===segs.length-1;marks+=last?`<path d="${barPath(x(i)-bw/2,top,bw,h)}" fill="${s.color}"/>`:(h>2?`<rect x="${f(x(i)-bw/2)}" y="${f(top+2)}" width="${f(bw)}" height="${f(h-2)}" fill="${s.color}"/>`:'');base=top;});}}
 const hits=model.months.map((m,i)=>model.tops[i]==null?'':`<rect class="yr-hit" x="${f(g.left+i*slot)}" y="${g.top}" width="${f(slot)}" height="${ph}" fill="transparent" tabindex="0" data-i="${i}" aria-label="${e(readout(model,i))}"></rect>`).join('');
 return `<svg class="yr-svg" viewBox="0 0 ${g.w} ${g.h}" role="img" aria-labelledby="${id}-t" aria-describedby="${id}-d"><title id="${id}-t">${e(model.title)}</title><desc id="${id}-d">${e(describeChart(model))}</desc>${grid}${bands}${run}<line class="yr-axis" x1="${g.left}" x2="${g.w-g.right}" y1="${g.top+ph}" y2="${g.top+ph}"/>${xl}${marks}${hits}</svg>`;}
// The table twin of a chart: every month, every series, the detail columns.
export function chartTable(model){const first=model.months.find((m,i)=>model.tops[i]!=null),extra=first&&model.detail?model.detail(first).map(([k])=>k):[];
 return `<table><thead><tr><th>Month</th>${model.series.map(s=>`<th>${e(s.label)}</th>`).join('')}${extra.map(k=>`<th>${e(k)}</th>`).join('')}</tr></thead><tbody>${model.months.map((m,i)=>{const det=m&&model.tops[i]!=null&&model.detail?Object.fromEntries(model.detail(m)):{};
  return `<tr><td>${MONTHS[i]}${model.partial[i]?'*':''}</td>${model.series.map(s=>`<td>${fmtValue(s.values[i],model.fmt)}</td>`).join('')}${extra.map(k=>`<td>${fmtValue(det[k],'int')}</td>`).join('')}</tr>`;}).join('')}</tbody></table>${model.partial.some(Boolean)?'<p class="yr-note">* to the run date, not a whole month</p>':''}`;}

export function installYearPage({getClient,getEngineState=()=>({state:'idle',towns:[]}),toast=()=>{},onDate=null,root=document.getElementById('year-root')}){
 const ui={library:null,trend:null,busy:false,recalc:false,error:'',panel:null,confirmClear:false,models:[]};
 let closePops=null;
 const client=()=>getClient?.()||null;
 const scenarioOf=id=>ui.library?.scenarios?.find(s=>s.id===id)||null;
 // ---- loading --------------------------------------------------------------------------------------------------
 async function loadLibrary(){const m=client();if(!m||m.readOnly||ui.library)return;try{ui.library=await m.scenarios();}catch(err){ui.error=err.message;}}
 // The trend for the current run; `recalc` says the run changed (the engine replays the year). Returns the error, if any.
 async function load({recalc=false}={}){const m=client();if(!m)return null;ui.busy=true;ui.recalc=recalc;ui.error='';render();
  try{ui.trend=await m.trend();ui.busy=false;ui.recalc=false;render();return null;}
  catch(err){if(err.superseded)return null;ui.busy=false;ui.recalc=false;ui.error=err.message;render();return err;}}
 async function open(hash){if(!parseYearRoute(hash))return;await loadLibrary();render();load();}
 function engineRefusal(err){const d=err.detail;return 'The engine refused it: '+(typeof d==='string'?d:Array.isArray(d)?d.map(x=>x?.msg||x?.message||JSON.stringify(x)).join('; '):d?.message||err.message);}
 // ---- episodes -------------------------------------------------------------------------------------------------
 async function inflict(){const m=client(),p=ui.panel;if(!m||p?.kind!=='inflict'||!p.draft)return;const parsed=[];
  for(const d of p.draft){const r=draftEpisode(d);if(r.error){p.error=r.error;render();return;}parsed.push(r.episode);}
  if(m.episodes.length+parsed.length>MAX_EPISODES){p.error=`At most ${MAX_EPISODES} episodes in a year.`;render();return;}
  const added=parsed.map(ep=>m.addEpisode(ep)),title=parsed.length>1?scenarioOf(p.scenario)?.title||added[0].title:added[0].title;
  ui.panel=null;toast(`Recalculating the year with ${title}…`);const err=await load({recalc:true});
  if(err?.status===422){for(const a of added)m.removeEpisode(a.id);ui.panel={...p,error:engineRefusal(err)};toast('The engine refused the episode.');await load();}}
 async function saveEdit(){const m=client(),p=ui.panel;if(!m||p?.kind!=='edit')return;const r=draftEpisode(p.draft);if(r.error){p.error=r.error;render();return;}
  const was=m.episodes.find(x=>x.id===p.id);if(!was)return;const before=JSON.parse(JSON.stringify(was));m.updateEpisode(p.id,r.episode);
  ui.panel=null;toast(`Recalculating the year with ${r.episode.title}…`);const err=await load({recalc:true});
  if(err?.status===422){m.updateEpisode(p.id,before);ui.panel={...p,error:engineRefusal(err)};await load();}}
 async function remove(id){const m=client();if(!m)return;const ep=m.episodes.find(x=>x.id===id);if(!m.removeEpisode(id))return;ui.panel=null;toast(`Recalculating the year without ${ep.title}…`);await load({recalc:true});}
 async function clearAll(){const m=client();if(!m)return;const n=m.episodes.length;m.clearEpisodes();ui.confirmClear=false;ui.panel=null;toast(`Recalculating the year without ${n} episode${n===1?'':'s'}…`);await load({recalc:true});}
 function viewDay(day){const m=client();if(!day)return;Promise.resolve(onDate?onDate(day):null).then(()=>{if(m&&m.asOf!==day)m.setAsOf(day);load();});}
 // ---- rendering ------------------------------------------------------------------------------------------------
 function head(){const m=client(),asOf=ui.trend?.asOf||m?.asOf||'',n=m?.readOnly?0:m?.episodes.length||0;
  return `<header class="year-head"><div><span class="section-kicker">RUN · ${YEAR}</span><h1 class="has-pop">Year<button type="button" class="schema-info" aria-label="About the Year" aria-expanded="false" title="About the Year">i</button><div class="schema-pop" role="note"><p>The simulated year, day by day. Click a day to inflict a scenario from the engine's library starting that day; the engine replays the whole year with that episode and the charts below show its mark, month by month.</p><p>Episodes are run input like your actions and settings: kept in this browser, sent with every request, applied by the engine. Settings in an episode are absolute (a number, true/false) or relative to the base (*0.5, +2, -1); a ramp slides a number there over that many days.</p></div></h1></div><div class="year-tools"><label>Run date <input type="date" id="year-asof" min="${YEAR}-01-01" max="${YEAR}-12-31" value="${e(asOf)}"></label>${n?ui.confirmClear?`<span class="year-confirm">Clear ${n} episode${n===1?'':'s'}? <button type="button" class="small-link" data-act="clear-yes">Yes, clear</button><button type="button" class="small-link" data-act="clear-no">Keep</button></span>`:`<button type="button" class="small-link" data-act="clear">Clear all episodes</button>`:''}</div></header>`;}
 function status(){const m=client(),t=ui.trend,n=m?.episodes.length||0,eps=`${n} episode${n===1?'':'s'}`;
  if(ui.error)return `<p class="year-status" role="status"><span class="year-error">${e(ui.error)}</span></p>`;
  if(!t)return `<p class="year-status" role="status">${ui.busy?(m?.readOnly?'Loading saved trends…':ui.recalc?'Recalculating the year… (5–15 s)':'Asking the engine… (a cold engine replays the year first, 5–15 s)'):''}</p>`;
  return `<p class="year-status" role="status">${m?.readOnly?'Saved results':'Engine data'} as of ${e(t.asOf)} · ${eps}${ui.busy?(ui.recalc?' · Recalculating the year…':' · Updating…'):''}</p>`;}
 function month(mo,asOf,eps){const spans=episodeSpans(eps,mo),selected=ui.panel?.kind==='inflict'?ui.panel.day:null,cells=[];
  for(let i=0;i<mo.offset;i++)cells.push('<span class="year-pad"></span>');
  for(let d=1;d<=mo.days;d++){const day=mo.start.slice(0,8)+String(d).padStart(2,'0'),wd=(mo.offset+d-1)%7,cls=['year-day',asOf&&day<=asOf?'is-past':'',day===asOf?'is-today':'',wd>=5?'is-weekend':'',day===selected?'is-selected':''].filter(Boolean).join(' ');
   cells.push(`<button type="button" class="${cls}" data-day="${day}" aria-label="${e(longDay(day))}${day===asOf?', the run date':''}"${day===selected?' aria-pressed="true"':''}>${d}</button>`);}
  const bars=spans.map(s=>{const ep=eps[s.index];return `<button type="button" class="year-bar${s.startsHere?' starts':''}${s.endsHere?' ends':''}" data-ep="${e(ep.id)}" style="left:${((s.from-1)/mo.days*100).toFixed(2)}%;width:${((s.to-s.from+1)/mo.days*100).toFixed(2)}%;top:${s.lane*6}px;background:${episodeColor(s.index)}" title="${e(ep.title)} · ${e(rangeLabel(ep))}" aria-label="Edit ${e(ep.title)}, ${e(rangeLabel(ep))}"></button>`;}).join('');
  return `<div class="year-month"><h2>${mo.label}</h2><div class="year-grid">${WEEKDAYS.map(w=>`<span class="year-wd" aria-hidden="true">${w}</span>`).join('')}${cells.join('')}</div><div class="year-strip" style="height:${Math.max(1,spans.length)*6+2}px">${bars}</div></div>`;}
 function legend(eps){if(!eps.length)return '<p class="year-legend-empty">No episodes yet. Click a day to inflict a scenario from that date.</p>';
  return `<ul class="year-legend" aria-label="Episodes">${eps.map((ep,i)=>`<li><button type="button" class="year-leg" data-ep="${e(ep.id)}" aria-label="Edit ${e(ep.title)}"><i style="background:${episodeColor(i)}"></i><strong>${e(ep.title)}</strong><span>${e(rangeLabel(ep))}${ep.ramp?` · ramp ${ep.ramp} d`:''}</span></button></li>`).join('')}</ul>`;}
 function calendar(){const m=client(),asOf=ui.trend?.asOf||m?.asOf||'',eps=m?.episodes||[];
  return `<section class="year-calendar" aria-label="Calendar ${YEAR}"><div class="year-months">${calendarModel().map(mo=>month(mo,asOf,eps)).join('')}</div>${legend(eps)}</section>`;}
 function card(model,k){const m=client(),asOf=ui.trend?.asOf||m?.asOf||null,eps=m?.episodes||[],li=model.latest,one=model.series.length===1;
  const when=li<0?'':model.partial[li]?`${MONTHS[li]} to ${shortDay(model.months[li].end)}`:MONTHS[li],latest=li<0?'<strong>—</strong><span>no figures yet</span>':one?`<strong>${e(fmtValue(model.series[0].values[li],model.fmt))}</strong><span>${e(when)}</span>`:`<span>latest · ${e(when)}</span>`;
  const leg=one?'':`<ul class="yr-legend">${model.series.map(s=>`<li><i class="${model.kind==='line'?'is-line':''}" style="background:${s.color}"></i><span>${e(s.label)}</span>${li>=0&&s.values[li]!=null?`<strong>${e(fmtValue(s.values[li],model.fmt))}</strong>`:''}</li>`).join('')}</ul>`;
  return `<article class="yr-card" data-chart="${k}"><header><div><h3>${e(model.title)}</h3><p>${e(model.unit)}</p></div><div class="yr-latest">${latest}</div></header>${chartSvg(model,{asOf,episodes:eps,id:'yr-'+model.id})}<div class="yr-tip" hidden></div>${leg}<details class="yr-table"><summary>Table</summary>${chartTable(model)}</details></article>`;}
 function trends(){const t=ui.trend;if(!t)return `<section class="year-trends" aria-label="Trends"><div class="yr-empty">${ui.busy?'':'No trend yet.'}</div></section>`;
  ui.models=CHARTS.map(c=>chartModel(c,t.months));return `<section class="year-trends${ui.busy?' is-stale':''}" aria-label="Trends">${ui.models.map(card).join('')}</section>`;}
 function library(p){const lib=ui.library;if(!lib)return `<p class="small-note">${ui.error?e(ui.error):'Loading the scenario library…'}</p>`;
  return (lib.groups||[]).map(g=>{const own=(lib.scenarios||[]).filter(s=>s.group===g.id),soon=(lib.coming||[]).filter(s=>s.group===g.id);if(!own.length&&!soon.length)return '';
   return `<h3>${e(g.title)}</h3>${own.map(s=>`<div class="year-sc"><button type="button" class="year-sc-pick" data-sc="${e(s.id)}"><strong>${e(s.title)}</strong><span>${e(s.description||'')}</span></button>${s.watch?`<details><summary>What to watch</summary><p>${e(s.watch)}</p></details>`:''}${s.tags?.length?`<span class="year-tags">${s.tags.map(t=>`<em>${e(t)}</em>`).join('')}</span>`:''}</div>`).join('')}${soon.map(s=>`<div class="year-sc is-coming" aria-disabled="true"><strong>${e(s.title)}<em class="year-soon">coming soon</em></strong><span>${e(s.description||'')}</span></div>`).join('')}`;}).join('')||'<p class="small-note">The library is empty.</p>';}
 function draftForm(drafts,{single=false}={}){return drafts.map((d,k)=>`<fieldset class="year-ep"><legend>${single?'Episode':`Episode ${k+1}`}</legend><label class="year-f">Title <input type="text" data-k="${k}" data-f="title" value="${e(d.title||'')}" maxlength="80"></label><div class="year-f-row"><label class="year-f">Start <input type="date" data-k="${k}" data-f="from" min="${YEAR}-01-01" max="${YEAR}-12-31" value="${e(d.from||'')}"></label><label class="year-f">End <input type="date" data-k="${k}" data-f="to" min="${YEAR}-01-01" max="${YEAR}-12-31" value="${e(d.to||'')}" placeholder="year end"></label><label class="year-f">Ramp <input type="number" data-k="${k}" data-f="ramp" min="0" max="365" step="1" value="${e(d.ramp??0)}"> days</label></div><table class="year-settings"><thead><tr><th>Setting</th><th>Value</th></tr></thead><tbody>${settingRows(d.settings).map(([g,key,v])=>`<tr><td><span>${e(prettyKey(g))}</span><code>${e(g)}.${e(key)}</code></td><td><input type="text" data-k="${k}" data-g="${e(g)}" data-key="${e(key)}" value="${e(v)}" aria-label="${e(g)}.${e(key)}"></td></tr>`).join('')||'<tr><td colspan="2">No settings.</td></tr>'}</tbody></table></fieldset>`).join('')+'<p class="small-note">A number or true/false sets the value for the episode; *0.5, +2 or -1 change the base value. Blank end: to the year end.</p>';}
 function panel(){const p=ui.panel;if(!p)return '';const m=client();
  if(p.kind==='inflict'){const sc=p.scenario?scenarioOf(p.scenario):null;
   return `<aside class="year-panel" aria-label="Inflict a scenario"><header><div><span class="section-kicker">INFLICT ON</span><h2>${e(longDay(p.day))}</h2></div><button type="button" class="close-btn" data-act="close" aria-label="Close">×</button></header><div class="year-panel-actions"><button type="button" class="outline-btn" data-act="view-day">View this day</button>${m?.asOf===p.day?'<span class="small-note">This is the run date.</span>':''}</div>${p.error?`<p class="year-error" role="alert">${e(p.error)}</p>`:''}${sc?`<button type="button" class="small-link" data-act="back">← Library</button><h3 class="year-sc-title">${e(sc.title)}</h3><p class="small-note">${e(sc.description||'')}</p>${sc.watch?`<p class="year-watch"><strong>Watch</strong> ${e(sc.watch)}</p>`:''}${draftForm(p.draft)}<div class="year-panel-foot"><button type="button" class="primary-btn" data-act="inflict">Inflict</button></div>`:`<p class="small-note">Pick a scenario; its episodes start on this day.</p><div class="year-library">${library(p)}</div>`}</aside>`;}
  const ep=m?.episodes.find(x=>x.id===p.id);if(!ep){return '';}
  return `<aside class="year-panel" aria-label="Edit an episode"><header><div><span class="section-kicker">EPISODE ${e(ep.id)}</span><h2>${e(ep.title)}</h2></div><button type="button" class="close-btn" data-act="close" aria-label="Close">×</button></header>${ep.scenario?`<p class="small-note">From the scenario ${e(scenarioOf(ep.scenario)?.title||ep.scenario)}.</p>`:''}${p.error?`<p class="year-error" role="alert">${e(p.error)}</p>`:''}${draftForm([p.draft],{single:true})}<div class="year-panel-foot"><button type="button" class="primary-btn" data-act="save">Save</button><button type="button" class="small-link" data-act="remove">Remove</button></div></aside>`;}
 function render(){if(!root)return;const m=client();
  if(!m){root.innerHTML=`<section class="fiori-shell"><div class="fiori-empty ws-empty">${engineNotice(getEngineState(),undefined,'#/year','The Year')}</div></section>`;root.querySelector('[data-ws="retry"]')?.addEventListener('click',()=>location.reload());return;}
  root.innerHTML=`<div class="year-layout${ui.panel?' has-panel':''}"><main class="year-main">${head()}${status()}${calendar()}${trends()}</main>${panel()}</div>`;
  if(m.readOnly){root.querySelector('#year-asof').disabled=true;for(const b of root.querySelectorAll('[data-day],[data-ep]')){b.disabled=true;b.removeAttribute('data-day');b.removeAttribute('data-ep');}const pop=root.querySelector('.schema-pop');if(pop)pop.innerHTML='<p>Saved engine results through '+e(m.asOf)+'. Episodes and trends are archived with this run. Open a live engine to change inputs or replay another date.</p>';const empty=root.querySelector('.year-legend-empty');if(empty)empty.textContent='No episodes in this saved run.';}
  closePops?.();closePops=bindPopovers(root);if(ui.panel)root.querySelector('.year-panel h2')?.scrollIntoView?.({block:'nearest'});}
 // ---- hover readout ----------------------------------------------------------------------------------------------
 function showTip(hit){const card=hit.closest('.yr-card'),model=ui.models[Number(card?.dataset.chart)],i=Number(hit.dataset.i);if(!card||!model)return;const tip=card.querySelector('.yr-tip'),m=model.months[i];
  const rows=[];const h=document.createElement('strong');h.textContent=`${MONTHS[i]} ${YEAR}`;rows.push(h);
  for(const s of model.series){if(s.values[i]==null)continue;const r=document.createElement('div'),key=document.createElement('i'),v=document.createElement('b'),l=document.createElement('span');key.style.background=s.color;v.textContent=fmtValue(s.values[i],model.fmt);l.textContent=s.label;r.append(key,v,l);rows.push(r);}
  for(const [k,v] of (m&&model.detail?model.detail(m):[])){const r=document.createElement('div');r.className='is-detail';const b=document.createElement('b'),l=document.createElement('span');b.textContent=fmtValue(v,'int');l.textContent=k;r.append(b,l);rows.push(r);}
  tip.replaceChildren(...rows);tip.hidden=false;tip.style.left=`${((Number(hit.getAttribute('x'))+Number(hit.getAttribute('width'))/2)/GEOM.w*100).toFixed(1)}%`;tip.classList.toggle('is-right',i>=8);tip.classList.toggle('is-left',i<3);}
 function hideTip(card){card?.querySelector('.yr-tip')?.setAttribute('hidden','');}
 // ---- events ---------------------------------------------------------------------------------------------------
 root?.addEventListener('click',ev=>{const b=ev.target.closest('button');if(!b||!root.contains(b))return;const m=client();if(m?.readOnly)return;
  if(b.dataset.day){ui.panel={kind:'inflict',day:b.dataset.day,scenario:null,draft:null,error:''};ui.confirmClear=false;render();return;}
  if(b.dataset.ep){const ep=m?.episodes.find(x=>x.id===b.dataset.ep);if(!ep)return;ui.panel={kind:'edit',id:ep.id,draft:{...JSON.parse(JSON.stringify(ep)),to:ep.to||''},error:''};render();return;}
  if(b.dataset.sc){const p=ui.panel,sc=scenarioOf(b.dataset.sc);if(p?.kind!=='inflict'||!sc)return;p.scenario=sc.id;p.draft=episodeDates(sc,p.day).map(d=>({...d,to:d.to||''}));p.error='';render();return;}
  switch(b.dataset.act){
   case 'close':ui.panel=null;render();return;
   case 'back':if(ui.panel){ui.panel.scenario=null;ui.panel.draft=null;ui.panel.error='';}render();return;
   case 'view-day':viewDay(ui.panel?.day);return;
   case 'inflict':inflict();return;
   case 'save':saveEdit();return;
   case 'remove':remove(ui.panel?.id);return;
   case 'clear':ui.confirmClear=true;render();return;
   case 'clear-no':ui.confirmClear=false;render();return;
   case 'clear-yes':clearAll();return;}});
 root?.addEventListener('input',ev=>{const el=ev.target,p=ui.panel;if(!p||el.dataset.k==null)return;const d=p.kind==='edit'?p.draft:p.draft?.[Number(el.dataset.k)];if(!d)return;
  if(el.dataset.f)d[el.dataset.f]=el.value;else if(el.dataset.g!=null){((d.settings||={})[el.dataset.g]||={})[el.dataset.key]=el.value;}});
 root?.addEventListener('change',ev=>{const el=ev.target;if(el.id==='year-asof'){const day=el.value;if(!day)return;viewDay(day);}});
 root?.addEventListener('pointermove',ev=>{const hit=ev.target.closest?.('.yr-hit');if(hit)showTip(hit);else hideTip(ev.target.closest?.('.yr-card'));});
 root?.addEventListener('pointerleave',()=>{for(const c of root.querySelectorAll('.yr-card'))hideTip(c);});
 root?.addEventListener('focusin',ev=>{const hit=ev.target.closest?.('.yr-hit');if(hit)showTip(hit);});
 root?.addEventListener('focusout',ev=>{if(ev.target.classList?.contains('yr-hit'))hideTip(ev.target.closest('.yr-card'));});
 root?.addEventListener('keydown',ev=>{if(ev.key==='Escape'&&ui.panel&&!ev.target.closest?.('input,select,textarea')){ui.panel=null;render();}});
 return {open,render,load,refresh(){if(parseYearRoute(location.hash)){if(client()&&!ui.trend)open(location.hash);else render();}},get state(){return ui;}};
}
