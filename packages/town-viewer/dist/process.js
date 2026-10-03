// Activity sequences (#/process[/MONTH[/EVENT]]): the month's Activity Sequence graph from the engine (POST
// /api/process/graph) as an event explorer and a trace of one sequence, beside the mix of sequence types and what each
// costs (POST /api/process/costs). The engine decides events, causes, costs and days; this module indexes and renders.
import {escapeText as e} from './customer-view.js';
import {money,num} from './worklists.js';
export const DOMAINS={ami:'AMI',read:'Reads',vee:'VEE',wm:'Work management',field:'Field',cx:'Customer',billing:'Billing',invoice:'Invoicing',payment:'Payments',collections:'Collections'};
export const EDGES={caused_by:'caused by',triggered:'triggered',resulted_in:'resulted in',blocked_by:'blocked by',resolved_by:'resolved by',escalated_to:'escalated to',required_for:'required for',compensated_by:'compensated by'};
const MONTHS=['January','February','March','April','May','June','July','August','September','October','November','December'],FEED_CAP=150,STACK_CAP=30;
const ROUTE=/^#\/process(?:\/([1-9]|1[0-2])(?:\/([\w.:-]+))?)?$/;
export function parseRoute(hash){const m=String(hash||'').match(ROUTE);return m?{month:m[1]?Number(m[1]):null,eventId:m[2]||null}:null;}
export function routeHash({month=null,eventId=null}={}){return '#/process'+(month?'/'+month+(eventId?'/'+eventId:''):'');}
// Node time in days since 1 Jan 2026, town local time (the engine's day index plus the hour).
export const at=n=>n.day+(n.hour||0)/24;
export const dayDelta=(from,to)=>to.day-from.day;
export const costTotal=c=>(c?.labor||0)+(c?.system||0)+(c?.cx||0);
export const localDate=day=>new Date(Date.UTC(2026,0,1+day)).toISOString().slice(0,10);
export function clock(hour){const m=Math.floor((hour||0)*60+1e-6);return String(Math.floor(m/60)%24).padStart(2,'0')+':'+String(m%60).padStart(2,'0');}
const share=v=>v>0&&v<.1?(v*100).toFixed(1)+'%':Math.round(v*100)+'%';
const cents=v=>Math.round(v*100)/100;
// Lookups for one graph reply (cached per reply): nodes by id, edges into and out of each node, nodes per sequence.
const indexes=new WeakMap();
export function indexGraph(g){let x=indexes.get(g);if(x)return x;x={byId:new Map(),into:new Map(),out:new Map(),series:new Map()};
 for(const n of g.nodes||[]){x.byId.set(n.id,n);x.into.set(n.id,[]);x.out.set(n.id,[]);if(!x.series.has(n.seriesKey))x.series.set(n.seriesKey,[]);x.series.get(n.seriesKey).push(n);}
 for(const ed of g.edges||[])if(x.byId.has(ed.from)&&x.byId.has(ed.to)){x.out.get(ed.from).push(ed);x.into.get(ed.to).push(ed);}
 indexes.set(g,x);return x;}
function walk(g,id,up){const x=indexGraph(g),seen=new Set(),todo=[id];while(todo.length){for(const ed of (up?x.into:x.out).get(todo.pop())||[]){const next=up?ed.from:ed.to;if(next!==id&&!seen.has(next)){seen.add(next);todo.push(next);}}}return seen;}
// Events that led to this one (edges followed backwards) and events that followed from it.
export const upstream=(g,id)=>walk(g,id,true);
export const downstream=(g,id)=>walk(g,id,false);
// The whole Activity Sequence of an event as a pipeline: causes before effects, earliest first, so the Initiating Event
// leads. Each step carries its D+N day, the edge into it with its delay, and its place relative to the selected event.
export function buildTrace(g,id){const x=indexGraph(g),sel=x.byId.get(id);if(!sel)return null;
 const members=x.series.get(sel.seriesKey),order=new Map(members.map((n,i)=>[n.id,i])),placed=new Set(),steps=[];
 while(steps.length<members.length){let best=null;
  for(const n of members)if(!placed.has(n.id)&&x.into.get(n.id).every(ed=>placed.has(ed.from)||!order.has(ed.from))&&(!best||at(n)<at(best)||at(n)===at(best)&&order.get(n.id)<order.get(best.id)))best=n;
  best??=members.find(n=>!placed.has(n.id));placed.add(best.id);steps.push(best);}
 const first=steps[0],up=upstream(g,id),down=downstream(g,id),pos=new Map(steps.map((n,i)=>[n.id,i])),cost={labor:0,system:0,cx:0};
 for(const n of steps)for(const k in cost)cost[k]+=n.cost?.[k]||0;
 return {seriesKey:sel.seriesKey,variantId:sel.variantId,acctId:sel.acctId,selected:sel,upstream:up,downstream:down,
  cost:{labor:cents(cost.labor),system:cents(cost.system),cx:cents(cost.cx),total:cents(costTotal(cost))},elapsedDays:Math.round((Math.max(...steps.map(at))-at(first))*10)/10,
  steps:steps.map((n,i)=>{const edge=x.into.get(n.id)[0]||null,from=edge?x.byId.get(edge.from):steps[i-1]||null;
   return {node:n,index:i,dayN:dayDelta(first,n),initiating:!x.into.get(n.id).length,edge:edge?.type||null,from:from?.id||null,delay:from?dayDelta(from,n):null,adjacent:!from||pos.get(from.id)===i-1,
    role:n.id===id?'selected':up.has(n.id)?'upstream':down.has(n.id)?'downstream':null};})};}
// The event explorer: newest first, filtered by domain, event type, sequence type and account (or case) text, capped.
export function filterFeed(nodes,{domain='',type='',sequence='',search='',limit=FEED_CAP}={}){const q=String(search||'').trim().toLowerCase();
 const rows=(nodes||[]).map((n,i)=>[n,i]).filter(([n])=>(!domain||n.d===domain)&&(!type||n.type===type)&&(!sequence||n.variantId===sequence)&&(!q||String(n.acctId||'').toLowerCase().includes(q)||String(n.seriesKey||'').toLowerCase().includes(q)))
  .sort((a,b)=>at(b[0])-at(a[0])||b[1]-a[1]).map(([n])=>n);
 return {rows:rows.slice(0,limit),total:rows.length};}
export function feedOptions(nodes){const d=new Map(),t=new Map();for(const n of nodes||[]){d.set(n.d,(d.get(n.d)||0)+1);const o=t.get(n.type)||{type:n.type,label:n.l,icon:n.i,count:0};o.count++;t.set(n.type,o);}
 const rank=Object.keys(DOMAINS);return {domains:[...d].map(([id,count])=>({id,label:DOMAINS[id]||id,count})).sort((a,b)=>(rank.indexOf(a.id)+1||99)-(rank.indexOf(b.id)+1||99)),types:[...t.values()].sort((a,b)=>a.label.localeCompare(b.label))};}
// Sequence mix from the cost view (to date): share of sequences, cost per case (with carry), days to release and the
// human / RPA / field split (a sequence can touch more than one, so the split is of their sum). inMonth counts the
// sequences raised in the month shown.
export function sequenceMix(types,nodes=[]){const total=(types||[]).reduce((a,t)=>a+(t.count||0),0),month=new Map();
 for(const n of nodes||[]){if(!month.has(n.variantId))month.set(n.variantId,new Set());month.get(n.variantId).add(n.seriesKey);}
 return {total,rows:(types||[]).map(t=>{const h=t.human||0,r=t.rpa||0,f=t.field||0,sum=h+r+f;
  return {type:t.type,label:t.label,icon:t.icon,count:t.count||0,share:total?(t.count||0)/total:0,perCase:t.perCase,activityCost:t.activityCost,carry:t.carry,avgDaysToRelease:t.avgDaysToRelease,rpaRule:!!t.rpaRule,
   split:{human:sum?h/sum:0,rpa:sum?r/sum:0,field:sum?f/sum:0},inMonth:month.get(t.type)?.size||0};}).sort((a,b)=>b.count-a.count||String(a.label).localeCompare(String(b.label)))};}
export function installProcess({getClient,toast=()=>{}}){
 const $=id=>document.getElementById(id);let route={month:null,eventId:null},month=null,graph=null,costs=null,loaded=null,busy=0,stack=[],reveal=false;const filters={domain:'',type:'',sequence:'',search:''};
 const client=()=>getClient(),monthName=m=>MONTHS[m-1]+' 2026',dataKey=m=>JSON.stringify(m.body());
 $('wl-settings')?.insertAdjacentHTML('beforebegin','<a id="wl-process" class="small-link" href="#/process">Activity sequences</a>');
 function setStatus(text){$('pr-status').textContent=text||'';}
 async function load(){const m2c=client();
  if(!m2c){busy++;graph=costs=loaded=null;$('pr-mix').innerHTML='';$('pr-feed-note').textContent='';$('pr-trace').innerHTML='';setStatus('');$('pr-feed').innerHTML=`<div class="wl-empty"><h2>Activity sequences need the engine</h2><p>Open an engine town (for example <code>?town=small_town</code> on the hosted site), or run <code>uv run utilsim serve</code> locally and add <code>?engine=http://127.0.0.1:8010</code>. The engine replays a year of reads, VEE and work queues for the town.</p></div>`;return;}
  const ticket=++busy;setStatus('Running the engine…');
  try{const pending=m2c.costs(),asOf=m2c.asOf||(await pending).asOf,m=route.month||Number(asOf.slice(5,7));$('pr-month').value=String(m);const [c,g]=await Promise.all([pending,m2c.graph(m)]);if(ticket!==busy)return;month=m;costs=c;graph=g;loaded={client:m2c,key:dataKey(m2c)};}
  catch(err){if(ticket===busy&&!err.superseded){setStatus(err.message);toast(err.message);}return;}
  const sequences=indexGraph(graph).series.size;
  setStatus(sequences?`${num(sequences)} Activity Sequence${sequences>1?'s':''} raised in ${monthName(month)} · ${num(graph.nodes.length)} events · as of ${costs.asOf}.`:`No Activity Sequences raised in ${monthName(month)} by ${costs.asOf}.${Number(costs.asOf.slice(5,7))<month?' Move the view date in Worklists to see later months.':''}`);
  renderMix();renderFilters();renderFeed();renderTrace();}
 function renderMix(){const mix=sequenceMix(costs.types,graph.nodes),short=MONTHS[month-1].slice(0,3);
  $('pr-mix').innerHTML=`<h2>Sequence mix</h2><p class="small-note">${num(mix.total)} sequences to ${e(costs.asOf)}. Cost per case includes carry.</p><p class="pr-legend"><span><i></i>Human</span><span><i class="r"></i>RPA</span><span><i class="f"></i>Field</span></p><div class="pr-mix-list">`
   +(mix.rows.length?mix.rows.map(r=>`<button data-pr-seq="${e(r.type)}" aria-pressed="${filters.sequence===r.type}" title="Show only ${e(r.label)} events"><span class="pr-mix-name">${e(r.icon)} ${e(r.label)}${r.rpaRule?'<span class="pr-rpa" title="An RPA rule covers this type">RPA</span>':''}</span><strong>${num(r.count)}</strong><span class="pr-mix-stats">${share(r.share)} · ${money(r.perCase)} per case · ${r.avgDaysToRelease==null?'—':r.avgDaysToRelease.toFixed(1)+' d'} to release</span><span class="pr-split" role="img" aria-label="Human ${share(r.split.human)}, RPA ${share(r.split.rpa)}, field ${share(r.split.field)}"><i style="width:${(r.split.human*100).toFixed(1)}%"></i><i class="r" style="width:${(r.split.rpa*100).toFixed(1)}%"></i><i class="f" style="width:${(r.split.field*100).toFixed(1)}%"></i></span><small>${num(r.inMonth)} raised in ${short}</small></button>`).join(''):'<p class="small-note">No exceptions raised yet.</p>')+'</div>';
  document.querySelectorAll('[data-pr-seq]').forEach(b=>b.onclick=()=>{filters.sequence=filters.sequence===b.dataset.prSeq?'':b.dataset.prSeq;document.querySelectorAll('[data-pr-seq]').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.prSeq===filters.sequence)));renderFeed();});}
 function renderFilters(){const o=feedOptions(graph.nodes);if(!o.domains.some(d=>d.id===filters.domain))filters.domain='';if(!o.types.some(t=>t.type===filters.type))filters.type='';
  $('pr-domain').innerHTML='<option value="">All domains</option>'+o.domains.map(d=>`<option value="${e(d.id)}">${e(d.label)} (${num(d.count)})</option>`).join('');$('pr-domain').value=filters.domain;
  $('pr-type').innerHTML='<option value="">All events</option>'+o.types.map(t=>`<option value="${e(t.type)}">${e(t.label)} (${num(t.count)})</option>`).join('');$('pr-type').value=filters.type;}
 function renderFeed(){const {rows,total}=filterFeed(graph.nodes,filters),seq=filters.sequence&&costs.types.find(t=>t.type===filters.sequence);
  $('pr-feed-note').innerHTML=`<span>Newest first · ${total>rows.length?`${num(rows.length)} of `:''}${num(total)} event${total===1?'':'s'}</span>${seq?`<span>${e(seq.icon)} ${e(seq.label)} only</span><button class="small-link" id="pr-seq-clear">Show every type</button>`:''}`;
  if($('pr-seq-clear'))$('pr-seq-clear').onclick=()=>{filters.sequence='';document.querySelectorAll('[data-pr-seq]').forEach(x=>x.setAttribute('aria-pressed','false'));renderFeed();};
  $('pr-feed').innerHTML=rows.length?`<ol>${rows.map(n=>`<li><button data-pr-event="${e(n.id)}"><span class="pr-icon" aria-hidden="true">${e(n.i)}</span><span class="pr-ev"><strong>${e(n.l)}</strong><small>${localDate(n.day)} ${clock(n.hour)} · <span class="mono">${e(n.acctId)}</span></small></span><span class="pr-cost">${money(costTotal(n.cost))}</span></button></li>`).join('')}</ol>`
   :`<div class="wl-empty"><p>${graph.nodes.length?'No events match these filters.':`No events in ${monthName(month)}.`}</p></div>`;
  $('pr-feed').querySelectorAll('[data-pr-event]').forEach(b=>b.onclick=()=>{reveal=true;select(b.dataset.prEvent);});markFeed();}
 // Selection only re-tints the feed (no re-render, so its scroll position and focus stay).
 function markFeed(){const id=route.eventId,g=graph&&indexGraph(graph).byId.has(id),up=g?upstream(graph,id):new Set(),down=g?downstream(graph,id):new Set();
  $('pr-feed').querySelectorAll('[data-pr-event]').forEach(b=>{const x=b.dataset.prEvent;b.className=x===id?'sel':up.has(x)?'up':down.has(x)?'down':'';if(x===id)b.setAttribute('aria-current','true');else b.removeAttribute('aria-current');});}
 function renderTrace(){const el=$('pr-trace'),prev=stack.at(-1),back=prev?`<button class="small-link pr-back" id="pr-back" title="${stack.length} earlier event${stack.length>1?'s':''}">← Back to ${e(prev.label)}</button>`:'';
  if(!route.eventId){el.innerHTML=back+'<div class="wl-empty"><p>Select an event to trace its Activity Sequence: the Initiating Event first, then every step with its delay and cost. Steps that led to the event are tinted red; steps that followed from it, blue.</p></div>';}
  else{const t=buildTrace(graph,route.eventId);
   if(!t)el.innerHTML=back+`<div class="wl-empty"><p>Event <code>${e(route.eventId)}</code> is not in the Activity Sequences raised in ${monthName(month)} as of ${e(costs.asOf)}.</p></div>`;
   else{const x=indexGraph(graph),type=costs.types.find(k=>k.type===t.variantId),init=t.steps[0].node;
    el.innerHTML=`${back}<div class="eyebrow">ACTIVITY SEQUENCE · ${e(t.seriesKey)}</div><h2>${e(type?.icon||init.i)} ${e(type?.label||init.l)}</h2><div class="wl-case-sub">Account <span class="mono">${e(t.acctId)}</span> · ${t.steps.length} steps from ${localDate(init.day)}</div>
     <div class="pr-totals">${[['Labour',money(t.cost.labor)],['System',money(t.cost.system)],['CX',money(t.cost.cx)],['Total',money(t.cost.total)],['Elapsed',t.elapsedDays.toFixed(1)+' d']].map(([k,v])=>`<div><span>${k}</span><strong>${v}</strong></div>`).join('')}</div>
     <a class="outline-btn pr-open" href="#/worklists/ALL/case/${e(t.seriesKey)}">Open case</a>
     <p class="pr-key"><span><i class="up"></i>${num(t.upstream.size)} led to the selected event</span><span><i class="down"></i>${num(t.downstream.size)} followed from it</span></p>
     <ol class="pr-pipe">${t.steps.map(s=>{const n=s.node,tint=s.role==='downstream'?'down':s.role==='upstream'||s.role==='selected'&&t.upstream.has(s.from)?'up':'',cls={selected:'sel',upstream:'up',downstream:'down'}[s.role]||'';
      return `${s.index?`<li class="pr-edge ${tint}"><span>${e(s.edge?EDGES[s.edge]||s.edge.replaceAll('_',' '):'then')}${s.adjacent||!s.edge?'':` · from ${e(x.byId.get(s.from)?.l)}`}</span><b>+${s.delay}d</b></li>`:''}<li class="pr-step ${cls}"><button data-pr-step="${e(n.id)}" ${s.role==='selected'?'aria-current="true"':''}><span class="pr-day">D+${s.dayN}</span><span class="pr-icon" aria-hidden="true">${e(n.i)}</span><span class="pr-ev"><strong>${e(n.l)}</strong>${s.initiating&&!s.index?'<em>Initiating Event</em>':''}<small>${localDate(n.day)} ${clock(n.hour)} · ${e(DOMAINS[n.d]||n.d)} · ${money(costTotal(n.cost))}</small></span></button></li>`;}).join('')}</ol>`;
    el.querySelectorAll('[data-pr-step]').forEach(b=>b.onclick=()=>select(b.dataset.prStep));}}
  if($('pr-back'))$('pr-back').onclick=()=>{const p=stack.pop();if(p)go({month:p.month,eventId:p.eventId});};
  if(reveal&&route.eventId&&matchMedia('(max-width:1100px)').matches)el.scrollIntoView({block:'start'});reveal=false;}
 // Viewing another event keeps the one before on a back stack (up to 30), across months.
 function select(id){if(id===route.eventId)return;const cur=graph&&indexGraph(graph).byId.get(route.eventId);if(cur){stack.push({month,eventId:cur.id,label:cur.l});if(stack.length>STACK_CAP)stack.shift();}go({month,eventId:id});}
 function go(next){route={...route,...next};const h=routeHash(route);if(location.hash!==h)location.hash=h;else open(route);}
 function open(r){if(!r)return;const m2c=client(),same=m2c&&graph&&loaded?.client===m2c&&loaded.key===dataKey(m2c)&&(r.month||month)===month;route=r;if(same){markFeed();renderTrace();}else load();}
 $('pr-month').onchange=ev=>go({month:Number(ev.target.value),eventId:null});
 $('pr-domain').onchange=ev=>{filters.domain=ev.target.value;if(graph)renderFeed();};$('pr-type').onchange=ev=>{filters.type=ev.target.value;if(graph)renderFeed();};
 let timer=0;$('pr-search').oninput=ev=>{clearTimeout(timer);timer=setTimeout(()=>{filters.search=ev.target.value.trim();if(graph)renderFeed();},200);};
 $('process-back').onclick=()=>{location.hash='#/worklists';};
 return {open,refresh:load};
}
