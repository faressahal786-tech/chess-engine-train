import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import chess

from engine import lib_core as C
from engine import search as E
from engine import trainer as T

passed = 0
failed = 0


def check(name, cond, extra=None):
    global passed, failed
    if cond:
        passed += 1
        print("  ok  " + name)
    else:
        failed += 1
        print("FAIL  " + name + (("  -> " + str(extra)[:300]) if extra is not None else ""))


PERFT_SUITE = [
    ("startpos", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", [20, 400, 8902]),
    ("kiwipete", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", [48, 2039, 97862]),
    ("pos3", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", [14, 191, 2812, 43238]),
    ("pos4", "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", [6, 264, 9467]),
    ("pos5", "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", [44, 1486, 62379]),
    ("pos6", "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10", [46, 2079, 89890]),
]


def san_of(fen, uci):
    board = C.set_fen(fen)
    mv = chess.Move.from_uci(uci)
    if mv not in board.legal_moves:
        return None
    return board.san(mv)


def main():
    print("[perft]")
    for name, fen, counts in PERFT_SUITE:
        pos = C.set_fen(fen)
        for d, expected in enumerate(counts):
            t0 = time.perf_counter()
            n = C.perft(pos, d + 1)
            dt = time.perf_counter() - t0
            check("%s depth %d (%d)" % (name, d + 1, n), n == expected,
                  "expected %d got %d" % (expected, n))

    print("\n[perft extra]")
    n = C.perft(C.create_start(), 4)
    check("startpos depth 4 (%d)" % n, n == 197281)

    print("\n[fen roundtrip]")
    for name, fen, _ in PERFT_SUITE:
        out = C.to_fen(C.set_fen(fen))
        check(name, C.to_fen(C.set_fen(out)) == out, out)

    print("\n[game status]")
    st = C.set_fen("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    outcome = st.outcome(claim_draw=False)
    check("stalemate detected", outcome is not None and outcome.termination == chess.Termination.STALEMATE)
    fm = C.set_fen("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")
    outcome = fm.outcome(claim_draw=False)
    check("fools mate detected",
          outcome is not None and outcome.termination == chess.Termination.CHECKMATE and outcome.winner == chess.BLACK)
    check("K vs K insufficient", C.set_fen("8/8/4k3/8/8/3K4/8/8 w - - 0 1").is_insufficient_material())
    check("KN vs K insufficient", C.set_fen("8/8/4k3/8/8/3K4/5N2/8 w - - 0 1").is_insufficient_material())
    check("KP vs K sufficient", not C.set_fen("8/8/4k3/8/8/3K4/4P3/8 w - - 0 1").is_insufficient_material())

    print("\n[san]")
    check("pawn push SAN", san_of(C.to_fen(C.create_start()), "e2e4") == "e4")
    check("knight SAN", san_of(C.to_fen(C.create_start()), "g1f3") == "Nf3")
    check("disambiguation Nbd2", san_of("k7/8/8/8/8/8/8/KN3N2 w - - 0 1", "b1d2") == "Nbd2")
    castle_fen = "r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1"
    check("O-O san", san_of(castle_fen, "e1g1") == "O-O")
    check("O-O-O san", san_of(castle_fen, "e1c1") == "O-O-O")
    check("promotion bxa8=Q", san_of("rn2k3/1P6/8/8/8/8/8/4K3 w q - 0 1", "b7a8q") == "bxa8=Q")
    check("promotion b8=Q+", san_of("4k3/1P6/8/8/8/8/8/4K3 w - - 0 1", "b7b8q") == "b8=Q+")
    ep_fen = "rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3"
    check("en passant exf6", san_of(ep_fen, "e5f6") == "exf6")
    scholar = "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
    check("Qxf7# san", san_of(scholar, "h5f7") == "Qxf7#")

    print("\n[search]")
    P = E.default_params()
    h5_88 = (4 << 4) | 7
    f7_88 = (6 << 4) | 5
    pos = C.set_fen(scholar)
    r = E.think(pos, P, max_depth=3, time_ms=20000)
    check("finds Qxf7#", r and C.m_from(r["move"]) == h5_88 and C.m_to(r["move"]) == f7_88,
          str(r)[:250])
    check("mate score large", abs(r["score"]) > E.MATE - 100, str(r["score"]))
    back_rank = C.set_fen("k7/8/1K6/8/8/8/8/7R w - - 0 1")
    rb = E.think(back_rank, P, max_depth=2, time_ms=10000)
    h8_88 = (7 << 4) | 7
    check("back-rank mate found",
          rb and C.m_to(rb["move"]) == h8_88 and abs(rb["score"]) > E.MATE - 100)
    pos2 = C.create_start()
    before = C.to_fen(pos2)
    E.evaluate(pos2, P)
    check("evaluate does not mutate position", C.to_fen(pos2) == before)
    t0 = time.perf_counter()
    rs = E.think(C.create_start(), P, max_depth=3, time_ms=60000)
    dt = time.perf_counter() - t0
    nps = rs["nodes"] / max(dt, 1e-9)
    legal = list(C.create_start().legal_moves)
    mv_back = C.int_to_move(C.create_start(), rs["move"])
    check("start search returns legal move", mv_back in legal, rs["move"])
    print("  info  bench: depth %s · %d nodes · %.1fk nps" % (rs["depth"], rs["nodes"], nps / 1000))
    pv_san = E.pv_to_san(C.create_start(), rs["pv"])
    check("pv_to_san produces sans", isinstance(pv_san, list) and len(pv_san) >= 1, str(pv_san))

    print("\n[trainer]")
    rng = T.mulberry32(42)
    brain = {"version": 1, "meta": {"generation": 0, "record": {"w": 0, "l": 0, "d": 0}},
             "params": E.default_params()}
    state = T.new_trainer_state(brain)
    res = T.evolve_once(state, {"games_per_gen": 2, "depth": 1, "max_plies": 60, "open_plies": 2, "rng": rng})
    check("evolve_once completes", bool(res) and isinstance(res["ch_pts"], float), str(res))
    check("games counted", state["stats"]["games"] == 2, str(state["stats"]))
    ser = T.serialize_brain(state["brain"])
    back = T.deserialize_brain(json.loads(json.dumps(ser)))
    check("brain JSON roundtrip", T.serialize_brain(back)["params"]["val"] == ser["params"]["val"])
    mutated = T.mutate_params(state["brain"]["params"], rng, 1.0)
    in_range = all(20 <= mutated["val"][k] <= 1500 for k in ("p", "n", "b", "r", "q"))
    check("mutation keeps values sane", in_range, str(mutated["val"]))
    finite = all(isinstance(v, (int, float)) for side in ("pstW", "pstB")
                 for k in E.TABLE_KEYS for v in mutated[side][k])
    check("mutation produces finite PSTs", finite)

    print("\n%d passed, %d failed" % (passed, failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
