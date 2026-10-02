// Engine settings rendered from the engine's JSON Schema: groups, defaults, bounds, units, effects and advanced
// flags (x-unit, x-effects, x-advanced). The form reports only values that differ from the defaults, so the engine's
// defaults stay authoritative.
export function schemaFields(schema){
 const defs=schema?.$defs||{},resolve=s=>s?.$ref?defs[s.$ref.split('/').pop()]||{}:s||{},out=[];
 for(const [group,gs] of Object.entries(schema?.properties||{})){const g=resolve(gs);
  for(const [key,p0] of Object.entries(g.properties||{})){const p=resolve(p0),type=p.enum?'enum':p.type==='boolean'?'boolean':p.type==='integer'?'integer':p.type==='number'?'number':'text';
   out.push({group,groupTitle:g.title||group,groupDescription:g.description||'',key,title:p.title||key,description:p.description||'',type,min:p.minimum,max:p.maximum,
    unit:p['x-unit']||'',advanced:!!p['x-advanced'],effects:p['x-effects']||[],options:p.enum||null,default:p.default});}}
 return out;
}
export function parseField(f,raw){
 if(f.type==='boolean')return {ok:true,value:!!raw};
 if(f.type==='enum'||f.type==='text')return {ok:true,value:String(raw)};
 const v=Number(raw);if(raw===''||!Number.isFinite(v))return {ok:false,error:'Enter a number.'};
 if(f.type==='integer'&&!Number.isInteger(v))return {ok:false,error:'Enter a whole number.'};
 if(f.min!=null&&v<f.min)return {ok:false,error:`At least ${f.min}.`};if(f.max!=null&&v>f.max)return {ok:false,error:`At most ${f.max}.`};
 return {ok:true,value:v};
}
// values: {group:{key:value}} → only the entries that differ from the field defaults.
export function overridesFrom(fields,values){
 const out={};for(const f of fields){const v=values?.[f.group]?.[f.key];if(v===undefined||v===f.default)continue;(out[f.group]||={})[f.key]=v;}
 return out;
}
export function renderSchemaForm(el,schema,{values={},showAdvanced=false,onChange=()=>{}}={}){
 const fields=schemaFields(schema),state=structuredClone(values||{}),groups=new Map();
 for(const f of fields){if(!groups.has(f.group))groups.set(f.group,[]);groups.get(f.group).push(f);}
 el.replaceChildren();
 for(const [group,list] of groups){
  const card=document.createElement('section'),h=document.createElement('h3'),intro=document.createElement('p');card.className='settings-card schema-group';card.dataset.group=group;
  h.textContent=list[0].groupTitle;intro.className='small-note';intro.textContent=list[0].groupDescription;card.append(h,intro);
  for(const f of list){if(f.advanced&&!showAdvanced)continue;
   const row=document.createElement('label'),name=document.createElement('span'),hint=document.createElement('small'),err=document.createElement('small');row.className='schema-field';name.className='schema-name';name.textContent=f.description||f.title;
   const current=state[f.group]?.[f.key]??f.default;let input;
   if(f.type==='boolean'){input=document.createElement('input');input.type='checkbox';input.checked=!!current;}
   else if(f.type==='enum'){input=document.createElement('select');for(const o of f.options){const opt=document.createElement('option');opt.value=o;opt.textContent=String(o).replaceAll('_',' ');input.append(opt);}input.value=current;}
   else{input=document.createElement('input');input.type=f.type==='text'?'text':'number';if(f.min!=null)input.min=f.min;if(f.max!=null)input.max=f.max;input.step=f.type==='integer'?'1':'any';input.value=current??'';}
   input.name=f.group+'.'+f.key;input.dataset.group=f.group;input.dataset.key=f.key;
   hint.className='schema-hint';hint.textContent=[f.unit&&`Unit: ${f.unit}`,f.default!==undefined&&`Default ${f.default}`,f.effects.length&&`Affects ${f.effects.join(', ')}`].filter(Boolean).join(' · ');
   err.className='schema-error';err.setAttribute('role','alert');
   input.onchange=()=>{const res=parseField(f,f.type==='boolean'?input.checked:input.value);input.setAttribute('aria-invalid',String(!res.ok));err.textContent=res.ok?'':res.error;if(!res.ok)return;(state[f.group]||={})[f.key]=res.value;onChange(overridesFrom(fields,state));};
   if(f.unit){const unit=document.createElement('span');unit.className='schema-unit';unit.textContent=f.unit;row.append(name,input,unit,hint,err);}else row.append(name,input,hint,err);
   card.append(row);}
  el.append(card);}
 return {fields,values:state};
}
