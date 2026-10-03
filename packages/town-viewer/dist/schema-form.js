// Engine settings rendered from the engine's JSON Schema: groups (in x-order), defaults, bounds, units, effects and
// advanced flags (x-unit, x-effects, x-advanced). A field is one compact row (short title, input, unit); its
// description, default, effects and path sit behind an (i) button, and the fields of a group lay out in two columns. Nested objects (a value per era, a season's temperatures) render as
// labelled sub-rows, lists as a checked JSON box, and settings the engine marks x-status "not-modelled" or
// x-deprecated stay visible but disabled with the reason. The form reports only values that differ from a base (the
// schema defaults, or a town's own configuration), so the engine stays authoritative.
const SUB_LABEL={pre_1945:'Pre-1945',postwar:'Post-war',modern:'Modern',mean_c:'Mean',sd_c:'Std dev',min_c:'Min',max_c:'Max',up_to:'Up to',price:'Price'};
export const prettyKey=k=>SUB_LABEL[k]||(s=>s.charAt(0).toUpperCase()+s.slice(1))(String(k).replaceAll('_',' '));
// Field titles read as sentences: a generated Title Case title ("Analyst Queue Days Max") becomes "Analyst queue days
// max", and the utility acronyms keep their capitals ("Rpa Coverage" → "RPA coverage"). A title someone wrote stays.
const ACRONYMS=new Set(['AMI','AMR','VEE','RPA','OSM','PV','EV','HST','AC','DC','GJ','NSF','PAD','ANSI','CT','SAP','KV','KVA','KW','KWH','ID','IDS','API','CSV','JSON','YAML','UTC','GIS','HV','LV','MV','PRV','SAIDI','SAIFI','COM','RES','MRU','VPN','AMP']);
export function sentenceTitle(title){const t=String(title||'');if(!/^[A-Z][a-z0-9]*( [A-Z0-9][a-z0-9]*)*$/.test(t))return t;
 return t.split(' ').map((w,i)=>{const up=w.toUpperCase();if(ACRONYMS.has(up))return up;return i?w.toLowerCase():w;}).join(' ');}
function scalarType(p){return p.enum?'enum':p.type==='boolean'?'boolean':p.type==='integer'?'integer':p.type==='number'?'number':'text';}
function statusOf(p){const reason=p['x-status-reason']||p['x-reason']||p['x-note']||'';
 if(p['x-deprecated'])return {status:'deprecated',reason:typeof p['x-deprecated']==='string'?p['x-deprecated']:reason||'Deprecated.'};
 if(p['x-status']&&p['x-status']!=='modelled')return {status:p['x-status'],reason:reason||(p['x-status']==='not-modelled'?'Not modelled by the engine yet.':String(p['x-status']))};return null;}
// One schema property → a field description (scalar, nested object of scalars, or JSON for lists and maps).
function describe(defs,key,p0){
 const resolve=s=>{if(s?.$ref){const {$ref,...rest}=s;return {...(defs[$ref.split('/').pop()]||{}),...rest,title:rest.title,_ref:true};}if(s?.allOf?.length===1&&s.allOf[0].$ref){const {allOf,...rest}=s;return resolve({...rest,$ref:allOf[0].$ref});}return s||{};};
 let p=resolve(p0),nullable=false;
 if(Array.isArray(p.anyOf)){const opts=p.anyOf.filter(o=>o.type!=='null');nullable=opts.length<p.anyOf.length;if(opts.length===1){const {anyOf,...rest}=p;p={...resolve(opts[0]),...rest,title:rest.title,description:rest.description??resolve(opts[0]).description};}}
 const title=p.title||prettyKey(key),base={key,title,description:p.description||'',min:p.minimum,max:p.maximum,xmin:p.exclusiveMinimum,xmax:p.exclusiveMaximum,unit:p['x-unit']||'',advanced:!!p['x-advanced'],effects:p['x-effects']||[],options:p.enum||null,default:p.default,nullable,...(statusOf(p)||{})};
 if(p.type==='object'&&p.properties&&Object.values(p.properties).every(c=>{const r=resolve(c);return !r.properties&&r.type!=='array'&&r.type!=='object';}))
  return {...base,type:'object',children:Object.entries(p.properties).map(([k,c])=>{const d=describe(defs,k,c);return {...d,title:SUB_LABEL[k]||(d.title===prettyKey(k)||/^[A-Z][a-z]*( [A-Z0-9][a-z0-9]*)*$/.test(d.title)?prettyKey(k):d.title),unit:d.unit||base.unit};})};
 if(p.type==='array'||p.type==='object'||p.anyOf)return {...base,type:'json',array:p.type==='array',items:p.items?resolve(p.items):null,minItems:p.minItems,maxItems:p.maxItems};
 return {...base,type:scalarType(p),maxLength:p.maxLength};
}
// groups: optional (key, groupSchema) => boolean, e.g. only the town-scoped groups of the full SimConfig schema.
export function schemaFields(schema,{groups=null}={}){
 const defs=schema?.$defs||{},resolve=s=>s?.$ref?defs[s.$ref.split('/').pop()]||{}:s||{},out=[];
 const list=Object.entries(schema?.properties||{}).map(([group,gs],i)=>({group,g:resolve(gs),i})).filter(({group,g})=>g.properties&&(!groups||groups(group,g)));
 list.sort((a,b)=>(a.g['x-order']??1e9)-(b.g['x-order']??1e9)||a.i-b.i);
 for(const {group,g} of list){const gst=statusOf(g);
  for(const [key,p0] of Object.entries(g.properties)){const f=describe(defs,key,p0);if(gst&&!f.status)Object.assign(f,gst);
   out.push({group,groupTitle:g.title||group,groupDescription:g.description||'',...f,path:group+'.'+key,disabled:!!f.status});}}
 return out;
}
const isNum=v=>typeof v==='number'&&Number.isFinite(v);
function checkItem(item,spec,i){if(!spec)return null;const at=`Item ${i+1}`;
 if(spec.type==='number'||spec.type==='integer')return isNum(item)&&(spec.type==='number'||Number.isInteger(item))?null:`${at} must be a ${spec.type==='integer'?'whole ':''}number.`;
 if(spec.type==='string')return typeof item==='string'?null:`${at} must be text.`;
 if(spec.properties){if(!item||typeof item!=='object'||Array.isArray(item))return `${at} must be an object like {${Object.keys(spec.properties).map(k=>`"${k}": …`).join(', ')}}.`;
  for(const k of spec.required||Object.keys(spec.properties))if(!(k in item))return `${at} needs "${k}".`;
  for(const [k,c] of Object.entries(spec.properties)){if(!(k in item))continue;const v=item[k],ok=c.anyOf?c.anyOf.some(o=>o.type==='null'?v===null:o.type==='number'||o.type==='integer'?isNum(v):o.type==='string'?typeof v==='string':true):c.type==='number'||c.type==='integer'?isNum(v):c.type==='string'?typeof v==='string':true;if(!ok)return `${at}: "${k}" has the wrong type.`;}
  if(spec.additionalProperties===false){const extra=Object.keys(item).find(k=>!(k in spec.properties));if(extra)return `${at}: unknown key "${extra}".`;}}
 return null;}
export function parseField(f,raw){
 if(f.type==='boolean')return {ok:true,value:!!raw};
 if(f.type==='object'){const value={};for(const c of f.children){const r=parseField(c,raw?.[c.key]);if(!r.ok)return {ok:false,error:`${c.title}: ${r.error}`};value[c.key]=r.value;}return {ok:true,value};}
 if(f.type==='json'){let v;try{v=typeof raw==='string'?JSON.parse(raw):raw;}catch{return {ok:false,error:'Enter valid JSON.'};}
  if(v===null&&f.nullable)return {ok:true,value:null};
  if(f.array){if(!Array.isArray(v))return {ok:false,error:'Enter a JSON list, for example [1, 2].'};if(f.minItems!=null&&v.length<f.minItems)return {ok:false,error:`At least ${f.minItems} items.`};if(f.maxItems!=null&&v.length>f.maxItems)return {ok:false,error:`At most ${f.maxItems} items.`};
   for(let i=0;i<v.length;i++){const e=checkItem(v[i],f.items,i);if(e)return {ok:false,error:e};}}
  else if(!v||typeof v!=='object')return {ok:false,error:'Enter a JSON object.'};
  return {ok:true,value:v};}
 if((raw===''||raw==null)&&f.nullable)return {ok:true,value:null};
 if(f.type==='enum'||f.type==='text'){const s=String(raw??'');if(f.maxLength!=null&&s.length>f.maxLength)return {ok:false,error:`At most ${f.maxLength} characters.`};return {ok:true,value:s};}
 const v=Number(raw);if(raw===''||raw==null||!Number.isFinite(v))return {ok:false,error:'Enter a number.'};
 if(f.type==='integer'&&!Number.isInteger(v))return {ok:false,error:'Enter a whole number.'};
 if(f.min!=null&&v<f.min)return {ok:false,error:`At least ${f.min}.`};if(f.max!=null&&v>f.max)return {ok:false,error:`At most ${f.max}.`};
 if(f.xmin!=null&&v<=f.xmin)return {ok:false,error:`More than ${f.xmin}.`};if(f.xmax!=null&&v>=f.xmax)return {ok:false,error:`Less than ${f.xmax}.`};
 return {ok:true,value:v};
}
// Structural equality for settings values (key order does not matter).
export function same(a,b){if(a===b)return true;if(!a||!b||typeof a!=='object'||typeof b!=='object'||Array.isArray(a)!==Array.isArray(b))return false;
 const ka=Object.keys(a),kb=Object.keys(b);return ka.length===kb.length&&ka.every(k=>Object.prototype.hasOwnProperty.call(b,k)&&same(a[k],b[k]));}
const refOf=(f,base)=>base?base[f.group]?.[f.key]:f.default;
// values: {group:{key:value}} → only the entries that differ from the field defaults (or from `base`, e.g. a town's config).
export function overridesFrom(fields,values,base=null){
 const out={};for(const f of fields){const v=values?.[f.group]?.[f.key];if(v===undefined||same(v,refOf(f,base)))continue;(out[f.group]||={})[f.key]=v;}
 return out;
}
// Changed settings, counted per value: a nested object counts each sub-value that differs.
export function changeList(fields,values,base=null){
 const out=[];for(const f of fields){const v=values?.[f.group]?.[f.key],r=refOf(f,base);if(v===undefined||same(v,r))continue;
  if(f.type==='object'&&v&&r&&typeof r==='object'){for(const c of f.children)if(!same(v[c.key],r[c.key]))out.push(f.path+'.'+c.key);}else out.push(f.path);}
 return out;
}
// A search over titles, descriptions, keys and group titles; every word must match.
export function fieldMatches(f,query){const words=String(query||'').toLowerCase().split(/\s+/).filter(Boolean);if(!words.length)return true;
 const text=[f.title,f.description,f.path||f.group+'.'+f.key,f.key,f.groupTitle,f.unit,...(f.children||[]).map(c=>c.title)].join(' ').toLowerCase().replaceAll('_',' ');
 return words.every(w=>text.includes(w.replaceAll('_',' ')));}
const show=v=>v===null?'none':v===undefined?'—':typeof v==='object'?Array.isArray(v)?JSON.stringify(v):Object.values(v).join(' / '):String(v);
const jsonText=v=>v==null?'null':Array.isArray(v)&&v.some(x=>x&&typeof x==='object')?'[\n'+v.map(x=>' '+JSON.stringify(x)).join(',\n')+'\n]':JSON.stringify(v);
// Options: values ({group:{key:value}}), base (what "changed" compares with; default the schema defaults), groups
// (filter), showAdvanced, collapsible (cards fold; `open` lists the groups open at first), skip (paths rendered
// elsewhere), decorate(field,row,input) and onChange(overrides, changes). Returns {fields, values, set, filter, changes}.
export function renderSchemaForm(el,schema,{values={},base=null,groups=null,showAdvanced=false,collapsible=false,open=[],skip=[],decorate=null,baseLabel='',onChange=()=>{}}={}){
 const info=(label,lines)=>{const text=lines.filter(Boolean);if(!text.length)return null;const b=mk('button','schema-info','i');b.type='button';b.setAttribute('aria-label','About '+label);b.setAttribute('aria-expanded','false');b.title=text[0];const pop=mk('div','schema-pop');pop.setAttribute('role','note');for(const t of text){pop.append(mk('p',null,t));}return [b,pop];};
 const fields=schemaFields(schema,{groups}),state=structuredClone(values||{}),byGroup=new Map(),rows=new Map(),badges=new Map(),mk=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e;};
 for(const f of fields){if(!byGroup.has(f.group))byGroup.set(f.group,[]);byGroup.get(f.group).push(f);}
 const changes=()=>changeList(fields,state,base),refLabel=baseLabel||(base?'This town':'Default');
 function mark(f){const r=rows.get(f.path),ref=refOf(f,base),cur=state[f.group]?.[f.key],changed=cur!==undefined&&!same(cur,ref);if(r){r.row.classList.toggle('is-changed',changed);r.was.textContent=changed?`${refLabel}: ${show(ref)}`:'';}
  const n=changeList(byGroup.get(f.group),state,base).length,b=badges.get(f.group);if(b){b.textContent=n?`${n} changed`:'';b.hidden=!n;}}
 function commit(f,value){(state[f.group]||={})[f.key]=value;mark(f);onChange(overridesFrom(fields,state,base),changes());}
 el.replaceChildren();
 for(const [group,list] of byGroup){
  const card=mk(collapsible?'details':'section','settings-card schema-group'),h=mk('h3',null,list[0].groupTitle),badge=mk('span','schema-badge'),ginfo=info(list[0].groupTitle,[list[0].groupDescription]),body=mk('div','schema-fields');card.dataset.group=group;badge.hidden=true;badges.set(group,badge);
  const head=mk(collapsible?'summary':'div','schema-group-head'+(collapsible?' schema-summary':'')),count=mk('span','schema-count',`${list.filter(f=>!skip.includes(f.path)).length}`);head.append(h,badge,count);if(ginfo){head.classList.add('has-pop');head.append(...ginfo);}if(collapsible)card.open=open==='all'||open.includes(group);card.append(head,body);
  for(const f of list){if(skip.includes(f.path))continue;const hidden=f.advanced&&!showAdvanced;
   const row=mk(f.type==='object'?'div':'label','schema-field'+(f.disabled?' is-disabled':'')),name=mk('span','schema-name',sentenceTitle(f.title)),err=mk('small','schema-error'),was=mk('small','schema-was');row.dataset.path=f.path;if(hidden)row.hidden=true;row.title=f.description||'';
   const current=state[f.group]?.[f.key]??f.default;let input,inputs=[];
   if(f.type==='boolean'){input=mk('input');input.type='checkbox';input.checked=!!current;}
   else if(f.type==='enum'){input=mk('select');for(const o of f.options){const opt=mk('option',null,String(o).replaceAll('_',' '));opt.value=o;input.append(opt);}input.value=current;}
   else if(f.type==='json'){input=mk('textarea','schema-json');input.spellcheck=false;input.value=jsonText(current);input.rows=Math.min(8,input.value.split('\n').length+(input.value.length>60?1:0));row.classList.add('schema-wide');}
   else if(f.type==='object'){input=mk('div','schema-subs');row.setAttribute('role','group');row.setAttribute('aria-label',f.description||f.title);
    for(const c of f.children){const lab=mk('label','schema-sub'),cap=mk('span',null,c.title),i=mk('input');i.type='number';i.step=c.type==='integer'?'1':'any';if(c.min!=null)i.min=c.min;if(c.max!=null)i.max=c.max;i.value=current?.[c.key]??'';i.dataset.key=c.key;i.name=f.path+'.'+c.key;i.disabled=f.disabled;lab.append(cap,i);input.append(lab);inputs.push(i);}row.classList.add('schema-wide');}
   else{input=mk('input');input.type=f.type==='text'?'text':'number';if(f.min!=null)input.min=f.min;if(f.max!=null)input.max=f.max;if(f.maxLength!=null)input.maxLength=f.maxLength;if(f.type!=='text')input.step=f.type==='integer'?'1':'any';input.value=current??'';if(f.nullable)input.placeholder='none';}
   if(f.type!=='object'){input.name=f.path;input.dataset.group=f.group;input.dataset.key=f.key;input.disabled=f.disabled;inputs=[input];}
   const finfo=info(sentenceTitle(f.title),[f.description,f.status&&`${f.status==='deprecated'?'Deprecated':f.status==='not-modelled'?'Not modelled':'Unavailable'}: ${f.reason}`,[f.unit&&`Unit ${f.unit}`,f.default!==undefined&&`Default ${show(f.default)}`,f.advanced&&'Advanced'].filter(Boolean).join(' · '),f.effects.length&&`Affects ${f.effects.join(', ')}`,f.path]);if(finfo){row.classList.add('has-pop');name.append(finfo[0]);}
   err.setAttribute('role','alert');
   const read=()=>f.type==='boolean'?input.checked:f.type==='object'?Object.fromEntries(inputs.map(i=>[i.dataset.key,i.value])):input.value;
   const check=()=>{const res=parseField(f,read());for(const i of inputs)i.setAttribute('aria-invalid',String(!res.ok));err.textContent=res.ok?'':res.error;return res;};
   for(const i of inputs){i.onchange=()=>{const res=check();if(res.ok)commit(f,res.value);};if(f.type==='json')i.oninput=check;}
   const ctl=mk('span','schema-control');ctl.append(input);if(f.unit&&f.type!=='json'&&f.type!=='object')ctl.append(mk('span','schema-unit',f.unit));if(f.status)ctl.append(mk('span','schema-status',f.status==='deprecated'?'Deprecated':f.status==='not-modelled'?'Not modelled':'Unavailable'));
   row.append(name,ctl,was,err);if(finfo)row.append(finfo[1]);
   decorate?.(f,row,input);rows.set(f.path,{row,input,inputs,was,f});body.append(row);mark(f);}
  el.append(card);}
 // Sets a value from outside the form (a seed button, a reset), updating its inputs.
 function set(path,value,{silent=false}={}){const f=fields.find(x=>x.path===path);if(!f)return false;(state[f.group]||={})[f.key]=value;const r=rows.get(path);
  if(r){if(f.type==='boolean')r.input.checked=!!value;else if(f.type==='object')for(const i of r.inputs)i.value=value?.[i.dataset.key]??'';else r.input.value=f.type==='json'?jsonText(value):value??'';for(const i of r.inputs)i.setAttribute('aria-invalid','false');}
  mark(f);if(!silent)onChange(overridesFrom(fields,state,base),changes());return true;}
 // Shows only matching settings; cards with a match open while a search is active. Returns the number of matches.
 function filter(query){let n=0;for(const {row,f} of rows.values()){const hit=fieldMatches(f,query)&&(showAdvanced||!f.advanced||!!query);row.hidden=!hit;if(hit)n++;}
  for(const card of el.querySelectorAll('.schema-group')){const any=[...card.querySelectorAll('.schema-field')].some(r=>!r.hidden);card.hidden=!any&&!!query;if(collapsible&&query&&any)card.open=true;const c=card.querySelector('.schema-count');if(c)c.textContent=String([...card.querySelectorAll('.schema-field')].filter(r=>!r.hidden).length);}return n;}
 return {fields,values:state,set,filter,changes,invalid:()=>[...el.querySelectorAll('[aria-invalid="true"]')].length};
}
