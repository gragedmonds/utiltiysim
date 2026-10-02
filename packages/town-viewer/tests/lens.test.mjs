import test from 'node:test';
import assert from 'node:assert/strict';
import {lensColor,loadingColor,lensLegend,tally,LENSES,DEFAULT_THRESHOLDS as T,buildLens,legendRows,lensIndex,lineColor,setLensThresholds,lensThresholds,onLensThresholds,zoomStep} from '../dist/lens-marks.js';
import {m2cRunKey,frameClock} from '../dist/map-lens.js';
import {snapshot} from './fixtures.mjs';

test('lens classes follow ANSI voltage, water pressure, gas tiers and case status',()=>{
 assert.deepEqual(LENSES.map(l=>l[0]),['network','voltage','pressure','cases']);
 const ok=lensColor('voltage',120),warn=lensColor('voltage',115),bad=lensColor('voltage',113.6);
 assert.ok(ok&&warn&&bad&&new Set([ok,warn,bad]).size===3);
 assert.equal(lensColor('voltage',127),bad);
 assert.equal(lensColor('voltage',null),null);
 assert.equal(lensColor('pressure',250),bad);assert.equal(lensColor('pressure',300),warn);assert.equal(lensColor('pressure',450),ok);
 assert.notEqual(lensColor('pressure',600),ok);
 assert.equal(lensColor('pressure',1.7,T,'gas'),ok);assert.equal(lensColor('pressure',0.8,T,'gas'),bad);assert.notEqual(lensColor('pressure',414,T,'gas'),ok);
 assert.equal(lensColor('cases',0),lensLegend('cases')[0][0]);assert.equal(lensColor('network',120),null);
 assert.equal(loadingColor(1.2),bad);assert.equal(loadingColor(0.9),warn);assert.equal(loadingColor(0.5),null);
 assert.deepEqual(tally([ok,ok,bad,null]),{[ok]:2,[bad]:1});
 assert.ok(lensLegend('voltage').length>=3&&lensLegend('pressure',T,'gas').length===4&&lensLegend('network').length===0);
});

const flowFixture=()=>({voltage:new Map([['P-1',120],['P-2',113],['P-3',null]]),loading:new Map([['tx1',1.2],['tx2',.85],['tx3',.3],['l1',.9],['l2',1.05],['l3',.2],['s1',2]]),pressure:{water:new Map([['P-1',450],['P-2',250]]),gas:new Map([['P-1',1.7],['P-2',414]])}});
const indexFixture={transformers:[{id:'T1',edgeId:'tx1',x:1,z:2},{id:'T2',edgeId:'tx2',x:3,z:4},{id:'T3',edgeId:'tx3',x:5,z:6}],lineEdges:['l1','l2','l3']};

test('a lens builds premise discs, transformer rings and loaded lines from one frame',()=>{
 const ok=lensColor('voltage',120),bad=lensColor('voltage',113),warm=loadingColor(.9),hot=loadingColor(1.2);
 const v=buildLens('voltage',{flow:flowFixture(),index:indexFixture});
 assert.equal(v.available,true);assert.deepEqual(v.entries,[['P-1',ok],['P-2',bad]]);
 assert.deepEqual(v.assets.map(a=>[a.id,a.color]),[['T1',hot],['T2',warm]]);
 assert.deepEqual(v.lines,[['l1',warm],['l2',hot]],'Voltage lens: amber above 80 %, red above 100 %');
 assert.deepEqual(v.counts,{[ok]:1,[bad]:1});assert.deepEqual(v.ringCounts,{[hot]:1,[warm]:1});
 // Overloads stay visible with every lens; only the Voltage lens shows the amber band.
 assert.deepEqual(buildLens('network',{flow:flowFixture(),index:indexFixture}).lines,[['l2',hot]]);
 assert.deepEqual(buildLens('network',{flow:flowFixture(),index:indexFixture}).entries,[]);
 // Pressure follows the active utility layer; electric falls back to water.
 const pw=buildLens('pressure',{flow:flowFixture(),utility:'electric'}),pg=buildLens('pressure',{flow:flowFixture(),utility:'gas'});
 assert.equal(pw.utility,'water');assert.deepEqual(pw.entries.map(e=>e[0]),['P-1','P-2']);assert.equal(pw.entries[1][1],lensColor('pressure',250));
 assert.equal(pg.utility,'gas');assert.equal(pg.entries[0][1],lensColor('pressure',1.7,T,'gas'));
 // Cases: the meter-to-cash summary's premise status.
 const c=buildLens('cases',{summary:{premises:{ids:['P-1','P-2'],status:[0,3],legend:['clean','estimated','open case','escalated','field order']}}});
 assert.deepEqual(c.entries,[['P-1',lensColor('cases',0)],['P-2',lensColor('cases',3)]]);
 // Without engine data the lens says so (the control disables it) and draws nothing.
 for(const id of ['voltage','pressure','cases']){const b=buildLens(id,{flow:{}});assert.equal(b.available,false);assert.equal(b.entries.length,0);}
});

test('legend rows count each class, with ring and line rows',()=>{
 const v=buildLens('voltage',{flow:flowFixture(),index:indexFixture}),rows=legendRows(v);
 const by=label=>rows.find(r=>r.label.includes(label));
 assert.equal(by('ANSI A').count,1);assert.equal(by('transformer > 100').count,1);assert.equal(by('transformer > 100').shape,'ring');
 assert.equal(by('80% loaded').count,1);assert.equal(by('overloaded').count,1);assert.equal(by('overloaded').shape,'line');
 const n=legendRows(buildLens('network',{flow:flowFixture(),index:indexFixture}));assert.deepEqual(n.map(r=>r.count),[1],'Network: only the overload row');
 assert.deepEqual(legendRows(buildLens('network',{flow:{loading:new Map()},index:indexFixture})),[]);
 const cases=legendRows(buildLens('cases',{summary:{premises:{ids:['P-1'],status:[1]}}}),{caseLegend:['a','b','c','d','e']});assert.deepEqual(cases.map(r=>[r.label,r.count]),[['a',0],['b',1],['c',0],['d',0],['e',0]]);
});

test('lens index finds transformers and line edges once per town',()=>{
 const s=snapshot(),el=s.networks.electric;el.nodes.push({id:'tx',x:5,z:5,kind:'transformer'});el.edges.push({id:'e-tx',from:'a',to:'tx',kind:'transformer',points:[{x:10,z:0},{x:5,z:5}],lengthM:7},{id:'svc',from:'tx',to:'m1',kind:'service',points:[{x:5,z:5},{x:10,z:10}],lengthM:7});
 const ix=lensIndex(s);assert.deepEqual(ix.transformers,[{id:'tx',edgeId:'e-tx',x:5,z:5,ratingKVA:null}]);assert.deepEqual(ix.lineEdges,['sa','ab','sb','am1','bm2']);assert.equal(lensIndex(s),ix);
});

test('thresholds are overridable from one place and the map hears about it',()=>{
 let heard=0;const off=onLensThresholds(()=>heard++);
 try{setLensThresholds({vLow:115,lineWarm:.5});assert.equal(lensThresholds().vLow,115);assert.equal(lensThresholds().vHigh,T.vHigh);assert.equal(lensColor('voltage',114.5),lensColor('voltage',113));assert.equal(lineColor(.6),loadingColor(.9));assert.equal(heard,1);}
 finally{setLensThresholds(null);off();}
 assert.deepEqual(lensThresholds(),T);assert.equal(lineColor(.6),null);assert.equal(lineColor(.9,false),null);assert.equal(lineColor(1.1,false),loadingColor(1.2));
});

test('marks grow with distance in half steps; run keys and frame clocks for the legend',()=>{
 assert.equal(zoomStep(50),1);assert.equal(zoomStep(600),2);assert.equal(zoomStep(5000),6);assert.equal(zoomStep(375),1.5);
 const m={townId:'t',asOf:'2026-07-15',actions:[{}],settings:null,outageKey:()=>'x'};assert.equal(m2cRunKey(m),'t|2026-07-15|1|null|x');assert.equal(m2cRunKey(null),null);
 assert.notEqual(m2cRunKey({...m,actions:[{},{}]}),m2cRunKey(m));
 assert.equal(frameClock({simTime:'2026-01-15T23:30:00Z',clock:{simTime:'2026-01-15T23:30:00Z',timezone:'America/Toronto'}}),'18:30');assert.equal(frameClock(null),null);
});
