import test from 'node:test';
import assert from 'node:assert/strict';
import {matchesQuery,expectedRegister,readNote} from '../dist/workspace.js';

test('search matches whole words from their start',()=>{
 assert.ok(matchesQuery('CASE-260708-01380 Comm fail · 12 Hall Street','Hall Street'));
 assert.ok(!matchesQuery('CASE-260702-01305 Consecutive estimates · 155 Howard Marshall Street','Hall Street'),'"Marshall" does not match "Hall"');
 assert.ok(matchesQuery('CASE-260715-01450 Large credit','case-2607'),'case ids by prefix');
 assert.ok(matchesQuery('anything',''),'an empty query matches everything');
});

test('the expected register is the previous register plus the expected use',()=>{
 assert.equal(expectedRegister({read:{previousRegisterValue:10187.328},expected:34.5}),10221.828);
 assert.equal(expectedRegister({previous:54162,expected:{consumption:1417.4}}),55579.4);
 assert.equal(expectedRegister({expected:{registerValue:47888}}),47888,'the engine\'s own value wins');
 assert.equal(expectedRegister({read:{}}),null);
});

test('a missed or estimated read says why',()=>{
 assert.equal(readNote({reasonCode:'SIM_POWER_OUTAGE'}),'Power outage at the AMI collection');
 assert.equal(readNote({reasonCode:'NO_ACCESS'}),'No access on the reading route');
 assert.equal(readNote({reason:'Power outage 01:00–03:20',reasonCode:'SIM_POWER_OUTAGE'}),'Power outage 01:00–03:20','the engine\'s text wins');
 assert.equal(readNote({readType:'actual'}),'');
});
