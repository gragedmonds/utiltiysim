// utilsim viewer adapter. Same exports as the prototype's model.js, backed by the engine's utility-town/2.0
// snapshot (static file or the engine API) instead of generating towns in the browser.
export let VERSION = 'engine';
export const UTILS = ['electric', 'water', 'gas'];
export const LABELS = {electric: 'Electricity', water: 'Water', gas: 'Gas'};
export const COLORS = {electric: 0xe5a735, water: 0x149faf, gas: 0xa783d8};
export const round = (v, p = 3) => Math.round(v * 10 ** p) / 10 ** p;

const params = new URLSearchParams(location.search);
export const API = (params.get('api') || window.UTILSIM_API || '').replace(/\/$/, '');
export const STATIC_SNAPSHOT = params.get('snapshot') || './data/snapshot.json.gz';
export const PRESET = params.get('preset') || 'whitby_small';

// ---- terrain: bilinear sample of the snapshot heightmap ------------------------------------------------------
let T = null;
export function setTerrain(t) { T = t; }
export function terrain(x, z) {
  if (!T) return 0;
  const fx = (x - T.originX) / T.cellSizeM, fz = (z - T.originZ) / T.cellSizeM;
  const c = Math.max(0, Math.min(T.cols - 1.0001, fx)), r = Math.max(0, Math.min(T.rows - 1.0001, fz));
  const c0 = Math.floor(c), r0 = Math.floor(r), tc = c - c0, tr = r - r0, v = T.values;
  const a = v[r0][c0], b = v[r0][c0 + 1], d = v[r0 + 1][c0], e = v[r0 + 1][c0 + 1];
  return ((a * (1 - tc) + b * tc) * (1 - tr) + (d * (1 - tc) + e * tc) * tr) - T.base;
}

// ---- loading ------------------------------------------------------------------------------------------------
async function fetchJson(url, opts) {
  const res = await fetch(url, opts);
  if (!res.ok) throw Error(`${url}: ${res.status} ${await res.text()}`);
  if (url.endsWith('.gz') && !res.headers.get('content-encoding')) {
    const stream = res.body.pipeThrough(new DecompressionStream('gzip'));
    return JSON.parse(await new Response(stream).text());
  }
  return res.json();
}

export function parseOSM() {
  throw Error('OSM import runs in the engine: utilsim gen --config overrides.json (town.osm_source).');
}

export async function createTown(_source, {seed, count} = {}) {
  let snap;
  if (API) {
    const body = {preset: PRESET, seed: String(seed || 'WHITBY-042'), houses: Number(count) || undefined};
    const created = await fetchJson(`${API}/api/towns`, {method: 'POST', headers: {'Content-Type': 'application/json'},
                                                          body: JSON.stringify(body)});
    let status = created.status;
    while (status === 'building') {
      await new Promise(r => setTimeout(r, 1500));
      status = (await fetchJson(`${API}/api/towns/${created.townId}`)).status;
    }
    if (status !== 'ready') throw Error(`Town build ${status}`);
    const profile = (Number(count) || 0) > 2000 ? 'viewer' : 'full';
    snap = await fetchJson(`${API}/api/towns/${created.townId}/snapshot.json?profile=${profile}`);
  } else {
    snap = await fetchJson(STATIC_SNAPSHOT);
  }
  return prepare(snap);
}

export function prepare(snap) {
  VERSION = snap.generatorVersion;
  const base = Math.min(...snap.terrain.values.flat());
  setTerrain({...snap.terrain, base});
  snap._base = base;
  snap._premise = new Map(snap.premises.map((p, i) => [p.id, i]));
  snap._reads = new Map();
  for (const r of snap.sampleReads || []) {
    if (!snap._reads.has(r.premiseId)) snap._reads.set(r.premiseId, []);
    snap._reads.get(r.premiseId).push(r);
  }
  snap._topo = {};
  for (const u of UTILS) {
    const net = snap.networks[u], index = new Map(net.nodes.map((n, i) => [n.id, i]));
    const edgeIndex = new Map(net.edges.map((e, i) => [e.id, i]));
    const children = new Map();
    for (const e of net.edges) { if (!children.has(e.from)) children.set(e.from, []); children.get(e.from).push(e); }
    const ordered = [], q = [net.sourceId];
    for (let i = 0; i < q.length; i++) for (const e of children.get(q[i]) || []) { ordered.push({e, a: index.get(e.from), b: index.get(e.to)}); q.push(e.to); }
    snap._topo[u] = {index, edgeIndex, ordered, source: index.get(net.sourceId)};
  }
  snap.validation = snap.validation || {valid: true, errors: [], networkEdges: 0};
  snap.source.districtTiles = snap.source.districtTiles || 1;
  return snap;
}

// ---- demand and flows (identical shapes to the engine's FlowModel) ------------------------------------------
const SCENARIO = {solar: 'normal', outage: 'substation_outage'};
export function demand(h, hour, scenario = 'normal', target = null) {
  scenario = SCENARIO[scenario] || scenario;
  const occupied = h.occupied ? 1 : 0.09;
  const sun = Math.max(0, Math.sin((hour - 6) / 12 * Math.PI));
  const morning = Math.exp(-(((hour - 7.5) / 2) ** 2)), evening = Math.exp(-(((hour - 19) / 3) ** 2));
  let load = h.dailyKWh / 24 * (0.42 + 1.15 * morning + 1.65 * evening) * occupied;
  let water = h.dailyWaterM3 / 24 * (0.22 + 2.0 * morning + 1.8 * evening) * occupied;
  const gas = h.dailyGasM3 / 24 * (0.35 + 1.3 * morning + 0.8 * evening) * occupied;
  let generation = sun * (h.solarPeakKW ?? h.solarKW ?? 0) * (h.solar ? 1 : 0);
  if (scenario === 'leak' && h.id === target) water += 0.65;
  if (scenario === 'substation_outage') { load = 0; generation = 0; }
  return {electric: load - generation, water, gas: h.services.gas ? gas : 0, loadKW: load, generationKW: generation,
          importKW: Math.max(0, load - generation), exportKW: Math.max(0, generation - load)};
}

export function flows(town, hour, scenario = 'normal', target = null) {
  const homes = new Map(town.premises.map(h => [h.id, demand(h, hour, scenario, target)])), out = {homes};
  for (const u of UTILS) {
    const net = town.networks[u], t = town._topo[u], totals = new Float64Array(net.nodes.length);
    net.nodes.forEach((n, i) => { if (n.kind === 'meter' && n.premiseId) totals[i] = homes.get(n.premiseId)[u]; });
    const edgeFlows = new Map();
    for (let i = t.ordered.length - 1; i >= 0; i--) { const {e, a, b} = t.ordered[i]; edgeFlows.set(e.id, totals[b]); totals[a] += totals[b]; }
    out[u] = {source: totals[t.source], edgeFlows, unit: net.unit};
  }
  return out;
}

export function traceService(town, premiseId, utility) {
  const net = town.networks[utility], t = town._topo[utility], path = [];
  let i = t.index.get(`${utility}-N-${premiseId}`);
  while (i !== undefined && net.nodes[i].parentEdgeId) {
    const e = net.edges[t.edgeIndex.get(net.nodes[i].parentEdgeId)];
    path.push(e);
    i = t.index.get(e.from);
    if (path.length > net.edges.length) throw Error('Invalid network cycle');
  }
  return path.reverse();
}

export function monthlyReads(town, h) { return town._reads.get(h.id) || []; }

export async function ensureReads(town, h) {
  if (town._reads.has(h.id) || !API) return;
  const stack = await fetchJson(`${API}/api/towns/${town.id}/premises/${h.id}`);
  town._reads.set(h.id, stack.reads || []);
}

export function exportTown(town) {
  const out = {};
  for (const [k, v] of Object.entries(town)) if (!k.startsWith('_')) out[k] = v;
  return out;
}
