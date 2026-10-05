// Year: the calendar of the active simulated year (2026 first, then each year continued from it), the episodes inflicted
// on it and the month-by-month trends of the run.
// An episode is a scenario from the engine's library (GET /api/m2c/scenarios) applied from a day the analyst clicks;
// episodes are run input like actions and settings (EngineM2C.episodes, on every request), so the engine replays the
// year with them (first request after a change: 5–15 s) and POST /api/m2c/trend returns the twelve months' figures.
// The year switcher moves between the years opened; Continue opens the next year on this one's close (EngineM2C).
// This page draws the calendar and the charts, edits episodes and formats; nothing here computes a figure.
// Route: #/year (the client's active year).
// Plan mode (`plan: true`, local-runs.html with local-year.js LocalPlan): the same calendar, library, episode panel,
// bars and legend for a simulation run on the analyst's computer. Nothing runs: no trend charts, run date or years;
// the client's preview() gives the days sporadic episodes strike, and the episodes go into the next revision's job.
import {engineNotice} from './workspace.js';
import {fetchKpiCatalogue,fetchKpiValues,kpiStrip} from './kpis.js';
import {bindPopovers} from './config-page.js';
import {episodeDates,FIRST_YEAR,LAST_YEAR,activeYear,dayYear,yearEnd} from './m2c.js';
import {fmtCell} from './data-page.js';
import {prettyKey} from './schema-form.js';
import {money} from './worklists.js';
import {installSetupAgent,currentRunInput} from './setup-agent.js';
export const ROUTE=/^#\/year$/;
export const MAX_EPISODES=40;
export function parseYearRoute(hash){return ROUTE.test(String(hash||''))?{}:null;}
export function yearHash(){return '#/year';}
const e=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const INT=new Intl.NumberFormat('en-CA',{maximumFractionDigits:0});
const MONTHS=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'],WEEKDAYS=['M','T','W','T','F','S','S'];
const addDays=(day,n)=>new Date(Date.parse(day+'T12:00:00Z')+n*86400000).toISOString().slice(0,10);
const isDay=d=>/^\d{4}-\d{2}-\d{2}$/.test(String(d||''))&&!Number.isNaN(Date.parse(d+'T12:00:00Z'));
export const longDay=day=>new Intl.DateTimeFormat('en-GB',{weekday:'short',day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}).format(new Date(day+'T12:00:00Z')).replace(',','');
export const shortDay=day=>new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'short',timeZone:'UTC'}).format(new Date(day+'T12:00:00Z'));
// An episode's days; an end on 31 December of its year (or none) is the year end.
export const rangeLabel=ep=>`${shortDay(ep.from)} – ${ep.to&&ep.to<yearEnd(dayYear(ep.from)||FIRST_YEAR)?shortDay(ep.to):'year end'}`;
// ---- the calendar model ----------------------------------------------------------------------------------------
// Twelve months with their weekday offset (Monday first: 0..6 for the 1st) and day count, for a 7-column grid (29 Feb in a leap year).
export function calendarModel(year=FIRST_YEAR){return MONTHS.map((label,i)=>{const first=new Date(Date.UTC(year,i,1)),days=new Date(Date.UTC(year,i+1,0)).getUTCDate(),offset=(first.getUTCDay()+6)%7;
 const mm=String(i+1).padStart(2,'0');return {month:i+1,label,days,offset,weeks:Math.ceil((offset+days)/7),start:`${year}-${mm}-01`,end:`${year}-${mm}-${String(days).padStart(2,'0')}`};});}
// The day ranges (1-based, inside the month) each episode covers in a month, in episode order; `to` null runs to the
// year end. `index` is the episode's position in the list (its colour), `lane` its row under this month. A month number
// is a month of `year`.
export function episodeSpans(episodes,month,year=FIRST_YEAR){const mo=typeof month==='number'?calendarModel(year)[month-1]:month;if(!mo)return [];const out=[],end=mo.start.slice(0,4)+'-12-31';
 for(let index=0;index<(episodes||[]).length;index++){const ep=episodes[index];if(!ep?.from)continue;const to=ep.to||end;if(ep.from>mo.end||to<mo.start)continue;
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
// ---- sporadic episodes -----------------------------------------------------------------------------------------
// An episode's `pattern` makes it strike only some days of its window: `spikes` (count bursts of length days, one in
// each equal stretch) or `days` (a share of the days, scattered), each day at a strength (0–1) towards the episode's
// values. The engine draws the days (the trend's episodes[].hits); this page only edits the pattern and draws them.
export const STRIKE_KINDS={steady:'Every day',spikes:'Spikes',days:'Scattered days'};
const pairOf=(v,d)=>v==null?[d,d]:Array.isArray(v)?[v[0],v[1]]:[v,v];
const pctText=v=>String(Math.round(Number(v)*1000)/10);
const pct=v=>Math.round(Number(v)*100)+'%';
const plural=(n,one,many=one+'s')=>`${n} ${Number(n)===1?one:many}`;
// The "When it strikes" controls as typed (share and strength in %) for an episode's pattern; steady (no pattern)
// starts the other kinds from a few spikes of 1–2 days or 20% of the days, at full strength, on working days.
export function strikeDraft(p){const kind=p?.kind==='spikes'||p?.kind==='days'?p.kind:'steady',l=kind==='spikes'?pairOf(p.length,1):[1,2],st=kind==='steady'?[1,1]:pairOf(p.strength,1);
 return {kind,count:String(kind==='spikes'?p.count??'':4),lenMin:String(l[0]),lenMax:String(l[1]),share:pctText(kind==='days'?p.share:.2),strMin:pctText(st[0]),strMax:pctText(st[1]),workdays:kind==='steady'||p.workdays!==false,independent:kind!=='steady'&&!!p.independent,...(kind!=='steady'&&p.seed?{seed:String(p.seed)}:{})};}
// The days from `from` to `to` (inclusive) a pattern can strike: Monday to Friday when `workdays` (the engine also
// skips its holidays).
export function windowDays(from,to,workdays=true){let n=0;for(let t=Date.parse(from+'T12:00:00Z'),z=Date.parse(to+'T12:00:00Z');t<=z;t+=86400000){const wd=new Date(t).getUTCDay();if(!workdays||(wd!==0&&wd!==6))n++;}return n;}
// The controls as an episode's `pattern` ({pattern: null} for every day), or the first thing wrong with them, checked as
// the engine checks them: 1–60 whole spikes of 1–30 whole days (min ≤ max), a share above 0 up to 100%, a strength
// 0–100% (min ≤ max, max above 0). Share and strength become fractions; the window is `from`–`to`.
export function draftPattern(s,{from=null,to=null}={}){if(!s||!s.kind||s.kind==='steady')return {pattern:null};if(!(s.kind in STRIKE_KINDS))return {error:'When it strikes is every day, spikes or scattered days.'};
 const num=v=>String(v??'').trim()===''?NaN:Number(v),whole=(v,lo,hi)=>{const n=num(v);return Number.isInteger(n)&&n>=lo&&n<=hi?n:null;},frac=v=>Number((v/100).toFixed(6)),workdays=s.workdays!==false,out={kind:s.kind};
 const room=isDay(from)&&isDay(to)?windowDays(from,to,workdays):null,what=workdays?'working days':'days';if(room===0)return {error:`There are no ${what} between the start and the end.`};
 if(s.kind==='spikes'){const n=whole(s.count,1,60);if(n==null)return {error:'Spikes: how many is a whole number, 1–60.'};if(room!=null&&n>room)return {error:`${plural(n,'spike')} do not fit in ${plural(room,what.slice(0,-1),what)}.`};
  const l0=whole(s.lenMin,1,30),l1=whole(s.lenMax,1,30);if(l0==null||l1==null)return {error:'Days each is a whole number of days, 1–30.'};if(l0>l1)return {error:'Days each: the first number is more than the second.'};out.count=n;out.length=[l0,l1];}
 else{const sh=num(s.share);if(!Number.isFinite(sh)||sh<=0||sh>100||frac(sh)<=0)return {error:'Scattered days: the share of days is above 0% and up to 100%.'};out.share=frac(sh);}
 const a=num(s.strMin),b=num(s.strMax);if(![a,b].every(v=>Number.isFinite(v)&&v>=0&&v<=100))return {error:'Strength is 0–100%.'};if(a>b)return {error:'Strength: the first number is more than the second.'};if(b<=0)return {error:'Strength must reach above 0%.'};
 out.strength=[frac(a),frac(b)];out.workdays=workdays;out.independent=!!s.independent;if(s.seed)out.seed=String(s.seed);return {pattern:out};}
// A pattern in a few words, for the legend and the bar's label: "6 spikes · 1–2 d", "30% of working days", " · mixed"
// when each setting draws its own strength, and the days struck once the trend has them.
export function patternLabel(p,struck=null){if(!p)return '';const [l0,l1]=pairOf(p.length,1);
 return (p.kind==='spikes'?`${plural(p.count,'spike')} · ${l0===l1?l0:`${l0}–${l1}`} d`:`${pctText(p.share)}% of ${p.workdays===false?'days':'working days'}`)+(p.independent?' · mixed':'')+(struck==null?'':` · ${plural(struck,'day')} struck`);}
// A library scenario's sporadic templates in one line ('' for a steady scenario): "Sporadic: 6 spikes of 1–2 days over 6 months".
const overLabel=days=>days==null?'to the year end':days<14?`over ${plural(days,'day')}`:days<60?`over ${Math.round(days/7)} weeks`:`over ${Math.round(days/30.44)} months`;
export function scenarioPatternLine(sc){const lines=(sc?.episodes||[]).filter(t=>t?.pattern).map(t=>{const p=t.pattern,[l0,l1]=pairOf(p.length,1);
  return `${p.kind==='spikes'?`${plural(p.count,'spike')} of ${l0===l1?plural(l0,'day'):`${l0}–${l1} days`}`:`${pctText(p.share)}% of ${p.workdays===false?'days':'working days'}`} ${overLabel(t.durationDays??null)}${p.independent?', a different mix each day':''}`;});
 return lines.length?'Sporadic: '+lines.join('; '):'';}
// The days each sporadic episode strikes, from the trend's episodes (matched by id): id → [[day, strength 0–1]]. Only
// for an episode whose title, window and pattern are the trend's own, so a trend of an older shape is not drawn.
const shapeOf=p=>JSON.stringify([p.kind,p.kind==='spikes'?[Number(p.count),pairOf(p.length,1).map(Number)]:Number(p.share),pairOf(p.strength,1).map(Number),p.workdays!==false,!!p.independent,p.seed||null]);
export function episodeStrikes(trend,episodes){const out=new Map(),mine=new Map((episodes||[]).filter(ep=>ep?.pattern&&ep.id).map(ep=>[ep.id,ep]));
 for(const t of trend?.episodes||[]){const ep=mine.get(t?.id);if(!ep||!t.pattern||!Array.isArray(t.hits))continue;
  if(t.from!==ep.from||t.to!==(ep.to||yearEnd(dayYear(ep.from)||FIRST_YEAR))||(t.title!=null&&t.title!==String(ep.title||ep.id).slice(0,120))||shapeOf(t.pattern)!==shapeOf(ep.pattern))continue;
  out.set(ep.id,t.hits.filter(h=>Array.isArray(h)&&isDay(h[0])).map(([d,v])=>[d,Number(v)]));}
 return out;}
// A struck day as text: "Head end down · Fri 13 Feb 2026 · strength 89%".
export const strikeTitle=(ep,day,v)=>`${ep.title} · ${longDay(day)} · strength ${pct(v)}`;
// The "When it strikes" controls of the panel's draft `k` (strikeDraft as typed): every day, spikes or scattered days.
function strikeFields(s,k){const id=`yr-strike-${k}`,num=(p,label,min,max,step=1)=>`<input type="number" data-k="${k}" data-p="${p}" min="${min}" max="${max}" step="${step}" value="${e(s[p])}"${label?` aria-label="${e(label)}"`:''}>`;
 const kinds=Object.entries(STRIKE_KINDS).map(([v,l])=>`<label><input type="radio" name="${id}" data-k="${k}" data-p="kind" value="${v}"${s.kind===v?' checked':''}>${e(l)}</label>`).join('');
 const range=(a,b,label,unit,min,max,step)=>`<div class="year-f"><span aria-hidden="true">${e(label)}</span><span class="year-range">${num(a,`${label}, from`,min,max,step)}<span aria-hidden="true">–</span>${num(b,`${label}, to`,min,max,step)}${unit?`<span aria-hidden="true">${unit}</span>`:''}</span></div>`;
 const own=s.kind==='spikes'?`<div class="year-strike-row"><label class="year-f">How many spikes ${num('count','',1,60)}</label>${range('lenMin','lenMax','Days each','',1,30)}</div>`
  :s.kind==='days'?`<div class="year-strike-row"><label class="year-f">Share of the days, % ${num('share','',0,100,'any')}</label></div>`:'';
 const more=s.kind==='steady'?'<p class="small-note">The settings hold every day from the start to the end.</p>'
  :`${own}<div class="year-strike-row">${range('strMin','strMax','Strength','%',0,100,'any')}</div><label class="year-check"><input type="checkbox" data-k="${k}" data-p="workdays"${s.workdays!==false?' checked':''}> Working days only</label><label class="year-check"><input type="checkbox" data-k="${k}" data-p="independent"${s.independent?' checked':''}> A different mix each day</label><p class="small-note">${s.kind==='spikes'?'One spike in each equal stretch of the window.':'Scattered over the window.'} Strength: how far a struck day goes towards the episode's values (100%: all the way). A different mix: each setting its own strength each day. The engine draws the days from the run's seed.</p>`;
 return `<fieldset class="year-strike"><legend>When it strikes</legend><div class="year-seg">${kinds}</div>${more}</fieldset>`;}
// A panel draft (dates, ramp and settings rows as typed, and `strike`: the "When it strikes" controls, else the draft's
// own `pattern`) as one episode of `year`, or the first thing wrong with it.
export function draftEpisode(d,year=FIRST_YEAR){if(!isDay(d.from)||!d.from.startsWith(year+'-'))return {error:`Start must be a ${year} date.`};
 const to=d.to?String(d.to).trim():'';if(to&&(!isDay(to)||!to.startsWith(year+'-')))return {error:`End must be a ${year} date, or blank for the year end.`};if(to&&to<d.from)return {error:'End is before the start.'};
 const ramp=d.ramp===''||d.ramp==null?0:Number(d.ramp);if(!Number.isInteger(ramp)||ramp<0)return {error:'Ramp is a whole number of days.'};
 const settings={};for(const [g,keys] of Object.entries(d.settings||{}))for(const [k,raw] of Object.entries(keys||{})){const v=parseSettingValue(raw);if(v===undefined)return {error:`${g}.${k} needs a value.`};(settings[g]||={})[k]=v;}
 if(!Object.keys(settings).length)return {error:'An episode changes at least one setting.'};
 const pr=draftPattern(d.strike||strikeDraft(d.pattern),{from:d.from,to:to||yearEnd(year)});if(pr.error)return {error:pr.error};
 return {episode:{title:String(d.title||'').trim()||d.scenario||'Episode',scenario:d.scenario||null,from:d.from,to:to&&to<yearEnd(year)?to:null,ramp,settings,...(pr.pattern?{pattern:pr.pattern}:{})}};}
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
 {id:'contactEffects',title:'What the contact centre changed',unit:'in the month',kind:'stack',fmt:'int',series:[{label:'Bill disputes',pick:m=>m.contact?.feedback?.disputes},{label:'Complaints',pick:m=>m.contact?.feedback?.complaints},{label:'Pay later after bad service',pick:m=>m.contact?.feedback?.payLater},{label:'Cancelled autopay',pick:m=>m.contact?.feedback?.autopayCancelled}],detail:m=>{const f=m.contact?.feedback;return f?[['Rebilled on a check read',f.rebilled],['Explained',f.explained],['Credited back',f.credited==null?null:'$'+Math.round(f.credited).toLocaleString()],['Disputes open',f.disputesOpen],['Complaints open',f.complaintsOpen]]:[];}},
 {id:'fieldDone',title:'Field work completed',unit:'work orders completed in the month, by programme',kind:'stack',fmt:'int',series:Object.entries(FIELD_PROGRAMS).map(([p,label])=>({label,pick:m=>m.field?.byProgram?.[p]})),detail:m=>m.field?[['Created',m.field.created],['Remote (AMI)',m.field.remote],['Crew hours',hoursOrDash(m.field.hours)],['Overtime hours',hoursOrDash(m.field.overtimeHours)]]:[]},
 {id:'fieldBacklog',title:'Field backlog',unit:'released orders open at month end, by programme',kind:'stack',fmt:'int',series:Object.entries(FIELD_PROGRAMS).map(([p,label])=>({label,pick:m=>m.field?.backlog?.[p]})),detail:m=>m.field?[['Overdue',m.field.overdue],['Crew utilisation',m.field.utilisationPct==null?'—':Math.round(m.field.utilisationPct*100)+'%']]:[]},
 {id:'fieldOnTime',title:'Field work on time',unit:'share of orders completed by their due date',kind:'line',fmt:'pct',series:[{label:'On time',pick:m=>m.field?.onTimePct}],detail:m=>m.field?[['Emergency response (min)',m.field.responseMin??'—'],['Response, slowest 10% (min)',m.field.responseP90Min??'—'],['Days to complete',m.field.daysToComplete??'—']]:[]},
 {id:'fieldEffects',title:'What field work changed',unit:'reads in the month the field work stopped',kind:'stack',fmt:'int',series:[{label:'Not read: service off',pick:m=>m.field?.effects?.readsOff},{label:'Missed: dead battery',pick:m=>m.field?.effects?.deadBatteryMisses}],detail:m=>{const e=m.field?.effects;return e?[['Disconnected',e.disconnected],['Reconnected',e.reconnected],['Meters exchanged',e.exchanged],['Meters drifting',e.driftingMeters],['Overdue work that failed',e.failures]]:[];}},
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
export function fmtValue(v,kind){if(v==null)return '—';if(!Number.isFinite(Number(v)))return typeof v==='string'?v:'—';if(kind==='pct')return (Number(v)*100).toFixed(1)+'%';return fmtCell(v,{kind});}
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
// The year a chart's months are in (the trend's own month starts; 2026 when it has none).
export const modelYear=model=>dayYear((model?.months||[]).find(m=>m?.start)?.start)||FIRST_YEAR;
export function describeChart(model){const n=model.tops.filter(v=>v!=null).length,li=model.latest;if(li<0)return `${model.title}, ${model.unit}. No figures yet.`;
 return `${model.title}, ${model.unit}. ${n} month${n===1?'':'s'}, ${MONTHS[model.tops.findIndex(v=>v!=null)]} to ${MONTHS[li]} ${modelYear(model)}${model.partial[li]?`, ${MONTHS[li]} to the run date only`:''}. Latest, ${readout(model,li)}.`;}
export const GEOM={w:320,h:150,left:44,right:10,top:10,bottom:22};
// Inline SVG for one chart: hairline grid and ticks, episode bands, the run date, the marks, and one hit target per month.
// A sporadic episode's band is fainter, with a thin tick at the top for each day it strikes (`strikes`: episodeStrikes).
export function chartSvg(model,{asOf=null,episodes=[],strikes=null,id='yr',year=modelYear(model)}={}){const g=GEOM,pw=g.w-g.left-g.right,ph=g.h-g.top-g.bottom,slot=pw/12,cal=calendarModel(year),end=yearEnd(year),f=n=>Number(n.toFixed(2));
 const x=i=>f(g.left+(i+.5)*slot),y=v=>f(g.top+ph-(v/model.max)*ph),dayX=day=>{if(!day||day>end)return g.left+pw;const mi=Number(day.slice(5,7))-1,d=Number(day.slice(8,10));return f(g.left+(mi+(d-1)/cal[mi].days)*slot);};
 const grid=model.ticks.map(t=>`<line class="yr-grid" x1="${g.left}" x2="${g.w-g.right}" y1="${y(t)}" y2="${y(t)}"/><text class="yr-tick" x="${g.left-6}" y="${f(y(t)+3)}" text-anchor="end">${e(fmtTick(t,model.fmt))}</text>`).join('');
 const xl=MONTHS.map((m,i)=>`<text class="yr-tick" x="${x(i)}" y="${g.h-7}" text-anchor="middle">${m[0]}</text>`).join('');
 const dayMid=day=>{const mi=Number(day.slice(5,7))-1,d=Number(day.slice(8,10));return f(g.left+(mi+(d-.5)/cal[mi].days)*slot);};let lane=0;
 const bands=episodes.map((ep,k)=>{const a=dayX(ep.from),b=ep.to&&ep.to<end?dayX(addDays(ep.to,1)):g.left+pw;if(b<=a)return '';const c=episodeColor(k),hits=ep.pattern?strikes?.get?.(ep.id)||null:null,what=`${e(ep.title)} · ${e(rangeLabel(ep))}${ep.pattern?' · '+e(patternLabel(ep.pattern,hits?hits.length:null)):''}`;
  const band=`<rect class="yr-band${ep.pattern?' is-sporadic':''}" x="${a}" y="${g.top}" width="${f(b-a)}" height="${ph}" fill="${c}"><title>${what}</title></rect>`;if(!ep.pattern)return band;
  const y0=g.top+Math.min(lane++,3)*7,d=(hits||[]).filter(([day])=>day.startsWith(year+'-')).map(([day])=>`M${dayMid(day)} ${y0}V${y0+6}`).join('');
  return band+(d?`<path class="yr-strike" d="${d}" stroke="${c}"><title>${what}</title></path>`:'');}).join('');
 const run=asOf&&asOf.startsWith(year+'-')?`<line class="yr-run" x1="${dayX(asOf)}" x2="${dayX(asOf)}" y1="${g.top}" y2="${g.top+ph}"><title>Run date ${e(asOf)}</title></line>`:'';
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

// The last day the episodes run to (an open end: their year's last day).
export function episodeRunEnd(episodes,year=dayYear(episodes[0]?.from)||FIRST_YEAR){return episodes.reduce((end,ep)=>{const day=ep.to||yearEnd(year);return day>end?day:end;},`${year}-01-01`);}
// The figures a later year opened with (the summary's `opening`: what the year before closed with), as short phrases.
export function openingFigures(o){if(!o)return [];const p=(v,one,many)=>`${INT.format(Number(v)||0)} ${Number(v)===1?one:many}`;
 return [p(o.openCases,'open case','open cases'),`${money(Number(o.receivable)||0)} receivable`,p(o.unpaidInvoices,'unpaid invoice','unpaid invoices'),p(o.unbilledDocuments,'unbilled document','unbilled documents'),
  p(o.openOrders,'open field order','open field orders'),p(o.servicesOff,'service off','services off'),p(o.deadBatteries,'dead battery','dead batteries'),p(o.faultyMeters,'faulty meter','faulty meters')];}

export async function inflictReviewedEpisodes(m,proposal,analyse){
 if(m.readOnly)throw Error('Open a live simulation to inflict tweaks.');
 if(!proposal.episodes?.length||m.episodes.length+proposal.episodes.length>MAX_EPISODES)throw Error('Choose new periods within the 40-episode limit.');
 const before=structuredClone(m.episodes),date=m.asOf;
 try{for(const ep of proposal.episodes)m.addEpisode(ep);m.setAsOf(proposal.runTo);const error=await analyse();if(error)throw error;}
 catch(error){m.episodes=before;m.asOf=date;m.save();throw error;}
}

// The year bar: the years opened (a switcher), Continue into the next year (on the last year opened, to 2030, with a
// confirm step: `confirm`), a closed year's note, and for a later year what it opened with (`opening`: {year, figures},
// the summary's `opening`). An archived run shows only its opening.
export function yearsBar(m,{confirm=false,opening=null,loaded=false}={}){if(!m)return '';const yr=activeYear(m),list=Array.isArray(m.years)&&m.years.length?m.years:[yr],last=list.at(-1),next=yr+1;
 const sw=m.readOnly?'':`<div class="year-switch" role="group" aria-label="Simulation year">${list.map(y=>`<button type="button" data-year="${y}" aria-pressed="${y===yr}"${y===yr?' aria-current="true"':''}>${y}</button>`).join('')}</div>`;
 const cont=m.readOnly?'':m.canContinue?.()?(confirm?`<span class="year-continue-confirm" role="group" aria-label="Continue into ${next}"><span>Open ${next} on ${yr}'s close? ${yr} then closes: its actions and episodes stay as they are.</span><button type="button" class="primary-btn" data-act="continue-yes">Continue into ${next}</button><button type="button" class="small-link" data-act="continue-no">Not yet</button></span>`
  :`<button type="button" class="outline-btn year-continue" data-act="continue">Continue into ${next}</button><span class="year-years-note">${next} opens where ${yr} closes: balances, open cases, bills, field orders, services off and devices carry.</span>`)
  :m.isClosed?.()?`<span class="year-years-note is-closed">${e(m.closedMessage?.()||`${yr} is closed.`)}</span>`:yr>=LAST_YEAR&&yr===last?`<span class="year-years-note">The simulation runs to ${LAST_YEAR}.</span>`:'';
 const o=yr>FIRST_YEAR?opening?.year===yr?opening.figures?`<p class="year-opening"><strong>Opened with</strong> ${openingFigures(opening.figures).map(x=>`<span>${e(x)}</span>`).join('')}</p>`:''
  :`<p class="year-opening is-loading">Opened on ${yr-1}'s close${loaded?' · loading its figures…':''}</p>`:'';
 return (sw||cont?`<section class="year-years" aria-label="Years">${sw}${cont}</section>`:'')+o;}

// `onYear(year)` hears a year switched to or opened (the Studio's other pages and the map follow the active year).
export function installYearPage({getClient,getSimulation=()=>null,getEngineState=()=>({state:'idle',towns:[]}),toast=()=>{},onDate=null,onYear=null,root=document.getElementById('year-root'),plan=false}){
 const ui={library:null,trend:null,busy:false,recalc:false,opened:false,error:'',panel:null,confirmClear:false,confirmContinue:false,opening:null,models:[],agent:null,applying:false,kpi:{catalogue:null,values:null,key:'',error:''}};
 // The simulation's chosen figures (its record's `kpis`), measured year to date by the engine for the run in view.
 function kpiIds(){const s=getSimulation();return Array.isArray(s?.kpis)?s.kpis:[];}
 async function loadKpis(){const m=client(),ids=kpiIds();if(!m||!ids.length||plan)return;const key=JSON.stringify([ids,m.asOf,m.settings,m.seed,m.episodes,m.actions?.length]);if(ui.kpi.key===key)return;ui.kpi.key=key;ui.kpi.values=null;ui.kpi.error='';
  try{ui.kpi.catalogue||=await fetchKpiCatalogue(m.api,{fetchImpl:m.fetchImpl});const data=await fetchKpiValues(m.api,m.body({asOf:m.asOf,kpis:ids}),{fetchImpl:m.fetchImpl});if(ui.kpi.key!==key)return;ui.kpi.values=data.values;ui.kpi.thresholds=data.thresholds;}catch(err){if(ui.kpi.key===key)ui.kpi.error=err.message;}
  const strip=root?.querySelector('.kpi-strip');if(strip)strip.outerHTML=kpis();}
 function kpis(){const s=getSimulation(),ids=kpiIds();if(!ids.length||plan||!client())return '';const href='./glossary.html?simulation='+encodeURIComponent(s.id)+'&town='+encodeURIComponent(s.townRef||'');
  if(ui.kpi.error)return `<section class="kpi-strip" aria-label="Your KPIs"><div class="kpi-strip-head"><h3>Your KPIs</h3><a href="${e(href)}">Glossary ↗</a></div><p class="small-note">${e(ui.kpi.error)}</p></section>`;
  return kpiStrip(ui.kpi.catalogue,ids,ui.kpi.values,{thresholds:ui.kpi.thresholds||{},href});}
 let closePops=null,closeAgent=null,agentClient=null,strikes=new Map();
 const header=root?.ownerDocument?.querySelector('.studio-header');
 const positionGuide=()=>{if(header)root.style.setProperty('--year-guide-top',header.getBoundingClientRect().bottom+'px');};
 if(header&&globalThis.ResizeObserver)new ResizeObserver(positionGuide).observe(header);
 positionGuide();
 const client=()=>getClient?.()||null;
 const yearOf=()=>activeYear(client());
 // The active year takes no new episodes when it is closed (a later year opened on it) or archived.
 const frozen=m=>!!m&&(m.readOnly||!!m.isClosed?.());
 const scenarioOf=id=>ui.library?.scenarios?.find(s=>s.id===id)||null;
 // ---- loading --------------------------------------------------------------------------------------------------
 async function loadLibrary(){const m=client();if(!m||m.readOnly||ui.library)return;try{ui.library=await m.scenarios();}catch(err){ui.error=err.message;}}
 // The trend for the current run; `recalc` says the run changed (the engine replays the year). Returns the error, if any.
 // A reply for a year no longer active (switched away while it ran) is dropped.
 async function load({recalc=false,opened=false}={}){const m=client();if(!m)return null;const yr=activeYear(m);ui.busy=true;ui.recalc=recalc;ui.opened=opened;ui.error='';render();
  try{const t=await (plan?m.preview():m.trend());if(client()!==m||activeYear(m)!==yr)return null;ui.trend=t;ui.trendYear=yr;ui.busy=false;ui.recalc=false;ui.opened=false;render();loadOpening(m,yr);return null;}
  catch(err){if(err.superseded||client()!==m||activeYear(m)!==yr)return null;ui.busy=false;ui.recalc=false;ui.opened=false;ui.error=err.message;render();return err;}}
 // What a later year opened with: the summary's `opening` (the run is warm once the trend is in).
 async function loadOpening(m,yr){if(yr<=FIRST_YEAR||typeof m.summary!=='function'){ui.opening=null;return;}if(ui.opening?.year===yr&&ui.opening.figures)return;
  let figures=null;try{figures=(await m.summary())?.opening||null;}catch(err){if(err.superseded)return;}if(client()===m&&activeYear(m)===yr){ui.opening={year:yr,figures};render();}}
 // ---- years ----------------------------------------------------------------------------------------------------
 function yearChanged(m,note){ui.panel=null;ui.confirmClear=false;ui.confirmContinue=false;ui.trend=null;ui.opening=null;ui.error='';ui.models=[];
  try{onYear?.(m.year);}catch(err){toast(err.message);}if(note)toast(note);}
 function switchYear(y){const m=client();if(!m||m.readOnly||typeof m.setYear!=='function')return;try{if(!m.setYear(y))return;}catch(err){toast(err.message);return;}yearChanged(m);load();}
 function continueYear(){const m=client();if(!m?.canContinue?.())return;const from=m.year;let y;try{y=m.continueYear();}catch(err){toast(err.message);return;}
  yearChanged(m,`${y} opened on ${from}'s close.`);load({recalc:true,opened:true});}
 async function open(hash){if(!plan&&!parseYearRoute(hash))return;await loadLibrary();render();load();}
 function engineRefusal(err){const d=err.detail;return 'The engine refused it: '+(typeof d==='string'?d:Array.isArray(d)?d.map(x=>x?.msg||x?.message||JSON.stringify(x)).join('; '):d?.message||err.message);}
 // ---- episodes -------------------------------------------------------------------------------------------------
 async function inflict(){const m=client(),p=ui.panel;if(!m||p?.kind!=='inflict'||!p.draft)return;const parsed=[];
  for(const d of p.draft){const r=draftEpisode(d,yearOf());if(r.error){p.error=r.error;render();return;}parsed.push(r.episode);}
  if(m.episodes.length+parsed.length>MAX_EPISODES){p.error=`At most ${MAX_EPISODES} episodes in a year.`;render();return;}
  const added=parsed.map(ep=>m.addEpisode(ep)),title=parsed.length>1?scenarioOf(p.scenario)?.title||added[0].title:added[0].title;
  const previous=m.asOf,end=episodeRunEnd(parsed,yearOf());m.setAsOf(plan&&previous>end?previous:end); // a plan's results date only moves on
  ui.panel=null;toast(plan?`${title} added to the year.`:`Analysing ${title} through ${longDay(end)}…`);const err=await load({recalc:true});
  if(err?.status===422){for(const a of added)m.removeEpisode(a.id);m.setAsOf(previous);ui.panel={...p,error:engineRefusal(err)};toast('The engine refused the episode.');await load();}
  else if(!err&&onDate){try{await onDate(end);}catch(e){toast('Year updated; the operations day could not refresh: '+e.message);}}}
 async function saveEdit(){const m=client(),p=ui.panel;if(!m||p?.kind!=='edit')return;const r=draftEpisode(p.draft,yearOf());if(r.error){p.error=r.error;render();return;}
  const was=m.episodes.find(x=>x.id===p.id);if(!was)return;const before=JSON.parse(JSON.stringify(was));m.updateEpisode(p.id,{pattern:null,...r.episode});
  ui.panel=null;toast(plan?`${r.episode.title} saved.`:`Recalculating the year with ${r.episode.title}…`);const err=await load({recalc:true});
  if(err?.status===422){m.updateEpisode(p.id,{pattern:null,...before});ui.panel={...p,error:engineRefusal(err)};await load();}}
 async function remove(id){const m=client();if(!m)return;const ep=m.episodes.find(x=>x.id===id);if(!m.removeEpisode(id))return;ui.panel=null;toast(plan?`${ep.title} removed.`:`Recalculating the year without ${ep.title}…`);await load({recalc:true});}
 async function clearAll(){const m=client();if(!m)return;const n=m.episodes.length;m.clearEpisodes();ui.confirmClear=false;ui.panel=null;toast(plan?`${n} episode${n===1?'':'s'} cleared.`:`Recalculating the year without ${n} episode${n===1?'':'s'}…`);await load({recalc:true});}
 function viewDay(day){const m=client();if(!day)return;Promise.resolve(onDate?onDate(day):null).then(()=>{if(m&&m.asOf!==day)m.setAsOf(day);load();});}
 function mountAgent(){const m=client(),p=ui.panel;if(p?.kind!=='agent'||!m||m.readOnly)return;
  agentClient=m;closeAgent=installSetupAgent({root:root.querySelector('#year-agent-root'),api:m.api,mode:'inflict',getDraft:()=>({...currentRunInput(m,p.day),name:getSimulation()?.name||'',region:getSimulation()?.region||'',purpose:getSimulation()?.purpose||'',agent:ui.agent}),onSave:s=>{ui.agent=s;},onBack:()=>{ui.panel=null;render();},onApply:async proposal=>{
   if(client()!==m)throw Error('The active simulation changed. Open the guide again.');
   ui.applying=true;toast(`Analysing ${proposal.name} through ${longDay(proposal.runTo)}…`);
   try{await inflictReviewedEpisodes(m,proposal,()=>load({recalc:true}));}
   catch(err){ui.error='';render();throw Error(err.status===422?engineRefusal(err):'Analysis could not finish. The added periods were rolled back. '+err.message);}
   finally{ui.applying=false;}
   ui.agent=null;ui.panel=null;render();
   if(onDate)try{await onDate(proposal.runTo);}catch(err){toast('Year updated; the operations day could not refresh: '+err.message);}
  }});}
 // ---- rendering ------------------------------------------------------------------------------------------------
 function head(){const m=client(),yr=yearOf(),asOf=ui.trend?.asOf||m?.asOf||'',n=frozen(m)?0:m?.episodes.length||0;
  const voice=m&&!frozen(m)&&yr===FIRST_YEAR?`<button type="button" class="outline-btn" data-act="voice-tweak">● Talk through a tweak</button>`:"",clear=n?ui.confirmClear?`<span class="year-confirm">Clear ${n} episode${n===1?'':'s'}? <button type="button" class="small-link" data-act="clear-yes">Yes, clear</button><button type="button" class="small-link" data-act="clear-no">Keep</button></span>`:`<button type="button" class="small-link" data-act="clear">Clear all episodes</button>`:'';
  if(plan)return `<header class="year-head"><div><span class="section-kicker">COMMAND CENTER · ${yr}</span><h2 class="has-pop">Command Center<button type="button" class="schema-info" aria-label="About the year" aria-expanded="false" title="About the year">i</button><div class="schema-pop" role="note"><p>The simulated year, day by day, as in the Command Center. Click a day to inflict a scenario from the engine's library starting that day; click an episode's bar or its name below to edit or remove it.</p><p>Run the utility to begin. After that, apply dated changes here and the engine recalculates your results.</p><p>An episode can strike only some days of its period: a few spikes, or scattered days. The engine draws them from this simulation's own seed, so every district strikes the same days; the calendar shows the period faint and the days struck solid.</p></div></h2></div><div class="year-tools">${voice}${clear}</div></header>`;
  return `<header class="year-head"><div><span class="section-kicker">RUN · ${yr}</span><h1 class="has-pop">Command Center<button type="button" class="schema-info" aria-label="About the Command Center" aria-expanded="false" title="About the Command Center">i</button><div class="schema-pop" role="note"><p>The simulated year, day by day. Click a day to inflict a scenario from the engine's library starting that day; the engine replays the whole year with that episode and the charts below show its mark, month by month.</p><p>Episodes are run input like your actions and settings: kept in this browser, sent with every request, applied by the engine. Settings in an episode are absolute (a number, true/false) or relative to the base (*0.5, +2, -1); a ramp slides a number there over that many days.</p><p>An episode can strike only some days of its period: a few spikes, or scattered days. The engine draws those days from the run's seed; the calendar shows the period faint and the days struck solid.</p></div></h1></div><div class="year-tools">${voice}<label>Run date <input type="date" id="year-asof" min="${yr}-01-01" max="${yr}-12-31" value="${e(asOf)}"></label>${clear}</div></header>`;}
 function years(){return plan?'':yearsBar(client(),{confirm:ui.confirmContinue,opening:ui.opening,loaded:!!ui.trend});}
 function status(){const m=client(),t=ui.trend,n=m?.episodes.length||0,eps=`${n} episode${n===1?'':'s'}`;
  if(ui.error)return `<p class="year-status" role="status"><span class="year-error">${e(ui.error)}</span></p>`;
  if(plan)return `<p class="year-status" role="status">${ui.busy?'Checking the episodes with the engine…':n?`${eps} · applies across your utility`:''}</p>`;
  if(!t)return `<p class="year-status" role="status">${ui.busy?(m?.readOnly?'Loading saved trends…':ui.opened?`Opening ${yearOf()} on ${yearOf()-1}'s close… (the engine replays each year, 10–30 s)`:ui.recalc?'Recalculating the year… (5–15 s)':'Asking the engine… (a cold engine replays the year first, 5–15 s)'):''}</p>`;
  return `<p class="year-status" role="status">${m?.readOnly?'Saved results':'Engine data'} as of ${e(t.asOf)} · ${eps}${ui.busy?(ui.recalc?' · Recalculating the year…':' · Updating…'):''}</p>`;}
 // A sporadic episode's bar is its window, faint and dashed, with the days it strikes solid (once the trend has them);
 // a struck day's cell says which episode strikes it and how hard.
 function month(mo,asOf,eps){const spans=episodeSpans(eps,mo),selected=ui.panel?.kind==='inflict'?ui.panel.day:null,cells=[],struck=new Map();
  for(const ep of eps)for(const [day,v] of strikes.get(ep.id)||[])if(day>=mo.start&&day<=mo.end)(struck.get(day)||struck.set(day,[]).get(day)).push([ep,v]);
  for(let i=0;i<mo.offset;i++)cells.push('<span class="year-pad"></span>');
  for(let d=1;d<=mo.days;d++){const day=mo.start.slice(0,8)+String(d).padStart(2,'0'),wd=(mo.offset+d-1)%7,hit=struck.get(day),cls=['year-day',asOf&&day<=asOf?'is-past':'',day===asOf?'is-today':'',wd>=5?'is-weekend':'',day===selected?'is-selected':'',hit?'has-strike':''].filter(Boolean).join(' ');
   cells.push(`<button type="button" class="${cls}" data-day="${day}" aria-label="${e(longDay(day))}${day===asOf?', the run date':''}${hit?e(hit.map(([ep,v])=>`, ${ep.title} strikes at ${pct(v)}`).join('')):''}"${hit?` title="${e(hit.map(([ep,v])=>strikeTitle(ep,day,v)).join('\n'))}"`:''}${day===selected?' aria-pressed="true"':''}>${d}</button>`);}
  const bars=spans.map(s=>{const ep=eps[s.index],c=episodeColor(s.index),n=s.to-s.from+1,hits=ep.pattern?strikes.get(ep.id)||null:null;
   const marks=hits?hits.filter(([d])=>d>=mo.start&&d<=mo.end).map(([d,v])=>{const i=Number(d.slice(8,10))-s.from;return i<0||i>=n?'':`<i style="left:${(i/n*100).toFixed(2)}%;width:${(100/n).toFixed(2)}%" title="${e(strikeTitle(ep,d,v))}"></i>`;}).join(''):'';
   const what=ep.pattern?patternLabel(ep.pattern,hits?hits.length:null):'',said=ep.pattern?`, sporadic: ${hits?`strikes ${hits.length} day${hits.length===1?'':'s'}`:'strikes some days'}`:'';
   return `<button type="button" class="year-bar${s.startsHere?' starts':''}${s.endsHere?' ends':''}${ep.pattern?' is-sporadic':''}" data-ep="${e(ep.id)}" style="left:${((s.from-1)/mo.days*100).toFixed(2)}%;width:${(n/mo.days*100).toFixed(2)}%;top:${s.lane*6}px;${ep.pattern?`--c:${c};background-color:${c}59`:`background:${c}`}" title="${e(ep.title)} · ${e(rangeLabel(ep))}${what?' · '+e(what):''}" aria-label="Edit ${e(ep.title)}, ${e(rangeLabel(ep))}${e(said)}">${marks}</button>`;}).join('');
  return `<div class="year-month"><h2>${mo.label}</h2><div class="year-grid">${WEEKDAYS.map(w=>`<span class="year-wd" aria-hidden="true">${w}</span>`).join('')}${cells.join('')}</div><div class="year-strip" style="height:${Math.max(1,spans.length)*6+2}px">${bars}</div></div>`;}
 function legend(eps){if(!eps.length)return '<p class="year-legend-empty">No episodes yet. Click a day to inflict a scenario from that date.</p>';
  return `<ul class="year-legend" aria-label="Episodes">${eps.map((ep,i)=>{const hits=ep.pattern?strikes.get(ep.id):null;return `<li><button type="button" class="year-leg" data-ep="${e(ep.id)}" aria-label="Edit ${e(ep.title)}"><i${ep.pattern?` class="is-sporadic" style="--c:${episodeColor(i)}"`:` style="background:${episodeColor(i)}"`}></i><strong>${e(ep.title)}</strong><span>${e(rangeLabel(ep))}${ep.ramp?` · ramp ${ep.ramp} d`:''}${ep.pattern?' · '+e(patternLabel(ep.pattern,hits?hits.length:null)):''}</span></button></li>`;}).join('')}</ul>`;}
 function calendar(){const m=client(),yr=yearOf(),asOf=plan?'':ui.trend?.asOf||m?.asOf||'',eps=m?.episodes||[];
  return `<section class="year-calendar" aria-label="Calendar ${yr}"><div class="year-months">${calendarModel(yr).map(mo=>month(mo,asOf,eps)).join('')}</div>${legend(eps)}</section>`;}
 function card(model,k){const m=client(),asOf=ui.trend?.asOf||m?.asOf||null,eps=m?.episodes||[],li=model.latest,one=model.series.length===1;
  const when=li<0?'':model.partial[li]?`${MONTHS[li]} to ${shortDay(model.months[li].end)}`:MONTHS[li],latest=li<0?'<strong>—</strong><span>no figures yet</span>':one?`<strong>${e(fmtValue(model.series[0].values[li],model.fmt))}</strong><span>${e(when)}</span>`:`<span>latest · ${e(when)}</span>`;
  const leg=one?'':`<ul class="yr-legend">${model.series.map(s=>`<li><i class="${model.kind==='line'?'is-line':''}" style="background:${s.color}"></i><span>${e(s.label)}</span>${li>=0&&s.values[li]!=null?`<strong>${e(fmtValue(s.values[li],model.fmt))}</strong>`:''}</li>`).join('')}</ul>`;
  return `<article class="yr-card" data-chart="${k}"><header><div><h3>${e(model.title)}</h3><p>${e(model.unit)}</p></div><div class="yr-latest">${latest}</div></header>${chartSvg(model,{asOf,episodes:eps,strikes,id:'yr-'+model.id,year:yearOf()})}<div class="yr-tip" hidden></div>${leg}<details class="yr-table"><summary>Table</summary>${chartTable(model)}</details></article>`;}
 function trends(){const t=ui.trend;if(plan)return '';if(!t)return `<section class="year-trends" aria-label="Trends"><div class="yr-empty">${ui.busy?'':'No trend yet.'}</div></section>`;
  ui.models=CHARTS.map(c=>chartModel(c,t.months));return `<section class="year-trends${ui.busy?' is-stale':''}" aria-label="Trends">${ui.models.map(card).join('')}</section>`;}
 function library(p){const lib=ui.library;if(!lib)return `<p class="small-note">${ui.error?e(ui.error):'Loading the scenario library…'}</p>`;
  return (lib.groups||[]).map(g=>{const own=(lib.scenarios||[]).filter(s=>s.group===g.id),soon=(lib.coming||[]).filter(s=>s.group===g.id);if(!own.length&&!soon.length)return '';
   return `<h3>${e(g.title)}</h3>${own.map(s=>`<div class="year-sc"><button type="button" class="year-sc-pick" data-sc="${e(s.id)}"><strong>${e(s.title)}</strong><span>${e(s.description||'')}</span>${scenarioPatternLine(s)?`<span class="year-sc-pattern">${e(scenarioPatternLine(s))}</span>`:''}</button>${s.watch?`<details><summary>What to watch</summary><p>${e(s.watch)}</p></details>`:''}${s.tags?.length?`<span class="year-tags">${s.tags.map(t=>`<em>${e(t)}</em>`).join('')}</span>`:''}</div>`).join('')}${soon.map(s=>`<div class="year-sc is-coming" aria-disabled="true"><strong>${e(s.title)}<em class="year-soon">coming soon</em></strong><span>${e(s.description||'')}</span></div>`).join('')}`;}).join('')||'<p class="small-note">The library is empty.</p>';}
 function draftForm(drafts,{single=false}={}){const yr=yearOf();return drafts.map((d,k)=>`<fieldset class="year-ep"><legend>${single?'Episode':`Episode ${k+1}`}</legend><label class="year-f">Title <input type="text" data-k="${k}" data-f="title" value="${e(d.title||'')}" maxlength="80"></label><div class="year-f-row"><label class="year-f">Start <input type="date" data-k="${k}" data-f="from" min="${yr}-01-01" max="${yr}-12-31" value="${e(d.from||'')}"></label><label class="year-f">End <input type="date" data-k="${k}" data-f="to" min="${yr}-01-01" max="${yr}-12-31" value="${e(d.to||'')}" placeholder="year end"></label><label class="year-f">Ramp <input type="number" data-k="${k}" data-f="ramp" min="0" max="365" step="1" value="${e(d.ramp??0)}"> days</label></div>${strikeFields(d.strike||=strikeDraft(d.pattern),k)}<table class="year-settings"><thead><tr><th>Setting</th><th>Value</th></tr></thead><tbody>${settingRows(d.settings).map(([g,key,v])=>`<tr><td><span>${e(prettyKey(g))}</span><code>${e(g)}.${e(key)}</code></td><td><input type="text" data-k="${k}" data-g="${e(g)}" data-key="${e(key)}" value="${e(v)}" aria-label="${e(g)}.${e(key)}"></td></tr>`).join('')||'<tr><td colspan="2">No settings.</td></tr>'}</tbody></table></fieldset>`).join('')+'<p class="small-note">A number or true/false sets the value for the episode; *0.5, +2 or -1 change the base value. Blank end: to the year end.</p>';}
 function panel(){const p=ui.panel;if(!p)return '';const m=client();
  if(p.kind==='agent')return '<aside class="year-panel year-agent-panel" aria-label="Talk through a tweak"><div id="year-agent-root"></div></aside>';
  if(p.kind==='inflict'){const sc=p.scenario?scenarioOf(p.scenario):null;
   return `<aside class="year-panel" aria-label="Inflict a scenario"><header><div><span class="section-kicker">INFLICT ON</span><h2>${e(longDay(p.day))}</h2></div><button type="button" class="close-btn" data-act="close" aria-label="Close">×</button></header>${plan?'':`<div class="year-panel-actions"><button type="button" class="outline-btn" data-act="view-day">View this day</button>${m?.asOf===p.day?'<span class="small-note">This is the run date.</span>':''}</div>`}${p.error?`<p class="year-error" role="alert">${e(p.error)}</p>`:''}${sc?`<button type="button" class="small-link" data-act="back">← Library</button><h3 class="year-sc-title">${e(sc.title)}</h3><p class="small-note">${e(sc.description||'')}</p>${sc.watch?`<p class="year-watch"><strong>Watch</strong> ${e(sc.watch)}</p>`:''}${draftForm(p.draft)}<div class="year-panel-foot"><button type="button" class="primary-btn" data-act="inflict">${plan?'Add to the year':'Inflict &amp; run to period end'}</button></div>`:`<p class="small-note">${plan?'Pick a scenario; its episodes start on this day. They go into the next revision you run.':'Pick a scenario; its episodes start on this day. Inflicting runs the analysis to the last episode’s end (year end for an open-ended period).'}</p>${yearOf()===FIRST_YEAR?'<button type="button" class="outline-btn" data-act="voice-tweak">● Describe a tweak by voice or text</button>':''}<div class="year-library">${library(p)}</div>`}</aside>`;}
  const ep=m?.episodes.find(x=>x.id===p.id);if(!ep){return '';}
  return `<aside class="year-panel" aria-label="Edit an episode"><header><div><span class="section-kicker">EPISODE ${e(ep.id)}</span><h2>${e(ep.title)}</h2></div><button type="button" class="close-btn" data-act="close" aria-label="Close">×</button></header>${ep.scenario?`<p class="small-note">From the scenario ${e(scenarioOf(ep.scenario)?.title||ep.scenario)}.</p>`:''}${p.error?`<p class="year-error" role="alert">${e(p.error)}</p>`:''}${draftForm([p.draft],{single:true})}<div class="year-panel-foot"><button type="button" class="primary-btn" data-act="save">Save</button><button type="button" class="small-link" data-act="remove">Remove</button></div></aside>`;}
 function render(){if(!root)return;const m=client();
  const keepAgent=ui.panel?.kind==='agent'&&m===agentClient?root.querySelector('#year-agent-root'):null;
  if(!keepAgent){closeAgent?.();closeAgent=null;agentClient=null;}
  if(!m){root.innerHTML=`<section class="fiori-shell"><div class="fiori-empty ws-empty">${engineNotice(getEngineState(),undefined,'#/year','The Year')}</div></section>`;root.querySelector('[data-ws="retry"]')?.addEventListener('click',()=>location.reload());return;}
  strikes=episodeStrikes(ui.trend,m.episodes||[]);
  root.innerHTML=`<div class="year-layout${ui.panel?' has-panel':''}"><main class="year-main">${head()}${years()}${status()}${kpis()}${calendar()}${trends()}</main>${panel()}</div>`;loadKpis();
  if(keepAgent)root.querySelector('#year-agent-root')?.replaceWith(keepAgent);else if(ui.panel?.kind==='agent')mountAgent();
  if(m.readOnly){root.querySelector('#year-asof').disabled=true;for(const b of root.querySelectorAll('[data-day],[data-ep]')){b.disabled=true;b.removeAttribute('data-day');b.removeAttribute('data-ep');}const pop=root.querySelector('.schema-pop');if(pop)pop.innerHTML='<p>Saved engine results through '+e(m.asOf)+'. Episodes and trends are archived with this run. Open a live engine to change inputs or replay another date.</p>';const empty=root.querySelector('.year-legend-empty');if(empty)empty.textContent='No episodes in this saved run.';}
  else if(frozen(m)){for(const b of root.querySelectorAll('[data-day],[data-ep]')){b.disabled=true;b.removeAttribute('data-day');b.removeAttribute('data-ep');}const empty=root.querySelector('.year-legend-empty');if(empty)empty.textContent=`No episodes in ${m.year}.`;}
  closePops?.();closePops=bindPopovers(root);if(ui.panel)root.querySelector('.year-panel h2')?.scrollIntoView?.({block:'nearest'});}
 // ---- hover readout ----------------------------------------------------------------------------------------------
 function showTip(hit){const card=hit.closest('.yr-card'),model=ui.models[Number(card?.dataset.chart)],i=Number(hit.dataset.i);if(!card||!model)return;const tip=card.querySelector('.yr-tip'),m=model.months[i];
  const rows=[];const h=document.createElement('strong');h.textContent=`${MONTHS[i]} ${yearOf()}`;rows.push(h);
  for(const s of model.series){if(s.values[i]==null)continue;const r=document.createElement('div'),key=document.createElement('i'),v=document.createElement('b'),l=document.createElement('span');key.style.background=s.color;v.textContent=fmtValue(s.values[i],model.fmt);l.textContent=s.label;r.append(key,v,l);rows.push(r);}
  for(const [k,v] of (m&&model.detail?model.detail(m):[])){const r=document.createElement('div');r.className='is-detail';const b=document.createElement('b'),l=document.createElement('span');b.textContent=fmtValue(v,'int');l.textContent=k;r.append(b,l);rows.push(r);}
  tip.replaceChildren(...rows);tip.hidden=false;tip.style.left=`${((Number(hit.getAttribute('x'))+Number(hit.getAttribute('width'))/2)/GEOM.w*100).toFixed(1)}%`;tip.classList.toggle('is-right',i>=8);tip.classList.toggle('is-left',i<3);}
 function hideTip(card){card?.querySelector('.yr-tip')?.setAttribute('hidden','');}
 // ---- events ---------------------------------------------------------------------------------------------------
 root?.addEventListener('click',ev=>{const b=ev.target.closest('button');if(!b||!root.contains(b)||ui.applying)return;const m=client();if(m?.readOnly)return;
  if(b.dataset.year){switchYear(Number(b.dataset.year));return;}
  if(b.dataset.act==='continue'){ui.confirmContinue=true;render();root.querySelector('[data-act="continue-yes"]')?.focus();return;}
  if(b.dataset.act==='continue-no'){ui.confirmContinue=false;render();root.querySelector('[data-act="continue"]')?.focus();return;}
  if(b.dataset.act==='continue-yes'){continueYear();return;}
  if(b.dataset.day){ui.panel={kind:'inflict',day:b.dataset.day,scenario:null,draft:null,error:''};ui.confirmClear=false;render();return;}
  if(b.dataset.ep){const ep=m?.episodes.find(x=>x.id===b.dataset.ep);if(!ep)return;ui.panel={kind:'edit',id:ep.id,draft:{...JSON.parse(JSON.stringify(ep)),to:ep.to||'',strike:strikeDraft(ep.pattern)},error:''};render();return;}
  if(b.dataset.sc){const p=ui.panel,sc=scenarioOf(b.dataset.sc);if(p?.kind!=='inflict'||!sc)return;p.scenario=sc.id;p.draft=episodeDates(sc,p.day).map(d=>({...d,to:d.to||'',strike:strikeDraft(d.pattern)}));p.error='';render();return;}
  switch(b.dataset.act){
   case 'voice-tweak':if(frozen(m)||yearOf()!==FIRST_YEAR)return;ui.agent=null;ui.panel={kind:'agent',day:ui.panel?.day||m?.asOf||`${yearOf()}-03-31`};ui.confirmClear=false;render();return;
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
  if(el.dataset.f)d[el.dataset.f]=el.value;else if(el.dataset.g!=null){((d.settings||={})[el.dataset.g]||={})[el.dataset.key]=el.value;}
  else if(el.dataset.p){const s=d.strike||=strikeDraft(d.pattern);s[el.dataset.p]=el.type==='checkbox'?el.checked:el.value;
   if(el.dataset.p==='kind'){render();root.querySelector(`[data-k="${el.dataset.k}"][data-p="kind"][value="${el.value}"]`)?.focus();}}});
 root?.addEventListener('change',ev=>{const el=ev.target;if(el.id==='year-asof'){const day=el.value;if(!day)return;viewDay(day);}});
 root?.addEventListener('pointermove',ev=>{const hit=ev.target.closest?.('.yr-hit');if(hit)showTip(hit);else hideTip(ev.target.closest?.('.yr-card'));});
 root?.addEventListener('pointerleave',()=>{for(const c of root.querySelectorAll('.yr-card'))hideTip(c);});
 root?.addEventListener('focusin',ev=>{const hit=ev.target.closest?.('.yr-hit');if(hit)showTip(hit);});
 root?.addEventListener('focusout',ev=>{if(ev.target.classList?.contains('yr-hit'))hideTip(ev.target.closest('.yr-card'));});
 root?.addEventListener('keydown',ev=>{if(ev.key==='Escape'&&ui.panel&&!ev.target.closest?.('input,select,textarea')){ui.panel=null;render();}});
 globalThis.addEventListener?.('hashchange',()=>{if(!plan&&!parseYearRoute(location.hash)&&closeAgent){ui.panel=null;render();}});
 return {open,render,load,refresh(){if(plan||parseYearRoute(location.hash)){if(client()&&(!ui.trend||ui.trendYear!==yearOf())){ui.trend=null;open(location.hash);}else render();}},get state(){return ui;}};
}
