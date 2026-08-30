"use strict";
(function (root) {
  function createPool(workerPath, size) {
    const workers = [];
    const pending = {};
    let nextId = 1;
    let terminated = false;

    for (let i = 0; i < size; i++) {
      let w;
      try { w = new Worker(workerPath); }
      catch (err) {
        for (const prev of workers) { try { prev.terminate(); } catch (e2) { void e2; } }
        throw err;
      }
      w.onmessage = (e) => {
        const d = e.data || {};
        if (d.type === "result" && pending[d.id]) {
          const res = pending[d.id];
          delete pending[d.id];
          res(d.ok ? d.results : []);
        }
      };
      w.onerror = () => {
        for (const id in pending) {
          const res = pending[id];
          delete pending[id];
          res([]);
        }
      };
      workers.push(w);
    }

    function chunk(jobs, n) {
      const out = [];
      for (let i = 0; i < n; i++) out.push([]);
      jobs.forEach((j, idx) => out[idx % n].push(j));
      return out.map((part, i) => ({ part, worker: workers[i] })).filter((p) => p.part.length > 0);
    }

    return {
      size,
      playBatch(jobs, champParams, challParams, opts) {
        if (terminated || !jobs.length) return Promise.resolve([]);
        return Promise.all(
          chunk(jobs, workers.length).map(({ part, worker }) => new Promise((resolve) => {
            const id = nextId++;
            pending[id] = resolve;
            worker.postMessage({ cmd: "games", id, jobs: part, champParams, challParams, opts });
          }))
        ).then((arrs) => arrs.flat());
      },
      terminate() {
        if (terminated) return;
        terminated = true;
        for (const id in pending) { delete pending[id]; }
        for (const w of workers) { try { w.terminate(); } catch (e) { void e; } }
      }
    };
  }

  root.GamePool = { createPool };
  if (typeof module !== "undefined" && module.exports) module.exports = root.GamePool;
})(typeof globalThis !== "undefined" ? globalThis : this);
