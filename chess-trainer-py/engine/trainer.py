import math
import random

import chess

from . import search as E


def mulberry32(seed):
    state = seed & 0xFFFFFFFF

    def rng():
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        t = state
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t = (((t + ((t ^ (t >> 7)) * (t | 61) & 0xFFFFFFFF)) & 0xFFFFFFFF) ^ t) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0

    return rng


def gauss(rng):
    u = 0.0
    v = 0.0
    while u == 0.0:
        u = rng()
    while v == 0.0:
        v = rng()
    return math.sqrt(-2.0 * math.log(u)) * math.cos(2.0 * math.pi * v)


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def clone_params(P):
    out = {"val": dict(P["val"]),
           "pstW": {k: list(P["pstW"][k]) for k in E.TABLE_KEYS},
           "pstB": {k: list(P["pstB"][k]) for k in E.TABLE_KEYS}}
    for k in E.SCALAR_NAMES:
        out[k] = P[k]
    return out


SCALAR_SPEC = {
    "bishopPair": (6, 0, 90),
    "doubled": (4, 0, 45),
    "isolated": (4, 0, 45),
    "passed": (5, 0, 90),
    "rookOpen": (5, 0, 70),
    "rookHalf": (3, 0, 40),
    "kingShield": (3, -10, 35),
    "tempo": (2, -8, 30),
}

VAL_RANGE = {"p": (50, 260), "n": (180, 520), "b": (180, 540), "r": (350, 800), "q": (600, 1300)}
VAL_SIGMA = {"p": 14.0, "n": 20.0, "b": 20.0, "r": 20.0, "q": 20.0}


def mutate_params(base, rng, strength=1.0):
    P = clone_params(base)
    for k in ("p", "n", "b", "r", "q"):
        lo, hi = VAL_RANGE[k]
        P["val"][k] = clamp(P["val"][k] + gauss(rng) * VAL_SIGMA[k] * strength, lo, hi)
    for side in ("pstW", "pstB"):
        for k in E.TABLE_KEYS:
            arr = P[side][k]
            for i in range(128):
                if not (i & 0x88):
                    d = gauss(rng) * (7.0 * strength)
                    if rng() < 0.02:
                        d += gauss(rng) * 26.0 * strength
                    arr[i] = clamp(arr[i] + d, -140, 140)
    for k, (sigma, lo, hi) in SCALAR_SPEC.items():
        P[k] = clamp(P[k] + gauss(rng) * sigma * strength, lo, hi)
    return P


PIECE_SIMPLE_VALUE = {chess.PAWN: 100, chess.KNIGHT: 320,
                      chess.BISHOP: 330, chess.ROOK: 500, chess.QUEEN: 900}


def material_diff(board):
    diff = 0
    for piece in board.piece_map().values():
        pt = piece.piece_type
        if pt == chess.KING:
            continue
        v = PIECE_SIMPLE_VALUE[pt]
        diff += v if piece.color == chess.WHITE else -v
    return diff


_TERMINATION_NAMES = {
    chess.Termination.CHECKMATE: "checkmate",
    chess.Termination.STALEMATE: "stalemate",
    chess.Termination.INSUFFICIENT_MATERIAL: "insufficient material",
    chess.Termination.SEVENTYFIVE_MOVES: "75-move rule",
    chess.Termination.FIVEFOLD_REPETITION: "repetition",
    chess.Termination.FIFTY_MOVES: "50-move rule",
    chess.Termination.THREEFOLD_REPETITION: "repetition",
}


def play_game(white_params, black_params, depth=2, max_plies=160, open_plies=4,
              time_ms_per_move=0, rng=None, on_move=None):
    if rng is None:
        rng = mulberry32(random.randrange(0xFFFFFFFF))
    board = chess.Board()
    plies = 0
    result = None
    reason = None
    while True:
        outcome = board.outcome(claim_draw=True)
        if outcome is not None:
            if outcome.winner is None:
                result = "d"
            else:
                result = "w" if outcome.winner == chess.WHITE else "b"
            reason = _TERMINATION_NAMES.get(outcome.termination, str(outcome.termination))
            break
        if plies >= max_plies:
            d = material_diff(board)
            if abs(d) >= 250:
                result = "w" if d > 0 else "b"
                reason = "adjudicated"
            else:
                result = "d"
                reason = "ply limit"
            break
        params = white_params if board.turn == chess.WHITE else black_params
        move = None
        if plies < open_plies:
            legal = list(board.legal_moves)
            move = legal[int(rng() * len(legal)) % len(legal)]
            san_str = board.san(move) if on_move is not None and plies < 12 else None
        else:
            r = E.think(board, params, max_depth=depth, time_ms=time_ms_per_move)
            move = (r["move_obj"] if r and r.get("move_obj")
                    else next(iter(board.legal_moves)))
            san_str = None
        if on_move is not None:
            if san_str is None:
                try:
                    san_str = board.san(move)
                except Exception:
                    san_str = move.uci()
            if plies < 12 or plies % 20 == 0:
                on_move(san_str, plies)
        board.push(move)
        plies += 1
    return {"result": result, "reason": reason, "plies": plies}


def new_trainer_state(start_brain):
    return {
        "brain": start_brain,
        "stats": {"gen": start_brain.get("meta", {}).get("generation", 0),
                  "games": 0, "w": 0, "l": 0, "d": 0, "improvements": 0,
                  "last_ch_pts": 0, "last_games": 0, "total_plies": 0},
    }


def evolve_once(state, opts=None, should_stop=None):
    opts = opts or {}
    games = opts.get("games_per_gen", 8)
    depth = opts.get("depth", 2)
    max_plies = opts.get("max_plies", 160)
    open_plies = opts.get("open_plies", 4)
    time_ms = opts.get("time_ms_per_move", 0)
    strength = opts.get("strength", 1.0)

    champ_meta = state["brain"]["meta"]
    challenger = mutate_params(state["brain"]["params"],
                               opts.get("rng") or mulberry32(random.randrange(0xFFFFFFFF)),
                               strength)
    ch_pts = 0.0
    ch_w = ch_l = draws = 0
    plies_sum = 0
    stopped_early = False
    for g in range(games):
        if should_stop is not None and should_stop():
            stopped_early = True
            break
        challenger_white = g % 2 == 0
        res = play_game(
            white_params=challenger if challenger_white else state["brain"]["params"],
            black_params=state["brain"]["params"] if challenger_white else challenger,
            depth=depth, max_plies=max_plies, open_plies=open_plies,
            time_ms_per_move=time_ms,
            rng=mulberry32(int(opts["rng"]() * 0xFFFFFFFF)) if opts.get("rng") else None,
        )
        plies_sum += res["plies"]
        if res["result"] == "d":
            draws += 1
            ch_pts += 0.5
        elif (res["result"] == "w") == challenger_white:
            ch_w += 1
            ch_pts += 1
        else:
            ch_l += 1

    games_played = ch_w + ch_l + draws
    stats = state["stats"]
    stats["games"] += games_played
    stats["total_plies"] += plies_sum
    stats["last_ch_pts"] = ch_pts
    stats["last_games"] = games_played
    improved = False
    accepted = (not stopped_early) and games_played > 0 and ch_pts > games_played / 2.0
    if accepted:
        improved = True
        stats["improvements"] += 1
        rec = dict(champ_meta.get("record") or {"w": 0, "l": 0, "d": 0})
        rec["w"] += ch_w
        rec["l"] += ch_l
        rec["d"] += draws
        meta = {"generation": champ_meta.get("generation", 0) + 1,
                "bornAtGame": stats["games"],
                "record": rec}
        state["brain"] = {"version": 1, "meta": meta, "params": challenger}
        stats["gen"] = meta["generation"]
    else:
        rec = champ_meta.setdefault("record", {"w": 0, "l": 0, "d": 0})
        rec["w"] += ch_l
        rec["l"] += ch_w
        rec["d"] += draws
    avg_plies = round(plies_sum / games_played) if games_played else 0
    return {"improved": improved, "ch_pts": ch_pts, "games": games_played,
            "ch_w": ch_w, "ch_l": ch_l, "draws": draws,
            "avg_plies": avg_plies, "stopped_early": stopped_early}


def default_brain():
    return {"version": 1,
            "meta": {"generation": 0, "bornAtGame": 0, "record": {"w": 0, "l": 0, "d": 0}},
            "params": E.default_params()}


def serialize_brain(brain):
    meta = brain.get("meta")
    if not meta:
        meta = {"generation": brain.get("generation", 0),
                "record": brain.get("record", {"w": 0, "l": 0, "d": 0})}
    return {"version": 1, "meta": meta, "params": E.params_to_plain(brain["params"])}


def deserialize_brain(obj):
    if obj is None:
        raise ValueError("empty brain")
    src = obj
    meta = src.get("meta")
    if not meta:
        meta = {"generation": src.get("generation", 0),
                "record": src.get("record", {"w": 0, "l": 0, "d": 0})}
    return {"version": 1, "meta": meta, "params": E.params_from_plain(src.get("params"))}
