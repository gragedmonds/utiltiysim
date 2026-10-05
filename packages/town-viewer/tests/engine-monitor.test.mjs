import test from 'node:test';
import assert from 'node:assert/strict';
import {AnalysisQueue} from '../dist/engine-monitor.js';
const tick=()=>new Promise(r=>setTimeout(r,0));
test('queue limits concurrent analysis, keeps replies intact and learns measured ETA',async()=>{
 let time=0;const gates=[];const q=new AnalysisQueue({limit:1,now:()=>time,fetchImpl:()=>new Promise(r=>gates.push(r))});
 const first=q.request('/api/m2c/trend',{},'/api/m2c/trend'),second=q.request('/api/m2c/trend',{},'/api/m2c/trend');
 assert.equal(gates.length,1);assert.equal(q.snapshot().active.length,1);assert.equal(q.snapshot().queued.length,1);assert.equal(q.snapshot().eta,null);
 time=5000;gates[0](new Response('{"ok":true}',{headers:{'Content-Type':'application/json'}}));assert.deepEqual(await (await first).json(),{ok:true});await tick();assert.equal(gates.length,2);assert.equal(q.snapshot().eta,5000);
 gates[1](new Response('second'));assert.equal(await (await second).text(),'second');await tick();assert.equal(q.snapshot().active.length,0);assert.equal(q.snapshot().finished,2);
});
test('failed calls release the queue and cancellation removes queued work before it reaches the engine',async()=>{
 const gates=[];const q=new AnalysisQueue({limit:1,fetchImpl:()=>new Promise((resolve,reject)=>gates.push({resolve,reject}))});
 const first=q.request('first',{},'/api/m2c/trend'),controller=new AbortController(),cancelled=q.request('cancelled',{signal:controller.signal},'/api/m2c/trend');
 const rejected=assert.rejects(cancelled);controller.abort();await rejected;assert.equal(q.snapshot().queued.length,0);
 const failed=assert.rejects(first,/offline/);gates[0].reject(Error('offline'));await failed;await tick();assert.match(q.snapshot().lastError,/could not finish/);assert.equal(q.snapshot().active.length,0);
 const httpError=q.request('error',{},'/api/m2c/trend');gates[1].resolve(new Response('invalid',{status:422}));assert.equal((await httpError).status,422);await tick();assert.match(q.snapshot().lastError,/422/);
});


import {LOAD_MESSAGES,loadingMessage} from '../dist/load-messages.js';
import {monitorMarkup} from '../dist/local-monitor.js';
test('five hundred distinct loading messages rotate under the illustration',()=>{
 assert.equal(LOAD_MESSAGES.length,500);assert.equal(new Set(LOAD_MESSAGES).size,500);
 assert.notEqual(loadingMessage(0),loadingMessage(6500));
 const html=monitorMarkup({active:{name:'Test utility',progress:{totalHomes:50000,etaSeconds:859,etaBasis:'Reference test'}}});
 assert.match(html,/engine-scene-caption/);assert.ok(!html.includes('monitor-message'));
 assert.match(html,/15 min remaining/);assert.match(html,/Reference test/);
});

import {stopTarget,stopLocalWork} from '../dist/local-monitor.js';
test('Stop targets the visible job or analysis and preserves unrelated work',async()=>{
 const job={active:{jobId:'revision-2',name:'Test',progress:{}}},analysis={analysis:{analysisId:'analysis-1',name:'Test',totalHomes:80}};
 assert.deepEqual(stopTarget(job),{path:'jobs/revision-2/stop',body:{},id:'revision-2'});
 const calls=[];await stopLocalWork(analysis,async(...args)=>{calls.push(args);return {stopped:true};});
 assert.deepEqual(calls,[['analysis/stop',{analysisId:'analysis-1'}]]);
 assert.match(monitorMarkup(job),/Stop simulation/);assert.match(monitorMarkup({...job,active:{...job.active,stopping:true}}),/disabled>Stopping/);
 assert.equal(stopTarget({}),null);await assert.rejects(stopLocalWork({}),/finished/);
 await assert.rejects(stopLocalWork(job,async()=>{throw Error('Offline');}),/Offline/);
});
