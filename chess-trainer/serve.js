const path = require("path");
const fs = require("fs");

const ROOT = __dirname;
const PORT = Number(process.env.PORT || 8123);

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon"
};

Bun.serve({
  port: PORT,
  async fetch(req) {
    const url = new URL(req.url);
    let rel = decodeURIComponent(url.pathname);
    if (rel === "/") rel = "/index.html";
    const file = path.join(ROOT, rel);
    if (!file.startsWith(ROOT)) return new Response("Forbidden", { status: 403 });
    try {
      const data = await Bun.file(file).arrayBuffer();
      const ext = path.extname(file).toLowerCase();
      return new Response(data, {
        headers: { "Content-Type": MIME[ext] || "application/octet-stream" }
      });
    } catch (e) {
      void e;
      return new Response("Not found: " + rel, { status: 404 });
    }
  }
});

console.log(`Chess Trainer running at http://localhost:${PORT}`);
console.log("Open the URL in your browser to play or train.");
console.log("Press Ctrl+C to stop.");
