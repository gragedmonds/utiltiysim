// Browser frame intervals, not GPU timings. No wall-clock guesses or capped animation deltas.
export function summarizeFrames(intervals){
 const samples=intervals.filter(v=>Number.isFinite(v)&&v>0);if(!samples.length)return null;
 const sorted=[...samples].sort((a,b)=>a-b),sum=samples.reduce((a,b)=>a+b,0),tail=sorted.slice(-Math.max(1,Math.ceil(sorted.length*.01)));
 return {samples:samples.length,elapsedMs:sum,fps:1000*samples.length/sum,meanFrameMs:sum/samples.length,p95FrameMs:sorted[Math.ceil(sorted.length*.95)-1],onePercentLowFps:1000/(tail.reduce((a,b)=>a+b,0)/tail.length),framesOver33ms:samples.filter(v=>v>33.333).length,maxFrameMs:sorted.at(-1)};
}
export class FrameMonitor{
 constructor(){this.last=null;this.samples=[];this.lastPublish=0;this.latest=null;}
 reset(){this.last=null;this.samples=[];this.latest=null;}
 push(now,visible=true){if(!visible){this.reset();return null;}const delta=this.last===null?null:now-this.last;this.last=now;if(delta!==null&&delta>0)this.samples.push({at:now,delta});while(this.samples.length&&this.samples[0].at<now-2000)this.samples.shift();if(now-this.lastPublish>=500){this.lastPublish=now;this.latest=summarizeFrames(this.samples.map(s=>s.delta));}return delta;}
}
export const BENCHMARK_PHASES=['town_overview','neighbourhood','street_detail'];
export class BenchmarkSession{
 constructor(start,context){this.start=start;this.context=structuredClone(context);this.samples=BENCHMARK_PHASES.map(()=>[]);this.renderStats=BENCHMARK_PHASES.map(()=>({trianglesMin:null,trianglesMax:0,drawCallsMax:0,detailedHomesMax:0}));this.lastPhase=-1;this.previousElapsed=0;this.cancelReason=null;}
 cancel(reason){this.cancelReason=reason;}
 step(now,delta){const elapsed=(now-this.start)/1000,index=Math.min(2,Math.floor(elapsed/10));if(this.cancelReason)return {done:true,cancelled:true};
  // Discard each view's first two seconds and any interval crossing into/out of warm-up.
  if(delta>0&&index===this.lastPhase&&elapsed-index*10>=2&&this.previousElapsed-index*10>=2)this.samples[index].push(delta);
  this.lastPhase=index;this.previousElapsed=elapsed;return {done:elapsed>=30,index,phase:BENCHMARK_PHASES[index],progress:Math.min(1,elapsed/30),phaseProgress:Math.max(0,Math.min(1,(elapsed-index*10)/10))};
 }
 recordRender({triangles,drawCalls,detailedHomes}){if(this.lastPhase<0)return;const s=this.renderStats[this.lastPhase];s.trianglesMin=s.trianglesMin===null?triangles:Math.min(s.trianglesMin,triangles);s.trianglesMax=Math.max(s.trianglesMax,triangles);s.drawCallsMax=Math.max(s.drawCallsMax,drawCalls);s.detailedHomesMax=Math.max(s.detailedHomesMax,detailedHomes||0);}
 report(){const sufficient=this.samples.every(s=>s.length>=2);return {schemaVersion:'viewer-benchmark/1.0',status:this.cancelReason?'cancelled':sufficient?'completed':'insufficient_samples',cancelReason:this.cancelReason||(!sufficient?'Too few visible frames to compare all three views.':null),context:this.context,metric:'requestAnimationFrame intervals; not GPU timing',durationSeconds:30,warmupSecondsPerView:2,phases:BENCHMARK_PHASES.map((phase,i)=>({phase,...summarizeFrames(this.samples[i]),render:this.renderStats[i]})),overall:summarizeFrames(this.samples.flat())};}
}
