import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {indexGraph,connections,searchNodes,projectGraph,layoutGraph,edgePath} from '../dist/dependency-model.js';
const graph=indexGraph(JSON.parse(fs.readFileSync(new URL('../dist/dependency-graph.json',import.meta.url),'utf8')));
test('search finds settings, nested variables, calculation records and KPI names',()=>{
 assert.equal(searchNodes(graph,'process.analysts')[0].id,'process.analysts');
 assert.equal(searchNodes(graph,'Invoice timeliness')[0].id,'kpi:invoice_timeliness');
 assert.ok(searchNodes(graph,'crew meter').some(n=>n.id==='field.crew_meter.per_1000_premises'));
 assert.ok(searchNodes(graph,'underlying consumption').some(n=>n.id==='engine:usage'));
 assert.deepEqual(searchNodes(graph,'not-a-real-variable-123'),[]);
});
test('direct and transitive ancestry stay directional and conditional links can be excluded',()=>{
 const direct=connections(graph,'kpi:invoice_timeliness');
 assert.ok(direct.before.has('kpi.timely_invoice_days'));
 assert.equal(direct.after.size,0);
 const full=connections(graph,'kpi:invoice_timeliness',{all:true});
 assert.ok(full.before.size>direct.before.size);
 const off=connections(graph,'electric.primary_kv',{all:true,conditional:false});
 assert.ok(!off.after.has('kpi:customer_minutes_lost'));
 assert.ok(connections(graph,'electric.primary_kv',{all:true}).after.has('kpi:customer_minutes_lost'));
 assert.ok(!connections(graph,'town.units',{all:true}).after.has('kpi:cost_per_account'));
});
test('feedback cycles terminate without counting the selected node as its own predecessor',()=>{
 const x=indexGraph({nodes:['a','b','c'].map(id=>({id})),edges:[{source:'a',target:'b'},{source:'b',target:'c'},{source:'c',target:'a'}]});
 const reach=connections(x,'a',{all:true});assert.deepEqual([...reach.before].sort(),['b','c']);assert.deepEqual([...reach.after].sort(),['b','c']);
 assert.deepEqual([...connections(x,'a',{all:true,direction:'before'}).visible].sort(),['a','b','c']);
});
test('collapsed groups preserve every reachable setting and expanding reveals its real nodes',()=>{
 const selected='kpi:bills_on_time',scope=connections(graph,selected),closed=projectGraph(graph,scope,selected);
 const process=closed.nodes.find(n=>n.id==='group:process');assert.ok(process.members.length>1);
 const opened=projectGraph(graph,scope,selected,new Set(['process']));assert.ok(!opened.nodes.some(n=>n.id==='group:process'));
 for(const n of process.members)assert.ok(opened.nodes.some(x=>x.id===n.id));
 assert.equal(closed.nodes.reduce((n,x)=>n+(x.members?.length||1),0),scope.visible.size);
 for(const e of closed.edges)assert.ok(closed.nodes.some(n=>n.id===e.source)&&closed.nodes.some(n=>n.id===e.target));
});
test('large graphs grow horizontally and their cards do not overlap',()=>{
 const scope=connections(graph,'kpi:bills_on_time',{all:true}),p=projectGraph(graph,scope,'kpi:bills_on_time',new Set(['field','contact'])),layout=layoutGraph(p);
 assert.ok(layout.width>1200);assert.ok(layout.width>layout.height);
 assert.ok(new Set([...layout.positions.values()].map(p=>p.row)).size<=4);
 const pos=[...layout.positions.values()];for(let i=0;i<pos.length;i++)for(let j=i+1;j<pos.length;j++){
  const a=pos[i],b=pos[j];assert.ok(a.x+a.w<=b.x||b.x+b.w<=a.x||a.y+a.h<=b.y||b.y+b.h<=a.y);
 }
});

test('cards have one centered input/output and routes merge only in their card connector areas',()=>{
 for(const [selected,expanded] of [['process.analysts',['process']],['kpi:bills_on_time',['process']],['engine:review',['field','contact']]]){
  const scope=connections(graph,selected,{all:true}),p=projectGraph(graph,scope,selected,new Set(expanded)),layout=layoutGraph(p),segments=[];
  assert.equal(layout.routes.size,p.edges.length);
  assert.ok(layout.corridors.slice(1,-1).every(c=>c.height>=116),'rows leave room for the connection highway');
  for(const [id,card] of layout.positions){
   assert.equal(card.h,88,'branch count must not change card height');
   for(const side of ['in','out']){
    const count=p.edges.filter(e=>e[side==='in'?'target':'source']===id).length,ports=layout.ports.filter(p=>p.id===id&&p.side===side);
    assert.equal(ports.length,count?1:0);if(count)assert.equal(ports[0].count,count);
   }
  }
  for(const [e,points] of layout.routes){
   const source=layout.positions.get(e.source),target=layout.positions.get(e.target);
   assert.equal(points[0][0],source.x+source.w);assert.equal(points.at(-1)[0],target.x);
   assert.equal(points[0][1],source.y+source.h/2);
   assert.equal(points.at(-1)[1],target.y+target.h/2);
   const branch=layout.branches.get(e);
   assert.deepEqual(branch[0],[source.x+source.w+28,source.y+source.h/2]);
   assert.deepEqual(branch.at(-1),[target.x-28,target.y+target.h/2]);
   assert.ok(!edgePath(points).includes('NaN'));
   for(let i=1;i<points.length;i++){
    const a=points[i-1],b=points[i],horizontal=a[1]===b[1];assert.ok(horizontal||a[0]===b[0]);
    const lo=Math.min(a[horizontal?0:1],b[horizontal?0:1]),hi=Math.max(a[horizontal?0:1],b[horizontal?0:1]),fixed=a[horizontal?1:0];
    for(const r of layout.positions.values()){
     const cross=horizontal?fixed>r.y&&fixed<r.y+r.h&&lo<r.x+r.w&&hi>r.x:fixed>r.x&&fixed<r.x+r.w&&lo<r.y+r.h&&hi>r.y;
     assert.ok(!cross,`${e.source} → ${e.target} must not cross a card`);
    }
    for(const prev of segments)if(prev.edge!==e&&prev.horizontal===horizontal&&prev.fixed===fixed&&hi>prev.lo&&lo<prev.hi){
     const zones=[];if(e.source===prev.edge.source)zones.push(layout.portZones.get(e.source+':out'));if(e.target===prev.edge.target)zones.push(layout.portZones.get(e.target+':in'));
     const start=Math.max(lo,prev.lo),end=Math.min(hi,prev.hi);
     assert.ok(zones.some(z=>horizontal?fixed>=z.y&&fixed<=z.y+z.h&&start>=z.x&&end<=z.x+z.w:fixed>=z.x&&fixed<=z.x+z.w&&start>=z.y&&end<=z.y+z.h),'only connections at the same card may share a connector; corridor lines must stay separate');
    }
    segments.push({edge:e,horizontal,fixed,lo,hi});
   }
  }
 }
});

test('elbows use tangent circular quarter-turns while straight connectors stay straight',()=>{
 assert.equal(edgePath([[0,0],[80,0],[80,80],[160,80]]),'M0,0 L64,0 A16,16 0 0 1 80,16 L80,64 A16,16 0 0 0 96,80 L160,80');
 assert.equal(edgePath([[0,0],[28,0],[80,0]]),'M0,0 L28,0 L80,0');
 assert.ok(!edgePath([[0,0],[4,0],[4,-4]]).includes('NaN'));
});
