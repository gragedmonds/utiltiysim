import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from '../dist/vendor/three.module.js';
import {TownScene} from '../dist/scene.js';
import {traceConnection, PALETTE} from '../dist/adapter.js';
import {snapshot} from './fixtures.mjs';

// A premise without gas: the engine sends `gas: null` and has no gas meter for it.
function withoutGas(){const t=snapshot();t.premises[1].services.gas=null;const g=t.networks.gas;g.nodes=g.nodes.filter(n=>n.id!=='m2');g.edges=g.edges.filter(e=>e.id!=='bm2');return t;}
function scene(town){const s=Object.create(TownScene.prototype);Object.assign(s,{town,root:new THREE.Group(),heightAt:()=>0});return s;}

test('an unserved utility has no route and is reported as no service',()=>{const t=withoutGas();assert.deepEqual(traceConnection(t,'P-2','gas'),{connected:false,edges:[],reason:'No service'});assert.equal(traceConnection(t,'P-1','gas').connected,true);});

test('selecting a premise for a utility it does not take draws a neutral ring and no pipeline',()=>{const t=withoutGas(),s=scene(t);
 s.select(t.premises[1],'gas');assert.equal(s.trace.count,0,'no trace segments');assert.notEqual(s.selection.material.color.getHex(),PALETTE.gas);
 s.select(t.premises[0],'gas');assert.ok(s.trace.count>0,'a served premise is traced');assert.equal(s.selection.material.color.getHex(),PALETTE.gas);});
