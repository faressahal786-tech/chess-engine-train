"use strict";
(function (root) {
  const PAWN = 1, KNIGHT = 2, BISHOP = 3, ROOK = 4, QUEEN = 5, KING = 6;
  const WHITE = 0, BLACK = 1;

  const piece = (color, type) => (color << 3) | type;
  const typeOf = (p) => p & 7;
  const colorOf = (p) => p >> 3;

  const KNIGHT_OFFS = [31, 33, 14, 18, -31, -33, -14, -18];
  const KING_OFFS = [1, -1, 16, -16, 15, 17, -15, -17];
  const BISHOP_DIRS = [15, 17, -15, -17];
  const ROOK_DIRS = [1, -1, 16, -16];

  const FLAG_EP = 1, FLAG_CASTLE = 2, FLAG_DPUSH = 4;
  const mkMove = (f, t, p, c, pr, fl) =>
    f | (t << 7) | (p << 14) | ((c || 0) << 18) | ((pr || 0) << 22) | ((fl || 0) << 26);
  const mFrom = (m) => m & 127;
  const mTo = (m) => (m >>> 7) & 127;
  const mPiece = (m) => (m >>> 14) & 15;
  const mCapt = (m) => (m >>> 18) & 15;
  const mPromo = (m) => (m >>> 22) & 15;
  const mFlags = (m) => (m >>> 26) & 7;

  const ok = (sq) => !(sq & 0x88);

  const CASTLE_MASK = new Uint8Array(128).fill(15);
  CASTLE_MASK[0x00] &= ~2;
  CASTLE_MASK[0x07] &= ~1;
  CASTLE_MASK[0x04] &= ~3;
  CASTLE_MASK[0x70] &= ~8;
  CASTLE_MASK[0x77] &= ~4;
  CASTLE_MASK[0x74] &= ~12;

  let _zs = 0x9E3779B9 | 0;
  function zrand() {
    _zs ^= _zs << 13; _zs |= 0;
    _zs ^= _zs >>> 17;
    _zs ^= _zs << 5; _zs |= 0;
    return _zs >>> 0;
  }
  const Z_PIECE_LO = new Int32Array(24 * 128);
  const Z_PIECE_HI = new Int32Array(24 * 128);
  const Z_CASTLE_LO = new Int32Array(16);
  const Z_CASTLE_HI = new Int32Array(16);
  const Z_EP_LO = new Int32Array(8);
  const Z_EP_HI = new Int32Array(8);
  for (let i = 0; i < 24 * 128; i++) { Z_PIECE_LO[i] = zrand() | 0; Z_PIECE_HI[i] = zrand() | 0; }
  for (let i = 0; i < 16; i++) { Z_CASTLE_LO[i] = zrand() | 0; Z_CASTLE_HI[i] = zrand() | 0; }
  for (let i = 0; i < 8; i++) { Z_EP_LO[i] = zrand() | 0; Z_EP_HI[i] = zrand() | 0; }
  const Z_SIDE_LO = zrand() | 0;
  const Z_SIDE_HI = zrand() | 0;

  function zXor(pos, pieceCode, sq) {
    const idx = pieceCode * 128 + sq;
    pos.hLo ^= Z_PIECE_LO[idx];
    pos.hHi ^= Z_PIECE_HI[idx];
  }
  function zCastle(pos, oldR, newR) {
    if (oldR !== newR) {
      pos.hLo ^= Z_CASTLE_LO[oldR] ^ Z_CASTLE_LO[newR];
      pos.hHi ^= Z_CASTLE_HI[oldR] ^ Z_CASTLE_HI[newR];
    }
  }
  function zEp(pos, epSq) {
    if (epSq >= 0) {
      pos.hLo ^= Z_EP_LO[epSq & 7];
      pos.hHi ^= Z_EP_HI[epSq & 7];
    }
  }
  function zSide(pos) {
    pos.hLo = (pos.hLo ^ Z_SIDE_LO) | 0;
    pos.hHi = (pos.hHi ^ Z_SIDE_HI) | 0;
  }

  const NPM_VAL = [0, 0, 1, 1, 2, 4, 0];

  function computeHash(pos) {
    pos.hLo = 0; pos.hHi = 0;
    for (let sq = 0; sq < 128; sq++) {
      if (sq & 0x88) { sq += 7; continue; }
      const p = pos.board[sq];
      if (p) zXor(pos, p, sq);
    }
    zCastle(pos, 15, pos.castling);
    zEp(pos, pos.ep);
    if (pos.turn === BLACK) zSide(pos);
  }

  function computeNpm(pos) {
    pos.npm0 = 0; pos.npm1 = 0;
    for (let sq = 0; sq < 128; sq++) {
      if (sq & 0x88) { sq += 7; continue; }
      const p = pos.board[sq];
      if (!p) continue;
      const t = p & 7;
      if (t === PAWN || t === KING) continue;
      if ((p >> 3) === WHITE) pos.npm0 += NPM_VAL[t]; else pos.npm1 += NPM_VAL[t];
    }
  }

  const FILES = "abcdefgh";
  const sqName = (sq) => FILES[sq & 7] + (((sq >> 4) & 7) + 1);
  const parseSq = (s) => (s.charCodeAt(0) - 97) + ((s.charCodeAt(1) - 49) * 16);
  const PIECE_CHARS = { P: piece(WHITE, PAWN), N: piece(WHITE, KNIGHT), B: piece(WHITE, BISHOP), R: piece(WHITE, ROOK), Q: piece(WHITE, QUEEN), K: piece(WHITE, KING), p: piece(BLACK, PAWN), n: piece(BLACK, KNIGHT), b: piece(BLACK, BISHOP), r: piece(BLACK, ROOK), q: piece(BLACK, QUEEN), k: piece(BLACK, KING) };
  const CHAR_OF = {};
  for (const ch in PIECE_CHARS) CHAR_OF[PIECE_CHARS[ch]] = ch;

  class Position {
    constructor() {
      this.board = new Uint8Array(128);
      this.turn = WHITE;
      this.castling = 0;
      this.ep = -1;
      this.halfmove = 0;
      this.fullmove = 1;
      this.kings = [-1, -1];
      this.hist = [];
      this.hLo = 0;
      this.hHi = 0;
      this.npm0 = 0;
      this.npm1 = 0;
    }
  }

  function setFen(pos, fen) {
    pos.board.fill(0);
    pos.kings = [-1, -1];
    pos.hist.length = 0;
    const parts = fen.trim().split(/\s+/);
    const rows = parts[0].split("/");
    if (rows.length !== 8) throw new Error("bad FEN board: " + fen);
    for (let i = 0; i < 8; i++) {
      let file = 0;
      const rank = 7 - i;
      for (const ch of rows[i]) {
        if (ch >= "1" && ch <= "8") { file += +ch; continue; }
        const pc = PIECE_CHARS[ch];
        if (!pc) throw new Error("bad FEN char: " + ch);
        const sq = rank * 16 + file;
        pos.board[sq] = pc;
        if (typeOf(pc) === KING) pos.kings[colorOf(pc)] = sq;
        file++;
      }
      if (file !== 8) throw new Error("bad FEN row length: " + rows[i]);
    }
    pos.turn = parts[1] === "b" ? BLACK : WHITE;
    pos.castling = 0;
    const cr = parts[2] || "-";
    if (cr.includes("K")) pos.castling |= 1;
    if (cr.includes("Q")) pos.castling |= 2;
    if (cr.includes("k")) pos.castling |= 4;
    if (cr.includes("q")) pos.castling |= 8;
    pos.ep = parts[3] && parts[3] !== "-" ? parseSq(parts[3]) : -1;
    pos.halfmove = parts[4] !== undefined ? +parts[4] : 0;
    pos.fullmove = parts[5] !== undefined ? +parts[5] : 1;
    computeHash(pos);
    computeNpm(pos);
    return pos;
  }

  function toFen(pos) {
    const rows = [];
    for (let i = 0; i < 8; i++) {
      let row = "", empty = 0;
      const rank = 7 - i;
      for (let f = 0; f < 8; f++) {
        const pc = pos.board[rank * 16 + f];
        if (!pc) { empty++; continue; }
        if (empty) { row += empty; empty = 0; }
        row += CHAR_OF[pc];
      }
      if (empty) row += empty;
      rows.push(row);
    }
    let cr = "";
    if (pos.castling & 1) cr += "K";
    if (pos.castling & 2) cr += "Q";
    if (pos.castling & 4) cr += "k";
    if (pos.castling & 8) cr += "q";
    return rows.join("/") + " " + (pos.turn === WHITE ? "w" : "b") + " " + (cr || "-") + " " +
      (pos.ep >= 0 ? sqName(pos.ep) : "-") + " " + pos.halfmove + " " + pos.fullmove;
  }

  function createStart() {
    return setFen(new Position(), "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
  }

  function isAttacked(pos, sq, by) {
    const b = pos.board;
    if (by === WHITE) {
      let t = sq - 15; if (ok(t) && b[t] === 1) return true;
      t = sq - 17; if (ok(t) && b[t] === 1) return true;
    } else {
      let t = sq + 15; if (ok(t) && b[t] === 9) return true;
      t = sq + 17; if (ok(t) && b[t] === 9) return true;
    }
    const n = piece(by, KNIGHT);
    for (let i = 0; i < 8; i++) { const t = sq + KNIGHT_OFFS[i]; if (ok(t) && b[t] === n) return true; }
    const k = piece(by, KING);
    for (let i = 0; i < 8; i++) { const t = sq + KING_OFFS[i]; if (ok(t) && b[t] === k) return true; }
    const bq = piece(by, BISHOP), qq = piece(by, QUEEN);
    for (let i = 0; i < 4; i++) {
      let t = sq + BISHOP_DIRS[i];
      while (ok(t)) { const p = b[t]; if (p) { if (p === bq || p === qq) return true; break; } t += BISHOP_DIRS[i]; }
    }
    const rq = piece(by, ROOK);
    for (let i = 0; i < 4; i++) {
      let t = sq + ROOK_DIRS[i];
      while (ok(t)) { const p = b[t]; if (p) { if (p === rq || p === qq) return true; break; } t += ROOK_DIRS[i]; }
    }
    return false;
  }

  function inCheck(pos, color) {
    return isAttacked(pos, pos.kings[color], color ^ 1);
  }

  function genCastles(pos, moves) {
    const us = pos.turn, them = us ^ 1;
    const b = pos.board;
    if (us === WHITE) {
      if (pos.kings[WHITE] !== 0x04) return;
      if ((pos.castling & 1) && !b[0x05] && !b[0x06] && b[0x07] === piece(WHITE, ROOK) &&
        !isAttacked(pos, 0x04, them) && !isAttacked(pos, 0x05, them))
        moves.push(mkMove(0x04, 0x06, piece(WHITE, KING), 0, 0, FLAG_CASTLE));
      if ((pos.castling & 2) && !b[0x03] && !b[0x02] && !b[0x01] && b[0x00] === piece(WHITE, ROOK) &&
        !isAttacked(pos, 0x04, them) && !isAttacked(pos, 0x03, them))
        moves.push(mkMove(0x04, 0x02, piece(WHITE, KING), 0, 0, FLAG_CASTLE));
    } else {
      if (pos.kings[BLACK] !== 0x74) return;
      if ((pos.castling & 4) && !b[0x75] && !b[0x76] && b[0x77] === piece(BLACK, ROOK) &&
        !isAttacked(pos, 0x74, them) && !isAttacked(pos, 0x75, them))
        moves.push(mkMove(0x74, 0x76, piece(BLACK, KING), 0, 0, FLAG_CASTLE));
      if ((pos.castling & 8) && !b[0x73] && !b[0x72] && !b[0x71] && b[0x70] === piece(BLACK, ROOK) &&
        !isAttacked(pos, 0x74, them) && !isAttacked(pos, 0x73, them))
        moves.push(mkMove(0x74, 0x72, piece(BLACK, KING), 0, 0, FLAG_CASTLE));
    }
  }

  function pushPawn(moves, from, to, p, cap, promoRank) {
    if ((to >> 4) === promoRank) {
      moves.push(mkMove(from, to, p, cap, QUEEN, 0));
      moves.push(mkMove(from, to, p, cap, ROOK, 0));
      moves.push(mkMove(from, to, p, cap, BISHOP, 0));
      moves.push(mkMove(from, to, p, cap, KNIGHT, 0));
    } else {
      moves.push(mkMove(from, to, p, cap, 0, 0));
    }
  }

  function generateMoves(pos, capturesOnly) {
    const moves = [];
    const us = pos.turn, them = us ^ 1, b = pos.board;
    const promoRank = us === WHITE ? 7 : 0;
    const startRank = us === WHITE ? 1 : 6;
    const dir = us === WHITE ? 16 : -16;
    for (let sq = 0; sq < 128; sq++) {
      if (sq & 0x88) { sq += 7; continue; }
      const p = b[sq];
      if (!p || colorOf(p) !== us) continue;
      const t = typeOf(p);
      if (t === PAWN) {
        const one = sq + dir;
        if (ok(one) && !b[one]) {
          if (!capturesOnly) {
            pushPawn(moves, sq, one, p, 0, promoRank);
            if ((sq >> 4) === startRank) {
              const two = sq + dir * 2;
              if (!b[two]) moves.push(mkMove(sq, two, p, 0, 0, FLAG_DPUSH));
            }
          } else if ((one >> 4) === promoRank) {
            pushPawn(moves, sq, one, p, 0, promoRank);
          }
        }
        for (let k = 0; k < 2; k++) {
          const to = sq + dir + (k ? 1 : -1);
          if (!ok(to)) continue;
          const q = b[to];
          if (q && colorOf(q) === them) {
            pushPawn(moves, sq, to, p, q, promoRank);
          } else if (!q && to === pos.ep) {
            moves.push(mkMove(sq, to, p, piece(them, PAWN), 0, FLAG_EP));
          }
        }
      } else if (t === KNIGHT || t === KING) {
        const offs = t === KNIGHT ? KNIGHT_OFFS : KING_OFFS;
        for (let i = 0; i < 8; i++) {
          const to = sq + offs[i];
          if (!ok(to)) continue;
          const q = b[to];
          if (q && colorOf(q) === us) continue;
          if (capturesOnly && !q) continue;
          moves.push(mkMove(sq, to, p, q, 0, 0));
        }
        if (t === KING && !capturesOnly) genCastles(pos, moves);
      } else {
        const dirs = t === BISHOP ? BISHOP_DIRS : t === ROOK ? ROOK_DIRS : KING_OFFS;
        const nd = dirs.length;
        for (let i = 0; i < nd; i++) {
          const d = dirs[i];
          let to = sq + d;
          while (ok(to)) {
            const q = b[to];
            if (q) {
              if (colorOf(q) === them) moves.push(mkMove(sq, to, p, q, 0, 0));
              break;
            }
            if (!capturesOnly) moves.push(mkMove(sq, to, p, 0, 0, 0));
            to += d;
          }
        }
      }
    }
    return moves;
  }

  function makeMove(pos, m) {
    const from = mFrom(m), to = mTo(m), pc = mPiece(m), fl = mFlags(m);
    const cap = mCapt(m), promoT = mPromo(m);
    const us = pos.turn, them = us ^ 1;
    pos.hist.push({
      m, cap, castling: pos.castling, ep: pos.ep, halfmove: pos.halfmove,
      hLo: pos.hLo, hHi: pos.hHi, n0: pos.npm0, n1: pos.npm1
    });
    zXor(pos, pc, from);
    if (cap) zXor(pos, cap, to);
    if (fl & FLAG_EP) {
      const capSq = to + (us === WHITE ? -16 : 16);
      zXor(pos, piece(them, PAWN), capSq);
      pos.board[capSq] = 0;
    }
    const placed = promoT ? piece(us, promoT) : pc;
    pos.board[to] = placed;
    pos.board[from] = 0;
    zXor(pos, placed, to);
    if (fl & FLAG_CASTLE) {
      if (to > from) {
        zXor(pos, pos.board[to + 1], to + 1);
        pos.board[to - 1] = pos.board[to + 1];
        pos.board[to + 1] = 0;
        zXor(pos, pos.board[to - 1], to - 1);
      } else {
        zXor(pos, pos.board[to - 2], to - 2);
        pos.board[to + 1] = pos.board[to - 2];
        pos.board[to - 2] = 0;
        zXor(pos, pos.board[to + 1], to + 1);
      }
    }
    if (typeOf(pc) === KING) pos.kings[us] = to;
    const oldCastling = pos.castling;
    pos.castling &= CASTLE_MASK[from] & CASTLE_MASK[to];
    zCastle(pos, oldCastling, pos.castling);
    zEp(pos, pos.ep);
    pos.ep = (fl & FLAG_DPUSH) ? from + (us === WHITE ? 16 : -16) : -1;
    zEp(pos, pos.ep);
    if (promoT) {
      if (us === WHITE) { pos.npm0 += NPM_VAL[promoT]; } else { pos.npm1 += NPM_VAL[promoT]; }
    } else if (cap && typeOf(cap) !== PAWN && typeOf(cap) !== KING) {
      if (them === WHITE) { pos.npm0 -= NPM_VAL[typeOf(cap)]; } else { pos.npm1 -= NPM_VAL[typeOf(cap)]; }
    }
    pos.halfmove = (typeOf(pc) === PAWN || cap) ? 0 : pos.halfmove + 1;
    if (us === BLACK) pos.fullmove++;
    pos.turn = them;
    zSide(pos);
  }

  function unmakeMove(pos) {
    const u = pos.hist.pop();
    const m = u.m;
    pos.turn ^= 1;
    const us = pos.turn;
    if (us === BLACK) pos.fullmove--;
    const from = mFrom(m), to = mTo(m), pc = mPiece(m), fl = mFlags(m);
    pos.board[from] = pc;
    pos.board[to] = 0;
    if (fl & FLAG_EP) {
      pos.board[to + (us === WHITE ? -16 : 16)] = piece(us ^ 1, PAWN);
    } else if (u.cap) {
      pos.board[to] = u.cap;
    }
    if (fl & FLAG_CASTLE) {
      if (to > from) { pos.board[to + 1] = pos.board[to - 1]; pos.board[to - 1] = 0; }
      else { pos.board[to - 2] = pos.board[to + 1]; pos.board[to + 1] = 0; }
    }
    if (typeOf(pc) === KING) pos.kings[us] = from;
    pos.castling = u.castling;
    pos.ep = u.ep;
    pos.halfmove = u.halfmove;
    pos.hLo = u.hLo;
    pos.hHi = u.hHi;
    pos.npm0 = u.n0;
    pos.npm1 = u.n1;
  }

  function doNullMove(pos) {
    pos.hist.push({ __null: true, ep: pos.ep, hLo: pos.hLo, hHi: pos.hHi });
    zEp(pos, pos.ep);
    pos.ep = -1;
    pos.turn ^= 1;
    zSide(pos);
  }

  function undoNullMove(pos) {
    const u = pos.hist.pop();
    pos.turn ^= 1;
    pos.ep = u.ep;
    pos.hLo = u.hLo;
    pos.hHi = u.hHi;
  }

  function legalMoves(pos) {
    const out = [];
    const ms = generateMoves(pos, false);
    for (let i = 0; i < ms.length; i++) {
      makeMove(pos, ms[i]);
      if (!inCheck(pos, pos.turn ^ 1)) out.push(ms[i]);
      unmakeMove(pos);
    }
    return out;
  }

  function posKey(pos) {
    let s = "";
    for (let r = 7; r >= 0; r--) {
      for (let f = 0; f < 8; f++) {
        const p = pos.board[r * 16 + f];
        s += p ? CHAR_OF[p] : ".";
      }
    }
    return s + "|" + pos.turn + "|" + pos.castling + "|" + (pos.ep >> 4);
  }

  function insufficientMaterial(pos) {
    const minors = [];
    for (let sq = 0; sq < 128; sq++) {
      if (sq & 0x88) { sq += 7; continue; }
      const p = pos.board[sq];
      if (!p) continue;
      const t = typeOf(p);
      if (t === KING) continue;
      if (t === PAWN || t === ROOK || t === QUEEN) return false;
      minors.push({ t, dark: ((sq >> 4) + (sq & 7)) % 2 === 1 });
    }
    if (minors.length === 0) return true;
    if (minors.length === 1) return true;
    for (const mn of minors) if (mn.t === KNIGHT) return false;
    const firstDark = minors[0].dark;
    for (const mn of minors) if (mn.dark !== firstDark) return false;
    return true;
  }

  function gameStatus(pos, keys, repCount) {
    const moves = legalMoves(pos);
    if (moves.length === 0) {
      if (inCheck(pos, pos.turn)) {
        return { over: true, result: pos.turn === WHITE ? "0-1" : "1-0", reason: "checkmate", moves };
      }
      return { over: true, result: "1/2-1/2", reason: "stalemate", moves };
    }
    if (insufficientMaterial(pos)) return { over: true, result: "1/2-1/2", reason: "insufficient material", moves };
    if (pos.halfmove >= 100) return { over: true, result: "1/2-1/2", reason: "50-move rule", moves };
    if (keys && keys.length) {
      const k = posKey(pos);
      let count = 0;
      for (let i = 0; i < keys.length; i++) if (keys[i] === k) count++;
      if (count >= (repCount || 2)) return { over: true, result: "1/2-1/2", reason: "repetition", moves };
    }
    return { over: false, result: null, reason: null, moves };
  }

  function san(pos, m, legal) {
    legal = legal || legalMoves(pos);
    const from = mFrom(m), to = mTo(m), fl = mFlags(m);
    let s;
    if (fl & FLAG_CASTLE) {
      s = to > from ? "O-O" : "O-O-O";
    } else {
      const pc = mPiece(m), t = typeOf(pc);
      const isCap = mCapt(m) !== 0 || (fl & FLAG_EP) !== 0;
      if (t === PAWN) {
        s = isCap ? FILES[from & 7] + "x" + sqName(to) : sqName(to);
        if (mPromo(m)) s += "=" + " PNBRQK"[mPromo(m)];
      } else {
        s = " PNBRQK"[t];
        const others = [];
        for (let i = 0; i < legal.length; i++) {
          const x = legal[i];
          if (x !== m && mPiece(x) === pc && mTo(x) === to && mFrom(x) !== from) others.push(x);
        }
        if (others.length) {
          let sameFile = false, sameRank = false;
          for (const o of others) {
            if ((o & 7) === (from & 7)) sameFile = true;
            if ((o >> 4) === (from >> 4)) sameRank = true;
          }
          if (!sameFile) s += FILES[from & 7];
          else if (!sameRank) s += ((from >> 4) & 7) + 1;
          else s += sqName(from);
        }
        if (isCap) s += "x";
        s += sqName(to);
      }
    }
    makeMove(pos, m);
    const hasMoves = legalMoves(pos).length > 0;
    if (inCheck(pos, pos.turn)) s += hasMoves ? "+" : "#";
    unmakeMove(pos);
    return s;
  }

  function perft(pos, depth) {
    if (depth === 0) return 1;
    const ms = legalMoves(pos);
    if (depth === 1) return ms.length;
    let n = 0;
    for (let i = 0; i < ms.length; i++) {
      makeMove(pos, ms[i]);
      n += perft(pos, depth - 1);
      unmakeMove(pos);
    }
    return n;
  }

  function divide(pos, depth) {
    const lines = [];
    const ms = legalMoves(pos);
    let total = 0;
    for (const m of ms) {
      makeMove(pos, m);
      const n = perft(pos, depth - 1);
      unmakeMove(pos);
      total += n;
      lines.push(sqName(mFrom(m)) + sqName(mTo(m)) + ": " + n);
    }
    lines.push("total: " + total);
    return lines.join("\n");
  }

  const api = {
    PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING, WHITE, BLACK,
    piece, typeOf, colorOf,
    mkMove, mFrom, mTo, mPiece, mCapt, mPromo, mFlags,
    FLAG_EP, FLAG_CASTLE, FLAG_DPUSH,
    Position, createStart, setFen, toFen,
    generateMoves, isAttacked, inCheck, makeMove, unmakeMove,
    legalMoves, posKey, gameStatus, insufficientMaterial,
    san, perft, divide, sqName, parseSq,
    doNullMove, undoNullMove
  };

  root.ChessCore = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
