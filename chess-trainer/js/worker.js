"use strict";
(function () {
  const files = ["chess-core.js", "search.js", "trainer-core.js", "pool.js", "service.js"];
  if (typeof importScripts === "function") {
    importScripts.apply(null, files);
  } else if (typeof require === "function") {
    for (const f of files) require("./" + f);
  } else {
    throw new Error("no script loader available in worker");
  }
})();

const svc = self.ChessService.create({ reply: (m) => postMessage(m) });

self.onmessage = function (e) {
  svc.handle(e.data);
};
