import sys
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.amp import autocast, GradScaler
import numpy as np
import random
import math
import time
import os
import threading
import queue
import multiprocessing as mp
from multiprocessing import shared_memory
import pickle
import struct
from collections import deque
from dataclasses import dataclass
from typing import Optional
import chess
import tkinter as tk
from tkinter import messagebox

# ==================== CONFIG ====================
@dataclass
class Config:
    num_blocks: int = 6
    num_channels: int = 192
    se_ratio: int = 4
    policy_dropout: float = 0.0
    value_dropout: float = 0.0
    use_history: int = 7
    
    num_simulations: int = 100
    c_puct_base: float = 19652
    c_puct_init: float = 1.25
    dirichlet_alpha: float = 0.3
    dirichlet_eps: float = 0.25
    
    max_moves: int = 512
    temperature_moves: int = 30
    temperature_init: float = 1.0
    temperature_final: float = 0.1
    temperature_decay: float = 0.95
    resign_threshold: float = -0.9
    resign_consecutive: int = 3     # consecutive low-value moves before resign
    resign_moves: int = 30
    augment_data: bool = True        # mirror positions horizontally for 2x training data
    
    batch_size: int = 256
    lr: float = 0.002
    weight_decay: float = 1e-4
    momentum: float = 0.9
    lr_min: float = 1e-5
    grad_clip: float = 1.0
    
    buffer_size: int = 100000
    priority_alpha: float = 0.6
    priority_beta: float = 0.4
    priority_beta_anneal: int = 50000
    priority_eps: float = 1e-6
    
    # 50/50 split config
    train_steps_per_game: int = 4      # 4 training steps per self-play game = ~50/50
    
    warmup_steps: int = 1000           # linear LR warmup steps
    lr_warmup_min: float = 0.0
    total_training_steps: int = 100000 # cosine T_max
    
    eval_baseline_games: int = 0       # 0 = skip baseline eval (costs ~1s/game)
    baseline_search_sims: int = 0      # 0 = heuristic-only, >0 = MCTS with random policy
    
    use_opening_book: bool = True      # start from opening book positions
    opening_book_moves: int = 8        # max moves from opening book

    ema_decay: float = 0.995           # model EMA decay (0 = disable)
    gradient_accumulation_steps: int = 1  # accumulate N batches per optimizer step
    log_csv: bool = True               # log metrics to CSV
    
    device: str = "cuda" if torch.cuda.is_available() else "cpu"
    mixed_precision: bool = True
    compile_model: bool = False       # auto-set: True on Linux, False on Windows
    compile_mode: str = "default"
    num_selfplay_games: int = 10000
    
    log_dir: str = "logs"
    checkpoint_dir: str = "checkpoints"
    save_interval: int = 100          # save every N training steps
    eval_interval: int = 5000         # evaluate every N training steps
    eval_games: int = 20
    keep_best_n: int = 5
    eval_batch_size: int = 16         # batch MCTS leaf NN evaluations
    num_workers: int = 0              # 0 = auto-detect (os.cpu_count() - 1)
    queue_max_size: int = 20          # max queued games per worker
    tensorboard: bool = True

CFG = Config()

# Shared between training loop and GUI
@dataclass
class TrainingStats:
    running: bool = False
    stop_requested: bool = False
    total_games: int = 0
    training_steps: int = 0
    buffer_size: int = 0
    queue_size: int = 0
    curr_queue_size: int = 0
    win_rate: float = 0.0
    avg_game_len: float = 0.0
    elapsed: float = 0.0
    sp_wins: int = 0
    sp_losses: int = 0
    sp_draws: int = 0
    sp_resigned: int = 0
    target_games: int = 10000
    log_lines: list = None
    error: str = ""
    last_moves: list = None
    last_start_fen: str = ""
    current_board_fen: str = ""
    live_queue: any = None
    def __post_init__(self):
        if self.log_lines is None: self.log_lines = []
        if self.last_moves is None: self.last_moves = []

# ==================== MOVE ENCODING ====================
QUEEN_DIRS = [(1,0),(1,1),(0,1),(-1,1),(-1,0),(-1,-1),(0,-1),(1,-1)]
KNIGHT_MOVES = [(2,1),(1,2),(-1,2),(-2,1),(-2,-1),(-1,-2),(1,-2),(2,-1)]
PROMO_TYPES = [chess.KNIGHT, chess.BISHOP, chess.ROOK]

MOVE_TO_INDEX = np.full((64, 64, 4), -1, dtype=np.int32)
INDEX_TO_MOVE = [None] * 4672

def _init_move_tables():
    for from_sq in range(64):
        fr, ff = divmod(from_sq, 8)
        for dir_idx, (dr, df) in enumerate(QUEEN_DIRS):
            for dist in range(1, 8):
                tr, tf = fr + dr * dist, ff + df * dist
                if 0 <= tr < 8 and 0 <= tf < 8:
                    to_sq = tr * 8 + tf
                    idx = from_sq * 73 + dir_idx * 7 + (dist - 1)
                    MOVE_TO_INDEX[from_sq, to_sq, 0] = idx
                    INDEX_TO_MOVE[idx] = (from_sq, to_sq, None)
        for k_idx, (dr, df) in enumerate(KNIGHT_MOVES):
            tr, tf = fr + dr, ff + df
            if 0 <= tr < 8 and 0 <= tf < 8:
                to_sq = tr * 8 + tf
                idx = from_sq * 73 + 56 + k_idx
                MOVE_TO_INDEX[from_sq, to_sq, 0] = idx
                INDEX_TO_MOVE[idx] = (from_sq, to_sq, None)
        for p_idx, promo in enumerate(PROMO_TYPES):
            for p_dir in range(3):
                idx = from_sq * 73 + 64 + p_dir * 3 + p_idx
                INDEX_TO_MOVE[idx] = (from_sq, p_dir, promo)

_init_move_tables()

def move_to_index(move: chess.Move, board: chess.Board) -> int:
    from_sq = move.from_square
    to_sq = move.to_square
    promo = move.promotion
    promo_idx = 0
    if promo == chess.KNIGHT: promo_idx = 1
    elif promo == chess.BISHOP: promo_idx = 2
    elif promo == chess.ROOK: promo_idx = 3
    idx = MOVE_TO_INDEX[from_sq, to_sq, promo_idx]
    if idx == -1: idx = MOVE_TO_INDEX[from_sq, to_sq, 0]
    return max(0, min(idx, 4671))

def index_to_move(idx: int, board: chess.Board) -> Optional[chess.Move]:
    if idx < 0 or idx >= 4672: return None
    data = INDEX_TO_MOVE[idx]
    if data is None: return None
    from_sq, spec, promo = data
    if promo is not None:
        fr, ff = divmod(from_sq, 8)
        if board.turn == chess.WHITE:
            dirs = [(1, 0), (1, -1), (1, 1)]
        else:
            dirs = [(-1, 0), (-1, 1), (-1, -1)]
        dr, df = dirs[spec]
        tr, tf = fr + dr, ff + df
        if 0 <= tr < 8 and 0 <= tf < 8:
            to_sq = tr * 8 + tf
            move = chess.Move(from_sq, to_sq, promotion=promo)
            if move in board.legal_moves: return move
        return None
    if spec >= 0:
        move = chess.Move(from_sq, spec)
        if move in board.legal_moves: return move
    return None

# ==================== DATA AUGMENTATION (horizontal mirror) ====================
def _init_mirror_policy():
    global MIRROR_POLICY_IDX
    if MIRROR_POLICY_IDX is not None: return
    mirror = np.arange(4672, dtype=np.int32)
    QUEEN_DIR_MIRROR = np.array([0, 7, 6, 5, 4, 3, 2, 1], dtype=np.int32)
    KNIGHT_MIRROR = np.array([7, 6, 5, 4, 3, 2, 1, 0], dtype=np.int32)
    PROMO_DIR_MIRROR = np.array([0, 2, 1], dtype=np.int32)
    for from_sq in range(64):
        fr, ff = divmod(from_sq, 8)
        mf_from = 7 - ff
        m_from_sq = fr * 8 + mf_from
        for dir_idx, (dr, df) in enumerate(QUEEN_DIRS):
            m_dir = int(QUEEN_DIR_MIRROR[dir_idx])
            for dist in range(1, 8):
                tr, tf = fr + dr * dist, ff + df * dist
                if 0 <= tr < 8 and 0 <= tf < 8:
                    idx = from_sq * 73 + dir_idx * 7 + (dist - 1)
                    m_idx = m_from_sq * 73 + m_dir * 7 + (dist - 1)
                    mirror[idx] = m_idx
        for k_idx in range(8):
            dr, df = KNIGHT_MOVES[k_idx]; tr, tf = fr + dr, ff + df
            if 0 <= tr < 8 and 0 <= tf < 8:
                idx = from_sq * 73 + 56 + k_idx
                m_k_idx = int(KNIGHT_MIRROR[k_idx])
                m_idx = m_from_sq * 73 + 56 + m_k_idx
                mirror[idx] = m_idx
        for p_dir in range(3):
            m_p_dir = int(PROMO_DIR_MIRROR[p_dir])
            for promo_idx in range(3):
                idx = from_sq * 73 + 64 + p_dir * 3 + promo_idx
                m_idx = m_from_sq * 73 + 64 + m_p_dir * 3 + promo_idx
                mirror[idx] = m_idx
    MIRROR_POLICY_IDX = mirror

MIRROR_POLICY_IDX = None

def augment_data_batch(game_data: list) -> list:
    if not game_data: return []
    _init_mirror_policy()
    augmented = []
    for states, policy, value in game_data:
        x = states.reshape(8, 15, 8, 8).copy()
        x = np.ascontiguousarray(x[:, :, :, ::-1])
        x[:, [0,1,2,3,4,5,6,7,8,9,10,11]] = x[:, [6,7,8,9,10,11,0,1,2,3,4,5]]
        x[:, 12] = 1.0 - x[:, 12]
        castling = np.round(x[:, 13, 0, 0] * 15).astype(np.int32)
        wk = (castling >> 0) & 1; wq = (castling >> 1) & 1
        bk = (castling >> 2) & 1; bq = (castling >> 3) & 1
        mcast = ((wq << 0) | (wk << 1) | (bq << 2) | (bk << 3)).astype(np.float32) / 15.0
        x[:, 13, :, :] = mcast[:, None, None]
        x[:, 14, :, :] = x[:, 14, :, ::-1]
        mirrored_policy = policy[MIRROR_POLICY_IDX]
        augmented.append((x.reshape(120, 8, 8).copy(), mirrored_policy, -value))
    return augmented

def policy_to_move_probs(policy: np.ndarray, board: chess.Board):
    legal_moves = list(board.legal_moves)
    if not legal_moves: return np.array([]), []
    legal_indices = np.array([move_to_index(m, board) for m in legal_moves], dtype=np.int32)
    legal_probs = policy[legal_indices]
    total = legal_probs.sum()
    if total > 0: legal_probs = legal_probs / total
    else: legal_probs = np.ones_like(legal_probs) / len(legal_probs)
    return legal_probs, legal_moves

# ==================== BOARD ENCODING (112 planes) ====================
PIECE_PLANES = {
    (chess.PAWN, chess.WHITE): 0, (chess.KNIGHT, chess.WHITE): 1,
    (chess.BISHOP, chess.WHITE): 2, (chess.ROOK, chess.WHITE): 3,
    (chess.QUEEN, chess.WHITE): 4, (chess.KING, chess.WHITE): 5,
    (chess.PAWN, chess.BLACK): 6, (chess.KNIGHT, chess.BLACK): 7,
    (chess.BISHOP, chess.BLACK): 8, (chess.ROOK, chess.BLACK): 9,
    (chess.QUEEN, chess.BLACK): 10, (chess.KING, chess.BLACK): 11,
}

# Thread-local MCTS history cache (per-thread to avoid lock contention)
# Each MCTS call clears its thread's cache at entry; capped at 512 entries
MAX_HISTORY_CACHE = 512
_thread_local = threading.local()

def _get_mcts_cache():
    if not hasattr(_thread_local, 'mcts_cache'):
        _thread_local.mcts_cache = {}
        _thread_local.mcts_cache_keys = []
    return _thread_local.mcts_cache, _thread_local.mcts_cache_keys

def board_to_planes(board: chess.Board) -> np.ndarray:
    planes = np.zeros((15, 8, 8), dtype=np.float32)
    for sq, piece in board.piece_map().items():
        plane = PIECE_PLANES[(piece.piece_type, piece.color)]
        rank, file = divmod(sq, 8)
        planes[plane, 7 - rank, file] = 1.0
    planes[12, :, :] = 1.0 if board.turn == chess.WHITE else 0.0
    castling = 0
    if board.has_kingside_castling_rights(chess.WHITE): castling |= 1
    if board.has_queenside_castling_rights(chess.WHITE): castling |= 2
    if board.has_kingside_castling_rights(chess.BLACK): castling |= 4
    if board.has_queenside_castling_rights(chess.BLACK): castling |= 8
    planes[13, :, :] = castling / 15.0
    if board.ep_square is not None:
        rank, file = divmod(board.ep_square, 8)
        planes[14, 7 - rank, file] = 1.0
    return planes

class PositionHistory:
    def __init__(self, history_length: int = 8):
        self.history_length = history_length
        self.boards = deque(maxlen=history_length)
    def push(self, board: chess.Board):
        self.boards.append(board.copy(stack=False))

    def get_tensor(self) -> torch.Tensor:
        planes_list = []
        for b in self.boards:
            planes_list.append(board_to_planes(b))
        while len(planes_list) < self.history_length:
            planes_list.insert(0, np.zeros((15, 8, 8), dtype=np.float32))
        tensor = np.concatenate(planes_list, axis=0)
        return torch.from_numpy(tensor).float()

# ==================== NETWORK ====================
class SEBlock(nn.Module):
    def __init__(self, channels: int, reduction: int = 4):
        super().__init__()
        self.fc = nn.Sequential(
            nn.AdaptiveAvgPool2d(1),
            nn.Conv2d(channels, channels // reduction, 1, bias=False),
            nn.ReLU(inplace=True),
            nn.Conv2d(channels // reduction, channels, 1, bias=False),
            nn.Sigmoid()
        )
    def forward(self, x): return x * self.fc(x)

class ResBlock(nn.Module):
    def __init__(self, channels: int, se_ratio: int = 4, dropout: float = 0.0):
        super().__init__()
        self.conv1 = nn.Conv2d(channels, channels, 3, padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(channels)
        self.conv2 = nn.Conv2d(channels, channels, 3, padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(channels)
        self.se = SEBlock(channels, se_ratio)
        self.dropout = nn.Dropout2d(dropout) if dropout > 0 else nn.Identity()
    def forward(self, x):
        residual = x
        x = F.relu(self.bn1(self.conv1(x)), inplace=True)
        x = self.dropout(x)
        x = self.bn2(self.conv2(x))
        x = self.se(x)
        x += residual
        return F.relu(x, inplace=True)

class AZNet(nn.Module):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        in_channels = (cfg.use_history + 1) * 15  # 8 * 15 = 120 (7 history + 1 current)
        self.input_conv = nn.Sequential(
            nn.Conv2d(in_channels, cfg.num_channels, 3, padding=1, bias=False),
            nn.BatchNorm2d(cfg.num_channels),
            nn.ReLU(inplace=True)
        )
        self.tower = nn.Sequential(*[
            ResBlock(cfg.num_channels, cfg.se_ratio, 
                     cfg.policy_dropout if i > cfg.num_blocks // 2 else 0.0)
            for i in range(cfg.num_blocks)
        ])
        self.policy_conv = nn.Sequential(
            nn.Conv2d(cfg.num_channels, 32, 1, bias=False),
            nn.BatchNorm2d(32), nn.ReLU(inplace=True)
        )
        self.policy_fc = nn.Linear(32 * 8 * 8, 4672)
        self.value_conv = nn.Sequential(
            nn.Conv2d(cfg.num_channels, 3, 1, bias=False),
            nn.BatchNorm2d(3), nn.ReLU(inplace=True)
        )
        self.value_fc1 = nn.Linear(3 * 8 * 8, 256)
        self.value_fc2 = nn.Linear(256, 1)
        self.value_dropout = nn.Dropout(cfg.value_dropout)
        self._init_weights()
    def _init_weights(self):
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
            elif isinstance(m, nn.BatchNorm2d):
                nn.init.constant_(m.weight, 1); nn.init.constant_(m.bias, 0)
            elif isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                if m.bias is not None: nn.init.constant_(m.bias, 0)
        for m in self.modules():
            if isinstance(m, ResBlock): nn.init.constant_(m.bn2.weight, 0)
    def forward(self, x):
        x = self.input_conv(x); x = self.tower(x)
        p = self.policy_conv(x); p = p.view(p.size(0), -1); policy = self.policy_fc(p)
        v = self.value_conv(x); v = v.view(v.size(0), -1)
        v = F.relu(self.value_fc1(v), inplace=True); v = self.value_dropout(v)
        value = torch.tanh(self.value_fc2(v))
        return policy, value

# ==================== PRIORITIZED REPLAY BUFFER ====================
class PrioritizedReplayBuffer:
    def __init__(self, capacity: int, alpha: float = 0.6, beta: float = 0.4,
                 beta_anneal_steps: int = 100000, eps: float = 1e-6):
        self.capacity = capacity; self.alpha = alpha; self.beta = beta
        self.beta_anneal_steps = beta_anneal_steps; self.eps = eps
        self.max_priority = 1.0; self.lock = threading.Lock()
        self.states = np.zeros((capacity, 120, 8, 8), dtype=np.float32)
        self.policies = np.zeros((capacity, 4672), dtype=np.float32)
        self.values = np.zeros(capacity, dtype=np.float32)
        self.priorities = np.zeros(capacity, dtype=np.float32)
        self.size = 0; self.pos = 0
    def add(self, states, policies, values):
        n = len(states)
        idxs = (self.pos + np.arange(n)) % self.capacity
        with self.lock:
            self.states[idxs] = states; self.policies[idxs] = policies
            self.values[idxs] = values; self.priorities[idxs] = self.max_priority
            self.pos = (self.pos + n) % self.capacity
            self.size = min(self.size + n, self.capacity)
    def sample(self, batch_size: int):
        with self.lock:
            if self.size < batch_size: raise ValueError("Buffer too small")
            self.beta = min(1.0, self.beta + batch_size / self.beta_anneal_steps)
            probs = self.priorities[:self.size] ** self.alpha
            probs_sum = probs.sum()
            probs = probs / probs_sum if probs_sum > 0 else np.ones(self.size) / self.size
            idxs = np.random.choice(self.size, batch_size, p=probs, replace=False)
            weights = (self.size * probs[idxs]) ** (-self.beta)
            weights /= weights.max()
            return (torch.from_numpy(self.states[idxs]).float(),
                    torch.from_numpy(self.policies[idxs]).float(),
                    torch.from_numpy(self.values[idxs]).float(),
                    idxs, weights.astype(np.float32))
    def update_priorities(self, idxs, priorities):
        with self.lock:
            self.priorities[idxs] = priorities + self.eps
            self.max_priority = max(self.max_priority, priorities.max())
    def __len__(self): return self.size

# ==================== MCTS ====================
class MCTSNode:
    __slots__ = ('prior', 'visit_count', 'value_sum', 'children', 'virtual_loss')
    def __init__(self, prior: float):
        self.prior = prior; self.visit_count = 0; self.value_sum = 0.0
        self.children = {}; self.virtual_loss = 0
    def total_visits(self): return self.visit_count + self.virtual_loss
    def value(self): return self.value_sum / self.total_visits() if self.total_visits() else 0.0
    def is_expanded(self): return bool(self.children)
    def expand(self, policy: torch.Tensor, board: chess.Board):
        for move in board.legal_moves:
            idx = move_to_index(move, board)
            p = policy[idx].item()
            if p > 0: self.children[move] = MCTSNode(prior=p)
    def select_child(self, cfg: Config, parent_visit: int):
        c_puct = math.log((parent_visit + cfg.c_puct_base + 1) / cfg.c_puct_base) + cfg.c_puct_init
        sqrt_parent = math.sqrt(max(1, parent_visit))
        best_score = -float('inf'); best_move = best_child = None
        # Inline hot-path attribute access instead of calling value()/total_visits()
        for move, child in self.children.items():
            n = child.visit_count + child.virtual_loss
            q = child.value_sum / n if n else 0.0
            u = c_puct * child.prior * sqrt_parent / (1 + n)
            score = q + u
            if score > best_score: best_score, best_move, best_child = score, move, child
        return best_move, best_child
    def backup(self, value: float): self.visit_count += 1; self.value_sum += value

class MCTSContext:
    def __init__(self, cfg: Config):
        self.cfg = cfg; self.history = PositionHistory(cfg.use_history + 1)
        self.temp_board = chess.Board()
    def build_history(self, board: chess.Board):
        self.history = PositionHistory(self.cfg.use_history + 1)
        cache, keys = _get_mcts_cache()
        key = board._transposition_key()
        if key in cache:
            self.history.boards = [b.copy(stack=False) for b in cache[key]]
            return
        self.temp_board = board.copy()
        n = min(len(board.move_stack), self.cfg.use_history)
        for _ in range(n):
            self.temp_board.pop()
            self.history.push(self.temp_board)
        self.history.push(board)
        cache_boards = [b.copy(stack=False) for b in self.history.boards]
        cache[key] = cache_boards
        if len(cache) > MAX_HISTORY_CACHE:
            old_key = keys.pop(0) if keys else None
            if old_key is not None: cache.pop(old_key, None)
        keys.append(key)
    def get_tensor(self, board: chess.Board, device: str):
        self.build_history(board)
        return self.history.get_tensor().unsqueeze(0).to(device)

def run_mcts(model: AZNet, board: chess.Board, cfg: Config, add_noise: bool = True,
             temp: float = 1.0, prev_root: Optional['MCTSNode'] = None,
             num_simulations: Optional[int] = None):
    """Run MCTS with tree reuse and parallel batch leaf evaluation.
    
    If prev_root is given and board is one move deeper, reuses the child 
    matching the last move as the new root (saves initial eval + subtree).
    All non-terminal leaves are collected first, then evaluated in one batched 
    GPU call, then expanded and backed up — avoids interleaved GPU syncs.
    """
    # Clear per-thread cache only on fresh searches
    if prev_root is None:
        cache, keys = _get_mcts_cache(); cache.clear(); keys.clear()
        root = MCTSNode(prior=1.0)
    else:
        root = prev_root.children.get(board.peek(), MCTSNode(prior=1.0))
    
    ctx = MCTSContext(cfg)
    if not root.is_expanded():
        x = ctx.get_tensor(board, cfg.device)
        with torch.no_grad():
            if cfg.mixed_precision:
                with autocast(cfg.device): policy_logits, value = model(x)
            else: policy_logits, value = model(x)
        policy_s = F.softmax(policy_logits[0], dim=0).cpu()
        root_value = value.item()
        root.expand(policy_s, board)
        if add_noise and root.children:
            moves = list(root.children.keys())
            noise = np.random.dirichlet([cfg.dirichlet_alpha] * len(moves))
            for move, n in zip(moves, noise):
                root.children[move].prior = (1 - cfg.dirichlet_eps) * root.children[move].prior + cfg.dirichlet_eps * n
    else:
        root_value = root.value()
    
    sim_count = num_simulations if num_simulations is not None else cfg.num_simulations
    # Phase 1: Traverse ALL simulations — no GPU calls during traversal
    leaves = []
    for _ in range(sim_count):
        node = root; search_board = board.copy(stack=False); path = []
        while node.is_expanded():
            move, node = node.select_child(cfg, node.total_visits())
            search_board.push(move); path.append((node, move))
        if search_board.is_game_over():
            result = search_board.result()
            leaf_value = 1.0 if result == "1-0" else -1.0 if result == "0-1" else 0.0
            for n, _ in reversed(path):
                n.backup(leaf_value); leaf_value = -leaf_value
            root.backup(leaf_value)
        else:
            for n, _ in path + [(root, None)]:
                n.virtual_loss += 1
            leaves.append((path, node, search_board.copy(stack=False)))
    
    # Phase 2: Evaluate ALL leaves in one GPU call
    if leaves:
        tensors = []
        for _, _, b in leaves:
            ctx.build_history(b)
            tensors.append(ctx.history.get_tensor().unsqueeze(0))
        
        x = torch.cat(tensors, dim=0).to(cfg.device)
        with torch.no_grad():
            if cfg.mixed_precision:
                with autocast(cfg.device): policy_logits, values = model(x)
            else: policy_logits, values = model(x)
        policies = F.softmax(policy_logits, dim=1).cpu()
        
        # Phase 3: Expand and backup all paths
        for i, (path, leaf_node, b) in enumerate(leaves):
            v = float(values[i].item())
            leaf_node.expand(policies[i], b)
            for n, _ in path + [(root, None)]:
                n.virtual_loss -= 1
            leaf_value = v
            for n, _ in reversed(path):
                n.backup(leaf_value); leaf_value = -leaf_value
            root.backup(leaf_value)
    
    visits = np.zeros(4672, dtype=np.float32)
    for move, child in root.children.items():
        idx = move_to_index(move, board); visits[idx] = child.visit_count
    if temp == 0:
        policy_out = np.zeros_like(visits); policy_out[visits.argmax()] = 1.0
    else:
        visits = visits ** (1.0 / temp); policy_out = visits / (visits.sum() + 1e-8)
    return policy_out, root.value(), {'visits': visits, 'root_value': root.value()}, root

# ==================== OPENING BOOK ====================
OPENINGS = [
    # e4 openings
    ["e2e4","e7e5","g1f3","b8c6","f1c4"],           # Italian Game
    ["e2e4","e7e5","g1f3","b8c6","f1b5"],           # Spanish (Ruy Lopez)
    ["e2e4","e7e5","g1f3","b8c6","d2d4","e5d4","f1c4"],  # Scotch Gambit
    ["e2e4","e7e5","g1f3","g8f6"],                   # Petrov Defense
    ["e2e4","e7e5","f1c4","g8f6"],                   # Bishop's Opening
    ["e2e4","e7e5","g1f3","d7d6"],                   # Philidor Defense
    ["e2e4","e7e5","g1f3","f7f5"],                   # Latvian Gambit
    ["e2e4","c7c5"],                                  # Sicilian Defense
    ["e2e4","c7c5","g1f3","d7d6","d2d4","c5d4"],    # Sicilian Open
    ["e2e4","c7c5","g1f3","b8c6","d2d4","c5d4"],    # Sicilian Sveshnikov
    ["e2e4","e7e6"],                                  # French Defense
    ["e2e4","e7e6","d2d4","d7d5","e4e5"],            # French Advance
    ["e2e4","e7e6","d2d4","d7d5","b1c3"],            # French Tarrasch
    ["e2e4","c7c6"],                                  # Caro-Kann
    ["e2e4","c7c6","d2d4","d7d5","e4e5"],            # Caro-Kann Advance
    ["e2e4","d7d6"],                                  # Pirc Defense
    ["e2e4","g7g6"],                                  # Modern Defense
    ["e2e4","g8f6"],                                  # Alekhine's Defense
    ["e2e4","d7d5"],                                  # Scandinavian Defense
    ["e2e4","b7b6"],                                  # Owen's Defense
    ["e2e4","a7a6"],                                  # St. George Defense
    ["e2e4","c7c5","g1f3","e7e6","d2d4","c5d4","f3d4"], # Sicilian Scheveningen
    ["e2e4","c7c5","g1f3","g7g6","d2d4","c5d4","f3d4"], # Sicilian Dragon
    ["e2e4","c7c5","c2c3"],                           # Sicilian Alapin
    # d4 openings
    ["d2d4","d7d5"],                                  # Queen's Pawn Game
    ["d2d4","d7d5","c2c4"],                           # Queen's Gambit
    ["d2d4","d7d5","c2c4","d5c4"],                    # Queen's Gambit Accepted
    ["d2d4","d7d5","c2c4","e7e6"],                    # Queen's Gambit Declined
    ["d2d4","d7d5","c2c4","c7c6"],                    # Slav Defense
    ["d2d4","d7d5","c2c4","c7c6","g1f3","g8f6","b1c3"], # Slav Main Line
    ["d2d4","d7d5","c2c4","c7c6","e2e3"],            # Semi-Slav
    ["d2d4","g8f6"],                                  # Indian Defense
    ["d2d4","g8f6","c2c4","g7g6"],                    # King's Indian
    ["d2d4","g8f6","c2c4","g7g6","b1c3","f8g7","e2e4","d7d6"], # KID Classical
    ["d2d4","g8f6","c2c4","e7e6"],                    # Queen's Indian
    ["d2d4","g8f6","c2c4","e7e6","b1c3","f8b4"],     # Nimzo-Indian
    ["d2d4","g8f6","c2c4","e7e6","g1f3","b7b6"],     # Bogo-Indian
    ["d2d4","g8f6","c2c4","c7c5"],                    # Benoni Defense
    ["d2d4","g8f6","c2c4","c7c5","d4d5","e7e6"],     # Modern Benoni
    ["d2d4","f7f5"],                                  # Dutch Defense
    # Flank openings
    ["c2c4"],                                          # English Opening
    ["c2c4","e7e5"],                                  # English Symmetrical
    ["c2c4","c7c5"],                                  # English Symmetrical
    ["c2c4","e7e6"],                                  # English Keres
    ["g1f3"],                                          # Reti Opening
    ["g1f3","d7d5","c2c4"],                           # Reti Gambit
    ["b1c3"],                                          # Dunst Opening
    ["f2f4"],                                          # Bird's Opening
    ["b2b3"],                                          # Larsen's Opening
    ["g2g3"],                                          # King's Fianchetto
]

def get_opening_position(cfg: Config) -> chess.Board:
    if cfg.opening_book_moves <= 0:
        return chess.Board()
    board = chess.Board()
    opening = random.choice(OPENINGS)
    for uci in opening[:random.randint(1, len(opening))]:
        move = chess.Move.from_uci(uci)
        if move in board.legal_moves:
            board.push(move)
        else:
            break
    return board

# ==================== MODEL EMA ====================
class ModelEMA:
    def __init__(self, model: nn.Module, decay: float = 0.995):
        self.decay = decay
        self.shadow = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    def update(self, model: nn.Module):
        with torch.no_grad():
            for k, v in model.state_dict().items():
                self.shadow[k] = self.decay * self.shadow[k] + (1 - self.decay) * v.detach().cpu()
    def apply_to(self, model: nn.Module):
        dev = next(model.parameters()).device
        model.load_state_dict({k: v.to(dev) for k, v in self.shadow.items()})

# ==================== CSV LOGGER ====================
class CSVLogger:
    def __init__(self, path: str):
        self.path = path
        self.fields = []
        self._first = True
    def log(self, **kwargs):
        if self._first:
            self.fields = list(kwargs.keys())
            with open(self.path, 'w') as f:
                f.write(','.join(self.fields) + '\n')
            self._first = False
        with open(self.path, 'a') as f:
            f.write(','.join(str(kwargs.get(k, '')) for k in self.fields) + '\n')

# ==================== SELF-PLAY ====================
def self_play_game(cfg: Config, game_id: int, seed: int, model: AZNet, live_queue=None):
    torch.manual_seed(seed); np.random.seed(seed); random.seed(seed)
    board = get_opening_position(cfg) if cfg.use_opening_book else chess.Board()
    start_fen = board.fen()
    game_data = []; move_count = 0; resigned = False
    prev_root = None; next_sims = None; moves_list = []; resign_count = 0
    sp_ctx = MCTSContext(cfg)
    if live_queue is not None:
        try: live_queue.put((game_id, None, start_fen), False)
        except: pass
    while not board.is_game_over() and move_count < cfg.max_moves and not resigned:
        temp = cfg.temperature_init * (cfg.temperature_decay ** move_count) if move_count < cfg.temperature_moves else cfg.temperature_final
        policy, _, info, prev_root = run_mcts(model, board, cfg, add_noise=True, temp=temp, prev_root=prev_root, num_simulations=next_sims)
        root_value = info['root_value']
        # Adaptive sims: save time in decided games (use prev move's root_value)
        next_sims = cfg.num_simulations
        if abs(root_value) > 0.95:
            next_sims = max(cfg.num_simulations // 4, 10)
        elif abs(root_value) > 0.85:
            next_sims = max(cfg.num_simulations // 2, 20)
        sp_ctx.build_history(board)
        x = sp_ctx.history.get_tensor().numpy()
        game_data.append((x.copy(), policy.copy(), board.turn == chess.WHITE))
        legal_probs, legal_moves = policy_to_move_probs(policy, board)
        if not legal_moves: break
        move_idx = np.random.choice(len(legal_moves), p=legal_probs)
        move = legal_moves[move_idx]
        moves_list.append(move)
        board.push(move); move_count += 1
        if live_queue is not None:
            try: live_queue.put((game_id, move.uci(), board.fen()), False)
            except: pass
        if root_value < cfg.resign_threshold and move_count > cfg.resign_moves:
            resign_count += 1
            if resign_count >= cfg.resign_consecutive:
                resigned = True; break
        else:
            resign_count = 0
    if resigned:
        result = "0-1" if board.turn == chess.WHITE else "1-0"
        outcome = 1.0 if result == "1-0" else -1.0
    else:
        result = board.result()
        outcome = 1.0 if result == "1-0" else -1.0 if result == "0-1" else 0.0
    if live_queue is not None:
        try: live_queue.put((game_id, None, None), False)
        except: pass
    return [(x, p, outcome if wtm else -outcome) for x, p, wtm in game_data], result, resigned, moves_list, start_fen

# ==================== TRAINING ====================
def train_step(model, optimizer, scaler, states, target_policies, target_values, weights, cfg):
    model.train()
    states = states.to(cfg.device, non_blocking=True)
    target_policies = target_policies.to(cfg.device, non_blocking=True)
    target_values = target_values.to(cfg.device, non_blocking=True)
    if not isinstance(weights, torch.Tensor): weights = torch.from_numpy(weights)
    weights = weights.to(cfg.device, non_blocking=True)
    optimizer.zero_grad(set_to_none=True)
    if cfg.mixed_precision:
        with autocast(cfg.device):
            policy_logits, value = model(states)
            log_policy = F.log_softmax(policy_logits, dim=1)
            policy_loss = -(target_policies * log_policy).sum(1)
            value_loss = F.mse_loss(value.squeeze(), target_values, reduction='none')
            loss = (weights * (policy_loss + value_loss)).mean()
        scaler.scale(loss).backward()
        if cfg.grad_clip > 0:
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)
        scaler.step(optimizer); scaler.update()
        priorities = (value.squeeze() - target_values).abs().detach().cpu().numpy()
    else:
        policy_logits, value = model(states)
        log_policy = F.log_softmax(policy_logits, dim=1)
        policy_loss = -(target_policies * log_policy).sum(1)
        value_loss = F.mse_loss(value.squeeze(), target_values, reduction='none')
        loss = (weights * (policy_loss + value_loss)).mean()
        loss.backward()
        if cfg.grad_clip > 0: torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)
        optimizer.step()
        priorities = (value.squeeze() - target_values).abs().detach().cpu().numpy()
    return loss.item(), policy_loss.mean().item(), value_loss.mean().item(), priorities

# ==================== BASELINE OPPONENT ====================
PIECE_VALUES = {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330, chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 0}
# Piece-square tables (from white's perspective, indexed by square)
PST = {
    chess.PAWN: [
        0,  0,  0,  0,  0,  0,  0,  0,
       50, 50, 50, 50, 50, 50, 50, 50,
       10, 10, 20, 30, 30, 20, 10, 10,
        5,  5, 10, 25, 25, 10,  5,  5,
        0,  0,  0, 20, 20,  0,  0,  0,
        5, -5,-10,  0,  0,-10, -5,  5,
        5, 10, 10,-20,-20, 10, 10,  5,
        0,  0,  0,  0,  0,  0,  0,  0,
    ],
    chess.KNIGHT: [
        -50,-40,-30,-30,-30,-30,-40,-50,
        -40,-20,  0,  0,  0,  0,-20,-40,
        -30,  0, 10, 15, 15, 10,  0,-30,
        -30,  5, 15, 20, 20, 15,  5,-30,
        -30,  0, 15, 20, 20, 15,  0,-30,
        -30,  5, 10, 15, 15, 10,  5,-30,
        -40,-20,  0,  5,  5,  0,-20,-40,
        -50,-40,-30,-30,-30,-30,-40,-50,
    ],
    chess.BISHOP: [
        -20,-10,-10,-10,-10,-10,-10,-20,
        -10,  0,  0,  0,  0,  0,  0,-10,
        -10,  0, 10, 10, 10, 10,  0,-10,
        -10,  5,  5, 10, 10,  5,  5,-10,
        -10,  0, 10, 10, 10, 10,  0,-10,
        -10, 10, 10, 10, 10, 10, 10,-10,
        -10,  5,  0,  0,  0,  0,  5,-10,
        -20,-10,-10,-10,-10,-10,-10,-20,
    ],
    chess.ROOK: [
        0,  0,  0,  0,  0,  0,  0,  0,
        5, 10, 10, 10, 10, 10, 10,  5,
       -5,  0,  0,  0,  0,  0,  0, -5,
       -5,  0,  0,  0,  0,  0,  0, -5,
       -5,  0,  0,  0,  0,  0,  0, -5,
       -5,  0,  0,  0,  0,  0,  0, -5,
       -5,  0,  0,  0,  0,  0,  0, -5,
        0,  0,  0,  5,  5,  0,  0,  0,
    ],
    chess.QUEEN: [
        -20,-10,-10, -5, -5,-10,-10,-20,
        -10,  0,  0,  0,  0,  0,  0,-10,
        -10,  0,  5,  5,  5,  5,  0,-10,
         -5,  0,  5,  5,  5,  5,  0, -5,
          0,  0,  5,  5,  5,  5,  0, -5,
        -10,  5,  5,  5,  5,  5,  0,-10,
        -10,  0,  5,  0,  0,  0,  0,-10,
        -20,-10,-10, -5, -5,-10,-10,-20,
    ],
}

def heuristic_eval(board: chess.Board) -> float:
    """Material + piece-square evaluation, positive = good for white."""
    score = 0
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece is None: continue
        val = PIECE_VALUES[piece.piece_type]
        pst = PST.get(piece.piece_type)
        if pst is not None:
            if piece.color == chess.WHITE:
                val += pst[sq]
            else:
                val += pst[chess.square_mirror(sq)]
        if piece.color == chess.WHITE: score += val
        else: score -= val
    return score / 1000.0  # normalize

def baseline_move(board: chess.Board, search_sims: int = 0) -> chess.Move:
    """Pick the best move by heuristic (with optional shallow search)."""
    if search_sims <= 0:
        legal = list(board.legal_moves)
        if not legal: return None
        best_move = None; best_score = -float('inf')
        for move in legal:
            board.push(move)
            score = heuristic_eval(board)
            if board.turn == chess.BLACK: score = -score
            board.pop()
            if score > best_score: best_score, best_move = score, move
        return best_move
    # Shallow minimax with heuristic leaf eval
    def alpha_beta(b, depth, alpha, beta, maximizing):
        if depth == 0 or b.is_game_over():
            if b.is_game_over():
                result = b.result()
                return 1.0 if result == "1-0" else -1.0 if result == "0-1" else 0.0
            return heuristic_eval(b) * (1 if maximizing else -1)
        legal = list(b.legal_moves)
        if maximizing:
            value = -float('inf')
            for move in legal:
                b.push(move)
                value = max(value, alpha_beta(b, depth - 1, alpha, beta, False))
                b.pop()
                if value >= beta: break
                alpha = max(alpha, value)
            return value
        else:
            value = float('inf')
            for move in legal:
                b.push(move)
                value = min(value, alpha_beta(b, depth - 1, alpha, beta, True))
                b.pop()
                if value <= alpha: break
                beta = min(beta, value)
            return value
    legal = list(board.legal_moves)
    best_move = None; best_score = -float('inf')
    for move in legal:
        board.push(move)
        score = alpha_beta(board, search_sims - 1, -float('inf'), float('inf'), board.turn == chess.WHITE)
        board.pop()
        if score > best_score: best_score, best_move = score, move
    return best_move

# ==================== LR SCHEDULER WITH WARMUP ====================
class WarmupCosineLR:
    def __init__(self, optimizer: torch.optim.Optimizer, warmup_steps: int, warmup_min_lr: float,
                 target_lr: float, cosine_t_max: int, cosine_min_lr: float):
        self.optimizer = optimizer
        self.warmup_steps = warmup_steps
        self.warmup_min_lr = warmup_min_lr
        self.target_lr = target_lr
        self.cosine_t_max = cosine_t_max
        self.cosine_min_lr = cosine_min_lr
        self._step = 0
        self._cosine = optim.lr_scheduler.CosineAnnealingLR(
            optimizer, T_max=cosine_t_max, eta_min=cosine_min_lr)
    def step(self):
        self._step += 1
        if self._step <= self.warmup_steps:
            progress = self._step / max(1, self.warmup_steps)
            lr = self.warmup_min_lr + (self.target_lr - self.warmup_min_lr) * progress
            for pg in self.optimizer.param_groups: pg['lr'] = lr
        else:
            self._cosine.step()
    def state_dict(self):
        return {'step': self._step, 'cosine_state': self._cosine.state_dict()}
    def load_state_dict(self, state):
        self._step = state['step']
        if state['cosine_state'] is not None:
            self._cosine.load_state_dict(state['cosine_state'])
    def get_last_lr(self):
        return [pg['lr'] for pg in self.optimizer.param_groups]

# ==================== SELF-PLAY WORKER (multiprocessing) ====================
SHM_SIZE = 64 * 1024 * 1024  # 64 MB shared memory for weight sync

class SelfPlayWorker(mp.Process):
    """Worker process that generates self-play games in parallel.
    Each process owns its own GPU model; weights sync via shared memory.
    No GIL contention — true CPU parallelism for tree traversal.
    """
    def __init__(self, worker_id, cfg, shm_name, shm_lock, weight_version,
                 game_queue, stop_event, live_queue=None):
        super().__init__()
        self.worker_id = worker_id
        self.cfg = cfg
        self.shm_name = shm_name
        self.shm_lock = shm_lock
        self.weight_version = weight_version
        self.game_queue = game_queue
        self.stop_event = stop_event
        self.live_queue = live_queue
        self.daemon = True

    def run(self):
        # Runs in a separate process — no GIL contention
        self._model = AZNet(self.cfg).to(self.cfg.device)
        self._model.eval()
        shm = shared_memory.SharedMemory(name=self.shm_name)
        last_version = -1
        seed_base = (self.worker_id + 1) * 100000
        local_games = 0

        while not self.stop_event.is_set():
            # Sync weights from training model via shared memory
            ver = self.weight_version.value
            if ver != last_version:
                with self.shm_lock:
                    size = struct.unpack_from('Q', shm.buf, 0)[0]
                    if size > 0:
                        data = bytes(shm.buf[8:8+size])
                if size > 0:
                    sd = pickle.loads(data)
                    self._model.load_state_dict(sd)
                last_version = ver

            game_data, result, resigned, moves_list, start_fen = self_play_game(
                self.cfg, self.worker_id, seed_base + local_games, model=self._model,
                live_queue=self.live_queue)
            local_games += 1
            if game_data:
                self.game_queue.put((game_data, result, resigned, moves_list, start_fen))

        shm.close()

# ==================== MAIN ====================
def evaluate_model(model, cfg, num_games, baseline_sims=0):
    model.eval()
    model_wins = 0; model_losses = 0; draws = 0
    for g in range(num_games):
        board = chess.Board()
        model_color = chess.WHITE if g % 2 == 0 else chess.BLACK
        prev_root = None
        while not board.is_game_over():
            if board.turn == model_color:
                policy, _, _, prev_root = run_mcts(model, board, cfg, add_noise=False, temp=0.0, prev_root=prev_root)
                legal_probs, legal_moves = policy_to_move_probs(policy, board)
                if not legal_moves: break
                move = legal_moves[legal_probs.argmax()]
                board.push(move)
                # Advance tree through model's move (now at opponent's position)
                if prev_root is not None:
                    prev_root = prev_root.children.get(move, None)
            else:
                move = baseline_move(board, baseline_sims)
                if move is None: break
                board.push(move)
                # Advance tree through opponent's move (back to model's position)
                if prev_root is not None:
                    prev_root = prev_root.children.get(move, None)
        result = board.result()
        if result == "1-0" and model_color == chess.WHITE: model_wins += 1
        elif result == "0-1" and model_color == chess.BLACK: model_wins += 1
        elif result in ("1-0", "0-1"): model_losses += 1
        else: draws += 1
    return (model_wins - model_losses) / num_games

def main(stats: TrainingStats = None, cfg: Config = None):
    torch.manual_seed(42); np.random.seed(42); random.seed(42)
    torch.backends.cudnn.benchmark = True; torch.backends.cudnn.deterministic = False
    
    # Apply passed cfg overrides to global CFG
    if cfg is not None:
        for k, v in cfg.__dict__.items():
            if v is not None:
                setattr(CFG, k, v)
    # Auto-detect settings
    if CFG.num_workers <= 0:
        CFG.num_workers = min(max(1, os.cpu_count() - 1), 4)
    if CFG.compile_model and sys.platform.startswith('win32'):
        CFG.compile_model = False
    
    os.makedirs(CFG.log_dir, exist_ok=True); os.makedirs(CFG.checkpoint_dir, exist_ok=True)
    writer = None
    if CFG.tensorboard:
        try:
            from torch.utils.tensorboard import SummaryWriter
            writer = SummaryWriter(CFG.log_dir)
        except Exception:
            print("tensorboard not installed, disabling logging")
    
    if stats: stats.running = True
    print(f"Device: {CFG.device}  Workers: {CFG.num_workers}", flush=True)
    model = AZNet(CFG).to(CFG.device)
    if CFG.compile_model and hasattr(torch, 'compile') and sys.platform != 'win32':
        try:
            model = torch.compile(model, mode=CFG.compile_mode)
            print("Model compiled")
        except Exception:
            print("torch.compile failed, skipping")
    
    ema = ModelEMA(model, CFG.ema_decay) if CFG.ema_decay > 0 else None
    
    optimizer = optim.SGD(model.parameters(), lr=CFG.lr, momentum=CFG.momentum,
                          weight_decay=CFG.weight_decay, nesterov=True)
    scheduler = WarmupCosineLR(optimizer, CFG.warmup_steps, CFG.lr_warmup_min,
                                CFG.lr, CFG.total_training_steps, CFG.lr_min)
    scaler = GradScaler(CFG.device, enabled=CFG.mixed_precision)
    
    buffer = PrioritizedReplayBuffer(CFG.buffer_size, CFG.priority_alpha, CFG.priority_beta, CFG.priority_beta_anneal)
    csv_log = CSVLogger(os.path.join(CFG.log_dir, 'metrics.csv')) if CFG.log_csv else None
    
    # Game statistics tracking
    sp_wins = sp_losses = sp_draws = sp_total = 0
    sp_total_moves = 0; sp_resigned = 0
    
    start_iteration = 0; best_eval = -1; total_games = 0; training_steps = 0
    checkpoints = sorted([f for f in os.listdir(CFG.checkpoint_dir) if f.endswith('.pt')],
                         key=lambda x: int(x.split('_')[-1].split('.')[0]) if x.startswith('checkpoint_') else 0) if os.path.exists(CFG.checkpoint_dir) else []
    if checkpoints:
        latest = os.path.join(CFG.checkpoint_dir, checkpoints[-1])
        print(f"Loading: {latest}")
        ckpt = torch.load(latest, map_location=CFG.device, weights_only=False)
        model.load_state_dict(ckpt['model_state_dict'])
        if 'optimizer_state_dict' in ckpt: optimizer.load_state_dict(ckpt['optimizer_state_dict'])
        if 'scheduler_state_dict' in ckpt: scheduler.load_state_dict(ckpt['scheduler_state_dict'])
        if ema and 'ema_state' in ckpt: ema.shadow = {k: v.cpu() for k, v in ckpt['ema_state'].items()}
        start_iteration = ckpt.get('iteration', 0); best_eval = ckpt.get('best_eval', -1)
        total_games = ckpt.get('total_games', 0); training_steps = ckpt.get('training_steps', 0)
        if 'sp_stats' in ckpt: sp_wins, sp_losses, sp_draws, sp_total_moves, sp_resigned = ckpt['sp_stats']
        print(f"Resumed: games={total_games}, training_steps={training_steps}")
    
    # === WORKER SETUP (multiprocessing) ===
    # True parallelism: each worker is a separate process with its own GPU model
    # Weights synced via shared memory; game results via multiprocessing queue
    shm = shared_memory.SharedMemory(create=True, size=SHM_SIZE)
    sd_bytes = pickle.dumps({k: v.cpu() for k, v in model.state_dict().items()})
    struct.pack_into('Q', shm.buf, 0, len(sd_bytes))
    shm.buf[8:8+len(sd_bytes)] = sd_bytes
    
    shm_lock = mp.Lock()
    weight_version = mp.Value('i', 0, lock=False)
    game_queue = mp.Queue(maxsize=CFG.queue_max_size)
    live_queue = mp.Queue(maxsize=2000)
    if stats: stats.live_queue = live_queue
    stop_event = mp.Event()
    
    workers = [SelfPlayWorker(i, CFG, shm.name, shm_lock, weight_version,
                               game_queue, stop_event, live_queue) for i in range(CFG.num_workers)]
    for i, w in enumerate(workers):
        w.start()
        time.sleep(0.3)  # stagger to avoid GPU context contention
    print(f"Started {CFG.num_workers} self-play worker processes (true CPU parallelism)", flush=True)
    
    # === PRODUCER-CONSUMER LOOP ===
    t_start = time.time()
    last_saved_step = -1
    model.train(); model.zero_grad(set_to_none=True)
    acc_steps = 0
    save_threads = []
    
    try:
        while total_games < CFG.num_selfplay_games:
            iteration_start = time.time()
            
            # Check worker health (timeout after 2 min of no games)
            try:
                game_data, result, resigned, moves_list, start_fen = game_queue.get(timeout=120)
            except queue.Empty:
                alive = sum(1 for w in workers if w.is_alive())
                print(f"WARNING: No games for 120s (workers alive: {alive}/{CFG.num_workers})", flush=True)
                if alive < CFG.num_workers:
                    print("Restarting dead workers...", flush=True)
                    for i, w in enumerate(workers):
                        if not w.is_alive():
                            workers[i] = SelfPlayWorker(i, CFG, shm.name, shm_lock, weight_version,
                                                        game_queue, stop_event)
                            workers[i].start()
                continue
            
            if stats:
                stats.last_moves = moves_list
                stats.last_start_fen = start_fen
                stats.current_board_fen = chess.Board().fen()
            
            states, policies, values = zip(*game_data)
            s_arr = np.stack(states); p_arr = np.stack(policies); v_arr = np.array(values)
            buffer.add(s_arr, p_arr, v_arr)
            if CFG.augment_data and s_arr.shape[0] > 0:
                aug = augment_data_batch(game_data)
                if aug:
                    a_states, a_policies, a_values = zip(*aug)
                    buffer.add(np.stack(a_states), np.stack(a_policies), np.array(a_values))
            total_games += 1
            
            if resigned: sp_resigned += 1
            if result == "1-0": sp_wins += 1
            elif result == "0-1": sp_losses += 1
            else: sp_draws += 1
            sp_total_moves += len(game_data)
            
            # === TRAINING PHASE ===
            for _ in range(CFG.train_steps_per_game):
                if len(buffer) < CFG.batch_size: break
                b_states, b_policies, b_values, idxs, weights_np = buffer.sample(CFG.batch_size)
                weights = torch.from_numpy(weights_np).to(CFG.device, non_blocking=True)
                b_states = b_states.to(CFG.device, non_blocking=True)
                b_policies = b_policies.to(CFG.device, non_blocking=True)
                b_values = b_values.to(CFG.device, non_blocking=True)
                
                with autocast(CFG.device):
                    policy_logits, value = model(b_states)
                    log_policy = F.log_softmax(policy_logits, dim=1)
                    policy_loss = -(b_policies * log_policy).sum(1)
                    value_loss = F.mse_loss(value.squeeze(), b_values, reduction='none')
                    loss = (weights * (policy_loss + value_loss)).mean()
                    loss = loss / CFG.gradient_accumulation_steps
                
                scaler.scale(loss).backward()
                acc_steps += 1
                
                if acc_steps >= CFG.gradient_accumulation_steps:
                    if CFG.grad_clip > 0:
                        scaler.unscale_(optimizer)
                        torch.nn.utils.clip_grad_norm_(model.parameters(), CFG.grad_clip)
                    scaler.step(optimizer); scaler.update()
                    optimizer.zero_grad(set_to_none=True)
                    acc_steps = 0
                    
                    training_steps += 1
                    scheduler.step()
                    if ema: ema.update(model)
                    
                    per_sample_priorities = (value.squeeze() - b_values).abs().detach().cpu().numpy()
                    buffer.update_priorities(idxs, per_sample_priorities)
                    
                    if writer:
                        writer.add_scalar('train/loss', loss.item() * CFG.gradient_accumulation_steps, training_steps)
                        writer.add_scalar('train/policy_loss', policy_loss.mean().item(), training_steps)
                        writer.add_scalar('train/value_loss', value_loss.mean().item(), training_steps)
                        writer.add_scalar('train/lr', optimizer.param_groups[0]['lr'], training_steps)
            
            if acc_steps > 0:
                if CFG.grad_clip > 0:
                    scaler.unscale_(optimizer)
                    torch.nn.utils.clip_grad_norm_(model.parameters(), CFG.grad_clip)
                scaler.step(optimizer); scaler.update()
                optimizer.zero_grad(set_to_none=True)
                training_steps += 1; scheduler.step()
                if ema: ema.update(model)
                per_sample_priorities = (value.squeeze() - b_values).abs().detach().cpu().numpy()
                buffer.update_priorities(idxs, per_sample_priorities)
                acc_steps = 0
            
            # Push updated weights to worker processes via shared memory
            sd_bytes = pickle.dumps({k: v.cpu() for k, v in model.state_dict().items()})
            with shm_lock:
                n = len(sd_bytes)
                if n + 8 > SHM_SIZE:
                    print("WARNING: state dict too large for shared memory", flush=True)
                else:
                    struct.pack_into('Q', shm.buf, 0, n)
                    shm.buf[8:8+n] = sd_bytes
                    weight_version.value = training_steps
            
            # Logging
            selfplay_winrate = sp_wins / max(1, sp_wins + sp_losses + sp_draws)
            avg_game_len = sp_total_moves / max(1, sp_wins + sp_losses + sp_draws)
            elapsed = time.time() - t_start
            iter_time = time.time() - iteration_start
            qsize = game_queue.qsize()
            msg = (f"Game {total_games}/{CFG.num_selfplay_games}: "
                   f"buf={len(buffer)}, q={qsize}, steps={training_steps}, "
                   f"win={selfplay_winrate:.1%}, avg={avg_game_len:.0f}, "
                   f"time={elapsed:.0f}s, iter={iter_time:.1f}s")
            print(msg)
            if stats:
                stats.total_games = total_games; stats.training_steps = training_steps
                stats.buffer_size = len(buffer); stats.curr_queue_size = qsize
                stats.win_rate = selfplay_winrate; stats.avg_game_len = avg_game_len
                stats.elapsed = elapsed; stats.target_games = CFG.num_selfplay_games
                stats.log_lines.append(msg)
                if len(stats.log_lines) > 200: stats.log_lines = stats.log_lines[-200:]
            if stats and stats.stop_requested:
                print("Training stopped by user", flush=True); break
            
            if csv_log:
                csv_log.log(step=training_steps, games=total_games, buffer=len(buffer),
                            queue_size=qsize, selfplay_winrate=selfplay_winrate,
                            avg_game_len=avg_game_len, lr=optimizer.param_groups[0]['lr'],
                            time_elapsed=elapsed)
            
            # Checkpoint
            if training_steps > 0 and training_steps % CFG.save_interval == 0:
                ckpt_dict = {'iteration': training_steps, 'model_state_dict': model.state_dict(),
                             'optimizer_state_dict': optimizer.state_dict(), 'scheduler_state_dict': scheduler.state_dict(),
                             'best_eval': best_eval, 'total_games': total_games, 'training_steps': training_steps,
                             'config': CFG, 'sp_stats': (sp_wins, sp_losses, sp_draws, sp_total_moves, sp_resigned)}
                if ema: ckpt_dict['ema_state'] = ema.shadow
                ckpt_path = os.path.join(CFG.checkpoint_dir, f'checkpoint_{training_steps}.pt')
                t = threading.Thread(target=lambda p=ckpt_path, d=ckpt_dict: (torch.save(d, p), print(f"Saved: {p}")))
                t.start(); save_threads.append(t)
                if len(save_threads) > 3: save_threads.pop(0).join()
                last_saved_step = training_steps
                checkpoints = sorted([f for f in os.listdir(CFG.checkpoint_dir) if f.startswith('checkpoint_')],
                                     key=lambda x: int(x.split('_')[-1].split('.')[0]))
                for old in checkpoints[:-CFG.keep_best_n]:
                    os.remove(os.path.join(CFG.checkpoint_dir, old))
            
            # Eval (infrequent — workers keep producing during eval)
            if training_steps > 0 and training_steps % CFG.eval_interval == 0 and CFG.eval_games > 0:
                if ema: ema.apply_to(model); model.eval()
                eval_score = evaluate_model(model, CFG, CFG.eval_games)
                print(f"Self-play eval: {eval_score:.3f}")
                if writer: writer.add_scalar('eval/selfplay', eval_score, training_steps)
                if csv_log: csv_log.log(step=training_steps, eval_selfplay=eval_score)
                if CFG.eval_baseline_games > 0:
                    baseline_score = evaluate_model(model, CFG, CFG.eval_baseline_games, baseline_sims=CFG.baseline_search_sims)
                    print(f"vs baseline: {baseline_score:.3f}")
                    if writer: writer.add_scalar('eval/baseline', baseline_score, training_steps)
                    if csv_log: csv_log.log(step=training_steps, eval_baseline=baseline_score)
                    eval_score = baseline_score
                if eval_score > best_eval:
                    best_eval = eval_score
                    torch.save({'model_state_dict': model.state_dict(), 'eval_score': eval_score, 'iteration': training_steps},
                               os.path.join(CFG.checkpoint_dir, 'best_model.pt'))
                    print(f"New best: {eval_score:.3f}")
                if ema: model.load_state_dict({k: v.to(CFG.device) for k, v in ema.shadow.items()})
                
    finally:
        stop_event.set()
        for w in workers: w.join(timeout=10)
        # Drain remaining games for accurate final stats
        while True:
            try:
                game_data, result, resigned, moves_list, _ = game_queue.get_nowait()
                total_games += 1
                if resigned: sp_resigned += 1
                if result == "1-0": sp_wins += 1
                elif result == "0-1": sp_losses += 1
                else: sp_draws += 1
                sp_total_moves += len(game_data)
            except:
                break
        shm.close()
        shm.unlink()
        for t in save_threads: t.join(timeout=30)
        if (total_games > 0 or training_steps > 0) and training_steps != last_saved_step:
            ckpt_dict = {'iteration': training_steps, 'model_state_dict': model.state_dict(),
                         'optimizer_state_dict': optimizer.state_dict(), 'scheduler_state_dict': scheduler.state_dict(),
                         'best_eval': best_eval, 'total_games': total_games, 'training_steps': training_steps,
                         'config': CFG, 'sp_stats': (sp_wins, sp_losses, sp_draws, sp_total_moves, sp_resigned)}
            if ema: ckpt_dict['ema_state'] = ema.shadow
            ckpt_path = os.path.join(CFG.checkpoint_dir, f'checkpoint_{training_steps}.pt')
            torch.save(ckpt_dict, ckpt_path)
            print(f"Saved: {ckpt_path}")
        if acc_steps > 0:
            scaler.step(optimizer); scaler.update()
            optimizer.zero_grad(set_to_none=True)
        if writer: writer.close()
        if stats: stats.running = False
        print(f"Training complete! Games: {total_games}, Steps: {training_steps}")

# ==================== GUI ====================
class PromotionDialog(tk.Toplevel):
    def __init__(self, parent, color):
        super().__init__(parent)
        self.title('Promote')
        self.result = chess.QUEEN
        self.grab_set()
        tk.Label(self, text='Promote to:', font=('TkDefaultFont', 10)).pack(pady=6)
        f = tk.Frame(self); f.pack(pady=6)
        for pt in [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]:
            tk.Button(f, text=UNICODE_PIECES[pt][color], font=('Segoe UI Symbol', 26),
                      width=2, command=lambda p=pt: self._pick(p)).pack(side=tk.LEFT, padx=3)
        self.geometry('+%d+%d' % (parent.winfo_rootx()+120, parent.winfo_rooty()+180))
        self.wait_window()
    def _pick(self, pt): self.result = pt; self.destroy()

UNICODE_PIECES = {
    chess.PAWN:   {chess.WHITE: '\u2659', chess.BLACK: '\u265F'},
    chess.KNIGHT: {chess.WHITE: '\u2658', chess.BLACK: '\u265E'},
    chess.BISHOP: {chess.WHITE: '\u2657', chess.BLACK: '\u265D'},
    chess.ROOK:   {chess.WHITE: '\u2656', chess.BLACK: '\u265C'},
    chess.QUEEN:  {chess.WHITE: '\u2655', chess.BLACK: '\u265B'},
    chess.KING:   {chess.WHITE: '\u2654', chess.BLACK: '\u265A'},
}

SQ_SIZE = 64; MARGIN = 24; BOARD_PX = SQ_SIZE * 8
COLORS = ('#F0D9B5', '#B58863'); LAST_MOVE = '#BACA2B'

class ChessGUI:
    def __init__(self, root, cfg=None):
        self.root = root; self.root.title('AlphaZero Chess')
        self.cfg = cfg or Config()
        self.cfg.num_simulations = getattr(self.cfg, 'num_simulations', 100) or 100
        self.device = self.cfg.device
        if self.device == 'cuda' and not torch.cuda.is_available():
            self.device = 'cpu'; self.cfg.device = 'cpu'
        self.board = chess.Board(); self.selected_sq = None
        self.legal_squares = set(); self.last_move = None
        self.thinking = False; self.game_over = False
        self.play_as = chess.WHITE; self._eval_score = 0.0; self._top_moves = []
        self._train_stats = TrainingStats()
        self._train_thread = None
        self._training_loop = False
        self._live_game_id = -1
        self._anim_moves = []; self._anim_idx = 0; self._anim_speed = 30
        self._show_train_board = False; self._train_board = chess.Board()
        self._build_ui()
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)
        ok = self._load_model()
        if not ok: self.status_var.set('No checkpoint found -- AI disabled')
        self._redraw(); self._update_status()

    def _build_ui(self):
        main = tk.Frame(self.root, padx=10, pady=10, bg='#f0f0f0'); main.pack()
        bf = tk.Frame(main, bg='#f0f0f0'); bf.pack(side=tk.LEFT)
        self.canvas = tk.Canvas(bf, width=BOARD_PX+MARGIN*2+4, height=BOARD_PX+MARGIN*2+4,
                                highlightthickness=0, bg='#f0f0f0')
        self.canvas.pack(); self.canvas.bind('<Button-1>', self._on_click)
        side = tk.Frame(main, padx=10, bg='#f0f0f0'); side.pack(side=tk.RIGHT, fill=tk.Y)
        self.status_var = tk.StringVar(value='Loading...')
        tk.Label(side, textvariable=self.status_var, font=('TkDefaultFont', 11, 'bold'),
                 bg='#f0f0f0', wraplength=200).pack(pady=(0, 3))
        ef = tk.Frame(side, height=18, bg='#ddd', bd=1, relief=tk.SUNKEN)
        ef.pack(fill=tk.X, pady=(0, 5)); ef.pack_propagate(False)
        self.eval_cv = tk.Canvas(ef, height=18, highlightthickness=0, bg='#ddd')
        self.eval_cv.pack(fill=tk.X)
        self.top_var = tk.StringVar(value='')
        tk.Label(side, textvariable=self.top_var, font=('Consolas', 9),
                 fg='#333', bg='#f0f0f0', justify=tk.LEFT, width=28, anchor='w').pack(pady=(0, 5))
        mf = tk.Frame(side, bg='#f0f0f0'); mf.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        self.mt = tk.Text(mf, width=26, height=10, font=('Consolas', 9),
                          bg='#fafafa', fg='#222', relief=tk.SUNKEN, bd=1)
        self.mt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sc = tk.Scrollbar(mf, command=self.mt.yview); sc.pack(side=tk.RIGHT, fill=tk.Y)
        self.mt.config(yscrollcommand=sc.set)
        sf = tk.Frame(side, bg='#f0f0f0'); sf.pack(fill=tk.X, pady=(2, 4))
        tk.Label(sf, text='Sims:', font=('TkDefaultFont', 9), bg='#f0f0f0').pack(side=tk.LEFT)
        self.sims_v = tk.IntVar(value=self.cfg.num_simulations)
        tk.Spinbox(sf, from_=10, to=1600, increment=10, textvariable=self.sims_v,
                   width=5, font=('TkDefaultFont', 9)).pack(side=tk.LEFT, padx=(2, 8))
        self.side_btn = tk.Button(sf, text='White', command=self._switch_side, width=8)
        self.side_btn.pack(side=tk.LEFT)
        b1 = tk.Frame(side, bg='#f0f0f0'); b1.pack(fill=tk.X)
        for txt, cmd in [('New Game', self._new_game), ('Undo', self._undo),
                         ('Flip', self._flip), ('Resign', self._resign)]:
            tk.Button(b1, text=txt, command=cmd, width=8).pack(side=tk.LEFT, padx=1)
        b2 = tk.Frame(side, bg='#f0f0f0'); b2.pack(fill=tk.X, pady=(2, 0))
        for txt, cmd in [('Copy FEN', self._copy_fen), ('Load...', self._load_dialog)]:
            tk.Button(b2, text=txt, command=cmd, width=12).pack(side=tk.LEFT, padx=1)
        # Training controls
        tf = tk.LabelFrame(side, text='Training', font=('TkDefaultFont', 9, 'bold'),
                           bg='#f0f0f0', padx=4, pady=4)
        tf.pack(fill=tk.X, pady=(4, 0))
        btnf = tk.Frame(tf, bg='#f0f0f0'); btnf.pack(fill=tk.X)
        self.train_btn = tk.Button(btnf, text='Start Training', command=self._toggle_training,
                                   bg='#4caf50', fg='white', width=14)
        self.train_btn.pack(side=tk.LEFT, padx=(0, 4))
        self.train_status = tk.Label(btnf, text='Idle', font=('TkDefaultFont', 9),
                                     bg='#f0f0f0', fg='#555')
        self.train_status.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._train_vars = {}
        for key, label in [('games', 'Games'), ('win', 'Win'), ('steps', 'Steps'),
                           ('buf', 'Buffer'), ('speed', 'Speed')]:
            f = tk.Frame(tf, bg='#f0f0f0'); f.pack(fill=tk.X)
            tk.Label(f, text=label, font=('TkDefaultFont', 8), width=6, anchor='w',
                     bg='#f0f0f0').pack(side=tk.LEFT)
            v = tk.StringVar(value='--')
            tk.Label(f, textvariable=v, font=('Consolas', 8), anchor='e',
                     bg='#f0f0f0').pack(side=tk.RIGHT, fill=tk.X, expand=True)
            self._train_vars[key] = v
        af = tk.Frame(tf, bg='#f0f0f0'); af.pack(fill=tk.X, pady=(2, 0))
        tk.Label(af, text='Speed', font=('TkDefaultFont', 8), bg='#f0f0f0').pack(side=tk.LEFT)
        self._anim_speed_v = tk.IntVar(value=30)
        tk.Scale(af, from_=1, to=200, orient=tk.HORIZONTAL, variable=self._anim_speed_v,
                 showvalue=False, length=60, bg='#f0f0f0', highlightthickness=0).pack(side=tk.LEFT)
        self._anim_speed_label = tk.Label(af, text='30ms', font=('TkDefaultFont', 7), width=4,
                                          bg='#f0f0f0')
        self._anim_speed_label.pack(side=tk.LEFT)
        def _on_speed_changed(*_):
            self._anim_speed = self._anim_speed_v.get()
            self._anim_speed_label.config(text=f'{self._anim_speed}ms')
        self._anim_speed_v.trace_add('write', _on_speed_changed)
        self._show_train_var = tk.BooleanVar(value=True)
        def _toggle_show(): self._show_train_board = self._show_train_var.get()
        tk.Checkbutton(af, text='Show', variable=self._show_train_var,
                       command=_toggle_show, bg='#f0f0f0', font=('TkDefaultFont', 8)
                       ).pack(side=tk.RIGHT)
        self._train_log_collapsed = True
        self._train_log_btn = tk.Button(tf, text='+ Show Log', command=self._toggle_log,
                                        font=('TkDefaultFont', 8), relief=tk.FLAT)
        self._train_log_btn.pack(fill=tk.X, pady=(2, 0))
        self._train_log_text = tk.Text(tf, height=5, font=('Consolas', 8),
                                       bg='#1e1e1e', fg='#ccc', relief=tk.SUNKEN, bd=1)
        self._train_log_sb = tk.Scrollbar(tf, command=self._train_log_text.yview)
        self._train_log_text.config(yscrollcommand=self._train_log_sb.set)
        self.root.bind('<Control-z>', lambda e: self._undo())
        self.root.bind('<r>', lambda e: self._new_game())
        self.root.bind('<Escape>', lambda e: self._clear_sel())

    def _toggle_log(self):
        if self._train_log_collapsed:
            self._train_log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self._train_log_sb.pack(side=tk.RIGHT, fill=tk.Y)
            self._train_log_btn.config(text='- Hide Log')
        else:
            self._train_log_text.pack_forget()
            self._train_log_sb.pack_forget()
            self._train_log_btn.config(text='+ Show Log')
        self._train_log_collapsed = not self._train_log_collapsed

    def _toggle_training(self):
        if self._training_loop or (self._train_stats and self._train_stats.running):
            self._training_loop = False
            if self._train_stats:
                self._train_stats.stop_requested = True
            self.train_btn.config(text='Stopping...', state=tk.DISABLED)
        else:
            self._start_training()

    def _start_training(self):
        self.train_btn.config(text='Stop Training', bg='#f44336', fg='white', state=tk.NORMAL)
        self._live_game_id = -1
        self._training_loop = True
        def run():
            while self._training_loop:
                stats = TrainingStats()
                stats.target_games = self.cfg.num_selfplay_games
                self._train_stats = stats
                try:
                    main(stats)
                except Exception as e:
                    stats.error = str(e)
                    import traceback; traceback.print_exc()
                    break
            self._train_stats.running = False
        self._train_thread = threading.Thread(target=run, daemon=True)
        self._train_thread.start()
        self._poll_training()
        self._poll_live()

    def _poll_live(self):
        q = self._train_stats.live_queue
        if q is None:
            if self._training_loop or self._train_stats.running:
                self.root.after(100, self._poll_live)
            return
        try:
            while True:
                try:
                    gid, move_uci, fen = q.get_nowait()
                except:
                    break
                if fen is None and move_uci is None:
                    if gid == self._live_game_id:
                        self._live_game_id = -1
                    continue
                if fen and (self._live_game_id < 0 or gid == self._live_game_id):
                    if gid != self._live_game_id:
                        self._live_game_id = gid
                        self.board = chess.Board(fen=fen)
                    if move_uci:
                        self.board.push_uci(move_uci)
                        self.last_move = chess.Move.from_uci(move_uci)
                    self._redraw()
        except:
            pass
        if self._training_loop or self._train_stats.running:
            self.root.after(50, self._poll_live)

    def _start_animation(self, moves, start_fen=None):
        if not moves: return
        self._anim_saved_board = self.board
        self._anim_saved_last = self.last_move
        self._anim_moves = list(moves)
        self._anim_idx = 0
        self.board = chess.Board(fen=start_fen) if start_fen else chess.Board()
        self._redraw()
        self.status_var.set(f'Replay: {len(moves)} moves')
        self.root.after(self._anim_speed * 2, self._anim_step)

    def _end_animation(self):
        self._anim_moves = []
        self.board = self._anim_saved_board
        self.last_move = self._anim_saved_last
        self.status_var.set('Training...')
        self._redraw()

    def _anim_step(self):
        if self._anim_idx >= len(self._anim_moves):
            self._end_animation()
            return
        try:
            move = self._anim_moves[self._anim_idx]
            self.board.push(move)
            self._anim_idx += 1
            self.last_move = move
            self._redraw()
            delay = self._anim_speed * 3
            if self._anim_idx >= len(self._anim_moves):
                delay = min(delay * 2, 2000)
            self.root.after(delay, self._anim_step)
        except:
            self._end_animation()

    def _poll_training(self):
        s = self._train_stats
        if s.running or s.log_lines:
            self.train_status.config(text='Training...' if s.running else 'Done')
            if s.running:
                self._train_vars['games'].set(f'{s.total_games}/{s.target_games}')
                self._train_vars['win'].set(f'{s.win_rate:.1%}')
                self._train_vars['steps'].set(str(s.training_steps))
                self._train_vars['buf'].set(str(s.buffer_size))
                if s.elapsed > 0:
                    gps = s.total_games / s.elapsed
                    self._train_vars['speed'].set(f'{gps:.2f} g/s')
            if s.log_lines:
                last = s.log_lines[-1]
                self._train_log_text.insert(tk.END, last + '\n')
                self._train_log_text.see(tk.END)
                s.log_lines.clear()
            if s.last_moves and not self._anim_moves and not s.live_queue:
                self._start_animation(s.last_moves, s.last_start_fen)
                s.last_moves = []
                s.last_start_fen = ""
        if self._training_loop and not s.running:
            self.train_status.config(text='Restarting...')
        if not s.running and self._train_stats.stop_requested:
            self.train_btn.config(text='Start Training', bg='#4caf50', fg='white', state=tk.NORMAL)
            self.train_status.config(text='Stopped')
            if s.error:
                self.train_status.config(text=f'Error: {s.error}')
        if self._training_loop or s.running or s.log_lines:
            self.root.after(500, self._poll_training)

    def _clear_sel(self):
        self.selected_sq = None; self.legal_squares = set(); self._redraw()

    def _load_model(self, path=None):
        self.model = None
        if path is None:
            d = self.cfg.checkpoint_dir
            if not os.path.exists(d): return False
            ckpts = [f for f in os.listdir(d) if f.endswith('.pt')]
            if not ckpts: return False
            best = [f for f in ckpts if f.startswith('best')]
            path = os.path.join(d, best[0] if best else sorted(ckpts)[-1])
        for attempt_device in [self.device, 'cpu']:
            try:
                s = torch.load(path, map_location=attempt_device, weights_only=False)
                self.model = AZNet(self.cfg).to(attempt_device)
                self.model.load_state_dict(s['model_state_dict'])
                self.model.eval()
                self.device = attempt_device
                n = sum(p.numel() for p in self.model.parameters())
                self.status_var.set(f'Loaded: {os.path.basename(path)} ({n/1e6:.1f}M)')
                return True
            except Exception:
                if attempt_device == 'cpu':
                    self.status_var.set(f'Load error: see console')
                    import traceback; traceback.print_exc()
                    return False

    def _load_dialog(self):
        from tkinter import filedialog
        p = filedialog.askopenfilename(initialdir=self.cfg.checkpoint_dir,
                                       title='Select checkpoint', filetypes=[('PyTorch', '*.pt')])
        if p: self._load_model(p)

    def _draw_board(self):
        self.canvas.delete('all'); ox, oy = MARGIN, MARGIN
        flip = getattr(self, '_flipped', False)
        for r in range(8):
            for f in range(8):
                dr = 7-r if not flip else r
                df = f if not flip else 7-f
                x, y = ox+f*SQ_SIZE, oy+r*SQ_SIZE
                c = COLORS[(f+dr)%2]
                self.canvas.create_rectangle(x, y, x+SQ_SIZE, y+SQ_SIZE, fill=c, outline='')
                sq = chess.square(df, dr); p = self.board.piece_at(sq)
                if self.last_move:
                    for ms in (self.last_move.from_square, self.last_move.to_square):
                        mf, mr = chess.square_file(ms), chess.square_rank(ms)
                        mx = ox+(mf if not flip else 7-mf)*SQ_SIZE
                        my = oy+(7-mr if not flip else mr)*SQ_SIZE
                        self.canvas.create_rectangle(mx, my, mx+SQ_SIZE, my+SQ_SIZE, fill=LAST_MOVE, outline='')
                if sq == self.selected_sq:
                    self.canvas.create_rectangle(x, y, x+SQ_SIZE, y+SQ_SIZE, fill='', outline='#0a0', width=3)
                if self.board.is_check() and p and p.piece_type == chess.KING and p.color == self.board.turn:
                    self.canvas.create_oval(x+4, y+4, x+SQ_SIZE-4, y+SQ_SIZE-4, fill='', outline='#d00', width=3)
                if p:
                    self.canvas.create_text(x+SQ_SIZE//2, y+SQ_SIZE//2, text=UNICODE_PIECES[p.piece_type][p.color],
                                            font=('Segoe UI Symbol', 32), fill='#000')
        for sq in self.legal_squares:
            mf, mr = chess.square_file(sq), chess.square_rank(sq)
            cx = ox+(mf if not flip else 7-mf)*SQ_SIZE+SQ_SIZE//2
            cy = oy+(7-mr if not flip else mr)*SQ_SIZE+SQ_SIZE//2
            r = 7 if self.board.piece_at(sq) else 4
            self.canvas.create_oval(cx-r, cy-r, cx+r, cy+r, fill='#666666', outline='')
        for i in range(8):
            d = i if not flip else 7-i
            for pos, anc in [((ox+i*SQ_SIZE+SQ_SIZE//2, oy-10), 'n'),
                             ((ox+i*SQ_SIZE+SQ_SIZE//2, oy+8*SQ_SIZE+8), 's')]:
                self.canvas.create_text(pos[0], pos[1], text=chr(ord('a')+d), font=('TkDefaultFont', 9), fill='#555')
            for anc in ['w', 'e']:
                x = MARGIN+(4 if anc=='w' else BOARD_PX+MARGIN-4)
                self.canvas.create_text(x, oy+i*SQ_SIZE+SQ_SIZE//2, text=str(d+1),
                                        font=('TkDefaultFont', 9), fill='#555')

    def _draw_eval(self):
        self.eval_cv.delete('all')
        w = self.eval_cv.winfo_width() or 200
        s = max(-1, min(1, self._eval_score))
        f = (s+1)/2
        self.eval_cv.create_rectangle(0, 0, w*f, 18, fill='#fff', outline='')
        self.eval_cv.create_rectangle(w*f, 0, w, 18, fill='#222', outline='')
        self.eval_cv.create_line(w//2, 0, w//2, 18, fill='#888')
        self.eval_cv.create_text(w//2, 9, text=f'{s:.2f}', font=('Consolas', 9, 'bold'),
                                 fill='#000' if f>0.5 else '#fff')

    def _redraw(self):
        self._draw_board(); self._draw_eval()

    def _on_click(self, event):
        if self.thinking or self.game_over: return
        if self._train_stats and self._train_stats.running: return
        ox, oy = MARGIN, MARGIN; f = (event.x-ox)//SQ_SIZE; r = (event.y-oy)//SQ_SIZE
        if not (0 <= f < 8 and 0 <= r < 8): return
        flip = getattr(self, '_flipped', False)
        sq = chess.square(f if not flip else 7-f, 7-r if not flip else r)
        p = self.board.piece_at(sq)
        if self.selected_sq is not None and sq in self.legal_squares:
            promo_moves = [m for m in self.board.legal_moves
                           if m.from_square == self.selected_sq and m.to_square == sq]
            normal = [m for m in promo_moves if not m.promotion]
            if normal: self._human_move(normal[0]); return
            if promo_moves:
                dlg = PromotionDialog(self.root, self.board.turn)
                for m in promo_moves:
                    if m.promotion == dlg.result: self._human_move(m); return
                self._human_move(promo_moves[0]); return
        if p and p.color == self.board.turn:
            self.selected_sq = sq
            self.legal_squares = {m.to_square for m in self.board.legal_moves if m.from_square == sq}
        else:
            self.selected_sq = None; self.legal_squares = set()
        self._redraw()

    def _preview_move(self, move, callback):
        self._redraw()
        ox, oy = MARGIN, MARGIN
        flip = getattr(self, '_flipped', False)
        for sq, color in [(move.from_square, '#ffdd00'), (move.to_square, '#88ff88')]:
            sf, sr = chess.square_file(sq), chess.square_rank(sq)
            x = ox + (sf if not flip else 7-sf) * SQ_SIZE
            y = oy + (7-sr if not flip else sr) * SQ_SIZE
            self.canvas.create_rectangle(x, y, x+SQ_SIZE, y+SQ_SIZE, fill=color, outline='#444', width=2)
        self.canvas.update()
        self.root.after(200, callback)

    def _human_move(self, move):
        self.selected_sq = None; self.legal_squares = set()
        self._preview_move(move, lambda m=move: self._human_finish(m))

    def _human_finish(self, move):
        self.board.push(move); self.last_move = move
        self._log(move, 'You'); self._redraw(); self._update_status()
        if not self.board.is_game_over(): self.root.after(10, self._trigger_ai)

    def _trigger_ai(self):
        if self.board.turn != self.play_as and not self.board.is_game_over():
            self.root.after(10, self._ai_move)

    def _ai_move(self):
        if self.board.is_game_over() or self.thinking: return
        self.thinking = True; self.status_var.set('Thinking...')
        self.root.config(cursor='watch'); self.root.update()
        threading.Thread(target=self._ai_thread, daemon=True).start()

    def _on_close(self): self.thinking = False; self.game_over = True; self.root.destroy()

    def _ai_thread(self):
        try:
            if self.model is None: self.root.after(0, self._no_model); return
            self.cfg.num_simulations = self.sims_v.get()
            board_cpy = self.board.copy()
            policy, root_val, info, _ = run_mcts(self.model, board_cpy, self.cfg, add_noise=False, temp=0.0, num_simulations=self.cfg.num_simulations)
            eval_score = info['root_value']
            visits = info['visits']
            move_data = []
            for m in board_cpy.legal_moves:
                idx = move_to_index(m, board_cpy)
                v = int(visits[idx])
                if v > 0: move_data.append((v, m))
            move_data.sort(key=lambda x: -x[0])
            best_move = move_data[0][1] if move_data else None
            total_v = sum(v for v, _ in move_data)
            top_info = []
            for v, m in move_data[:5]:
                try: san = board_cpy.san(m)
                except Exception: san = str(m)
                top_info.append((san, v / max(1, total_v) * 100))
            self.root.after(0, self._ai_done, best_move, top_info, eval_score)
        except Exception as e:
            import traceback; self.root.after(0, self._ai_err, str(e))

    def _no_model(self): self.thinking = False; self.root.config(cursor=''); self.status_var.set('No model loaded')
    def _ai_done(self, move, top_info, eval_score):
        self.thinking = False; self.root.config(cursor='')
        self._eval_score = eval_score; self._top_moves = top_info
        self.top_var.set('\n'.join(f'{s} {p:.0f}%' for s, p in top_info))
        if move is None or self.game_over: return
        self._preview_move(move, lambda m=move: self._ai_finish(m))

    def _ai_finish(self, move):
        self.board.push(move); self.last_move = move
        self._log(move, 'AI'); self._redraw(); self._update_status()
        if not self.board.is_game_over() and self.board.turn != self.play_as:
            self.root.after(50, self._ai_move)
    def _ai_err(self, msg): self.thinking = False; self.root.config(cursor=''); self.status_var.set('AI error (see console)'); print(f'GUI AI error: {msg}')
    def _update_status(self):
        if self.board.is_game_over():
            self.game_over = True
            m = {'1-0': 'White wins!', '0-1': 'Black wins!', '1/2-1/2': 'Draw!'}
            self.status_var.set(f'Game Over: {m.get(self.board.result(), self.board.result())}')
        else:
            self.game_over = False
            self.status_var.set(f'{"White" if self.board.turn == chess.WHITE else "Black"}\'s turn')
    def _log(self, move, tag):
        try: san = self.board.san(move)
        except Exception: san = str(move)
        n = len(self.board.move_stack)
        prefix = f'{(n+1)//2}. ' if tag == 'You' else '     '
        self.mt.insert(tk.END, f'{prefix}{tag}: {san}\n'); self.mt.see(tk.END)
    def _switch_side(self):
        self.play_as = chess.BLACK if self.play_as == chess.WHITE else chess.WHITE
        self.side_btn.config(text='White' if self.play_as == chess.WHITE else 'Black')
        if self.board.turn != self.play_as and not self.board.is_game_over(): self.root.after(100, self._ai_move)
    def _new_game(self):
        if self.board.move_stack and not messagebox.askyesno('New Game', 'Start new game?'): return
        self.board = chess.Board(); self.selected_sq = None; self.legal_squares = set(); self.last_move = None
        self.thinking = False; self.game_over = False; self._eval_score = 0.0; self._top_moves = []
        self.mt.delete('1.0', tk.END); self.top_var.set(''); self.root.config(cursor='')
        self._redraw(); self._update_status()
        if self.board.turn != self.play_as: self.root.after(100, self._ai_move)
    def _undo(self):
        if self.thinking or self.game_over: return
        for _ in range(min(2, len(self.board.move_stack))): self.board.pop()
        self.last_move = self.board.peek() if self.board.move_stack else None
        self.selected_sq = None; self.legal_squares = set(); self._top_moves = []; self.top_var.set('')
        lines = self.mt.get('1.0', tk.END).strip().split('\n')
        self.mt.delete('1.0', tk.END)
        for L in lines[:-2]: self.mt.insert(tk.END, L + '\n')
        self._redraw(); self._update_status()
        if self.board.turn != self.play_as and not self.board.is_game_over(): self.root.after(100, self._ai_move)
    def _flip(self): self._flipped = not getattr(self, '_flipped', False); self._redraw()
    def _resign(self):
        if self.game_over: return
        if messagebox.askyesno('Resign', f'Resign as {"White" if self.play_as==chess.WHITE else "Black"}?'):
            self.thinking = False; self.game_over = True; self.root.config(cursor='')
            result = '0-1' if self.play_as==chess.WHITE else '1-0'
            self.mt.insert(tk.END, f'{result} Resign\n')
            self.status_var.set(f'You resigned ({result})')
    def _copy_fen(self):
        self.root.clipboard_clear(); self.root.clipboard_append(self.board.fen())
        self.status_var.set('FEN copied')

def launch_gui(cfg=None):
    root = tk.Tk()
    gui = ChessGUI(root, cfg)
    try:
        root.mainloop()
    finally:
        if gui._train_stats.running:
            gui._train_stats.stop_requested = True
            gui._train_thread.join(timeout=10)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AlphaZero Chess Training", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    for name, typ in Config.__dataclass_fields__.items():
        t = typ.type
        default = typ.default
        if t is bool:
            parser.add_argument(f'--{name}', type=lambda x: x.lower() in ('true','1','yes'), default=default)
        elif t is int:
            parser.add_argument(f'--{name}', type=int, default=default)
        elif t is float:
            parser.add_argument(f'--{name}', type=float, default=default)
        elif t is str:
            parser.add_argument(f'--{name}', type=str, default=default)
    parser.add_argument('--play', action='store_true', help='Launch GUI to play against a trained model')
    args = parser.parse_args()
    for name in Config.__dataclass_fields__:
        val = getattr(args, name)
        if val != getattr(Config, name):
            setattr(CFG, name, val)
            print(f"  {name} = {val}")
    if args.play:
        launch_gui(CFG)
    else:
        try:
            main()
        except KeyboardInterrupt:
            print("\nInterrupted by user")