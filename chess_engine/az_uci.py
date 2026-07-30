"""UCI adapter for AlphaZero chess engine. Use with En Croissant or any UCI GUI."""
import sys, os, time, chess, torch
sys.path.insert(0, os.path.dirname(__file__))
import az_multithreaded as az

def find_checkpoint(checkpoint_dir="checkpoints"):
    if not os.path.exists(checkpoint_dir):
        return None
    ckpts = [f for f in os.listdir(checkpoint_dir) if f.endswith('.pt')]
    if not ckpts:
        return None
    best = [f for f in ckpts if f.startswith('best')]
    return os.path.join(checkpoint_dir, best[0] if best else sorted(ckpts)[-1])

def main():
    cfg = az.CFG
    cfg.use_opening_book = False
    cfg.mixed_precision = False

    ckpt_path = find_checkpoint()
    if ckpt_path is None:
        print(f'No checkpoint found in {cfg.checkpoint_dir}')
        sys.exit(1)

    model = az.AZNet(cfg).to(cfg.device)
    model.eval()
    sd = torch.load(ckpt_path, map_location=cfg.device, weights_only=False)
    if 'model_state_dict' in sd:
        model.load_state_dict(sd['model_state_dict'])
    else:
        model.load_state_dict(sd)
    print(f'Loaded {ckpt_path}', file=sys.stderr, flush=True)

    board = chess.Board()
    ponder = False
    info_out = lambda msg: print(f'info {msg}', flush=True)

    print('id name AlphaZero', flush=True)
    print('id author OpenCode', flush=True)
    print('option name NumSimulations type spin default 100 min 10 max 1600', flush=True)
    print('uciok', flush=True)

    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()

        if line == 'uci':
            print('id name AlphaZero', flush=True)
            print('id author OpenCode', flush=True)
            print('option name NumSimulations type spin default 100 min 10 max 1600', flush=True)
            print('uciok', flush=True)

        elif line == 'isready':
            print('readyok', flush=True)

        elif line == 'ucinewgame':
            board = chess.Board()

        elif line.startswith('position'):
            parts = line.split()
            if 'startpos' in parts:
                board = chess.Board()
                idx = parts.index('startpos') + 1
            elif 'fen' in parts:
                idx = parts.index('fen') + 1
                fen_parts = []
                while idx < len(parts) and parts[idx] != 'moves':
                    fen_parts.append(parts[idx]); idx += 1
                board = chess.Board(' '.join(fen_parts))
            else:
                continue
            if 'moves' in parts:
                move_idx = parts.index('moves') + 1
                for m_str in parts[move_idx:]:
                    try: board.push_uci(m_str)
                    except: break

        elif line.startswith('go'):
            if board.is_game_over():
                print('bestmove 0000', flush=True)
                continue
            args = line.split()
            movetime = None
            wtime = btime = winc = binc = None
            for i, a in enumerate(args):
                if a == 'movetime' and i + 1 < len(args):
                    movetime = int(args[i + 1])
                elif a == 'wtime' and i + 1 < len(args):
                    wtime = int(args[i + 1])
                elif a == 'btime' and i + 1 < len(args):
                    btime = int(args[i + 1])
                elif a == 'winc' and i + 1 < len(args):
                    winc = int(args[i + 1])
                elif a == 'binc' and i + 1 < len(args):
                    binc = int(args[i + 1])

            n_sims = cfg.num_simulations
            if movetime is not None and movetime > 0:
                n_sims = max(10, int(movetime / 3))
            elif wtime is not None and btime is not None:
                side_time = wtime if board.turn == chess.WHITE else btime
                inc = winc if board.turn == chess.WHITE else binc
                target = max(100, side_time // 40 + inc)
                n_sims = max(10, int(target / 3))
            n_sims = min(n_sims, cfg.num_simulations)

            t0 = time.time()
            policy, root_val, info, _ = az.run_mcts(model, board, cfg, add_noise=False, temp=0.0, num_simulations=n_sims)
            elapsed = time.time() - t0
            visits = info['visits']
            move_data = []
            for m in board.legal_moves:
                idx = az.move_to_index(m, board)
                v = int(visits[idx])
                if v > 0: move_data.append((v, m))
            move_data.sort(key=lambda x: -x[0])
            total_v = sum(v for v, _ in move_data) or 1
            for v, m in move_data[:3]:
                try: san = board.san(m)
                except: san = str(m)
                info_out(f'string {san} {v/total_v*100:.0f}%')
            info_out(f'depth {n_sims} score cp {int(root_val*100)} time {int(elapsed*1000)} nodes {n_sims} pv {" ".join(mv.uci() for _, mv in move_data[:5])}')
            best = move_data[0][1].uci() if move_data else '0000'
            print(f'bestmove {best}', flush=True)

        elif line.startswith('setoption'):
            parts = line.split()
            if 'NumSimulations' in parts:
                for i, p in enumerate(parts):
                    if p == 'value' and i + 1 < len(parts):
                        cfg.num_simulations = max(10, min(1600, int(parts[i + 1])))

        elif line == 'ponderhit':
            pass
        elif line == 'quit':
            break

if __name__ == '__main__':
    main()
