import json
import random
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import chess

from engine import lib_core as C
from engine import search as E
from engine import trainer as T

STATIC = ROOT / "static"
BRAIN_PATH = ROOT / "brains" / "brain.json"
PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else \
    int(__import__("os").environ.get("PORT", "8124"))

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def log(msg):
    try:
        print("[%s] %s" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


class App:
    def __init__(self):
        self.lock = threading.RLock()
        self.trainer_state = None
        self.running = False
        self.paused = False
        self.stop_requested = False
        self.opts = {}
        self.events = []
        self.event_seq = 0
        self.thread = None
        self.selftest_running = False

    def boot(self):
        brain = None
        if BRAIN_PATH.exists():
            try:
                brain = T.deserialize_brain(json.loads(BRAIN_PATH.read_text(encoding="utf-8")))
                log("loaded brain: gen %d" % brain["meta"].get("generation", 0))
            except Exception as e:
                log("brain load failed (%s), using defaults" % e)
        if brain is None:
            brain = T.default_brain()
        self.trainer_state = T.new_trainer_state(brain)
        self.save_brain()

    def emit(self, type_, **kw):
        with self.lock:
            self.event_seq += 1
            evt = {"type": type_, "seq": self.event_seq}
            evt.update(kw)
            self.events.append(evt)
            if len(self.events) > 2000:
                del self.events[:1000]

    def events_after(self, cursor):
        with self.lock:
            return [e for e in self.events if e["seq"] > cursor]

    def max_seq(self):
        with self.lock:
            return self.event_seq

    def snapshot(self):
        with self.lock:
            ts = self.trainer_state
            return {
                "brain": T.serialize_brain(ts["brain"]),
                "stats": dict(ts["stats"]),
                "running": self.running,
                "paused": self.paused,
            }

    def save_brain(self):
        try:
            BRAIN_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = BRAIN_PATH.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(T.serialize_brain(self.trainer_state["brain"])), encoding="utf-8")
            tmp.replace(BRAIN_PATH)
        except Exception as e:
            log("brain save failed: %s" % e)

    def start_training(self, opts):
        with self.lock:
            self.opts = opts or {}
            if self.running:
                if self.paused:
                    self.paused = False
                    self.emit("resumed")
                    log("training resumed")
                return {"ok": True, "already": True}
            self.stop_requested = False
            self.paused = False
            self.running = True
            seed = random.SystemRandom().randrange(0xFFFFFFFF)
            self.thread = threading.Thread(target=self._trainer_loop,
                                           args=(T.mulberry32(seed),), daemon=True)
            self.thread.start()
            self.emit("started")
            log("training started")
            return {"ok": True}

    def pause(self):
        with self.lock:
            if self.running:
                self.paused = True
                log("training paused")

    def resume(self):
        with self.lock:
            if self.running and self.paused:
                self.paused = False
                self.emit("resumed")
                log("training resumed")

    def stop(self):
        with self.lock:
            if self.running:
                self.stop_requested = True
                log("stop requested")

    def _trainer_loop(self, rng):
        try:
            while True:
                with self.lock:
                    if self.stop_requested:
                        break
                    paused = self.paused
                    opts = dict(self.opts)
                if paused:
                    time.sleep(0.15)
                    continue
                opts["rng"] = rng
                try:
                    res = T.evolve_once(self.trainer_state, opts,
                                        should_stop=lambda: self.stop_requested)
                except Exception:
                    log("trainer error:\n" + traceback.format_exc())
                    break
                if res["stopped_early"]:
                    break
                stats = dict(self.trainer_state["stats"])
                self.emit("genDone", improved=res["improved"], ch_pts=res["ch_pts"],
                          games=res["games"], ch_w=res["ch_w"], ch_l=res["ch_l"],
                          draws=res["draws"], avg_plies=res["avg_plies"], stats=stats)
                log("gen %-5d challenger %.1f/%d (%dW %dL %dD)%s total=%d" % (
                    stats["gen"], res["ch_pts"], res["games"], res["ch_w"], res["ch_l"],
                    res["draws"], " PROMOTED" if res["improved"] else "", stats["games"]))
                if res["improved"]:
                    self.save_brain()
                    self.emit("brain", brain=T.serialize_brain(self.trainer_state["brain"]))
                time.sleep(0.01)
        finally:
            with self.lock:
                was_running = self.running
                self.running = False
                self.paused = False
                self.stop_requested = False
            if was_running:
                self.save_brain()
                self.emit("stopped", brain=T.serialize_brain(self.trainer_state["brain"]),
                          stats=dict(self.trainer_state["stats"]))
                log("training stopped · saved")

    def load_brain(self, obj):
        brain = T.deserialize_brain(obj)
        with self.lock:
            self.trainer_state["brain"] = brain
        self.save_brain()
        self.emit("loaded", brain=T.serialize_brain(brain))
        log("brain loaded: gen %d" % brain["meta"].get("generation", 0))

    def reset_brain(self):
        self.load_brain(T.default_brain())

    def think(self, fen, depth, time_ms):
        pos = C.set_fen(fen)
        with self.lock:
            params = self.trainer_state["brain"]["params"]
        r = E.think(pos, params, max_depth=max(1, min(int(depth), 5)),
                    time_ms=int(time_ms))
        if r is None:
            return {"ok": False, "message": "no legal moves"}
        return {
            "ok": True,
            "from": C.m_from(r["move"]),
            "to": C.m_to(r["move"]),
            "promo": C.m_promo(r["move"]),
            "score": r["score"],
            "depth": r["depth"],
            "nodes": r["nodes"],
            "time_ms": r["time_ms"],
            "pv_san": E.pv_to_san(pos, r["pv"]),
        }

    def selftest(self):
        with self.lock:
            if self.selftest_running:
                return {"ok": False, "lines": ["self-test already running"]}
            self.selftest_running = True
        lines = []
        try:
            P = E.default_params()

            def t(name, fn):
                try:
                    ok = bool(fn())
                except Exception as e:
                    ok = False
                    name += " (%s)" % e
                lines.append("[PASS] " + name if ok else "[FAIL] " + name)

            t("perft startpos d1-d3 (20/400/8902)", lambda: (
                C.perft(C.create_start(), 1) == 20 and
                C.perft(C.create_start(), 2) == 400 and
                C.perft(C.create_start(), 3) == 8902))
            kiwi = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
            t("perft kiwipete d2 (2039)", lambda: C.perft(C.set_fen(kiwi), 2) == 2039)
            scholar = "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"

            def mate():
                p = C.set_fen(scholar)
                r = E.think(p, P, max_depth=3, time_ms=30000)
                return r and r.get("move_obj") is not None and r["move_obj"].uci() == "h5f7"
            t("search finds Qxf7#", mate)
            t("SAN castling O-O", lambda: self._san_oo())
            t("FEN roundtrip", lambda: C.to_fen(
                C.set_fen(C.to_fen(C.set_fen(kiwi)))) ==
                C.to_fen(C.set_fen(kiwi)))
            lines.append("self-test complete")
        finally:
            with self.lock:
                self.selftest_running = False
        return {"ok": True, "lines": lines}

    @staticmethod
    def _san_oo():
        b = C.set_fen("r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1")
        mv = chess.Move.from_uci("e1g1")
        return mv in b.legal_moves and b.san(mv) == "O-O"


APP = App()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ChessTrainerPy/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, obj, status=200):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 10 * 1024 * 1024:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path == "/" or path == "/index.html":
                return self._static_file("index.html")
            if path.startswith("/css/") or path.startswith("/js/") or path.startswith("/img/"):
                rel = path.lstrip("/")
                return self._static_file(rel)
            if path == "/api/brain":
                snap = APP.snapshot()
                return self._send_json({"brain": snap["brain"]})
            if path == "/api/state":
                return self._send_json(APP.snapshot())
            if path == "/api/train/stream":
                return self._handle_stream()
            if path == "/api/selftest":
                return self._send_json(APP.selftest())
            return self._send_json({"error": "not found"}, status=404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True
        except Exception:
            traceback.print_exc()
            try:
                self._send_json({"error": "internal error"}, status=500)
            except Exception:
                self.close_connection = True

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            body = self._read_json()
            if path == "/api/think":
                res = APP.think(body.get("fen", ""), body.get("depth", 2),
                                body.get("time_ms", 2000))
                return self._send_json(res)
            if path == "/api/train/start":
                opts = body.get("opts") or {}
                norm = {
                    "depth": max(1, min(int(opts.get("depth", 2)), 4)),
                    "games_per_gen": max(2, min(int(opts.get("games_per_gen", 8)), 40)),
                    "max_plies": max(30, min(int(opts.get("max_plies", 140)), 400)),
                    "open_plies": max(0, min(int(opts.get("open_plies", 4)), 12)),
                    "strength": float(opts.get("strength", 1.0)),
                }
                return self._send_json(APP.start_training(norm))
            if path == "/api/train/pause":
                APP.pause()
                return self._send_json({"ok": True})
            if path == "/api/train/resume":
                APP.resume()
                return self._send_json({"ok": True})
            if path == "/api/train/stop":
                APP.stop()
                return self._send_json({"ok": True})
            if path == "/api/brain/load":
                APP.load_brain(body.get("brain"))
                return self._send_json({"ok": True})
            if path == "/api/brain/reset":
                APP.reset_brain()
                return self._send_json({"ok": True})
            return self._send_json({"error": "not found"}, status=404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True
        except Exception:
            traceback.print_exc()
            try:
                self._send_json({"error": "bad request: " + str(Exception)}, status=400)
            except Exception:
                self.close_connection = True

    def _static_file(self, rel):
        target = (STATIC / rel).resolve()
        if not str(target).startswith(str(STATIC.resolve())) or not target.is_file():
            return self._send_json({"error": "not found"}, status=404)
        data = target.read_bytes()
        ext = target.suffix.lower()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _handle_stream(self):
        query = self.path.split("?", 1)
        cursor = 0
        if len(query) == 2 and "cursor=" in query[1]:
            try:
                cursor = int(query[1].split("cursor=")[1].split("&")[0])
            except ValueError:
                cursor = 0
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def send_evt(evt):
            data = json.dumps(evt, ensure_ascii=False)
            self.wfile.write(("data: " + data + "\n\n").encode("utf-8"))

        try:
            send_evt({"type": "hello", **APP.snapshot()})
            self.wfile.flush()
            last_beat = time.time()
            while not self.close_connection:
                pending = APP.events_after(cursor)
                for evt in pending:
                    cursor = max(cursor, evt["seq"])
                    send_evt(evt)
                if pending:
                    self.wfile.flush()
                elif time.time() - last_beat > 12:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    last_beat = time.time()
                time.sleep(0.25)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            self.close_connection = True
        except Exception:
            traceback.print_exc()
            self.close_connection = True


def main():
    APP.boot()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.daemon_threads = True
    log("Chess Trainer (python) running at http://localhost:%d" % PORT)
    log("Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("shutting down")
        APP.stop()
        server.server_close()


if __name__ == "__main__":
    main()
