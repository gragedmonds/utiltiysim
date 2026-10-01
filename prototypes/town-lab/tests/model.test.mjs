import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import crypto from 'node:crypto';
import {parseOSM,createTown,flows,traceService,monthlyReads,exportTown,UTILS} from '../dist/model.js';
const raw=JSON.parse(fs.readFileSync(new URL('../dist/whitby-roads.json',import.meta.url))),source=parseOSM(raw);
const digest=x=>crypto.createHash('sha256').update(JSON.stringify(x)).digest('hex');
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-7,`${a} != ${b}`);
let basic=createTown(source,{count:480});
test('same manifest and exported source reconstruct byte-identical towns',()=>{
 assert.equal(digest(basic),digest(createTown(source,{count:480})));
 assert.equal(digest(basic),digest(createTown(basic.sourceSnapshot,{seed:basic.seed,count:basic.count})));
 assert.notEqual(digest(basic),digest(createTown(source,{seed:'ANOTHER-SEED',count:480})));
 const before=digest(basic);flows(basic,12,'leak',basic.premises[0].id);monthlyReads(basic,basic.premises[0]);assert.equal(before,digest(basic));
});
test('sizes through 10,000 homes have valid graph and commercial relationships',()=>{
 for(const count of [120,480,2000,10000]){let start=performance.now();const t=count===480?basic:createTown(source,{count});assert.equal(t.count,count);assert.equal(t.premises.length,count);assert.equal(t.validation.valid,true);assert.deepEqual(t.validation.errors,[]);
 const homes=new Set(t.premises.map(h=>h.id)),meters=new Map(t.meters.map(m=>[m.id,m])),points=new Map(t.servicePoints.map(p=>[p.id,p])),inst=new Set(t.installations.map(x=>x.id)),accounts=new Set(t.accounts.map(x=>x.id));
 for(const sp of t.servicePoints){assert.ok(homes.has(sp.premiseId));assert.ok(meters.has(sp.meterId));assert.ok(inst.has(sp.installationId));}
 for(const r of t.registers)assert.ok(meters.has(r.meterId));for(const c of t.contracts){assert.ok(inst.has(c.installationId));assert.ok(accounts.has(c.accountId));}
 for(const h of t.premises)assert.equal(Boolean(h.services.gas),!h.electricHeat);
 // For each utility all children have exactly one parent; no orphan services and no accidental cycles.
 for(const u of UTILS){let n=t.networks[u];assert.equal(new Set(n.edges.map(e=>e.to)).size,n.nodes.length-1);let nodes=new Set(n.nodes.map(n=>n.id));n.edges.forEach(e=>{assert.ok(nodes.has(e.from)&&nodes.has(e.to));assert.ok(e.lengthM>=0);});}
 const sample=t.premises.filter((_,i)=>i%Math.max(1,Math.floor(count/30))===0);for(const h of sample){const p=traceService(t,h.id,'electric');assert.equal(p[0].voltageKV,69);assert.ok(p.some(e=>e.kind==='transformer'&&e.secondaryVoltageKV===.24));assert.equal(p.at(-1).voltageKV,.24);assert.equal(p.at(-1).kind,'service');}
 let f=flows(t,12);for(const u of UTILS)near(f[u].source,[...f.homes.values()].reduce((s,d)=>s+d[u],0));console.log(`${count} homes: ${Math.round(performance.now()-start)} ms generation, integrity and initial flow; ${t.validation.connectedServices} services`);
 }
});
test('energy and mass balance at every junction; solar export reverses edges',()=>{
 const f=flows(basic,12);assert.ok(basic.premises.some(h=>h.solar&&f.homes.get(h.id).electric<0));assert.ok(f.electric.source<0);assert.ok(flows(basic,0).electric.source>0);
 for(const u of UTILS){const net=basic.networks[u],children=new Map();for(const e of net.edges){children.set(e.from,(children.get(e.from)||0)+f[u].edgeFlows.get(e.id));}for(const e of net.edges){const n=net.nodes.find(n=>n.id===e.to);const demand=n.premiseId?f.homes.get(n.premiseId)[u]:0;near(f[u].edgeFlows.get(e.id),(children.get(e.to)||0)+demand);}}
 const outage=flows(basic,12,'outage');near(outage.electric.source,0);assert.ok([...outage.electric.edgeFlows.values()].every(v=>v===0));
});
test('a leak changes precisely the target home and its upstream path',()=>{
 const target=basic.premises[0],baseline=flows(basic,8),leak=flows(basic,8,'leak',target.id),up=new Set(traceService(basic,target.id,'water').map(e=>e.id));near(leak.water.source-baseline.water.source,.65);
 for(const e of basic.networks.water.edges)near(leak.water.edgeFlows.get(e.id)-baseline.water.edgeFlows.get(e.id),up.has(e.id)?.65:0);
 near(leak.electric.source,baseline.electric.source);near(leak.gas.source,baseline.gas.source);
});
test('calendar reads reconcile, remain monotone and never net import/export registers',()=>{
 for(const h of basic.premises.slice(0,60)){const june=monthlyReads(basic,h,6),july=monthlyReads(basic,h,7);for(const r of june){assert.ok(r.consumption>=0);near(r.registerValue-r.previousRegisterValue,r.consumption);assert.equal(r.registerValue,july.find(j=>j.registerId===r.registerId).previousRegisterValue);assert.equal(r.veeStatus,'not_processed');assert.equal(r.billingDocumentId,null);assert.equal(r.invoiceId,null);}assert.equal(june.filter(r=>r.direction==='export').length,h.solar?1:0);assert.equal(digest(june),digest(monthlyReads(basic,h,6)));}
 const exported=exportTown(basic);assert.equal(exported.sampleReads.length,basic.registers.length);assert.deepEqual(exported.billingDocuments,[]);assert.deepEqual(exported.invoices,[]);fs.writeFileSync(new URL('../tests/example-town.json',import.meta.url),JSON.stringify(exported));
});
test('invalid generation input fails; valid Overpass out geom input is accepted',()=>{
 for(const count of [0,19,10001,4.5,NaN])assert.throws(()=>createTown(source,{count}));assert.throws(()=>createTown(source,{seed:' '}));assert.throws(()=>parseOSM({}));assert.throws(()=>parseOSM({elements:[]}));
 const overpass={elements:[{type:'way',id:1,tags:{highway:'residential'},geometry:[{lat:43,lon:-79},{lat:43.01,lon:-79},{lat:43.01,lon:-78.99}]}]};const parsed=parseOSM(overpass);assert.ok(parsed.roads.length);assert.equal(createTown(parsed,{count:20}).validation.valid,true);
});
