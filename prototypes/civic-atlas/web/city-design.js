// Saved-world metadata is shared by the shell and overview. Land-use geometry
// supplies destinations, but never creates customers, assets or simulated demand.
export function worldProfile(town,state={}){
 const design=town.atlasDesign||{},version=String(design.version||'');
 const planned=version.startsWith('civic-atlas-town500/');
 const reference=version.startsWith('civic-atlas-reference/');
 const authored=planned||reference||design.curated===true;
 const name=design.name||town.name||state.environmentId||'Saved town';
 const focus=design.focus||design.initialView;
 const initialView=focus&&['x','z','viewHeightM'].every(k=>Number.isFinite(focus[k]))?focus:reference?{x:65,z:-65,viewHeightM:245}:undefined;
 return {name,planned,reference,authored,initialView,
  defaultArt:design.defaultArt||(reference||planned?'blocks':'native'),
  label:planned?'Planned fictional town':authored?'Designed reference town':'Generated fictional town',
  caption:planned?'Planned geography · saved physical records':authored?'Curated geography · saved physical records':'Generated geography · saved world records',
  pattern:planned?'Main Street · planned neighborhoods':authored?'Curated reference layout':'Connected neighborhoods',
  description:design.description||(authored?'Authored fictional geography; utility assets and daily records come from the runtime.':'Generated once, retained across every simulated day.'),
 };
}
export function townDestinations(town){
 const d=town.atlasDesign||{},destinations=[];
 const addAreas=(items,group,prefix,note)=>{for(const area of items||[]){
  if(!Array.isArray(area.polygon)||area.polygon.length<3||!area.polygon.every(p=>Number.isFinite(p.x)&&Number.isFinite(p.z)))continue;
  const id=area.id||`${prefix}-${destinations.length}`;
  const ids=area.premiseIds||area.ids||[];
  const count=ids.filter(id=>town.premises.some(p=>p.id===id)).length;
  const label=area.name||area.label||id;
  const name=(items||[]).filter(p=>(p.name||p.label||p.id)===label).length>1?`${label} · ${id}`:label;
  destinations.push({id:`${prefix}:${id}`,name,group,area,note:count?`${count} saved properties`:note});
 }};
 addAreas(d.districts,'Districts & Main Street','district','Saved district layout');
 addAreas((d.landUseZones||[]).filter(z=>!['residential','buffer','field','park'].includes(z.kind)),'Districts & Main Street','zone','Planned land use · inspect buildings for physical records');
 addAreas(d.parks,'Parks','park','Saved park · illustrated amenities');
 addAreas(d.fields,'Countryside · land use only','field','Descriptive field · no farm production or utility demand');
 addAreas((d.blocks||[]).filter(b=>!b.kind||b.kind==='residential'),'Residential blocks','block','Saved neighborhood layout');
 addAreas((d.blocks||[]).filter(b=>b.kind&&b.kind!=='residential'),'Town center & civic blocks','block','Saved block layout');
 for(const home of town.premises){
  if(!['school','church','industrial','depot','pump_house'].includes(home.buildingType))continue;
  const type=home.buildingType.replaceAll('_',' '),label=type[0].toUpperCase()+type.slice(1);
  destinations.push({id:`premise:${home.id}`,name:home.name||`${label} · ${home.address||home.id}`,group:home.buildingType==='industrial'?'Industrial properties':'Civic & utility properties',home,note:`${home.buildingType.replaceAll('_',' ')} · saved physical records`});
 }
 return destinations;
}
// Concept studies never populate the saved world. Navigation resolves examples
// from source categories instead of hard-coding IDs or inventing premises.
export const CITY_FAMILIES=[
 {id:'homes',group:'homes',name:'Homes with individual character',tag:'Detached homes',tile:0,summary:'A shared street rhythm, with different rooflines, porches, gardens and materials.',rules:['Doors and front walks face the street; driveways connect to real access.','Vary form as well as color. Keep roof solar tied to recorded equipment.','Quiet local streets, private back gardens, occasional corner trees.'],match:p=>p.buildingType==='detached'},
 {id:'shops',group:'work',name:'A Main Street worth walking',tag:'Shops & cafés',tile:1,summary:'A continuous, human-scaled frontage: glazed shops, awnings and doors close to the sidewalk.',rules:['Group narrow shopfronts along connected commercial streets.','Put deliveries and bins at the rear or side, outside pedestrian entrances.','Use signs, cornices and canopy variation without adding fictional businesses.'],match:p=>p.buildingType==='storefront'},
 {id:'apartments',group:'homes',name:'More neighbors, shared space',tag:'Courtyard apartments',tile:2,summary:'Modest apartment buildings bring density near shops, parks and connecting streets.',rules:['Use shared entrances and courtyards, with parking behind the frontage.','Record separate premises and service arrangements before adding residents.','Step down toward neighboring houses; keep courtyards visible from our fixed camera.'],match:p=>['apartment','apartments'].includes(p.buildingType)},
 {id:'townhouses',group:'homes',name:'A compact residential edge',tag:'Townhouses',tile:3,summary:'Attached homes with individual doors, repeated bays and small private gardens.',rules:['Keep a coherent roofline with small variations in doors and masonry.','One visible front door per intended home; preserve premise identity.','Use as a transition between detached streets and busier central blocks.'],match:p=>['townhouse','rowhouse'].includes(p.buildingType)},
 {id:'park',group:'public',name:'Room to play. Room to breathe.',tag:'Neighborhood park',tile:4,summary:'An open lawn, play space and paths that join the surrounding neighborhood.',rules:['Keep usable lawn clear; cluster trees around edges and seating.','Provide a legible route from the sidewalk to each activity.','Play equipment is decorative here; it does not create utility demand.'],park:'recreation'},
 {id:'river',group:'public',name:'A riverfront people can reach',tag:'River park',tile:5,summary:'A public promenade, shaded places to pause and a softer planted river edge.',rules:['Respect the river geometry and retain a buffer at the bank.','Keep a continuous public walking route with visible neighborhood access.','No invented road crossing, flood protection or water-system asset.'],park:'riverfront'},
 {id:'industry',group:'work',name:'A working edge to the town',tag:'Light industry',tile:6,summary:'Workshop sheds, rooflights, service yards and a smaller, welcoming office frontage.',rules:['Locate freight access on suitable connecting roads, away from quiet cul-de-sacs.','Separate truck maneuvering and storage from pedestrian entrances.','Use planted buffers beside homes; model demand and equipment before commissioning.'],match:p=>p.buildingType==='industrial'},
 {id:'school',group:'public',name:'A recognizable civic anchor',tag:'School campus',tile:7,summary:'A clear main entrance, safe walking connections and grounds sized for its role.',rules:['Keep entrances legible and service access separate from arrival space.','Place civic buildings where they support surrounding neighborhoods.','Use the recorded footprint, height and utility services in the actual map.'],match:p=>p.buildingType==='school'},
];
export function renderCityDesign(town,{esc,state={}}){
 const profile=worldProfile(town,state),population=town.premises.filter(p=>p.premiseType==='residential'&&p.occupied).reduce((n,p)=>n+(p.occupants||0),0);
 const destinations=townDestinations(town).filter(p=>p.group!=='Residential blocks');
 const featured=destinations.filter(p=>p.home&&['school','church','industrial'].includes(p.home.buildingType)).filter((p,i,items)=>items.findIndex(other=>other.home.buildingType===p.home.buildingType)===i);
 const links=[...featured,...destinations.filter(p=>!p.home)].slice(0,16);
 const savedPlaces=profile.planned?`<section class="city-saved-places"><div><span class="eyebrow">THIS SAVED WORLD</span><h2>${esc(profile.name)} · ${town.homes.toLocaleString()} homes</h2><p>${population.toLocaleString()} residential occupants · ${town.count.toLocaleString()} premises in all. Homes and residents are different quantities.</p></div><div class="city-saved-links">${links.map(p=>`<button data-city-example="${esc(p.id)}"><strong>${esc(p.name)}</strong><small>${esc(p.note)}</small><span aria-hidden="true">→</span></button>`).join('')}</div><small>Districts and fields describe the town plan. Only saved premises and assets contribute physical records; fields do not simulate farming.</small></section>`:'';
 return `<div class="content-heading"><div><span class="eyebrow">CIVIC ATLAS · CITY DESIGN STUDIES</span><h1>A town made of real places.</h1><p>Homes, places to work, and shared spaces—each with a reason to be where it is.</p></div><button class="primary" data-page="map">Return to town map →</button></div>
 ${savedPlaces}<div class="city-design-intro"><div><span class="eyebrow">ONE VISUAL LANGUAGE</span><h2>Different places.<br>The same world.</h2><p>Warm masonry. Leafy streets. Clear entrances. A fixed aerial view that keeps the town easy to read.</p></div><div><b>Concept illustrations</b><p>These images explore the next visual direction. “See saved example” opens the current map, which is still being refined toward these studies.</p><small>New building families are not added to the simulation by this page.</small></div></div>
 <div class="city-filters" role="group" aria-label="Filter city design studies">${[['all','All places'],['homes','Homes'],['work','Work & commerce'],['public','Parks & civic']].map(([id,label])=>`<button data-city-filter="${id}" aria-pressed="${id==='all'}">${label}</button>`).join('')}</div>
 <div class="city-study-grid">${CITY_FAMILIES.map(f=>{
 const example=f.match?town.premises.find(f.match):null,park=f.park?town.atlasDesign?.parks?.find(p=>p.kind===f.park):null;
 const available=example||park;
 return `<article class="city-study" data-city-group="${f.group}" id="city-study-${f.id}"><div class="city-study-art" role="img" aria-label="Concept illustration of ${esc(f.tag.toLowerCase())}" style="--art-x:${f.tile%4/3*100}%;--art-y:${f.tile<4?0:100}%"><span>Visual study</span></div><div class="city-study-copy"><span class="eyebrow">${f.tag}</span><h2>${f.name}</h2><p>${f.summary}</p><details><summary>How this belongs in the city</summary><ul>${f.rules.map(r=>`<li>${r}</li>`).join('')}</ul></details><div class="city-study-foot"><small>${available?'Category present in saved world':'Planned family · not in this world'}</small>${available?`<button class="text-button" data-city-example="${f.id}">See saved example →</button>`:''}</div></div></article>`;
 }).join('')}</div><section class="city-scale-note"><span class="eyebrow">GROW THE PLACE, NOT JUST THE HOUSE COUNT</span><h2>Density changes the pattern.</h2><div><p><b>500 residents</b>A compact center, mostly detached homes, modest civic space. Industry only where the town’s role supports it.</p><p><b>5,000 residents</b>Several connected neighborhoods, a stronger Main Street, attached housing and apartments near the center.</p><p><b>50,000 residents</b>Multiple centers, a street hierarchy, larger employment areas and a varied housing mix. Parks and access scale with neighborhoods.</p></div><small>Design principles, not a population conversion formula. Actual capacity needs parcel, household and infrastructure checks.</small></section>`;
}
