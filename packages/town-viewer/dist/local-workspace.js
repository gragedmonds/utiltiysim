import {EngineM2C} from './m2c.js';
import {localRequest} from './local-session.js';
// The live engine client, querying every processing checkpoint through one local endpoint.
export class LocalUtility extends EngineM2C{
 constructor({job,model,library,api='/api',onSave=()=>{}}){
  const initial={...(model.workspaceState||{}),settings:model.settings,episodes:model.episodes||[],actions:model.actions||[],seed:model.seed};
  if(!model.workspaceState)initial.asOf=model.asOf;
  super({api,townRef:'local-run-'+job.result.districts[0].runKey,simulationId:model.id,storage:null,initial,
   onSave:m=>{const state={settings:m.settings,seed:m.seed,...m.chain[0],year:m.year,later:m.chain.slice(1)};
    library.update(model.id,{settings:m.settings||{},episodes:m.chain[0].episodes,asOf:m.asOf,actions:m.chain[0].actions,workspaceState:state});onSave(m);}});
  this.job=job;this.localUtility=true;
  this.fetchImpl=async(input,init)=>{
   const url=new URL(input,globalThis.location?.href||'http://localhost');
   if(init?.method==='POST'&&/\/api\/(m2c|process|vee)\//.test(url.pathname)&&!url.pathname.includes('/episodes/preview')){
    const path=url.pathname.slice(url.pathname.indexOf('/api/')+4),params=JSON.parse(init.body||'{}');
    try{const value=await localRequest('jobs/'+this.job.jobId+'/query',{path,params},{timeout:12*60*60*1000});
     return new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}});
    }catch(e){return new Response(JSON.stringify({detail:e.message}),{status:e.status||422,headers:{'Content-Type':'application/json'}});}
   }
   return globalThis.fetch(input,init);
  };
 }
 body(extra={}){const body=super.body(extra);return {...body,settings:this.settings||{},seed:this.seed||null,episodes:this.episodes||[],outages:body.outages||[]};}
 // Portable utility jobs currently archive 2026. Do not offer a year the job format cannot save.
 canContinue(){return false;}
 async tableCsv(params){const data=await this.table(params);const cell=v=>'"'+String(v??'').replaceAll('"','""')+'"';return [data.columns.map(c=>cell(c.key)).join(','),...data.rows.map(r=>r.map(cell).join(','))].join('\n');}
 async tableLink(params){return localRequest('jobs/'+this.job.jobId+'/link',this.body(params),{timeout:12*60*60*1000});}
}
