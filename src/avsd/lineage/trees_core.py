"""Module B2 core: candidate parents, parent posterior, MAP tree and posterior samples (SPEC 6.4.2-6.4.4).

Occurrences of one unit are in time order (global index order: unit, then time),
so a candidate parent always has a lower index and every parent assignment is a
forest.

Candidate parents of occurrence i (agent a_i, time t_i), SPEC 6.4.2:

- chat message j, t_j < t_i, within L_B (3 run days on the run-day clock):
  for an agent child, a_i was in j's room when j was posted and acted that run
  day (`exposure="main"`, decisions "Module B2 exposure"; a 2 s tolerance
  around room moves is folded into the visibility masks), or was in that room
  at some time between t_j and t_i (`exposure="ever"`, sensitivity); a human
  child sees every room;
- a_i's own memory occurrence j while the unit is still in a_i's memory at t_i
  (B1 presence under the chosen rule set; chat children only, because a
  memory occurrence is the first memory version that holds the unit);
- a_i's own search answer j within L_B;
- env_i (agent children): a_i's own turns hold the unit within L_B before t_i.
  `env_rule="precede"` (main): only hits before a_i's first exposure through
  any other candidate count, so a turn that repeats what a_i had already seen
  is not an independent observation; `env_rule="any"` follows SPEC 6.4.2
  literally. The env node's time is the earliest hit in the window.
- a search answer's candidates are the chat messages of the village days its
  query covered (t_j < t_i, any room).

Posterior: P(parent = j) is proportional to K_ij exp(gamma S_ij) (E_ij is the
candidate set). S_ij counts the non-root variants i and j share: quantity values
under a context key that the root holds with a different value, and rare
4-grams the root lacks (SPEC 6.4.3). env has S = 0: the environment is the
source, not a copy. The root of the S term is the unit's first occurrence.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from avsd.lineage.trees_kernel import KEY_CODE, EdgeTimes

CHAT, MEMORY, SEARCH = 0, 1, 2
SRC_NAMES = ("chat", "memory", "search")
ENV = -2  # parent code of env_i
NONE = -1  # no parent (root)
L_B_DEFAULT = 3.0  # run days
I64_MAX = np.iinfo(np.int64).max
_MIX = np.uint64(0xD6E8FEB86659FD93)


def variant_id(key: np.ndarray, val: np.ndarray) -> np.ndarray:
    with np.errstate(over="ignore"):
        return (np.asarray(key, dtype=np.int64).view(np.uint64) * _MIX
                + np.asarray(val, dtype=np.int64).view(np.uint64)).view(np.int64)


class Ragged:
    """Rows of variable length stored as one value array and offsets."""

    def __init__(self, values: np.ndarray, offsets: np.ndarray):
        self.values = np.asarray(values)
        self.offsets = np.asarray(offsets, dtype=np.int64)

    def __getitem__(self, i: int) -> np.ndarray:
        return self.values[self.offsets[i]:self.offsets[i + 1]]

    def __len__(self) -> int:
        return len(self.offsets) - 1

    def lengths(self) -> np.ndarray:
        return np.diff(self.offsets)

    @classmethod
    def from_lists(cls, rows: list, dtype=np.int64) -> "Ragged":
        lens = np.array([len(r) for r in rows], dtype=np.int64)
        vals = np.concatenate([np.asarray(r, dtype=dtype) for r in rows]) if len(rows) and lens.sum() else \
            np.zeros(0, dtype=dtype)
        return cls(vals, np.concatenate([[0], np.cumsum(lens)]))

    def take(self, idx: np.ndarray) -> "Ragged":
        return Ragged.from_lists([self[int(i)] for i in idx], self.values.dtype)


@dataclass
class Occ:
    """All occurrences, sorted by (unit, time); `start[u]:start[u+1]` is unit u."""

    start: np.ndarray  # int64, n_units + 1
    ts: np.ndarray  # int64 microseconds UTC
    t: np.ndarray  # float64 active seconds
    pos: np.ndarray  # float64 run-day clock
    src: np.ndarray  # int8 CHAT, MEMORY, SEARCH
    actor: np.ndarray  # int16 agent index, -1 human
    vis: np.ndarray  # uint64 bit mask of agents that see a chat occurrence (main rule)
    room: np.ndarray  # int32 room code, -1 none
    vday: np.ndarray  # int32 village day
    s0: np.ndarray  # int32 first covered village day of a search answer, -1 otherwise
    s1: np.ndarray  # int32 last covered village day
    rz: np.ndarray  # int32 run-day realization (chat), -1 otherwise
    tin: np.ndarray  # float64 t_in_day
    date: np.ndarray  # datetime64[D] PT date
    mem_end: np.ndarray  # int64 microseconds: end of memory presence (I64_MAX if never lost)
    mem_rs: dict[int, tuple[np.ndarray, np.ndarray]]  # restorations: index -> (starts, ends) microseconds
    qv_key: "Ragged"  # per occurrence: int64 quantity context keys
    qv_val: "Ragged"  # per occurrence: int64 values (aligned with qv_key)
    grams: "Ragged"  # per occurrence: int64 rare grams
    env: dict[tuple[int, int], tuple[np.ndarray, np.ndarray, np.ndarray]]  # (unit, agent) -> ts, t, pos of hits
    room_spells: dict | None = None  # agent -> {room code: (starts, ends)} microseconds (exposure "ever")

    @property
    def n(self) -> int:
        return len(self.ts)

    @property
    def n_units(self) -> int:
        return len(self.start) - 1


@dataclass
class Cands:
    """Candidate parent rows, grouped by child (rows of one child are contiguous)."""

    child: np.ndarray  # int64 global index
    parent: np.ndarray  # int64 global index, ENV for env_i
    key: np.ndarray  # int8 kernel key
    dt: np.ndarray  # float64 active seconds
    S: np.ndarray  # int32 shared non-root variants
    same_block: np.ndarray  # bool
    tau: np.ndarray  # float64 t_in_day difference
    source_class: np.ndarray  # int8 (self, other, human, system), -1 if the parent is not chat
    t_env: np.ndarray  # float64 active seconds of the env node (nan otherwise)
    stats: dict = field(default_factory=dict)
    n_var: np.ndarray | None = None  # per occurrence: number of non-root variants (values and grams)
    n_var_q: np.ndarray | None = None  # per occurrence: number of non-root values (SPEC appendix A)
    S_q: np.ndarray | None = None  # per row: shared non-root values

    def subset(self, m: np.ndarray) -> "Cands":
        c = Cands(self.child[m], self.parent[m], self.key[m], self.dt[m], self.S[m], self.same_block[m],
                  self.tau[m], self.source_class[m], self.t_env[m], dict(self.stats))
        c.n_var, c.n_var_q = self.n_var, self.n_var_q
        c.S_q = None if self.S_q is None else self.S_q[m]
        return c

    @property
    def n(self) -> int:
        return len(self.child)

    def edge_times(self, occ: Occ) -> EdgeTimes:
        """Edge inputs of a time term; rooms as room ids (`occ.room_ids`, codes if the ids are unknown)."""
        code = occ.room[self.child]
        ids = getattr(occ, "room_ids", None)
        if ids is not None:
            room = np.where(code >= 0, ids[np.maximum(code, 0)], None).astype(object)
        else:
            room = code
        return EdgeTimes(self.key, self.dt, self.same_block, self.tau, self.source_class, room,
                         occ.date[self.child])

    def offsets(self) -> tuple[np.ndarray, np.ndarray]:
        """Children with candidates and the start of their rows (plus the end)."""
        if not len(self.child):
            return np.zeros(0, np.int64), np.zeros(1, np.int64)
        brk = np.flatnonzero(np.diff(self.child)) + 1
        starts = np.concatenate([[0], brk, [len(self.child)]]).astype(np.int64)
        return self.child[starts[:-1]], starts


def nonroot_variants(occ: Occ, lo: int, hi: int, quantity_only: bool = False) -> list[np.ndarray]:
    """Non-root variant ids of the occurrences lo..hi-1 of one unit (root = lo): quantity values under a
    context key the root holds with another value (the "non-root values" of SPEC appendix A) and, unless
    `quantity_only`, rare 4-grams the root lacks (SPEC 6.4.3)."""
    rk, rv = occ.qv_key[lo], occ.qv_val[lo]
    root_vals: dict[int, set[int]] = {}
    for k, v in zip(rk.tolist(), rv.tolist()):
        root_vals.setdefault(k, set()).add(v)
    root_grams = occ.grams[lo]
    out = []
    for i in range(lo, hi):
        if i == lo:
            out.append(np.zeros(0, np.int64))
            continue
        k, v = occ.qv_key[i], occ.qv_val[i]
        if len(k):
            m = np.fromiter(((kk in root_vals) and (vv not in root_vals[kk]) for kk, vv in zip(k.tolist(), v.tolist())),
                            dtype=bool, count=len(k))
            qv = variant_id(k[m], v[m])
        else:
            qv = np.zeros(0, np.int64)
        if quantity_only:
            out.append(np.unique(qv))
            continue
        g = occ.grams[i]
        if len(g) and len(root_grams):
            g = g[~np.isin(g, root_grams)]
        out.append(np.unique(np.concatenate([qv, g])) if (len(qv) or len(g)) else np.zeros(0, np.int64))
    return out


def shared_counts(var: list[np.ndarray]) -> np.ndarray:
    """S[i, j] = |V_i & V_j| for the occurrences of one unit."""
    n = len(var)
    lens = [len(v) for v in var]
    if sum(lens) == 0:
        return np.zeros((n, n), dtype=np.int32)
    from scipy import sparse

    allv = np.concatenate([v for v in var if len(v)])
    uniq, inv = np.unique(allv, return_inverse=True)
    rows = np.repeat(np.arange(n), lens)
    B = sparse.csr_matrix((np.ones(len(allv), dtype=np.int32), (rows, inv)), shape=(n, len(uniq)))
    return (B @ B.T).toarray().astype(np.int32)


def _present(occ: Occ, j: np.ndarray, ts_i: int) -> np.ndarray:
    """Memory occurrences j still in their agent's memory at ts_i."""
    ok = (occ.ts[j] <= ts_i) & (ts_i < occ.mem_end[j])
    for k in np.flatnonzero(~ok):
        rs = occ.mem_rs.get(int(j[k]))
        if rs is not None:
            s, e = rs
            if np.any((s <= ts_i) & (ts_i < e)):
                ok[k] = True
    return ok


def _in_room_between(occ: Occ, agent: int, room: int, t0: int, t1: int) -> bool:
    sp = (occ.room_spells or {}).get(agent, {}).get(room)
    if sp is None:
        return False
    s, e = sp
    k = int(np.searchsorted(e, t0, side="right"))
    return k < len(s) and s[k] < t1


def unit_candidates(occ: Occ, u: int, L: float = L_B_DEFAULT, env_rule: str = "precede",
                    exposure: str = "main") -> dict[str, np.ndarray]:
    """Candidate rows of one unit (see the module docstring)."""
    lo, hi = int(occ.start[u]), int(occ.start[u + 1])
    n = hi - lo
    ts, pos, src, actor = occ.ts[lo:hi], occ.pos[lo:hi], occ.src[lo:hi], occ.actor[lo:hi]
    var = nonroot_variants(occ, lo, hi)
    S = shared_counts(var)
    var_q = nonroot_variants(occ, lo, hi, quantity_only=True)
    S_q = shared_counts(var_q)
    rows: dict[str, list] = {k: [] for k in ("child", "parent", "key", "S", "S_q", "t_env")}
    n_env_dropped = 0
    for i in range(1, n) if n else ():
        ti = ts[i]
        earlier = ts[:i] < ti
        if not earlier.any():
            continue
        js = np.flatnonzero(earlier)
        si, ai = int(src[i]), int(actor[i])
        within = (pos[i] - pos[js]) <= L
        if si == SEARCH:
            m = (src[js] == CHAT) & (occ.vday[lo + js] >= occ.s0[lo + i]) & (occ.vday[lo + js] <= occ.s1[lo + i])
            sel = js[m]
            keys = np.full(len(sel), KEY_CODE["history>search"], dtype=np.int8)
        elif ai < 0:
            sel = js[(src[js] == CHAT) & within]
            keys = np.full(len(sel), KEY_CODE["chat>human"], dtype=np.int8)
        else:
            chat = (src[js] == CHAT) & within
            if exposure == "main":
                chat &= ((occ.vis[lo + js] >> np.uint64(ai)) & np.uint64(1)).astype(bool)
            elif exposure == "ever":
                for q in np.flatnonzero(chat):
                    j = int(js[q])
                    if actor[j] != ai and not _in_room_between(occ, ai, int(occ.room[lo + j]), int(ts[j]), int(ti)):
                        chat[q] = False
            elif exposure != "all":
                raise ValueError(f"exposure must be main, ever or all, not {exposure!r}")
            mem = np.zeros(len(js), dtype=bool)
            if si == CHAT:
                mj = (src[js] == MEMORY) & (actor[js] == ai)
                if mj.any():
                    mem[mj] = _present(occ, lo + js[mj], int(ti))
            srch = (src[js] == SEARCH) & (actor[js] == ai) & within
            sel = js[chat | mem | srch]
            keys = np.empty(len(sel), dtype=np.int8)
            sj = src[sel]
            self_ = actor[sel] == ai
            child_mem = si == MEMORY
            keys[(sj == CHAT) & ~self_] = KEY_CODE["chat>memory:other" if child_mem else "chat>chat:other"]
            keys[(sj == CHAT) & self_] = KEY_CODE["chat>memory:self" if child_mem else "chat>chat:self"]
            keys[sj == MEMORY] = KEY_CODE["memory>chat"]
            keys[sj == SEARCH] = KEY_CODE["search>memory" if child_mem else "search>chat"]
            hits = occ.env.get((u, ai))
            if hits is not None:
                hts, ht, hp = hits
                w = (hts < ti) & (hp >= pos[i] - L)
                if w.any():
                    k0 = int(np.flatnonzero(w)[0])
                    first_exposure = ts[sel].min() if len(sel) else I64_MAX
                    if env_rule == "any" or hts[k0] < first_exposure:
                        rows["child"].append(lo + i)
                        rows["parent"].append(ENV)
                        rows["key"].append(KEY_CODE["env>memory" if child_mem else "env>chat"])
                        rows["S"].append(0)
                        rows["S_q"].append(0)
                        rows["t_env"].append(float(ht[k0]))
                    else:
                        n_env_dropped += 1
        for j, k in zip(sel.tolist(), keys.tolist()):
            rows["child"].append(lo + i)
            rows["parent"].append(lo + j)
            rows["key"].append(k)
            rows["S"].append(int(S[i, j]))
            rows["S_q"].append(int(S_q[i, j]))
            rows["t_env"].append(np.nan)
    out = {"child": np.array(rows["child"], dtype=np.int64), "parent": np.array(rows["parent"], dtype=np.int64),
           "key": np.array(rows["key"], dtype=np.int8), "S": np.array(rows["S"], dtype=np.int32),
           "S_q": np.array(rows["S_q"], dtype=np.int32),
           "t_env": np.array(rows["t_env"], dtype=np.float64), "n_env_dropped": n_env_dropped,
           "lo": lo, "n_var": np.array([len(v) for v in var], dtype=np.int32),
           "n_var_q": np.array([len(v) for v in var_q], dtype=np.int32)}
    # Rows of one child must be contiguous and in child order; env rows were appended first.
    if len(out["child"]):
        o = np.lexsort((out["parent"], out["child"]))
        for k in ("child", "parent", "key", "S", "S_q", "t_env"):
            out[k] = out[k][o]
    return out


def finish_cands(occ: Occ, parts: list[dict]) -> Cands:
    """Concatenate unit rows and add intervals and the module A hook fields."""
    def cat(k, dt):
        xs = [p[k] for p in parts if len(p[k])]
        return np.concatenate(xs).astype(dt) if xs else np.zeros(0, dt)

    child, parent = cat("child", np.int64), cat("parent", np.int64)
    key, S, t_env = cat("key", np.int8), cat("S", np.int32), cat("t_env", np.float64)
    S_q = cat("S_q", np.int32) if any("S_q" in p for p in parts) else np.zeros(len(child), np.int32)
    o = np.lexsort((parent, child))
    child, parent, key, S, S_q, t_env = child[o], parent[o], key[o], S[o], S_q[o], t_env[o]
    is_env = parent == ENV
    pj = np.where(is_env, child, parent)
    t_par = np.where(is_env, t_env, occ.t[pj])
    dt = occ.t[child] - t_par
    chat_pair = (~is_env) & (occ.src[pj] == CHAT) & (occ.src[child] == CHAT)
    same_block = chat_pair & (occ.rz[child] == occ.rz[pj]) & (occ.rz[child] >= 0)
    tau = np.where(same_block, occ.tin[child] - occ.tin[pj], np.nan)
    sc = np.full(len(child), -1, dtype=np.int8)
    par_chat = (~is_env) & (occ.src[pj] == CHAT)
    pa, ca = occ.actor[pj], occ.actor[child]
    sc[par_chat & (pa < 0)] = 2
    sc[par_chat & (pa >= 0) & (pa == ca)] = 0
    sc[par_chat & (pa >= 0) & (pa != ca)] = 1
    stats = {"env_dropped_by_precede": int(sum(p.get("n_env_dropped", 0) for p in parts))}
    n_var = np.zeros(occ.n, dtype=np.int32)
    n_var_q = np.zeros(occ.n, dtype=np.int32)
    for p in parts:
        if "n_var" in p and len(p["n_var"]):
            n_var[p["lo"]:p["lo"] + len(p["n_var"])] = p["n_var"]
            n_var_q[p["lo"]:p["lo"] + len(p["n_var_q"])] = p["n_var_q"]
    c = Cands(child, parent, key, np.maximum(dt, 0.0), S, same_block, tau, sc, t_env, stats)
    c.n_var, c.n_var_q, c.S_q = n_var, n_var_q, S_q
    return c


def all_candidates(occ: Occ, units: np.ndarray | None = None, L: float = L_B_DEFAULT, env_rule: str = "precede",
                   exposure: str = "main") -> Cands:
    units = np.arange(occ.n_units) if units is None else units
    return finish_cands(occ, [unit_candidates(occ, int(u), L, env_rule, exposure) for u in units])


def posterior(c: Cands, K: np.ndarray, gamma: float, use_time: bool = True, use_content: bool = True
              ) -> np.ndarray:
    """P(parent) per candidate row (rows of a child sum to 1)."""
    if not c.n:
        return np.zeros(0)
    logw = np.zeros(c.n)
    if use_time:
        logw += np.log(np.maximum(K, 1e-300))
    if use_content:
        logw += gamma * c.S
    _, starts = c.offsets()
    mx = np.maximum.reduceat(logw, starts[:-1])
    w = np.exp(logw - np.repeat(mx, np.diff(starts)))
    tot = np.add.reduceat(w, starts[:-1])
    return w / np.repeat(tot, np.diff(starts))


def map_choice(c: Cands, post: np.ndarray, n_occ: int) -> np.ndarray:
    """Chosen candidate row per occurrence (-1 if it has no candidates), by maximum posterior.
    Ties go to the latest parent (rows are in parent order within a child)."""
    chosen = np.full(n_occ, -1, dtype=np.int64)
    kids, starts = c.offsets()
    for k, (a, b) in enumerate(zip(starts[:-1], starts[1:])):
        p = post[a:b]
        best = np.flatnonzero(p >= p.max() - 1e-12)
        chosen[kids[k]] = a + int(best[-1])
    return chosen


def sample_choice(c: Cands, post: np.ndarray, n_occ: int, rng: np.random.Generator) -> np.ndarray:
    """One posterior draw of the chosen candidate row per occurrence (SPEC 6.4.4)."""
    chosen = np.full(n_occ, -1, dtype=np.int64)
    kids, starts = c.offsets()
    if not len(kids):
        return chosen
    cum = np.cumsum(post)
    base = np.concatenate([[0.0], cum])[starts[:-1]]
    u = base + rng.random(len(kids)) * (cum[starts[1:] - 1] - base)
    pick = np.searchsorted(cum, u, side="left")
    pick = np.minimum(np.maximum(pick, starts[:-1]), starts[1:] - 1)
    chosen[kids] = pick
    return chosen


def forest(c: Cands, chosen: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Parent (global index, ENV or NONE), generation and tree root of every occurrence.

    A child of env_i starts a new subtree at generation 0 (SPEC 6.4.3)."""
    n = len(chosen)
    parent = np.full(n, NONE, dtype=np.int64)
    has = chosen >= 0
    parent[has] = c.parent[chosen[has]]
    gen = np.zeros(n, dtype=np.int32)
    root = np.arange(n, dtype=np.int64)
    _forest_pass(parent, gen, root)
    return parent, gen, root


try:
    from numba import njit

    @njit(cache=False)
    def _forest_pass(parent, gen, root):  # pragma: no cover - compiled
        for i in range(len(parent)):
            p = parent[i]
            if p >= 0:
                gen[i] = gen[p] + 1
                root[i] = root[p]
except ImportError:  # pragma: no cover
    def _forest_pass(parent, gen, root):
        for i in range(len(parent)):
            p = parent[i]
            if p >= 0:
                gen[i] = gen[p] + 1
                root[i] = root[p]


def single_candidate_edges(c: Cands) -> np.ndarray:
    """Rows whose child has exactly one candidate (the kernel fit set, SPEC 6.4.3)."""
    kids, starts = c.offsets()
    one = np.diff(starts) == 1
    return starts[:-1][one]
