import {worldProfile} from './city-design.js';
/** Map-led Living World dashboard. All quantities and the map image are supplied
 * by the actual saved world; this module does not advance or synthesize state. */
export function renderOverview({town,state,population,roadsKm,advance,mapImage,day,fmt,icon,esc,dayEvents,weather}) {
  const profile=worldProfile(town,state),name=esc(profile.name);
  const completed=state.lastCompletedDay?day(state.lastCompletedDay):'No completed days';
  const nextDay=day(state.through);
  const latest=state.daysHistory?.[0];
  const hasTemperature=typeof latest?.temperature==='number'&&Number.isFinite(latest.temperature);
  const clock=state.clockOwner==='local-cruise'?'Local cruise control':state.managedDelivery?'Shared runtime clock':'Manual advancement';
  const history=dayEvents(3);
  const metrics=[
    ['Residents',population,'Saved residential occupancy','people'],
    ['Homes',town.homes,`${fmt(town.count)} premises in all`,'home'],
    ['Physical meters',state.assets,'Water · electricity · gas','water'],
    ['Days recorded',state.days,'Committed world history','calendar'],
  ];
  return `<div class="ov-dashboard">
    <div class="ov-heading">
      <div><span class="ov-eyebrow">YOUR LIVING WORLD</span><h1>${name}, at a glance.</h1><p>A place to explore. A physical world to understand.</p></div>
      <div class="ov-saved-state"><span class="ov-state-dot"></span><div><small>WORLD SAVED THROUGH</small><strong>${esc(completed)}</strong></div></div>
    </div>
    <div class="ov-primary-grid">
      <section class="ov-map-panel" aria-label="Saved ${name} geography">
        <div class="ov-panel-heading"><div><span class="ov-eyebrow">A WORLD WORTH EXPLORING</span><h2>Your town, in perspective.</h2></div><span class="ov-map-type">${esc(profile.label)}</span></div>
        <button type="button" class="ov-map-link" data-page="map" aria-label="Open the interactive ${name} town map">
          ${mapImage?`<img src="${esc(mapImage)}" alt="Actual saved ${name} geography rendered by Civic Atlas" decoding="async">`:'<span class="ov-map-unavailable">Open the town map to explore its saved geography.</span>'}
          <span class="ov-map-caption"><span class="ov-state-dot"></span>Saved geography · real world records</span>
          <span class="ov-map-action">${icon('map')}Explore town map <span aria-hidden="true">→</span></span>
        </button>
        <div class="ov-map-facts"><span>${icon('map')}<b>${esc(Number.isFinite(roadsKm)?roadsKm.toFixed(1):'—')} km</b> of streets</span><span><b>${fmt(town.count)}</b> premises to inspect</span>${Array.isArray(town.parks)?`<span><b>${fmt(town.parks.length)}</b> saved parks</span>`:''}</div>
      </section>
      <aside class="ov-world-panel" aria-label="World profile and physical clock">
        <div class="ov-world-heading"><span class="ov-eyebrow">THE WORLD AT A GLANCE</span><span class="ov-context">Living World · administrator</span></div>
        <div class="ov-metrics">${metrics.map(([label,value,note,symbol])=>`<div class="ov-metric"><span class="ov-metric-label">${icon(symbol)}${label}</span><strong>${fmt(value)}</strong><small>${esc(note)}</small></div>`).join('')}</div>
        <div class="ov-next-day"><div class="ov-next-day-label">${icon('calendar')}<span>NEXT PHYSICAL DAY</span><span class="ov-clock-label">${esc(clock)}</span></div><div class="ov-next-date">${esc(nextDay)}</div><p>${state.manualAdvanceAllowed===false?esc(state.clockReason||'Advancement is controlled by the world runtime.'):'Continue this world by one day. New observations and outcomes are saved to its history.'}</p><div class="ov-advance-action">${advance}</div></div>
        <button type="button" class="ov-config-link" data-page="configure">${icon('sliders')}View this world’s configuration <span aria-hidden="true">→</span></button>
      </aside>
    </div>
    <div class="ov-lower-grid">
      <section class="ov-weather-panel ov-lower-panel"><div class="ov-lower-heading"><div><span class="ov-eyebrow">THE PHYSICAL CONDITIONS</span><h2>Recorded weather</h2></div>${hasTemperature?`<div class="ov-temperature">${fmt(latest.temperature)}<small>°C</small></div>`:''}</div><p>Daily temperature · illustrative physical model</p><div class="ov-weather-chart">${weather()}</div></section>
      <section class="ov-history-panel ov-lower-panel"><div class="ov-lower-heading"><div><span class="ov-eyebrow">THE STORY SO FAR</span><h2>Recent activity</h2></div><button type="button" class="ov-inline-link" data-page="activity">View all <span aria-hidden="true">→</span></button></div>${history||'<p class="ov-empty-history">No physical days have completed yet. The next committed day will appear here.</p>'}</section>
      <section class="ov-evidence-panel ov-lower-panel"><span class="ov-evidence-icon">${icon('connections')}</span><span class="ov-eyebrow">BEYOND THE TOWN</span><h2>Physical evidence.<br>Connected possibilities.</h2><p><strong>${fmt(state.observations)} observations</strong> are stored in this world. Delivery and processing by other applications are separate steps.</p><button type="button" class="ov-inline-link" data-page="connections">Explore connections <span aria-hidden="true">→</span></button></section>
    </div>
  </div>`;
}
