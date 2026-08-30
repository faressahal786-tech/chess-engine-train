# Chess Self-Play Trainer

Self-play chess trainer that evolves by playing against itself — with a browser GUI where you can play the evolved engine.

Burned brain at `chess-trainer/brains/brain.json` (auto-created). Current bundle ships a gen-38 champion (704 games).

## Quick start

```powershell
cd chess-trainer
bun install    # no deps, just validates
bun run-tests.js   # 53/53 should pass
bun serve.js       # http://localhost:8123
# or: bun train.js --minutes 30 --threads 0   # 0 = all cores
```

Alternative: double-click `chess-trainer/index.html` (single-threaded fallback).

## How it works

1. **Engine** — 0x88 board, alpha-beta + quiescence + transposition table + null-move pruning, tapered PST + pawn-structure + bishop-pair + rook-open + king-shield eval. Every number in the eval is learnable.
2. **Trainer** — evolution loop: champion → Gaussian-mutated challenger → parallel games across all cores via Workers. Challenger promoted only if >50% score.
3. **GUI** — Play vs engine with undo/flip/hint, Train tab (live SSE), Brain tab (heatmaps, export/import/reset, self-test).

Performance: **1.3M nps** single-thread, **~1,380 games/min** on 16 threads (7.3× vs single-thread).
