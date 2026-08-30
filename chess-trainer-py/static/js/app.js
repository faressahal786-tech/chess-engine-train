"use strict";
(function () {
  const C = window.ChessCore, E = window.Engine;

  const $ = (id) => document.getElementById(id);
  const board = $("board");
  const ctx = board.getContext("2d");

  const LOGICAL = 576, CELL = 72;
  const GLYPHS = { 1: "\u265F", 2: "\u265E", 3: "\u265D", 4: "\u265C", 5: "\u265B", 6: "\u265A" };
  const PROMO_GLYPHS = { q: "\u265B", r: "\u265C", b: "\u265D", n: "\u265E" };
  const STRENGTHS = { fast: { depth: 2, timeMs: 1200 }, balanced: { depth: 3, timeMs: 3000 }, strong: { depth: 4, timeMs: 9000 } };

  let pos = C.createStart();
  let keys = [C.posKey(pos)];
  let sans = [];
  let lastMoveStack = [];
  let legalNow = C.legalMoves(pos);
  let playerColor = C.WHITE;
  let gameOverInfo = null;
  let thinking = false;
  let epoch = 0;
  let thinkSeq = 0;
  let selected = -1;
  let lastMove = { from: -1, to: -1 };
  let hintSquares = null, hintTimer = 0;
  let viewFlipped = false;
  let soundOn = true;

  let currentBrainObj = null;
  let trainRunning = false, trainPaused = false;

  async function api(path, body) {
    const opts = body !== undefined
      ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
      : {};
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error((await r.text()) || r.statusText);
    return r.json();
  }

  function loadPrefs() {
    try {
      const p = JSON.parse(localStorage.getItem("ct.ui.v1") || "{}");
      if (typeof p.sound === "boolean") soundOn = p.sound;
      if (p.strength && STRENGTHS[p.strength]) $("selStrength").value = p.strength;
      if (p.side) $("selSide").value = p.side;
    } catch (e) { void e; }
    $("btnSound").textContent = soundOn ? "\uD83D\uDD0A" : "\uD83D\uDD07";
  }

  function savePrefs() {
    try {
      localStorage.setItem("ct.ui.v1", JSON.stringify({
        sound: soundOn,
        strength: $("selStrength").value,
        side: $("selSide").value
      }));
    } catch (e) { void e; }
  }

  function route(msg) {
    if (!msg || !msg.type) return;
    switch (msg.type) {
      case "hello":
        adoptBrain(msg.brain, false);
        updateStatsUI(msg.stats || {});
        trainRunning = !!msg.running;
        trainPaused = !!msg.paused;
        setTrainButtons();
        break;
      case "brain":
      case "loaded":
        adoptBrain(msg.brain, true);
        break;
      case "started":
        trainRunning = true; trainPaused = false;
        setTrainButtons();
        addTrainLog("training started");
        break;
      case "resumed":
        trainRunning = true; trainPaused = false;
        setTrainButtons();
        break;
      case "genDone":
        onGenDone(msg);
        break;
      case "stopped":
        trainRunning = false; trainPaused = false;
        setTrainButtons();
        adoptBrain(msg.brain, false);
        updateStatsUI(msg.stats || {});
        addTrainLog("training stopped \u00B7 brain saved server-side");
        toast("Training stopped \u2014 brain saved");
        break;
      case "error":
        addTrainLog("ERROR: " + msg.message);
        toast("Error: " + msg.message);
        break;
    }
  }

  function adoptBrain(obj, announce) {
    if (!obj || !obj.params) return;
    currentBrainObj = obj;
    const meta = obj.meta || {};
    const rec = meta.record || { w: 0, l: 0, d: 0 };
    $("brainBadge").textContent = `\uD83E\uDDE0 gen ${meta.generation || 0} \u00B7 ${meta.bornAtGame || 0} games \u00B7 ${rec.w}W/${rec.d}D/${rec.l}L`;
    refreshBrainTab();
    if (announce && meta.generation > 0) {
      addTrainLog(`new champion promoted: gen ${meta.generation}`);
    }
  }

  function strengthOpts() {
    return STRENGTHS[$("selStrength").value] || STRENGTHS.balanced;
  }

  function updateStatus() {
    const dot = $("turnDot");
    dot.style.background = pos.turn === C.WHITE ? "#f5f5f5" : "#22242a";
    dot.style.boxShadow = "0 0 0 2px var(--border)";
    let text;
    if (gameOverInfo) text = resultText(gameOverInfo);
    else if (thinking) text = "Engine is thinking\u2026";
    else if (pos.turn === playerColor) text = "Your move" + (C.inCheck(pos, pos.turn) ? " \u2014 check!" : "");
    else text = "Engine's move";
    $("statusText").textContent = text;
    $("btnHint").disabled = thinking || !!gameOverInfo;
    $("btnUndo").disabled = sans.length === 0;
  }

  function resultText(gi) {
    const youWon = (gi.result === "1-0" && playerColor === C.WHITE) || (gi.result === "0-1" && playerColor === C.BLACK);
    if (gi.result === "d") return "Draw \u2014 " + gi.reason;
    if (youWon) return "You win! (" + gi.result + ", " + gi.reason + ")";
    return "Engine wins (" + gi.result + ", " + gi.reason + ")";
  }

  function showBanner(text) {
    $("banner").hidden = false;
    $("bannerText").textContent = text;
  }

  function hideBanner() { $("banner").hidden = true; }

  function endGame(st) {
    gameOverInfo = { result: st.result, reason: st.reason };
    showBanner(resultText(gameOverInfo));
    playEndSound(gameOverInfo);
    updateStatus();
  }

  function squareViewRC(sq) {
    const file = sq & 7, rank = sq >> 4;
    const vcol = viewFlipped ? 7 - file : file;
    const vrow = viewFlipped ? rank : 7 - rank;
    return { vcol, vrow };
  }

  function xyToSquare(px, py) {
    const vcol = Math.floor(px / CELL), vrow = Math.floor(py / CELL);
    if (vcol < 0 || vcol > 7 || vrow < 0 || vrow > 7) return -1;
    const file = viewFlipped ? 7 - vcol : vcol;
    const rank = viewFlipped ? vrow : 7 - vrow;
    return rank * 16 + file;
  }

  function fillSquareColor(sq, color) {
    const { vcol, vrow } = squareViewRC(sq);
    ctx.fillStyle = color;
    ctx.fillRect(vcol * CELL, vrow * CELL, CELL, CELL);
  }

  function drawPieceAt(sq, pieceCode) {
    const { vcol, vrow } = squareViewRC(sq);
    const x = vcol * CELL + CELL / 2;
    const y = vrow * CELL + CELL / 2 + 2;
    const white = C.colorOf(pieceCode) === C.WHITE;
    ctx.font = Math.round(CELL * 0.64) + 'px "Segoe UI Symbol","Apple Symbols","Noto Sans Symbols 2",sans-serif';
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    if (white) {
      ctx.lineWidth = 2.6;
      ctx.strokeStyle = "#2b2b2b";
      ctx.strokeText(GLYPHS[C.typeOf(pieceCode)], x, y);
      ctx.fillStyle = "#fdfdfd";
      ctx.fillText(GLYPHS[C.typeOf(pieceCode)], x, y);
    } else {
      ctx.lineWidth = 1.6;
      ctx.strokeStyle = "rgba(240,240,240,.75)";
      ctx.strokeText(GLYPHS[C.typeOf(pieceCode)], x, y);
      ctx.fillStyle = "#17181c";
      ctx.fillText(GLYPHS[C.typeOf(pieceCode)], x, y);
    }
  }

  function render() {
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    const dpr = window.devicePixelRatio || 1;
    if (board.width !== LOGICAL * dpr) { board.width = LOGICAL * dpr; board.height = LOGICAL * dpr; }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    for (let vr = 0; vr < 8; vr++) {
      for (let vc = 0; vc < 8; vc++) {
        const file = viewFlipped ? 7 - vc : vc;
        const rank = viewFlipped ? vr : 7 - vr;
        const light = ((file + rank) & 1) === 1;
        ctx.fillStyle = light ? "#ebecd0" : "#739552";
        ctx.fillRect(vc * CELL, vr * CELL, CELL, CELL);
      }
    }

    if (lastMove.from >= 0) {
      fillSquareColor(lastMove.from, "rgba(255,213,80,.40)");
      fillSquareColor(lastMove.to, "rgba(255,213,80,.40)");
    }

    const checkSq = C.inCheck(pos, pos.turn) ? pos.kings[pos.turn] : -1;
    if (checkSq >= 0) {
      const { vcol, vrow } = squareViewRC(checkSq);
      const cx = vcol * CELL + CELL / 2, cy = vrow * CELL + CELL / 2;
      const grad = ctx.createRadialGradient(cx, cy, 4, cx, cy, CELL * 0.62);
      grad.addColorStop(0, "rgba(255,60,50,.65)");
      grad.addColorStop(1, "rgba(255,60,50,0)");
      ctx.fillStyle = grad;
      ctx.fillRect(vcol * CELL, vrow * CELL, CELL, CELL);
    }

    for (let vr = 0; vr < 8; vr++) {
      for (let vc = 0; vc < 8; vc++) {
        const file = viewFlipped ? 7 - vc : vc;
        const rank = viewFlipped ? vr : 7 - vr;
        const light = ((file + rank) & 1) === 1;
        ctx.fillStyle = light ? "#6f8f4c" : "#dfe2cf";
        ctx.font = "600 11px system-ui,sans-serif";
        ctx.textBaseline = "middle";
        ctx.textAlign = "center";
        if (vr === 7) ctx.fillText(String.fromCharCode(97 + file), vc * CELL + CELL - 9, vr * CELL + CELL - 10);
        if (vc === 0) ctx.fillText(String(rank + 1), vc * CELL + 8, vr * CELL + 10);
      }
    }

    for (let sq = 0; sq < 128; sq++) {
      if (sq & 0x88) { sq += 7; continue; }
      const p = pos.board[sq];
      if (p) drawPieceAt(sq, p);
    }

    if (selected >= 0) {
      fillSquareColor(selected, "rgba(250,220,110,.30)");
      const { vcol, vrow } = squareViewRC(selected);
      ctx.strokeStyle = "#f7d774";
      ctx.lineWidth = 3;
      ctx.strokeRect(vcol * CELL + 2, vrow * CELL + 2, CELL - 4, CELL - 4);
      for (const m of legalNow) {
        if (C.mFrom(m) !== selected) continue;
        const to = C.mTo(m);
        const tv = squareViewRC(to);
        const cx = tv.vcol * CELL + CELL / 2, cy = tv.vrow * CELL + CELL / 2;
        const isCapture = C.mCapt(m) !== 0 || (C.mFlags(m) & C.FLAG_EP) !== 0 || pos.board[to] !== 0;
        ctx.fillStyle = "rgba(20,30,15,.32)";
        if (isCapture) {
          ctx.strokeStyle = "rgba(20,30,15,.38)";
          ctx.lineWidth = 5;
          ctx.beginPath();
          ctx.arc(cx, cy, CELL * 0.44, 0, Math.PI * 2);
          ctx.stroke();
        } else {
          ctx.beginPath();
          ctx.arc(cx, cy, CELL * 0.14, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }

    if (hintSquares) {
      fillSquareColor(hintSquares.from, "rgba(70,205,125,.45)");
      fillSquareColor(hintSquares.to, "rgba(70,205,125,.55)");
    }
  }

  function renderMoveList() {
    const ol = $("moveList");
    ol.textContent = "";
    if (!sans.length) {
      const li = document.createElement("li");
      li.className = "empty-moves";
      li.textContent = "no moves yet";
      ol.appendChild(li);
      return;
    }
    for (let i = 0; i < sans.length; i += 2) {
      const li = document.createElement("li");
      const w = document.createElement("span");
      w.className = "mv-white" + (i === sans.length - 1 ? " mv-last" : "");
      w.textContent = sans[i];
      li.appendChild(w);
      if (sans[i + 1] !== undefined) {
        const b = document.createElement("span");
        b.className = "mv-black" + (i + 1 === sans.length - 1 ? " mv-last" : "");
        b.style.marginLeft = "8px";
        b.textContent = sans[i + 1];
        li.appendChild(b);
      }
      ol.appendChild(li);
    }
    ol.scrollTop = ol.scrollHeight;
  }

  let actx = null;
  function initAudioOnce() {
    if (actx) return;
    try { actx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { void e; }
  }
  function blip(freq, dur, type, gain, delay) {
    if (!soundOn || !actx) return;
    try {
      const t = actx.currentTime + (delay || 0);
      const o = actx.createOscillator(), g = actx.createGain();
      o.type = type || "triangle";
      o.frequency.value = freq;
      g.gain.setValueAtTime(gain || 0.12, t);
      g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      o.connect(g); g.connect(actx.destination);
      o.start(t); o.stop(t + dur + 0.03);
    } catch (e) { void e; }
  }
  function playMoveSounds(capture, check) {
    if (capture) { blip(150, 0.12, "square", 0.13); blip(95, 0.1, "triangle", 0.09, 0.04); }
    else blip(330, 0.07, "triangle", 0.1);
    if (check) { blip(660, 0.08, "sine", 0.12); blip(880, 0.1, "sine", 0.11, 0.09); }
  }
  function playEndSound(gi) {
    if (gi.result === "d") { blip(440, 0.12, "sine", 0.1); blip(440, 0.16, "sine", 0.1, 0.16); return; }
    const youWon = (gi.result === "1-0" && playerColor === C.WHITE) || (gi.result === "0-1" && playerColor === C.BLACK);
    const seq = youWon ? [392, 494, 587, 784] : [392, 330, 262, 196];
    seq.forEach((f, i) => blip(f, 0.16, "triangle", 0.11, i * 0.14));
  }

  function clearHint() {
    hintSquares = null;
    if (hintTimer) { clearTimeout(hintTimer); hintTimer = 0; }
  }

  function applyPlayerMove(m) {
    const over = applyMove(m);
    if (!over) scheduleEngine();
  }

  function applyMove(m) {
    const sanStr = C.san(pos, m, legalNow);
    const cap = C.mCapt(m) !== 0 || (C.mFlags(m) & C.FLAG_EP) !== 0;
    C.makeMove(pos, m);
    keys.push(C.posKey(pos));
    sans.push(sanStr);
    lastMoveStack.push({ from: C.mFrom(m), to: C.mTo(m) });
    lastMove = { from: C.mFrom(m), to: C.mTo(m) };
    selected = -1;
    legalNow = C.legalMoves(pos);
    const check = C.inCheck(pos, pos.turn);
    const st = C.gameStatus(pos, keys, 3);
    render();
    renderMoveList();
    if (st.over) { playMoveSounds(cap, check); endGame(st); return true; }
    playMoveSounds(cap, check);
    updateStatus();
    return false;
  }

  async function requestThink(opts, hint) {
    const cur = epoch;
    const seq = ++thinkSeq;
    await new Promise((res) => setTimeout(res, 40));
    if (cur !== epoch) return;
    try {
      const res = await api("/api/think", { fen: C.toFen(pos), opts, hint, seq });
      if (cur !== epoch || seq !== thinkSeq) return;
      handleThinkResult(res, cur, hint);
    } catch (err) {
      if (cur !== epoch) return;
      thinking = false;
      updateStatus();
      toast("Engine error: " + err.message);
    }
  }

  function scheduleEngine() {
    if (gameOverInfo) return;
    thinking = true;
    updateStatus();
    const opts = strengthOpts();
    requestThink({ depth: opts.depth, time_ms: opts.timeMs, root_noise: 8, pick_margin: 16 }, false)
      .catch(() => {});
  }

  function handleThinkResult(res, cur, hint) {
    if (res.epoch !== undefined && res.epoch !== cur) return;
    if (!res.ok) { thinking = false; updateStatus(); return; }
    if (hint) {
      clearHint();
      hintSquares = { from: res.from, to: res.to };
      render();
      hintTimer = setTimeout(() => { hintSquares = null; render(); }, 2600);
      updateEvalFromThink(res, pos.turn === C.WHITE);
      return;
    }
    if (!thinking) return;
    thinking = false;
    if (gameOverInfo) { updateStatus(); return; }
    let mv = null;
    for (const m of legalNow) {
      if (C.mFrom(m) === res.from && C.mTo(m) === res.to && (C.mPromo(m) || 0) === (res.promo || 0)) { mv = m; break; }
    }
    if (!mv && legalNow.length) mv = legalNow[0];
    if (!mv) { updateStatus(); return; }
    const moverWhite = pos.turn === C.WHITE;
    applyMove(mv);
    updateEvalFromThink(res, moverWhite);
  }

  function updateEvalFromThink(res, moverWhite) {
    const scoreWhite = moverWhite ? res.score : -res.score;
    const pct = 50 + 50 * Math.tanh(scoreWhite / 600);
    $("evalfill").style.width = Math.max(4, Math.min(96, pct)) + "%";
    let txt;
    if (Math.abs(scoreWhite) > E.MATE - 2000) {
      const plies = E.MATE - Math.abs(scoreWhite);
      txt = (scoreWhite > 0 ? "+M" : "-M") + Math.max(1, Math.ceil(plies / 2));
    } else {
      const v = scoreWhite / 100;
      txt = (v > 0 ? "+" : "") + v.toFixed(2);
    }
    $("evaltext").textContent = txt;
    const pv = (res.pv_san || []).slice(0, 6).join(" ");
    $("engineInfo").textContent =
      `depth ${res.depth} \u00B7 ${(res.nodes / 1000).toFixed(1)}k nodes \u00B7 ${((res.time_ms || 0) / 1000).toFixed(1)}s` +
      (pv ? ` \u00B7 ${pv}` : "");
  }

  let promoResolve = null;
  function openPromo(matches) {
    promoResolve = null;
    const box = $("promoButtons");
    box.textContent = "";
    const order = ["q", "r", "b", "n"];
    const wanted = matches.map((m) => C.mPromo(m));
    const cls = playerColor === C.WHITE ? "white" : "black";
    for (const ch of order) {
      const typeNum = { q: C.QUEEN, r: C.ROOK, b: C.BISHOP, n: C.KNIGHT }[ch];
      if (wanted.indexOf(typeNum) === -1) continue;
      const btn = document.createElement("button");
      btn.className = "promo-btn " + cls;
      btn.textContent = PROMO_GLYPHS[ch];
      btn.addEventListener("click", () => closePromo(typeNum));
      box.appendChild(btn);
    }
    $("promoModal").hidden = false;
    promoResolve = (typeNum) => {
      $("promoModal").hidden = true;
      selected = -1;
      if (typeNum == null) { render(); return; }
      const m = matches.find((mm) => C.mPromo(mm) === typeNum);
      if (m) applyPlayerMove(m);
    };
  }

  function closePromo(typeNum) {
    if (promoResolve) { const f = promoResolve; promoResolve = null; f(typeNum); }
  }

  function onClickBoard(e) {
    initAudioOnce();
    if (!$("promoModal").hidden || thinking || gameOverInfo) return;
    if (pos.turn !== playerColor) return;
    const rect = board.getBoundingClientRect();
    const scale = LOGICAL / rect.width;
    const px = (e.clientX - rect.left) * scale;
    const py = (e.clientY - rect.top) * scale;
    const sq = xyToSquare(px, py);
    if (sq < 0) { selected = -1; render(); return; }
    if (selected >= 0) {
      const matches = legalNow.filter((m) => C.mFrom(m) === selected && C.mTo(m) === sq);
      if (matches.length === 1) { applyPlayerMove(matches[0]); return; }
      if (matches.length > 1) { openPromo(matches); return; }
      const p = pos.board[sq];
      if (p && C.colorOf(p) === playerColor && sq !== selected) { selected = sq; clearHint(); render(); }
      else { selected = -1; render(); }
    } else {
      const p = pos.board[sq];
      if (p && C.colorOf(p) === playerColor) { selected = sq; clearHint(); render(); }
    }
  }

  function newGame(sideChoice) {
    epoch++;
    thinking = false;
    gameOverInfo = null;
    hideBanner();
    clearHint();
    selected = -1;
    pos = C.createStart();
    keys = [C.posKey(pos)];
    sans = [];
    lastMoveStack = [];
    lastMove = { from: -1, to: -1 };
    playerColor = sideChoice === "random"
      ? (Math.random() < 0.5 ? C.WHITE : C.BLACK)
      : (sideChoice === "black" ? C.BLACK : C.WHITE);
    viewFlipped = playerColor === C.BLACK;
    legalNow = C.legalMoves(pos);
    $("evalfill").style.width = "50%";
    $("evaltext").textContent = "0.00";
    $("engineInfo").textContent = "\u00A0";
    render();
    renderMoveList();
    updateStatus();
    if (pos.turn !== playerColor) scheduleEngine();
  }

  function undo() {
    if (!sans.length) return;
    epoch++;
    thinking = false;
    gameOverInfo = null;
    hideBanner();
    clearHint();
    do {
      C.unmakeMove(pos);
      sans.pop();
      keys.pop();
      lastMoveStack.pop();
    } while (sans.length > 0 && pos.turn !== playerColor);
    lastMove = lastMoveStack.length
      ? { from: lastMoveStack[lastMoveStack.length - 1].from, to: lastMoveStack[lastMoveStack.length - 1].to }
      : { from: -1, to: -1 };
    selected = -1;
    legalNow = C.legalMoves(pos);
    render();
    renderMoveList();
    updateStatus();
    if (!gameOverInfo && pos.turn !== playerColor) scheduleEngine();
  }

  function toast(text) {
    const t = $("toast");
    t.textContent = text;
    t.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { t.hidden = true; }, 2800);
  }

  function fmtTime() {
    const d = new Date();
    return [d.getHours(), d.getMinutes(), d.getSeconds()].map((n) => String(n).padStart(2, "0")).join(":");
  }

  function addTrainLog(text) {
    const el = $("trainLog");
    const line = "[" + fmtTime() + "] " + text;
    el.textContent += (el.textContent ? "\n" : "") + line;
    const lines = el.textContent.split("\n");
    if (lines.length > 500) el.textContent = lines.slice(-500).join("\n");
    el.scrollTop = el.scrollHeight;
  }

  function setTrainButtons() {
    $("btnTrainStart").disabled = trainRunning;
    $("btnTrainPause").disabled = !trainRunning;
    $("btnTrainPause").textContent = trainPaused ? "\u25B6 Resume" : "\u23F8 Pause";
    $("btnTrainStop").disabled = !trainRunning;
  }

  function updateStatsUI(s) {
    $("stGen").textContent = s.gen || 0;
    $("stGames").textContent = s.games || 0;
    $("stImprove").textContent = s.improvements || 0;
    $("stRecord").textContent = `${s.w || 0}/${s.l || 0}/${s.d || 0}`;
    $("stAvgPlies").textContent = s.games ? Math.round((s.total_plies !== undefined ? s.total_plies : s.totalPlies || 0) / s.games) : "\u2013";
    const lg = s.last_games !== undefined ? s.last_games : s.lastGames;
    const lc = s.last_ch_pts !== undefined ? s.last_ch_pts : s.lastChPts;
    $("stLastMatch").textContent = lg ? `${lc}/${lg}` : "\u2013";
  }

  function onGenDone(msg) {
    updateStatsUI(msg.stats || {});
    const star = msg.improved ? "  \u2605 PROMOTED" : "";
    addTrainLog(
      `gen ${msg.stats.gen} \u00B7 challenger ${msg.ch_pts}/${msg.games} pts ` +
      `(${msg.ch_w}W ${msg.ch_l}L ${msg.draws}D) \u00B7 avg ${msg.avg_plies} plies${star}`
    );
  }

  const SCALAR_META = [
    ["bishopPair", "bishop pair", 0, 90],
    ["doubled", "doubled pawn pen", 0, 45],
    ["isolated", "isolated pawn pen", 0, 45],
    ["passed", "passed pawn bonus", 0, 90],
    ["rookOpen", "rook open file", 0, 70],
    ["rookHalf", "rook semi-open", 0, 40],
    ["kingShield", "king shield", -10, 35],
    ["tempo", "tempo", -8, 30]
  ];
  const VAL_META = [["p", "pawn"], ["n", "knight"], ["b", "bishop"], ["r", "rook"], ["q", "queen"]];

  function pvRow(name, value, lo, hi, unit) {
    const row = document.createElement("div");
    row.className = "pv-row";
    const nm = document.createElement("span"); nm.className = "pv-name"; nm.textContent = name;
    const bar = document.createElement("div"); bar.className = "pv-bar";
    const fill = document.createElement("div"); fill.className = "pv-fill";
    const frac = Math.max(0, Math.min(1, (value - lo) / (hi - lo)));
    fill.style.width = (frac * 100).toFixed(1) + "%";
    bar.appendChild(fill);
    const val = document.createElement("span"); val.className = "pv-val"; val.textContent = Math.round(value) + (unit || "");
    row.appendChild(nm); row.appendChild(bar); row.appendChild(val);
    return row;
  }

  const HM_DEFS = [["p", "pawn"], ["n", "knight"], ["b", "bishop"], ["r", "rook"], ["q", "queen"], ["kmg", "king mid"], ["keg", "king end"]];
  const hmCanvases = {};

  function buildHeatmaps() {
    const grid = $("heatmaps");
    grid.textContent = "";
    for (const [key, label] of HM_DEFS) {
      const item = document.createElement("div");
      item.className = "hm-item";
      const cv = document.createElement("canvas");
      cv.width = 8; cv.height = 8;
      item.appendChild(cv);
      const lbl = document.createElement("span");
      lbl.className = "hm-lbl";
      lbl.textContent = label;
      item.appendChild(lbl);
      grid.appendChild(item);
      hmCanvases[key] = cv;
    }
  }

  function hmColor(v) {
    const t = Math.max(-1, Math.min(1, v / 140));
    if (t >= 0) {
      const base = [34, 43, 56], hot = [235, 87, 87];
      const c = base.map((b, i) => Math.round(b + (hot[i] - b) * t));
      return `rgb(${c[0]},${c[1]},${c[2]})`;
    }
    const base = [34, 43, 56], cool = [86, 148, 245];
    const c = base.map((b, i) => Math.round(b + (cool[i] - b) * -t));
    return `rgb(${c[0]},${c[1]},${c[2]})`;
  }

  function refreshBrainTab() {
    if (!currentBrainObj) return;
    const P = currentBrainObj.params;
    const meta = currentBrainObj.meta || {};
    const rec = meta.record || { w: 0, l: 0, d: 0 };
    $("brainMetaLine").textContent =
      meta.generation
        ? `generation ${meta.generation} \u00B7 born after ${meta.bornAtGame || 0} training games \u00B7 record vs challengers ${rec.w}W ${rec.d}D ${rec.l}L`
        : "default parameters (generation 0)";
    const pvList = $("pvList");
    pvList.textContent = "";
    for (const [k, label] of VAL_META) pvList.appendChild(pvRow(label, P.val[k], 0, 1300));
    const scList = $("scalarList");
    scList.textContent = "";
    for (const [k, label, lo, hi] of SCALAR_META) scList.appendChild(pvRow(label, P[k], lo, hi));
    for (const [key] of HM_DEFS) {
      const arr = P.pstW[key];
      const cv = hmCanvases[key];
      if (!arr || !cv) continue;
      const g = cv.getContext("2d");
      for (let vr = 0; vr < 8; vr++) {
        for (let vc = 0; vc < 8; vc++) {
          const sq = (7 - vr) * 16 + vc;
          g.fillStyle = hmColor(arr[sq]);
          g.fillRect(vc, vr, 1, 1);
        }
      }
    }
  }

  function wireEvents() {
    document.querySelectorAll(".tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
        document.querySelectorAll(".tabpage").forEach((pg) => pg.classList.remove("active"));
        $("tab-" + btn.dataset.tab).classList.add("active");
        if (btn.dataset.tab === "brain") refreshBrainTab();
      });
    });

    board.addEventListener("pointerdown", onClickBoard);
    $("promoCancel").addEventListener("click", () => closePromo(null));

    $("btnNewGame").addEventListener("click", () => { savePrefs(); newGame($("selSide").value); });
    $("btnRematch").addEventListener("click", () => newGame($("selSide").value));
    $("btnUndo").addEventListener("click", undo);
    $("btnFlip").addEventListener("click", () => { viewFlipped = !viewFlipped; render(); });
    $("btnHint").addEventListener("click", () => {
      if (thinking || gameOverInfo) return;
      const o = strengthOpts();
      requestThink({ depth: Math.min(o.depth, 3), time_ms: 2500 }, true);
    });
    $("btnSound").addEventListener("click", () => {
      soundOn = !soundOn;
      $("btnSound").textContent = soundOn ? "\uD83D\uDD0A" : "\uD83D\uDD07";
      savePrefs();
      if (soundOn) { initAudioOnce(); blip(520, 0.06); }
    });

    $("btnTrainStart").addEventListener("click", () => {
      api("/api/train/start", {
        opts: {
          depth: parseInt($("selTrainDepth").value, 10),
          games_per_gen: parseInt($("inpGamesPerGen").value, 10),
          max_plies: parseInt($("inpMaxPlies").value, 10),
          open_plies: parseInt($("inpOpenPlies").value, 10),
          strength: parseFloat($("rngStrength").value)
        }
      }).catch((e) => toast("Start failed: " + e.message));
    });
    $("btnTrainPause").addEventListener("click", () => {
      api("/api/train/" + (trainPaused ? "resume" : "pause")).catch(() => {});
      if (!trainPaused) { trainPaused = true; addTrainLog("paused"); }
      setTrainButtons();
    });
    $("btnTrainStop").addEventListener("click", () => {
      api("/api/train/stop").catch((e) => toast("Stop failed: " + e.message));
    });
    $("rngStrength").addEventListener("input", () => { $("lblStrength").textContent = parseFloat($("rngStrength").value) + "\u00D7"; });

    $("btnExport").addEventListener("click", async () => {
      try {
        const data = await api("/api/brain");
        const blob = new Blob([JSON.stringify(data.brain, null, 1)], { type: "application/json" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `chess-brain-gen${data.brain.meta.generation || 0}.json`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      } catch (e) { toast("Export failed: " + e.message); }
    });
    $("btnImport").addEventListener("click", () => $("importFile").click());
    $("importFile").addEventListener("change", (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        let obj = null;
        try { obj = JSON.parse(String(reader.result)); } catch (err) { toast("Invalid JSON"); return; }
        api("/api/brain/load", { brain: obj })
          .then(() => toast("Brain imported"))
          .catch((err) => toast("Invalid brain: " + err.message));
      };
      reader.readAsText(file);
      e.target.value = "";
    });
    $("btnReset").addEventListener("click", () => {
      if (!confirm("Reset the brain to default parameters? Training progress will be lost.")) return;
      api("/api/brain/reset").then(() => toast("Brain reset")).catch((e) => toast("Reset failed: " + e.message));
    });
    $("btnSelfTest").addEventListener("click", async () => {
      const out = $("selftestOut");
      out.hidden = false;
      out.textContent = "running\u2026";
      $("btnSelfTest").disabled = true;
      try {
        const res = await api("/api/selftest");
        out.textContent = (res.lines || []).join("\n");
      } catch (e) {
        out.textContent = "self-test failed: " + e.message;
      }
      $("btnSelfTest").disabled = false;
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        if (!$("promoModal").hidden) closePromo(null);
        else { selected = -1; render(); }
      }
    });
  }

  function connectStream() {
    const es = new EventSource("/api/train/stream");
    es.onmessage = (e) => {
      try { route(JSON.parse(e.data)); } catch (err) { void err; }
    };
    es.onerror = () => {
      addTrainLog("connection lost — retrying…");
    };
  }

  function boot() {
    loadPrefs();
    buildHeatmaps();
    wireEvents();
    connectStream();
    newGame($("selSide").value);
    setTrainButtons();
    addTrainLog("ready — press Start training to begin self-play evolution");
  }

  boot();
})();
