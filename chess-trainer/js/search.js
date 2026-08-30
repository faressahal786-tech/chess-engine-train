"use strict";
(function (root) {
  const C = root.ChessCore;
  const { PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING, WHITE, BLACK } = C;

  const MATE = 1000000;
  const INF = 10000000;
  const PIECE_VAL = [0, 100, 320, 330, 500, 900, 20000];

  const PST_P = [
    0, 0, 0, 0, 0, 0, 0, 0,
    50, 50, 50, 50, 50, 50, 50, 50,
    10, 10, 20, 30, 30, 20, 10, 10,
    5, 5, 10, 25, 25, 10, 5, 5,
    0, 0, 0, 20, 20, 0, 0, 0,
    5, -5, -10, 0, 0, -10, -5, 5,
    5, 10, 10, -20, -20, 10, 10, 5,
    0, 0, 0, 0, 0, 0, 0, 0
  ];
  const PST_N = [
    -50, -40, -30, -30, -30, -30, -40, -50,
    -40, -20, 0, 0, 0, 0, -20, -40,
    -30, 0, 10, 15, 15, 10, 0, -30,
    -30, 5, 15, 20, 20, 15, 5, -30,
    -30, 0, 15, 20, 20, 15, 0, -30,
    -30, 5, 10, 15, 15, 10, 5, -30,
    -40, -20, 0, 5, 5, 0, -20, -40,
    -50, -40, -30, -30, -30, -30, -40, -50
  ];
  const PST_B = [
    -20, -10, -10, -10, -10, -10, -10, -20,
    -10, 0, 0, 0, 0, 0, 0, -10,
    -10, 0, 5, 10, 10, 5, 0, -10,
    -10, 5, 5, 10, 10, 5, 5, -10,
    -10, 0, 10, 10, 10, 10, 0, -10,
    -10, 10, 10, 10, 10, 10, 10, -10,
    -10, 5, 0, 0, 0, 0, 5, -10,
    -20, -10, -10, -10, -10, -10, -10, -20
  ];
  const PST_R = [
    0, 0, 0, 0, 0, 0, 0, 0,
    5, 10, 10, 10, 10, 10, 10, 5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    0, 0, 0, 5, 5, 0, 0, 0
  ];
  const PST_Q = [
    -20, -10, -10, -5, -5, -10, -10, -20,
    -10, 0, 0, 0, 0, 0, 0, -10,
    -10, 0, 5, 5, 5, 5, 0, -10,
    -5, 0, 5, 5, 5, 5, 0, -5,
    0, 0, 5, 5, 5, 5, 0, -5,
    -10, 5, 5, 5, 5, 5, 0, -10,
    -10, 0, 5, 0, 0, 0, 0, -10,
    -20, -10, -10, -5, -5, -10, -10, -20
  ];
  const PST_K_MG = [
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -20, -30, -30, -40, -40, -30, -30, -20,
    -10, -20, -20, -20, -20, -20, -20, -10,
    20, 20, 0, 0, 0, 0, 20, 20,
    20, 30, 10, 0, 0, 10, 30, 20
  ];
  const PST_K_EG = [
    -50, -40, -30, -20, -20, -30, -40, -50,
    -30, -20, -10, 0, 0, -10, -20, -30,
    -30, -10, 20, 30, 30, 20, -10, -30,
    -30, -10, 30, 40, 40, 30, -10, -30,
    -30, -10, 30, 40, 40, 30, -10, -30,
    -30, -10, 20, 30, 30, 20, -10, -30,
    -30, -30, 0, 0, 0, 0, -30, -30,
    -50, -30, -30, -30, -30, -30, -30, -50
  ];

  const BASE_TABLES = { p: PST_P, n: PST_N, b: PST_B, r: PST_R, q: PST_Q };

  function defaultParams() {
    const pstW = {}, pstB = {};
    for (const t of ["p", "n", "b", "r", "q"]) pstW[t] = new Float64Array(128);
    pstW.kmg = new Float64Array(128);
    pstW.keg = new Float64Array(128);
    for (const t of ["p", "n", "b", "r", "q"]) pstB[t] = new Float64Array(128);
    pstB.kmg = new Float64Array(128);
    pstB.keg = new Float64Array(128);
    for (let sq = 0; sq < 128; sq++) {
      if (sq & 0x88) continue;
      const f = sq & 7, r = sq >> 4;
      const idxW = (7 - r) * 8 + f;
      const idxB = r * 8 + f;
      for (const t of ["p", "n", "b", "r", "q"]) {
        pstW[t][sq] = BASE_TABLES[t][idxW];
        pstB[t][sq] = BASE_TABLES[t][idxB];
      }
      pstW.kmg[sq] = PST_K_MG[idxW];
      pstW.keg[sq] = PST_K_EG[idxW];
      pstB.kmg[sq] = PST_K_MG[idxB];
      pstB.keg[sq] = PST_K_EG[idxB];
    }
    return {
      val: { p: 100, n: 320, b: 330, r: 500, q: 900 },
      pstW, pstB,
      bishopPair: 30,
      doubled: 12,
      isolated: 16,
      passed: 24,
      rookOpen: 22,
      rookHalf: 11,
      kingShield: 9,
      tempo: 10
    };
  }

  function paramsFromPlain(o) {
    const d = defaultParams();
    if (!o || !o.val || !o.pstW || !o.pstB) return d;
    for (const k of ["p", "n", "b", "r", "q"]) {
      if (typeof o.val[k] === "number" && isFinite(o.val[k])) d.val[k] = o.val[k];
      for (const side of ["pstW", "pstB"]) {
        const src = o[side] && o[side][k];
        if (src && src.length >= 128) for (let i = 0; i < 128; i++) if (isFinite(src[i])) d[side][k][i] = src[i];
      }
    }
    for (const side of ["pstW", "pstB"]) {
      for (const k of ["kmg", "keg"]) {
        const src = o[side] && o[side][k];
        if (src && src.length >= 128) for (let i = 0; i < 128; i++) if (isFinite(src[i])) d[side][k][i] = src[i];
      }
    }
    for (const k of ["bishopPair", "doubled", "isolated", "passed", "rookOpen", "rookHalf", "kingShield", "tempo"]) {
      if (typeof o[k] === "number" && isFinite(o[k])) d[k] = o[k];
    }
    return d;
  }

  function paramsToPlain(p) {
    const pstW = {}, pstB = {};
    for (const k of ["p", "n", "b", "r", "q", "kmg", "keg"]) {
      pstW[k] = Array.from(p.pstW[k]);
      pstB[k] = Array.from(p.pstB[k]);
    }
    return {
      val: Object.assign({}, p.val), pstW, pstB,
      bishopPair: p.bishopPair, doubled: p.doubled, isolated: p.isolated,
      passed: p.passed, rookOpen: p.rookOpen, rookHalf: p.rookHalf,
      kingShield: p.kingShield, tempo: p.tempo
    };
  }

  const PASSED_F = [0, 0.2, 0.35, 0.55, 0.8, 1.15, 1.6, 0];

  function evaluate(pos, P) {
    let mg = 0, eg = 0, phase = 0;
    let wBishops = 0, bBishops = 0;
    let wkSq = pos.kings[WHITE], bkSq = pos.kings[BLACK];
    const wpFile = [-1, -1, -1, -1, -1, -1, -1, -1], bpFile = [8, 8, 8, 8, 8, 8, 8, 8];
    const wpCount = [0, 0, 0, 0, 0, 0, 0, 0], bpCount = [0, 0, 0, 0, 0, 0, 0, 0];
    const pieces = pos.pieces;

    for (let i = 0; i < pieces.length; i++) {
      const p = pieces[i].p, sq = pieces[i].sq;
      const t = p & 7, c = p >> 3;
      const f = sq & 7, r = sq >> 4;
      if (t === PAWN) {
        if (c === WHITE) {
          mg += P.val.p + P.pstW.p[sq]; eg += P.val.p + P.pstW.p[sq];
          wpCount[f]++;
          if (r > wpFile[f]) wpFile[f] = r;
        } else {
          mg -= P.val.p + P.pstB.p[sq]; eg -= P.val.p + P.pstB.p[sq];
          bpCount[f]++;
          if (r < bpFile[f]) bpFile[f] = r;
        }
      } else if (t === KNIGHT) {
        const s = P.val.n + (c === WHITE ? P.pstW.n[sq] : P.pstB.n[sq]);
        if (c === WHITE) { mg += s; eg += s; } else { mg -= s; eg -= s; }
        phase += 1;
      } else if (t === BISHOP) {
        const s = P.val.b + (c === WHITE ? P.pstW.b[sq] : P.pstB.b[sq]);
        if (c === WHITE) { mg += s; eg += s; wBishops++; } else { mg -= s; eg -= s; bBishops++; }
        phase += 1;
      } else if (t === ROOK) {
        const s = P.val.r + (c === WHITE ? P.pstW.r[sq] : P.pstB.r[sq]);
        if (c === WHITE) { mg += s; eg += s; } else { mg -= s; eg -= s; }
        phase += 2;
      } else if (t === QUEEN) {
        const s = P.val.q + (c === WHITE ? P.pstW.q[sq] : P.pstB.q[sq]);
        if (c === WHITE) { mg += s; eg += s; } else { mg -= s; eg -= s; }
        phase += 4;
      } else {
        mg += c === WHITE ? P.pstW.kmg[sq] : -P.pstB.kmg[sq];
        eg += c === WHITE ? P.pstW.keg[sq] : -P.pstB.keg[sq];
      }
    }

    for (let f = 0; f < 8; f++) {
      if (wpCount[f] > 1) { mg -= P.doubled * (wpCount[f] - 1); eg -= P.doubled * (wpCount[f] - 1); }
      if (bpCount[f] > 1) { mg += P.doubled * (bpCount[f] - 1); eg += P.doubled * (bpCount[f] - 1); }
      const wLeft = f > 0 ? wpCount[f - 1] : 0, wRight = f < 7 ? wpCount[f + 1] : 0;
      const bLeft = f > 0 ? bpCount[f - 1] : 0, bRight = f < 7 ? bpCount[f + 1] : 0;
      if (wpCount[f] > 0 && wLeft + wRight === 0) { mg -= P.isolated * wpCount[f]; eg -= P.isolated * wpCount[f]; }
      if (bpCount[f] > 0 && bLeft + bRight === 0) { mg += P.isolated * bpCount[f]; eg += P.isolated * bpCount[f]; }
      if (wpCount[f] > 0) {
        const aheadL = f > 0 ? bpFile[f - 1] : 8, aheadR = f < 7 ? bpFile[f + 1] : 8;
        if (bpFile[f] > wpFile[f] && aheadL > wpFile[f] && aheadR > wpFile[f]) {
          const bon = Math.round(P.passed * PASSED_F[wpFile[f]]);
          mg += bon; eg += Math.round(bon * 1.5);
        }
      }
      if (bpCount[f] > 0) {
        const aheadL = f > 0 ? wpFile[f - 1] : -1, aheadR = f < 7 ? wpFile[f + 1] : -1;
        if (wpFile[f] < bpFile[f] && aheadL < bpFile[f] && aheadR < bpFile[f]) {
          const bon = Math.round(P.passed * PASSED_F[7 - bpFile[f]]);
          mg -= bon; eg -= Math.round(bon * 1.5);
        }
      }
    }

    if (wBishops >= 2) { mg += P.bishopPair; eg += P.bishopPair; }
    if (bBishops >= 2) { mg -= P.bishopPair; eg -= P.bishopPair; }

    for (let i = 0; i < pieces.length; i++) {
      const p = pieces[i].p;
      if ((p & 7) !== ROOK) continue;
      const sq = pieces[i].sq;
      const f = sq & 7;
      if ((p >> 3) === WHITE) {
        if (wpCount[f] === 0) { mg += bpCount[f] === 0 ? P.rookOpen : P.rookHalf; eg += bpCount[f] === 0 ? P.rookOpen : P.rookHalf; }
      } else {
        if (bpCount[f] === 0) { mg -= wpCount[f] === 0 ? P.rookOpen : P.rookHalf; eg -= wpCount[f] === 0 ? P.rookOpen : P.rookHalf; }
      }
    }

    const b = pos.board;
    const wShield = countShield(b, wkSq, WHITE);
    const bShield = countShield(b, bkSq, BLACK);
    mg += wShield * P.kingShield - bShield * P.kingShield;

    if (phase > 24) phase = 24;
    const score = (mg * phase + eg * (24 - phase)) / 24 + P.tempo;
    return pos.turn === WHITE ? score : -score;
  }

  function countShield(b, kSq, color) {
    const f = kSq & 7, r = kSq >> 4;
    let shield = 0;
    const ownPawn = color === WHITE ? 1 : 9;
    for (let df = -1; df <= 1; df++) {
      const nf = f + df;
      if (nf < 0 || nf > 7) continue;
      const rr = color === WHITE ? r + 1 : r - 1;
      const target1 = (rr << 4) | nf;
      if (!(target1 & 0x88) && b[target1] === ownPawn) shield++;
      else {
        const target2 = ((color === WHITE ? rr + 1 : rr - 1) << 4) | nf;
        if (!(target2 & 0x88) && b[target2] === ownPawn) shield += 0.5;
      }
    }
    return shield;
  }

  const MVV_LVA_BONUS = 1000000;
  const TTM_BONUS = 2200000;

  const TT_BITS = 20, TT_SIZE = 1 << TT_BITS, TT_MASK = TT_SIZE - 1;
  const ttKeyLo = new Int32Array(TT_SIZE);
  const ttKeyHi = new Int32Array(TT_SIZE);
  const ttMove = new Int32Array(TT_SIZE);
  const ttScore = new Int32Array(TT_SIZE);
  const ttDepth = new Int8Array(TT_SIZE);
  const ttFlag = new Int8Array(TT_SIZE);
  const ttGen = new Int32Array(TT_SIZE);
  let ttEpoch = 1;
  const TT_EXACT = 1, TT_LOWER = 2, TT_UPPER = 3;
  const MATE_BOUND = MATE - 2000;

  function moveScore(m, killers, historyTable, ply, ttMoveCand) {
    if (ttMoveCand && m === ttMoveCand) return TTM_BONUS;
    const cap = C.mCapt(m), promo = C.mPromo(m), fl = C.mFlags(m);
    if (cap || promo) {
      let s = MVV_LVA_BONUS;
      if (cap) s += cap * 16 - (C.mPiece(m) & 7);
      if (fl & C.FLAG_EP) s += 15;
      if (promo) s += promo * 10;
      return s;
    }
    if (killers) {
      const k1 = killers[ply * 2], k2 = killers[ply * 2 + 1];
      if (m === k1) return 900000;
      if (m === k2) return 800000;
      const h = historyTable[C.mPiece(m) * 128 + C.mTo(m)];
      if (h > 0) return h;
    }
    return 0;
  }

  function sortMoves(moves, killers, historyTable, ply, ttMoveCand) {
    const scored = moves.map((m) => ({ m, s: moveScore(m, killers, historyTable, ply, ttMoveCand) }));
    scored.sort((a, b) => b.s - a.s);
    return scored.map((e) => e.m);
  }

  function think(pos, brain, opts) {
    opts = opts || {};
    const maxDepth = opts.maxDepth || 3;
    const timeMs = opts.timeMs || 0;
    const rng = opts.rng || null;
    const rootNoise = opts.rootNoise || 0;
    const pickMargin = opts.pickMargin || 0;
    const seenKeys = opts.seenKeys || null;

    const P = brain;
    const deadline = timeMs > 0 ? Date.now() + timeMs : Infinity;
    let nodes = 0;
    let aborted = false;
    const killers = new Int32Array(128);
    const historyTable = new Int32Array(16 * 128);

    const rootMoves = C.legalMoves(pos);
    if (rootMoves.length === 0) return null;

    let bestMove = rootMoves[0], bestScore = 0, completedDepth = 0, bestPv = [];

    const evalAt = () => evaluate(pos, P);

    function qsearch(alpha, beta, ply) {
      nodes++;
      if ((nodes & 2047) === 0 && Date.now() > deadline) aborted = true;
      const stand = evaluate(pos, P);
      if (stand >= beta) return stand;
      if (stand > alpha) alpha = stand;
      if (ply > 24) return alpha;
      const caps = sortMoves(C.generateMoves(pos, true), null, null, 0);
      for (let i = 0; i < caps.length; i++) {
        const m = caps[i];
        const cap = C.mCapt(m);
        const promo = C.mPromo(m);
        if (!promo && cap) {
          const v = PIECE_VAL[cap & 7];
          if (stand + v + 150 < alpha) continue;
        }
        C.makeMove(pos, m);
        if (C.inCheck(pos, pos.turn ^ 1)) { C.unmakeMove(pos); continue; }
        const v = -qsearch(-beta, -alpha, ply + 1);
        C.unmakeMove(pos);
        if (aborted) return alpha;
        if (v >= beta) return v;
        if (v > alpha) alpha = v;
      }
      return alpha;
    }

    const t0 = Date.now();

    function negamax(depth, alpha, beta, ply, allowNull) {
      nodes++;
      if ((nodes & 2047) === 0 && Date.now() > deadline) aborted = true;
      if (pos.halfmove >= 100) return 0;
      const us = pos.turn;
      const inChk = C.inCheck(pos, us);
      if (inChk && depth < 3) depth++;
      if (depth <= 0) return qsearch(alpha, beta, ply);

      const origAlpha = alpha;
      const ttIdx = useTT ? (pos.hLo & TT_MASK) : 0;
      let ttMoveCand = 0;
      if (useTT && ply > 0 && ttGen[ttIdx] === ttEpoch && ttKeyLo[ttIdx] === (pos.hLo | 0) && ttKeyHi[ttIdx] === (pos.hHi | 0)) {
        ttMoveCand = ttMove[ttIdx];
        if (ttDepth[ttIdx] >= depth) {
          let s = ttScore[ttIdx];
          if (s > MATE_BOUND) s -= ply; else if (s < -MATE_BOUND) s += ply;
          const f = ttFlag[ttIdx];
          if (f === TT_EXACT) return s;
          if (f === TT_LOWER && s >= beta) return s;
          if (f === TT_UPPER && s <= alpha) return s;
        }
      }

      if (allowNull && !inChk && !ttMoveCand && depth >= 3 &&
        beta < MATE_BOUND && (us === C.WHITE ? pos.npm0 : pos.npm1) > 0) {
        C.doNullMove(pos);
        const R = 2 + ((depth > 6) ? 1 : 0);
        const v = -negamax(depth - 1 - R, -beta, -beta + 1, ply + 1, false);
        C.undoNullMove(pos);
        if (aborted) return alpha;
        if (v >= beta) return v >= MATE_BOUND ? beta : v;
      }

      let futileBase = -INF;
      let canFutile = false;
      if (depth === 1 && !inChk && !ttMoveCand && beta < MATE_BOUND) {
        futileBase = evaluate(pos, P);
        canFutile = futileBase + 175 <= alpha;
      }

      const moves = sortMoves(C.generateMoves(pos, false), killers, historyTable, Math.min(ply, 60), ttMoveCand);
      let legal = 0, bestVal = -INF, bestMv = 0;
      for (let i = 0; i < moves.length; i++) {
        const m = moves[i];
        const isCap = C.mCapt(m) !== 0 || C.mPromo(m) !== 0 || (C.mFlags(m) & C.FLAG_EP) !== 0;
        if (canFutile && i >= 3 && !isCap && m !== ttMoveCand) {
          continue;
        }
        C.makeMove(pos, m);
        if (C.inCheck(pos, us)) { C.unmakeMove(pos); continue; }
        legal++;
        let v;
        if (i === 0 || depth < 3) {
          v = -negamax(depth - 1, -beta, -alpha, ply + 1, true);
        } else {
          let R = 0;
          if (i >= 4 && !isCap && !inChk) R = 1;
          v = -negamax(depth - 1 - R, -alpha - 1, -alpha, ply + 1, true);
          if (R && v > alpha) {
            v = -negamax(depth - 1, -alpha - 1, -alpha, ply + 1, true);
          }
          if (v > alpha && v < beta) {
            v = -negamax(depth - 1, -beta, -alpha, ply + 1, true);
          }
        }
        C.unmakeMove(pos);
        if (aborted) return bestVal === -INF ? alpha : bestVal;
        if (v > bestVal) { bestVal = v; bestMv = m; }
        if (v > alpha) {
          alpha = v;
          if (v >= beta) {
            if (!isCap) {
              const kp = Math.min(ply, 60) * 2;
              if (killers[kp] !== m) { killers[kp + 1] = killers[kp]; killers[kp] = m; }
              historyTable[C.mPiece(m) * 128 + C.mTo(m)] += depth * depth;
            }
            break;
          }
        }
      }
      if (legal === 0) return inChk ? -(MATE - ply) : 0;

      let ss = bestVal > MATE_BOUND ? bestVal + ply : bestVal < -MATE_BOUND ? bestVal - ply : bestVal;
      if (useTT) {
        const flag = bestVal <= origAlpha ? TT_UPPER : (bestVal >= beta ? TT_LOWER : TT_EXACT);
        ttGen[ttIdx] = ttEpoch;
        ttKeyLo[ttIdx] = pos.hLo | 0; ttKeyHi[ttIdx] = pos.hHi | 0;
        ttScore[ttIdx] = ss; ttDepth[ttIdx] = depth; ttFlag[ttIdx] = flag; ttMove[ttIdx] = bestMv;
      }

      return bestVal;
    }

    const useTT = maxDepth > 2;
    if (useTT) {
      if (++ttEpoch > 2000000000) { ttGen.fill(0); ttEpoch = 1; }
    }
    let prevScored = rootMoves.map((m) => ({ m, s: 0 }));
    for (let d = 1; d <= maxDepth; d++) {
      const scored = [];
      let alpha = -INF;
      let localBest = null, localBestV = -INF;
      const ordered = prevScored.slice().sort((a, b) => b.s - a.s).map((e) => e.m);
      const rest = rootMoves.filter((m) => ordered.indexOf(m) === -1);
      const fullList = ordered.concat(rest);
      for (const m of fullList) {
        C.makeMove(pos, m);
        let v = -negamax(d - 1, -INF, INF - 1, 1);
        C.unmakeMove(pos);
        if (aborted) break;
        if (seenKeys) {
          const k = C.posKey(pos);
          let occ = 0;
          for (let i = 0; i < seenKeys.length; i++) if (seenKeys[i] === k) occ++;
          if (occ > 0 && v > -MATE / 2 && v < MATE / 2) v -= 14 * occ;
        }
        if (rng && rootNoise > 0) v += (rng() * 2 - 1) * rootNoise;
        scored.push({ m, s: v });
        if (v > localBestV) { localBestV = v; localBest = m; }
        if (v > alpha) alpha = v;
      }
      if (localBest !== null && (!aborted || d === 1)) {
        bestMove = localBest;
        bestScore = localBestV;
        completedDepth = d;
        prevScored = scored;
      } else if (d === 1 && localBest !== null) {
        bestMove = localBest;
        bestScore = localBestV;
        completedDepth = 1;
        prevScored = scored;
      }
      if (aborted) break;
      if (Math.abs(bestScore) > MATE - 200) break;
      if (Date.now() > deadline) break;
    }

    if (pickMargin > 0 && prevScored.length > 1) {
      const top = prevScored.filter((e) => e.s >= bestScore - pickMargin);
      if (top.length > 1 && rng) {
        const pick = top[Math.floor(rng() * top.length)];
        bestMove = pick.m;
        bestScore = pick.s;
      }
    }

    const pv = extractPv(pos, P, bestMove, Math.max(completedDepth, 1));
    return {
      move: bestMove,
      score: bestScore,
      depth: completedDepth,
      nodes,
      timeMs: Date.now() - t0,
      pv
    };
  }

  function extractPv(pos, P, firstMove, maxLen) {
    const pvLine = [];
    let made = 0;
    try {
      C.makeMove(pos, firstMove);
      made++;
      pvLine.push(firstMove);
      for (let i = 1; i < maxLen + 4; i++) {
        const moves = C.generateMoves(pos, false);
        let bestV = -INF, bestM = 0;
        for (const m of moves) {
          C.makeMove(pos, m);
          if (C.inCheck(pos, pos.turn ^ 1)) { C.unmakeMove(pos); continue; }
          const v = -evaluate(pos, P);
          C.unmakeMove(pos);
          if (v > bestV) { bestV = v; bestM = m; }
        }
        if (!bestM) break;
        C.makeMove(pos, bestM);
        made++;
        pvLine.push(bestM);
      }
    } finally {
      while (made-- > 0) C.unmakeMove(pos);
    }
    return pvLine;
  }

  const api = {
    MATE, INF,
    defaultParams, paramsFromPlain, paramsToPlain,
    evaluate, think
  };
  root.Engine = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
