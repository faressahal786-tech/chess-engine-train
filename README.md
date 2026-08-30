# Chess Trainer — choose your engine

Two complete, interchangeable builds of the same self-play trainer. Both evolve a brain by playing against itself and both ship the same browser GUI where you can play the evolved engine.

| Folder | Runtime | Speed | Notes |
|---|---|---|---|
| `chess-trainer/` | **Bun** (JS, pure stdlib) | **~1.3M nps, ~7× faster training** | Recommended for most users |
| `chess-trainer-py/` | Python 3.13.15 (bundled, + python-chess) | ~38k nps single-thread | Tinker in Python; same API |

Burned brains are at `brains/brain.json` (auto-created). The current bundle ships a gen-38 champion (704 games) in `chess-trainer`.

## Quick start — Bun (recommended)

```powershell
cd chess-trainer
bun install    # no deps, just validates
bun run-tests.js   # 53/53 should pass
bun serve.js       # http://localhost:8123
# or: bun train.js --minutes 30 --threads 0   # 0 = all cores
```

Alternative: double-click `chess-trainer/index.html` (single-threaded fallback).

## Quick start — Python

No install needed — the project vendors CPython 3.13.15 + `python-chess` in `chess-trainer-py/runtime/`:

```powershell
cd chess-trainer-py
.\run.bat              # opens browser + starts server on :8124
# or:
.\runtime\python.exe run_tests.py
.\runtime\python.exe train_cli.py --minutes 30
.\runtime\python.exe api_test.py
```

## How it works

1. **Engine** — 0x88 board, alpha-beta + quiescence + transposition table + null-move pruning, tapered PST + pawn-structure + bishop-pair + rook-open + king-shield eval. Every number in the eval is learnable.
2. **Trainer** — evolution loop: champion → Gaussian-mutated challenger → parallel games (all cores via Workers). Challenger promoted only if >50% score.
3. **GUI** — Play vs engine with undo/flip/hint, Train tab (live SSE), Brain tab (heatmaps, export/import/reset, self-test).

## Repository

```powershell
git clone <your-remote>
# bun build:  chess-trainer/
# py  build:  chess-trainer-py/
```

`cities-skylines1-agent-skill/` is an unrelated local skill — not part of the release.
