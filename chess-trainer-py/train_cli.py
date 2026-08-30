import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import trainer as T

ROOT = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description="headless self-play chess trainer")
    ap.add_argument("--minutes", type=float, default=5)
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--games-per-gen", type=int, default=6)
    ap.add_argument("--max-plies", type=int, default=120)
    ap.add_argument("--open-plies", type=int, default=4)
    ap.add_argument("--mutation", type=float, default=1.0)
    ap.add_argument("--seed", type=lambda v: int(v, 0), default=None)
    ap.add_argument("--out", default="brains/brain.json")
    args = ap.parse_args()

    out_path = (ROOT / args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    brain = None
    if out_path.exists():
        try:
            brain = T.deserialize_brain(json.loads(out_path.read_text(encoding="utf-8")))
            print("resuming from %s (gen %d)" % (out_path.name, brain["meta"].get("generation", 0)))
        except Exception as e:
            print("could not resume (%s); starting fresh" % e)
    if brain is None:
        brain = T.default_brain()

    state = T.new_trainer_state(brain)
    seed = args.seed if args.seed is not None else int(time.time() * 1000) & 0xFFFFFFFF
    rng = T.mulberry32(seed)
    deadline = time.time() + args.minutes * 60

    print("self-play training: %.1f min · depth %d · %d games/gen · out %s"
          % (args.minutes, args.depth, args.games_per_gen, out_path))
    print("press Ctrl+C to stop early (progress saved on every improvement)")

    def save():
        tmp = out_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(T.serialize_brain(state["brain"])), encoding="utf-8")
        tmp.replace(out_path)

    t0 = time.time()
    gens = 0
    try:
        while time.time() < deadline:
            res = T.evolve_once(state, {
                "depth": args.depth,
                "games_per_gen": args.games_per_gen,
                "max_plies": args.max_plies,
                "open_plies": args.open_plies,
                "strength": args.mutation,
                "rng": rng,
            })
            gens += 1
            s = state["stats"]
            elapsed_min = (time.time() - t0) / 60
            rate = s["games"] / max(0.01, elapsed_min)
            print("gen %-5d challenger %.1f/%d (%dW %dL %dD)%s total %d games · %.1f/min · %.1f min elapsed"
                  % (s["gen"], res["ch_pts"], res["games"], res["ch_w"], res["ch_l"], res["draws"],
                     " PROMOTED" if res["improved"] else "", s["games"], rate, elapsed_min))
            if res["improved"]:
                save()
    except KeyboardInterrupt:
        print("\nstopping…")

    save()
    s = state["stats"]
    print("done: gen %d · %d games trained · %d improvements" %
          (s["gen"], s["games"], s["improvements"]))
    print("brain saved to %s" % out_path)


if __name__ == "__main__":
    main()
