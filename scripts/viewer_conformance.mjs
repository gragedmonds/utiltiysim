// Engine → viewer conformance. Runs Astra's real receiver (packages/town-viewer/dist) against an engine export
// directory (snapshot.json[.gz], replay-day.json, state-*.json) and checks the handoff smoke list:
// load the native snapshot, keep metre geometry and offsets, select a house, trace each connection, show a supplied
// read, keep missing values null, accept signed-flow frames, reject a frame from a mismatched topology.
// Usage: node scripts/viewer_conformance.mjs [exportDir]
import fs from 'node:fs'; import path from 'node:path'; import zlib from 'node:zlib';
import {inspectSnapshot, StateReceiver, traceConnection} from '../packages/town-viewer/dist/adapter.js';
import {customerIndex, customerProfile} from '../packages/town-viewer/dist/customer.js';

const dir = process.argv[2] || 'examples/whitby-480-seed42';
const readJson = p => JSON.parse(p.endsWith('.gz') ? zlib.gunzipSync(fs.readFileSync(p)) : fs.readFileSync(p, 'utf8'));
const snapPath = fs.existsSync(path.join(dir, 'snapshot.json')) ? path.join(dir, 'snapshot.json') : path.join(dir, 'snapshot.json.gz');
const snap = readJson(snapPath);
const results = [];
const check = (name, fn) => {
  try { const detail = fn(); results.push({name, ok: true, detail}); }
  catch (e) { results.push({name, ok: false, detail: String(e.message || e)}); }
};
const expectThrow = (fn, what) => { try { fn(); } catch (e) { return e.message; } throw Error(`${what} was not rejected`); };

let inspection;
check('inspectSnapshot accepts the native 2.0 snapshot', () => {
  const before = JSON.stringify(snap.bounds);
  inspection = inspectSnapshot(snap);
  if (JSON.stringify(snap.bounds) !== before) throw Error('inspection mutated the snapshot');
  if (snap.source.utilityOffsets !== 'geometry') throw Error('offsets not declared as geometry');
  return {premises: snap.premises.length, homes: snap.homes, edges: Object.values(snap.networks).reduce((a, n) => a + n.edges.length, 0)};
});
const home = snap.premises.find(h => h.premiseType === 'residential' && h.services.gas) || snap.premises[0];
check('trace a house to a source on every service', () => {
  const out = {};
  for (const u of ['electric', 'water', 'gas']) {
    if (!home.services[u]) continue;
    const t = traceConnection(snap, home.id, u);
    if (!t.connected) throw Error(`${u}: ${t.reason}`);
    const sources = new Set(snap.networks[u].sourceIds || [snap.networks[u].sourceId]);
    if (!sources.has(t.sourceId)) throw Error(`${u}: unexpected source ${t.sourceId}`);
    out[u] = t.edges.length;
  }
  return {premise: home.id, edges: out};
});
check('customer profile joins account, meters and supplied reads', () => {
  const p = customerProfile(snap, customerIndex(snap), home, snap.simulation.epoch);
  if (!p.account) throw Error('no account');
  if (!p.partner) throw Error('no business partner');
  if (!p.services.length || !p.services.every(s => s.meters.length)) throw Error('service without meter');
  if (snap.detail === 'full' && !p.reads.length) throw Error('no reads supplied for a full snapshot');
  return {account: p.account.id, services: p.services.length, reads: p.reads.length, contracts: p.contracts.length};
});
const frames = [];
if (snap.stateFrame) frames.push(['embedded stateFrame', [snap.stateFrame]]);
for (const f of fs.readdirSync(dir).filter(f => /^(replay|state)-.*\.json$/.test(f)).sort()) {
  const j = readJson(path.join(dir, f));
  frames.push([f, j.frames ?? [j]]);
}
for (const [name, list] of frames) {
  check(`receiver accepts ${name} (${list.length} frame${list.length === 1 ? '' : 's'})`, () => {
    const r = new StateReceiver(inspection);
    let nulls = 0, negatives = 0;
    for (const f of list) {
      const {flow} = r.accept(f);
      for (const u of ['electric', 'water', 'gas']) for (const v of flow[u].edgeFlows.values()) { if (v === null) nulls++; else if (v < 0) negatives++; }
    }
    return {nullFlowsKept: nulls, negativeFlows: negatives};
  });
}
check('water loop flows arrive, and a null flow stays null (unknown never becomes zero)', () => {
  const loops = snap.networks.water.edges.filter(e => e.loop && e.enabled).map(e => e.id);
  if (!loops.length) return {loops: 0};
  const {flow} = new StateReceiver(inspection).accept(snap.stateFrame);
  const missing = loops.filter(id => typeof flow.water.edgeFlows.get(id) !== 'number');
  if (missing.length) throw Error(`${missing.length} loop edges have no flow`);
  // An engine whose loop solve fell back sends null on its loops: the receiver must keep it null.
  const w = snap.stateFrame.networks.water, i = w.edgeIds.indexOf(loops[0]);
  const fallback = {...snap.stateFrame, networks: {...snap.stateFrame.networks, water: {...w, flows: w.flows.map((v, k) => k === i ? null : v)}}};
  const kept = new StateReceiver(inspection).accept(fallback).flow.water.edgeFlows.get(loops[0]);
  if (kept !== null) throw Error(`a null loop flow became ${kept}`);
  return {loops: loops.length};
});
check('outage frame isolates customers through disabled supply edges', () => {
  const p = path.join(dir, 'state-substation_outage.json');
  if (!fs.existsSync(p)) return 'no outage frame in export';
  const f = readJson(p);
  const r = new StateReceiver(inspection);
  const {flow} = r.accept(f);
  const t = traceConnection(snap, home.id, 'electric', flow.electric.edgeEnabled);
  if (t.connected) throw Error('house still connected during substation outage');
  const water = traceConnection(snap, home.id, 'water', flow.water.edgeEnabled);
  if (!water.connected) throw Error('water should stay connected');
  return {electric: t.reason};
});
check('receiver rejects mismatched, stale and foreign frames', () => {
  const f = snap.stateFrame;
  const reasons = {};
  reasons.topology = expectThrow(() => new StateReceiver(inspection).accept({...f, topologyRevision: 'topo-tampered'}), 'tampered topology');
  reasons.town = expectThrow(() => new StateReceiver(inspection).accept({...f, townId: 'town-0000000000000000'}), 'foreign town');
  const r = new StateReceiver(inspection);
  r.accept(f);
  reasons.stale = expectThrow(() => r.accept({...f}), 'duplicate sequence');
  return reasons;
});
const failed = results.filter(r => !r.ok);
console.log(JSON.stringify({export: dir, townId: snap.id, passed: results.length - failed.length, failed: failed.length, results}, null, 2));
process.exit(failed.length ? 1 : 0);
