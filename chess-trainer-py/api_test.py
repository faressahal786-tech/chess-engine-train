import http.client
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / "runtime" / "python.exe"
PORT = 8199
BASE = "http://127.0.0.1:%d" % PORT

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


def req(method, path, body=None, timeout=30):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    payload = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if payload else {}
    conn.request(method, path, body=payload, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, (json.loads(data) if data and resp.getheader("Content-Type", "").startswith("application/json") else data)


def main():
    env = dict(os.environ)
    proc = subprocess.Popen([str(PYTHON), str(ROOT / "server.py"), "--port", str(PORT)],
                            cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", env=env)
    try:
        ready = False
        for _ in range(50):
            time.sleep(0.2)
            try:
                status, _ = req("GET", "/api/state", timeout=5)
                if status == 200:
                    ready = True
                    break
            except OSError:
                continue
        check("server boots and answers /api/state", ready)
        if not ready:
            print(proc.stdout.read() if proc.poll() is not None else "(still running)")
            return

        status, html = req("GET", "/", timeout=10)
        check("GET / serves index.html", status == 200 and b"Chess Self-Play Trainer" in html)
        status, js = req("GET", "/js/app.js", timeout=10)
        check("GET /js/app.js served", status == 200 and b"requestThink" in js)
        status, css = req("GET", "/css/style.css", timeout=10)
        check("GET /css/style.css served", status == 200 and b"[hidden]" in css)

        status, brain = req("GET", "/api/brain", timeout=10)
        check("GET /api/brain returns brain", status == 200 and "params" in brain.get("brain", {}))

        scholar = "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
        h5 = (ord("h") - 97) + (4 * 16)
        f7 = (ord("f") - 97) + (6 * 16)
        t0 = time.time()
        status, think = req("POST", "/api/think",
                            {"fen": scholar, "depth": 3, "time_ms": 30000}, timeout=60)
        dt = time.time() - t0
        check("think finds Qxf7# (%.1fs)" % dt,
              status == 200 and think.get("ok") and think["from"] == h5 and think["to"] == f7,
              json.dumps(think)[:250])
        check("think reports pv_san", isinstance(think.get("pv_san"), list) and len(think["pv_san"]) >= 1,
              think.get("pv_san"))

        start_pos = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        status, think2 = req("POST", "/api/think", {"fen": start_pos, "depth": 2, "time_ms": 10000}, timeout=60)
        check("think on startpos ok", status == 200 and think2.get("ok") and think2.get("depth", 0) >= 1)

        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=120)
        conn.request("GET", "/api/train/stream")
        stream = conn.getresponse()
        check("SSE content type", stream.getheader("Content-Type", "").startswith("text/event-stream"))

        hello_line = stream.readline()
        check("SSE hello event first", hello_line.startswith(b"data: ") and b'"type": "hello"' in hello_line or b'"type":"hello"' in hello_line, hello_line[:120])

        status, _ = req("POST", "/api/train/start",
                        {"opts": {"depth": 1, "games_per_gen": 2, "max_plies": 40, "open_plies": 2}}, timeout=15)
        check("train start accepted", status == 200)

        saw_gen_done = False
        deadline = time.time() + 90
        while time.time() < deadline:
            line = stream.readline()
            if not line:
                break
            if line.startswith(b"data: "):
                try:
                    evt = json.loads(line[6:].decode("utf-8"))
                except ValueError:
                    continue
                if evt.get("type") == "genDone":
                    saw_gen_done = True
                    check("genDone carries stats", evt.get("stats", {}).get("games", 0) >= 2, json.dumps(evt)[:200])
                    break
        check("received genDone over SSE", saw_gen_done)

        status, _ = req("POST", "/api/train/pause", timeout=10)
        games_before = None
        status, state = req("GET", "/api/state", timeout=10)
        games_before = state["stats"]["games"]
        check("pause accepted", status == 200)
        time.sleep(1.5)
        status, state2 = req("GET", "/api/state", timeout=10)
        check("no progress while paused", state2["stats"]["games"] == games_before,
              "%s vs %s" % (games_before, state2["stats"]["games"]))
        status, _ = req("POST", "/api/train/stop", timeout=10)
        check("stop accepted", status == 200)

        stopped_seen = False
        brain_evt = None
        deadline = time.time() + 20
        while time.time() < deadline:
            line = stream.readline()
            if not line:
                break
            if line.startswith(b"data: "):
                try:
                    evt = json.loads(line[6:].decode("utf-8"))
                except ValueError:
                    continue
                if evt.get("type") == "stopped":
                    stopped_seen = True
                    break
                if evt.get("type") == "brain":
                    brain_evt = evt
        check("received stopped over SSE", stopped_seen)
        conn.close()

        status, brain_now = req("GET", "/api/brain", timeout=10)
        check("brain persisted file exists", (ROOT / "brains" / "brain.json").exists())
        status, res = req("POST", "/api/brain/load", {"brain": brain_now["brain"]}, timeout=10)
        check("brain load roundtrip", status == 200 and res.get("ok"))

        status, st = req("GET", "/api/selftest", timeout=180)
        lines = st.get("lines", [])
        check("self-test all pass", status == 200 and sum(1 for l in lines if l.startswith("[PASS]")) >= 5
              and not any(l.startswith("[FAIL]") for l in lines), "\n".join(lines))
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    print("\n%d passed, %d failed" % (passed, failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
