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
 return {before,after,visible,edges:graph.edges.filter(e=>visible.has(e.source)&&visible.has(e.target)&&(conditional||e.kind!=='conditional'))};
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
 return {nodes,edges:[...edges.values()]};
}
// Interval colouring gives overlapping connections different tracks. Disjoint segments can reuse a
// track. Only the short entry/exit connectors at a card are shared; the corridors keep separate lines.
function freeTrack(tracks,lo,hi){const i=tracks.findIndex(t=>t.every(s=>hi<s.lo||lo>s.hi));return i<0?tracks.length:i;}
function reserve(tracks,lo,hi){const i=freeTrack(tracks,lo,hi);(tracks[i]??=[]).push({lo,hi});return i;}
export function layoutGraph(projected){
 const maxRows=4,cardWidth=244,pitch=8,stem=28,cells=new Map(),columns=[],groups=[],incoming=new Map(),outgoing=new Map();
 for(const e of projected.edges){if(!incoming.has(e.target))incoming.set(e.target,[]);incoming.get(e.target).push(e);if(!outgoing.has(e.source))outgoing.set(e.source,[]);outgoing.get(e.source).push(e);}
 for(const lane of LANES){
  const nodes=projected.nodes.filter(n=>n.lane===lane).sort((a,b)=>(a.kind==='group')-(b.kind==='group')||a.title.localeCompare(b.title)),first=columns.length;
  for(let c=0;c<Math.max(1,Math.ceil(nodes.length/maxRows));c++){
   const rows=nodes.slice(c*maxRows,(c+1)*maxRows),col=columns.length;columns.push({width:rows.length?cardWidth:184});
   rows.forEach((n,row)=>cells.set(n.id,{col,row,h:88,bandHeight:88}));
  }
  groups.push({id:lane,first,last:columns.length-1,count:nodes.length});
 }
 const rowCount=Math.max(1,...[...cells.values()].map(c=>c.row+1)),horizontal=Array.from({length:rowCount+1},()=>[]),vertical=Array.from({length:columns.length+1},()=>[]),plans=new Map();
 const edges=[...projected.edges].sort((a,b)=>Math.abs(cells.get(b.source).col-cells.get(b.target).col)-Math.abs(cells.get(a.source).col-cells.get(a.target).col)||a.source.localeCompare(b.source)||a.target.localeCompare(b.target));
 for(const e of edges){
  const s=cells.get(e.source),t=cells.get(e.target),exit=s.col+1,entry=t.col,plan={exit,entry};
  if(exit===entry){plan.direct=true;plan.sTrack=reserve(vertical[exit],Math.min(s.row,t.row),Math.max(s.row,t.row)+1);}
  else{
   const low=Math.min(s.row,t.row),high=Math.max(s.row,t.row),gaps=low===high?[low,low+1]:Array.from({length:high-low},(_,i)=>low+i+1),lo=Math.min(exit,entry),hi=Math.max(exit,entry);
   gaps.sort((a,b)=>(freeTrack(horizontal[a],lo,hi)-freeTrack(horizontal[b],lo,hi))*10+Math.abs(a-s.row-1)-Math.abs(b-s.row-1));
   plan.gap=gaps[0];plan.hTrack=reserve(horizontal[plan.gap],lo,hi);
   plan.sTrack=reserve(vertical[exit],Math.min(s.row,plan.gap),Math.max(s.row+1,plan.gap));
   plan.tTrack=reserve(vertical[entry],Math.min(t.row,plan.gap),Math.max(t.row+1,plan.gap));
  }
  plans.set(e,plan);
 }
 // Split the common card connectors into independently spaced leads, reserving a small fan area
 // on each side of the alley. Leads on opposite sides must not accidentally merge in the corridor.
 const portGroups=new Map();
 const portGroup=(alley,row)=>{const key=alley+':'+row;if(!portGroups.has(key))portGroups.set(key,{row,edges:new Set(),cells:new Set()});return portGroups.get(key);};
 for(const e of projected.edges){const p=plans.get(e),s=cells.get(e.source),t=cells.get(e.target);for(const [alley,c] of [[p.exit,s],[p.entry,t]]){const g=portGroup(alley,c.row);g.edges.add(e);g.cells.add(c);}}
 for(const g of portGroups.values()){
  g.edges=[...g.edges].sort((a,b)=>(plans.get(a).gap??g.row+.5)-(plans.get(b).gap??g.row+.5)||cells.get(a.source).col-cells.get(b.source).col||cells.get(a.target).col-cells.get(b.target).col);
  g.height=Math.max(88,g.edges.length*pitch+32);for(const c of g.cells)c.bandHeight=Math.max(c.bandHeight,g.height);
 }
 const alleys=[];let x=24;
 for(let i=0;i<=columns.length;i++){
  const count=(col,map)=>Math.max(0,...[...cells].filter(([,c])=>c.col===col).map(([id])=>map.get(id)?.length||0));
  const outFan=stem+count(i-1,outgoing)*pitch+24,inFan=stem+count(i,incoming)*pitch+24,channelWidth=Math.max(64,vertical[i].length*pitch+32),width=outFan+channelWidth+inFan;
  alleys.push({x,width,outFan,inFan,channelWidth});x+=width;if(columns[i]){columns[i].x=x;x+=columns[i].width;}
 }
 const rowHeights=Array.from({length:rowCount},(_,r)=>Math.max(88,...[...cells.values()].filter(c=>c.row===r).map(c=>c.bandHeight))),rowY=[],corridors=[];let y=84;
 for(let r=0;r<=rowCount;r++){const height=Math.max(r===0?58:r===rowCount?74:116,horizontal[r].length*pitch+40);corridors.push({y,height,tracks:horizontal[r].length});y+=height;if(r<rowCount){rowY.push(y);y+=rowHeights[r];}}
 const positions=new Map([...cells].map(([id,c])=>[id,{x:columns[c.col].x,y:rowY[c.row]+(rowHeights[c.row]-c.h)/2,w:cardWidth,h:c.h,col:c.col,row:c.row}]));
 const lanes=groups.map(g=>({id:g.id,count:g.count,x:alleys[g.first].x+alleys[g.first].width/2,width:alleys[g.last+1].x+alleys[g.last+1].width/2-(alleys[g.first].x+alleys[g.first].width/2)}));
 const trackX=(alley,track)=>alleys[alley].x+alleys[alley].outFan+alleys[alley].channelWidth/2+(track-(vertical[alley].length-1)/2)*pitch;
 const trackY=p=>corridors[p.gap].y+corridors[p.gap].height/2+(p.hTrack-(horizontal[p.gap].length-1)/2)*pitch;
 const portY=(alley,p,e)=>{const g=portGroup(alley,p.row);return p.y+p.h/2+(g.edges.indexOf(e)-(g.edges.length-1)/2)*pitch;};
 const ports=[],portZones=new Map();
 for(const [id,p] of positions){
  const cy=p.y+p.h/2,bandTop=rowY[p.row],bandHeight=rowHeights[p.row];
  for(const [side,list] of [['in',incoming.get(id)],['out',outgoing.get(id)]])if(list?.length){
   const a=alleys[side==='in'?p.col:p.col+1],points=side==='in'?[[p.x-stem,cy],[p.x,cy]]:[[p.x+p.w,cy],[p.x+p.w+stem,cy]];
   ports.push({id,side,points,conditional:list.every(e=>e.conditional),count:list.length});
   portZones.set(id+':'+side,{x:side==='in'?p.x-a.inFan:p.x+p.w,y:bandTop,w:side==='in'?a.inFan:a.outFan,h:bandHeight});
  }
 }
 const routes=new Map(),branches=new Map();
 for(const e of projected.edges){const p=plans.get(e),s=positions.get(e.source),t=positions.get(e.target),sy=portY(p.exit,s,e),ty=portY(p.entry,t,e),sx=trackX(p.exit,p.sTrack);
  const scy=s.y+s.h/2,tcy=t.y+t.h/2,sFan=s.x+s.w+stem+16+outgoing.get(e.source).indexOf(e)*pitch,tFan=t.x-stem-16-incoming.get(e.target).indexOf(e)*pitch;
  const middle=p.direct?[[sx,sy],[sx,ty]]:[[sx,sy],[sx,trackY(p)],[trackX(p.entry,p.tTrack),trackY(p)],[trackX(p.entry,p.tTrack),ty]];
  const points=[[s.x+s.w,scy],[s.x+s.w+stem,scy],[sFan,scy],[sFan,sy],...middle,[tFan,ty],[tFan,tcy],[t.x-stem,tcy],[t.x,tcy]];
  const distinct=ps=>ps.filter((v,i)=>!i||v[0]!==ps[i-1][0]||v[1]!==ps[i-1][1]);
  routes.set(e,distinct(points));branches.set(e,distinct(points.slice(1,-1)));
 }
 return {positions,lanes,corridors,routes,branches,ports,portZones,trackPitch:pitch,width:x+24,height:y+24};
}
export function edgePath(points){
 if(!points?.length)return '';
 let path=`M${points[0][0]},${points[0][1]}`;
 for(let i=1;i<points.length-1;i++){
  const a=points[i-1],b=points[i],c=points[i+1],before=Math.hypot(b[0]-a[0],b[1]-a[1]),after=Math.hypot(c[0]-b[0],c[1]-b[1]),cross=(b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]);
  if(!cross){path+=` L${b[0]},${b[1]}`;continue;}
  const r=Math.min(16,before/2,after/2);
  path+=` L${b[0]+(a[0]-b[0])*r/before},${b[1]+(a[1]-b[1])*r/before} A${r},${r} 0 0 ${cross>0?1:0} ${b[0]+(c[0]-b[0])*r/after},${b[1]+(c[1]-b[1])*r/after}`;
 }
 const end=points.at(-1);return path+` L${end[0]},${end[1]}`;
}
