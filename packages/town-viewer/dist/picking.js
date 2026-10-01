// Register before orbit listeners and track the whole gesture, not only its endpoints.
export function bindPropertyPicking(canvas,pick,signal){
 let down=null;const pointers=new Set();
 canvas.addEventListener('pointerdown',e=>{pointers.add(e.pointerId);if(pointers.size>1){if(down)down.moved=true;return;}if(e.button===0)down={id:e.pointerId,x:e.clientX,y:e.clientY,moved:false};},{capture:true,signal});
 canvas.addEventListener('pointermove',e=>{if(down?.id===e.pointerId&&Math.hypot(e.clientX-down.x,e.clientY-down.y)>6)down.moved=true;},{capture:true,signal});
 canvas.addEventListener('pointerup',e=>{const click=down?.id===e.pointerId&&!down.moved&&e.button===0&&Math.hypot(e.clientX-down.x,e.clientY-down.y)<=6;pointers.delete(e.pointerId);if(down?.id===e.pointerId)down=null;if(click)pick(e);},{capture:true,signal});
 canvas.addEventListener('pointercancel',e=>{pointers.delete(e.pointerId);down=null;},{capture:true,signal});
}
