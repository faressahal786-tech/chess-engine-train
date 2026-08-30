"use strict";
(function (root) {
  const C = root.ChessCore;
  const E = root.Engine;

  function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function gauss(rng) {
    let u = 0, v = 0;
    while (u === 0) u = rng();
    while (v === 0) v = rng();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  }

  function cloneParams(P) {
    const out = { val: Object.assign({}, P.val), pstW: {}, pstB: {} };
    for (const k of ["p", "n", "b", "r", "q", "kmg", "keg"]) {
      out.pstW[k] = Float64Array.from(P.pstW[k]);
      out.pstB[k] = Float64Array.from(P.pstB[k]);
    }
    for (const k of ["bishopPair", "doubled", "isolated", "passed", "rookOpen", "rookHalf", "kingShield", "tempo"])
      out[k] = P[k];
    return out;
  }

  function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }

  const SCALAR_SPEC = {
    bishopPair: [6, 0, 90],
    doubled: [4, 0, 45],
    isolated: [4, 0, 45],
    passed: [5, 0, 90],
    rookOpen: [5, 0, 70],
    rookHalf: [3, 0, 40],
    kingShield: [3, -10, 35],
    tempo: [2, -8, 30]
  };

  function mutateParams(base, rng, strength) {
    strength = strength == null ? 1 : strength;
    const P = cloneParams(base);
    const valRange = { p: [50, 260], n: [180, 520], b: [180, 540], r: [350, 800], q: [600, 1300] };
    for (const k of ["p", "n", "b", "r", "q"]) {
      const sigma = (k === "p" ? 14 : 20) * strength;
      P.val[k] = clamp(P.val[k] + gauss(rng) * sigma, valRange[k][0], valRange[k][1]);
    }
    for (const side of ["pstW", "pstB"]) {
      for (const k of ["p", "n", "b", "r", "q", "kmg", "keg"]) {
        const arr = P[side][k];
        for (let i = 0; i < 128; i++) {
          if (!(i & 0x88)) {
            let d = gauss(rng) * (7 * strength);
            if (rng() < 0.02) d += gauss(rng) * 26 * strength;
            arr[i] = clamp(arr[i] + d, -140, 140);
          }
        }
      }
    }
    for (const k in SCALAR_SPEC) {
      const [sigma, lo, hi] = SCALAR_SPEC[k];
      P[k] = clamp(P[k] + gauss(rng) * sigma * strength, lo, hi);
    }
    return P;
  }

  function materialDiff(pos) {
    const b = pos.board;
    let diff = 0;
    for (let sq = 0; sq < 128; sq++) {
      if (sq & 0x88) { sq += 7; continue; }
      const p = b[sq];
      if (!p) continue;
      const t = p & 7;
      if (t === C.KING) continue;
      const v = t === C.PAWN ? 100 : t === C.KNIGHT ? 320 : t === C.BISHOP ? 330 : t === C.ROOK ? 500 : 900;
      diff += (p >> 3) === C.WHITE ? v : -v;
    }
    return diff;
  }

  function playGame(opts, onMove) {
    opts = opts || {};
    const whiteP = opts.whiteParams, blackP = opts.blackParams;
    const depth = opts.depth || 2;
    const maxPlies = opts.maxPlies || 160;
    const openPlies = opts.openPlies != null ? opts.openPlies : 4;
    const timeMsPerMove = opts.timeMsPerMove || 0;
    const rng = opts.rng || mulberry32(0x9e3779b9);

    const pos = C.createStart();
    const keys = [C.posKey(pos)];
    let plies = 0;
    let result = null, reason = null;

    while (true) {
      const status = C.gameStatus(pos, keys, 2);
      if (status.over) {
        result = status.result === "1-0" ? "w" : status.result === "0-1" ? "b" : "d";
        reason = status.reason;
        break;
      }
      if (plies >= maxPlies) {
        const d = materialDiff(pos);
        if (Math.abs(d) >= 250) { result = d > 0 ? "w" : "b"; reason = "adjudicated"; }
        else { result = "d"; reason = "ply limit"; }
        break;
      }
      const params = pos.turn === C.WHITE ? whiteP : blackP;
      let move = null;
      if (plies < openPlies) {
        const legal = status.moves;
        move = legal[Math.floor(rng() * legal.length)];
      } else {
        const r = E.think(pos, params, { maxDepth: depth, timeMs: timeMsPerMove });
        move = r ? r.move : status.moves[0];
      }
      if (onMove && plies < 12) onMove(C.san(pos, move, status.moves), plies);
      else if (onMove && plies % 20 === 0) onMove("…", plies);
      C.makeMove(pos, move);
      keys.push(C.posKey(pos));
      plies++;
    }
    return { result, reason, plies };
  }

  function newTrainerState(startBrain) {
    return {
      brain: startBrain,
      stats: { gen: startBrain.generation || 0, games: 0, w: 0, l: 0, d: 0, improvements: 0, lastChPts: 0, lastGames: 0, totalPlies: 0 }
    };
  }

  function applyGeneration(state, champMeta, challenger, chPts, chW, chL, draws, pliesSum, gamesPlayed) {
    const stats = state.stats;
    stats.games += gamesPlayed;
    stats.totalPlies += pliesSum;
    stats.lastChPts = chPts;
    stats.lastGames = gamesPlayed;
    let improved = false;
    if (gamesPlayed > 0 && chPts > gamesPlayed / 2) {
      improved = true;
      state.stats.improvements++;
      const meta = Object.assign({}, champMeta, {
        generation: (champMeta && champMeta.generation || 0) + 1,
        bornAtGame: state.stats.games,
        record: {
          w: (champMeta && champMeta.record && champMeta.record.w || 0),
          l: (champMeta && champMeta.record && champMeta.record.l || 0),
          d: (champMeta && champMeta.record && champMeta.record.d || 0)
        }
      });
      meta.record.w += chW; meta.record.l += chL; meta.record.d += draws;
      state.brain = { version: 1, params: challenger, meta };
      state.stats.gen = meta.generation;
    } else {
      if (champMeta && !champMeta.record) champMeta.record = { w: 0, l: 0, d: 0 };
      if (champMeta && champMeta.record) { champMeta.record.l += chW; champMeta.record.w += chL; champMeta.record.d += draws; }
    }
    return improved;
  }

  function evolveOnce(state, opts) {
    opts = opts || {};
    const games = opts.gamesPerGen || 8;
    const gameOpts = {
      depth: opts.depth || 2,
      maxPlies: opts.maxPlies || 160,
      openPlies: opts.openPlies != null ? opts.openPlies : 4,
      timeMsPerMove: opts.timeMsPerMove || 0
    };
    const champMeta = state.brain.meta;
    const challenger = mutateParams(state.brain.params, opts.rng || mulberry32((Math.random() * 0xffffffff) >>> 0), opts.strength || 1);
    let chPts = 0, chW = 0, chL = 0, draws = 0, pliesSum = 0;
    for (let g = 0; g < games; g++) {
      const challengerWhite = g % 2 === 0;
      const res = playGame({
        whiteParams: challengerWhite ? challenger : state.brain.params,
        blackParams: challengerWhite ? state.brain.params : challenger,
        depth: gameOpts.depth,
        maxPlies: gameOpts.maxPlies,
        openPlies: gameOpts.openPlies,
        timeMsPerMove: gameOpts.timeMsPerMove,
        rng: mulberry32((opts.rng ? opts.rng() : Math.random()) * 0xffffffff)
      });
      pliesSum += res.plies;
      if (res.result === "d") { draws++; chPts += 0.5; }
      else if ((res.result === "w") === challengerWhite) { chW++; chPts += 1; }
      else chL++;
    }
    const gamesPlayed = chW + chL + draws;
    const improved = applyGeneration(state, champMeta, challenger, chPts, chW, chL, draws, pliesSum, gamesPlayed);
    return { improved, chPts, games: gamesPlayed, chW, chL, draws, avgPlies: gamesPlayed ? Math.round(pliesSum / gamesPlayed) : 0 };
  }

  function evolveOnceAsync(state, opts, pool) {
    opts = opts || {};
    const games = opts.gamesPerGen || 8;
    const champMeta = state.brain.meta;
    const challenger = mutateParams(state.brain.params,
      opts.rng || mulberry32((Math.random() * 0xffffffff) >>> 0), opts.strength || 1);
    const jobs = [];
    for (let g = 0; g < games; g++) {
      jobs.push({
        challengerWhite: g % 2 === 0,
        seed: (opts.rng ? opts.rng() : Math.random()) * 0xffffffff >>> 0
      });
    }
    const gameOpts = {
      depth: opts.depth || 2,
      maxPlies: opts.maxPlies || 160,
      openPlies: opts.openPlies != null ? opts.openPlies : 4,
      timeMsPerMove: opts.timeMsPerMove || 0
    };
    return pool.playBatch(jobs, state.brain.params, challenger, gameOpts).then((results) => {
      let chPts = 0, chW = 0, chL = 0, draws = 0, pliesSum = 0;
      for (const r of results) {
        chPts += r.pts; chW += r.w; chL += r.l; draws += r.d; pliesSum += r.plies;
      }
      const gamesPlayed = chW + chL + draws;
      const improved = applyGeneration(state, champMeta, challenger, chPts, chW, chL, draws, pliesSum, gamesPlayed);
      return {
        improved, chPts, games: gamesPlayed, chW, chL, draws,
        avgPlies: gamesPlayed ? Math.round(pliesSum / gamesPlayed) : 0
      };
    });
  }

  function serializeBrain(brain) {
    return {
      version: 1,
      meta: brain.meta || { generation: brain.generation || 0, record: brain.record || { w: 0, l: 0, d: 0 } },
      params: E.paramsToPlain(brain.params)
    };
  }

  function deserializeBrain(obj) {
    if (!obj) throw new Error("empty brain");
    const src = typeof obj === "string" ? JSON.parse(obj) : obj;
    const meta = src.meta || { generation: src.generation || 0, record: src.record || { w: 0, l: 0, d: 0 } };
    return { version: 1, meta, params: E.paramsFromPlain(src.params) };
  }

  const api = {
    mulberry32, gauss, cloneParams, mutateParams,
    playGame, newTrainerState, evolveOnce, evolveOnceAsync,
    serializeBrain, deserializeBrain, materialDiff
  };
  root.Trainer = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
