import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {offlineRoute} from '../dist/focus-ui.js';
import {validLauncherURL} from '../dist/local-session.js';

test('desktop legacy routes send map and empty destinations to the Command Center',()=>{
 for(const hash of ['','#/map','#/town','#/something-removed'])assert.equal(offlineRoute(hash,true),'#/year');
 for(const hash of ['#/process/3','#/year','#/workspace/exceptions','#/data/bills','#/config'])assert.equal(offlineRoute(hash,true),hash);
 assert.equal(offlineRoute('#/map',false),'#/map');
 assert.equal(offlineRoute('#/config/scenarios',true),'#/config/m2c');
 assert.equal(offlineRoute('#/config/scenarios',false),'#/config/scenarios');
});
test('launcher settings only accept a local authenticated bootstrap address',()=>{
 assert.equal(validLauncherURL('http://127.0.0.1:51234/#token='+'a'.repeat(64)),true);
 for(const u of ['',undefined,'https://example.com/','javascript:alert(1)','http://127.0.0.1:51234/','http://127.0.0.1:51234/elsewhere#token='+'a'.repeat(64)])assert.equal(!!validLauncherURL(u),false);
});
test('Activity sequences is a primary destination in both desktop simulation views',()=>{
 for(const name of ['studio.html','local-runs.html']){
  const html=fs.readFileSync(new URL('../dist/'+name,import.meta.url),'utf8');
  assert.match(html,/<a href="#\/process"[^>]*>Activity sequences<\/a>/);
 }
});
