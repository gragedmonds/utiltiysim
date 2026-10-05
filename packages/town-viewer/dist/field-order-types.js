// Keep recorded activities stable; expose a physical job and its purpose.
export const fieldWorkType=(vocabulary,activity)=>(vocabulary?.workTypes||[]).find(w=>w.purposes.some(p=>p.activity===activity))||null;
export function activityForWorkType(vocabulary,id,current){
 const work=vocabulary?.workTypes?.find(w=>w.id===id);
 return work?.purposes.find(p=>p.activity===current)?.activity||work?.purposes[0]?.activity||current;
}
export const fieldPurposes=(vocabulary,activity)=>fieldWorkType(vocabulary,activity)?.purposes||[];
export const optionalMeterReview=c=>['HIGH_BILL','BILL_DISPUTE','ZERO_USAGE','LOW_USAGE'].includes(c?.type);
