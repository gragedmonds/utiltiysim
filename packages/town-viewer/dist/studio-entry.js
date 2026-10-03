import {installEngineMonitor} from './engine-monitor.js';
try{
 const {activeSimulation:s}=await import('./simulation-session.js');
 if(!s||s.status!=='ready'){const url=new URL('./',location.href);const engine=new URLSearchParams(location.search).get('engine');if(engine)url.searchParams.set('engine',engine);location.replace(url);}
 else{
  const url=new URL(location.href);url.searchParams.set('town',s.townRef);if(!url.hash)url.hash='#/year';history.replaceState(null,'',url);
  const home=new URL('./',location.href);if(url.searchParams.has('engine'))home.searchParams.set('engine',url.searchParams.get('engine'));document.getElementById('nav-simulations').href=home;
  document.title=s.name+' · Utility Studio';document.body.classList.add('simulation-session');
  const label=document.createElement('span');label.className='simulation-name';label.textContent=s.name;label.title=s.name;document.querySelector('.studio-brand').append(label);
  installEngineMonitor();document.body.hidden=false;await import('./app.js');
 }
}catch(e){document.body.hidden=false;document.body.replaceChildren();const h=document.createElement('h1'),p=document.createElement('p'),a=document.createElement('a');h.textContent='This simulation couldn’t open.';p.textContent=e.message;a.href='./';a.textContent='Return to your simulations';document.body.append(h,p,a);}
