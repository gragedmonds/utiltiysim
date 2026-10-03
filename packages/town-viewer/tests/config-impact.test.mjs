// Settings say where their effect reaches and how they change the results (x-reach, x-impact from the engine's
// utilsim/config/impact.py): the field model carries both, the popover leads with them, and search finds by reach.
import test from 'node:test';
import assert from 'node:assert/strict';
import {schemaFields,infoLines,fieldMatches,REACH} from '../dist/schema-form.js';

const schema={'x-reaches':{year:'Changes the year.',town:'New town.'},$defs:{
  HousingConfig:{title:'Housing & households','x-order':2,properties:{
   pool_rate:{type:'number',title:'Pool Rate',description:'Share of houses with a pool.',default:0.06,'x-reach':'town','x-impact':'Pools run a pump on electricity in summer.'}}},
  ProcessConfig:{title:'Meter-to-cash process','x-order':11,properties:{
   analysts:{type:'integer',title:'Analysts',description:'People on the queues.',default:2,'x-reach':'year','x-impact':'Fewer analysts grow the backlog.'},
   plain:{type:'number',title:'Plain',description:'No hints.',default:1}}}},
 properties:{housing:{$ref:'#/$defs/HousingConfig'},process:{$ref:'#/$defs/ProcessConfig'}}};

test('fields carry reach and impact from the schema',()=>{
 const f=Object.fromEntries(schemaFields(schema).map(x=>[x.path,x]));
 assert.equal(f['housing.pool_rate'].reach,'town');assert.match(f['housing.pool_rate'].impact,/pump on electricity/);
 assert.equal(f['process.analysts'].reach,'year');assert.equal(f['process.plain'].reach,'');assert.equal(f['process.plain'].impact,'');
});

test('the popover leads with how the setting changes the results, then where it reaches',()=>{
 const f=schemaFields(schema).find(x=>x.path==='process.analysts');
 const lines=infoLines(f,schema['x-reaches']);
 assert.equal(lines[0],'How it changes the results: Fewer analysts grow the backlog.');
 assert.equal(lines[1],'Reaches: Changes the year.');
 assert.equal(lines[2],'People on the queues.');
 assert.ok(lines.includes('process.analysts'));
 const plain=infoLines(schemaFields(schema).find(x=>x.path==='process.plain'));
 assert.equal(plain[0],'No hints.');
 const fallback=infoLines(schemaFields(schema).find(x=>x.path==='housing.pool_rate'),null);
 assert.equal(fallback[1],'Reaches: '+REACH.town.text);
});

test('search finds settings by reach and by their explanation',()=>{
 const fs=schemaFields(schema);
 assert.deepEqual(fs.filter(f=>fieldMatches(f,'year')).map(f=>f.path),['process.analysts']);
 assert.deepEqual(fs.filter(f=>fieldMatches(f,'electricity')).map(f=>f.path),['housing.pool_rate']);
});

test('the reach labels cover the engine reaches',()=>{
 assert.deepEqual(Object.keys(REACH).sort(),['display','operations','shape','town','year']);
 for(const r of Object.values(REACH)){assert.ok(r.chip.length<=8);assert.ok(r.text.length>20);}
});
