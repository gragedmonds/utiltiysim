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
