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
test('packs are generic towns, labelled by their preset',()=>{
 assert.equal(packLabel({preset:'small_town',source:{type:'synthetic',label:'Synthetic town'}}),'Small town');
 assert.equal(packLabel({preset:'village'}),'Village');assert.equal(packLabel({preset:'us_town'}),'Us town');
 assert.equal(packCaption({homes:1900,source:{type:'synthetic'}}),'1,900 homes');
});

test('?town= routes to a pack by preset or town id, else to a town the engine generated',async()=>{
 const {townRoute,engineSnapshotUrl}=await import('../dist/packs.js');
 const packs={towns:[{preset:'small_town',townId:'town-b1c40ea889bd3200'},{preset:'town',townId:'town-3e327e045e791573'}]};
 assert.equal(townRoute('small_town',packs).pack.preset,'small_town');assert.equal(townRoute('town-3e327e045e791573',packs).pack.preset,'town');
 assert.deepEqual(townRoute('town-d968ce9db1c457bc',packs),{townId:'town-d968ce9db1c457bc'});
 assert.deepEqual(townRoute('town-d968ce9db1c457bc',null),{townId:'town-d968ce9db1c457bc'},'no pack index (an engine-only host)');
 assert.equal(townRoute('springfield',packs),null);assert.equal(townRoute('town-../../etc',packs),null);assert.equal(townRoute(null,packs),null);
 assert.deepEqual(townRoute('small_town~eNqrVsrILy3OzEtXsqpWSs1J',packs),{townId:'small_town~eNqrVsrILy3OzEtXsqpWSs1J'},'a generated town named by its preset and changes');
 assert.equal(townRoute('small_town~../../x',packs),null);assert.equal(townRoute('~eNqr',packs),null);
 assert.equal(engineSnapshotUrl('http://127.0.0.1:8010/api','town-d968ce9db1c457bc'),'http://127.0.0.1:8010/api/towns/town-d968ce9db1c457bc/snapshot.json?detail=viewer&profile=viewer');
});

test('a bare address opens the default engine town: the small town when the site has it, else the first pack',async()=>{
 const {defaultPack,DEFAULT_TOWN}=await import('../dist/packs.js');
 assert.equal(DEFAULT_TOWN,'small_town');
 assert.equal(defaultPack({towns:[{preset:'village'},{preset:'small_town'}]}).preset,'small_town');
 assert.equal(defaultPack({towns:[{preset:'town'},{preset:'large_town'}]}).preset,'town');
 assert.equal(defaultPack({towns:[]}),null);assert.equal(defaultPack(null),null);
});
