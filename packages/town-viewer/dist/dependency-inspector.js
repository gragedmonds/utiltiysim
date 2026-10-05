const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// A collapsed group or a shared card port can carry several real relationships.
// Preserve them all; an explanation always belongs to one source/target/kind triple.
export function relationshipEntries(edges,graph){
 const seen=new Set(),entries=[];
 for(const edge of edges)for(const link of edge.links||[edge]){
  const key=JSON.stringify([link.source,link.target,link.kind]);if(seen.has(key))continue;seen.add(key);
  entries.push({link,edge:edge.links?edge:null,label:`${graph.byId.get(link.source)?.title||link.source} → ${graph.byId.get(link.target)?.title||link.target}`});
 }
 return entries;
}

export function explanationMarkup(link){
 const x=link.explanation;
 if(!x)return `<p>${esc(link.note||'No detailed explanation is available in this saved map.')}</p><p class="dep-link-scope">This saved map has no calculation detail for this relationship.</p>`;
 const list=(title,items)=>items?.length?`<section><h4>${title}</h4><ul>${items.map(s=>`<li>${esc(s)}</li>`).join('')}</ul></section>`:'';
 return `<span class="dep-link-kind">${esc(x.basis)}</span><p class="dep-link-summary">${esc(x.summary)}</p>${x.formula?`<section class="dep-link-formula"><h4>${link.kind==='influence'?'Downstream calculation':'Calculation / rule'}</h4><code>${esc(x.formula)}</code></section>`:''}${list('How it works',x.steps)}${list('When it applies',x.conditions)}${x.example?`<section class="dep-link-example"><h4>Worked illustration</h4><p>${esc(x.example)}</p></section>`:''}<details class="dep-link-references"><summary>Engine references</summary>${(x.references||[]).map(s=>`<code>${esc(s)}</code>`).join('')}</details><p class="dep-link-scope">Engine logic · illustrations are not values from your run.</p>`;
}

export function createLinkInspector(dialog,{getGraph,trace}){
 const panel=document.createElement('aside');panel.className='dep-link-inspector';panel.hidden=true;
 panel.setAttribute('role','region');panel.setAttribute('aria-label','Connection explanation');dialog.append(panel);
 let entries=[],index=0,pinned=false,timer,anchor={x:0,y:0},returnFocus=null;
 const cancel=()=>clearTimeout(timer);
 function close(restore=false){cancel();panel.hidden=true;pinned=false;trace(null);if(restore&&returnFocus?.isConnected)returnFocus.focus({preventScroll:true});returnFocus=null;}
 function place(){
  const bounds=dialog.getBoundingClientRect(),r=panel.getBoundingClientRect(),gap=12;
  let left=anchor.x+18,top=anchor.y+18;
  if(left+r.width>bounds.right-gap)left=anchor.x-r.width-18;
  if(top+r.height>bounds.bottom-gap)top=anchor.y-r.height-18;
  panel.style.left=Math.max(bounds.left+gap,Math.min(left,bounds.right-r.width-gap))+'px';
  panel.style.top=Math.max(bounds.top+gap,Math.min(top,bounds.bottom-r.height-gap))+'px';
 }
 function content(){
  const item=entries[index],g=getGraph(),s=g.byId.get(item.link.source),t=g.byId.get(item.link.target);
  panel.innerHTML=`<header><span class="dep-eyebrow">INSIDE THE CONNECTION</span><button type="button" data-pin aria-pressed="${pinned}">${pinned?'Pinned':'Pin open'}</button><button type="button" data-close aria-label="Close connection explanation">×</button></header><div class="dep-link-scroll">${entries.length>1?`<label class="dep-link-picker">${entries.length} relationships share this connector<select aria-label="Relationship to explain">${entries.map((e,i)=>`<option value="${i}" ${i===index?'selected':''}>${esc(e.label)} · ${esc(e.link.source)} · ${esc(e.link.kind)}</option>`).join('')}</select></label>`:''}<h3><span>${esc(s?.title||item.link.source)}</span><b aria-label="feeds into">↓</b><span>${esc(t?.title||item.link.target)}</span></h3><p class="dep-link-ids">${esc(item.link.source)} → ${esc(item.link.target)}</p>${explanationMarkup(item.link)}</div>`;
  panel.querySelector('[data-close]').onclick=()=>close(true);
  panel.querySelector('[data-pin]').onclick=e=>{pinned=!pinned;e.currentTarget.textContent=pinned?'Pinned':'Pin open';e.currentTarget.setAttribute('aria-pressed',String(pinned));};
  const picker=panel.querySelector('select');if(picker)picker.onchange=()=>{index=Number(picker.value);pinned=true;content();place();panel.querySelector('select').focus();};
  trace(item.edge);place();
 }
 panel.onpointerenter=cancel;panel.onpointerleave=()=>hideSoon();panel.onfocusin=cancel;
 panel.onfocusout=e=>{if(!panel.contains(e.relatedTarget))hideSoon();};
 function hideSoon(){cancel();if(!pinned&&!panel.contains(document.activeElement))timer=setTimeout(()=>close(),320);}
 function show(edges,x,y,{pin=false,focus=null}={}){
  cancel();if(pinned&&!pin)return;
  const next=relationshipEntries(edges,getGraph());if(!next.length)return;
  entries=next;index=0;pinned=pin;anchor={x,y};returnFocus=focus;panel.hidden=false;content();
  if(focus)panel.querySelector('[data-close]').focus({preventScroll:true});
 }
 const escape=e=>{if(e.key==='Escape'&&!panel.hidden){e.preventDefault();e.stopPropagation();close(true);}};
 dialog.addEventListener('keydown',escape,true);
 return {show,close,hideSoon,place,transformed(){if(!pinned)close();},destroy(){close();dialog.removeEventListener('keydown',escape,true);panel.remove();}};
}
