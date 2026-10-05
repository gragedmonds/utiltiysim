// Pure graph operations shared by the explorer and its tests. Cycles are legitimate engine feedback.
export const LANES=['environment','operations','data','metrics'];
export function indexGraph(graph){
 const nodes=new Map(graph.nodes.map(n=>[n.id,n])),incoming=new Map(),outgoing=new Map();
 for(const edge of graph.edges){if(!nodes.has(edge.source)||!nodes.has(edge.target))throw Error('The dependency map contains an unknown variable.');
  if(!incoming.has(edge.target))incoming.set(edge.target,[]);incoming.get(edge.target).push(edge);
  if(!outgoing.has(edge.source))outgoing.set(edge.source,[]);outgoing.get(edge.source).push(edge);}
 return {...graph,byId:nodes,incoming,outgoing};
}
export function connections(graph,id,{all=false,conditional=true,direction='both'}={}){
 const walk=(map,next)=>{const visited=new Set([id]),found=new Set(),queue=[id];for(let i=0;i<queue.length;i++)for(const e of map.get(queue[i])||[]){if(!conditional&&e.kind==='conditional')continue;const n=e[next];if(visited.has(n))continue;visited.add(n);found.add(n);if(all)queue.push(n);}return found;};
 const before=walk(graph.incoming,'source'),after=walk(graph.outgoing,'target'),visible=new Set([id]);
 if(direction!=='after')for(const n of before)visible.add(n);if(direction!=='before')for(const n of after)visible.add(n);
 return {before,after,visible,direction,edges:graph.edges.filter(e=>visible.has(e.source)&&visible.has(e.target)&&(conditional||e.kind!=='conditional'))};
}
export function searchNodes(graph,text){const q=text.trim().toLowerCase(),words=q.split(/\s+/);if(!q)return [];
 return graph.nodes.map(n=>{const label=(n.title+' '+n.id+' '+n.topic).toLowerCase(),body=(label+' '+(n.description||'')+' '+(n.impact||'')).toLowerCase();
  const score=n.id.toLowerCase()===q?0:n.title.toLowerCase()===q?1:label.startsWith(q)?2:label.includes(q)?3:words.every(w=>label.includes(w))?4:words.every(w=>body.includes(w))?5:99;return {node:n,score};})
 .filter(x=>x.score<99).sort((a,b)=>a.score-b.score||a.node.title.localeCompare(b.node.title)).map(x=>x.node);
}
export function projectGraph(graph,selection,id,expanded=new Set()){
 const buckets=new Map(),members=new Map();
 for(const key of selection.visible){const n=graph.byId.get(key);if(!n)continue;
  const bucket=n.kind==='setting'&&n.id!==id&&!expanded.has(n.id.split('.')[0])?'group:'+n.id.split('.')[0]:n.id;
  members.set(key,bucket);if(!buckets.has(bucket))buckets.set(bucket,[]);buckets.get(bucket).push(n);}
 const nodes=[...buckets].map(([key,rows])=>key.startsWith('group:')?{id:key,title:rows[0].topic,lane:rows[0].lane,kind:'group',topic:rows[0].topic,members:rows,
  description:`${rows.length} connected settings`,relation:rows.every(n=>selection.before.has(n.id))?'before':rows.every(n=>selection.after.has(n.id))?'after':'both'}:
  {...rows[0],relation:key===id?'selected':selection.before.has(key)&&selection.after.has(key)?'both':selection.before.has(key)?'before':'after'});
 const edges=new Map();for(const e of selection.edges){const a=members.get(e.source),b=members.get(e.target);if(a===b)continue;const k=a+'|'+b+'|'+(e.kind==='conditional');
  if(!edges.has(k))edges.set(k,{source:a,target:b,conditional:e.kind==='conditional',links:[]});edges.get(k).links.push(e);}
 return unfoldFeedback(nodes,[...edges.values()],id,selection.direction);
}
// The category colours describe what a variable is; its position describes causality. Unroll
// feedback into finite visual occurrences, all pointing to the same underlying variable.
function unfoldFeedback(nodes,edges,focus,direction='both'){
 const byId=new Map(nodes.map(n=>[n.id,n])),views=new Map(),result=[],represented=new Set();
 const walk=before=>{
  const adjacency=new Map();for(const e of edges){const key=before?e.target:e.source;if(!adjacency.has(key))adjacency.set(key,[]);adjacency.get(key).push(e);}
  const state=new Map(),order=[],forward=[],feedback=new Set();
  function visit(id){state.set(id,1);for(const e of adjacency.get(id)||[]){const next=before?e.source:e.target;
   if(state.get(next)===1){feedback.add(e);continue;}forward.push(e);if(!state.has(next))visit(next);
  }state.set(id,2);order.push(id);}
  visit(focus);const depth=new Map([[focus,0]]);
  for(const id of order.reverse())for(const e of adjacency.get(id)||[]){if(feedback.has(e))continue;const next=before?e.source:e.target;depth.set(next,Math.max(depth.get(next)||0,depth.get(id)+1));}
  return {before,depth,forward,feedback};
 };
 const empty=before=>({before,depth:new Map([[focus,0]]),forward:[],feedback:[]});
 const left=direction==='after'?empty(true):walk(true),right=direction==='before'?empty(false):walk(false);
 const add=(key,original,rank,relation)=>{if(!views.has(key)){const n=byId.get(original);views.set(key,{...n,id:key,nodeId:original,groupKey:n.kind==='group'?original.slice(6):null,rank,relation});}return key;};
 add(focus,focus,0,'selected');
 const occurrence=(side,id)=>id===focus?focus:side.before||!left.depth.has(id)?id:'after:'+id;
 for(const side of [left,right]){
  const sign=side.before?-1:1,relation=side.before?'before':'after';
  for(const [id,depth] of side.depth)if(id!==focus)add(occurrence(side,id),id,sign*depth,relation);
  for(const e of side.forward){result.push({...e,source:occurrence(side,e.source),target:occurrence(side,e.target)});represented.add(e);}
  const end=Math.max(...side.depth.values())+1;
  for(const e of side.feedback){
   const original=side.before?e.source:e.target,key=(side.before?'repeat-before:':'repeat-after:')+original;
   add(key,original,sign*end,relation);
   result.push({...e,source:side.before?key:occurrence(side,e.source),target:side.before?occurrence(side,e.target):key});represented.add(e);
  }
 }
 // Shortcuts between an upstream branch and a downstream branch still belong in the picture.
 for(const e of edges)if(!represented.has(e))result.push({...e,source:occurrence(left,e.source),target:occurrence(right,e.target)});
 const counts=new Map();for(const n of views.values())counts.set(n.nodeId,(counts.get(n.nodeId)||0)+1);
 for(const n of views.values())n.repeated=counts.get(n.nodeId)>1;
 return {nodes:[...views.values()],edges:result};
}
export function layoutGraph(projected){
 const cardWidth=244,cardHeight=88,stem=28,gap=176,rowGap=116,columns=[],groups=[];
 const sort=(a,b)=>(a.kind==='group')-(b.kind==='group')||a.title.localeCompare(b.title);
 const append=(id,title,theme,nodes)=>{
  if(!nodes.length)return;const first=columns.length;
  if(id==='metrics')columns.push([...nodes].sort(sort));
  else for(const rank of [...new Set(nodes.map(n=>n.rank))].sort((a,b)=>a-b)){
   const peers=nodes.filter(n=>n.rank===rank).sort(sort);
   for(let i=0;i<peers.length;i+=4)columns.push(peers.slice(i,i+4));
  }
  groups.push({id,title,theme,first,last:columns.length-1,count:nodes.length});
 };
 const ordinary=projected.nodes.filter(n=>n.kind!=='metric');
 append('before','Feeds into','environment',ordinary.filter(n=>n.rank<0));
 append('focus','In focus','data',ordinary.filter(n=>n.rank===0));
 append('after','Feeds onward','operations',ordinary.filter(n=>n.rank>0));
 append('metrics','KPIs','metrics',projected.nodes.filter(n=>n.kind==='metric'));
 const rowCount=Math.max(1,...columns.map(c=>c.length)),positions=new Map();
 columns.forEach((nodes,col)=>{const first=Math.floor((rowCount-nodes.length)/2);nodes.forEach((n,i)=>positions.set(n.id,{x:64+col*(cardWidth+gap),y:142+(first+i)*(cardHeight+rowGap),w:cardWidth,h:cardHeight,col,row:first+i}));});
 const width=128+columns.length*cardWidth+Math.max(0,columns.length-1)*gap,height=142+rowCount*(cardHeight+rowGap),routes=new Map(),branches=new Map(),ports=[],corridors=Array.from({length:rowCount},(_,r)=>({y:142+r*(cardHeight+rowGap)+cardHeight,height:rowGap,tracks:0}));
 const incoming=new Map(),outgoing=new Map();
 for(const e of projected.edges){
  if(!incoming.has(e.target))incoming.set(e.target,[]);incoming.get(e.target).push(e);
  if(!outgoing.has(e.source))outgoing.set(e.source,[]);outgoing.get(e.source).push(e);
  const s=positions.get(e.source),t=positions.get(e.target),sy=s.y+s.h/2,ty=t.y+t.h/2;
  // Common source exits and destination entries form shared trunks. Each row has only two
  // highway tracks (ordinary / conditional), independent of the number of relationships.
  const offset=e.conditional?12:0,sx=s.x+s.w+56+offset,tx=t.x-56-offset;
  let middle;
  if(s.col+1===t.col)middle=[[sx,sy],[sx,ty]];
  else{const corridor=corridors[s.row],y=corridor.y+rowGap/2+offset;corridor.tracks=Math.max(corridor.tracks,e.conditional?2:1);middle=[[sx,sy],[sx,y],[tx,y],[tx,ty]];}
  const distinct=ps=>ps.filter((v,i)=>!i||v[0]!==ps[i-1][0]||v[1]!==ps[i-1][1]);
  const points=distinct([[s.x+s.w,sy],[s.x+s.w+stem,sy],...middle,[t.x-stem,ty],[t.x,ty]]);
  routes.set(e,points);branches.set(e,points.slice(1,-1));
 }
 for(const [id,p] of positions)for(const [side,map] of [['in',incoming],['out',outgoing]]){
  const list=map.get(id);if(!list?.length)continue;const y=p.y+p.h/2;
  ports.push({id,side,count:list.length,conditional:list.every(e=>e.conditional),points:side==='in'?[[p.x-stem,y],[p.x,y]]:[[p.x+p.w,y],[p.x+p.w+stem,y]]});
 }
 const lanes=groups.map(g=>({...g,x:Math.max(12,64+g.first*(cardWidth+gap)-gap/2),width:(g.last-g.first+1)*(cardWidth+gap)-(g.first===0?36:0)}));
 return {positions,lanes,corridors,routes,branches,ports,bundles:bundleRoutes(branches),trackPitch:12,width,height};
}
// Draw each shared stretch once, and retain every relationship travelling along it. Splitting
// at collinear endpoints also makes hovering a partially shared trunk offer the correct links.
export function bundleRoutes(routes){
 const lines=new Map(),curves=new Map();
 for(const [edge,points] of routes)for(const part of pathParts(points)){
  if(part.arc){const key=part.d+'|'+edge.conditional;if(!curves.has(key))curves.set(key,{d:part.d,conditional:edge.conditional,edges:[]});curves.get(key).edges.push(edge);continue;}
  const [a,b]=part.points,horizontal=a[1]===b[1],fixed=a[horizontal?1:0],lo=Math.min(a[horizontal?0:1],b[horizontal?0:1]),hi=Math.max(a[horizontal?0:1],b[horizontal?0:1]);
  if(lo===hi)continue;const key=[horizontal,fixed,edge.conditional].join('|');
  if(!lines.has(key))lines.set(key,{horizontal,fixed,conditional:edge.conditional,segments:[]});lines.get(key).segments.push({lo,hi,edge});
 }
 const bundles=[...curves.values()];
 for(const {horizontal,fixed,conditional,segments} of lines.values()){
  const stops=[...new Set(segments.flatMap(s=>[s.lo,s.hi]))].sort((a,b)=>a-b);
  for(let i=1;i<stops.length;i++){
   const lo=stops[i-1],hi=stops[i],edges=[...new Set(segments.filter(s=>s.lo<=lo&&s.hi>=hi).map(s=>s.edge))];if(!edges.length)continue;
   const points=horizontal?[[lo,fixed],[hi,fixed]]:[[fixed,lo],[fixed,hi]];
   bundles.push({d:`M${points[0]} L${points[1]}`,points,conditional,edges});
  }
 }
 return bundles;
}
function pathParts(points){
 if(!points?.length)return [];const parts=[];let cursor=points[0];
 const line=end=>{if(cursor[0]!==end[0]||cursor[1]!==end[1])parts.push({points:[cursor,end],d:`M${cursor} L${end}`});cursor=end;};
 for(let i=1;i<points.length-1;i++){
  const a=points[i-1],b=points[i],c=points[i+1],before=Math.hypot(b[0]-a[0],b[1]-a[1]),after=Math.hypot(c[0]-b[0],c[1]-b[1]),cross=(b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]);
  if(!cross){line(b);continue;}const r=Math.min(16,before/2,after/2),start=[b[0]+(a[0]-b[0])*r/before,b[1]+(a[1]-b[1])*r/before],end=[b[0]+(c[0]-b[0])*r/after,b[1]+(c[1]-b[1])*r/after];
  line(start);parts.push({arc:true,d:`M${start} A${r},${r} 0 0 ${cross>0?1:0} ${end}`});cursor=end;
 }
 line(points.at(-1));return parts;
}
export function edgePath(points){
 if(!points?.length)return '';
 return `M${points[0]}`+pathParts(points).map(part=>part.d.slice(part.d.indexOf(' '))).join('');
}
