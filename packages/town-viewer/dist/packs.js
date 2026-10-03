// Engine town packs: prebuilt, immutable towns served next to the viewer (packs/index.json, town-pack/1.0).
// A pack is the engine's own snapshot and day replay; the viewer validates them like any loaded file.
export async function fetchPackIndex(base='./packs/'){
 try{const r=await fetch(base+'index.json',{cache:'no-cache'});if(!r.ok)return null;const index=await r.json();
  if(index?.schemaVersion!=='town-pack/1.0'||!Array.isArray(index.towns))return null;return {...index,base};}
 catch{return null;}
}
export async function fetchGzipJSON(url){
 const r=await fetch(url);if(!r.ok)throw Error(`Could not load ${url} (${r.status}).`);
 // Servers may already have decoded the body (Content-Encoding); only gunzip a real gzip stream.
 const bytes=new Uint8Array(await r.arrayBuffer());
 if(bytes[0]!==0x1f||bytes[1]!==0x8b)return JSON.parse(new TextDecoder().decode(bytes));
 const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
 return JSON.parse(await new Response(stream).text());
}
// The engine town a bare address opens (the small town, the one the Studio is tested on), else the index's first.
export const DEFAULT_TOWN='small_town';
export function defaultPack(packs){const list=packs?.towns||[];return list.find(t=>t.preset===DEFAULT_TOWN)||list[0]||null;}
// Packs are generic towns named by their preset: small_town → Small town.
export function packLabel(t){const s=String(t.preset||'').replaceAll('_',' ');return s.charAt(0).toUpperCase()+s.slice(1);}
// ?town=<ref>: a prebuilt pack (by preset or its town id), else a town the engine generated (its town id; the
// snapshot then comes from the engine, which is also its live connection).
export function townRoute(ref,packs){if(!ref)return null;const t=packs?.towns?.find(t=>t.preset===ref||t.townId===ref);if(t)return {pack:t};return /^town-[0-9a-f]{8,64}$/i.test(ref)||isTownRef(ref)?{townId:ref}:null;}
// A generated town's self-describing name: its preset plus the settings that differ, e.g. small_town~eJyr… (any engine rebuilds it).
export function isTownRef(ref){return /^[a-z0-9_]+~[A-Za-z0-9_-]{4,4000}$/.test(String(ref||''));}
export function engineSnapshotUrl(api,tid){return `${api}/towns/${encodeURIComponent(tid)}/snapshot.json?detail=viewer&profile=viewer`;}
export function packCaption(t){return `${Number(t.homes).toLocaleString('en-CA')} homes`;}
