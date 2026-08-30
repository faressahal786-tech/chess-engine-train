import chess

WHITE = chess.WHITE
BLACK = chess.BLACK
PAWN = chess.PAWN
KNIGHT = chess.KNIGHT
BISHOP = chess.BISHOP
ROOK = chess.ROOK
QUEEN = chess.QUEEN
KING = chess.KING

FLAG_EP, FLAG_CASTLE, FLAG_DPUSH = 1, 2, 4


def sq63_to_88(s):
    return ((s >> 3) << 4) | (s & 7)


def sq_88_to_63(sq):
    return ((sq >> 4) * 8) + (sq & 7)


def sq_name(sq63):
    return chess.square_name(sq63)


def parse_sq(name):
    return chess.parse_square(name)


def create_start():
    return chess.Board()


def set_fen(fen):
    return chess.Board(fen)


def to_fen(board):
    return board.fen()


def legal_moves(board):
    return list(board.legal_moves)


def perft(board, depth):
    if depth == 0:
        return 1
    if depth == 1:
        return board.legal_moves.count()
    total = 0
    for mv in board.legal_moves:
        board.push(mv)
        total += perft(board, depth - 1)
        board.pop()
    return total


def divide(board, depth):
    lines = []
    total = 0
    for mv in board.legal_moves:
        board.push(mv)
        n = perft(board, depth - 1)
        board.pop()
        total += n
        lines.append("%s: %d" % (mv.uci(), n))
    lines.append("total: %d" % total)
    return "\n".join(lines)


def mk_move(f88, t88, promo=0, capt=0, fl=0):
    return f88 | (t88 << 7) | ((capt or 0) << 18) | ((promo or 0) << 22) | ((fl or 0) << 26)


def m_from(m):
    return m & 127


def m_to(m):
    return (m >> 7) & 127


def m_capt(m):
    return (m >> 18) & 15


def m_promo(m):
    return (m >> 22) & 15


def m_flags(m):
    return (m >> 26) & 7


def move_to_int(move):
    return mk_move(sq63_to_88(move.from_square), sq63_to_88(move.to_square), move.promotion or 0)


def int_to_move(board, i):
    f63 = sq_88_to_63(i & 127)
    t63 = sq_88_to_63((i >> 7) & 127)
    pr = (i >> 22) & 15
    for mv in board.legal_moves:
        if mv.from_square == f63 and mv.to_square == t63 and (mv.promotion or 0) == pr:
            return mv
    return None


def pos_key(board):
    return " ".join(board.fen().split()[:4])
