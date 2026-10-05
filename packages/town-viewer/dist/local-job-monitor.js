import {localToken} from './local-session.js';
import {updateLocalMonitor} from './local-monitor.js';
const token=localToken();
if(token&&typeof document!=='undefined'&&!location.pathname.endsWith('local-runs.html')){
 for(const href of ['./local-runs.css','./engine-monitor.css']){const style=document.createElement('link');style.rel='stylesheet';style.href=href;document.head.append(style);}
 const host=document.createElement('aside');host.className='local-floating';host.hidden=true;host.setAttribute('aria-label','Local engine activity');document.body.append(host);
 let pending=false;async function refresh(){if(pending)return;pending=true;try{const r=await fetch('/local/status',{headers:{Authorization:'Bearer '+token},signal:AbortSignal.timeout(8000)});if(r.ok)updateLocalMonitor(host,await r.json());}catch{}finally{pending=false;}}
 refresh();setInterval(refresh,2500);
}
