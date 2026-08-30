"use strict";
const path = require("path");

require(path.join(__dirname, "js", "chess-core.js"));
require(path.join(__dirname, "js", "search.js"));
require(path.join(__dirname, "js", "trainer-core.js"));

const C = globalThis.ChessCore;
const E = globalThis.Engine;
const T = globalThis.Trainer;

let passed = 0, failed = 0;
function check(name, cond, extra) {
  if (cond) { passed++; console.log("  ok  " + name); }
  else { failed++; console.log("FAIL  " + name + (extra !== undefined ? "  -> " + extra : "")); }
}

console.log("[perft]");
const PERFT_SUITE = [
  { name: "startpos", fen: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", counts: [20, 400, 8902, 197281] },
  { name: "kiwipete", fen: "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", counts: [48, 2039, 97862] },
  { name: "pos3", fen: "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", counts: [14, 191, 2812, 43238] },
  { name: "pos4", fen: "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", counts: [6, 264, 9467] },
  { name: "pos5", fen: "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", counts: [44, 1486, 62379] },
  { name: "pos6", fen: "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10", counts: [46, 2079, 89890] }
];
for (const t of PERFT_SUITE) {
  const pos = C.setFen(new C.Position(), t.fen);
  for (let d = 0; d < t.counts.length; d++) {
    const n = C.perft(pos, d + 1);
    check(`${t.name} depth ${d + 1} (${n})`, n === t.counts[d], `expected ${t.counts[d]}, got ${n}`);
  }
}

console.log("\n[fen roundtrip]");
for (const t of PERFT_SUITE) {
  const pos = C.setFen(new C.Position(), t.fen);
  const out = C.toFen(pos);
  const reparsed = C.setFen(new C.Position(), out);
  check(t.name, C.toFen(reparsed) === out, `${out}`);
}
{
  const pos = C.createStart();
  const moves = C.legalMoves(pos);
  let allOk = true;
  for (const m of moves) {
    C.makeMove(pos, m);
    if (C.toFen(C.setFen(new C.Position(), C.toFen(pos))) !== C.toFen(pos)) allOk = false;
    C.unmakeMove(pos);
  }
  check("start unmake restores FEN", allOk && C.toFen(pos) === "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
}

console.log("\n[game status]");
{
  const stalemate = C.setFen(new C.Position(), "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1");
  const st = C.gameStatus(stalemate);
  check("stalemate detected", st.over && st.result === "1/2-1/2" && st.reason === "stalemate", JSON.stringify(st));
  const foolsMate = C.setFen(new C.Position(), "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3");
  const fs = C.gameStatus(foolsMate);
  check("fools mate detected", fs.over && fs.result === "0-1" && fs.reason === "checkmate", JSON.stringify(fs));
  const kvk = C.setFen(new C.Position(), "8/8/4k3/8/8/3K4/8/8 w - - 0 1");
  check("K vs K insufficient", C.insufficientMaterial(kvk) === true);
  const knk = C.setFen(new C.Position(), "8/8/4k3/8/8/3K4/5N2/8 w - - 0 1");
  check("KN vs K insufficient", C.insufficientMaterial(knk) === true);
  const kpk = C.setFen(new C.Position(), "8/8/4k3/8/8/3K4/4P3/8 w - - 0 1");
  check("KP vs K sufficient", C.insufficientMaterial(kpk) === false);
}

console.log("\n[san]");
function sanOf(fen, from, to, promo) {
  const pos = C.setFen(new C.Position(), fen);
  const legal = C.legalMoves(pos);
  for (const m of legal) {
    if (C.mFrom(m) === from && C.mTo(m) === to && (C.mPromo(m) || 0) === (promo || 0)) return C.san(pos, m, legal);
  }
  return null;
}
{
  const e2 = C.parseSq("e2"), e4 = C.parseSq("e4");
  check("pawn push SAN", sanOf(C.toFen(C.createStart()), e2, e4) === "e4", sanOf(C.toFen(C.createStart()), e2, e4));
  const g1 = C.parseSq("g1"), f3 = C.parseSq("f3");
  check("knight SAN", sanOf(C.toFen(C.createStart()), g1, f3) === "Nf3", sanOf(C.toFen(C.createStart()), g1, f3));
  const disFen = "k7/8/8/8/8/8/8/KN3N2 w - - 0 1";
  check("disambiguation Nbd2", sanOf(disFen, C.parseSq("b1"), C.parseSq("d2")) === "Nbd2", sanOf(disFen, C.parseSq("b1"), C.parseSq("d2")));
  const castleFen = "r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1";
  check("O-O san", sanOf(castleFen, C.parseSq("e1"), C.parseSq("g1")) === "O-O", sanOf(castleFen, C.parseSq("e1"), C.parseSq("g1")));
  check("O-O-O san", sanOf(castleFen, C.parseSq("e1"), C.parseSq("c1")) === "O-O-O", sanOf(castleFen, C.parseSq("e1"), C.parseSq("c1")));
  const promoFen = "rn2k3/1P6/8/8/8/8/8/4K3 w q - 0 1";
  check("promotion bxa8=Q", sanOf(promoFen, C.parseSq("b7"), C.parseSq("a8"), C.QUEEN) === "bxa8=Q", sanOf(promoFen, C.parseSq("b7"), C.parseSq("a8"), C.QUEEN));
  const promoFen2 = "4k3/1P6/8/8/8/8/8/4K3 w - - 0 1";
  check("promotion b8=Q+", sanOf(promoFen2, C.parseSq("b7"), C.parseSq("b8"), C.QUEEN) === "b8=Q+", sanOf(promoFen2, C.parseSq("b7"), C.parseSq("b8"), C.QUEEN));
  const epFen = "rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3";
  check("en passant exf6", sanOf(epFen, C.parseSq("e5"), C.parseSq("f6")) === "exf6", sanOf(epFen, C.parseSq("e5"), C.parseSq("f6")));
  const mateFen = "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4";
  check("Qxf7# san", sanOf(mateFen, C.parseSq("h5"), C.parseSq("f7")) === "Qxf7#", sanOf(mateFen, C.parseSq("h5"), C.parseSq("f7")));
}

console.log("\n[search]");
{
  const pos = C.setFen(new C.Position(), "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4");
  const r = E.think(pos, E.defaultParams(), { maxDepth: 3 });
  check("finds Qxf7#", r && C.mFrom(r.move) === C.parseSq("h5") && C.mTo(r.move) === C.parseSq("f7"),
    r ? C.san(C.setFen(new C.Position(), "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"), r.move) + " score=" + r.score : "null");
  check("mate score large", Math.abs(r.score) > E.MATE - 100, String(r.score));

  const backRank = C.setFen(new C.Position(), "k7/8/1K6/8/8/8/8/7R w - - 0 1");
  const rb = E.think(backRank, E.defaultParams(), { maxDepth: 2 });
  check("back-rank mate found", rb && C.mTo(rb.move) === C.parseSq("h8") && Math.abs(rb.score) > E.MATE - 100,
    rb ? C.san(backRank, rb.move) : "null");

  const start = C.createStart();
  const rs = E.think(start, E.defaultParams(), { maxDepth: 2 });
  check("start search returns legal move", rs && C.legalMoves(start).indexOf(rs.move) >= 0);
  check("search nodes > 0", rs.nodes > 0);

  const pos2 = C.createStart();
  const before = C.toFen(pos2);
  E.evaluate(pos2, E.defaultParams());
  check("evaluate does not mutate position", C.toFen(pos2) === before);
}

console.log("\n[trainer]");
{
  const rng = T.mulberry32(42);
  const brain = { version: 1, meta: { generation: 0, record: { w: 0, l: 0, d: 0 } }, params: E.defaultParams() };
  const state = T.newTrainerState(brain);
  const res = T.evolveOnce(state, { gamesPerGen: 2, depth: 1, maxPlies: 60, openPlies: 2, rng });
  check("evolveOnce completes", !!res && typeof res.chPts === "number", JSON.stringify(res));
  check("games counted", state.stats.games === 2, String(state.stats.games));
  check("generation advanced or kept", state.stats.gen >= 0);

  const ser = T.serializeBrain(state.brain);
  const json = JSON.stringify(ser);
  const back = T.deserializeBrain(json);
  const ser2 = T.serializeBrain(back);
  check("brain JSON roundtrip", JSON.stringify(ser2) === json);

  const mutated = T.mutateParams(state.brain.params, rng, 1);
  let inRange = true;
  for (const k of ["p", "n", "b", "r", "q"]) if (!(mutated.val[k] >= 20 && mutated.val[k] <= 1500)) inRange = false;
  check("mutation keeps values sane", inRange, JSON.stringify(mutated.val));
  let finite = true;
  outer: for (const side of ["pstW", "pstB"]) {
    for (const k of ["p", "n", "b", "r", "q", "kmg", "keg"]) {
      for (let i = 0; i < 128; i++) {
        if (!isFinite(mutated[side][k][i])) { finite = false; break outer; }
      }
    }
  }
  check("mutation produces finite PSTs", finite);
}

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
