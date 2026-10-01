// Map chrome and settings navigation. Simulation commands remain with the app/engine.
const paths={
 search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/>',
 folder:'<path d="M3 7V5a1 1 0 0 1 1-1h5l3 3h8a1 1 0 0 1 1 1v11H3Z"/>',
 settings:'<path d="M5 3v18M12 3v18M19 3v18M2 8h6m1 8h6m1-9h6"/><circle cx="5" cy="8" r="2" fill="currentColor"/><circle cx="12" cy="16" r="2" fill="currentColor"/><circle cx="19" cy="7" r="2" fill="currentColor"/>',
 layers:'<path d="m3 8 9-5 9 5-9 5Zm0 5 9 5 9-5M3 18l9 5 9-5"/>',
 sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
 map:'<path d="m3 5 6-2 6 2 6-2v16l-6 2-6-2-6 2Zm6-2v16m6-14v16"/>',
 plan:'<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 11h18M11 3v18"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',minus:'<path d="M5 12h14"/>',
 close:'<path d="m6 6 12 12M6 18 18 6"/>',back:'<path d="m10 5-7 7 7 7M3 12h18"/>',
 upload:'<path d="M12 16V3m-5 5 5-5 5 5M3 15v6h18v-6"/>',
 download:'<path d="M12 3v13m-5-5 5 5 5-5M3 15v6h18v-6"/>',
 book:'<path d="M12 5C9 3 6 3 3 4v16c3-1 6-1 9 1 3-2 6-2 9-1V4c-3-1-6-1-9 1Zm0 0v16"/>'
};
export function installFocusUI({getContext,onSettings,onScenario}){
 const $=id=>document.getElementById(id), pairs=[['layers-toggle','layers-drawer'],['scenario-toggle','scenario-popover'],['data-toggle','data-popover'],['search-toggle','search-popover']];
 document.querySelectorAll('[data-icon]').forEach(el=>{el.insertAdjacentHTML('afterbegin',`<svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[el.dataset.icon]||''}</svg>`);});
 function closeTools(){for(const [button,panel] of pairs){$(panel).hidden=true;$(button).setAttribute('aria-expanded','false');}}
 for(const [button,panel] of pairs){$(button).setAttribute('aria-controls',panel);$(button).setAttribute('aria-expanded','false');$(button).onclick=()=>{const open=$(panel).hidden;closeTools();$('performance-panel').open=false;if(open){$(panel).hidden=false;$(button).setAttribute('aria-expanded','true');if(panel==='search-popover')$('search-input').focus();}};}
 $('layers-close').onclick=()=>{closeTools();$('layers-toggle').focus();};$('scenario-close').onclick=()=>{closeTools();$('scenario-toggle').focus();};
 $('performance-panel').addEventListener('toggle',()=>{if($('performance-panel').open)closeTools();});
 function refresh(){
  const {town,mode}=getContext(),imported=mode==='snapshot';if(!town)return;
  document.querySelectorAll('[data-scenario-preset]').forEach(el=>el.disabled=imported);
  $('preset-availability').textContent=imported?'This snapshot is read-only. Scenario commands need the engine connection.':'Preview one event at a time in the browser demo.';
  $('generator-context').hidden=!imported;
  const config=town.config||town.configuration;
  $('engine-config-preview').textContent=JSON.stringify(config||{mode,seed:town.seed,homes:town.count,source:town.source?.name||'Frozen Whitby street extract'},null,2);
  // Never invent incident-rate defaults or let local sliders imply a running engine.
  $('frequency-fields').replaceChildren();
  const fields=[['Gas leaks','gas_leak'],['Water main breaks','water_main_break'],['Lightning strikes','lightning_strike'],['Transformer failures','transformer_failure'],['AMI collector outages','ami_collector_down']];
  for(const [label,key] of fields){const row=document.createElement('label'),caption=document.createElement('span'),input=document.createElement('input');row.className='frequency-row';caption.textContent=label;input.disabled=true;input.placeholder='Awaiting engine';input.setAttribute('aria-label',label+' frequency');row.append(caption,input);$('frequency-fields').append(row);}
  const supplied=config?.incidents;if(supplied){const pre=document.createElement('pre');pre.textContent=JSON.stringify(supplied,null,2);$('frequency-fields').append(pre);}
  $('frequency-note').textContent=supplied?'Supplied incident configuration is shown below. Editing needs the engine schema and update API.':'Frequency controls will be enabled when the engine provides its configuration schema and update endpoint.';
 }
 function route(){const match=window.location.hash.match(/^#\/settings(?:\/(town|scenarios|data))?$/),open=!!match,tab=match?.[1]||'town';
  $('settings-page').hidden=!open;document.querySelector('.workspace').inert=open;document.querySelector('.topbar').inert=open;onSettings(open);
  if(open){closeTools();$('performance-panel').open=false;refresh();document.querySelectorAll('[data-settings-pane]').forEach(el=>el.hidden=el.dataset.settingsPane!==tab);document.querySelectorAll('[data-settings-tab]').forEach(el=>{if(el.dataset.settingsTab===tab)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});$('settings-back').focus();}
 }
 function settings(tab='town'){window.location.hash='/settings/'+tab;route();}
 function map(){window.location.hash='/town';route();$('settings-toggle').focus();}
 $('settings-toggle').onclick=()=>settings();$('settings-back').onclick=map;$('scenario-settings').onclick=()=>settings('scenarios');
 document.querySelectorAll('[data-settings-tab]').forEach(el=>el.onclick=()=>settings(el.dataset.settingsTab));
 document.querySelectorAll('[data-scenario-preset]').forEach(el=>el.onclick=()=>{onScenario(el.dataset.scenarioPreset);map();});
 $('settings-load-snapshot').onclick=()=>$('snapshot-file').click();
 for(const id of ['load-snapshot-btn','export-btn','requirements-btn'])$(id).addEventListener('click',closeTools);
 document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeTools();if(!$('settings-page').hidden)map();}});
 window.addEventListener('hashchange',route);route();
 return {refresh,map,closeTools};
}
