import test from 'node:test';
import assert from 'node:assert/strict';
import {fieldWorkType,activityForWorkType,fieldPurposes,optionalMeterReview} from '../dist/field-order-types.js';
const vocabulary={workTypes:[{id:'meter_visit',title:'Meter visit',purposes:[{activity:'Meter investigation',label:'Investigate meter / usage'},{activity:'Special meter read',label:'Read / re-read'},{activity:'Access investigation',label:'Resolve access issue'}]},{id:'meter_exchange',title:'Exchange meter',purposes:[{activity:'Meter exchange',label:'Replace meter'}]}]};
test('read and investigation purposes share one work type without rewriting recorded activities',()=>{
 for(const activity of ['Special meter read','Meter investigation','Access investigation']){
  assert.equal(fieldWorkType(vocabulary,activity).id,'meter_visit');
  assert.equal(activityForWorkType(vocabulary,'meter_visit',activity),activity);
  assert.equal(fieldPurposes(vocabulary,activity).length,3);
 }
 assert.equal(activityForWorkType(vocabulary,'meter_exchange','Special meter read'),'Meter exchange');
 assert.equal(activityForWorkType(vocabulary,'meter_visit','Meter exchange'),'Meter investigation');
 assert.equal(fieldWorkType({},'Special meter read'),null,'old vocabulary falls back to its original selector');
 assert.equal(activityForWorkType({},'unknown','Special meter read'),'Special meter read');
});
test('field evidence is a review option for billing and zero usage, not a dispatch rule',()=>{
 for(const type of ['HIGH_BILL','BILL_DISPUTE','ZERO_USAGE','LOW_USAGE'])assert.equal(optionalMeterReview({type}),true);
 assert.equal(optionalMeterReview({type:'FIELD_SERVICE'}),false);
 assert.equal(optionalMeterReview(null),false);
});
