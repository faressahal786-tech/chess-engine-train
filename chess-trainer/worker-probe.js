"use strict";
const path = require("path");

console.log("creating bun Worker from js/worker.js ...");
const w = new Worker(path.join(__dirname, "js", "worker.js"));

w.onmessage = (e) => {
  console.log("worker ->", JSON.stringify(e.data).slice(0, 220));
  if (e.data && e.data.type === "hello") {
    const pos = globalThis.ChessCore.createStart();
    w.postMessage({
      cmd: "think", id: 7, epoch: 1,
      fen: globalThis.ChessCore.toFen(pos),
      opts: { maxDepth: 2, timeMs: 1500 }
    });
  }
  if (e.data && e.data.type === "thinkResult") {
    console.log("THINK OK:", JSON.stringify(e.data));
    process.exit(0);
  }
};
w.onerror = (err) => { console.error("worker error:", err.message || err); };
globalThis.process.on("exit", () => { try { w.terminate(); } catch (e) { void e; } });

setTimeout(async () => {
  console.error("TIMEOUT — no thinkResult after 8s");
  process.exit(1);
}, 8000);

require(path.join(__dirname, "js", "chess-core.js"));
setTimeout(() => {
  const C = globalThis.ChessCore;
  const pos = C.createStart();
  w.postMessage({ cmd: "hello" });
}, 100);
