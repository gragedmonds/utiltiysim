// Data: the tables behind the town and its meter-to-cash run (customers, meters and reads, bills and prices,
// collections, work), as the engine holds them on the run date. The engine builds, filters, sorts and pages every
// table (POST /api/m2c/table), writes the CSV (POST /api/m2c/table.csv) and makes the links another system reads
// (POST /api/m2c/table/link, then GET /api/m2c/export/<table>.csv|json); this page asks, shows and formats, and
// opens the record behind a linked cell (premise on the map, installation or read in the Workspace, account, case,
// order). Route: #/data[/<table>]. Nothing here computes a figure.
import {engineNotice} from './workspace.js';
import {bindPopovers} from './config-page.js';
import {activeYear,dayYear} from './m2c.js';
export const ROUTE=/^#\/data(?:\/([\w-]+))?$/;
export const PAGE_SIZES=[50,100,200,500];
export const CSV_PAGE=5000;
export const INLINE_FACETS=6; // facet selects shown before "More filters"
export function parseDataRoute(hash){const m=String(hash||'').match(ROUTE);return {table:m?.[1]||null};}
export function dataHash(table){return table?'#/data/'+encodeURIComponent(table):'#/data';}
const e=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const NUM=new Intl.NumberFormat('en-CA',{maximumFractionDigits:3}),INT=new Intl.NumberFormat('en-CA',{maximumFractionDigits:0}),MONEY=new Intl.NumberFormat('en-CA',{style:'currency',currency:'CAD'});
// A cell as text: money, counts and numbers in Canadian notation, shares as percentages, yes/no, dates as the engine wrote them.
export function fmtCell(v,col){if(v==null||v==='')return '—';switch(col?.kind){case 'money':return MONEY.format(v);case 'int':return INT.format(v);case 'num':return NUM.format(v);case 'pct':return Math.round(Number(v)*100)+'%';case 'bool':return v?'Yes':'No';default:return String(v);}}
// The account an invoice belongs to: the row's accountId column, else the id itself (INV-{account}-{YYYYMMDD}).
export function invoiceAccount(id,row=null,columns=null){const k=columns?.findIndex(c=>c.key==='accountId')??-1;if(k>=0&&row?.[k])return row[k];const m=/^INV-(.+)-\d{8}$/.exec(String(id||''));return m?m[1]:null;}
// Where a linked cell goes: a premise on the map, a record the Workspace opens, or a Workspace page by hash.
export function linkTarget(col,value,row=null,columns=null){if(value==null||value==='')return null;const id=String(value);
 switch(col?.link){case 'premise':return {kind:'premise',id};case 'installation':return {kind:'installation',id};case 'read':return {kind:'read',id};
  case 'account':return {hash:'#/workspace/account/'+encodeURIComponent(id)};case 'invoice':{const a=invoiceAccount(id,row,columns);return a?{hash:'#/workspace/account/'+encodeURIComponent(a)}:null;}
  case 'case':return {hash:'#/workspace/case/'+encodeURIComponent(id)};case 'order':return {hash:'#/workspace/field-order/'+encodeURIComponent(id)};default:return null;}}
// CSV pages from the engine (each with its header) as one file.
export function stitchCsv(pages){return pages.map((t,i)=>i?t.replace(/^[^\n]*\n?/,''):t).join('');}
export const pageCount=(total,size)=>Math.max(1,Math.ceil((total||0)/Math.max(1,size)));
export function csvName(town,table,asOf){return `${String(town||'town').replace(/[^\w-]+/g,'-')}-${table}-${asOf||'run'}.csv`;}
// Hidden columns per table, remembered in this browser.
const PREFS='utility-town-data-cols:';
export function loadHidden(storage,table){try{const v=JSON.parse(storage?.getItem(PREFS+table)||'[]');return new Set(Array.isArray(v)?v:[]);}catch{return new Set();}}
export function saveHidden(storage,table,hidden){try{if(hidden.size)storage?.setItem(PREFS+table,JSON.stringify([...hidden]));else storage?.removeItem(PREFS+table);}catch{}}
// The facet selects: the first INLINE_FACETS inline, the rest behind "More filters"; a set filter is marked.
export function facetMarkup(columns,facets,filters){const cols=columns.filter(c=>c.facet&&facets?.[c.key]?.length);
 const one=c=>{const v=filters[c.key];const set=v!=null;return `<label class="data-facet${set?' is-set':''}"><span>${e(c.label)}</span><select data-facet="${e(c.key)}" aria-label="${e(c.label)}"><option value="*"${set?'':' selected'}>All</option>${facets[c.key].map(f=>{const val=f.value==null?'':String(f.value);const text=f.value==null?'(blank)':f.value===true?'Yes':f.value===false?'No':String(f.value);return `<option value="${e(val)}"${set&&String(v)===val?' selected':''}>${e(text)} · ${INT.format(f.count)}</option>`;}).join('')}</select></label>`;};
 const inline=cols.slice(0,INLINE_FACETS).map(one).join(''),more=cols.slice(INLINE_FACETS);const moreSet=more.some(c=>filters[c.key]!=null);
 return inline+(more.length?`<details class="data-more"${moreSet?' open':''}><summary>More filters${moreSet?' ·':''}</summary><div class="data-more-body">${more.map(one).join('')}</div></details>`:'');}
export function sourceLabel(source){return source==='town'?'Town snapshot':source==='run'?'Engine run · as of the run date':'Town snapshot + engine run';}
// Connecting another system: the engine's links (POST /api/m2c/table/link) as absolute URLs, and the panel that
// explains them. A link carries the run's inputs, so it returns this table of this run whoever asks.
export function absoluteUrl(apiBase,path,origin=globalThis.location?.href||'http://localhost/'){return new URL(String(apiBase||'/api').replace(/\/?$/,'/')+path,origin).href;}
export function withoutPage(url){const u=new URL(url);u.searchParams.delete('page');return u.href;}
export function connectLinks(link,apiBase,origin){if(!link?.paths)return null;return {csv:absoluteUrl(apiBase,link.paths.csv,origin),json:absoluteUrl(apiBase,link.paths.json,origin)};}
export function connectMarkup(link,{apiBase,origin,title,asOf,columns=[],body=null}={}){
 const urls=connectLinks(link,apiBase,origin),total=link?.total??0,id=columns.find(c=>c.kind==='id')?.key||columns[0]?.key||'id';
 const row=(kind,label,url)=>`<div class="connect-row"><label for="connect-${kind}">${label}</label><input id="connect-${kind}" readonly value="${e(url)}" spellcheck="false"><button type="button" class="outline-btn" data-copy="connect-${kind}">Copy</button></div>`;
 const post=absoluteUrl(apiBase,'m2c/table.csv',origin),postJson=absoluteUrl(apiBase,'m2c/table',origin);
 const bodyText=body?JSON.stringify({...body,page:1,pageSize:CSV_PAGE},null,2):'';
 const pages=`${INT.format(total)} row${total===1?'':'s'}: ${INT.format(link?.pages?.csv??1)} CSV page${(link?.pages?.csv??1)===1?'':'s'} of up to ${INT.format(link?.pageSize?.csv??CSV_PAGE)} rows, or ${INT.format(link?.pages?.json??1)} JSON page${(link?.pages?.json??1)===1?'':'s'} of up to ${INT.format(link?.pageSize?.json??1000)}.`;
 return `<section class="data-connect" aria-labelledby="connect-title"><div class="connect-head"><h3 id="connect-title">Connect another system to ${e(title||'this table')}</h3><button type="button" class="small-link" id="connect-close">Close</button></div>
<p>${urls?`These links return ${e(title||'this table')} as of ${e(asOf||'the run date')} with your filters, sort and visible columns: the rows on this page, from this run (its settings, scenarios and your work). Celonis, Power BI, Excel, a database job or a script can read them on a schedule with a plain GET; no login. Anyone with a link can read this simulated data.`:`This run's inputs are too large to put in a link. A system can still POST them: see “POST the request” below.`}</p>
${urls?row('csv','CSV',urls.csv)+row('json','JSON',urls.json)+`<p class="small-note">${pages} Change <code>page=1</code> to <code>page=2</code>, <code>3</code>… Every response gives the total (<code>X-Total-Rows</code> header; <code>total</code> in JSON) and the next page (<code>Link: rel="next"</code> header; <code>next</code> in JSON, null on the last page).</p>`:''}
${urls?`<details><summary>Celonis</summary><ol><li>In Data Integration, add a data connection that extracts from a REST API (a custom connection built with the Extractor Builder).</li><li>Endpoint: <code>GET</code> <code>${e(withoutPage(urls.json))}</code>, with a query parameter <code>page</code> paginated by page number from 1 until <code>next</code> is null (or <code>rows</code> comes back empty).</li><li>Records: the list in <code>rows</code>; each column is a field with the keys of the CSV header. Use <code>${e(id)}</code> as the primary key.</li><li>Schedule the extraction. The link returns the same data until the simulation changes; then copy the new link from here and update the endpoint.</li></ol></details>
<details><summary>Power BI or Excel</summary><p>Get Data › From Web, and paste the CSV link. One page holds up to ${INT.format(CSV_PAGE)} rows; for more, add a query per page (<code>page=2</code>…) and append them, or use the JSON link with paging.</p></details>
<details><summary>curl</summary><pre>curl -o page1.csv "${e(urls.csv)}"\n# every page, one file each, until the last\nfor p in $(seq 1 ${link?.pages?.csv??1}); do\n  curl -o "page$p.csv" "${e(withoutPage(urls.csv))}&amp;page=$p"\ndone</pre></details>
<details><summary>Python</summary><pre>import pandas as pd\nimport requests\n\nurl = "${e(urls.json)}"\nrows = []\nwhile url:\n    page = requests.get(url, timeout=180).json()\n    rows += page["rows"]\n    url = page["next"]\ndf = pd.DataFrame(rows)</pre></details>`:''}
<details${urls?'':' open'}><summary>POST the request (any size)</summary><p>Send this body to <code>${e(post)}</code> (CSV, up to ${INT.format(CSV_PAGE)} rows a page) or <code>${e(postJson)}</code> (JSON, up to 500), with <code>Content-Type: application/json</code>, changing <code>page</code> until every row is in.</p>${bodyText?`<div class="connect-row"><label for="connect-body">Body</label><textarea id="connect-body" readonly rows="6" spellcheck="false">${e(bodyText)}</textarea><button type="button" class="outline-btn" data-copy="connect-body">Copy</button></div>`:''}</details>
<p class="small-note">A link holds this run's inputs: change the run date, a setting, a scenario or your work, and copy the new link. The engine computes the run when asked (5–15 s the first time).</p></section>`;}
const DEFAULT_TABLE='accounts';

export function installDataPage({getClient,getEngineState=()=>({state:'idle',towns:[]}),toast=()=>{},onDate=null,onShowPremise=()=>{},onOpenRecord=()=>{},storage=globalThis.localStorage,root=document.getElementById('data-root')}){
 const ui={table:null,page:1,pageSize:100,sort:null,desc:false,search:'',filters:{},hidden:new Set(),catalog:null,data:null,busy:false,error:'',counts:{},csv:null,connect:false,link:null,linkBusy:false,linkError:''};
 let closePops=null,searchTimer=null;
 const client=()=>getClient?.()||null;
 const spec=()=>ui.catalog?.groups.flatMap(g=>g.tables.map(t=>({...t,groupTitle:g.title}))).find(t=>t.name===ui.table)||null;
 const query=()=>({table:ui.table,page:ui.page,pageSize:ui.pageSize,...(ui.sort?{sort:ui.sort,desc:ui.desc}:{}),...(ui.search?{search:ui.search}:{}),...(Object.keys(ui.filters).length?{filters:ui.filters}:{})});
 const selection=()=>{const {page,pageSize,...q}=query();const cols=ui.data?.columns?.map(c=>c.key).filter(k=>!ui.hidden.has(k));return ui.hidden.size&&cols?.length?{...q,columns:cols}:q;};
 async function loadLink(){const m=client();if(!m||!ui.connect||!ui.data)return;const want=JSON.stringify(selection());ui.linkBusy=true;ui.linkError='';render();
  try{const link=await m.tableLink(selection());if(JSON.stringify(selection())!==want)return;ui.link={...link,key:want};}catch(err){ui.linkError=err.message;}finally{ui.linkBusy=false;render();}}
 function go(table){const h=dataHash(table);if(location.hash!==h)location.hash=h;else open(h);}
 // ---- loading --------------------------------------------------------------------------------------------------
 async function loadCatalog(){const m=client();if(!m||ui.catalog)return;try{ui.catalog=await m.tables();}catch(err){ui.error=err.message;}}
 async function load(){const m=client();if(!m||!ui.table)return;ui.busy=true;ui.error='';render();
  try{const data=await m.table(query());if(data.table!==ui.table)return;ui.data=data;ui.counts[data.table]=data.rowsInTable;ui.busy=false;render();if(ui.connect&&ui.link?.key!==JSON.stringify(selection()))loadLink();}
  catch(err){if(err.superseded)return;ui.busy=false;ui.error=err.status===404?`The engine has no table "${ui.table}".`:err.message;render();}}
 function reset(table){ui.link=null;ui.table=table;ui.page=1;ui.sort=null;ui.desc=false;ui.search='';ui.filters={};ui.data=null;ui.error='';ui.hidden=loadHidden(storage,table);}
 const known=name=>!ui.catalog||ui.catalog.groups.some(g=>g.tables.some(t=>t.name===name));
 async function open(hash){const r=parseDataRoute(hash);await loadCatalog();const table=r.table&&known(r.table)?r.table:DEFAULT_TABLE;
  if(table!==ui.table)reset(table);if(!r.table||r.table!==table){const h=dataHash(table);if(location.hash!==h){location.hash=h;return;}}
  render();load();}
 // ---- CSV ------------------------------------------------------------------------------------------------------
 async function downloadCsv(){const m=client(),d=ui.data;if(!m||!d||ui.csv)return;const total=d.total,pages=pageCount(total,CSV_PAGE),texts=[];ui.csv={done:0,pages};render();
  try{for(let p=1;p<=pages;p++){texts.push(await m.tableCsv({...query(),page:p,pageSize:CSV_PAGE}));ui.csv.done=p;render();}
   const blob=new Blob([stitchCsv(texts)],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=csvName(m.townRef,d.table,d.asOf);document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),4000);
   toast(`Downloaded ${INT.format(total)} row${total===1?'':'s'} of ${d.title} as ${a.download}.`);}
  catch(err){toast('Download failed. '+err.message);}
  finally{ui.csv=null;render();}}
 // ---- rendering ------------------------------------------------------------------------------------------------
 function sidebar(){const cat=ui.catalog;if(!cat)return '';
  const count=t=>ui.counts[t.name]!=null?`<span class="data-count">${INT.format(ui.counts[t.name])}</span>`:'';
  return `<aside class="data-side" aria-label="Tables"><h1>Data</h1><p class="small-note">${client()?.readOnly?'Archived tables at the saved run date. Click a column to sort, or use the filters to select rows.':'Every table of this town and its run, as the engine holds it on the run date. Click a column to sort, a linked value to open its record.'}</p><select class="data-table-select" id="data-table-select" aria-label="Table">${cat.groups.map(g=>`<optgroup label="${e(g.title)}">${g.tables.map(t=>`<option value="${e(t.name)}"${t.name===ui.table?' selected':''}>${e(t.title)}</option>`).join('')}</optgroup>`).join('')}</select><nav class="data-nav" id="data-nav">${cat.groups.map(g=>`<h2>${e(g.title)}</h2>${g.tables.map(t=>`<button type="button" data-table="${e(t.name)}" class="${t.name===ui.table?'is-active':''}" aria-current="${t.name===ui.table?'page':'false'}">${e(t.title)}${count(t)}</button>`).join('')}`).join('')}</nav></aside>`;}
 function head(s){const m=client(),d=ui.data,asOf=d?.asOf||m?.asOf||'';
  return `<header class="data-head"><div><span class="section-kicker">${e((s?.groupTitle||'').toUpperCase())} · ${e(sourceLabel(s?.source).toUpperCase())}</span><h2 class="has-pop">${e(s?.title||ui.table||'Data')}<button type="button" class="schema-info" aria-label="About this table" aria-expanded="false" title="About this table">i</button><div class="schema-pop" role="note"><p>${e(s?.description||'')}</p><p>${e(sourceLabel(s?.source))}${d?` · ${INT.format(d.rowsInTable)} rows as of ${e(d.asOf)}`:''}. Facet counts cover the whole table; the search looks in ids, names and addresses. The CSV carries every row of the current filter, in pages of ${INT.format(CSV_PAGE)}.</p></div></h2></div><div class="data-tools"><label>Run date <input type="date" id="data-asof" min="${activeYear(m)}-01-01" max="${activeYear(m)}-12-31" value="${e(asOf)}"></label><button type="button" id="data-csv" class="outline-btn" data-icon="download"${!d||!d.total||ui.csv?' disabled':''}>${ui.csv?`Downloading ${ui.csv.done}/${ui.csv.pages}…`:'Download CSV'}</button>${m?.readOnly?'':`<button type="button" id="data-connect" class="outline-btn" aria-expanded="${ui.connect}" aria-controls="data-connect-panel"${!d?' disabled':''}>Connect</button>`}</div></header>`;}
 function connectPanel(){if(!ui.connect)return '';const m=client(),d=ui.data,s=spec();
  if(ui.linkError)return `<section class="data-connect" id="data-connect-panel"><p class="data-error">${e(ui.linkError)}</p><button type="button" class="small-link" id="connect-close">Close</button></section>`;
  if(!ui.link||ui.link.key!==JSON.stringify(selection()))return `<section class="data-connect" id="data-connect-panel"><p class="small-note" role="status">${ui.linkBusy?'Making the links…':''}</p></section>`;
  return `<div id="data-connect-panel">${connectMarkup(ui.link,{apiBase:m?.api,title:s?.title||d?.title,asOf:d?.asOf,columns:d?.columns||[],body:m?.requestBody?m.requestBody(selection()):null})}</div>`;}
 function controls(){const d=ui.data,cols=d?.columns||[];const set=Object.keys(ui.filters).length||ui.search;
  return `<div class="data-controls"><input type="search" id="data-search" placeholder="Find an id, name or address" aria-label="Find" value="${e(ui.search)}">${d?facetMarkup(cols,d.facets,ui.filters):''}${set?'<button type="button" class="small-link" id="data-clear">Clear filters</button>':''}${cols.length?`<details class="data-columns"><summary>Columns${ui.hidden.size?` · ${cols.length-ui.hidden.size}/${cols.length}`:''}</summary><div class="data-columns-body">${cols.map(c=>`<label><input type="checkbox" data-col="${e(c.key)}"${ui.hidden.has(c.key)?'':' checked'}> ${e(c.label)}</label>`).join('')}<button type="button" class="small-link" id="data-cols-all">Show all</button></div></details>`:''}</div>`;}
 function status(){const d=ui.data;if(ui.error)return `<p class="data-status" role="status"><span class="data-error">${e(ui.error)}</span></p>`;if(!d)return `<p class="data-status" role="status">${ui.busy?(client()?.readOnly?'Loading saved table…':'Asking the engine… (a cold engine replays the year first, 5–15 s)'):''}</p>`;
  const filtered=d.total!==d.rowsInTable;return `<p class="data-status" role="status">${ui.busy?'Updating… ':''}${client()?.readOnly?'Saved results':'Engine data'} as of ${e(d.asOf)} · ${INT.format(d.rowsInTable)} row${d.rowsInTable===1?'':'s'}${filtered?` · ${INT.format(d.total)} match the filter`:''}${d.sort?` · sorted by ${e(d.columns.find(c=>c.key===d.sort)?.label||d.sort)} ${d.desc?'descending':'ascending'}`:''}</p>`;}
 function cell(v,c,row,cols){const cls=`k-${c.kind}${v==null||v===''?' is-empty':''}`;const t=client()?.readOnly?null:linkTarget(c,v,row,cols);
  if(t)return `<td class="${cls}"><button type="button" class="data-link" data-link="${e(c.key)}">${e(String(v))}</button></td>`;
  if(c.kind==='bool'&&v!=null)return `<td class="${cls}"><span class="${v?'data-bool-yes':''}">${fmtCell(v,c)}</span></td>`;return `<td class="${cls}">${e(fmtCell(v,c))}</td>`;}
 function table(){const d=ui.data;if(!d)return `<div class="data-table"><div class="data-empty">${ui.busy?'':'No data yet.'}</div></div>`;
  const vis=d.columns.map((c,i)=>[c,i]).filter(([c])=>!ui.hidden.has(c.key)),first=(d.page-1)*d.pageSize;
  if(!d.rows.length)return `<div class="data-table"><div class="data-empty">${d.rowsInTable?'No rows match this filter.':'Nothing here yet on this run date.'}</div></div>`;
  return `<div class="data-table" role="region" aria-label="${e(d.title)}" tabindex="0"><table><thead><tr><th class="data-rowno"></th>${vis.map(([c])=>`<th class="k-${c.kind}${d.sort===c.key?' is-sorted':''}" aria-sort="${d.sort===c.key?(d.desc?'descending':'ascending'):'none'}"><button type="button" data-sort="${e(c.key)}" title="Sort by ${e(c.label)}">${e(c.label)}${c.unit?` <span class="data-unit">${e(c.unit)}</span>`:''}${d.sort===c.key?(d.desc?' ↓':' ↑'):''}</button></th>`).join('')}</tr></thead><tbody>${d.rows.map((r,k)=>`<tr data-row="${k}"><td class="data-rowno">${INT.format(first+k+1)}</td>${vis.map(([c,i])=>cell(r[i],c,r,d.columns)).join('')}</tr>`).join('')}</tbody></table></div>`;}
 function pager(){const d=ui.data;if(!d)return '';const pages=pageCount(d.total,d.pageSize),a=d.total?(d.page-1)*d.pageSize+1:0,b=Math.min(d.total,d.page*d.pageSize);
  return `<footer class="data-pager"><span>Rows ${INT.format(a)}–${INT.format(b)} of ${INT.format(d.total)}</span><span class="spacer"></span><label>Rows per page <select id="data-size" aria-label="Rows per page">${PAGE_SIZES.map(n=>`<option value="${n}"${n===ui.pageSize?' selected':''}>${n}</option>`).join('')}</select></label><button type="button" class="small-link" data-page="-1"${d.page<=1?' disabled':''}>Previous</button><span>Page ${INT.format(d.page)} of ${INT.format(pages)}</span><button type="button" class="small-link" data-page="1"${d.page>=pages?' disabled':''}>Next</button></footer>`;}
 function render(){if(!root)return;const m=client();const search=root.querySelector('#data-search'),focused=document.activeElement===search,pos=search?.selectionStart;
  if(!m){root.innerHTML=`<section class="fiori-shell"><div class="fiori-empty ws-empty">${engineNotice(getEngineState(),undefined,'#/data','Data')}</div></section>`;root.querySelector('[data-ws="retry"]')?.addEventListener('click',()=>location.reload());return;}
  const s=spec();root.innerHTML=`<div class="data-layout">${sidebar()}<main class="data-main">${head(s)}${connectPanel()}${controls()}${status()}${table()}${pager()}</main></div>`;
  if(m.readOnly)root.querySelector('#data-asof').disabled=true;
  closePops?.();closePops=bindPopovers(root);if(focused){const el=root.querySelector('#data-search');el?.focus();try{el?.setSelectionRange(pos,pos);}catch{}}}
 // ---- events ---------------------------------------------------------------------------------------------------
 root?.addEventListener('click',ev=>{const b=ev.target.closest('button');if(!b||!root.contains(b))return;
  if(b.dataset.table){go(b.dataset.table);return;}
  if(b.dataset.sort){const k=b.dataset.sort;if(ui.sort===k){if(ui.desc){ui.sort=null;ui.desc=false;}else ui.desc=true;}else{ui.sort=k;ui.desc=false;}ui.page=1;load();return;}
  if(b.dataset.page){ui.page=Math.max(1,ui.page+Number(b.dataset.page));load();return;}
  if(b.id==='data-clear'){ui.filters={};ui.search='';ui.page=1;load();return;}
  if(b.id==='data-csv'){downloadCsv();return;}
  if(b.id==='data-connect'){ui.connect=!ui.connect;render();if(ui.connect)loadLink();return;}
  if(b.id==='connect-close'){ui.connect=false;render();root.querySelector('#data-connect')?.focus();return;}
  if(b.dataset.copy){const el=root.querySelector('#'+b.dataset.copy);if(!el)return;const text=el.value;const done=()=>toast('Copied to the clipboard.');
   (navigator.clipboard?.writeText?navigator.clipboard.writeText(text):Promise.reject()).then(done,()=>{el.select();try{document.execCommand('copy');done();}catch{toast('Select the text and copy it.');}});return;}
  if(b.id==='data-cols-all'){ui.hidden=new Set();saveHidden(storage,ui.table,ui.hidden);render();return;}
  if(b.dataset.link){const tr=b.closest('tr'),d=ui.data,row=d?.rows[Number(tr?.dataset.row)],c=d?.columns.find(x=>x.key===b.dataset.link),t=linkTarget(c,b.textContent,row,d?.columns);if(!t)return;
   if(t.hash){location.hash=t.hash;return;}if(t.kind==='premise'){onShowPremise(t.id);return;}onOpenRecord(t.kind,t.id);}});
 root?.addEventListener('change',ev=>{const el=ev.target;
  if(el.id==='data-table-select'){go(el.value);return;}
  if(el.dataset.facet){const k=el.dataset.facet;if(el.value==='*')delete ui.filters[k];else ui.filters[k]=el.value;ui.page=1;load();return;}
  if(el.id==='data-size'){ui.pageSize=Number(el.value);ui.page=1;load();return;}
  if(el.id==='data-asof'){const day=el.value;if(!day)return;const m=client();if(m&&dayYear(day)!==activeYear(m)){toast(`Choose a date in ${activeYear(m)}.`);render();return;}Promise.resolve(onDate?onDate(day):null).then(()=>{if(m&&m.asOf!==day)m.setAsOf(day);ui.page=1;load();});return;}
  if(el.dataset.col){if(el.checked)ui.hidden.delete(el.dataset.col);else ui.hidden.add(el.dataset.col);saveHidden(storage,ui.table,ui.hidden);render();}});
 root?.addEventListener('input',ev=>{if(ev.target.id!=='data-search')return;const v=ev.target.value;clearTimeout(searchTimer);searchTimer=setTimeout(()=>{if(v.trim()===ui.search)return;ui.search=v.trim();ui.page=1;load();},250);});
 root?.addEventListener('keydown',ev=>{if(ev.key==='Enter'&&ev.target.id==='data-search'){clearTimeout(searchTimer);ui.search=ev.target.value.trim();ui.page=1;load();}});
 return {open,render,refresh(){if(/^#\/data/.test(location.hash)){if(client()&&!ui.catalog)open(location.hash);else render();}},get state(){return ui;}};
}
