"use strict";
(function (root) {
  const C = root.ChessCore, E = root.Engine, T = root.Trainer;

  function defaultBrain() {
    return {
      version: 1,
      meta: { generation: 0, bornAtGame: 0, record: { w: 0, l: 0, d: 0 } },
      params: E.defaultParams()
    };
  }

  function create(bridge, opts2) {
    opts2 = opts2 || {};
    const reply = typeof bridge === "function" ? bridge : (m) => bridge.reply(m);
    const isWorkerCtx = typeof importScripts === "function";
    let state = null;
    let running = false;
    let paused = false;
    let trainOpts = null;
    let pool = null;
    let loopScheduled = false;

    function detectCores() {
      try {
        if (typeof navigator !== "undefined" && navigator.hardwareConcurrency) return navigator.hardwareConcurrency;
        if (typeof os !== "undefined" && os.availableParallelism) return os.availableParallelism();
      } catch (e) { void e; }
      return 4;
    }

    function ensurePool(size) {
      if (pool && pool.size === size) return pool;
      if (pool) { pool.terminate(); pool = null; }
      if (!root.GamePool) return null;
      const path = opts2.workerPath || (isWorkerCtx ? "game-worker.js" : "js/game-worker.js");
      try {
        pool = root.GamePool.createPool(path, size);
      } catch (e) {
        pool = null;
      }
      return pool;
    }

    function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

    function ensureState(brainObj) {
      if (!state) state = T.newTrainerState(brainObj || defaultBrain());
    }

    function finishGen(res) {
      reply({
        type: "genDone",
        improved: res.improved,
        chPts: res.chPts,
        games: res.games,
        chW: res.chW,
        chL: res.chL,
        draws: res.draws,
        avgPlies: res.avgPlies,
        stats: state.stats
      });
      if (res.improved) reply({ type: "brain", brain: T.serializeBrain(state.brain) });
    }

    async function runAsyncLoop() {
      while (running && !paused && !loopScheduled) {
        loopScheduled = true;
        let res;
        try {
          res = await T.evolveOnceAsync(state, trainOpts, pool);
        } catch (err) {
          running = false;
          loopScheduled = false;
          reply({ type: "error", message: String(err) });
          return;
        }
        loopScheduled = false;
        if (!running) break;
        finishGen(res);
        await sleep(0);
      }
    }

    function runSyncLoop() {
      let res;
      try {
        res = T.evolveOnce(state, trainOpts);
      } catch (err) {
        running = false;
        reply({ type: "error", message: String(err) });
        return;
      }
      finishGen(res);
      if (!running || paused) return;
      setTimeout(loop, 0);
    }

    function loop() {
      if (!running || paused) return;
      const threads = trainOpts.threads | 0;
      if (threads > 1) {
        const p = ensurePool(threads);
        if (p && p.size > 1) { runAsyncLoop(); return; }
      }
      runSyncLoop();
    }

    function pvToSan(pos, pv) {
      const out = [];
      try {
        let legal = C.legalMoves(pos);
        for (let i = 0; i < Math.min(pv.length, 6); i++) {
          const m = pv[i];
          let found = null;
          for (const lm of legal) {
            if (lm === m || (C.mFrom(lm) === C.mFrom(m) && C.mTo(lm) === C.mTo(m) && C.mPromo(lm) === C.mPromo(m))) { found = lm; break; }
          }
          if (found == null) break;
          out.push(C.san(pos, found, legal));
          C.makeMove(pos, found);
          legal = C.legalMoves(pos);
        }
      } catch (err) { void err; }
      return out;
    }

    function handle(d) {
      if (!d || !d.cmd) return;
      switch (d.cmd) {
        case "hello":
          ensureState(d.brain);
          reply({ type: "hello", brain: T.serializeBrain(state.brain) });
          break;
        case "load":
          try {
            const b = T.deserializeBrain(d.brain);
            running = false;
            paused = false;
            state = T.newTrainerState(b);
            reply({ type: "loaded", brain: T.serializeBrain(state.brain) });
          } catch (err) {
            reply({ type: "error", message: String(err) });
          }
          break;
        case "start":
          ensureState(d.brain);
          trainOpts = d.opts || {};
          if (!Number.isFinite(trainOpts.threads) || trainOpts.threads < 1) trainOpts.threads = detectCores();
          trainOpts.threads = Math.min(trainOpts.threads | 0, 64);
          if (!running) {
            running = true;
            paused = false;
            reply({ type: "started", stats: state.stats, threads: trainOpts.threads });
            loop();
          } else if (paused) {
            paused = false;
            reply({ type: "resumed", threads: trainOpts.threads });
            loop();
          }
          break;
        case "pause":
          paused = true;
          break;
        case "resume":
          if (running && paused) { paused = false; loop(); }
          break;
        case "stop":
          running = false;
          paused = false;
          if (pool) { pool.terminate(); pool = null; }
          if (state) reply({ type: "stopped", brain: T.serializeBrain(state.brain), stats: state.stats });
          break;
        case "think": {
          try {
            const pos = C.setFen(new C.Position(), d.fen);
            let params = null;
            if (d.brain) params = E.paramsFromPlain(d.brain.params || d.brain);
            else if (state) params = state.brain.params;
            else params = E.defaultParams();
            const r = E.think(pos, params, d.opts || {});
            const pvSan = r && r.pv ? pvToSan(pos, r.pv) : [];
            reply({
              type: "thinkResult",
              id: d.id,
              epoch: d.epoch,
              hint: !!d.hint,
              ok: true,
              from: r ? C.mFrom(r.move) : -1,
              to: r ? C.mTo(r.move) : -1,
              promo: r ? C.mPromo(r.move) : 0,
              score: r ? r.score : 0,
              depth: r ? r.depth : 0,
              nodes: r ? r.nodes : 0,
              timeMs: r ? r.timeMs : 0,
              pvSan
            });
          } catch (err) {
            reply({ type: "thinkResult", id: d.id, epoch: d.epoch, ok: false, message: String(err) });
          }
          break;
        }
      }
    }

    return {
      handle,
      getStats: () => (state ? state.stats : null),
      getBrain: () => (state ? T.serializeBrain(state.brain) : null),
      isTraining: () => running && !paused
    };
  }

  root.ChessService = { create };
  if (typeof module !== "undefined" && module.exports) module.exports = root.ChessService;
})(typeof globalThis !== "undefined" ? globalThis : this);
