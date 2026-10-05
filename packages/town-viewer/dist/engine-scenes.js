// Small, rigged SVG cartoons. CSS plays the poses; no per-frame JS.
import {rigArm,rigStyle,mitten} from './engine-scene-rig.js';
export const SCENE_DURATION = 18000;
export const ENGINE_SCENES = [
  {id:'pole', name:'The pole-planting crew', message:'A little elbow grease. A rather large splash.', sky:'#f8f2e6'},
  {id:'meter', name:'The meter detective', message:'No reading escapes that eye.', sky:'#edf3e9'},
  {id:'invoice', name:'The invoice express', message:'Sealed with a little too much enthusiasm.', sky:'#f2edf8'},
];

export function sceneIndexAt(elapsed) {
  return Math.floor(Math.max(0, elapsed) / SCENE_DURATION) % ENGINE_SCENES.length;
}

const ink = '#483049';
const palettes = {
  purple:{skin:'#b892d3',shade:'#a27abc',light:'#dbc4eb'},
  green:{skin:'#a6c78d',shade:'#85ad77',light:'#d5e6b7'},
  yellow:{skin:'#f7d883',shade:'#e7b95f',light:'#fff0b4'},
};

function arm(path, color, extra='') {
  return `<g ${extra}><path d="${path}" fill="none" stroke="${ink}" stroke-width="22"/><path d="${path}" fill="none" stroke="${color}" stroke-width="16"/></g>`;
}

function boots() {
  return `<g fill="#5b425a"><path d="M-29-20Q-18-23-12-14L-10-2Q-19 4-45 1Q-50-10-38-13L-32-14Z"/><path d="M15-19Q23-23 32-16L36-10Q52-11 53 1H14Q10-8 15-19Z"/></g><g stroke="#8b6b84" stroke-width="3"><path d="M-39-7L-19-7M22-7H42"/></g><path d="M-45 1H-11M15 1H51" stroke-width="4"/>`;
}

function body(color, office=false) {
  const c = palettes[color];
  const silhouette = color==='yellow'
    ? 'M-35-22C-51-46-29-101-8-119C1-127 14-124 20-113Q25-104 17-99Q9-99 7-106C8-88 37-79 44-50Q57-12 18-10L-16-11Q-30-12-35-22Z'
    : color==='green'
      ? 'M-42-26C-61-48-37-85-21-99Q-10-120 8-111C29-113 31-93 43-76Q66-43 44-22C26-5-25-7-42-26Z'
      : 'M-40-27C-56-52-29-76-26-94C-20-125 9-124 21-102C25-89 46-68 48-45Q54-16 23-12C1-6-26-10-40-27Z';
  return `${boots()}<path d="${silhouette}" fill="${c.skin}"/><path d="M-30-30Q-2-12 32-29Q39-21 26-17Q-8-7-30-22Z" fill="${c.shade}" stroke="none"/><path d="M-20-91Q-13-111-2-108" fill="none" stroke="${c.light}" stroke-width="6"/>
    ${office ? `<path d="M-29-67L0-55L24-70L34-52L14-44L1-52L-11-40L-35-56Z" fill="#fffaf0"/><g class="blob-tie"><path d="M-2-52L8-54L12-44L5-37L-3-43Z" fill="#8661b1"/><path d="M5-37L15-17L4-9L-3-22Z" fill="#8661b1"/></g>`
      : `<g fill="#edf05d"><path d="M-26-71L-11-66L-9-24L-32-22L-42-34L-36-59Z"/><path d="M22-70L36-68L48-42L39-23L13-20L13-62Z"/></g><g fill="#e6ece5" stroke="none"><path d="M-28-69L-22-67L-23-42L-29-41Z"/><path d="M26-68L32-67L38-42L31-40Z"/><path d="M-39-38L-10-35L-10-29L-37-32Z"/><path d="M14-36L45-41L43-34L14-29Z"/></g><path d="M-29-28L-16-26M22-25L33-27" stroke="#b0ac34" stroke-width="2"/>`}`;
}

function face(color) {
  const c=palettes[color];
  return `<g class="blob-face"><g fill="#fffdf4" stroke-width="2"><ellipse cx="-4" cy="-87" rx="9" ry="13"/><ellipse cx="17" cy="-88" rx="10" ry="14"/></g><g class="blob-pupils" fill="${ink}" stroke="none"><ellipse cx="-1" cy="-84" rx="4" ry="7"/><ellipse cx="21" cy="-85" rx="4.5" ry="7.5"/><circle cx="0" cy="-87" r="1.5" fill="white"/><circle cx="22" cy="-88" r="1.5" fill="white"/></g><path d="M-13-104Q-7-111 1-105M11-108Q21-116 29-107" fill="none" stroke-width="4"/><path d="M-8-68Q12-53 33-70Q31-40 12-43Q-1-45-8-68Z" fill="#654056"/><path d="M-5-65Q12-55 29-67L26-59Q9-52-2-59Z" fill="#fffdf4" stroke="none"/>${color==='yellow'?'':'<path d="M7-46Q15-58 25-48Q17-42 7-46Z" fill="#ed95a2" stroke="none"/>'}<path d="M20-78Q30-84 34-76Q34-70 24-70" fill="${c.skin}" stroke-width="2"/><path d="M-16-67Q-12-72-7-71" fill="none" stroke-width="2"/></g>`;
}

function scenery(kind) {
  if (kind==='invoice') return `<rect width="540" height="208" fill="#f3edf7"/><circle cx="232" cy="95" r="116" fill="#e9dff1"/><path d="M0 182H540V208H0Z" fill="#e4d7e8"/><g stroke="#d0bfd8" stroke-width="2" fill="none"><path d="M409 19H502V103H409Z M455 19V103M409 60H502"/></g><path d="M412 98L455 65L499 98" fill="#e1d4e9"/><g fill="#fdf9f0" stroke="#c8b7ce" stroke-width="2"><path d="M70 68L105 63L111 106L75 111Z"/><path d="M77 76L98 73M80 84L100 81M81 92L94 90"/></g>`;
  return `<rect width="540" height="208" fill="${kind==='pole'?'#f8f2e6':'#edf3e9'}"/><circle cx="86" cy="43" r="21" fill="#f0d79a"/><g fill="#fffdf6"><path d="M121 37Q118 24 133 25Q140 11 152 24Q168 21 172 35Q150 43 121 37Z"/><path d="M443 37Q447 26 458 29Q470 14 481 29Q497 28 494 39Z"/></g><path d="M0 159Q91 121 165 150T331 142T540 146V208H0Z" fill="${kind==='pole'?'#dfe4c9':'#d4e3c6'}"/><path d="M0 180Q113 164 213 178T540 173V208H0Z" fill="${kind==='pole'?'#cfd9ba':'#c0d3ae'}"/><g fill="none" stroke="#aabc98" stroke-width="2" stroke-linecap="round"><path d="M42 173L39 166M43 173L48 167M481 174L478 167M482 174L487 169"/></g>`;
}

function poleScene() {
  return `${scenery('pole')}<g opacity=".48" fill="#fffaf0" stroke="#b6b79d" stroke-width="2"><path d="M355 165V102L401 72L446 102V165Z"/><path d="M345 106L401 65L457 106" fill="none" stroke-width="4"/><path d="M370 111H385V133H370ZM412 111H430V133H412Z" fill="#ead6a0"/><path d="M395 139H411V165H395Z"/></g>
    <ellipse cx="251" cy="184" rx="92" ry="9" fill="#899171" opacity=".2"/>
    <g class="pole-ripple" fill="none" stroke="#998373" stroke-width="3"><ellipse cx="288" cy="182" rx="34" ry="6"/><ellipse cx="288" cy="182" rx="49" ry="10"/></g>
    ${rigArm('pole',palettes.purple.skin)}
    <g transform="translate(204 180)"><g class="pole-blob" stroke="${ink}" stroke-width="2.8" stroke-linejoin="round" stroke-linecap="round">
      ${arm('M-29-57Q-61-49-49-30Q-43-23-34-29',palettes.purple.shade,'class="pole-back-arm"')}
      ${body('purple')}${face('purple')}
    </g></g>
    <g class="pole-prop" stroke="${ink}" stroke-width="2.8" stroke-linejoin="round"><path d="M279 44Q288 40 296 44V181H279Z" fill="#b78359"/><path d="M282 48V170" stroke="#dbb283" stroke-width="3"/><path d="M292 56L288 87L293 118L288 164" fill="none" stroke="#956143" stroke-width="1.5"/><ellipse cx="287.5" cy="44" rx="8.5" ry="3" fill="#e0b589"/><path d="M271 67H304V75H271Z" fill="#9b9bab"/><path d="M277 66V52M298 66V52" stroke-width="4"/><path d="M273 53H281M294 53H302" stroke="#7f8090" stroke-width="5"/><g class="blob-grip" transform="translate(288 124)">${mitten(palettes.purple.skin)}</g></g>
    <g class="pole-splash" fill="#b29270" stroke="#735943" stroke-width="2" stroke-linejoin="round"><path d="M250 182Q265 183 256 168Q273 170 272 182Q282 176 278 163Q295 170 295 182Q310 172 315 162Q322 175 311 181Q330 169 338 181Q308 192 274 189Z"/><path d="M248 164Q226 146 230 141Q238 137 248 164Z"/><path d="M317 154Q330 130 335 137Q338 144 317 154Z"/><path d="M285 149Q276 124 283 123Q292 125 285 149Z"/></g>
    <g class="pole-drops" fill="#b29270"><ellipse cx="232" cy="135" rx="4" ry="6" transform="rotate(-35 232 135)"/><ellipse cx="340" cy="144" rx="5" ry="3" transform="rotate(-30 340 144)"/><circle cx="264" cy="143" r="3"/></g>
    <g class="pole-impact" stroke="#8b6655" stroke-width="3" stroke-linecap="round"><path d="M246 187L234 191M335 183L348 187M293 195V201"/></g>`;
}

function meterScene() {
  return `${scenery('meter')}<g stroke="#887d78" stroke-width="2.5" stroke-linejoin="round"><path d="M351 181V62L427 21L524 67V181Z" fill="#fff9e9"/><path d="M341 67L427 17L533 67" fill="none" stroke="#8b8084" stroke-width="7"/><path d="M352 89H523M352 119H523M352 149H523" stroke="#e4ddcd" stroke-width="1.5"/><path d="M451 75H492V120H451Z" fill="#dce9e3"/><path d="M470 76V119M452 98H491" stroke="#fff9e9" stroke-width="4"/>
    <path d="M392 57V84M392 141V179" fill="none" stroke="#969796" stroke-width="6"/><rect x="368" y="82" width="48" height="63" rx="9" fill="#c2ccc4"/><circle cx="392" cy="106" r="17" fill="#f9faf0"/><path d="M386 100L392 106L401 102" fill="none" class="meter-needle"/><rect x="379" y="124" width="26" height="10" rx="2" fill="#5f7169" stroke="none"/><path d="M383 127V131M388 127V131M394 127V131M400 127V131" stroke="#f8f8e5" stroke-width="2"/></g>
    <ellipse cx="262" cy="184" rx="79" ry="8" fill="#6f886c" opacity=".18"/>
    ${rigArm('meter',palettes.green.skin)}
    <g transform="translate(255 180)"><g class="meter-blob" stroke="${ink}" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round">
      ${arm('M-34-56Q-57-39-43-27Q-32-22-27-32',palettes.green.shade)}${body('green')}${face('green')}
    </g></g>
    <g class="meter-glass" stroke="${ink}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"><path d="M337 114L353 147" stroke-width="12"/><path d="M339 119L351 144" stroke="#79587d" stroke-width="6"/><circle cx="320" cy="89" r="32" fill="#837088"/><circle cx="320" cy="89" r="26" fill="#e5f2e4"/><g class="meter-big-eye"><ellipse cx="320" cy="89" rx="23" ry="25" fill="#fffdf4" stroke="#99ba81" stroke-width="3"/><ellipse cx="328" cy="92" rx="10" ry="17" fill="${ink}" stroke="none"/><ellipse cx="332" cy="85" rx="3" ry="5" fill="white" stroke="none"/></g><path d="M300 84Q302 69 317 68" fill="none" stroke="#fff" stroke-width="3" opacity=".8"/><g class="blob-grip" transform="translate(348 137)">${mitten(palettes.green.skin)}</g></g>
    <g class="meter-surprise" fill="none" stroke="#997a38" stroke-width="4" stroke-linecap="round"><path d="M304 39L300 29M324 36L327 23M344 43L352 34"/></g>
    <g class="meter-sparkle" fill="#e5b94e" stroke="#fff6d9" stroke-width="1"><path d="M431 96L434 104L442 107L434 110L431 119L428 110L420 107L428 104Z"/></g>`;
}

function invoiceScene() {
  return `${scenery('invoice')}<ellipse cx="250" cy="184" rx="84" ry="8" fill="#997da8" opacity=".17"/>
    ${rigArm('invoice',palettes.yellow.skin)}
    <g transform="translate(222 179)"><g class="invoice-blob" stroke="${ink}" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round">
      ${arm('M-30-57Q-52-42-40-25Q-29-20-24-30',palettes.yellow.shade)}${body('yellow',true)}${face('yellow')}
    </g></g>
    <g stroke="${ink}" stroke-width="2.5" stroke-linejoin="round"><path d="M293 149H470V158H293Z" fill="#bd926e"/><path d="M305 158V187M457 158V187" stroke="#806476" stroke-width="8"/><path d="M424 132H459V144H424Z" fill="#fffaf2"/><path d="M426 136H457M426 140H457" stroke="#c5b7c2" stroke-width="1"/><path d="M428 124H461V136H428Z" fill="#fffaf2"/><path d="M430 128H459M430 132H459" stroke="#c5b7c2" stroke-width="1"/></g>
    <g class="invoice-envelope" stroke="${ink}" stroke-width="2.5" stroke-linejoin="round"><path d="M303 99H388V142H303Z" fill="#decddc"/>
      <path class="invoice-flap" d="M303 99L345 68L388 99Z" fill="#fff8e9"/>
      <g class="invoice-paper"><path d="M318 70H373V125H318Z" fill="#fffef6"/><text x="345" y="83" text-anchor="middle" font-family="system-ui,sans-serif" font-size="7" font-weight="800" fill="#69506d" stroke="none">INVOICE</text><path d="M327 92H362M327 99H362M327 106H347" stroke="#b5a5b6" stroke-width="2"/></g>
      <path d="M303 99H388V143H303Z" fill="#fff8e9"/><path d="M303 99L345 124L388 99M303 143L330 116M388 143L360 116" fill="none" stroke="#b7a0b6" stroke-width="1.5"/>
      <path class="invoice-flap invoice-closing" d="M303 99L345 68L388 99Z" fill="#fff8e9"/>
      <g class="invoice-seal"><circle cx="345" cy="121" r="7" fill="#a584bf" stroke="none"/><path d="M342 120L345 123L349 118" fill="none" stroke="white" stroke-width="1.5"/></g>
    </g>
    <g class="invoice-palm blob-grip">${mitten(palettes.yellow.skin)}</g>
    <g class="invoice-speed" stroke="#ab83af" stroke-width="3" stroke-linecap="round"><path d="M356 99H394M347 110H404M365 122H395"/></g>
    <g class="invoice-pop" transform="translate(0 48)" fill="none" stroke="#a584bf" stroke-width="3" stroke-linecap="round"><path d="M348 53V44M365 58L371 51M329 58L323 50"/></g>`;
}

const drawings = [poleScene, meterScene, invoiceScene];
export function renderEngineScene(index, message) {
  const normalized = ((Math.trunc(Number(index)) || 0) % ENGINE_SCENES.length + ENGINE_SCENES.length) % ENGINE_SCENES.length;
  const scene = ENGINE_SCENES[normalized];
  const caption = String(message ?? scene.message).replace(/[&<>]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
  return `<svg class="blob-scene blob-scene--${scene.id}" data-scene="${scene.id}" viewBox="0 0 540 208" aria-hidden="true" focusable="false">${rigStyle(scene.id)}${drawings[normalized]()}</svg><span class="engine-scene-caption">${caption}</span>`;
}
