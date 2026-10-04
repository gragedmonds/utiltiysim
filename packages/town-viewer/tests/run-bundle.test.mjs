import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {gzipSync} from 'node:zlib';
import {RunBundle,SavedM2C,validateManifest,safeName,checkedJSON,selectSavedTable} from '../dist/run-bundle.js';
import {filterWorklist,overviewMarkup} from '../dist/runs.js';

function fixture(){
 const data={
  'inputs.json':{town:'town-1',episodes:[],actions:[],settings:{},seed:'s'},
  'aggregates.json':{schemaVersion:'run-aggregates/1.0',runKey:'a'.repeat(64),asOf:'2026-01-31',towns:[{summary:{kpis:{reads:10,casesOpen:2,costs:{total:5},carry:3}}}]},
  'trend.json':{asOf:'2026-01-31',months:[]},'scorecard.json':{asOf:'2026-01-31'},
  'tables/catalog.json':{groups:[]},
  'tables/accounts.json.gz':{schemaVersion:'run-table/1.0',table:'accounts',asOf:'2026-01-31',columns:[{key:'id',kind:'id'},{key:'name',kind:'text'},{key:'amount',kind:'money'},{key:'active',kind:'bool',facet:true}],searchColumns:[0,1],facets:{},rows:[['A','O\'Connor, Jr',2,true],['B','Quote "two"',null,false],['C','Other',7,null]]},
  'worklists/2026-01-31.json.gz':{asOf:'2026-01-31',rows:[]},'summaries/2026-01-31.json':{kpis:{casesOpen:0}}
 };
 const bytes=new Map(Object.entries(data).map(([name,value])=>[name,name.endsWith('.gz')?gzipSync(JSON.stringify(value)):Buffer.from(JSON.stringify(value))]));
 const manifest={schemaVersion:'run-manifest/1.0',runKey:'a'.repeat(64),engineVersion:'0.9.0',engineBuild:'b'.repeat(64),asOf:'2026-01-31',inputs:data['inputs.json'],towns:[{id:'town-1',name:'<Town>',accounts:3,registers:4}],worklistDates:['2026-01-31'],files:[...bytes].map(([name,b])=>({name,bytes:b.length,sha256:createHash('sha256').update(b).digest('hex')}))};
 return {data,bytes,manifest};
}

test('a local folder reads all detail files without fetch; CSV quotes text and keeps empty cells',async()=>{
 const {bytes,manifest}=fixture(),files=[{name:'manifest.json',webkitRelativePath:'archive/manifest.json',size:2000,text:async()=>JSON.stringify(manifest)},...[...bytes].map(([name,b])=>({name:name.split('/').at(-1),webkitRelativePath:'archive/'+name,size:b.length,arrayBuffer:async()=>b}))];
 const bundle=await RunBundle.fromFiles(files),client=new SavedM2C(bundle);
 const result=await client.table({table:'accounts',sort:'amount',desc:true,pageSize:2});assert.deepEqual(result.rows.map(r=>r[0]),['C','A']);assert.equal(result.total,3);
 assert.equal(await client.tableCsv({table:'accounts'}),'id,name,amount,active\nA,"O\'Connor, Jr",2,true\nB,"Quote ""two""",,false\nC,Other,7,\n');
 assert.equal(await bundle.verify(),manifest.files.length);assert.throws(()=>client.act(),/live engine/);assert.throws(()=>client.setAsOf('2026-02-01'),/read-only/);
 const before=await bundle.read('trend.json');before.months.push(1);assert.deepEqual((await bundle.read('trend.json')).months,[],'callers cannot mutate cached data');
});

test('missing details and a corrupt compressed file give explicit errors',async()=>{
 const {bytes,manifest}=fixture();const bundle=new RunBundle(manifest,name=>bytes.get(name));
 await assert.rejects(bundle.read('not-exported.json'),/no saved detail/);
 const entry=manifest.files.find(f=>f.name==='tables/accounts.json.gz');
 const corrupt=Buffer.from(bytes.get(entry.name));corrupt[10]^=1;
 await assert.rejects(checkedJSON(corrupt,entry),/checksum mismatch/);
 await assert.rejects(checkedJSON(corrupt.subarray(1),entry),/size mismatch/);
 const files=[{name:'manifest.json',size:1000,text:async()=>JSON.stringify(manifest)}];const incomplete=await RunBundle.fromFiles(files);
 await assert.rejects(incomplete.read('trend.json'),/Missing saved detail/);
 await assert.rejects(RunBundle.fromFiles([...files,...files]),/exactly one manifest/);
});

test('manifest rejects traversal, duplicate files, unsafe URLs and unsupported versions',async()=>{
 const {manifest}=fixture();for(const name of ['../x','a/../b','a\\b','/absolute','a//b','https://x','x?q=1'])assert.equal(safeName(name),false,name);
 assert.throws(()=>validateManifest({...manifest,schemaVersion:'run-manifest/2.0'}),/Unsupported/);
 assert.throws(()=>validateManifest({...manifest,asOf:'2026-02-30'}),/Invalid saved run dates/);
 assert.throws(()=>validateManifest({...manifest,files:[...manifest.files,manifest.files[0]]}),/Invalid bundle file/);
 assert.throws(()=>validateManifest({...manifest,files:manifest.files.filter(f=>f.name!=='trend.json')}),/Missing bundle file/);
 await assert.rejects(RunBundle.fromURL('file:///tmp/archive'),/HTTP or HTTPS/);
});

test('late table responses and errors cannot overwrite a newer saved selection',async()=>{
 const {manifest,data}=fixture(),pending=[];
 const client=new SavedM2C({manifest,read:()=>new Promise((resolve,reject)=>pending.push({resolve,reject}))});
 const old=client.table({table:'accounts',search:'Other'});const dropped=assert.rejects(old,err=>err.superseded===true);
 const latest=client.table({table:'accounts',search:"o'connor"});pending[1].resolve(data['tables/accounts.json.gz']);
 assert.deepEqual((await latest).rows.map(r=>r[0]),['A']);pending[0].resolve(data['tables/accounts.json.gz']);await dropped;
 const failed=client.table({table:'accounts'});const ignored=assert.rejects(failed,err=>err.superseded===true);
 const current=client.table({table:'accounts'});pending[3].resolve(data['tables/accounts.json.gz']);await current;
 pending[2].reject(Error('late failure'));await ignored;
});

test('HTTP folder loading only requests saved files; URL errors and checksums remain visible',async()=>{
 const {bytes,manifest}=fixture(),requests=[];
 const bundle=await RunBundle.fromURL('https://example.test/runs/run',{fetchImpl:async url=>{requests.push(url.href);const name=url.pathname.split('/run/')[1],raw=name==='manifest.json'?Buffer.from(JSON.stringify(manifest)):bytes.get(name);return {ok:!!raw,status:raw?200:404,arrayBuffer:async()=>raw};}});
 assert.deepEqual(await bundle.read('scorecard.json'),{asOf:'2026-01-31'});assert.deepEqual(requests,['https://example.test/runs/run/manifest.json','https://example.test/runs/run/scorecard.json']);
 const absent=await RunBundle.fromURL('https://example.test/runs/run',{fetchImpl:async url=>({ok:url.pathname.endsWith('manifest.json'),status:404,arrayBuffer:async()=>Buffer.from(JSON.stringify(manifest))})});
 await assert.rejects(absent.read('trend.json'),/unavailable \(404\)/);
});

test('saved table selection keeps nulls last, supports blank facets and refuses unknown columns',()=>{
 const table=fixture().data['tables/accounts.json.gz'];
 assert.deepEqual(selectSavedTable(table,{filters:{active:'null'}}).map(r=>r[0]),['C']);
 assert.deepEqual(selectSavedTable(table,{filters:{amount:'1..5'}}).map(r=>r[0]),['A']);
 assert.deepEqual(selectSavedTable(table,{search:"o'connor"}).map(r=>r[0]),['A']);
 assert.deepEqual(selectSavedTable(table,{sort:'amount',desc:true}).map(r=>r[0]),['C','A','B']);
 assert.throws(()=>selectSavedTable(table,{sort:'unknown'}),/Unknown sort/);assert.throws(()=>selectSavedTable(table,{filters:{unknown:'a'}}),/Unknown filter/);
});

test('saved overview escapes supplied names and workspace selects only matching archived rows',()=>{
 const {manifest,data}=fixture();assert.match(overviewMarkup(manifest,data['aggregates.json']),/&lt;Town&gt;/);
 const rows=[{caseId:'C1',queue:'FIELD',address:'One'},{caseId:'C2',queue:'BILLING',address:'Two'}];
 assert.deepEqual(filterWorklist(rows,{queue:'FIELD',search:'one'}),[rows[0]]);assert.deepEqual(filterWorklist(rows,{queue:'FIELD',search:'two'}),[]);
});

test('a saved run of a later year (2027-2030) opens with its year; dates outside 2026-2030 are refused',()=>{
 const {manifest}=fixture(),dated=(d,inputs=manifest.inputs)=>({...manifest,asOf:d,worklistDates:[d],inputs,files:manifest.files.map(f=>({...f,name:f.name.replace('2026-01-31',d)}))});
 const later=dated('2027-03-31',{...manifest.inputs,year:2027,previous:[{actions:[]}]});assert.equal(validateManifest(later).asOf,'2027-03-31');
 const client=new SavedM2C(new RunBundle(later,()=>null));assert.equal(client.year,2027);assert.deepEqual(client.years,[2027]);assert.equal(client.yearStart(),'2027-01-01');assert.equal(client.yearEnd(),'2027-12-31');assert.equal(client.isClosed(),false);assert.equal(client.canContinue(),false);
 assert.equal(new SavedM2C(new RunBundle(dated('2030-12-31'),()=>null)).year,2030,'no year in its inputs: the saved date\'s');assert.equal(new SavedM2C(new RunBundle(manifest,()=>null)).year,2026);
 assert.equal(validateManifest(dated('2028-02-29')).asOf,'2028-02-29');
 for(const d of ['2025-12-31','2031-01-01','2027-02-29'])assert.throws(()=>validateManifest(dated(d)),/Invalid saved run dates/,d);
});
