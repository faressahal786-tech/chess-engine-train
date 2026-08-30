import time

import chess

MATE = 1000000
INF = 10000000

PST_P = [
    0, 0, 0, 0, 0, 0, 0, 0,
    50, 50, 50, 50, 50, 50, 50, 50,
    10, 10, 20, 30, 30, 20, 10, 10,
    5, 5, 10, 25, 25, 10, 5, 5,
    0, 0, 0, 20, 20, 0, 0, 0,
    5, -5, -10, 0, 0, -10, -5, 5,
    5, 10, 10, -20, -20, 10, 10, 5,
    0, 0, 0, 0, 0, 0, 0, 0]
PST_N = [
    -50, -40, -30, -30, -30, -30, -40, -50,
    -40, -20, 0, 0, 0, 0, -20, -40,
    -30, 0, 10, 15, 15, 10, 0, -30,
    -30, 5, 15, 20, 20, 15, 5, -30,
    -30, 0, 15, 20, 20, 15, 0, -30,
    -30, 5, 10, 15, 15, 10, 5, -30,
    -40, -20, 0, 5, 5, 0, -20, -40,
    -50, -40, -30, -30, -30, -30, -40, -50]
PST_B = [
    -20, -10, -10, -10, -10, -10, -10, -20,
    -10, 0, 0, 0, 0, 0, 0, -10,
    -10, 0, 5, 10, 10, 5, 0, -10,
    -10, 5, 5, 10, 10, 5, 5, -10,
    -10, 0, 10, 10, 10, 10, 0, -10,
    -10, 10, 10, 10, 10, 10, 10, -10,
    -10, 5, 0, 0, 0, 0, 5, -10,
    -20, -10, -10, -10, -10, -10, -10, -20]
PST_R = [
    0, 0, 0, 0, 0, 0, 0, 0,
    5, 10, 10, 10, 10, 10, 10, 5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    0, 0, 0, 5, 5, 0, 0, 0]
PST_Q = [
    -20, -10, -10, -5, -5, -10, -10, -20,
    -10, 0, 0, 0, 0, 0, 0, -10,
    -10, 0, 5, 5, 5, 5, 0, -10,
    -5, 0, 5, 5, 5, 5, 0, -5,
    0, 0, 5, 5, 5, 5, 0, -5,
    -10, 5, 5, 5, 5, 5, 0, -10,
    -10, 0, 5, 0, 0, 0, 0, -10,
    -20, -10, -10, -5, -5, -10, -10, -20]
PST_K_MG = [
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -20, -30, -30, -40, -40, -30, -30, -20,
    -10, -20, -20, -20, -20, -20, -20, -10,
    20, 20, 0, 0, 0, 0, 20, 20,
    20, 30, 10, 0, 0, 10, 30, 20]
PST_K_EG = [
    -50, -40, -30, -20, -20, -30, -40, -50,
    -30, -20, -10, 0, 0, -10, -20, -30,
    -30, -10, 20, 30, 30, 20, -10, -30,
    -30, -10, 30, 40, 40, 30, -10, -30,
    -30, -10, 30, 40, 40, 30, -10, -30,
    -30, -10, 20, 30, 30, 20, -10, -30,
    -30, -30, 0, 0, 0, 0, -30, -30,
    -50, -30, -30, -30, -30, -30, -30, -50]

BASE_TABLES = {"p": PST_P, "n": PST_N, "b": PST_B, "r": PST_R, "q": PST_Q}
TABLE_KEYS = ("p", "n", "b", "r", "q", "kmg", "keg")


def _build_side_tables():
    w = {}
    b = {}
    for k in TABLE_KEYS:
        w[k] = [0] * 128
        b[k] = [0] * 128
    for sq88 in range(128):
        if sq88 & 0x88:
            continue
        f = sq88 & 7
        r = sq88 >> 4
        idx_w = (7 - r) * 8 + f
        idx_b = r * 8 + f
        for t in ("p", "n", "b", "r", "q"):
            w[t][sq88] = BASE_TABLES[t][idx_w]
            b[t][sq88] = BASE_TABLES[t][idx_b]
        w["kmg"][sq88] = PST_K_MG[idx_w]
        w["keg"][sq88] = PST_K_EG[idx_w]
        b["kmg"][sq88] = PST_K_MG[idx_b]
        b["keg"][sq88] = PST_K_EG[idx_b]
    return w, b


_W_DEFAULT, _B_DEFAULT = _build_side_tables()

SCALAR_NAMES = ("bishopPair", "doubled", "isolated", "passed",
                "rookOpen", "rookHalf", "kingShield", "tempo")


def default_params():
    return {
        "val": {"p": 100.0, "n": 320.0, "b": 330.0, "r": 500.0, "q": 900.0},
        "pstW": {k: list(_W_DEFAULT[k]) for k in TABLE_KEYS},
        "pstB": {k: list(_B_DEFAULT[k]) for k in TABLE_KEYS},
        "bishopPair": 30.0,
        "doubled": 12.0,
        "isolated": 16.0,
        "passed": 24.0,
        "rookOpen": 22.0,
        "rookHalf": 11.0,
        "kingShield": 9.0,
        "tempo": 10.0,
    }


def params_from_plain(o):
    d = default_params()
    if not o:
        return d
    val = o.get("val") or {}
    for k in ("p", "n", "b", "r", "q"):
        v = val.get(k)
        if isinstance(v, (int, float)):
            d["val"][k] = float(v)
    for side in ("pstW", "pstB"):
        src_side = o.get(side) or {}
        for k in TABLE_KEYS:
            src = src_side.get(k)
            if src and len(src) >= 128:
                for i in range(128):
                    v = src[i]
                    if isinstance(v, (int, float)):
                        d[side][k][i] = float(v)
    for k in SCALAR_NAMES:
        v = o.get(k)
        if isinstance(v, (int, float)):
            d[k] = float(v)
    return d


def params_to_plain(p):
    return {
        "val": dict(p["val"]),
        "pstW": {k: list(p["pstW"][k]) for k in TABLE_KEYS},
        "pstB": {k: list(p["pstB"][k]) for k in TABLE_KEYS},
        **{k: p[k] for k in SCALAR_NAMES},
    }


PASSED_F = (0, 0.2, 0.35, 0.55, 0.8, 1.15, 1.6, 0)
VAL_KEY_BY_TYPE = ("", "p", "n", "b", "r", "q")


def count_shield(board, k_sq63, white):
    if k_sq63 is None:
        return 0.0
    f = k_sq63 & 7
    r = k_sq63 >> 3
    shield = 0.0
    for df in (-1, 0, 1):
        nf = f + df
        if nf < 0 or nf > 7:
            continue
        rr = r + 1 if white else r - 1
        if 0 <= rr < 8:
            t = rr * 8 + nf
            if board.piece_type_at(t) == chess.PAWN and board.color_at(t) == white:
                shield += 1
                continue
        rr2 = rr + 1 if white else rr - 1
        if 0 <= rr2 < 8:
            t2 = rr2 * 8 + nf
            if board.piece_type_at(t2) == chess.PAWN and board.color_at(t2) == white:
                shield += 0.5
    return shield


def evaluate(board, P):
    mg = 0.0
    eg = 0.0
    phase = 0
    w_bishops = 0
    b_bishops = 0
    wk_sq = None
    bk_sq = None

    wp_file = [-1] * 8
    bp_file = [8] * 8
    wp_count = [0] * 8
    bp_count = [0] * 8
    rooks = []

    val = P["val"]
    pstW = P["pstW"]
    pstB = P["pstB"]

    for s63, piece in board.piece_map().items():
        pt = piece.piece_type
        white = piece.color == chess.WHITE
        f = s63 & 7
        r = s63 >> 3
        sq88 = (r << 4) | f
        if pt == chess.PAWN:
            if white:
                s = val["p"] + pstW["p"][sq88]
                mg += s
                eg += s
                wp_count[f] += 1
                if r > wp_file[f]:
                    wp_file[f] = r
            else:
                s = val["p"] + pstB["p"][sq88]
                mg -= s
                eg -= s
                bp_count[f] += 1
                if r < bp_file[f]:
                    bp_file[f] = r
        elif pt == chess.KING:
            if white:
                mg += pstW["kmg"][sq88]
                eg += pstW["keg"][sq88]
                wk_sq = s63
            else:
                mg -= pstB["kmg"][sq88]
                eg -= pstB["keg"][sq88]
                bk_sq = s63
        else:
            key = VAL_KEY_BY_TYPE[pt]
            tbl = pstW[key] if white else pstB[key]
            s = val[key] + tbl[sq88]
            if pt == chess.KNIGHT:
                phase += 1
            elif pt == chess.BISHOP:
                phase += 1
                if white:
                    w_bishops += 1
                else:
                    b_bishops += 1
            elif pt == chess.ROOK:
                phase += 2
                rooks.append((f, white))
            elif pt == chess.QUEEN:
                phase += 4
            if white:
                mg += s
                eg += s
            else:
                mg -= s
                eg -= s

    doubled = P["doubled"]
    isolated = P["isolated"]
    for f in range(8):
        wc = wp_count[f]
        bc = bp_count[f]
        if wc > 1:
            pen = doubled * (wc - 1)
            mg -= pen
            eg -= pen
        if bc > 1:
            pen = doubled * (bc - 1)
            mg += pen
            eg += pen
        wl = wp_count[f - 1] if f > 0 else 0
        wr_ = wp_count[f + 1] if f < 7 else 0
        bl = bp_count[f - 1] if f > 0 else 0
        br_ = bp_count[f + 1] if f < 7 else 0
        if wc > 0 and wl + wr_ == 0:
            pen = isolated * wc
            mg -= pen
            eg -= pen
        if bc > 0 and bl + br_ == 0:
            pen = isolated * bc
            mg += pen
            eg += pen
        if wc > 0:
            al = bp_file[f - 1] if f > 0 else 8
            ar = bp_file[f + 1] if f < 7 else 8
            if bp_file[f] > wp_file[f] and al > wp_file[f] and ar > wp_file[f]:
                bon = round(P["passed"] * PASSED_F[wp_file[f]])
                mg += bon
                eg += round(bon * 1.5)
        if bc > 0:
            al = wp_file[f - 1] if f > 0 else -1
            ar = wp_file[f + 1] if f < 7 else -1
            if wp_file[f] < bp_file[f] and al < bp_file[f] and ar < bp_file[f]:
                bon = round(P["passed"] * PASSED_F[7 - bp_file[f]])
                mg -= bon
                eg -= round(bon * 1.5)

    if w_bishops >= 2:
        mg += P["bishopPair"]
        eg += P["bishopPair"]
    if b_bishops >= 2:
        mg -= P["bishopPair"]
        eg -= P["bishopPair"]

    rook_open = P["rookOpen"]
    rook_half = P["rookHalf"]
    for f, white in rooks:
        if white:
            if wp_count[f] == 0:
                bon = rook_open if bp_count[f] == 0 else rook_half
                mg += bon
                eg += bon
        else:
            if bp_count[f] == 0:
                bon = rook_open if wp_count[f] == 0 else rook_half
                mg -= bon
                eg -= bon

    mg += count_shield(board, wk_sq, True) * P["kingShield"]
    mg -= count_shield(board, bk_sq, False) * P["kingShield"]

    if phase > 24:
        phase = 24
    score = (mg * phase + eg * (24 - phase)) / 24 + P["tempo"]
    return score if board.turn == chess.WHITE else -score


def _order_moves(board, moves, killers, hist, ply):
    scored = []
    kp_base = min(ply, 60) * 2
    k1 = killers[kp_base]
    k2 = killers[kp_base + 1]
    for mv in moves:
        victim = board.piece_type_at(mv.to_square)
        promo = mv.promotion or 0
        if victim or board.is_en_passant(mv):
            at = board.piece_type_at(mv.from_square) or 1
            vt = victim or 1
            s = 1000000 + vt * 16 - at
            if board.is_en_passant(mv):
                s += 15
            if promo:
                s += promo * 10
        elif promo:
            s = 1000000 + promo * 10
        else:
            key = (mv.from_square, mv.to_square, mv.promotion)
            if key == k1:
                s = 900000
            elif key == k2:
                s = 800000
            else:
                h = hist[mv.from_square * 64 + mv.to_square]
                s = h if h > 0 else 0
        scored.append((s, mv))
    scored.sort(key=lambda e: e[0], reverse=True)
    return [m for _, m in scored]


def think(board, P, max_depth=3, time_ms=0, rng=None, root_noise=0.0,
          pick_margin=0.0, seen_keys=None):
    deadline = (time.perf_counter() + time_ms / 1000.0) if time_ms and time_ms > 0 else None
    nodes = 0
    aborted = False
    killers = [None] * 130
    hist = [0] * (64 * 64)

    def check_time():
        nonlocal aborted
        if deadline is not None and time.perf_counter() > deadline:
            aborted = True

    def qsearch(alpha, beta, ply):
        nonlocal nodes
        nodes += 1
        if (nodes & 1023) == 0:
            check_time()
        stand = evaluate(board, P)
        if stand >= beta:
            return stand
        if stand > alpha:
            alpha = stand
        if ply > 24:
            return alpha
        caps = _order_moves(board, list(board.generate_legal_captures()), killers, hist, ply)
        for mv in caps:
            if board.is_into_check(mv):
                continue
            board.push(mv)
            v = -qsearch(-beta, -alpha, ply + 1)
            board.pop()
            if aborted:
                return alpha
            if v >= beta:
                return v
            if v > alpha:
                alpha = v
        return alpha

    def negamax(depth, alpha, beta, ply):
        nonlocal nodes
        nodes += 1
        if (nodes & 1023) == 0:
            check_time()
        if board.halfmove_clock >= 100:
            return 0
        in_chk = board.is_check()
        if in_chk and depth < 3:
            depth += 1
        if depth <= 0:
            return qsearch(alpha, beta, ply)

        moves = _order_moves(board, list(board.legal_moves), killers, hist, ply)
        legal = 0
        best_val = -INF
        for mv in moves:
            if board.is_into_check(mv):
                continue
            legal += 1
            board.push(mv)
            v = -negamax(depth - 1, -beta, -alpha, ply + 1)
            board.pop()
            if aborted:
                return best_val if best_val != -INF else alpha
            if v > best_val:
                best_val = v
            if v > alpha:
                alpha = v
                if v >= beta:
                    if not (board.piece_type_at(mv.to_square) or mv.promotion or board.is_en_passant(mv)):
                        kp = min(ply, 60) * 2
                        key = (mv.from_square, mv.to_square, mv.promotion)
                        if killers[kp] != key:
                            killers[kp + 1] = killers[kp]
                            killers[kp] = key
                        hist[mv.from_square * 64 + mv.to_square] += depth * depth
                    break
        if legal == 0:
            return -(MATE - ply) if in_chk else 0
        return best_val

    t0 = time.perf_counter()
    root_moves = list(board.legal_moves)
    if not root_moves:
        return None

    best_move_obj = root_moves[0]
    best_score = 0
    completed_depth = 0
    prev_scored = [(mv, 0) for mv in root_moves]

    for d in range(1, max_depth + 1):
        scored = []
        local_best = None
        local_best_v = -INF
        full_list = [m for m, _ in sorted(prev_scored, key=lambda e: e[1], reverse=True)]
        in_full = set(full_list)
        for m in root_moves:
            if m not in in_full:
                full_list.append(m)
        for mv in full_list:
            board.push(mv)
            v = -negamax(d - 1, -INF, INF - 1, 1)
            if seen_keys and not aborted and abs(v) < MATE / 2:
                k = " ".join(board.fen().split()[:4])
                occ = sum(1 for kk in seen_keys if kk == k)
                if occ > 0:
                    v -= 14 * occ
            board.pop()
            if aborted:
                break
            if rng is not None and root_noise > 0:
                v += (rng() * 2 - 1) * root_noise
            scored.append((mv, v))
            if v > local_best_v:
                local_best_v = v
                local_best = mv
        if local_best is not None and (not aborted or d == 1):
            best_move_obj = local_best
            best_score = local_best_v
            completed_depth = d
            prev_scored = scored
        if aborted:
            break
        if abs(best_score) > MATE - 200:
            break
        if deadline is not None and time.perf_counter() > deadline:
            break

    if pick_margin > 0 and rng is not None and len(prev_scored) > 1:
        top = [e for e in prev_scored if e[1] >= best_score - pick_margin]
        if len(top) > 1:
            pick = top[int(rng() * len(top)) % len(top)]
            best_move_obj, best_score = pick

    pv = extract_pv(board, P, best_move_obj, max(completed_depth, 1))
    from . import lib_core as L
    return {
        "move": L.move_to_int(best_move_obj),
        "move_obj": best_move_obj,
        "score": best_score,
        "depth": completed_depth,
        "nodes": nodes,
        "time_ms": int((time.perf_counter() - t0) * 1000),
        "pv": pv,
    }


def extract_pv(board, P, first_move, max_len):
    from . import lib_core as L
    pv_line = []
    b2 = board.copy(stack=False)
    made = 0
    try:
        b2.push(first_move)
        made += 1
        pv_line.append(L.move_to_int(first_move))
        for _ in range(max_len + 4):
            best_v = -INF
            best_m = None
            for m in b2.legal_moves:
                if b2.is_into_check(m):
                    continue
                b2.push(m)
                v = -evaluate(b2, P)
                b2.pop()
                if v > best_v:
                    best_v = v
                    best_m = m
            if best_m is None:
                break
            b2.push(best_m)
            made += 1
            pv_line.append(L.move_to_int(best_m))
    finally:
        while made > 0:
            b2.pop()
            made -= 1
    return pv_line


def pv_to_san(board, pv_ints):
    from . import lib_core as L
    out = []
    b2 = board.copy(stack=True)
    try:
        legal = list(b2.legal_moves)
        for i in pv_ints[:6]:
            found = L.int_to_move(b2, i)
            if found is None or found not in legal:
                break
            out.append(b2.san(found))
            b2.push(found)
            legal = list(b2.legal_moves)
    except Exception:
        pass
    return out
