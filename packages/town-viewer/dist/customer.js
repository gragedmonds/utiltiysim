// Read-only joins over engine records. Unknown values are never replaced with bills or balances.
const rows=(town,key)=>Array.isArray(town[key])?town[key]:[];
const byId=list=>new Map(list.map(r=>[r.id,r]));
const group=(list,key)=>{const m=new Map();for(const r of list){const v=r[key];if(v==null)continue;if(!m.has(v))m.set(v,[]);m.get(v).push(r);}return m;};
export function validAt(record,at){return (!record.validFrom||Date.parse(record.validFrom)<=Date.parse(at))&&(!record.validTo||Date.parse(record.validTo)>Date.parse(at));}
export function customerIndex(town){return {
 accounts:byId(rows(town,'accounts')),partners:byId(rows(town,'businessPartners')),
 services:byId(rows(town,'servicePoints')),installations:byId(rows(town,'installations')),
 metersByService:group(rows(town,'meters'),'servicePointId'),registersByMeter:group(rows(town,'registers'),'meterId'),
 contractsByInstallation:group(rows(town,'contracts'),'installationId'),tariffsByContract:group(rows(town,'tariffAssignments'),'contractId'),
 readsByPremise:group(rows(town,'sampleReads'),'premiseId'),billsByAccount:group(rows(town,'billingDocuments'),'accountId'),invoicesByAccount:group(rows(town,'invoices'),'accountId'),
 mrus:byId(rows(town,'mrus')),schedulesByMru:group(rows(town,'readSchedules'),'mruId')
};}
// An invoice as the billing tab shows it: its period from its billing documents (earliest start to latest end) and
// whether any of them was billed on an estimate; its payments and dunning steps stay as the engine sent them.
export function invoiceDetails(invoices,docs){const byId=new Map((docs||[]).map(d=>[d.id,d]));return (invoices||[]).map(v=>{const ds=(v.billingDocumentIds||[]).map(id=>byId.get(id)).filter(Boolean),starts=ds.map(d=>d.periodStart).filter(Boolean).sort(),ends=ds.map(d=>d.periodEnd).filter(Boolean).sort();
 return {...v,periodStart:v.periodStart??starts[0]??null,periodEnd:v.periodEnd??ends.at(-1)??null,estimated:v.estimated??(ds.length?ds.some(d=>d.estimated===true):null)};});}
export function customerProfile(town,index,home,at){
 const services=Object.entries(home.services).filter(([,id])=>!!id).map(([commodity,id])=>{
  const service=index.services.get(id)||null,installation=index.installations.get(service?.installationId)||null;
  const contracts=index.contractsByInstallation.get(installation?.id)||[];
  const meters=(index.metersByService.get(id)||[]).map(meter=>({meter,registers:index.registersByMeter.get(meter.id)||[]}));
  return {commodity,id,service,installation,contracts,meters};
 });
 const contracts=services.flatMap(s=>s.contracts),active=contracts.filter(c=>validAt(c,at));
 const accountIds=[...new Set([home.accountId,...contracts.map(c=>c.accountId)].filter(Boolean))];
 const accounts=accountIds.map(id=>index.accounts.get(id)).filter(Boolean);
 const direct=index.accounts.get(home.accountId);
 const account=(direct&&validAt(direct,at)?direct:null)||index.accounts.get(active[0]?.accountId)||direct||accounts[0]||null;
 const partner=index.partners.get(account?.businessPartnerId)||null;
 const mruId=home.mruId||services.find(s=>s.installation?.mruId)?.installation.mruId;
 const reads=index.readsByPremise.get(home.id)||[];
 const bills=index.billsByAccount.get(account?.id)||[],billIds=new Set(bills.map(b=>b.id));
 // Invoice joins may be by account or by explicit billing-document references.
 const invoices=[...new Map([...(index.invoicesByAccount.get(account?.id)||[]),...rows(town,'invoices').filter(i=>(i.billingDocumentIds||[]).some(id=>billIds.has(id)))].map(i=>[i.id,i])).values()];
 return {home,account,accounts,partner,services,contracts,reads,bills,invoices,mru:index.mrus.get(mruId)||null,schedules:index.schedulesByMru.get(mruId)||[],at};
}

// Presentation fixtures are added only by explicit browser demo mode, never by snapshot import.
export function demoCustomers(town){
 const first=['Alex','Jordan','Sam','Taylor','Morgan','Casey','Robin','Avery','Cameron','Jamie','Riley','Quinn'];
 const last=['Patel','Martin','Chen','Wilson','Singh','Brown','Tremblay','Campbell','Ahmed','Thompson','Wong','Anderson'];
 const hash=s=>{let h=2166136261;for(const c of s){h^=c.charCodeAt(0);h=Math.imul(h,16777619);}return h>>>0;};
 const byAccount=new Map(town.premises.map(h=>[h.accountId,h]));
 return {...town,businessPartners:town.accounts.map(a=>{const n=hash(town.seed+':customer:'+a.businessPartnerId);return {id:a.businessPartnerId,name:first[n%first.length]+' '+last[Math.floor(n/first.length)%last.length],kind:'person',synthetic:true};}),accounts:town.accounts.map(a=>({...a,premiseId:byAccount.get(a.id)?.id,synthetic:true}))};
}
