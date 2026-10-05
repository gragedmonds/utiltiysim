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
if(token&&typeof document!=='undefined')document.documentElement.classList.add('local-engine');
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

// The remembered-folder launch skips the bootstrap page. Keep its update/restart
// controls reachable from Studio without persisting its per-launch credential.
export function validLauncherURL(address){try{const u=new URL(address);return u.protocol==='http:'&&u.hostname==='127.0.0.1'&&!!u.port&&!u.username&&!u.password&&u.pathname==='/'&&!u.search&&new URLSearchParams(u.hash.slice(1)).get('token')?.length>=32;}catch{return false;}}
async function installAppSettings(){
 if(!isApp()||document.querySelector('.local-app-settings'))return;
 try{const s=await localRequest('status');if(!validLauncherURL(s.launcherURL))return;
  const header=document.querySelector('.top-actions,.offline-header,.studio-header,body > header');if(!header)return;
  const a=document.createElement('a');a.href=s.launcherURL;a.target='_blank';a.rel='noopener noreferrer';a.className='local-app-settings';a.title='App settings and updates';a.setAttribute('aria-label',a.title);a.textContent='⚙';
  Object.assign(a.style,{display:'inline-grid',placeItems:'center',width:'32px',height:'32px',flex:'0 0 32px',marginLeft:'12px',border:'1px solid #c9c8d5',borderRadius:'50%',textDecoration:'none',color:'#605282',fontSize:'20px'});header.append(a);
 }catch{} // Studio remains usable with an older launcher or without its settings page.
}
if(typeof document!=='undefined'){if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',installAppSettings,{once:true});else installAppSettings();}
