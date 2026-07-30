# AlphaZero Chess Engine

A complete AlphaZero chess training system with parallel self-play workers, batched MCTS, tree reuse, and a live GUI for watching training games in real time.

## Features

- **Parallel MCTS** — batched leaf evaluation: all simulations traverse first, then one GPU call evaluates all leaves
- **Tree reuse** — search tree persists across moves (no rebuild from scratch each turn)
- **Parallel self-play** — N independent `multiprocessing.Process` workers, each with its own GPU model, weights synced via shared memory
- **Adaptive simulations** — reduces sims by 50-75% when game outcome is decided
- **Live GUI** — tkinter interface showing training games in real time as workers make moves
- **Data augmentation** — mirrors positions horizontally for 2x training data
- **Opening book** — 50 curated openings for varied training
- **Resignation detection** — 3 consecutive low-value moves before resigning
- **Async checkpointing** — saves models on a background thread
- **Worker health monitoring** — detects and restarts crashed workers
- **EMA** — exponential moving average of model weights for stable training
- **UCI adapter** — `az_uci.py` for use with UCI-compatible GUIs (En Croissant, etc.)

## Requirements

- Python 3.10+
- PyTorch 2.0+
- NVIDIA GPU with CUDA (recommended) or CPU
- Windows / Linux / macOS

## Quick Start

```bash
pip install -r chess_engine/requirements.txt

# Start GUI with training
python chess_engine/az_multithreaded.py --play

# Start training from CLI (headless)
python chess_engine/az_multithreaded.py
```

### GUI Controls

1. Click **Start Training** — workers begin self-play, games stream to the board live
2. Training auto-loops — restarts when target games are reached
3. Click **Stop Training** to break the loop
4. After training (or load a checkpoint), play against the AI using the board

### CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--play` | `False` | Launch GUI |
| `--num_selfplay_games` | `10000` | Total self-play games per training cycle |
| `--num_simulations` | `100` | MCTS simulations per move |
| `--num_workers` | `auto` | Parallel worker count (default: min(cpu_count-1, 4)) |
| `--batch_size` | `256` | Training batch size |
| `--use_history` | `7` | Past positions to stack (7 = 8 total planes) |
| `--device` | `cuda` | Training device (`cuda` or `cpu`) |

### Training With En Croissant

1. Add `chess_engine/az_uci.bat` as an engine in En Croissant's Engines tab
2. Configure `NumSimulations` option (default 100, higher = stronger)
3. Start a game — the engine loads the best checkpoint and uses MCTS

## Project Structure

```
chess_engine/
├── az_multithreaded.py   # Training + GUI (~1800 lines)
├── az_uci.py             # UCI protocol adapter
├── az_uci.bat            # Windows batch wrapper
├── requirements.txt      # Dependencies
├── checkpoints/          # Saved model checkpoints
└── logs/                 # Training metrics (TensorBoard + CSV)
commit.py                 # Git commit helper (no git CLI needed)
git_log.py                # Git log viewer
```

## Architecture

```
┌─────────────┐     Shared Memory (pickled weights)     ┌─────────────┐
│   Trainer   │ ◄────────────────────────────────────►  │  Worker 1   │
│  (GPU: M1)  │     mp.Queue (game data) ◄──────────    │  (GPU: M1)  │
│             │     mp.Queue (live moves) ────────►    │  Worker 2   │
│  Training   │                                          │  (GPU: M1)  │
│  loop +     │     stop_event (mp.Event)               │  Worker N   │
│  checkpoint │                                          └─────────────┘
└──────┬──────┘
       │ live_queue
       ▼
┌─────────────┐
│    GUI      │
│  (tkinter)  │
└─────────────┘
```

- **Workers** are independent `multiprocessing.Process` instances — true CPU parallelism with no GIL contention
- **Weight sync** via `multiprocessing.shared_memory` — trainer serializes model, workers deserialize
- **Live queue** streams `(game_id, move_uci, fen)` tuples — GUI displays them in real time
- **`num_workers`** auto-capped at 4 on single-GPU systems to prevent CUDA context exhaustion

## Model Specs

- **Input**: 120 planes (15 × 8 past positions), 8×8 spatial
- **Output**: 4672 policy logits + scalar value head
- **Body**: 6 residual blocks, 192 channels, SE blocks
- **Training**: AdamW, cosine LR schedule, gradient clipping, priority replay buffer
