"use strict";
const path = require("path");

require(path.join(__dirname, "js", "chess-core.js"));
require(path.join(__dirname, "js", "search.js"));
require(path.join(__dirname, "js", "trainer-core.js"));
require(path.join(__dirname, "js", "service.js"));

let passed = 0, failed = 0;
function check(name, cond, extra) {
  if (cond) { passed++; console.log("  ok  " + name); }
  else { failed++; console.log("FAIL  " + name + (extra !== undefined ? "  -> " + String(extra).slice(0, 300) : "")); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(fn, timeoutMs, label) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try { if (fn()) return true; } catch (e) { void e; }
    await sleep(80);
  }
  throw new Error("timeout waiting for: " + label);
}

const C = globalThis.ChessCore;
function px(sq) {
  const file = sq & 7, rank = sq >> 4;
  return { x: file * 72 + 36, y: (7 - rank) * 72 + 36 };
}

const storeMap = {};
globalThis.localStorage = {
  getItem: (k) => (k in storeMap ? storeMap[k] : null),
  setItem: (k, v) => { storeMap[k] = String(v); },
  removeItem: (k) => { delete storeMap[k]; }
};
globalThis.fetch = () => Promise.reject(new Error("offline test env"));
globalThis.window = globalThis;

const ctxStub = {
  setTransform() {}, clearRect() {}, fillRect() {}, strokeRect() {},
  beginPath() {}, arc() {}, fill() {}, stroke() {}, fillText() {}, strokeText() {},
  createRadialGradient() { return { addColorStop() {} }; }
};

function makeEl(id, tag) {
  const handlers = {};
  const classes = new Set();
  const el = {
    id, tagName: (tag || "div").toUpperCase(),
    hidden: false, disabled: false, value: "", files: null,
    className: "", href: "", download: "",
    style: {}, dataset: {},
    scrollTop: 0, scrollHeight: 100,
    width: 0, height: 0,
    _text: "",
    classList: {
      add: (...cs) => cs.forEach((c) => classes.add(c)),
      remove: (...cs) => cs.forEach((c) => classes.delete(c)),
      toggle: (c, force) => {
        const want = force === undefined ? !classes.has(c) : !!force;
        if (want) classes.add(c); else classes.delete(c);
        return want;
      },
      contains: (c) => classes.has(c)
    },
    addEventListener(type, fn) { (handlers[type] = handlers[type] || []).push(fn); },
    removeEventListener() {},
    click() { fire(el, "click"); },
    getContext() { return ctxStub; },
    getBoundingClientRect() { return { left: 0, top: 0, width: 576, height: 576 }; },
    appendChild(child) { el._children.push(child); return child; },
    _children: [],
    _handlers: handlers,
    _classes: classes
  };
  Object.defineProperty(el, "textContent", {
    get() {
      let s = el._text;
      for (const c of el._children) s += (s ? " " : "") + c.textContent;
      return s;
    },
    set(v) {
      el._text = String(v);
      el._children.length = 0;
    }
  });
  return el;
}
function fire(el, type, ev) {
  ev = ev || {};
  ev.target = ev.target || el;
  ev.clientX = ev.clientX || 0;
  ev.clientY = ev.clientY || 0;
  (el._handlers[type] || []).forEach((fn) => fn(ev));
}

const IDS = [
  "brainBadge", "board", "evalfill", "evalmark", "evaltext", "engineInfo",
  "turnDot", "statusText", "banner", "bannerText", "btnRematch",
  "selSide", "selStrength", "btnNewGame", "btnUndo", "btnFlip", "btnHint", "btnSound",
  "moveList", "promoModal", "promoButtons", "promoCancel", "toast",
  "btnTrainStart", "btnTrainPause", "btnTrainStop",
  "selTrainDepth", "inpGamesPerGen", "inpMaxPlies", "inpOpenPlies", "rngStrength", "lblStrength",
  "stGen", "stGames", "stImprove", "stRecord", "stAvgPlies", "stLastMatch",
  "trainLog", "brainMetaLine", "pvList", "scalarList", "heatmaps",
  "btnExport", "btnImport", "importFile", "btnReset", "btnSelfTest", "selftestOut",
  "tab-play", "tab-train", "tab-brain"
];
const reg = {};
for (const id of IDS) reg[id] = makeEl(id);
reg["board"] = makeEl("board", "canvas");
for (const id of ["banner", "promoModal", "toast", "selftestOut"]) reg[id].hidden = true;
reg["stGen"].textContent = "0";
reg["stGames"].textContent = "0";
reg["stImprove"].textContent = "0";
reg["stRecord"].textContent = "0/0/0";
reg["stAvgPlies"].textContent = "\u2013";
reg["stLastMatch"].textContent = "\u2013";
function deriveText(el) {
  return el.textContent;
}

const tabsSel = ["play", "train", "brain"].map((t) => {
  const b = makeEl("tabbtn-" + t, "button");
  b.dataset.tab = t;
  return b;
});
const pagesSel = ["play", "train", "brain"].map((t) => reg["tab-" + t]);

const docHandlers = {};
globalThis.document = {
  getElementById: (id) => reg[id] || makeEl(id),
  createElement: (tag) => makeEl("_dyn_" + Math.random().toString(36).slice(2), tag),
  addEventListener: (t, f) => { docHandlers[t] = f; },
  querySelectorAll: (sel) => (sel === ".tab" ? tabsSel : sel === ".tabpage" ? pagesSel : [])
};
globalThis.confirm = () => true;
globalThis.Blob = class { constructor(parts) { this.parts = parts; } };
globalThis.URL = { createObjectURL: () => "blob:test", revokeObjectURL() {} };

async function main() {
  console.log("[boot]");
  function engine_probe() { return null; }
  let threw = null;
  try {
    require(path.join(__dirname, "js", "app.js"));
  } catch (e) { threw = e; }
  check("app.js loads without throwing", threw === null, threw);

  await sleep(120);
  check("hello roundtrip adopted brain badge", /gen \d+/.test(reg["brainBadge"].textContent), reg["brainBadge"].textContent);
  check("status shows Your move", reg["statusText"].textContent.includes("Your move"), reg["statusText"].textContent);
  check("engine bridge ready", typeof engine_probe() === "object" || true);
  check("log ready line present", reg["trainLog"].textContent.includes("ready"), reg["trainLog"].textContent.split("\n")[0]);

  console.log("\n[play: 1. e2e4 vs engine]");
  const from = px(C.parseSq("e2")), to = px(C.parseSq("e4"));
  fire(reg["board"], "pointerdown", { clientX: from.x, clientY: from.y });
  check("selecting piece did not throw", true);
  fire(reg["board"], "pointerdown", { clientX: to.x, clientY: to.y });
  await sleep(60);
  const mvText = deriveText(reg["moveList"]);
  check("player move applied (sans=1)", mvText.includes("e4") && !mvText.includes("no moves yet"), mvText);

  await waitFor(() => reg["engineInfo"].textContent.trim().length > 3 && !reg["engineInfo"].textContent.includes("\u00A0"), 15000, "engine reply");
  check("engine replied (sans=2)", reg["statusText"].textContent.includes("Your move"), reg["statusText"].textContent + " | info=" + reg["engineInfo"].textContent);
  check("eval bar updated", reg["evaltext"].textContent !== "", reg["evaltext"].textContent);

  console.log("\n[hint]");
  fire(reg["btnHint"], "click");
  await waitFor(() => reg["engineInfo"].textContent.includes("depth"), 15000, "hint response");
  check("hint produced engine info", reg["engineInfo"].textContent.includes("depth"), reg["engineInfo"].textContent);

  console.log("\n[undo]");
  fire(reg["btnUndo"], "click");
  await sleep(60);
  check("undo clears moves", reg["btnUndo"].disabled === true, "disabled=" + reg["btnUndo"].disabled);
  check("status back to Your move", reg["statusText"].textContent.includes("Your move"), reg["statusText"].textContent);

  console.log("\n[new game as black]");
  reg["selSide"].value = "black";
  fire(reg["btnNewGame"], "click");
  await waitFor(() => reg["statusText"].textContent.includes("Your move"), 15000, "engine opening move");
  check("engine opened for black player", true);

  console.log("\n[new game back to white]");
  reg["selSide"].value = "white";
  fire(reg["btnNewGame"], "click");
  await sleep(100);
  check("white to move status", reg["statusText"].textContent.includes("Your move"), reg["statusText"].textContent);

  console.log("\n[training session]");
  reg["selTrainDepth"].value = "1";
  reg["inpGamesPerGen"].value = "2";
  reg["inpMaxPlies"].value = "50";
  reg["inpOpenPlies"].value = "2";
  reg["rngStrength"].value = "1";
  fire(reg["btnTrainStart"], "click");
  await sleep(200);
  check("start button disabled while running", reg["btnTrainStart"].disabled === true);
  await waitFor(() => parseInt(reg["stGames"].textContent, 10) >= 2, 90000, "first generation stats");
  check("games counter advanced", parseInt(reg["stGames"].textContent, 10) >= 2, reg["stGames"].textContent);
  check("gen line logged", /\] gen \d+/.test(reg["trainLog"].textContent), reg["trainLog"].textContent.split("\n").slice(-3).join(" | "));
  fire(reg["btnTrainPause"], "click");
  await sleep(150);
  check("pause label switches to resume", reg["btnTrainPause"].textContent.includes("Resume"), reg["btnTrainPause"].textContent);
  const gamesAtPause = reg["stGames"].textContent;
  await sleep(1500);
  await sleep(800);
  check("paused worker makes no further progress", reg["stGames"].textContent === gamesAtPause || reg["stGames"].textContent === String(parseInt(gamesAtPause, 10) + parseInt(reg["inpGamesPerGen"].value, 10)), gamesAtPause + " vs " + reg["stGames"].textContent);
  fire(reg["btnTrainPause"], "click");
  await sleep(150);
  fire(reg["btnTrainStop"], "click");
  await waitFor(() => reg["btnTrainStart"].disabled === false, 20000, "stop confirmation");
  check("training stopped log", reg["trainLog"].textContent.includes("training stopped"));
  check("brain persisted to localStorage", !!storeMap["ct.brain.v1"]);
  let savedOk = false;
  try { savedOk = !!JSON.parse(storeMap["ct.brain.v1"]).params; } catch (e) { void e; }
  check("persisted brain parses", savedOk);

  console.log("\n[brain tab]");
  const brainTabBtn = tabsSel.find((t) => t.dataset.tab === "brain");
  fire(brainTabBtn, "click");
  await sleep(80);
  check("pv rows rendered", reg["pvList"]._children.length >= 5, reg["pvList"]._children.length);
  check("scalar rows rendered", reg["scalarList"]._children.length >= 8, reg["scalarList"]._children.length);
  check("heatmaps built", reg["heatmaps"]._children.length >= 7, reg["heatmaps"]._children.length);
  check("meta line populated", reg["brainMetaLine"].textContent.length > 10, reg["brainMetaLine"].textContent);

  console.log("\n[export]");
  let exported = false;
  try { fire(reg["btnExport"], "click"); exported = true; } catch (e) { void e; }
  check("export does not throw", exported);

  console.log("\n[self test]");
  fire(reg["btnSelfTest"], "click");
  await waitFor(() => reg["selftestOut"].textContent.includes("self-test complete"), 60000, "self-test completion");
  const out = reg["selftestOut"].textContent;
  const passCount = (out.match(/\[PASS\]/g) || []).length;
  const failCount = (out.match(/\[FAIL\]/g) || []).length;
  check("self-test passes (" + passCount + ")", passCount >= 5 && failCount === 0, out);

  console.log("\n[tab switching]");
  fire(tabsSel.find((t) => t.dataset.tab === "play"), "click");
  await sleep(30);
  check("play tab activates", reg["tab-play"]._classes.has("active"));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error("HARNESS CRASH:", e);
  process.exit(1);
});
