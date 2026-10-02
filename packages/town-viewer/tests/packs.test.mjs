import test from 'node:test';
import assert from 'node:assert/strict';
import {gzipSync} from 'node:zlib';
import {fetchGzipJSON,packLabel,packCaption} from '../dist/packs.js';

const dataUrl=(bytes,type)=>`data:${type};base64,${Buffer.from(bytes).toString('base64')}`;
test('pack files are gunzipped in the browser, or used as-is when already decoded',async()=>{
 const doc={schemaVersion:'utility-town/2.0',id:'town-x'};
 assert.deepEqual(await fetchGzipJSON(dataUrl(gzipSync(JSON.stringify(doc)),'application/gzip')),doc);
 assert.deepEqual(await fetchGzipJSON(dataUrl(new TextEncoder().encode(JSON.stringify(doc)),'application/json')),doc);
});
test('pack labels prefer the real place, then the extract label, then the preset',()=>{
 assert.equal(packLabel({preset:'ayr',place:{name:'Ayr'},source:{label:'Ayr street snapshot'}}),'Ayr');
 assert.equal(packLabel({preset:'whitby_small',place:null,source:{label:'Whitby street snapshot'}}),'Whitby');
 assert.equal(packLabel({preset:'ontario_small',source:{label:''}}),'ontario small');
 assert.equal(packCaption({homes:1861,source:{type:'osm'}}),'1,861 homes · real streets');
});

test('?town= routes to a pack by preset or town id, else to a town the engine generated',async()=>{
 const {townRoute,engineSnapshotUrl}=await import('../dist/packs.js');
 const packs={towns:[{preset:'ayr',townId:'town-b1c40ea889bd3200'},{preset:'elora',townId:'town-3e327e045e791573'}]};
 assert.equal(townRoute('ayr',packs).pack.preset,'ayr');assert.equal(townRoute('town-3e327e045e791573',packs).pack.preset,'elora');
 assert.deepEqual(townRoute('town-d968ce9db1c457bc',packs),{townId:'town-d968ce9db1c457bc'});
 assert.deepEqual(townRoute('town-d968ce9db1c457bc',null),{townId:'town-d968ce9db1c457bc'},'no pack index (an engine-only host)');
 assert.equal(townRoute('springfield',packs),null);assert.equal(townRoute('town-../../etc',packs),null);assert.equal(townRoute(null,packs),null);
 assert.deepEqual(townRoute('ayr~eNqrVsrILy3OzEtXsqpWSs1J',packs),{townId:'ayr~eNqrVsrILy3OzEtXsqpWSs1J'},'a generated town named by its preset and changes');
 assert.equal(townRoute('ayr~../../x',packs),null);assert.equal(townRoute('~eNqr',packs),null);
 assert.equal(engineSnapshotUrl('http://127.0.0.1:8010/api','town-d968ce9db1c457bc'),'http://127.0.0.1:8010/api/towns/town-d968ce9db1c457bc/snapshot.json?detail=viewer&profile=viewer');
});
