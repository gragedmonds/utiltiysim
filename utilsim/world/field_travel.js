const $=id=>document.getElementById(id);
const form=$('estimate');
let identity,revision=0;
function message(text,error=false){$('message').textContent=text;$('message').className=error?'error':'';}
async function request(path,body){
 const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{cache:'no-store'});
 const value=await response.json();if(!response.ok)throw Error(value.error||'Unable to load this estimate.');return value;
}
function duration(seconds){const minutes=Math.floor(seconds/60),remainder=seconds%60;return `${minutes}m ${remainder}s`;}
function render(quote){
 $('result').hidden=false;$('metrics').replaceChildren();$('route').replaceChildren();
 $('route').hidden=quote.status!=='ready';$('binding').textContent='';
 if(quote.status!=='ready'){$('summary').textContent='Visit estimate unavailable';message(quote.reason,true);return;}
 $('summary').textContent=`Total visit: ${duration(quote.totalSeconds)}`;
 const labels={mobilisation:'Preparation',outbound:'Drive to service',work:'On-site work',return:'Drive to depot'};
 for(const [key,value] of Object.entries(quote.durationSeconds)){
  const group=document.createElement('div'),term=document.createElement('dt'),detail=document.createElement('dd');
  term.textContent=labels[key];detail.textContent=duration(value);group.append(term,detail);$('metrics').append(group);
 }
 const points=quote.outbound.points,x=points.map(p=>p.x),z=points.map(p=>p.z);
 const left=Math.min(...x),top=Math.min(...z),width=Math.max(1,Math.max(...x)-left),height=Math.max(1,Math.max(...z)-top),pad=Math.max(width,height)*.1;
 $('route').setAttribute('viewBox',`${left-pad} ${top-pad} ${width+pad*2} ${height+pad*2}`);
 const line=document.createElementNS('http://www.w3.org/2000/svg','polyline');
 line.setAttribute('points',points.map(p=>`${p.x},${p.z}`).join(' '));line.setAttribute('fill','none');line.setAttribute('stroke','#14724b');line.setAttribute('stroke-width','4');line.setAttribute('vector-effect','non-scaling-stroke');$('route').append(line);
 for(const [point,label,color] of [[points[0],'Depot','#183c31'],[points.at(-1),'Service','#c06920']]){
  const marker=document.createElementNS('http://www.w3.org/2000/svg','circle'),title=document.createElementNS('http://www.w3.org/2000/svg','title');
  marker.setAttribute('cx',point.x);marker.setAttribute('cy',point.z);marker.setAttribute('r',Math.max(width,height)*.012);marker.setAttribute('fill',color);title.textContent=label;marker.append(title);$('route').append(marker);
 }
 $('binding').textContent=`Assignment ${quote.assignmentId} · depot ${quote.depotId} · ${(quote.outbound.lengthMeters/1000).toFixed(2)} km outbound, ${(quote.return.lengthMeters/1000).toFixed(2)} km return`;
 message('Estimate ready. No crew time has been reserved.');
}
form.addEventListener('input',()=>{revision++;$('result').hidden=true;message('Assumptions changed. Estimate again to refresh the result.');});
form.addEventListener('submit',async event=>{
 event.preventDefault();if(!identity)return;const requestedRevision=revision;$('submit').disabled=true;$('result').hidden=true;message('Calculating the saved-road route…');
 try{
  const values=new FormData(form);
  const body={schemaVersion:'field-travel-quote/1',environmentId:identity.environmentId,worldFingerprint:identity.worldFingerprint,
   assignmentId:values.get('assignmentId'),depotId:values.get('depotId'),mobilisationSeconds:Number(values.get('mobilisation'))*60,
   workSeconds:Number(values.get('work'))*60,speedsKmh:Object.fromEntries(['arterial','collector','local'].map(k=>[k,Number(values.get(k))]))};
  const quote=await request('/api/field-travel/quote',body);if(revision===requestedRevision)render(quote);
 }catch(error){if(revision===requestedRevision)message(error.message,true);}finally{$('submit').disabled=false;}
});
async function load(){
 try{
  const [state,snapshot]=await Promise.all([request('/api/field-execution?limit=100'),request('/api/map/snapshot')]);identity=state;
  for(const item of state.items){if(item.state!=='accepted'||item.assignment.operation!=='repair-water-leak')continue;
   const option=document.createElement('option');option.value=item.assignment.assignmentId;option.label=item.assignment.assetId;$('assignments').append(option);}
  for(const depot of snapshot.facilities||[]){if(depot.kind!=='depot')continue;const option=document.createElement('option');option.value=depot.id;option.textContent=depot.label||depot.id;form.elements.depotId.append(option);}
  if(!form.elements.depotId.options.length){message('This world has no saved depot. A visit cannot be estimated.',true);return;}
  $('submit').disabled=false;message('Choose a saved assignment and review the visit assumptions.');
 }catch(error){message(error.message,true);}
}
load();
