"""Per-agent memory chains for module B1: fact-unit states across consolidations.

Path S (SPEC 6.3.1, decisions "Module B1"). Each memory row is a full
snapshot, given here as a list of line hashes (`avsd.lineage.memory` builds
them) and a mapping from line hash to the anchor occurrences on that line.
Rows are the agent's live rows in (created_at, id) order: IDENT rows (no-ops)
and rows of dead lineage branches (generations that no later row descends
from) are removed by the caller.

Definitions (`run_chain`, rules v1):

- Occurrence: (anchor type, value, context key) on a line. Fact unit: the
  occurrence for quantity types (number, money, percent, time), else
  (type, value). U(row) is the set of units on the row's lines.
- A unit enters at its first row (any relation). Its entry index e is the
  number of consolidations at or before that row, so its first trial is
  consolidation e + 1, and trial g is consolidation e + g.
- Consolidation c (a live REWRITE row R_c, input row I_c = the previous live
  row, previous version P_c = R_{c-1}, or the first row for c = 1) is one trial
  for every unit that entered before R_c and was never lost:
  kept if the unit is in U(R_c); otherwise modified if, for some context key
  the unit had on I_c, R_c holds the same (type, context key) with a value
  that P_c did not hold under it; otherwise dropped. Modified and dropped are
  losses: the survival event is the first loss, and S = g - 1 consolidations
  survived. Units never lost are censored after the agent's last
  consolidation (S = number of trials seen).
- After a loss, a unit is restored at the first consolidation whose output
  holds it again ("reappended" if I_c already held it, i.e. it came back in
  appended text, else "recreated" by the consolidation). Later absences after a
  restoration are re-losses. Restorations never reset S.
- Undo rows (revert, trunc_other, and fork_append whose base is not the
  previous row) restore an earlier snapshot. Units that entered after the last
  consolidation and are absent after the undo are removed from tracking, as if
  they had never entered. Consolidations are counted only on live rows, so a
  fork that abandons a rewrite drops that rewrite from every unit's trials.
- Presence spells: maximal runs of rows that hold a unit, over all live rows
  (appends included), for module B2.

Rules v2 (when `AgentInput.v2` is given; computed in the same pass, next to v1):

- Presence fallback: a unit at risk (never lost, or restored and present) that
  has no anchor in R_c still counts as present if its value occurs literally in
  R_c (`anchors.LiteralIndex`): for URL, date, email, phone, agent and entity
  types a surface form of the value anywhere; for time the same value as any
  time anchor or a surface form; for number, money and percent an anchor with
  the same value on a line that also contains the unit's context word. Hashed
  values are matched by hashing candidate strings. Restorations stay
  anchor-based.
- Modified: the old line that held the unit (in I_c) is aligned with R_c:
  lines kept verbatim and unique in both versions anchor a patience
  alignment; inside each changed block an old line is paired with the new
  line at the same offset when the block keeps its length, else with the new
  line that shares the most anchor keys (contexts and values) with it. The
  loss is a modification only if that line holds the unit's (type, context
  key) with a value the old line did not hold under it; otherwise a drop.

Rules v3 (`V2Data.versions` containing "v3"): as v2, except that a time, number,
money or percent unit counts as present through the fallback only if a line of
R_c holds the value (as the regex anchors normalise it) with the unit's context
word adjacent to it (`anchors.ctx_adjacent`: right after the value with up to
two words between, or right before it with only punctuation between). v2, v3
and v1 states are computed in the same pass, from the same entries.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from avsd.events.memory_versions import RELS
from avsd.lineage.anchors import (
    ENTITY_TYPES, HASHABLE_KINDS, TYPES, AnchorExtractor, LiteralIndex, candidate_hashes, keyed_hash,
    name_candidates,
)

REL_CODE: dict[str, int] = {r: i for i, r in enumerate(RELS)}
UNDO_RELS = frozenset({REL_CODE["revert"], REL_CODE["trunc_other"]})
KIND_FULL, KIND_EXT, KIND_COPY = 0, 1, 2
EVENT_CENSORED, EVENT_DROPPED, EVENT_MODIFIED = 0, 1, 2
SRC_NONE, SRC_REAPPENDED, SRC_RECREATED = 0, 1, 2
PAIR_LABELS = ("kept", "modified", "dropped", "new", "restored")
_EMPTY: frozenset[int] = frozenset()
_STRICT_QUANTITY = frozenset(TYPES.index(t) for t in ("number", "money", "percent"))
_TIME = TYPES.index("time")
_CONS_KEYS = ("at_risk", "kept", "dropped", "modified", "restored", "entered", "units_in", "units_out",
              "alive_missing_in", "lines_old", "lines_old_kept", "lines_new", "lines_new_kept")
_CONS2_KEYS = ("at_risk", "kept", "kept_fallback", "dropped", "modified", "restored")


@dataclass
class V2Data:
    """Inputs of the v2 rules for one agent.

    cons_text: text of each consolidation output R_c, by row index.
    in_text: text of the input row I_c, by the row index of a labelled consolidation.
    unit_info: unit -> (stored value, context lemma of the unit, '' for identity types).
    occ_type: anchor type code per local occurrence.
    """

    cons_text: dict[int, str]
    in_text: dict[int, str]
    unit_info: dict[int, tuple[str, str]]
    occ_type: np.ndarray
    salt: bytes
    versions: tuple[str, ...] = ("v2",)  # rule sets to run next to v1: "v2" and/or "v3"
    agent_names: tuple[str, ...] = ()  # for the regex anchors of the v3 adjacency check


@dataclass
class AgentInput:
    """One agent's live rows and its local anchor tables.

    `seg[k]` holds the hashes of the raw lines of row k's own text segment (0 for
    a line without anchor text): the whole row for KIND_FULL, the text from the
    start of the line that holds the end of the base for KIND_EXT (so the row's
    lines are the base's lines without its last one, then seg), nothing for
    KIND_COPY (the row equals its base).
    """

    agent_id: str
    rel: np.ndarray  # int8 REL_CODE per row
    kind: np.ndarray  # int8 KIND_* per row
    base: np.ndarray  # int64 index of the base row, -1 if none
    is_cons: np.ndarray  # bool, live consolidation (REWRITE)
    seg: list[np.ndarray]  # int64 line hashes per row
    line_hash: np.ndarray  # int64 sorted line hashes that carry anchors
    line_ptr: np.ndarray  # int64 offsets into line_occ, len(line_hash) + 1
    line_occ: np.ndarray  # int32 occurrence ids
    occ_unit: np.ndarray  # int32 unit id per occurrence
    occ_tc: np.ndarray  # int64 (type, context) id per occurrence, -1 for an empty context
    occ_val: np.ndarray  # int64 value id per occurrence
    label_rows: frozenset[int] = field(default_factory=frozenset)  # consolidation rows to label
    v2: V2Data | None = None


@dataclass
class AgentResult:
    agent_id: str
    n_cons: int
    units: dict[str, np.ndarray]  # per tracked unit, see run_chain
    spells: dict[str, np.ndarray]  # unit, start_row, end_row (-1 = still present)
    cons: dict[str, np.ndarray]  # per consolidation counts
    pairs: dict[int, list[tuple[int, str, int]]]  # label row -> [(unit, rule label, (type, ctx) id)]
    qa: dict[str, int]
    units2: dict[str, np.ndarray] | None = None  # rules v2, same units in the same order
    cons2: dict[str, np.ndarray] | None = None
    pairs2: dict[int, list[tuple[int, str, int]]] | None = None
    units3: dict[str, np.ndarray] | None = None  # rules v3
    cons3: dict[str, np.ndarray] | None = None
    pairs3: dict[int, list[tuple[int, str, int]]] | None = None


def _line_maps(inp: AgentInput) -> tuple[dict[int, frozenset[int]], dict[int, frozenset[int]]]:
    occ_of: dict[int, frozenset[int]] = {}
    unit_of: dict[int, frozenset[int]] = {}
    hashes = inp.line_hash.tolist()
    ptr = inp.line_ptr.tolist()
    occ = inp.line_occ
    for i, h in enumerate(hashes):
        o = occ[ptr[i]:ptr[i + 1]]
        occ_of[h] = frozenset(o.tolist())
        unit_of[h] = frozenset(inp.occ_unit[o].tolist())
    return occ_of, unit_of


class _RuleState:
    """Survival bookkeeping of the tracked units under one rule set."""

    def __init__(self) -> None:
        self.alive: set[int] = set()
        self.lost_absent: set[int] = set()
        self.lost_present: set[int] = set()
        self.loss: dict[int, tuple[int, int]] = {}
        self.restore: dict[int, tuple[int, int]] = {}
        self.n_restore: dict[int, int] = defaultdict(int)
        self.n_reloss: dict[int, int] = defaultdict(int)
        self.first_reloss: dict[int, int] = {}
        self.n_fallback: dict[int, int] = defaultdict(int)
        self.cols: dict[str, list[int]] = defaultdict(list)

    def ever_lost(self) -> set[int]:
        return self.lost_absent | self.lost_present

    def trial(self, c: int, cur: set[int], u_in: set[int], kept_extra: set[int] | None,
              modified_fn: Callable[[set[int]], set[int]]) -> tuple[int, set[int], set[int], set[int], set[int]]:
        """Consolidation c: losses, modifications, restorations and re-losses.

        kept_extra: units without an anchor in R_c that still count as present
        (v2 fallback). Returns at_risk, lost, modified, restored, rescued.
        """
        at_risk = len(self.alive)
        lost = self.alive - cur
        rescued: set[int] = set()
        if kept_extra:
            rescued = lost & kept_extra
            lost -= rescued
            for u in rescued:
                self.n_fallback[u] += 1
        modified = modified_fn(lost) if lost else set()
        for u in lost:
            self.loss[u] = (c, EVENT_MODIFIED if u in modified else EVENT_DROPPED)
        self.alive -= lost
        restored = self.lost_absent & cur
        for u in restored:
            self.n_restore[u] += 1
            if u not in self.restore:
                self.restore[u] = (c, SRC_REAPPENDED if u in u_in else SRC_RECREATED)
        relost = self.lost_present - cur
        if kept_extra:
            relost -= kept_extra
        for u in relost:
            self.n_reloss[u] += 1
            self.first_reloss.setdefault(u, c)
        self.lost_absent = (self.lost_absent - restored) | relost | lost
        self.lost_present = (self.lost_present - relost) | restored
        return at_risk, lost, modified, restored, rescued

    def arrays(self, units: list[int], entry_row: dict[int, int], entry_cons: dict[int, int]
               ) -> dict[str, np.ndarray]:
        lc = [self.loss.get(u, (-1, EVENT_CENSORED)) for u in units]
        rs = [self.restore.get(u, (-1, SRC_NONE)) for u in units]
        return {
            "unit": np.array(units, dtype=np.int32),
            "entry_row": np.array([entry_row[u] for u in units], dtype=np.int32),
            "entry_cons": np.array([entry_cons[u] for u in units], dtype=np.int32),
            "loss_cons": np.array([x[0] for x in lc], dtype=np.int32),
            "event": np.array([x[1] for x in lc], dtype=np.int8),
            "restore_cons": np.array([x[0] for x in rs], dtype=np.int32),
            "restore_src": np.array([x[1] for x in rs], dtype=np.int8),
            "n_restore": np.array([self.n_restore.get(u, 0) for u in units], dtype=np.int32),
            "n_reloss": np.array([self.n_reloss.get(u, 0) for u in units], dtype=np.int32),
            "reloss_cons": np.array([self.first_reloss.get(u, -1) for u in units], dtype=np.int32),
            "n_fallback": np.array([self.n_fallback.get(u, 0) for u in units], dtype=np.int32),
        }


def _lis(pairs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Longest subsequence of (i, j) pairs (sorted by i) with increasing j."""
    tails: list[int] = []
    tails_idx: list[int] = []
    prev = [-1] * len(pairs)
    for n, (_, j) in enumerate(pairs):
        k = bisect_left(tails, j)
        if k == len(tails):
            tails.append(j)
            tails_idx.append(n)
        else:
            tails[k] = j
            tails_idx[k] = n
        prev[n] = tails_idx[k - 1] if k > 0 else -1
    out = []
    n = tails_idx[-1] if tails_idx else -1
    while n >= 0:
        out.append(pairs[n])
        n = prev[n]
    return out[::-1]


class LineAligner:
    """Pairs each line of an old version with the line of the new version that replaced it."""

    def __init__(self, a: list[int], b: list[int], sig: Callable[[int], frozenset]) -> None:
        ca, cb = Counter(a), Counter(b)
        pos_b = {h: j for j, h in enumerate(b) if cb[h] == 1}
        pairs = [(i, pos_b[h]) for i, h in enumerate(a) if ca[h] == 1 and h in pos_b]
        anchors = _lis(pairs)
        self.ai = [-1] + [i for i, _ in anchors] + [len(a)]
        self.aj = [-1] + [j for _, j in anchors] + [len(b)]
        self.a, self.b, self.sig = a, b, sig

    def replacement(self, i: int) -> list[int]:
        """Indices (into b) of the line that replaced old line i; [] if kept or deleted."""
        k = bisect_right(self.ai, i) - 1
        if self.ai[k] == i:
            return []
        ia, ib = self.ai[k] + 1, self.ai[k + 1]
        ja, jb = self.aj[k] + 1, self.aj[k + 1]
        if jb <= ja:
            return []
        if ib - ia == jb - ja:
            return [ja + (i - ia)]
        sa = self.sig(self.a[i])
        best: list[int] = []
        best_s = 0.0
        for j in range(ja, jb):
            sb = self.sig(self.b[j])
            inter = len(sa & sb)
            if not inter:
                continue
            s = inter / len(sa | sb)
            if s > best_s + 1e-12:
                best, best_s = [j], s
            elif abs(s - best_s) <= 1e-12:
                best.append(j)
        if len(best) > 1:  # tie: the nearest relative position
            rel = (i - ia) / max(1, ib - ia)
            best = [min(best, key=lambda j: abs((j - ja) / max(1, jb - ja) - rel))]
        return best


def run_chain(inp: AgentInput) -> AgentResult:
    """States of every fact unit of one agent (definitions in the module docstring).

    `units` arrays (one entry per tracked unit): unit, entry_row, entry_cons,
    loss_cons (-1 if never lost), event (EVENT_*), restore_cons (first
    restoration, -1 if none), restore_src (SRC_*), n_restore, n_reloss,
    reloss_cons (first re-loss after the first restoration, -1 if none) and
    n_fallback (v2 only: consolidations at which only the literal fallback kept
    the unit). `cons` arrays (one entry per consolidation c = 1..K): row,
    at_risk, kept, dropped, modified, restored, entered (units new in R_c),
    units_in, units_out, alive_missing_in (never-lost units absent from I_c;
    nonzero only after a truncation), and verbatim line counts: lines_old (lines
    of I_c already in P_c), lines_new (lines of I_c appended since P_c) and how
    many of each R_c keeps (lines_old_kept, lines_new_kept). With `inp.v2`,
    units2, cons2 (at_risk, kept, kept_fallback, dropped, modified, restored)
    and pairs2 hold the same under rules v2, and units3, cons3, pairs3 under
    rules v3 (for the versions listed in `inp.v2.versions`).
    """
    occ_of, unit_of = _line_maps(inp)
    occ_unit = inp.occ_unit
    occ_unit_l = occ_unit.tolist()
    occ_tc = inp.occ_tc.tolist()
    occ_val = inp.occ_val.tolist()
    unit_val: dict[int, int] = {}
    unit_occs: dict[int, list[int]] = defaultdict(list)
    for o, u in enumerate(occ_unit_l):
        unit_occs[u].append(o)
        unit_val.setdefault(u, occ_val[o])
    v2 = inp.v2
    occ_type = v2.occ_type.tolist() if v2 is not None else []
    unit_type: dict[int, int] = {}
    if v2 is not None:
        for o, u in enumerate(occ_unit_l):
            unit_type.setdefault(u, occ_type[o])
    sig_cache: dict[int, frozenset] = {}

    def sig(h: int) -> frozenset:
        s = sig_cache.get(h)
        if s is None:
            os_ = occ_of.get(h, _EMPTY)
            s = sig_cache[h] = frozenset([("c", occ_tc[o]) for o in os_ if occ_tc[o] >= 0]
                                         + [("v", occ_type[o], occ_val[o]) for o in os_])
        return s

    n = len(inp.rel)
    lines: dict[int, list[int]] = {}
    s1 = _RuleState()
    versions = tuple(v2.versions) if v2 is not None else ()
    states = {ver: _RuleState() for ver in versions}
    extractor = AnchorExtractor(list(v2.agent_names), v2.salt) if "v3" in versions else None
    seen: set[int] = set()
    entry_row: dict[int, int] = {}
    entry_cons: dict[int, int] = {}
    entries_since_cons: list[int] = []
    spell_open: dict[int, int] = {}
    sp_unit: list[int] = []
    sp_start: list[int] = []
    sp_end: list[int] = []
    cons_rows: list[int] = []
    pairs: dict[int, list[tuple[int, str, int]]] = {}
    pairs_v: dict[str, dict[int, list[tuple[int, str, int]]]] = {ver: {} for ver in versions}
    qa = {"rows": n, "undo_rows": 0, "untracked_by_undo": 0, "fork_rows": 0}

    def units_of(lst: list[int]) -> set[int]:
        return set().union(*[unit_of.get(h, _EMPTY) for h in lst])

    def occs_of(lst: list[int]) -> set[int]:
        return set().union(*[occ_of.get(h, _EMPTY) for h in lst])

    def modified_test(cand: set[int], o_in: set[int], new_by_tc: dict[int, set[int]]) -> set[int]:
        """v1: units of `cand` whose context on I_c holds a value new since P_c in R_c."""
        out = set()
        if not new_by_tc:
            return out
        for u in cand:
            v = unit_val[u]
            for o in unit_occs[u]:
                if o in o_in:
                    vals = new_by_tc.get(occ_tc[o])
                    if vals and (len(vals) > 1 or v not in vals):
                        out.add(u)
                        break
        return out

    def modified_v2(cand: set[int], a_lst: list[int], b_lst: list[int], holder: dict | None = None) -> set[int]:
        """v2/v3: a value under the unit's context on the line that replaced the unit's line.

        `holder` shares one alignment of (a_lst, b_lst) between rule sets."""
        want = {u for u in cand if any(occ_tc[o] >= 0 for o in unit_occs[u])}
        if not want:
            return set()
        holder = {} if holder is None else holder
        if "a" not in holder:
            holder["a"] = [h for h in a_lst if h]
            holder["b"] = [h for h in b_lst if h]
        a, b = holder["a"], holder["b"]
        out: set[int] = set()
        for i, h in enumerate(a):
            os_ = occ_of.get(h)
            if not os_:
                continue
            mine = [o for o in os_ if occ_unit_l[o] in want and occ_tc[o] >= 0 and occ_unit_l[o] not in out]
            if not mine:
                continue
            if holder.get("al") is None:
                holder["al"] = LineAligner(a, b, sig)
            new_lines = holder["al"].replacement(i)
            if not new_lines:
                continue
            old_vals: dict[int, set[int]] = defaultdict(set)
            for o in os_:
                if occ_tc[o] >= 0:
                    old_vals[occ_tc[o]].add(occ_val[o])
            for o in mine:
                t = occ_tc[o]
                if any(occ_tc[o2] == t and occ_val[o2] not in old_vals[t]
                       for j in new_lines for o2 in occ_of.get(b[j], _EMPTY)):
                    out.add(occ_unit_l[o])
        return out

    def tv_map(lst: list[int]) -> dict[tuple[int, int], list[int]]:
        out: dict[tuple[int, int], list[int]] = defaultdict(list)
        for j, h in enumerate(lst):
            for o in occ_of.get(h, _EMPTY):
                out[(occ_type[o], occ_val[o])].append(j)
        return out

    cand_cache: dict[tuple[int, str], frozenset[str]] = {}  # (line hash, kind) -> email/phone hashes
    name_cache: dict[int, frozenset[str]] = {}  # line hash -> name candidates
    hmac_cache: dict[tuple[str, str], str] = {}  # (kind, name) -> keyed hash

    adj_cache: dict[tuple[int, int, int, str], bool] = {}  # (line hash, type, value, lemma) -> v3 adjacency

    def make_view(lst: list[int], text: str) -> dict:
        """Lazily built literal index, type-value line map and hashed candidates of one version."""
        return {"lst": lst, "text": text}

    def fallback(cand: set[int], lst: list[int], text: str, ver: str = "v2", view: dict | None = None) -> set[int]:
        """Units of `cand` whose value occurs literally in the version (v2 or v3 presence)."""
        out: set[int] = set()
        if not cand:
            return out
        view = make_view(lst, text) if view is None else view
        if "idx" not in view:
            view["idx"] = LiteralIndex(view["text"], v2.salt)
            view["tv"] = tv_map(view["lst"])
            view["hashed"] = {}
        idx, tv, hashed = view["idx"], view["tv"], view["hashed"]

        def hashed_has(kind: str, stored: str) -> bool:
            hs = hashed.get(kind)
            if hs is None:
                hs = hashed[kind] = set()
                pairs_ = [(j, h) for j, h in enumerate(lst[:len(idx.lines)]) if h]
                if kind in ENTITY_TYPES:
                    names: set[str] = set()
                    for j, h in pairs_:
                        c = name_cache.get(h)
                        if c is None:
                            c = name_cache[h] = name_candidates(idx.lines[j])
                        names |= c
                    for nm in names:
                        hv = hmac_cache.get((kind, nm))
                        if hv is None:
                            hv = hmac_cache[(kind, nm)] = keyed_hash(v2.salt, kind, nm)
                        hs.add(hv)
                else:
                    for j, h in pairs_:
                        c = cand_cache.get((h, kind))
                        if c is None:
                            c = cand_cache[(h, kind)] = frozenset(candidate_hashes(idx.lines[j], kind, v2.salt))
                        hs |= c
            return stored in hs

        for u in cand:
            t = unit_type[u]
            stored, lemma = v2.unit_info.get(u, ("", ""))
            if ver == "v3" and (t in _STRICT_QUANTITY or t == _TIME):
                # v3: the value with its context word adjacent to it, on a line holding the value.
                if lemma:
                    for j in tv.get((t, unit_val[u]), ()):
                        key = (lst[j], t, unit_val[u], lemma)
                        hit = adj_cache.get(key)
                        if hit is None:
                            hit = adj_cache[key] = idx.quantity_adjacent(j, TYPES[t], stored, lemma, extractor)
                        if hit:
                            out.add(u)
                            break
            elif t in _STRICT_QUANTITY:
                if lemma and any(idx.line_has_context(j, lemma) for j in tv.get((t, unit_val[u]), ())):
                    out.add(u)
            elif t == _TIME:
                if (t, unit_val[u]) in tv or idx.has_value("time", stored):
                    out.add(u)
            elif stored.startswith("h:"):
                if TYPES[t] in HASHABLE_KINDS and hashed_has(TYPES[t], stored):
                    out.add(u)
            elif stored and idx.has_value(TYPES[t], stored):
                out.add(u)
        return out

    c = 0
    prev_units: set[int] = set()
    p_occ: set[int] | None = None  # occurrences of the previous version
    p_lines: set[int] = set()  # line hashes of the previous version
    for k in range(n):
        kind, rel, b = int(inp.kind[k]), int(inp.rel[k]), int(inp.base[k])
        if kind == KIND_FULL:
            lst = inp.seg[k].tolist()
        elif kind == KIND_EXT:
            lst = lines[b][:-1] + inp.seg[k].tolist()
        else:
            lst = lines[b]
        lines[k] = lst
        lines.pop(k - 80, None)
        cur = units_of(lst)

        if inp.is_cons[k]:
            c += 1
            in_lst = lines[k - 1]
            u_in = prev_units
            o_in = occs_of(in_lst)
            o_out = occs_of(lst)
            new_occ = o_out - p_occ if p_occ is not None else o_out
            new_by_tc: dict[int, set[int]] = defaultdict(set)
            for o in new_occ:
                t = occ_tc[o]
                if t >= 0:
                    new_by_tc[t].add(occ_val[o])
            label = k in inp.label_rows
            ever1 = s1.ever_lost() if label else _EMPTY
            at_risk, lost, modified, restored, _ = s1.trial(
                c, cur, u_in, None, lambda L: modified_test(L, o_in, new_by_tc))
            tc_of: dict[int, int] = {}
            if label:
                for o in sorted(o_in) + sorted(o_out):
                    u = occ_unit_l[o]
                    if occ_tc[o] >= 0 and u not in tc_of:
                        tc_of[u] = occ_tc[o]
                gone = u_in - cur
                mod_all = modified_test(gone, o_in, new_by_tc)
                lab = [(u, "kept") for u in u_in & cur]
                lab += [(u, "modified" if u in mod_all else "dropped") for u in gone]
                lab += [(u, "restored" if u in ever1 else "new") for u in cur - u_in]
                pairs[k] = [(u, lb, tc_of.get(u, -1)) for u, lb in lab]
            if states:
                view_r = make_view(lst, v2.cons_text.get(k, ""))
                view_i = make_view(in_lst, v2.in_text.get(k, "")) if label else None
                holder: dict = {}
                for ver, st in states.items():
                    ever2 = st.ever_lost() if label else _EMPTY
                    cand = (st.alive | st.lost_present) - cur
                    extra = fallback(cand, lst, "", ver, view_r)
                    a2, lost2, mod2, rest2, resc2 = st.trial(
                        c, cur, u_in, extra, lambda L: modified_v2(L, in_lst, lst, holder))
                    for key, val in (("at_risk", a2), ("kept", a2 - len(lost2)), ("kept_fallback", len(resc2)),
                                     ("dropped", len(lost2) - len(mod2)), ("modified", len(mod2)),
                                     ("restored", len(rest2))):
                        st.cols[key].append(val)
                    if label:
                        gone_a = u_in - cur
                        lit_r = fallback(gone_a, lst, "", ver, view_r)
                        gone = gone_a - lit_r
                        mod_all2 = modified_v2(gone, in_lst, lst, holder)
                        new_side = cur - u_in
                        lit_i = fallback(new_side, in_lst, "", ver, view_i)
                        lab = [(u, "kept") for u in (u_in & cur) | lit_r | lit_i]
                        lab += [(u, "modified" if u in mod_all2 else "dropped") for u in gone]
                        lab += [(u, "restored" if u in ever2 else "new") for u in new_side - lit_i]
                        pairs_v[ver][k] = [(u, lb, tc_of.get(u, -1)) for u, lb in lab]
            entered_here = cur - seen
            # Verbatim line retention (lines that carry letters or digits).
            l_in, l_out = set(in_lst), set(lst)
            l_in.discard(0)
            l_out.discard(0)
            l_old = l_in & p_lines
            l_new = l_in - p_lines
            cons_rows.append(k)
            for key, val in (
                ("at_risk", at_risk), ("kept", at_risk - len(lost)),
                ("dropped", len(lost) - len(modified)), ("modified", len(modified)),
                ("restored", len(restored)), ("entered", len(entered_here)),
                ("units_in", len(u_in)), ("units_out", len(cur)),
                ("alive_missing_in", len((s1.alive | lost) - u_in)),
                ("lines_old", len(l_old)), ("lines_old_kept", len(l_old & l_out)),
                ("lines_new", len(l_new)), ("lines_new_kept", len(l_new & l_out)),
            ):
                s1.cols[key].append(val)
            p_occ = o_out
            p_lines = l_out
            entries_since_cons = []
        elif rel == REL_CODE["first"]:
            p_occ = occs_of(lst)
            p_lines = set(lst)
            p_lines.discard(0)

        # Undo: units that entered since the last consolidation and are gone.
        is_fork_back = rel == REL_CODE["fork_append"] and b != k - 1
        if rel in UNDO_RELS or is_fork_back:
            qa["undo_rows"] += rel in UNDO_RELS
            qa["fork_rows"] += is_fork_back
            gone = [u for u in entries_since_cons if u not in cur and u in s1.alive]
            for u in gone:
                s1.alive.discard(u)
                for st in states.values():
                    st.alive.discard(u)
                seen.discard(u)
                entry_row.pop(u, None)
                entry_cons.pop(u, None)
            qa["untracked_by_undo"] += len(gone)
            if gone:
                g = set(gone)
                entries_since_cons = [u for u in entries_since_cons if u not in g]

        # Entries (after the trials, so a unit new in R_c is first tried at c + 1).
        new = cur - seen
        for u in new:
            entry_row[u] = k
            entry_cons[u] = c
        seen |= new
        s1.alive |= new
        for st in states.values():
            st.alive |= new
        entries_since_cons.extend(new)

        # Presence spells over all rows.
        for u in cur - prev_units:
            spell_open[u] = len(sp_unit)
            sp_unit.append(u)
            sp_start.append(k)
            sp_end.append(-1)
        for u in prev_units - cur:
            i = spell_open.pop(u, None)
            if i is not None:
                sp_end[i] = k
        prev_units = cur

    units = sorted(entry_row)
    out_units = s1.arrays(units, entry_row, entry_cons)
    spells = {
        "unit": np.array(sp_unit, dtype=np.int32),
        "start_row": np.array(sp_start, dtype=np.int32),
        "end_row": np.array(sp_end, dtype=np.int32),
    }
    cons = {"row": np.array(cons_rows, dtype=np.int32)}
    cons.update({key: np.array(s1.cols.get(key, []), dtype=np.int64) for key in _CONS_KEYS})
    res = AgentResult(inp.agent_id, c, out_units, spells, cons, pairs, qa)
    for ver, st in states.items():
        cons_v = {"row": cons["row"]}
        cons_v.update({key: np.array(st.cols.get(key, []), dtype=np.int64) for key in _CONS2_KEYS})
        setattr(res, "units" + ver[1:], st.arrays(units, entry_row, entry_cons))
        setattr(res, "cons" + ver[1:], cons_v)
        setattr(res, "pairs" + ver[1:], pairs_v[ver])
    return res
