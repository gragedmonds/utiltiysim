// The app: Utility Studio served by this computer's own process (utilsim/worker/server.py), which also runs the
// engine and the job queue. The launcher opens the pages with the per-launch credential in the URL fragment
// (#token=…); it is kept in this browser for this origin (one launch's loopback port) and sent with every /local
// request. Without a token the pages are a plain Studio (the dev host, or `utilsim serve` with ?engine=): the job
// queue, saved results and the key settings need the app.
const KEY='utility-studio-local-token';
export function captureToken(where=globalThis.location,storage=globalThis.localStorage,history=globalThis.history){
 try{const fragment=new URLSearchParams(String(where?.hash||'').slice(1)),token=fragment.get('token');
  if(token){storage.setItem(KEY,token);history?.replaceState?.(null,'',where.pathname+where.search);return token;}
  return storage.getItem(KEY)||'';}
 catch{return '';}
}
let token=typeof location==='undefined'?'':captureToken();
export const localToken=()=>token;
export const isApp=()=>!!token;
// A /local request to the app's process; the Error's message is the server's reason.
export async function localRequest(path,data,{method,fetchImpl=globalThis.fetch,timeout=20000}={}){
 if(!token)throw Error('Open Utility Studio from the app to use this.');
 const r=await fetchImpl('/local/'+path,{method:method||(data===undefined?'GET':'POST'),headers:{Authorization:'Bearer '+token,...(data===undefined?{}:{'Content-Type':'application/json'})},body:data===undefined?undefined:JSON.stringify(data),signal:AbortSignal.timeout(timeout)});
 let result=null;try{result=await r.json();}catch{}
 if(!r.ok){if(r.status===401)token='';throw Error(typeof result?.detail==='string'?result.detail:'Utility Studio could not complete this request ('+r.status+').');}
 return result;
}
