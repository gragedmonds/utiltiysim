import test from 'node:test';
import assert from 'node:assert/strict';
import {lensColor,loadingColor,lensLegend,tally,LENSES,DEFAULT_THRESHOLDS as T} from '../dist/lens-marks.js';

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
