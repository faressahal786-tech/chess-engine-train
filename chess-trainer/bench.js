require("./js/chess-core.js");
require("./js/search.js");
const C = globalThis.ChessCore, E = globalThis.Engine;

let t0 = Date.now();
const r = E.think(C.createStart(), E.defaultParams(), { maxDepth: 6, timeMs: 8000 });
console.log("NEW: depth", r.depth, "·", r.nodes, "nodes ·", ((r.nodes / ((Date.now() - t0) / 1000)) / 1000).toFixed(1) + "k nps");

const scholar = "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4";
const s = C.setFen(new C.Position(), scholar);
const m = E.think(s, E.defaultParams(), { maxDepth: 4, timeMs: 4000 });
const posCheck = C.setFen(new C.Position(), scholar);
console.log("mate test:", C.san(posCheck, m.move), "| score", m.score);

const br = C.setFen(new C.Position(), "k7/8/1K6/8/8/8/8/7R w - - 0 1");
const rb = E.think(br, E.defaultParams(), { maxDepth: 4, timeMs: 4000 });
console.log("backrank:", C.san(C.setFen(new C.Position(), "k7/8/1K6/8/8/8/8/7R w - - 0 1"), rb.move), "| score", rb.score);
