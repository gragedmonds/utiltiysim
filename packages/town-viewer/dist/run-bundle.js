// Saved engine outputs. This client only selects rows and formats CSV; it never replays a run.
export const MANIFEST_VERSION='run-manifest/1.0';
const MAX_FILE=256*1024*1024;
const copy=value=>structuredClone(value);
// A saved run is of one year, 2026-2030 (a later year's bundle keeps `year` and `previous` in its inputs).
const savedDate=date=>typeof date==='string'&&/^20(2[6-9]|30)-\d{2}-\d{2}$/.test(date)&&!Number.isNaN(Date.parse(date))&&new Date(date).toISOString().slice(0,10)===date;
const superseded=()=>Object.assign(Error('superseded'),{superseded:true});
export const savedText=v=>v==null?'':typeof v==='boolean'?(v?'true':'false'):String(v);
export function safeName(name){return typeof name==='string'&&name.length>0&&!name.includes('\\')&&!name.startsWith('/')&&!name.split('/').some(p=>!p||p==='.'||p==='..')&&!/[?#:]/.test(name);}
export function validateManifest(m){
 if(m?.schemaVersion!==MANIFEST_VERSION)throw Error('Unsupported run bundle. Expected '+MANIFEST_VERSION+'.');
 if(!/^[a-f0-9]{64}$/.test(m.runKey)||!m.inputs||!Array.isArray(m.files)||!Array.isArray(m.towns)||!m.towns.length)throw Error('Incomplete run manifest.');
 if(!savedDate(m.asOf)||!Array.isArray(m.worklistDates)||!m.worklistDates.includes(m.asOf))throw Error('Invalid saved run dates.');
 const names=new Set();for(const f of m.files){if(!safeName(f.name)||names.has(f.name)||!Number.isSafeInteger(f.bytes)||f.bytes<0||f.bytes>MAX_FILE||!/^[a-f0-9]{64}$/.test(f.sha256))throw Error('Invalid bundle file: '+f.name);names.add(f.name);}
 for(const name of ['inputs.json','aggregates.json','trend.json','scorecard.json','tables/catalog.json'])if(!names.has(name))throw Error('Missing bundle file: '+name);
 for(const date of m.worklistDates)if(!savedDate(date)||date>m.asOf||!names.has('worklists/'+date+'.json.gz')||!names.has('summaries/'+date+'.json'))throw Error('Invalid worklist snapshot: '+date);
 return m;
}
export async function checkedJSON(bytes,entry){
 const raw=bytes instanceof Uint8Array?bytes:new Uint8Array(bytes);
 if(raw.byteLength!==entry.bytes)throw Error('Bundle size mismatch: '+entry.name);
 const crypto=globalThis.crypto;if(!crypto?.subtle)throw Error('Run integrity checks require HTTPS or localhost.');
 const digest=await crypto.subtle.digest('SHA-256',raw),sha=Array.from(new Uint8Array(digest),n=>n.toString(16).padStart(2,'0')).join('');
 if(sha!==entry.sha256)throw Error('Bundle checksum mismatch: '+entry.name);
 const blob=new Blob([raw]);const text=entry.name.endsWith('.gz')?await new Response(blob.stream().pipeThrough(new DecompressionStream('gzip'))).text():await blob.text();
 if(text.length>MAX_FILE)throw Error('Expanded bundle file exceeds the reader limit: '+entry.name);
 return JSON.parse(text);
}
export class RunBundle{
 constructor(manifest,readBytes){this.manifest=validateManifest(copy(manifest));this.readBytes=readBytes;this.cache=new Map();this.entries=new Map(this.manifest.files.map(f=>[f.name,f]));}
 static async fromURL(base,{fetchImpl=globalThis.fetch,origin=globalThis.location?.href}={}){
  const url=new URL(base,origin);if(!['http:','https:'].includes(url.protocol))throw Error('Use an HTTP or HTTPS bundle folder URL.');
  url.search='';url.hash='';if(!url.pathname.endsWith('/'))url.pathname+='/';
  const get=async name=>{const r=await fetchImpl(new URL(name,url));if(!r.ok)throw Error('Bundle file unavailable ('+r.status+'): '+name);const bytes=new Uint8Array(await r.arrayBuffer());if(bytes.length>MAX_FILE)throw Error('Bundle file is too large: '+name);return bytes;};
  const manifest=JSON.parse(new TextDecoder().decode(await get('manifest.json')));return new RunBundle(manifest,get);
 }
 static async fromFiles(files){
  const list=Array.from(files),manifests=list.filter(f=>(f.webkitRelativePath||f.name).split('/').at(-1)==='manifest.json');
  if(manifests.length!==1)throw Error('Choose one run folder containing exactly one manifest.json.');
  const file=manifests[0],full=file.webkitRelativePath||file.name,prefix=full.slice(0,-'manifest.json'.length);
  if(file.size>1024*1024)throw Error('Run manifest is too large.');
  const byName=new Map();for(const f of list){const p=f.webkitRelativePath||f.name;if(p.startsWith(prefix)){const rel=p.slice(prefix.length);if(byName.has(rel))throw Error('Duplicate bundle file: '+rel);byName.set(rel,f);}}
  return new RunBundle(JSON.parse(await file.text()),async name=>{const f=byName.get(name);if(!f)throw Error('Missing saved detail: '+name+'. Choose the complete run folder.');if(f.size>MAX_FILE)throw Error('Bundle file is too large: '+name);return new Uint8Array(await f.arrayBuffer());});
 }
 async read(name){
  const entry=this.entries.get(name);if(!entry)throw Error('This run has no saved detail: '+name);
  if(!this.cache.has(name)){const promise=Promise.resolve(this.readBytes(name)).then(bytes=>checkedJSON(bytes,entry)).catch(err=>{this.cache.delete(name);throw err;});this.cache.set(name,promise);if(this.cache.size>8)this.cache.delete(this.cache.keys().next().value);}
  return copy(await this.cache.get(name));
 }
 async verify(){for(const entry of this.entries.values())await checkedJSON(await this.readBytes(entry.name),entry);return this.entries.size;}
}
function matcher(col,want){
 want=String(want).trim();const numeric=['int','num','money','pct'].includes(col.kind);
 if(numeric&&want.includes('..')){const [lo,hi]=want.split('..'),a=lo.trim()?Number(lo):-Infinity,b=hi.trim()?Number(hi):Infinity;if(Number.isNaN(a)||Number.isNaN(b))throw Error('Invalid numeric range.');return v=>v!=null&&Number.isFinite(Number(v))&&Number(v)>=a&&Number(v)<=b;}
 if(['date','datetime'].includes(col.kind))return v=>want?savedText(v).startsWith(want):v==null;
 if(col.facet||numeric||['bool','id'].includes(col.kind))return v=>['','null','—'].includes(want)?v==null||v==='':savedText(v)===want;
 return v=>savedText(v).toLowerCase().includes(want.toLowerCase());
}
export function selectSavedTable(table,{search='',filters={},sort=null,desc=false}={}){
 const columns=table.columns,byKey=new Map(columns.map((c,i)=>[c.key,i])),tests=Object.entries(filters).map(([key,want])=>{if(!byKey.has(key))throw Error('Unknown filter column: '+key);const j=byKey.get(key);return [j,matcher(columns[j],want)];});
 const needle=search.trim().toLowerCase(),searchColumns=table.searchColumns||[];
 let rows=table.rows.filter(row=>(!needle||searchColumns.map(j=>savedText(row[j])).join(' ').toLowerCase().includes(needle))&&tests.every(([j,ok])=>ok(row[j])));
 if(sort){if(!byKey.has(sort))throw Error('Unknown sort column: '+sort);const j=byKey.get(sort),kind=columns[j].kind,numeric=['int','num','money','pct','bool'].includes(kind);
  rows=rows.slice().sort((a,b)=>{const x=a[j],y=b[j];if(x==null)return y==null?0:1;if(y==null)return -1;const xx=numeric?Number(x):savedText(x).toLowerCase(),yy=numeric?Number(y):savedText(y).toLowerCase();return (xx<yy?-1:xx>yy?1:0)*(desc?-1:1);});}
 return rows;
}
const csvCell=v=>{const s=savedText(v);return /[",\n\r]/.test(s)?'"'+s.replaceAll('"','""')+'"':s;};
export class SavedM2C{
 constructor(bundle){this.bundle=bundle;this.tableTicket=0;this.readOnly=true;this.asOf=bundle.manifest.asOf;this.year=Number(bundle.manifest.inputs.year)||Number(this.asOf.slice(0,4));this.years=[this.year];this.lastYear=this.year;this.townRef=bundle.manifest.inputs.town;this.townId=this.townRef;this.episodes=copy(bundle.manifest.inputs.episodes||[]);this.actions=copy(bundle.manifest.inputs.actions||[]);this.seed=bundle.manifest.inputs.seed;this.settings=copy(bundle.manifest.inputs.settings);}
 tables(){return this.bundle.read('tables/catalog.json');}
 trend(){return this.bundle.read('trend.json');}
 scorecard(){return this.bundle.read('scorecard.json');}
 scenarios(){return Promise.resolve({scenarios:[],groups:[],coming:[]});}
 async summary(date=this.asOf){return this.bundle.read('summaries/'+date+'.json');}
 async worklist(date=this.asOf){return this.bundle.read('worklists/'+date+'.json.gz');}
 async table(params){
  const ticket=++this.tableTicket;
  if(params.asOf&&params.asOf!==this.asOf)throw Error('Tables are saved as of '+this.asOf+'.');
  let table;try{table=await this.bundle.read('tables/'+params.table+'.json.gz');}catch(err){if(ticket!==this.tableTicket)throw superseded();throw err;}if(ticket!==this.tableTicket)throw superseded();
  if(table.schemaVersion!=='run-table/1.0'||table.asOf!==this.asOf||table.table!==params.table||!Array.isArray(table.rows)||!Array.isArray(table.columns)||table.rows.some(r=>r.length!==table.columns.length))throw Error('Invalid saved table: '+params.table);
  const rows=selectSavedTable(table,params),page=Math.max(1,params.page||1),size=Math.min(500,Math.max(1,params.pageSize||100));
  return {...table,schemaVersion:'m2c-table/1.0',rows:rows.slice((page-1)*size,page*size),rowsInTable:table.rows.length,total:rows.length,page,pageSize:size,sort:params.sort||null,desc:!!params.desc,search:params.search||'',filters:params.filters||{}};
 }
 async tableCsv(params){const table=await this.bundle.read('tables/'+params.table+'.json.gz'),rows=selectSavedTable(table,params),page=Math.max(1,params.page||1),size=Math.min(5000,Math.max(1,params.pageSize||5000));return [table.columns.map(c=>csvCell(c.key)).join(','),...rows.slice((page-1)*size,page*size).map(r=>r.map(v=>csvCell(v)).join(','))].join('\n')+'\n';}
 canAct(){return false;}
 yearStart(){return this.year+'-01-01';}
 yearEnd(){return this.year+'-12-31';}
 isClosed(){return false;}
 canContinue(){return false;}
 setAsOf(){throw Error('This archive is read-only; its tables are saved as of '+this.asOf+'.');}
 act(){throw Error('Open a live engine to change this run.');}
 export(){return copy(this.bundle.manifest.inputs);}
}
