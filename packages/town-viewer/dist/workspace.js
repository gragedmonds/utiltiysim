// Utility Studio Workspace: SAP-style transactions over the meter-to-cash engine (Astra's design,
// prototypes/utility-studio). Records, amounts, statuses and VEE results come from the engine through EngineM2C;
// nothing here invents a record. Query context (what you executed) is session state, kept apart from engine data.
import {escapeText as e} from './customer-view.js';

export const TRANSACTIONS=[
 ['Worklists','exceptions','Clarification Case List'],
 ['Worklists','vee','Resolve Implausible Meter Readings'],
 ['Display','billing-query','Display Billing'],
 ['Display','read-query','Display Meter Reading Results']
];
export const CATEGORIES=['My Assigned Cases','AMP','Bill Correction','Bill Print Errors','Billing Errors','Billing Outsorts','Billing- see IT Supp','Budget Bill Cases','Invoice Errors','Invoice Outsorts','Low Income Process','MR Implausibles','Meter Read Follow-Up','Field Work'];
const MISSING=['COMM_FAIL','NO_ACCESS','NO_READ','CONSECUTIVE_ESTIMATES'];
const VALUE_QUEUES=['VEE_REVIEW','SUPERVISOR'];
const SUBSTATUS={queued:['001','Awaiting pickup'],assigned:['002','In analyst review'],escalated:['003','Supervisor review'],field:['010','Field visit'],held:['004','Held'],resolved:['009','Completed']};

// The clarification category of an engine case: the engine's own when it sends one, otherwise derived from its queue
// and exception type. Categories with no engine meaning stay empty rather than showing invented cases.
export function categoryOf(row){
 if(row.category)return row.category;
 if(row.queue==='FIELD')return 'Field Work';
 if(row.type==='RATE_CLASS')return 'Billing Errors';
 if(['HIGH_BILL','BILL_CREDIT'].includes(row.type))return 'Billing Outsorts';
 if(MISSING.includes(row.type)||row.queue==='ESTIMATION')return 'Meter Read Follow-Up';
 if(VALUE_QUEUES.includes(row.queue))return 'MR Implausibles';
 return 'MR Implausibles';
}
export function caseStatus(row){if(row.resolvedAt)return 'Completed';return row.assignee&&row.assignee!=='RPA'?'Assigned':'Open';}
export function substatus(row){if(row.resolvedAt)return SUBSTATUS.resolved;if(row.queue==='FIELD')return SUBSTATUS.field;if(row.queue==='SUPERVISOR')return SUBSTATUS.escalated;return row.assignee?SUBSTATUS.assigned:SUBSTATUS.queued;}
export function matchesCategory(row,category){return category==='My Assigned Cases'?row.assignee==='you':categoryOf(row)===category;}

// Workspace routes: #/workspace/<transaction>, #/workspace/case/<id>, #/workspace/billing/<installation>/<screen>,
// #/workspace/reads/<readId>[/<screen>], #/workspace/field-order/<orderId>.
export function parseWorkspaceRoute(hash){
 const parts=String(hash||'').replace(/^#\/workspace\/?/,'').split('/').filter(Boolean).map(decodeURIComponent);
 const [head='exceptions',a=null,b=null]=parts;
 if(head==='case')return {tx:'exceptions',caseId:a};
 if(head==='billing')return {tx:'billing',record:a,screen:b||'orders'};
 if(head==='reads')return {tx:'reads',record:a,screen:b||'reads'};
 if(head==='field-order')return {tx:'field-order',record:a};
 return {tx:TRANSACTIONS.some(t=>t[1]===head)?head:'exceptions'};
}
export function workspaceHash(r){
 if(r.caseId)return '#/workspace/case/'+encodeURIComponent(r.caseId);
 if(r.tx==='billing')return `#/workspace/billing/${encodeURIComponent(r.record)}/${r.screen||'orders'}`;
 if(r.tx==='reads')return `#/workspace/reads/${encodeURIComponent(r.record)}${r.screen&&r.screen!=='reads'?'/'+r.screen:''}`;
 if(r.tx==='field-order')return '#/workspace/field-order/'+encodeURIComponent(r.record);
 return '#/workspace/'+(r.tx||'exceptions');
}

const SCREENS={orders:'Billing Details',documents:'Billing Documents',document:'Display Billing Document',invoice:'Display Print Document',contract:'Display Contract',installation:'Display Installation',reads:'Meter Reading Results',device:'Display Device and Register'};
const money=n=>n==null?'—':new Intl.NumberFormat('en-CA',{style:'currency',currency:'CAD'}).format(n);
const num=(v,d=3)=>v==null?'—':new Intl.NumberFormat('en-CA',{maximumFractionDigits:d}).format(v);
const day=iso=>iso?String(iso).slice(0,10):'—';
const btn=(label,act,extra='')=>`<button type="button" data-ws="${act}" ${extra}>${label}</button>`;
const field=(label,value,extra='')=>`<div class="gui-field"><span>${e(label)}</span><span class="gui-value ${extra}" title="${value==null?'':e(String(value))}">${value==null||value===''?'—':e(String(value))}</span></div>`;
const group=(title,body,extra='')=>`<fieldset class="gui-group ${extra}"><legend>${e(title)}</legend>${body}</fieldset>`;

export function installWorkspace({getClient,toast=()=>{},onShowPremise=()=>{},onProcess=()=>{},root=document.getElementById('workspace-root')}){
 const client=()=>getClient();
 const ui={route:{tx:'exceptions'},category:'My Assigned Cases',status:'Open',query:'',sort:'age',compact:false,veeStatus:'open',veeUtility:'all',veeQuery:'',filters:false,selected:new Set(),historyOpen:false,queries:{installation:'',read:''},queryError:'',context:{installation:null,read:null},rows:[],veeRows:[],caseView:null,record:null,busy:0,message:''};
 // Query context: a record page opens only for the record you executed in this session.
 const has=(kind,id)=>ui.context[kind]===id;
 function go(r){const h=workspaceHash(r);if(location.hash!==h)location.hash=h;else open(h);}
 function header(tx,title=''){
  const groups=[...new Set(TRANSACTIONS.map(t=>t[0]))],current=title||TRANSACTIONS.find(t=>t[1]===tx)?.[2]||'';
  return `<header class="sap-transaction-header ${title?'sap-transaction-classic':''}"><span class="sap-emblem">SAP</span><select id="ws-transaction" aria-label="SAP transaction">${title?`<option value="" selected disabled>${e(title)}</option>`:''}${groups.map(g=>`<optgroup label="${g}">${TRANSACTIONS.filter(t=>t[0]===g).map(([,id,label])=>`<option value="${id}" ${!title&&id===tx?'selected':''}>${label}</option>`).join('')}</optgroup>`).join('')}</select><span class="spacer"></span><small>100</small></header>`;
 }
 function statusbar(text){const m=client();return `<footer class="fiori-status"><span class="sap-square green"></span><span>${e(text)}</span><span class="spacer"></span><label class="ws-asof">Run date <input type="date" id="ws-asof" min="2026-01-01" max="2026-12-31" value="${e(m?.asOf||ui.asOf||'')}"></label><span>Engine data</span></footer>`;}
 function empty(text){return `<section class="fiori-shell">${header(ui.route.tx)}<div class="fiori-empty ws-empty">${text}</div>${statusbar('Workspace')}</section>`;}

 // ---- Clarification Case List ----------------------------------------------------------------------------------
 function caseRows(){const q=ui.query.trim().toLowerCase();return ui.rows.filter(r=>matchesCategory(r,ui.category)&&(ui.status==='All'||(ui.status==='Completed'?!!r.resolvedAt:!r.resolvedAt))&&(!q||`${r.caseId} ${r.label} ${r.address} ${r.accountId} ${r.premiseId}`.toLowerCase().includes(q)));}
 function caseBody(){const rows=caseRows();return rows.length?rows.map(r=>{const [code,text]=substatus(r),done=!!r.resolvedAt;return `<tr class="clarification-row" data-case="${e(r.caseId)}" tabindex="0"><td><span class="clarification-status ${done?'complete':''}"></span></td><td class="${done?'':'overdue-cell'}">${done?'—':r.ageDays+' d'}</td><td>${e(r.caseId)}</td><td>${e(r.icon||'')} ${e(r.label)} · ${e(r.address)}</td><td>${caseStatus(r)}</td><td>${code}</td><td>${e(text)}</td><td>${e(r.queue||'—')}</td><td>Monthly</td><td>UTILSIM</td><td>${e(r.assignee==='you'?'You':r.assignee||'Unassigned')}</td></tr>`;}).join(''):`<tr><td colspan="11" class="fiori-empty">${ui.busy?'Loading cases from the engine…':`No ${ui.status==='Open'?'open ':''}cases in ${e(ui.category)}${ui.query?' match this search':''}.`}</td></tr>`;}
 function casesPage(){const n=caseRows().length;return `<section class="fiori-shell clarification-shell">${header('exceptions')}<div class="clarification-main-toolbar">${btn(ui.compact?'Comfortable layout':'Compact layout','layout')}${btn('Update Clarification Case List','refresh')}${btn('Export list','export-cases')}</div><div class="clarification-layout"><aside class="clarification-sidebar"><div>Billing</div><nav aria-label="Clarification categories">${CATEGORIES.map(c=>`<button data-category="${c}" class="${ui.category===c?'active':''}" ${ui.category===c?'aria-current="page"':''}>${c}</button>`).join('')}</nav></aside><section class="clarification-main"><div class="clarification-title">${e(ui.category)}</div><div class="clarification-table-toolbar">${btn(ui.sort==='age'?'Oldest first':'Case number','sort','class="native-tool sort-tool" title="Change sort order"')}<label class="sr-only" for="ws-status">Status</label><select id="ws-status">${['Open','Completed','All'].map(v=>`<option ${ui.status===v?'selected':''}>${v}</option>`).join('')}</select><input type="search" id="ws-query" placeholder="Case, text, account…" value="${e(ui.query)}" aria-label="Find clarification case"><span class="spacer"></span><span id="ws-count">${n} cases</span></div><div class="clarification-table-scroll ${ui.compact?'compact':''}"><table class="clarification-table"><thead><tr><th></th><th>Overdue</th><th>Case</th><th>Clarification Case Text</th><th>Status</th><th>Substatus</th><th>Substatus Text</th><th>Job</th><th>Interval</th><th>Logical system</th><th>Assignee</th></tr></thead><tbody id="ws-cases">${caseBody()}</tbody></table></div></section></div>${statusbar('Clarification Case List')}</section>`;}
 async function loadCases(){const m=client();if(!m)return;const ticket=++ui.busy;try{const status=ui.status==='Completed'?'resolved':ui.status==='All'?'all':'open';const res=await m.queue({status,sort:ui.sort==='age'?'age':'created',page:1,pageSize:200,...(ui.category&&ui.category!=='My Assigned Cases'?{category:ui.category}:{})});if(ticket!==ui.busy)return;ui.rows=res.rows||[];ui.total=res.total;ui.asOf=res.asOf;}catch(err){if(!err.superseded)toast('Engine: '+err.message);}finally{if(ticket===ui.busy){ui.busy=0;render();}}}

 // ---- Clarification case detail ---------------------------------------------------------------------------------
 function casePage(c){
  const row=c,done=!!c.resolvedAt,[code,text]=substatus(c),category=categoryOf(c),catCode=String(Math.max(1,CATEGORIES.indexOf(category))).padStart(2,'0'),decision=c.decision||{},read=c.read||{},acts=new Set(c.actions||[]);
  const tests=(decision.tests||[]).map(t=>`<tr><td>${e(t.test)}</td><td>${e(t.outcome)}</td><td>${num(t.contribution,3)}</td><td>${e(t.rationale)}</td></tr>`).join('');
  const history=(c.events||[]).map((ev,i)=>`<tr><td>${i+1}</td><td>${day(ev.occurredAt)} ${String(ev.occurredAt||'').slice(11,16)}</td><td>${e(ev.payload?.icon||'')} ${e(ev.payload?.label||ev.eventType)}</td></tr>`).join('');
  const valueActions=[acts.has('accept')?btn('<span class="gui-action-check">✓</span> Clarif. Case Completed','accept',`class="gui-yellow" ${done?'disabled':''} title="Release the read as it stands"`):'',acts.has('estimate')?btn('Estimate &amp; release','estimate','class="gui-yellow"'):'',acts.has('override')?btn('Correct value…','override','class="gui-yellow"'):'',acts.has('escalate')?btn('Escalate','escalate','class="gui-yellow"'):''].join('');
  return `<section class="fiori-shell gui-case-shell" aria-label="Clarification Case Detail">${header('exceptions','Clarification Case Detail')}<nav class="gui-transaction-toolbar" aria-label="Case transactions">${btn('‹ Back to List','back')}${btn('Display Billing','billing-query')}${btn('Show on map','show-map')}${btn('Activity sequence','trace')}</nav><div class="gui-case-scroll"><div class="gui-case-content"><div class="gui-case-header"><div><div class="gui-field"><span>Clar.Case Cat.</span><span class="gui-code">${catCode}</span><span class="gui-inline-text">${e(category)}</span></div>${field('Clarif. Case',c.caseId)}</div><div>${field('Created on',day(c.createdAt))}${field('Time',String(c.createdAt||'').slice(11,16))}${field('Created By',c.queue==='BILLING'?'BILLING_RUN':'VEE_BATCH')}</div></div>
   ${group('Master Data',`<div class="gui-master-grid"><div>${field('Contract Acct',c.accountId)}${field('Installation',read.installationId)}${field('Premise',c.premiseId)}</div><div>${field('Address',c.address)}${field('Division',c.commodity)}${field('Device',read.meterId)}</div></div>`)}
   ${group('Clarification Reason',`<div class="gui-field gui-reason"><span>Clarific.Reason</span><span class="gui-code">${e(c.sapValidationCode||c.type)}</span><span class="gui-reason-text">${e(c.label)}</span></div><p class="gui-reason-description">${e(decision.tests?.find(t=>t.contribution>0)?.rationale||'')}</p>${tests?`<table class="gui-history-table ws-tests"><thead><tr><th>VEE test</th><th>Outcome</th><th>Risk</th><th>Rationale</th></tr></thead><tbody>${tests}</tbody></table>`:''}`)}
   ${group('Meter Reading',`<div class="gui-master-grid"><div>${field('Read document',read.id)}${field('Read date',day(read.readAt))}${field('Read status',read.readStatus)}</div><div>${field('Previous register',num(read.previousRegisterValue))}${field('Reported register',num(read.registerValue))}${field('Consumption',read.consumption==null?null:num(read.consumption)+' '+(read.unit||''))}</div></div>`)}
   <div class="gui-primary-actions">${valueActions||'<span class="gui-processing-hint">No engine actions are open on this case.</span>'}</div>
   ${group('Status/lock information',`<div class="gui-status-grid"><div class="gui-status-fields">${field('Last Processing Status',text,'gui-select-display')}${field('Status',done?'Completed':caseStatus(c),'gui-select-display')}${field('Substatus',code)}</div><div class="gui-status-right">${btn('▤ &nbsp; History','history','class="gui-yellow"')}${field('Last Processor',c.assignee==='you'?'You':c.assignee||'Unassigned')}${field('Queue',c.queue)}</div></div>`)}
   ${group('Processing',`<div class="gui-master-grid"><div>${field('Bill impact',money(c.impact))}${field('VEE confidence',c.confidence==null?null:Math.round(c.confidence*100)+'%')}</div><div>${field('Disposition',c.disposition)}${field('Outcome',c.outcome)}</div></div><div class="gui-inline-actions">${btn('Take ownership','assign','class="gui-yellow" disabled title="Needs the engine case-ownership action"')}${btn('Add note','note','class="gui-yellow" disabled title="Needs the engine case-note action"')}${btn('Create Field Service Order','field-order','class="gui-yellow" disabled title="Needs the engine field-service-order lifecycle"')}</div>`)}
   ${ui.historyOpen?group('Processing History',`<table class="gui-history-table"><thead><tr><th>Step</th><th>When</th><th>Activity</th></tr></thead><tbody>${history}</tbody></table>`,'gui-history'):''}
  </div></div>${statusbar('Clarification case '+c.caseId+' · '+(done?'Completed':caseStatus(c)))}</section>`;
 }
 async function loadCase(id){const m=client();if(!m)return;const ticket=++ui.busy;try{const c=await m.caseView(id);if(ticket!==ui.busy)return;ui.caseView=c;ui.asOf=c.asOf;}catch(err){if(!err.superseded){ui.caseView=null;ui.message=err.status===404?`Case ${id} is not in this run.`:err.message;}}finally{if(ticket===ui.busy){ui.busy=0;render();}}}

 // ---- Resolve Implausible Meter Readings ------------------------------------------------------------------------
 function veeRows(){const q=ui.veeQuery.trim().toLowerCase();return ui.veeRows.filter(r=>(ui.veeUtility==='all'||r.commodity===ui.veeUtility)&&(!q||`${r.caseId} ${r.address} ${r.accountId} ${r.meterId||''} ${r.readId}`.toLowerCase().includes(q)));}
 function veeBody(){const rows=veeRows();return rows.length?rows.map(r=>{const done=!!r.resolvedAt,sel=ui.selected.has(r.caseId);return `<tbody class="vee-record ${done?'released':''}"><tr class="vee-main-row"><td><input type="checkbox" data-read-select="${e(r.caseId)}" ${sel?'checked':''} ${done?'disabled':''} aria-label="Select reading ${e(r.readId)}"></td><td><span class="${done?'vee-released':'vee-overdue'}">${done?'Released':`${r.ageDays} Days<br>Overdue`}</span><br>${e(r.readDate)}</td><td><button class="fiori-link" data-ws="open-read" data-case="${e(r.caseId)}">${e(r.meterId||r.registerId)}</button><br><span class="vee-doc-id">${e(r.readId)}</span><br><span>${e(String(r.commodity).toUpperCase())};${e(r.unit||'')}</span></td><td>001<br>${e(r.commodity)} register</td><td><input type="checkbox" disabled aria-label="No additional meter reading reasons"></td><td>${e(r.mruId||'—')}</td><td>Periodic Meter Reading (01)</td><td>${e(r.technology||'')}</td><td>${btn('›','open-read',`data-case="${e(r.caseId)}" class="row-chevron" aria-label="Open ${e(r.readId)}"`)}</td></tr><tr class="vee-detail-row"><td></td><td colspan="8"><div class="vee-line"><span>Independent Validation:</span><div>${e(r.validationText||r.label)}<br>${e(r.sapValidationCode||'')}</div></div><div class="vee-line"><span>Consumption/Demand:</span><div>Current: &nbsp;${num(r.consumption)} ${e(r.unit||'')}<br>Expected: ${num(r.expected)} ${e(r.unit||'')}</div></div></td></tr></tbody>`;}).join(''):`<tbody><tr><td colspan="9" class="fiori-empty">${ui.busy?'Loading meter readings from the engine…':'No meter readings match the selected filters.'}</td></tr></tbody>`;}
 function veePage(){const rows=veeRows(),open=rows.filter(r=>!r.resolvedAt),selected=open.filter(r=>ui.selected.has(r.caseId)).length;return `<section class="fiori-shell vee-shell">${header('vee')}<section class="vee-variant"><div class="vee-variant-line">${btn('Standard <span class="chevron-down"></span>','filters',`aria-expanded="${ui.filters}"`)}<div class="vee-views"><label class="sr-only" for="ws-vee-view">Read status</label><select id="ws-vee-view"><option value="open" ${ui.veeStatus==='open'?'selected':''}>Open</option><option value="resolved" ${ui.veeStatus==='resolved'?'selected':''}>Released</option><option value="all" ${ui.veeStatus==='all'?'selected':''}>All statuses</option></select></div></div><div class="vee-filter-summary">Filtered By: ${ui.veeStatus==='open'?'Open implausible readings':ui.veeStatus==='resolved'?'Released readings':'All readings'}${ui.veeUtility==='all'?'':' · '+e(ui.veeUtility)}</div><div class="vee-filters" ${ui.filters?'':'hidden'}><label>Utility<select id="ws-vee-utility">${[['all','All utilities'],['gas','Gas'],['water','Water'],['electric','Electric']].map(([v,l])=>`<option value="${v}" ${ui.veeUtility===v?'selected':''}>${l}</option>`).join('')}</select></label><label>Device, account or address<input id="ws-vee-query" type="search" value="${e(ui.veeQuery)}" placeholder="Search readings"></label>${btn('Clear filters','clear-vee')}</div></section><div class="vee-list"><div class="vee-list-toolbar"><h2>Meter Readings (<span>${rows.length}</span>)</h2><span class="spacer"></span><span class="vee-selected">${selected?selected+' selected':''}</span>${btn('Create Field Service Order','field-order',`disabled title="Needs the engine field-service-order lifecycle"`)}${btn('Estimate','estimate-reads',selected?'':'disabled')}${btn('Release','release-reads',selected?'':'disabled')}</div><div class="vee-scroll"><table class="vee-table"><thead><tr><th><input type="checkbox" id="ws-select-all" aria-label="Select all open readings" ${selected&&selected===open.length?'checked':''}></th><th>Sched.<br>Reading Date</th><th>Device</th><th>Register</th><th>More MR<br>Reasons</th><th>Meter Reading Unit</th><th>Meter reading reason</th><th>Meter reading type</th><th></th></tr></thead>${veeBody()}</table></div></div>${statusbar('Resolve Implausible Meter Readings')}</section>`;}
 async function loadVee(){const m=client();if(!m)return;const ticket=++ui.busy;try{const rows=[];for(const queue of VALUE_QUEUES){const res=await m.post('/process/queue',{queue,status:ui.veeStatus,page:1,pageSize:200},'vee:'+queue);ui.asOf=res.asOf;rows.push(...(res.rows||[]));}if(ticket!==ui.busy)return;ui.veeRows=rows.filter(r=>!MISSING.includes(r.type)).sort((a,b)=>b.ageDays-a.ageDays||a.caseId.localeCompare(b.caseId));}catch(err){if(!err.superseded)toast('Engine: '+err.message);}finally{if(ticket===ui.busy){ui.busy=0;render();}}}
 async function releaseSelected(type){const m=client(),ids=[...ui.selected];if(!m||!ids.length)return;let done=0;for(const id of ids){try{await m.act(type,id);done++;ui.selected.delete(id);}catch(err){if(!err.superseded){toast(`${id}: ${err.message}`);break;}}}if(done)toast(`${done} reading${done>1?'s':''} ${type==='estimate'?'estimated and released':'released'} on ${m.asOf}.`);loadVee();}

 // ---- Display Billing / Display Meter Reading Results: query first, then the record ------------------------------
 function queryPage(kind){const isBill=kind==='installation',tx=isBill?'billing-query':'read-query',label=isBill?'Installation':'Meter reading document',value=ui.queries[kind];return `<section class="fiori-shell sap-query-shell">${header(tx)}<form class="sap-query" id="ws-query-form" data-kind="${kind}"><div class="sap-query-row"><label for="ws-query-input">${label}</label><input id="ws-query-input" name="q" value="${e(value)}" autocomplete="off" spellcheck="false" placeholder="${isBill?'Installation number':'Read document id'}">${btn('F4','f4',`data-kind="${kind}" title="Possible entries" aria-label="Possible entries for ${label}"`)}<button type="submit" class="sap-execute">Execute</button></div>${ui.queryError?`<p class="sap-query-error" role="alert">${e(ui.queryError)}</p>`:''}<div id="ws-f4"></div></form>${statusbar(isBill?'Display Billing':'Display Meter Reading Results')}</section>`;}
 async function execute(kind,raw){const id=String(raw||'').trim();ui.queries[kind]=id;ui.queryError='';if(!id){ui.queryError=`Enter ${kind==='installation'?'an installation':'a meter reading document'}.`;render();return;}const m=client();if(!m)return;try{const rec=await m.post(kind==='installation'?'/m2c/installation':'/m2c/read-document',kind==='installation'?{installationId:id}:{readId:id},'record');ui.record=rec;ui.context[kind]=id;go(kind==='installation'?{tx:'billing',record:id,screen:'orders'}:{tx:'reads',record:id});}catch(err){if(err.superseded)return;ui.queryError=/Engine 40[45]: (Not Found|Method Not Allowed)$/.test(err.message)?'This engine does not offer the lookup yet.':err.status===404?`${kind==='installation'?'Installation':'Meter reading document'} ${id} does not exist in this run.`:err.message;render();}}
 async function possibleEntries(kind){const m=client(),box=root.querySelector('#ws-f4');if(!m||!box)return;try{const res=await m.post('/m2c/possible-entries',{kind:kind==='installation'?'installation':'read',query:root.querySelector('#ws-query-input')?.value||'',page:1},'f4');box.innerHTML=`<table class="sap-f4"><thead><tr><th>Value</th><th>Description</th></tr></thead><tbody>${(res.rows||res.entries||[]).map(x=>`<tr><td><button type="button" class="fiori-link" data-f4="${e(x.id)}">${e(x.id)}</button></td><td>${e(x.text||x.description||'')}</td></tr>`).join('')||'<tr><td colspan="2">No entries.</td></tr>'}</tbody></table>`;}catch(err){if(!err.superseded)box.innerHTML=`<p class="sap-query-error">${err.status===404||err.status===405?'Possible entries need an engine update.':e(err.message)}</p>`;}}
 function recordPage(){const r=ui.route,rec=ui.record,isBill=r.tx==='billing';if(!rec)return empty('Loading the record from the engine…');const screen=r.screen||'orders',title=SCREENS[screen]||'Billing Details';
  const tabs=isBill?['orders','documents','contract','installation']:['reads','device'];
  const nav=`<nav class="gui-transaction-toolbar">${btn('‹ Back','record-back')}${tabs.map(s=>btn(SCREENS[s],'screen',`data-screen="${s}" ${s===screen?'aria-current="page"':''}`)).join('')}${btn('Show on map','show-map')}</nav>`;
  return `<section class="fiori-shell gui-case-shell">${header(isBill?'billing-query':'read-query',title)}${nav}<div class="gui-case-scroll"><div class="gui-case-content"><pre class="ws-record">${e(JSON.stringify(rec,null,1).slice(0,6000))}</pre></div></div>${statusbar(title+' · '+r.record)}</section>`;}

 // ---- rendering and events --------------------------------------------------------------------------------------
 function render(){const m=client();if(!root)return;if(!m){root.innerHTML=`<section class="fiori-shell"><div class="fiori-empty ws-empty"><h2>Workspace needs the engine</h2><p>Open an engine town (for example <code>?town=ayr</code>), or run <code>uv run utilsim serve</code> locally and add <code>?engine=http://127.0.0.1:8010</code>.</p></div></section>`;return;}
  const r=ui.route;let html;
  if(r.caseId)html=ui.caseView&&ui.caseView.caseId===r.caseId?casePage(ui.caseView):empty(ui.message||'Loading the case from the engine…');
  else if(r.tx==='vee')html=veePage();
  else if(r.tx==='billing-query')html=queryPage('installation');
  else if(r.tx==='read-query')html=queryPage('read');
  else if(r.tx==='billing'||r.tx==='reads')html=recordPage();
  else if(r.tx==='field-order')html=empty('Field service orders open from a clarification case or a selected implausible reading once the engine order lifecycle is available.');
  else html=casesPage();
  root.innerHTML=html;
 }
 function open(hash){const r=parseWorkspaceRoute(hash);ui.message='';
  // Record pages need the matching executed query in this session; otherwise return to the query.
  if(r.tx==='billing'&&!has('installation',r.record)){go({tx:'billing-query'});return;}
  if(r.tx==='reads'&&!has('read',r.record)){go({tx:'read-query'});return;}
  ui.route=r;render();
  if(r.caseId)loadCase(r.caseId);else if(r.tx==='vee')loadVee();else if(r.tx==='exceptions')loadCases();
 }
 root?.addEventListener('change',ev=>{const t=ev.target;
  if(t.id==='ws-transaction'&&t.value){ui.queryError='';go({tx:t.value});}
  else if(t.id==='ws-status'){ui.status=t.value;loadCases();}
  else if(t.id==='ws-vee-view'){ui.veeStatus=t.value;ui.selected.clear();loadVee();}
  else if(t.id==='ws-vee-utility'){ui.veeUtility=t.value;render();}
  else if(t.dataset.readSelect){if(t.checked)ui.selected.add(t.dataset.readSelect);else ui.selected.delete(t.dataset.readSelect);render();}
  else if(t.id==='ws-select-all'){const open=veeRows().filter(r=>!r.resolvedAt);if(t.checked)open.forEach(r=>ui.selected.add(r.caseId));else ui.selected.clear();render();}
  else if(t.id==='ws-asof'&&t.value){const m=client();m.setAsOf(t.value);toast(`Run date ${t.value}: actions are recorded on this day.`);open(location.hash);}
 });
 root?.addEventListener('input',ev=>{const t=ev.target;if(t.id==='ws-query'){ui.query=t.value;const body=root.querySelector('#ws-cases');if(body){body.innerHTML=caseBody();root.querySelector('#ws-count').textContent=caseRows().length+' cases';}}else if(t.id==='ws-vee-query'){ui.veeQuery=t.value;}});
 root?.addEventListener('submit',ev=>{const f=ev.target;if(f.id==='ws-query-form'){ev.preventDefault();execute(f.dataset.kind,f.q.value);}});
 root?.addEventListener('click',async ev=>{
  const cat=ev.target.closest('[data-category]');if(cat){if(cat.dataset.category==='MR Implausibles'){go({tx:'vee'});return;}ui.category=cat.dataset.category;render();loadCases();return;}
  const row=ev.target.closest('[data-case]:not([data-ws])');if(row&&row.tagName==='TR'){go({caseId:row.dataset.case});return;}
  const f4=ev.target.closest('[data-f4]');if(f4){const input=root.querySelector('#ws-query-input');input.value=f4.dataset.f4;ui.queries[root.querySelector('#ws-query-form').dataset.kind]=f4.dataset.f4;root.querySelector('#ws-f4').innerHTML='';input.focus();return;} // F4 selects; Execute is still needed
  const b=ev.target.closest('[data-ws]');if(!b||b.disabled)return;const act=b.dataset.ws,m=client(),c=ui.caseView;
  if(act==='layout'){ui.compact=!ui.compact;render();}
  else if(act==='refresh')loadCases();
  else if(act==='sort'){ui.sort=ui.sort==='age'?'case':'age';loadCases();}
  else if(act==='export-cases')exportCsv(caseRows());
  else if(act==='filters'){ui.filters=!ui.filters;render();}
  else if(act==='clear-vee'){ui.veeUtility='all';ui.veeQuery='';render();}
  else if(act==='release-reads')releaseSelected('accept');
  else if(act==='estimate-reads')releaseSelected('estimate');
  else if(act==='open-read')go({caseId:b.dataset.case});
  else if(act==='back')go({tx:'exceptions'});
  else if(act==='history'){ui.historyOpen=!ui.historyOpen;render();}
  else if(act==='billing-query')go({tx:'billing-query'});
  else if(act==='f4')possibleEntries(b.dataset.kind);
  else if(act==='record-back')go({tx:ui.route.tx==='billing'?'billing-query':'read-query'});
  else if(act==='screen')go({...ui.route,screen:b.dataset.screen});
  else if(act==='show-map'){const id=c?.premiseId||ui.record?.premiseId||ui.record?.installation?.premiseId;if(id)onShowPremise(id);}
  else if(act==='trace'&&c)onProcess(c);
  else if(['accept','estimate','escalate'].includes(act)&&c){try{await m.act(act,c.caseId);toast(`${c.caseId}: ${act} recorded on ${m.asOf}.`);loadCase(c.caseId);}catch(err){if(!err.superseded)toast(err.message);}}
  else if(act==='override'&&c){const v=prompt('Corrected register value',c.read?.registerValue??'');if(v==null||v==='')return;try{await m.act('override',c.caseId,v);toast(`${c.caseId}: corrected value recorded.`);loadCase(c.caseId);}catch(err){if(!err.superseded)toast(err.message);}}
 });
 function exportCsv(rows){const head=['caseId','category','label','address','accountId','queue','assignee','ageDays','impact'],csv=[head.join(','),...rows.map(r=>head.map(k=>JSON.stringify(k==='category'?categoryOf(r):r[k]??'')).join(','))].join('\n'),a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.download='clarification-cases.csv';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
 return {open,render,get state(){return ui;}};
}
