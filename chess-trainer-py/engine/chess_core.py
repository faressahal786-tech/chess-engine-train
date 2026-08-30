PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = 1, 2, 3, 4, 5, 6
WHITE, BLACK = 0, 1

FLAG_EP, FLAG_CASTLE, FLAG_DPUSH = 1, 2, 4


def piece(color, type_):
    return (color << 3) | type_


def type_of(p):
    return p & 7


def color_of(p):
    return p >> 3


KNIGHT_OFFS = (31, 33, 14, 18, -31, -33, -14, -18)
KING_OFFS = (1, -1, 16, -16, 15, 17, -15, -17)
BISHOP_DIRS = (15, 17, -15, -17)
ROOK_DIRS = (1, -1, 16, -16)

FILES = "abcdefgh"


def mk_move(f, t, p, c=0, pr=0, fl=0):
    return f | (t << 7) | (p << 14) | ((c or 0) << 18) | ((pr or 0) << 22) | ((fl or 0) << 26)


def m_from(m):
    return m & 127


def m_to(m):
    return (m >> 7) & 127


def m_piece(m):
    return (m >> 14) & 15


def m_capt(m):
    return (m >> 18) & 15


def m_promo(m):
    return (m >> 22) & 15


def m_flags(m):
    return (m >> 26) & 7


def ok(sq):
    return not (sq & 0x88)


CASTLE_MASK = [15] * 128
CASTLE_MASK[0x00] &= ~2
CASTLE_MASK[0x07] &= ~1
CASTLE_MASK[0x04] &= ~3
CASTLE_MASK[0x70] &= ~8
CASTLE_MASK[0x77] &= ~4
CASTLE_MASK[0x74] &= ~12

PIECE_CHARS = {
    "P": piece(WHITE, PAWN), "N": piece(WHITE, KNIGHT), "B": piece(WHITE, BISHOP),
    "R": piece(WHITE, ROOK), "Q": piece(WHITE, QUEEN), "K": piece(WHITE, KING),
    "p": piece(BLACK, PAWN), "n": piece(BLACK, KNIGHT), "b": piece(BLACK, BISHOP),
    "r": piece(BLACK, ROOK), "q": piece(BLACK, QUEEN), "k": piece(BLACK, KING),
}
CHAR_OF = {v: k for k, v in PIECE_CHARS.items()}


def sq_name(sq):
    return FILES[sq & 7] + str(((sq >> 4) & 7) + 1)


def parse_sq(s):
    return (ord(s[0]) - 97) + ((ord(s[1]) - 49) * 16)


class Position:
    __slots__ = ("board", "turn", "castling", "ep", "halfmove", "fullmove", "kings", "hist")

    def __init__(self):
        self.board = [0] * 128
        self.turn = WHITE
        self.castling = 0
        self.ep = -1
        self.halfmove = 0
        self.fullmove = 1
        self.kings = [-1, -1]
        self.hist = []


def set_fen(pos, fen):
    pos.board = [0] * 128
    pos.kings = [-1, -1]
    pos.hist = []
    parts = fen.strip().split()
    rows = parts[0].split("/")
    if len(rows) != 8:
        raise ValueError("bad FEN board: " + fen)
    for i in range(8):
        file = 0
        rank = 7 - i
        for ch in rows[i]:
            if ch.isdigit():
                file += int(ch)
                continue
            pc = PIECE_CHARS.get(ch)
            if pc is None:
                raise ValueError("bad FEN char: " + ch)
            sq = rank * 16 + file
            pos.board[sq] = pc
            if type_of(pc) == KING:
                pos.kings[color_of(pc)] = sq
            file += 1
        if file != 8:
            raise ValueError("bad FEN row length: " + rows[i])
    pos.turn = BLACK if len(parts) > 1 and parts[1] == "b" else WHITE
    pos.castling = 0
    cr = parts[2] if len(parts) > 2 else "-"
    if "K" in cr:
        pos.castling |= 1
    if "Q" in cr:
        pos.castling |= 2
    if "k" in cr:
        pos.castling |= 4
    if "q" in cr:
        pos.castling |= 8
    pos.ep = parse_sq(parts[3]) if len(parts) > 3 and parts[3] != "-" else -1
    pos.halfmove = int(parts[4]) if len(parts) > 4 else 0
    pos.fullmove = int(parts[5]) if len(parts) > 5 else 1
    return pos


def to_fen(pos):
    rows = []
    b = pos.board
    for i in range(8):
        row = ""
        empty = 0
        rank = 7 - i
        for f in range(8):
            pc = b[rank * 16 + f]
            if not pc:
                empty += 1
                continue
            if empty:
                row += str(empty)
                empty = 0
            row += CHAR_OF[pc]
        if empty:
            row += str(empty)
        rows.append(row)
    cr = ""
    if pos.castling & 1:
        cr += "K"
    if pos.castling & 2:
        cr += "Q"
    if pos.castling & 4:
        cr += "k"
    if pos.castling & 8:
        cr += "q"
    ep = sq_name(pos.ep) if pos.ep >= 0 else "-"
    return "%s %s %s %s %d %d" % ("/".join(rows), "w" if pos.turn == WHITE else "b",
                                  cr or "-", ep, pos.halfmove, pos.fullmove)


def create_start():
    return set_fen(Position(), "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")


def is_attacked(pos, sq, by):
    b = pos.board
    if by == WHITE:
        t = sq - 15
        if ok(t) and b[t] == 1:
            return True
        t = sq - 17
        if ok(t) and b[t] == 1:
            return True
        n = 2
        k = 6
        bq = 3
        qq = 5
    else:
        t = sq + 15
        if ok(t) and b[t] == 9:
            return True
        t = sq + 17
        if ok(t) and b[t] == 9:
            return True
        n = 10
        k = 14
        bq = 11
        qq = 13
    r = piece(by, ROOK)
    for i in range(8):
        t = sq + KNIGHT_OFFS[i]
        if ok(t) and b[t] == n:
            return True
    for i in range(8):
        t = sq + KING_OFFS[i]
        if ok(t) and b[t] == k:
            return True
    for i in range(4):
        d = BISHOP_DIRS[i]
        t = sq + d
        while ok(t):
            p = b[t]
            if p:
                if p == bq or p == qq:
                    return True
                break
            t += d
    for i in range(4):
        d = ROOK_DIRS[i]
        t = sq + d
        while ok(t):
            p = b[t]
            if p:
                if p == r or p == qq:
                    return True
                break
            t += d
    return False


def in_check(pos, color):
    return is_attacked(pos, pos.kings[color], color ^ 1)


def _gen_castles(pos, moves):
    us = pos.turn
    them = us ^ 1
    b = pos.board
    if us == WHITE:
        if pos.kings[WHITE] != 0x04:
            return
        wr = 4
        wk = 6
        if (pos.castling & 1) and not b[0x05] and not b[0x06] and b[0x07] == wr \
                and not is_attacked(pos, 0x04, them) and not is_attacked(pos, 0x05, them):
            moves.append(mk_move(0x04, 0x06, wk, 0, 0, FLAG_CASTLE))
        if (pos.castling & 2) and not b[0x03] and not b[0x02] and not b[0x01] and b[0x00] == wr \
                and not is_attacked(pos, 0x04, them) and not is_attacked(pos, 0x03, them):
            moves.append(mk_move(0x04, 0x02, wk, 0, 0, FLAG_CASTLE))
    else:
        if pos.kings[BLACK] != 0x74:
            return
        br = 12
        bk = 14
        if (pos.castling & 4) and not b[0x75] and not b[0x76] and b[0x77] == br \
                and not is_attacked(pos, 0x74, them) and not is_attacked(pos, 0x75, them):
            moves.append(mk_move(0x74, 0x76, bk, 0, 0, FLAG_CASTLE))
        if (pos.castling & 8) and not b[0x73] and not b[0x72] and not b[0x71] and b[0x70] == br \
                and not is_attacked(pos, 0x74, them) and not is_attacked(pos, 0x73, them):
            moves.append(mk_move(0x74, 0x72, bk, 0, 0, FLAG_CASTLE))


def _push_pawn(moves, frm, to, p, cap, promo_rank):
    if (to >> 4) == promo_rank:
        base = (frm | (to << 7) | (p << 14) | ((cap or 0) << 18))
        moves.append(base | (QUEEN << 22))
        moves.append(base | (ROOK << 22))
        moves.append(base | (BISHOP << 22))
        moves.append(base | (KNIGHT << 22))
    else:
        moves.append(frm | (to << 7) | (p << 14) | ((cap or 0) << 18))


def generate_moves(pos, captures_only=False):
    moves = []
    ap = moves.append
    us = pos.turn
    them = us ^ 1
    b = pos.board
    promo_rank = 7 if us == WHITE else 0
    start_rank = 1 if us == WHITE else 6
    direction = 16 if us == WHITE else -16
    for sq in range(120):
        if sq & 0x88:
            continue
        p = b[sq]
        if not p or color_of(p) != us:
            continue
        t = p & 7
        if t == PAWN:
            one = sq + direction
            if ok(one) and not b[one]:
                if not captures_only:
                    _push_pawn(moves, sq, one, p, 0, promo_rank)
                    if (sq >> 4) == start_rank:
                        two = sq + direction * 2
                        if not b[two]:
                            ap(sq | (two << 7) | (p << 14) | (FLAG_DPUSH << 26))
                elif (one >> 4) == promo_rank:
                    _push_pawn(moves, sq, one, p, 0, promo_rank)
            for dd in (direction - 1, direction + 1):
                to = sq + dd
                if not ok(to):
                    continue
                q = b[to]
                if q and (q >> 3) == them:
                    _push_pawn(moves, sq, to, p, q, promo_rank)
                elif not q and to == pos.ep:
                    ap(sq | (to << 7) | (p << 14) | (piece(them, PAWN) << 18) | (FLAG_EP << 26))
        elif t == KNIGHT or t == KING:
            offs = KNIGHT_OFFS if t == KNIGHT else KING_OFFS
            for i in range(8):
                to = sq + offs[i]
                if not ok(to):
                    continue
                q = b[to]
                if q and (q >> 3) == us:
                    continue
                if captures_only and not q:
                    continue
                ap(sq | (to << 7) | (p << 14) | ((q or 0) << 18))
            if t == KING and not captures_only:
                _gen_castles(pos, moves)
        else:
            if t == BISHOP:
                dirs = BISHOP_DIRS
            elif t == ROOK:
                dirs = ROOK_DIRS
            else:
                dirs = KING_OFFS
            for d in dirs:
                to = sq + d
                while ok(to):
                    q = b[to]
                    if q:
                        if (q >> 3) == them:
                            ap(sq | (to << 7) | (p << 14) | (q << 18))
                        break
                    if not captures_only:
                        ap(sq | (to << 7) | (p << 14))
                    to += d
    return moves


def make_move(pos, m):
    frm = m & 127
    to = (m >> 7) & 127
    pc = (m >> 14) & 15
    cap = (m >> 18) & 15
    promo_t = (m >> 22) & 15
    fl = m >> 26
    us = pos.turn
    them = us ^ 1
    pos.hist.append((m, cap, pos.castling, pos.ep, pos.halfmove))
    board = pos.board
    board[to] = piece(us, promo_t) if promo_t else pc
    board[frm] = 0
    if fl & FLAG_EP:
        board[to + (-16 if us == WHITE else 16)] = 0
    elif fl & FLAG_CASTLE:
        if to > frm:
            board[to - 1] = board[to + 1]
            board[to + 1] = 0
        else:
            board[to + 1] = board[to - 2]
            board[to - 2] = 0
    if (pc & 7) == KING:
        pos.kings[us] = to
    pos.castling &= CASTLE_MASK[frm] & CASTLE_MASK[to]
    pos.ep = frm + (16 if us == WHITE else -16) if (fl & FLAG_DPUSH) else -1
    pos.halfmove = 0 if ((pc & 7) == PAWN or cap) else pos.halfmove + 1
    if us == BLACK:
        pos.fullmove += 1
    pos.turn = them


def unmake_move(pos):
    m, cap, castling, ep, halfmove = pos.hist.pop()
    pos.turn ^= 1
    us = pos.turn
    if us == BLACK:
        pos.fullmove -= 1
    frm = m & 127
    to = (m >> 7) & 127
    pc = (m >> 14) & 15
    fl = m >> 26
    board = pos.board
    board[frm] = pc
    board[to] = 0
    if fl & FLAG_EP:
        board[to + (-16 if us == WHITE else 16)] = piece(us ^ 1, PAWN)
    elif cap:
        board[to] = cap
    if fl & FLAG_CASTLE:
        if to > frm:
            board[to + 1] = board[to - 1]
            board[to - 1] = 0
        else:
            board[to - 2] = board[to + 1]
            board[to + 1] = 0
    if (pc & 7) == KING:
        pos.kings[us] = frm
    pos.castling = castling
    pos.ep = ep
    pos.halfmove = halfmove


def legal_moves(pos):
    out = []
    ms = generate_moves(pos, False)
    for m in ms:
        make_move(pos, m)
        if not in_check(pos, pos.turn ^ 1):
            out.append(m)
        unmake_move(pos)
    return out


def pos_key(pos):
    b = pos.board
    chars = []
    ap = chars.append
    for r in range(7, -1, -1):
        base = r * 16
        for f in range(8):
            p = b[base + f]
            ap(CHAR_OF[p] if p else ".")
    return "".join(chars) + "|%d|%d|%d" % (pos.turn, pos.castling, pos.ep >> 4)


def insufficient_material(pos):
    minors = []
    b = pos.board
    for sq in range(120):
        if sq & 0x88:
            continue
        p = b[sq]
        if not p:
            continue
        t = p & 7
        if t == KING:
            continue
        if t == PAWN or t == ROOK or t == QUEEN:
            return False
        minors.append((((sq >> 4) + (sq & 7)) & 1) == 1)
    if not minors:
        return True
    if len(minors) == 1:
        return True
    first = minors[0]
    return all(d == first for d in minors)


def game_status(pos, keys=None, rep_count=2):
    moves = legal_moves(pos)
    if not moves:
        if in_check(pos, pos.turn):
            return {"over": True, "result": "0-1" if pos.turn == WHITE else "1-0",
                    "reason": "checkmate", "moves": moves}
        return {"over": True, "result": "1/2-1/2", "reason": "stalemate", "moves": moves}
    if insufficient_material(pos):
        return {"over": True, "result": "1/2-1/2", "reason": "insufficient material", "moves": moves}
    if pos.halfmove >= 100:
        return {"over": True, "result": "1/2-1/2", "reason": "50-move rule", "moves": moves}
    if keys:
        k = pos_key(pos)
        count = 0
        for kk in keys:
            if kk == k:
                count += 1
        if count >= rep_count:
            return {"over": True, "result": "1/2-1/2", "reason": "repetition", "moves": moves}
    return {"over": False, "result": None, "reason": None, "moves": moves}


def san(pos, m, legal=None):
    if legal is None:
        legal = legal_moves(pos)
    frm = m & 127
    to = (m >> 7) & 127
    fl = m >> 26
    if fl & FLAG_CASTLE:
        s = "O-O" if to > frm else "O-O-O"
    else:
        pc = (m >> 14) & 15
        t = pc & 7
        is_cap = ((m >> 18) & 15) != 0 or (fl & FLAG_EP) != 0
        if t == PAWN:
            s = (FILES[frm & 7] + "x" + sq_name(to)) if is_cap else sq_name(to)
            pr = (m >> 22) & 15
            if pr:
                s += "=" + " PNBRQK"[pr]
        else:
            s = " PNBRQK"[t]
            others = []
            for x in legal:
                if x != m and ((x >> 14) & 15) == pc and (((x >> 7) & 127) == to) and (x & 127) != frm:
                    others.append(x)
            if others:
                same_file = any((o & 7) == (frm & 7) for o in others)
                same_rank = any((o >> 4) == (frm >> 4) for o in others)
                if not same_file:
                    s += FILES[frm & 7]
                elif not same_rank:
                    s += str(((frm >> 4) & 7) + 1)
                else:
                    s += sq_name(frm)
            if is_cap:
                s += "x"
            s += sq_name(to)
    make_move(pos, m)
    has_moves = bool(legal_moves(pos))
    if in_check(pos, pos.turn):
        s += "+" if has_moves else "#"
    unmake_move(pos)
    return s


def perft(pos, depth):
    if depth == 0:
        return 1
    ms = legal_moves(pos)
    if depth == 1:
        return len(ms)
    total = 0
    for m in ms:
        make_move(pos, m)
        total += perft(pos, depth - 1)
        unmake_move(pos)
    return total


def divide(pos, depth):
    lines = []
    total = 0
    for m in legal_moves(pos):
        make_move(pos, m)
        n = perft(pos, depth - 1)
        unmake_move(pos)
        total += n
        lines.append("%s%s: %d" % (sq_name(m & 127), sq_name((m >> 7) & 127), n))
    lines.append("total: %d" % total)
    return "\n".join(lines)
