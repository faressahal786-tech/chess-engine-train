"use strict";
(function () {
  const files = ["chess-core.js", "search.js", "trainer-core.js"];
  if (typeof importScripts === "function") {
    importScripts.apply(null, files);
  } else if (typeof require === "function") {
    for (const f of files) require("./" + f);
  }

  const G = typeof globalThis !== "undefined" ? globalThis : self;
  const T = G.Trainer;

  self.onmessage = function (e) {
    const d = e.data || {};
    if (d.cmd === "games") {
      const results = [];
      try {
        for (const job of d.jobs) {
          const rng = T.mulberry32(job.seed >>> 0);
          const res = T.playGame({
            whiteParams: job.challengerWhite ? d.challParams : d.champParams,
            blackParams: job.challengerWhite ? d.champParams : d.challParams,
            depth: d.opts.depth,
            maxPlies: d.opts.maxPlies,
            openPlies: d.opts.openPlies,
            timeMsPerMove: d.opts.timeMsPerMove || 0,
            rng: rng
          });
          let pts = 0, w = 0, l = 0, dr = 0;
          if (res.result === "d") { dr = 1; pts = 0.5; }
          else if ((res.result === "w") === job.challengerWhite) { w = 1; pts = 1; }
          else l = 1;
          results.push({ pts, w, l, d: dr, plies: res.plies });
        }
        postMessage({ type: "result", id: d.id, ok: true, results });
      } catch (err) {
        postMessage({ type: "result", id: d.id, ok: false, message: String(err), results: [] });
      }
    }
  };
})();
