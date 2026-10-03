import test from 'node:test';
import assert from 'node:assert/strict';
import {parseDataRoute,dataHash,fmtCell,linkTarget,invoiceAccount,stitchCsv,pageCount,csvName,loadHidden,saveHidden,facetMarkup,sourceLabel,INLINE_FACETS,CSV_PAGE} from '../dist/data-page.js';
import {EngineM2C} from '../dist/m2c.js';

test('data routes name a table and round-trip',()=>{
 assert.deepEqual(parseDataRoute('#/data'),{table:null});assert.deepEqual(parseDataRoute('#/data/reads'),{table:'reads'});
 assert.deepEqual(parseDataRoute('#/data/billingDocuments'),{table:'billingDocuments'});assert.deepEqual(parseDataRoute('#/workspace'),{table:null});
 assert.equal(dataHash('invoices'),'#/data/invoices');assert.equal(dataHash(null),'#/data');assert.equal(parseDataRoute(dataHash('collectionsAccounts')).table,'collectionsAccounts');
});

test('cells format by kind and show a dash when empty',()=>{
 assert.equal(fmtCell(null,{kind:'money'}),'—');assert.equal(fmtCell('',{kind:'text'}),'—');
 assert.equal(fmtCell(1234.5,{kind:'money'}),'$1,234.50');assert.equal(fmtCell(-12,{kind:'money'}),'-$12.00');
 assert.equal(fmtCell(45149,{kind:'int'}),'45,149');assert.equal(fmtCell(1064.2714,{kind:'num'}),'1,064.271');
 assert.equal(fmtCell(0.63,{kind:'pct'}),'63%');assert.equal(fmtCell(true,{kind:'bool'}),'Yes');assert.equal(fmtCell(false,{kind:'bool'}),'No');
 assert.equal(fmtCell('2026-08-05',{kind:'date'}),'2026-08-05');assert.equal(fmtCell('CA-P-00001',{kind:'id'}),'CA-P-00001');
});

test('linked cells open the record behind them',()=>{
 const cols=[{key:'invoiceId',link:'invoice'},{key:'accountId',link:'account'}];
 assert.deepEqual(linkTarget({link:'premise'},'P-00041'),{kind:'premise',id:'P-00041'});
 assert.deepEqual(linkTarget({link:'installation'},'IN-P-00041-electric'),{kind:'installation',id:'IN-P-00041-electric'});
 assert.deepEqual(linkTarget({link:'read'},'READ-x'),{kind:'read',id:'READ-x'});
 assert.deepEqual(linkTarget({link:'account'},'CA-P-00041'),{hash:'#/workspace/account/CA-P-00041'});
 assert.deepEqual(linkTarget({link:'case'},'CASE-260427-SJF4B3'),{hash:'#/workspace/case/CASE-260427-SJF4B3'});
 assert.deepEqual(linkTarget({link:'order'},'WO-1'),{hash:'#/workspace/field-order/WO-1'});
 assert.deepEqual(linkTarget(cols[0],'INV-CA-P-00041-20260805',['INV-CA-P-00041-20260805','CA-P-00041'],cols),{hash:'#/workspace/account/CA-P-00041'},'the row names the account');
 assert.equal(invoiceAccount('INV-CA-P-00041-20260805'),'CA-P-00041','else the invoice id does');assert.equal(invoiceAccount('nonsense'),null);
 assert.equal(linkTarget({link:'account'},null),null);assert.equal(linkTarget({kind:'text'},'x'),null);
});

test('CSV pages stitch into one file with one header; names and page counts',()=>{
 assert.equal(stitchCsv(['a,b\n1,2\n3,4\n','a,b\n5,6\n']),'a,b\n1,2\n3,4\n5,6\n');assert.equal(stitchCsv(['a,b\n']),'a,b\n');assert.equal(stitchCsv([]),'');
 assert.equal(pageCount(45149,CSV_PAGE),10);assert.equal(pageCount(0,100),1);assert.equal(pageCount(100,100),1);assert.equal(pageCount(101,100),2);
 assert.equal(csvName('ayr','reads','2026-08-05'),'ayr-reads-2026-08-05.csv');assert.equal(csvName('town-348655bc6c071aad','invoices',null),'town-348655bc6c071aad-invoices-run.csv');
});

test('hidden columns are remembered per table and cleared when none are hidden',()=>{
 const m=new Map(),storage={getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v),removeItem:k=>m.delete(k)};
 assert.deepEqual([...loadHidden(storage,'reads')],[]);
 saveHidden(storage,'reads',new Set(['mruId','portion']));assert.deepEqual([...loadHidden(storage,'reads')].sort(),['mruId','portion']);assert.deepEqual([...loadHidden(storage,'invoices')],[]);
 saveHidden(storage,'reads',new Set());assert.equal(m.has('utility-town-data-cols:reads'),false);
 assert.deepEqual([...loadHidden({getItem:()=>'not json'},'x')],[]);
});

test('facet selects show counts, mark the set ones and fold the rest behind More filters',()=>{
 const columns=[{key:'commodity',label:'Commodity',facet:true},{key:'address',label:'Address'},{key:'released',label:'Released',facet:true,kind:'bool'},{key:'caseId',label:'Case',facet:true}];
 const facets={commodity:[{value:'electric',count:20},{value:'water',count:12}],released:[{value:true,count:30},{value:false,count:2}],caseId:[{value:null,count:31},{value:'CASE-1',count:1}]};
 const html=facetMarkup(columns,facets,{commodity:'water'});
 assert.match(html,/class="data-facet is-set"><span>Commodity<\/span><select data-facet="commodity"/);assert.match(html,/<option value="water" selected>water · 12<\/option>/);
 assert.match(html,/<option value="true">Yes · 30<\/option>/);assert.match(html,/<option value="">\(blank\) · 31<\/option>/);
 assert.doesNotMatch(html,/data-facet="address"/,'only facet columns get a select');assert.doesNotMatch(html,/data-more/,'few facets stay inline');
 const many=Array.from({length:INLINE_FACETS+2},(_,i)=>({key:'f'+i,label:'F'+i,facet:true})),mf=Object.fromEntries(many.map(c=>[c.key,[{value:'a',count:1}]]));
 const more=facetMarkup(many,mf,{['f'+(INLINE_FACETS+1)]:'a'});
 assert.match(more,/<details class="data-more" open><summary>More filters ·<\/summary>/);assert.equal((more.match(/data-facet=/g)||[]).length,INLINE_FACETS+2);
 assert.equal(sourceLabel('town'),'Town snapshot');assert.equal(sourceLabel('run'),'Engine run · as of the run date');assert.equal(sourceLabel('both'),'Town snapshot + engine run');
});

test('the client asks the engine for a table page with the run context, and for CSV pages',async()=>{
 const log=[],memory=()=>{const m=new Map();return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,v)};};
 const fetchImpl=async(url,opts={})=>{const body=opts.body?JSON.parse(opts.body):null;log.push({url,body});
  if(url.endsWith('/m2c/tables'))return {ok:true,json:async()=>({schemaVersion:'m2c-tables/1.0',groups:[]})};
  if(url.endsWith('/m2c/table.csv'))return {ok:true,text:async()=>'a,b\n1,2\n'};
  return {ok:true,json:async()=>({schemaVersion:'m2c-table/1.0',table:body.table,rows:[],total:0,echo:body})};};
 const m=new EngineM2C({api:'/api',townRef:'ayr',townId:'town-1',storage:memory(),fetchImpl});m.setAsOf('2026-08-05');m.setSettings({process:{analysts:2}});
 const cat=await m.tables();await m.tables();assert.equal(cat.schemaVersion,'m2c-tables/1.0');assert.equal(log.filter(x=>x.url.endsWith('/m2c/tables')).length,1,'the catalog is fetched once');
 const page=await m.table({table:'reads',page:2,pageSize:100,sort:'consumption',desc:true,filters:{commodity:'water'},search:'piper'});
 assert.deepEqual(log.at(-1).body,{town:'ayr',actions:[],table:'reads',page:2,pageSize:100,sort:'consumption',desc:true,filters:{commodity:'water'},search:'piper',settings:{process:{analysts:2}},asOf:'2026-08-05'});
 assert.equal(page.table,'reads');
 const csv=await m.tableCsv({table:'reads',page:1,pageSize:5000});assert.equal(csv,'a,b\n1,2\n');assert.equal(log.at(-1).body.pageSize,5000);assert.equal(log.at(-1).body.asOf,'2026-08-05');
});
