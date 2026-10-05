import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {indexGraph,connections,searchNodes,projectGraph,layoutGraph,edgePath,bundleRoutes} from '../dist/dependency-model.js';
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

test('bundled routes keep one centered input/output, rounded elbows and never cross cards',()=>{
 for(const [selected,expanded] of [['process.analysts',['process']],['kpi:bills_on_time',['process']],['engine:review',['field','contact']],['engine:invoices',[]]]){
  const scope=connections(graph,selected,{all:true}),p=projectGraph(graph,scope,selected,new Set(expanded)),layout=layoutGraph(p);
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

   }
  }
 }
});

test('elbows use tangent circular quarter-turns while straight connectors stay straight',()=>{
 assert.equal(edgePath([[0,0],[80,0],[80,80],[160,80]]),'M0,0 L64,0 A16,16 0 0 1 80,16 L80,64 A16,16 0 0 0 96,80 L160,80');
 assert.equal(edgePath([[0,0],[28,0],[80,0]]),'M0,0 L28,0 L80,0');
 assert.ok(!edgePath([[0,0],[4,0],[4,-4]]).includes('NaN'));
});

const assertForward=p=>{
 const layout=layoutGraph(p),nodes=new Map(p.nodes.map(n=>[n.id,n]));
 for(const e of p.edges){
  assert.ok(layout.positions.get(e.source).col<layout.positions.get(e.target).col,`${e.source} → ${e.target} should read left to right`);
  for(const link of e.links){
   const source=nodes.get(e.source),target=nodes.get(e.target);
   assert.ok(source.nodeId===link.source||source.members?.some(n=>n.id===link.source));
   assert.ok(target.nodeId===link.target||target.members?.some(n=>n.id===link.target));
  }
 }
 return layout;
};
test('invoice inputs sit left, downstream operations sit right and all six KPIs share one column',()=>{
 const id='engine:invoices',p=projectGraph(graph,connections(graph,id),id),layout=assertForward(p),focus=layout.positions.get(id);
 assert.ok(layout.positions.get('engine:bills').x<focus.x);
 for(const id of ['engine:collections','engine:contact','engine:carry'])assert.ok(layout.positions.get(id).x>focus.x);
 const metrics=p.nodes.filter(n=>n.kind==='metric');assert.equal(metrics.length,6);
 assert.equal(new Set(metrics.map(n=>layout.positions.get(n.id).x)).size,1);
 assert.equal(new Set(metrics.map(n=>layout.positions.get(n.id).y)).size,6);
});
test('feedback has finite repeated appearances with canonical identities and every real relationship',()=>{
 const g=indexGraph({nodes:['a','b','c','d','e','f','k'].map(id=>({id,title:id,kind:id==='k'?'metric':'data',lane:id==='k'?'metrics':'data'})),edges:[['a','b'],['b','c'],['c','a'],['c','d'],['d','e'],['e','d'],['f','b'],['f','k'],['a','k']].map(([source,target])=>({source,target,kind:'flow'}))});
 for(const id of ['a','d','f','k']){
  const scope=connections(g,id,{all:true}),p=projectGraph(g,scope,id);assertForward(p);
  assert.ok(p.nodes.length<scope.visible.size*4,'unrolling must terminate');
  assert.equal(p.nodes.filter(n=>n.id===id&&n.relation==='selected').length,1);
  for(const e of scope.edges)assert.ok(p.edges.some(view=>view.links.includes(e)),'no relationship may disappear');
 }
 const p=projectGraph(g,connections(g,'a',{all:true}),'a'),b=p.nodes.filter(n=>n.nodeId==='b');
 assert.ok(b.some(n=>n.rank<0)&&b.some(n=>n.rank>0));assert.ok(b.every(n=>n.repeated));
});
test('engine graph retains causal order and one KPI column across scopes and filters',()=>{
 for(const id of ['engine:invoices','engine:review','engine:reads','process.analysts','town.units','kpi:bills_on_time'])for(const all of [false,true])for(const conditional of [false,true])for(const direction of ['before','after','both']){
  const scope=connections(graph,id,{all,conditional,direction}),p=projectGraph(graph,scope,id),layout=assertForward(p);
  const represented=new Set(p.nodes.flatMap(n=>n.members?n.members.map(m=>m.id):[n.nodeId]));
  assert.deepEqual(represented,scope.visible);
  if(direction==='before')assert.ok(p.nodes.every(n=>n.rank<=0));
  if(direction==='after')assert.ok(p.nodes.every(n=>n.rank>=0));
  assert.ok(new Set(p.nodes.filter(n=>n.kind==='metric').map(n=>layout.positions.get(n.id).x)).size<=1);
  for(const e of scope.edges)assert.ok(p.edges.some(view=>view.links.includes(e))||p.nodes.some(n=>n.members?.some(m=>m.id===e.source)&&n.members.some(m=>m.id===e.target)),`${e.source} → ${e.target} must remain explainable or inside an expandable group`);
 }
});
test('partially overlapping paths paint once and expose all and only the links on each stretch',()=>{
 const a={conditional:false},b={conditional:false},c={conditional:true};
 const bundles=bundleRoutes(new Map([[a,[[0,0],[100,0]]],[b,[[40,0],[140,0]]],[c,[[40,0],[100,0]]]]));
 const ordinary=bundles.filter(b=>!b.conditional);
 assert.deepEqual(ordinary.map(b=>b.points),[[[0,0],[40,0]],[[40,0],[100,0]],[[100,0],[140,0]]]);
 assert.deepEqual(ordinary.map(b=>b.edges),[[a],[a,b],[b]]);
 assert.deepEqual(bundles.find(b=>b.conditional).edges,[c]);
});
test('dense maps share highways without losing individual complete highlight routes',()=>{
 const id='process.analysts',p=projectGraph(graph,connections(graph,id,{all:true}),id),layout=layoutGraph(p);
 assert.ok(layout.bundles.some(b=>b.edges.length>5),'common stretches should join early');
 assert.ok(layout.corridors.every(c=>c.tracks<=2),'density must not create hundreds of parallel tracks');
 let separate=0,shared=0;
 for(const b of layout.bundles)if(b.points){const [a,z]=b.points,len=Math.hypot(a[0]-z[0],a[1]-z[1]);shared+=len;separate+=len*b.edges.length;}
 assert.ok(shared<separate*.6,'shared paths should materially reduce visible ink');
 for(const e of p.edges){assert.ok(layout.routes.has(e));assert.ok(layout.bundles.some(b=>b.edges.includes(e)));}
});
