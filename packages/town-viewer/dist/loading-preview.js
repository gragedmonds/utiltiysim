import {updateLocalMonitor} from './local-monitor.js';
import {ENGINE_SCENES,SCENE_DURATION,sceneIndexAt} from './engine-scenes.js';

const panel=document.querySelector('#preview-monitor');
const buttons=[...document.querySelectorAll('[data-scene]')];
const status={analysis:{name:'Utility Studio',stage:'Animation preview',completed:2,total:4,etaBasis:'A little company while your utility gets to work.'}};
let epoch=Date.now(),selected=0,cycling=true,paused=false,pausedAt=0;

function render(){
  const elapsed=cycling?(paused?pausedAt:Date.now())-epoch:selected*SCENE_DURATION;
  selected=sceneIndexAt(elapsed);
  panel.dataset.sceneStarted='0';
  updateLocalMonitor(panel,status,elapsed);
  panel.querySelector('.engine-scene-caption').textContent=ENGINE_SCENES[selected].message;
  panel.querySelector('.monitor-estimate').textContent='Animation preview · no analysis is running';
  buttons.forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.scene)===selected)));
}
function setCycle(value){cycling=value;const button=document.querySelector('#cycle');button.textContent=`Auto-cycle: ${value?'on':'off'}`;button.setAttribute('aria-pressed',String(value));}
function inspectMoment(){const value=document.querySelector('#moment').value;if(value==='')return;for(const animation of panel.querySelector('.blob-scene').getAnimations({subtree:true}))animation.currentTime=Number(value);}
function replay(){delete panel.dataset.scene;delete panel.dataset.frame;epoch=(paused?pausedAt:Date.now())-selected*SCENE_DURATION;render();if(paused)inspectMoment();}
buttons.forEach(button=>button.addEventListener('click',()=>{selected=Number(button.dataset.scene);setCycle(false);replay();}));
document.querySelector('#replay').addEventListener('click',replay);
function setPaused(value){
  if(value===paused)return;paused=value;
  if(paused)pausedAt=Date.now();else epoch+=Date.now()-pausedAt;
  panel.classList.toggle('preview-paused',paused);
  const button=document.querySelector('#pause');button.textContent=paused?'Play animation':'Pause animation';button.setAttribute('aria-pressed',String(paused));
}
document.querySelector('#pause').addEventListener('click',()=>{setPaused(!paused);if(!paused)document.querySelector('#moment').value='';});
document.querySelector('#moment').addEventListener('change',event=>{if(event.target.value===''){setPaused(false);return;}setCycle(false);setPaused(true);inspectMoment();});
document.querySelector('#cycle').addEventListener('click',()=>{setCycle(!cycling);epoch=(paused?pausedAt:Date.now())-selected*SCENE_DURATION;render();});
render();
setInterval(render,500);
