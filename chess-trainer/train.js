const path = require("path");
const fs = require("fs");

require(path.join(__dirname, "js", "chess-core.js"));
require(path.join(__dirname, "js", "search.js"));
require(path.join(__dirname, "js", "trainer-core.js"));
require(path.join(__dirname, "js", "pool.js"));

const T = globalThis.Trainer;

function arg(name, def) {
  const i = process.argv.indexOf("--" + name);
  if (i === -1 || i + 1 >= process.argv.length) return def;
  return process.argv[i + 1];
}

const minutes = parseFloat(arg("minutes", "5"));
const depth = parseInt(arg("depth", "2"), 10);
const gamesPerGen = parseInt(arg("games-per-gen", "12"), 10);
const maxPlies = parseInt(arg("max-plies", "140"), 10);
const openPlies = parseInt(arg("open-plies", "4"), 10);
const strength = parseFloat(arg("mutation", "1"));
const seed = parseInt(arg("seed", String((Math.random() * 0xffffffff) >>> 0)), 10);
const outPath = path.resolve(__dirname, arg("out", "brains/brain.json"));

let threads = parseInt(arg("threads", "0"), 10);
if (!threads || threads < 1) {
  try { threads = navigator.hardwareConcurrency || 4; }
  catch (e) { threads = (require("os").cpus() || []).length || 4; }
}
threads = Math.max(1, Math.min(threads, 64));

if (!fs.existsSync(path.dirname(outPath))) fs.mkdirSync(path.dirname(outPath), { recursive: true });

let brain;
if (fs.existsSync(outPath)) {
  brain = T.deserializeBrain(fs.readFileSync(outPath, "utf8"));
  console.log(`resuming from ${path.basename(outPath)} (gen ${brain.meta.generation})`);
} else {
  brain = {
    version: 1,
    meta: { generation: 0, bornAtGame: 0, record: { w: 0, l: 0, d: 0 } },
    params: globalThis.Engine.defaultParams()
  };
}

const state = T.newTrainerState(brain);
const rng = T.mulberry32(seed);
const deadline = Date.now() + minutes * 60000;

console.log(`self-play training: ${minutes} min · depth ${depth} · ${gamesPerGen} games/gen · ${threads} threads · out ${outPath}`);
console.log("press Ctrl+C to stop early (progress is saved on every improvement)");

let pool = null;
try {
  const workerPath = require("path").join(__dirname, "js", "game-worker.js");
  pool = globalThis.GamePool.createPool(workerPath, threads);
  console.log(`worker pool ready (${pool.size} workers)`);
} catch (e) {
  console.log("worker pool unavailable (" + e.message + ") — training single-threaded");
  pool = null;
}

let saving = false;
function save() {
  if (saving) return;
  saving = true;
  try {
    const tmp = outPath + ".tmp";
    fs.writeFileSync(tmp, JSON.stringify(T.serializeBrain(state.brain)));
    fs.renameSync(tmp, outPath);
  } catch (e) {
    console.error("save failed:", e.message);
  }
  saving = false;
}

process.on("SIGINT", () => {
  console.log("\nstopping…");
  if (pool) pool.terminate();
  save();
  const s = state.stats;
  console.log(`final: gen ${s.gen} · ${s.games} games · ${s.improvements} improvements`);
  process.exit(0);
});

async function main() {
  const t0 = Date.now();
  while (Date.now() < deadline) {
    const opts = { depth, gamesPerGen, maxPlies, openPlies, strength, rng };
    let res;
    if (pool) res = await T.evolveOnceAsync(state, opts, pool);
    else res = T.evolve_once ? null : T.evolveOnce(state, opts);
    if (!res) break;
    const s = state.stats;
    const elapsedMin = ((Date.now() - t0) / 60000).toFixed(1);
    const rate = (s.games / Math.max(0.01, (Date.now() - t0) / 60000)).toFixed(1);
    console.log(
      `gen ${String(s.gen).padStart(4)} · challenger ${res.chPts}/${res.games} (${res.chW}W ${res.chL}L ${res.draws}D)` +
      `${res.improved ? " ★ promoted" : ""} · total ${s.games} games · ${rate}/min`
    );
    if (res.improved) save();
  }
  if (pool) pool.terminate();
  save();
  const s = state.stats;
  console.log(`done: gen ${s.gen} · ${s.games} games trained · ${s.improvements} improvements`);
  console.log(`brain saved to ${outPath}`);
  process.exit(0);
}

main().catch((e) => {
  console.error("fatal:", e);
  if (pool) pool.terminate();
  save();
  process.exit(1);
});
