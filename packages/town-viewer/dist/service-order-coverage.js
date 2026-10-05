// Reference-code coverage, not another set of work-order counts.
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export function serviceOrderCoverage(catalogue,filter=''){
 const c=catalogue?.serviceOrders;if(!c?.orders?.length)return '';
 const q=filter.trim().toLowerCase(),types=c.engineTypes||{},orders=c.orders.filter(o=>!q||[o.code,o.title,o.group,o.behaviour,o.gap,...(o.engineTypes||[]).map(k=>types[k]||k),...(o.manualActivities||[])].join(' ').toLowerCase().includes(q));
 if(!orders.length)return '';
 const countLabels={covered:'covered',partial:'partial',not_modelled:'not modelled'};
 const totals=Object.entries(c.statuses).map(([id,label])=>`<span class="report-status is-${esc(id)}">${orders.filter(o=>o.status===id).length} ${esc(countLabels[id]||label.toLowerCase())}</span>`).join(' ');
 return `<section class="glossary-family service-order-coverage" id="service-orders"><h2>Service-order coverage</h2><p>${orders.length} of ${c.orders.length} reference types · ${esc(c.source)}</p><div class="service-coverage-totals">${totals}</div><p>Core work covered means the behaviour exists under a broader engine activity. These reference codes are not separate selectable order types or extra work counts.</p><details class="service-coverage-note"><summary>Issuing work and interpreting the times</summary><p>${esc(c.manualNote)}</p><p>${esc(c.timingNote)}</p></details>${c.groups.map(group=>{
  const rows=orders.filter(o=>o.group===group);if(!rows.length)return '';
  return `<details class="service-order-group" ${q?'open':''}><summary><strong>${esc(group)}</strong><span>${rows.length} ${rows.length===1?'type':'types'}</span></summary><div class="service-order-list">${rows.map(o=>`<article class="service-order-card" id="service-order-${esc(o.code)}"><header><h3><code>${esc(o.code)}</code> ${esc(o.title)}</h3><span class="report-status is-${esc(o.status)}">${esc(c.statuses[o.status]||o.status)}</span></header><p>${esc(o.behaviour)}</p><dl>${o.engineTypes.length?`<dt>Related annual work</dt><dd>${o.engineTypes.map(k=>esc(types[k]||k)).join(' · ')}</dd>`:''}${o.manualActivities.length?`<dt>Related manual activity</dt><dd>${o.manualActivities.map(esc).join(' · ')}</dd>`:''}</dl>${o.gap?`<p class="service-order-gap"><b>Still missing:</b> ${esc(o.gap)}</p>`:''}</article>`).join('')}</div></details>`;
 }).join('')}</section>`;
}
