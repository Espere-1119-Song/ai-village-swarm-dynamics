"""Gemini as an extra independent rater for the hard B1 and B2 cases (owner's request, 2026-10-01).

The owner accepted the data terms of the Gemini API free tier for this use. The rows are the units the
owner labels blind (scripts/blind_labels.py): B1 strata A and B, then the B1 sample (stratum C,
priority 2), and the 50 B2 parent items (priority 1 first). The prompts are built from the blind
sheets: no rule-based occurrence counts, no ⟦ ⟧ / ⟨ ⟩ marks in B1, the B2 candidates in the blind
sheet's shuffled order without posteriors or the MAP parent. Personal data is replaced before
anything is sent or cached (`avsd.lineage.prelabel.Redactor`): human names (spaCy PERSON outside the
agent roster), emails and phone numbers become per-unit placeholders such as [PERSON_1];
credentials are already «masked». The owner's blind labels stay the reference; Gemini output is
never shown to the owner.

Key: ~/.config/avsd/gemini_key (owner's file, mode 600), read at run time and sent only to
generativelanguage.googleapis.com in the x-goog-api-key header (never in a URL; redirects are
refused, so the header cannot follow one). The key is never printed, logged or cached.

Commands (project env on GRASP, `source scripts/env.sh` first; scripts/gemini_label.sbatch runs
`prepare`, `run` and `export` as a resumable Slurm job):
  python scripts/gemini_label.py probe [--generate MODEL ...]   models the key can list; a one-line
                                                                 test call per named model (status only)
  python scripts/gemini_label.py prepare                         redacted requests (no API call)
  python scripts/gemini_label.py run [--max-requests N]          label pending rows, cache-driven
  python scripts/gemini_label.py export                          private label files under data/labels/
  python scripts/gemini_label.py status                          counts only

Cache: data/interim/llm_cache/gemini_hard/ (requests.jsonl, cache.jsonl, runs.jsonl, quota.json, compare.md):
redacted prompts and model outputs only, rows identified by opaque ids. The comparison (aggregates) stays
there too, out of outputs/, so that no Gemini result reaches the owner's report viewer.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import socket
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HOST = "generativelanguage.googleapis.com"
API = f"https://{HOST}/v1beta"
KEY_PATH = Path.home() / ".config" / "avsd" / "gemini_key"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects: urllib would copy the key header to the new location."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


_OPENER = urllib.request.build_opener(_NoRedirect)
_IPV4 = False


def prefer_ipv4() -> None:
    """Resolve hosts to IPv4 only (IPv6 was black-holed on some cluster nodes)."""
    global _IPV4
    if _IPV4:
        return
    orig = socket.getaddrinfo

    def gai(host, port, family=0, type=0, proto=0, flags=0):
        return orig(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = gai
    _IPV4 = True


def _key() -> str:
    try:
        k = KEY_PATH.read_text().strip()
    except OSError as e:
        raise SystemExit(f"cannot read the key file {KEY_PATH}: {e.strerror}") from None
    if not k:
        raise SystemExit(f"the key file {KEY_PATH} is empty")
    return k


def api(method: str, path: str, body: dict | None = None, timeout: float = 600.0) -> tuple[int, dict]:
    """One call to the Gemini API: (HTTP status, JSON body). The key goes in the header only."""
    url = API + path
    assert url.startswith(f"https://{HOST}/"), url
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode("utf-8"),
                                 method=method, headers={"x-goog-api-key": _key(),
                                                         "Content-Type": "application/json"})
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8") or "{}")
        except (ValueError, OSError):
            payload = {}
        return e.code, payload
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, {"error": {"message": f"network: {type(e).__name__}"}}


def quota_info(payload: dict) -> dict:
    """Quota id, limit and retry delay from a 429 body (no other content)."""
    out: dict = {}
    for d in (payload.get("error") or {}).get("details") or []:
        t = d.get("@type", "")
        if t.endswith("QuotaFailure"):
            v = (d.get("violations") or [{}])[0]
            out["quota_id"] = v.get("quotaId", "")
            out["quota_value"] = v.get("quotaValue", "")
            out["quota_metric"] = v.get("quotaMetric", "")
        elif t.endswith("RetryInfo"):
            out["retry_delay"] = d.get("retryDelay", "")
    return out


def probe(models: list[str]) -> None:
    prefer_ipv4()
    st, body = api("GET", "/models?pageSize=1000")
    if st != 200:
        raise SystemExit(f"list models: HTTP {st} {((body.get('error') or {}).get('status') or '')}")
    names = sorted(m["name"].removeprefix("models/") for m in body.get("models", [])
                   if "generateContent" in (m.get("supportedGenerationMethods") or []))
    print("models with generateContent:", ", ".join(n for n in names if "gemini" in n))
    for m in models:
        t0 = time.perf_counter()
        st, body = api("POST", f"/models/{m}:generateContent", {
            "contents": [{"role": "user", "parts": [{"text": "Reply with the single word OK."}]}],
            "generationConfig": {"maxOutputTokens": 512}})
        dt = time.perf_counter() - t0
        info = quota_info(body) if st == 429 else {}
        ver = body.get("modelVersion", "") if st == 200 else ""
        err = "" if st == 200 else ((body.get("error") or {}).get("status") or "")
        print(f"{m}: HTTP {st} {err} {ver} {dt:.1f} s {json.dumps(info) if info else ''}".rstrip())


# --- settings ---------------------------------------------------------------------------------------

# Free-tier models of the owner's key (probe of 2026-10-01: 3.1 Pro preview, 2.5 Pro and 2.5 Flash answer;
# 3.5 Flash is limited to 20 requests a day). Every row goes to the strongest model, 3.1 Pro preview. When
# its daily quota is used up, a row without an answer gets one from the fallback (2.5 Pro for the hard rows:
# B1 stratum A and the B2 items; 2.5 Flash for the others), and a later run replaces fallback answers with
# 3.1 Pro answers as the quota allows ("upgrade"). The model of every answer is recorded.
LADDERS: dict[str, tuple[str, ...]] = {"hard": ("gemini-3.1-pro-preview", "gemini-2.5-pro"),
                                       "main": ("gemini-3.1-pro-preview", "gemini-2.5-flash")}
MIN_INTERVAL = {"gemini-3.1-pro-preview": 13.0, "gemini-2.5-pro": 13.0, "gemini-2.5-flash": 7.0}  # s between calls
MAX_ATTEMPTS = 2  # per model: one retry when the answer does not validate
GENERATION = {"temperature": 1.0, "maxOutputTokens": 32768, "responseMimeType": "application/json"}  # default thinking
RESET_TZ = ZoneInfo("America/Los_Angeles")  # free-tier daily quotas reset at midnight Pacific time
GROUP_ORDER = {"A": 0, "B2-P1": 1, "B": 2, "B2-P2": 3, "C": 4, "adj": 5}
GROUP_TIER = {"A": "hard", "B2-P1": "hard", "B2-P2": "hard", "B": "main", "C": "main", "adj": "main"}


def cache_dir(cfg: dict) -> Path:
    from avsd.lineage import prelabel as pre

    return pre.cache_dir(cfg).parent / "gemini_hard"


def item_id(task: str, *parts: str) -> str:
    return task + ":" + hashlib.sha256("\x00".join(str(x).strip() for x in parts).encode()).hexdigest()[:16]


def b1_schema() -> dict:
    from avsd.lineage.prelabel import CONFIDENCES, LABELS

    return {"type": "OBJECT", "properties": {"label": {"type": "STRING", "enum": list(LABELS)},
                                             "confidence": {"type": "STRING", "enum": list(CONFIDENCES)},
                                             "rationale": {"type": "STRING"}},
            "required": ["label", "confidence", "rationale"], "propertyOrdering": ["label", "confidence", "rationale"]}


def b2_schema(cands: list[int]) -> dict:
    from avsd.lineage.prelabel import CONFIDENCES

    choices = [str(j) for j in cands] + ["ENV", "NONE"]
    return {"type": "OBJECT", "properties": {"choice": {"type": "STRING", "enum": choices},
                                             "confidence": {"type": "STRING", "enum": list(CONFIDENCES)},
                                             "rationale": {"type": "STRING"}},
            "required": ["choice", "confidence", "rationale"],
            "propertyOrdering": ["choice", "confidence", "rationale"]}


def request_key(item: dict, model: str, attempt: int, seed: int) -> str:
    blob = {"model": model, "prompt_version": item["prompt_version"], "messages": item["messages"],
            "generation": {**GENERATION, "seed": seed + attempt}, "schema": item["schema"]}
    return hashlib.sha256(json.dumps(blob, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def next_reset(now: datetime | None = None) -> datetime:
    """The next midnight in Pacific time, plus five minutes (UTC)."""
    now = (now or datetime.now(UTC)).astimezone(RESET_TZ)
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    return nxt.astimezone(UTC)


# --- prepare --------------------------------------------------------------------------------------------

def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def prepare(cfg: dict, rebuild: bool = False, log=print) -> dict:
    """Redacted requests for every row to label (requests.jsonl; nothing unredacted is written)."""
    import polars as pl

    from avsd.lineage import prelabel as pre
    from avsd.lineage import prelabel_parents as pp
    from avsd.lineage.anchors import _EMAIL, _PHONE, load_nlp

    out = cache_dir(cfg)
    if (out / "requests.jsonl").exists() and not rebuild:
        log(f"prepare: {out / 'requests.jsonl'} exists (use --rebuild to redo it)")
        return {}
    labels = Path(cfg["paths"]["labels"])
    agents = pl.read_parquet(Path(cfg["paths"]["processed"]) / "agents.parquet")["name"].to_list()
    red = pre.Redactor(agents, load_nlp())
    review = {(r["pair_id"].strip(), r["unit_key"].strip()): r for r in _read_csv(labels / pre.REVIEW_FILE)}
    blind1 = _read_csv(labels / "memory_pairs_blind.csv")
    seen = {(r["pair_id"].strip(), r["unit_key"].strip()) for r in blind1}
    adj = [k for k in pre.read_adjudication(labels / pre.ADJUDICATION_FILE) if k not in seen and k in review]
    rows1 = [(r, review[(r["pair_id"].strip(), r["unit_key"].strip())]["design_stratum"].split(":")[0]) for r in blind1]
    rows1 += [(review[k], "adj") for k in adj]
    prio2 = {r["child_uid"].strip(): r["review_priority"].strip() for r in _read_csv(labels / pp.REVIEW_FILE)}
    blind2 = _read_csv(labels / pp.BLIND_FILE)
    items, stats = [], Counter()
    for r, g in rows1:
        msgs, c = pre.gemini_b1_messages(r, red)
        stats.update({f"placeholders_{k.lower()}": v for k, v in c.items()})
        items.append({"id": item_id("b1", r["pair_id"], r["unit_key"]), "task": "memory", "group": g,
                      "tier": GROUP_TIER[g], "prompt_version": pre.GEMINI_PROMPT_VERSION, "messages": msgs,
                      "schema": b1_schema()})
    for r in blind2:
        msgs, cands, c = pp.gemini_b2_messages(r, red)
        stats.update({f"placeholders_{k.lower()}": v for k, v in c.items()})
        g = "B2-P1" if prio2.get(r["child_uid"].strip()) == "1" else "B2-P2"
        items.append({"id": item_id("b2", r["child_uid"]), "task": "parents", "group": g, "tier": GROUP_TIER[g],
                      "prompt_version": pp.GEMINI_PROMPT_VERSION, "messages": msgs, "schema": b2_schema(cands),
                      "cands": cands})
    items.sort(key=lambda x: GROUP_ORDER[x["group"]])
    leaks = sum(1 for it in items for m in it["messages"]
                if _EMAIL.search(m["content"]) or any(len("".join(ch for ch in x.group(0) if ch.isdigit())) >= 10
                                                      for x in _PHONE.finditer(m["content"])))
    if leaks:
        raise SystemExit(f"prepare: {leaks} redacted prompts still match the email or phone pattern; stopping")
    out.mkdir(parents=True, exist_ok=True)
    out.chmod(0o700)
    with pre._private_open(out / "requests.jsonl", "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    stats.update({f"group_{k}": v for k, v in Counter(it["group"] for it in items).items()})
    stats["items"] = len(items)
    (out / "prepare_stats.json").write_text(json.dumps({"created": _now(), **dict(stats)}, indent=1))
    log("prepare: " + ", ".join(f"{k} {v}" for k, v in sorted(stats.items())))
    return dict(stats)


# --- run ----------------------------------------------------------------------------------------------------

def _read_jsonl(path: Path) -> list[dict]:
    from avsd.lineage.prelabel import _read_jsonl as rj

    return rj(path)


def answer_text(body: dict) -> tuple[str, str]:
    """(final answer text without thought parts, finish reason) of a generateContent response."""
    cands = body.get("candidates") or []
    if not cands:
        return "", ((body.get("promptFeedback") or {}).get("blockReason") or "no_candidate")
    c = cands[0]
    parts = (c.get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if not p.get("thought")), c.get("finishReason", "")


def validate(item: dict, text: str) -> bool:
    from avsd.lineage import prelabel as pre
    from avsd.lineage import prelabel_parents as pp

    if item["task"] == "memory":
        return pre.schema_ok(text.strip())
    return pp.choice_ok(text.strip(), {"candidates": item.get("cands") or []})


def best_answer(item: dict, cache: dict, seed: int) -> tuple[int | None, int | None]:
    """(ladder rank, attempt) of the best valid answer: the highest-ranked model that has one."""
    for i, m in enumerate(LADDERS[item["tier"]]):
        for a in range(MAX_ATTEMPTS):
            e = cache.get(request_key(item, m, a, seed))
            if e and e.get("valid"):
                return i, a
    return None, None


def plan(item: dict, cache: dict, seed: int, exhausted: dict) -> tuple[str, str | None, int]:
    """What to do next for one item:
    ('todo', model, attempt) no valid answer yet; ('upgrade', model, attempt) a valid answer from a fallback
    model exists and a stronger model can still answer; ('done', model, attempt) the answer to use;
    ('wait', None, 0) the models it still needs are out of quota until the reset; ('failed', None, 0)."""
    ladder = LADDERS[item["tier"]]
    rank, att = best_answer(item, cache, seed)
    waiting = False
    for m in ladder[:len(ladder) if rank is None else rank]:
        n = sum(1 for a in range(MAX_ATTEMPTS) if request_key(item, m, a, seed) in cache)
        if n >= MAX_ATTEMPTS:
            continue
        if m in exhausted:
            waiting = True
            continue
        return ("todo" if rank is None else "upgrade"), m, n
    if rank is not None:
        return ("wait" if waiting else "done"), ladder[rank], att
    return ("wait", None, 0) if waiting else ("failed", None, 0)


def _delay(info: dict, default: float) -> float:
    d = str(info.get("retry_delay") or "").rstrip("s")
    try:
        return float(d) + 1.0
    except ValueError:
        return default


def run(cfg: dict, max_requests: int | None = None, minutes: float | None = None, log=print, call=None,
        sleep=time.sleep) -> int:
    """Label pending rows; returns 0 (nothing left), 3 (waiting for a daily reset) or 4 (budget used up)."""
    from avsd.lineage.prelabel import _private_open

    call = call or api
    prefer_ipv4()
    out = cache_dir(cfg)
    items = _read_jsonl(out / "requests.jsonl")
    if not items:
        raise SystemExit("run: no requests; run prepare first")
    seed = int(cfg["seed"])
    cache = {e["key"]: e for e in _read_jsonl(out / "cache.jsonl")}
    qpath = out / "quota.json"
    quota = json.loads(qpath.read_text()) if qpath.exists() else {}
    now = datetime.now(UTC)
    exhausted = {m: q for m, q in quota.items() if datetime.fromisoformat(q["until"]) > now}
    t0 = time.monotonic()
    last: dict[str, float] = defaultdict(float)
    st = Counter()
    budget_hit = False
    with _private_open(out / "cache.jsonl", "a", encoding="utf-8") as f:
        for item in [*items, *items]:  # rows without an answer first, then upgrades of fallback answers
            first = st["passes"] < len(items)
            st["passes"] += 1
            while True:
                state, m, a = plan(item, cache, seed, exhausted)
                if state not in ("todo", "upgrade") or (first and state == "upgrade"):
                    break
                if (max_requests is not None and st["requests"] >= max_requests) or \
                        (minutes is not None and time.monotonic() - t0 > minutes * 60):
                    budget_hit = True
                    break
                wait = last[m] + MIN_INTERVAL.get(m, 10.0) - time.monotonic()
                if wait > 0:
                    sleep(wait)
                body = {"systemInstruction": {"parts": [{"text": item["messages"][0]["content"]}]},
                        "contents": [{"role": "user", "parts": [{"text": item["messages"][1]["content"]}]}],
                        "generationConfig": {**GENERATION, "seed": seed + a, "responseSchema": item["schema"]}}
                tries, entry = 0, None
                while entry is None:
                    last[m] = time.monotonic()
                    t1 = time.monotonic()
                    status, resp = call("POST", f"/models/{m}:generateContent", body)
                    st["requests"] += 1
                    if status == 200:
                        text, finish = answer_text(resp)
                        ok = validate(item, text)
                        entry = {"key": request_key(item, m, a, seed), "id": item["id"], "task": item["task"],
                                 "group": item["group"], "tier": item["tier"], "model": m,
                                 "model_version": resp.get("modelVersion", ""), "attempt": a,
                                 "prompt_version": item["prompt_version"], "messages": item["messages"],
                                 "generation": body["generationConfig"], "output": text, "finish_reason": finish,
                                 "valid": ok, "usage": resp.get("usageMetadata", {}),
                                 "seconds": round(time.monotonic() - t1, 1), "created": _now()}
                        st["valid" if ok else "invalid"] += 1
                    elif status == 429:
                        info = quota_info(resp)
                        if "PerDay" in info.get("quota_id", ""):
                            until = next_reset()
                            exhausted[m] = quota[m] = {"until": until.isoformat(), "limit": info.get("quota_value", ""),
                                                       "quota_id": info.get("quota_id", "")}
                            qpath.write_text(json.dumps(quota, indent=1))
                            log(f"run: {m} daily quota used up (limit {info.get('quota_value', '?')}); "
                                f"next reset {until:%Y-%m-%d %H:%M} UTC")
                            break
                        st["rate_limited"] += 1
                        sleep(_delay(info, 30.0))
                    elif status in (0, 500, 502, 503, 504) and tries < 4:
                        tries += 1
                        st[f"retry_{status}"] += 1
                        sleep(15.0 * 2 ** (tries - 1))
                    elif status in (0, 500, 502, 503, 504):
                        st["transient_failures"] += 1
                        log(f"run: {m} unavailable after retries (HTTP {status}); item left for a later run")
                        break
                    else:  # a request error is recorded as an invalid attempt, so it is not resent forever
                        err = (resp.get("error") or {}).get("status") or str(status)
                        entry = {"key": request_key(item, m, a, seed), "id": item["id"], "task": item["task"],
                                 "group": item["group"], "tier": item["tier"], "model": m, "attempt": a,
                                 "prompt_version": item["prompt_version"], "messages": item["messages"],
                                 "generation": body["generationConfig"], "output": "", "valid": False,
                                 "error": f"HTTP {status} {err}", "created": _now()}
                        st["errors"] += 1
                        log(f"run: {m} HTTP {status} {err}")
                if entry is None:
                    if status in (0, 500, 502, 503, 504):
                        st["skipped"] += 1
                        break
                    continue  # quota used up: plan again (next model, or wait)
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                f.flush()
                cache[entry["key"]] = entry
                if st["requests"] % 20 == 0:
                    log(f"run: {st['requests']} requests, {st['valid']} valid, {st['invalid']} invalid, "
                        f"{time.monotonic() - t0:.0f} s")
            if budget_hit:
                break
    states = Counter(plan(it, cache, seed, exhausted)[0] for it in items)
    st.pop("passes", None)
    with _private_open(out / "runs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"finished": _now(), "seconds": round(time.monotonic() - t0, 1), **dict(st),
                            "states": dict(states), "exhausted": sorted(exhausted),
                            "ladders": {k: list(v) for k, v in LADDERS.items()}, "generation": GENERATION}) + "\n")
    log(f"run: {dict(st)}; items {dict(states)}")
    if budget_hit and (states.get("todo") or states.get("upgrade")):
        return 4
    return 3 if states.get("wait") else (4 if states.get("todo") or states.get("upgrade") else 0)


# --- export, status, compare ---------------------------------------------------------------------------

def final_answers(cfg: dict) -> tuple[list[dict], dict[str, dict]]:
    """(items, id -> answer) with the first valid answer in ladder order, or an invalid one when every
    attempt failed; items still pending have no entry."""
    out = cache_dir(cfg)
    items = _read_jsonl(out / "requests.jsonl")
    seed = int(cfg["seed"])
    cache = {e["key"]: e for e in _read_jsonl(out / "cache.jsonl")}
    res = {}
    for it in items:
        rank, a = best_answer(it, cache, seed)
        state = plan(it, cache, seed, {})[0]
        if rank is not None:
            res[it["id"]] = cache[request_key(it, LADDERS[it["tier"]][rank], a, seed)]
        elif state == "failed":
            tried = [cache[k] for mm in LADDERS[it["tier"]] for aa in range(MAX_ATTEMPTS)
                     if (k := request_key(it, mm, aa, seed)) in cache]
            res[it["id"]] = tried[-1] if tried else None
    return items, {k: v for k, v in res.items() if v is not None}


def export(cfg: dict, log=print) -> dict:
    """data/labels/memory_pairs_gemini.csv and parents_gemini.csv (private): one row per labelled item."""
    from avsd.lineage import prelabel as pre
    from avsd.lineage import prelabel_parents as pp

    labels = Path(cfg["paths"]["labels"])
    items, ans = final_answers(cfg)
    review = _read_csv(labels / pre.REVIEW_FILE)
    n1 = n2 = 0
    with pre._private_open(labels / pre.GEMINI_LABELS_FILE, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pair_id", "unit_key", "gemini_label", "gemini_confidence", "gemini_model", "gemini_model_version",
                    "gemini_attempt", "group"])
        group = {it["id"]: it["group"] for it in items}
        for r in review:
            e = ans.get(item_id("b1", r["pair_id"], r["unit_key"]))
            if e is None:
                continue
            p = pre.parse_model_output(e.get("output")) if e.get("valid") else {"label": "", "confidence": ""}
            w.writerow([r["pair_id"], r["unit_key"], p["label"], p["confidence"], e["model"],
                        e.get("model_version", ""), e["attempt"], group.get(e["id"], "")])
            n1 += 1
    mapping = json.loads((labels / pp.BLIND_MAP_FILE).read_text())
    sheet = {r["child_uid"].strip(): r for r in _read_csv(labels / pp.REVIEW_FILE)}
    with pre._private_open(labels / pp.GEMINI_FILE, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["child_uid", "gemini_choice_blind", "gemini_parent", "gemini_confidence", "gemini_model",
                    "gemini_model_version", "gemini_attempt", "group"])
        for r in _read_csv(labels / pp.BLIND_FILE):
            cu = r["child_uid"].strip()
            e = ans.get(item_id("b2", cu))
            if e is None:
                continue
            o = json.loads(e["output"]) if e.get("valid") else {}
            ch = str(o.get("choice", "")).strip()
            w.writerow([cu, ch, pp.gemini_parent(ch, mapping.get(cu, {}), sheet.get(cu, {})) if ch else "",
                        o.get("confidence", ""), e["model"], e.get("model_version", ""), e["attempt"], e["group"]])
            n2 += 1
    log(f"export: {n1} B1 rows to {pre.GEMINI_LABELS_FILE}, {n2} B2 rows to {pp.GEMINI_FILE}")
    return {"b1": n1, "b2": n2}


def status(cfg: dict) -> dict:
    out = cache_dir(cfg)
    items = _read_jsonl(out / "requests.jsonl")
    seed = int(cfg["seed"])
    cache = {e["key"]: e for e in _read_jsonl(out / "cache.jsonl")}
    quota = json.loads((out / "quota.json").read_text()) if (out / "quota.json").exists() else {}
    now = datetime.now(UTC)
    exhausted = {m: q for m, q in quota.items() if datetime.fromisoformat(q["until"]) > now}
    by = Counter((it["group"], plan(it, cache, seed, exhausted)[0]) for it in items)
    models = Counter((it["group"], LADDERS[it["tier"]][r]) for it in items
                     if (r := best_answer(it, cache, seed)[0]) is not None)
    print("items by group and state:", dict(sorted(by.items())))
    print("labelled by group and model:", dict(sorted(models.items())))
    print("models waiting for a reset:", {m: q["until"] for m, q in exhausted.items()} or "none")
    return {"states": dict(by), "models": dict(models)}


def compare(cfg: dict, log=print) -> list[str]:
    """Aggregates only: Gemini's agreement with the other raters and its accuracy on the third-judge sample.

    Written to the private cache dir (compare.md), not to outputs/, whose reports the owner browses: no
    Gemini result is shown to the owner before the blind labels are in."""
    from avsd.lineage import prelabel as pre
    from avsd.lineage import prelabel_parents as pp

    labels = Path(cfg["paths"]["labels"])
    items, ans = final_answers(cfg)

    def key(r: dict) -> tuple[str, str]:
        return r["pair_id"].strip(), r["unit_key"].strip()

    gpath = labels / pre.GEMINI_LABELS_FILE
    gem = {key(r): r for r in _read_csv(gpath)} if gpath.exists() else {}
    review = _read_csv(labels / pre.REVIEW_FILE)
    llm = {key(r): r for r in _read_csv(labels / pre.LLM_LABELS_FILE)}
    rules = {"rule_v1": {key(r): r["rule_label"] for r in _read_csv(labels / pre.PAIRS_FILE)}}
    for v, path in pre.rule_version_files(labels).items():
        rules[f"rule_{v}"] = {key(r): r[f"rule_label_{v}"] for r in _read_csv(path)}
    group = {it["id"]: it["group"] for it in items}
    raters = {"qwen35_122b": "Qwen3.5-122B", "gptoss_120b": "gpt-oss-120b", "consensus": "strong consensus",
              "qwen3_14b": "Qwen3-14B", "rule_v1": "rules v1", "rule_v2": "rules v2", "rule_v3": "rules v3"}
    rows = []
    for r in review:
        k = key(r)
        g = gem.get(k)
        if g is None:
            continue
        lab = {"gemini": g["gemini_label"], "model": g["gemini_model"],
               "group": group.get(item_id("b1", *k), ""), **{m: (llm.get(k) or {}).get(m, "") for m in
                                                            ("qwen35_122b", "gptoss_120b", "qwen3_14b")},
               **{m: d.get(k, "") for m, d in rules.items()}}
        lab["consensus"] = lab["qwen35_122b"] if lab["qwen35_122b"] == lab["gptoss_120b"] else ""
        rows.append(lab)
    L = ["# Gemini as an extra rater of the hard B1 and B2 cases", "",
         'Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village', "",
         ("Aggregates only. Gemini (owner's free-tier key, data terms accepted by the owner) labelled the rows the "
          "owner labels blind, from redacted prompts (b1-gemini-v1, b2-gemini-v1: no rule-based occurrence counts, "
          "no B1 marks, B2 candidates in the blind order without posteriors; human names, emails and phone numbers "
          "replaced by placeholders). Gemini output is never shown to the owner. Models: "
          + ", ".join(f"{t}: {' then '.join(m)}" for t, m in LADDERS.items()) + "."), ""]
    cov = Counter((it["group"], ans[it["id"]]["model"] if it["id"] in ans else "(pending)") for it in items)
    L += ["Rows by group and model:", "", "| group | model | rows |", "|---|---|---|"]
    L += [f"| {g} | {m} | {n} |" for (g, m), n in sorted(cov.items())]
    valid = Counter(bool(ans[it["id"]].get("valid")) for it in items if it["id"] in ans)
    L += ["", f"Valid answers: {valid.get(True, 0)} of {sum(valid.values())} answered rows.", ""]
    L += ["B1 agreement of Gemini with the other raters (rows where both have a label):", "",
          "| rater | group | rows | same label | share | kappa |", "|---|---|---|---|---|---|"]
    for m, name in raters.items():
        for gname, sel in (("A", ("A",)), ("B", ("B",)), ("C sample", ("C",)), ("A+B+C", ("A", "B", "C"))):
            sub = [x for x in rows if x["group"] in sel and x[m] in pre.LABELS and x["gemini"] in pre.LABELS]
            same = sum(1 for x in sub if x[m] == x["gemini"])
            kap = pre.cohen_kappa([x[m] for x in sub], [x["gemini"] for x in sub]) if sub else float("nan")
            L.append(f"| {name} | {gname} | {len(sub)} | {same} | {same / len(sub) if sub else float('nan'):.2f} | "
                     f"{kap:.2f} |")
    # third-judge sample
    out = pre.cache_dir(cfg)
    reqs = pre._read_jsonl(out / "requests.jsonl")
    seed = int(cfg["seed"])
    llm_lab = pre.model_label_lists(pre.model_answers(reqs, out, seed))
    llm_lab.update(pre.rule_labels(reqs, labels)[0])
    llm_lab["gemini"] = [(gem.get((str(r["pair_id"]).strip(), r["unit_key"].strip())) or {}).get("gemini_label", "")
                         for r in reqs]
    sample, info = pre.adjudication_frame(reqs, llm_lab, seed)
    judged = pre.read_adjudication(labels / pre.ADJUDICATION_FILE)
    methods = ["gemini", "qwen3_14b", "qwen35_122b", "gptoss_120b", "rule_v1", "rule_v2", "rule_v3"]
    acc = pre.adjudication_accuracy(sample, info, judged, llm_lab, methods)
    have = sum(1 for s_ in sample if llm_lab["gemini"][s_["row"]])
    L += ["", (f"Accuracy on the third-judge sample of B1 disagreements ({have} of {len(sample)} units have a "
               "Gemini label; frame and weights as in outputs/qa/memory_prelabel.md section 10):"), "",
          "| rater | D1 correct | D2 correct | all disagreements (95% CI) |", "|---|---|---|---|"]
    for m in methods:
        r = acc["methods"][m]
        cells = [f"{x[0]}/{x[1]}" if x else "-" for x in (r["D1"], r["D2"])]
        o = r["overall"]
        L.append(f"| {pre.METHOD_NAMES.get(m, m)} | {cells[0]} | {cells[1]} | "
                 + (f"{o[0]:.2f} [{o[1]:.2f}, {o[2]:.2f}]" if o else "-") + " |")
    # B2
    if (labels / pp.GEMINI_FILE).exists():
        g2 = {r["child_uid"].strip(): r for r in _read_csv(labels / pp.GEMINI_FILE)}
        sheet = _read_csv(labels / pp.REVIEW_FILE)
        L += ["", "B2 agreement of Gemini's parent with the other raters (items where both give a choice):", "",
              "| rater | items | same parent |", "|---|---|---|"]
        for col, name in (("model_map", "MAP parent"), ("llm_choice", "Qwen3-14B"), ("qwen35_choice", "Qwen3.5-122B"),
                          ("gptoss_choice", "gpt-oss-120b"), ("suggested_parent", "strong models' shared choice")):
            sub = [(r, g2[r["child_uid"].strip()]["gemini_parent"]) for r in sheet
                   if (g2.get(r["child_uid"].strip()) or {}).get("gemini_parent") and r.get(col, "").strip()]
            same = sum(1 for r, gp in sub if pp.normalize_label(r[col], [{"n": q, "uid": r.get(f"cand_{q}_uid", "")}
                                                                         for q in range(1, pp.MAX_CANDS + 1)]) == gp)
            L.append(f"| {name} | {len(sub)} | {same} |")
        kinds = Counter("env" if gp == "env" else "none" if gp == "none" else "candidate" if gp else "(no answer)"
                        for gp in (x["gemini_parent"] for x in g2.values()))
        L += ["", "Gemini's B2 choices: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())) + "."]
    L.append("")
    path = cache_dir(cfg) / "compare.md"
    with pre._private_open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    log(f"compare: {path}")
    return L


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--config", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("probe")
    sp.add_argument("--generate", nargs="*", default=[], help="models to send one tiny test request to")
    sp = sub.add_parser("prepare")
    sp.add_argument("--rebuild", action="store_true")
    sp = sub.add_parser("run")
    sp.add_argument("--max-requests", type=int, default=None)
    sp.add_argument("--minutes", type=float, default=None, help="stop starting requests after this many minutes")
    sub.add_parser("export")
    sub.add_parser("status")
    sub.add_parser("next-reset", help="print the next quota reset as local time for sbatch --begin")
    sub.add_parser("compare", help="aggregates: agreement and third-judge accuracy (private compare.md)")
    args = p.parse_args(argv)
    if args.cmd == "probe":
        probe(args.generate)
        return
    if args.cmd == "next-reset":
        print(next_reset().astimezone().strftime("%Y-%m-%dT%H:%M:%S"))
        return
    from avsd.config import load_config

    cfg = load_config(args.config)

    def log(*a):
        print(*a, flush=True)

    if args.cmd == "prepare":
        prepare(cfg, args.rebuild, log)
    elif args.cmd == "run":
        sys.exit(run(cfg, args.max_requests, args.minutes, log))
    elif args.cmd == "export":
        export(cfg, log)
    elif args.cmd == "status":
        status(cfg)
    else:
        compare(cfg, log)


if __name__ == "__main__":
    main(sys.argv[1:])
