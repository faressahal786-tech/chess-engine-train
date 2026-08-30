"use strict";
(function () {
  let files = ["chess-core.js", "search.js"];
  if (typeof importScripts === "function") importScripts.apply(null, files);
  else if (typeof require === "function") for (const f of files) require("./" + f);
  const C = (typeof globalThis !== "undefined" ? globalThis : self).ChessCore;
  const E = (typeof globalThis !== "undefined" ? globalThis : self).Engine;
  self.onmessage = function (e) {
    const d = e.data || {};
    if (d.cmd === "search") {
      try {
        const pos = C.setFen(new C.Position(), d.fen);
        const params = E.paramsFromPlain(d.params);
        const r = E.think(pos, params, { maxDepth: d.depth, timeMs: d.timeMs, rootNoise: 0, pickMargin: 0 });
        postMessage({ id: d.id, ok: true, move: r ? r.move : 0, score: r ? r.score : 0, depth: r ? r.depth : 0, nodes: r ? r.nodes : 0 });
      } catch (err) {
        postMessage({ id: d.id, ok: false, message: String(err) });
      }
    }
  };
})();
