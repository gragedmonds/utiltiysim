// Rendering quality profiles. Phones and low-memory devices start in "lite": iOS/Android reclaim the WebGL context
// when a page uses too much GPU memory (the canvas goes blank while HTML labels stay). Presentation only: simulation
// data, demand and reads are identical in both profiles.
export const PROFILES={
 full:{name:'full',antialias:true,powerPreference:'high-performance',maxPixelRatio:1.75,shadows:true,streetscape:true,houseDetail:'auto'},
 lite:{name:'lite',antialias:false,powerPreference:'default',maxPixelRatio:1.5,shadows:false,streetscape:false,houseDetail:'simple'}
};
const KEY='utility-town-quality';
function storage(){try{return window.localStorage;}catch{return null;}}
export function rememberQuality(q){try{storage()?.setItem(KEY,q);}catch{}}
// Order: ?quality=lite|full (remembered), then a remembered choice, then the device: a coarse pointer on a small
// screen, or ≤ 4 GB device memory, means lite.
export function chooseQuality({search=globalThis.location?.search||'',saved,coarse,shortSide,deviceMemory}={}){
 const asked=new URLSearchParams(search).get('quality');
 if(asked==='lite'||asked==='full'){rememberQuality(asked);return asked;}
 if(saved===undefined){try{saved=storage()?.getItem(KEY);}catch{saved=null;}}
 if(saved==='lite'||saved==='full')return saved;
 coarse??=globalThis.matchMedia?.('(pointer: coarse)').matches??false;
 shortSide??=Math.min(globalThis.screen?.width??1920,globalThis.screen?.height??1080);
 deviceMemory??=globalThis.navigator?.deviceMemory??8;
 return (coarse&&shortSide<=900)||deviceMemory<=4?'lite':'full';
}
