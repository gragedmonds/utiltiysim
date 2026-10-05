// The body, reaching arm and held prop share one authored set of poses.
// Sampled CSS paths keep each wrist on its grip without a JS animation loop.
const bodyOrigin = {pole:[204,180],meter:[255,180],invoice:[222,179]};
const propOrigin = {pole:[288,180],meter:[320,89],invoice:[345,122]};
const shoulder = {pole:[32,-54],meter:[34,-54],invoice:[31,-53]};
const grip = {pole:[288,124],meter:[348,137],invoice:[307,131]};
const identity = [0,0,0,1,1];
const pose = (at, body=identity, prop=identity, hand=null) => ({at,body,prop,hand});

const poses = {
  pole:[
    pose(0,[-22,0,-3,1,1],[-22,-5,-12,1,1]),
    pose(5,[-22,0,-3,1,1],[-22,-5,-12,1,1]),
    pose(10,[-9,-4,3,1,1],[-9,-7,-6,1,1]),
    pose(18,identity,[0,0,-5,1,1]),
    pose(23,identity,[0,0,-5,1,1]),
    pose(30,[-10,2,-9,.97,1.04],[-20,-12,-20,1,1]),
    pose(36,[0,-10,5,.92,1.08],[0,-25,6,1,1]),
    pose(41,[8,2,6,1.1,.88],[0,3,-2,1,1]),
    pose(44,[3,-2,-2,.97,1.03],[0,0,2,1,1]),
    pose(49,[-2,-4,-3,.97,1.03]),
    pose(57),pose(80),
    pose(92,[-22,0,-3,1,1],[-22,-5,-12,1,1]),
    pose(100,[-22,0,-3,1,1],[-22,-5,-12,1,1]),
  ],
  meter:[
    pose(0,identity,[-25,47,-30,.58,.58]),
    pose(16,identity,[-25,47,-30,.58,.58]),
    pose(24,[-4,1,-3,1.02,.98],[-33,32,-20,.72,.72]),
    pose(35,[8,0,8,1,1],[-14,6,5,1,1]),
    pose(47,[8,0,8,1,1],[-14,6,5,1,1]),
    pose(55,[12,0,10,1,1],[-7,7,7,1.02,1.02]),
    pose(62,[3,-3,-2,.98,1.03],[-27,-3,-2,1.06,1.06]),
    pose(72,[8,0,7,1,1],[-14,5,4,1,1]),
    pose(80,[8,0,7,1,1],[-14,5,4,1,1]),
    pose(94,identity,[-25,47,-30,.58,.58]),
    pose(100,identity,[-25,47,-30,.58,.58]),
  ],
  invoice:[
    pose(0,identity,identity,[306,132]),
    pose(12,identity,identity,[306,132]),
    pose(24,[4,0,3,1,1],identity,[333,88]),
    pose(32,[5,0,4,1,1],identity,[344,79]),
    pose(43,[8,1,5,1.02,.98],identity,[345,119]),
    pose(48,[8,1,5,1.02,.98],identity,[345,119]),
    pose(57,identity),
    pose(65,[-7,0,-6,1,1],[-9,3,-8,1,1]),
    pose(71,[8,0,7,1.03,.98],[12,-5,3,1,1]),
    pose(76,[11,0,8,1.03,.98],[112,-24,-5,.9,.9],[351,116]),
    pose(83,[-3,-2,-2,1,1],[225,-45,-12,.75,.75],[315,129]),
    pose(89,identity,[225,-45,-12,.75,.75],[306,132]),
    pose(90,identity,identity,[306,132]),
    pose(100,identity,identity,[306,132]),
  ],
};

const round = n => Number(n.toFixed(2));
function point([x,y], [tx,ty,angle,sx,sy], [ox,oy]=[0,0]) {
  const rad=angle*Math.PI/180,dx=(x-ox)*sx,dy=(y-oy)*sy;
  return [ox+tx+dx*Math.cos(rad)-dy*Math.sin(rad),oy+ty+dx*Math.sin(rad)+dy*Math.cos(rad)];
}
function atPose(kind,at) {
  const frames=poses[kind];
  const end=frames.findIndex(frame=>frame.at>=at);
  if(end===0)return frames[0];
  const a=frames[end-1],b=frames[end];
  const progress=(at-a.at)/(b.at-a.at),t=progress*progress*(3-2*progress);
  const blend=(a,b)=>a.map((value,i)=>value+(b[i]-value)*t);
  const handA=a.hand||point(grip[kind],a.prop,propOrigin[kind]);
  const handB=b.hand||point(grip[kind],b.prop,propOrigin[kind]);
  const result={body:blend(a.body,b.body),prop:blend(a.prop,b.prop)};
  result.hand=kind==='invoice'&&(a.hand||b.hand)?blend(handA,handB):point(grip[kind],result.prop,propOrigin[kind]);
  return result;
}
const transform = ([x,y,r,sx,sy])=>`translate(${round(x)}px,${round(y)}px) rotate(${round(r)}deg) scale(${round(sx)},${round(sy)})`;
function reach(kind,frame) {
  const local=point(shoulder[kind],frame.body);
  const start=local.map((n,i)=>n+bodyOrigin[kind][i]);
  const hand=frame.hand||point(grip[kind],frame.prop,propOrigin[kind]);
  const elbow=[start[0]+(hand[0]-start[0])*.48,Math.min(162,Math.max(start[1],hand[1])+19)];
  return `M${start.map(round).join(' ')}Q${elbow.map(round).join(' ')} ${hand.map(round).join(' ')}`;
}

export function rigArm(kind,color) {
  const d=reach(kind,atPose(kind,kind==='meter'?47:57));
  return `<g class="${kind}-reach" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="${d}" stroke="#483049" stroke-width="21"/><path d="${d}" stroke="${color}" stroke-width="15"/></g>`;
}

export function mitten(color) {
  return `<g stroke="#483049" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"><path d="M-8 3Q-13-4-8-8Q-4-13 0-9Q5-13 8-7Q14-4 11 3Q9 12 0 12Q-8 11-8 3Z" fill="${color}"/><path d="M-5 0Q1 4 7 0" fill="none" stroke-width="1.5"/></g>`;
}

const styleCache=new Map();
export function rigStyle(kind) {
  if(styleCache.has(kind))return styleCache.get(kind);
  const still=atPose(kind,kind==='meter'?47:57);
  const propClass={pole:'pole-prop',meter:'meter-glass',invoice:'invoice-envelope'}[kind];
  const frames=Array.from({length:101},(_,i)=>({at:i,...atPose(kind,i)}));
  const bodyFrames=frames.map(f=>`${f.at}%{transform:${transform(f.body)}}`).join('');
  const propFrames=frames.map(f=>`${f.at}%{transform:${transform(f.prop)}}`).join('');
  const armFrames=frames.map(f=>`${f.at}%{d:path('${reach(kind,f)}')}`).join('');
  const palm=still.hand||point(grip[kind],still.prop,propOrigin[kind]);
  const handFrames=kind==='invoice'?frames.map(f=>`${f.at}%{transform:translate(${f.hand.map(n=>round(n)+'px').join(',')})}`).join(''):'';
  const rules=`<style>
    .blob-scene--${kind} .${kind}-blob{transform:${transform(still.body)};animation-name:rig-${kind}-body;animation-timing-function:linear}
    .blob-scene--${kind} .${propClass}{transform:${transform(still.prop)};animation-name:rig-${kind}-prop${kind==='invoice'?',blob-envelope-visible':''};animation-timing-function:linear}
    .blob-scene--${kind} .${kind}-reach path{animation:rig-${kind}-reach var(--gag) linear infinite}
    @keyframes rig-${kind}-body{${bodyFrames}}
    @keyframes rig-${kind}-prop{${propFrames}}
    @keyframes rig-${kind}-reach{${armFrames}}
    ${kind==='invoice'?`.invoice-palm{transform:translate(${palm.map(n=>round(n)+'px').join(',')});animation:rig-invoice-hand var(--gag) linear infinite}@keyframes rig-invoice-hand{${handFrames}}`:''}
  </style>`;
  styleCache.set(kind,rules);
  return rules;
}
