"""Build a self-contained offline labelling page from the two blind sheets.

    python make_labeler.py <dir with memory_pairs_blind.csv and parents_blind.csv> <out.html>

The page embeds the rows as JSON, loads nothing from the network, keeps labels in the browser's
localStorage, and exports CSV files with exactly the blind sheets' columns.
"""

import csv
import json
import sys
from pathlib import Path

TEMPLATE = r"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AVSD 标注工具</title>
<style>
:root{--bg:#f4f6fa;--card:#fff;--ink:#0e1a33;--muted:#5a6478;--line:#dde2ec;--accent:#011f5b;--accent-soft:#e3e9f6;--red:#990000;--red-soft:#f7e6e6;--vmark:#ffe08a;--cmark:#d6e4ff;--done:#2e6b4f;--done-soft:#e2f0e8}
@media (prefers-color-scheme:dark){:root{--bg:#0b1020;--card:#121a2e;--ink:#e6ebf5;--muted:#9aa5bd;--line:#26314d;--accent:#8fb0f0;--accent-soft:#1b2a4d;--red:#ec7a7a;--red-soft:#3a1c22;--vmark:#6b5410;--cmark:#1f3a66;--done:#7cc9a1;--done-soft:#16332a}}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--ink);font:14px/1.55 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;display:flex;flex-direction:column}
header{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--line);background:var(--card)}
header h1{font-size:16px;margin:0 6px 0 0}
.tabs button,.btn{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:8px;padding:5px 11px;font:inherit;cursor:pointer}
.tabs button.on{background:var(--accent);border-color:var(--accent);color:var(--card)}
.btn:hover,.tabs button:hover{border-color:var(--accent)}
.prog{flex:1;min-width:180px;display:flex;align-items:center;gap:8px;color:var(--muted)}
.bar{flex:1;height:8px;border-radius:4px;background:var(--line);overflow:hidden}
.bar span{display:block;height:100%;background:var(--done)}
.saved{color:var(--muted);font-size:12px;min-width:90px}
main{flex:1;overflow:auto;padding:14px 16px}
.meta{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.pill{font-size:12px;padding:1px 9px;border-radius:10px;background:var(--accent-soft);color:var(--accent)}
.pill.done{background:var(--done-soft);color:var(--done)}
.pill.todo{background:var(--red-soft);color:var(--red)}
.unit{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:9px 12px;margin-bottom:10px}
.unit .k{color:var(--muted);margin-right:6px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media (max-width:820px){.cols{grid-template-columns:1fr}}
.col{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:9px 12px;min-width:0}
.col h3{margin:0 0 6px;font-size:13px;color:var(--muted);font-weight:600}
.earlier{margin-top:10px}
.win{border-top:1px dashed var(--line);padding:6px 0;white-space:normal;overflow-wrap:anywhere}
.win:first-of-type{border-top:0}
.win .n{color:var(--muted);font-size:12px;margin-right:4px}
.note{color:var(--muted);font-size:12px;margin-bottom:4px}
mark.v{background:var(--vmark);color:inherit;border-radius:3px;padding:0 2px}
mark.c{background:var(--cmark);color:inherit;border-radius:3px;padding:0 2px}
.nl{color:var(--muted);font-size:11px}
.mask{color:var(--red);font-size:12px}
.empty{color:var(--muted);font-style:italic}
.cands{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:10px}
.cand{background:var(--card);border:2px solid var(--line);border-radius:10px;padding:8px 12px;cursor:pointer;min-width:0}
.cand.sel{border-color:var(--accent);background:var(--accent-soft)}
.cand .hd{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;margin-bottom:4px}
.num{display:inline-block;min-width:22px;text-align:center;border-radius:6px;background:var(--accent);color:var(--card);font-weight:600}
.child{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:9px 12px;margin-bottom:10px}
footer{border-top:1px solid var(--line);background:var(--card);padding:10px 16px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.lab{border:2px solid var(--line);background:var(--card);color:var(--ink);border-radius:9px;padding:7px 12px;font:inherit;cursor:pointer}
.lab kbd,.btn kbd{font:600 11px ui-monospace,Menlo,monospace;color:var(--muted);margin-right:5px}
.lab.on{border-color:var(--accent);background:var(--accent);color:var(--card)}
.lab.on kbd{color:var(--card)}
.lab.unsure.on{border-color:var(--red);background:var(--red)}
#notes{flex:1;min-width:200px;border:1px solid var(--line);border-radius:8px;padding:7px 10px;font:inherit;background:var(--bg);color:var(--ink)}
#help{position:fixed;inset:0;background:rgba(0,0,0,.45);display:none;align-items:center;justify-content:center;padding:16px}
#help.show{display:flex}
#help .box{background:var(--card);color:var(--ink);max-width:760px;max-height:90vh;overflow:auto;border-radius:12px;padding:16px 20px}
#help h2{margin-top:0;font-size:16px}
#help li{margin:3px 0}
.ovgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin-bottom:8px}
.ovcard{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.ovcard h3{margin:0 0 4px;font-size:15px}
.ovcard .bar{margin:10px 0 8px}
.ovrow{display:flex;justify-content:space-between;align-items:center;color:var(--muted)}
.ovh{font-size:14px;margin:16px 0 8px;color:var(--muted)}
.tzrow{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 12px;margin-bottom:8px}
.tzrow.done{border-color:var(--done)}
.tzinfo{margin-bottom:6px}
.tzinfo a{margin-left:8px;color:var(--accent)}
.tzbtns{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.tznote{flex:1;min-width:180px;border:1px solid var(--line);border-radius:8px;padding:6px 9px;font:inherit;background:var(--bg);color:var(--ink)}
.fullbtn{margin-top:10px}
.fullwrap{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}
@media (max-width:820px){.fullwrap{grid-template-columns:1fr}}
.fulltext{white-space:pre-wrap;overflow-wrap:anywhere;max-height:70vh;overflow:auto;font-size:13px;line-height:1.5}
.toast{position:fixed;right:16px;bottom:70px;background:var(--accent);color:var(--card);padding:6px 12px;border-radius:8px;opacity:0;transition:opacity .25s;pointer-events:none}
.toast.show{opacity:.95}
</style>
</head>
<body>
<header>
  <h1>AVSD 盲标</h1>
  <div class="tabs"><button id="t-ov">总览</button> <button id="t-b1">B1 memory 事实</button> <button id="t-b2">B2 父节点</button> <button id="t-tz">时区核对</button></div>
  <div class="prog"><span id="cnt"></span><div class="bar"><span id="barfill"></span></div></div>
  <button class="btn" id="b-prev"><kbd>←</kbd>上一条</button>
  <button class="btn" id="b-next">下一条<kbd>→</kbd></button>
  <button class="btn" id="b-todo"><kbd>G</kbd>下一条未标</button>
  <button class="btn" id="b-export">导出 CSV</button>
  <label class="btn" style="cursor:pointer">导入 CSV<input type="file" id="imp" accept=".csv" style="display:none"></label>
  <button class="btn" id="b-help"><kbd>?</kbd>说明</button>
  <span class="saved" id="saved"></span>
</header>
<main id="view"></main>
<footer id="foot"></footer>
<div id="help"><div class="box" id="helpbox"></div></div>
<div class="toast" id="toast"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
"use strict";
const DATA = JSON.parse(document.getElementById("data").textContent);
const STORE_KEY = "avsd_labeler_" + DATA.meta.id;
let store = {b1: {}, b2: {}, tz: {}, cur: {b1: 0, b2: 0}, task: "ov"};
try { const s = localStorage.getItem(STORE_KEY); if (s) { const o = JSON.parse(s); store = Object.assign(store, o); } } catch (e) {}
store.tz = store.tz || {}; store.cur = store.cur || {b1: 0, b2: 0};
let canSave = true;
function save() {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(store)); document.getElementById("saved").textContent = "已保存 " + new Date().toLocaleTimeString(); }
  catch (e) { if (canSave) { canSave = false; toast("浏览器不允许本地保存，请定期导出 CSV"); } }
}
const B1_LABELS = [["kept","K","两版都有这个事实，写法可以不同"],["modified","M","事实还在，取值换了"],["dropped","D","PREV 有，NEXT 没有，也没有新值"],["new","N","PREV 没有，NEXT 有，更早版本也没有"],["restored","R","PREV 没有，NEXT 有，更早版本出现过同一事实"]];
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function marks(s) {
  let h = esc(s);
  h = h.replace(/⟦([^⟧]*)⟧/g, '<mark class="v">$1</mark>').replace(/⟨([^⟩]*)⟩/g, '<mark class="c">$1</mark>');
  h = h.replace(/«masked»/g, '<span class="mask">«masked»</span>').replace(/↵/g, '<span class="nl">↵</span><br>');
  return h;
}
function splitWins(s) {
  if (!s) return {prefix: "", wins: []};
  const a = s.indexOf("[1] ");
  if (a < 0) return {prefix: "", wins: [s]};
  const prefix = s.slice(0, a).trim(), wins = [];
  let pos = a + 4, k = 1;
  for (;;) {
    const tag = " [" + (k + 1) + "] ", nxt = s.indexOf(tag, pos);
    if (nxt < 0) { wins.push(s.slice(pos)); break; }
    wins.push(s.slice(pos, nxt)); pos = nxt + tag.length; k++;
  }
  return {prefix, wins};
}
function winsHtml(w) {
  if (!w.wins.length) return '<div class="empty">（这个版本没有可显示的片段）</div>';
  return (w.prefix ? '<div class="note">' + esc(w.prefix) + "</div>" : "") +
    w.wins.map((x, i) => '<div class="win"><span class="n">[' + (i + 1) + "]</span>" + marks(x) + "</div>").join("");
}
const task = () => store.task;
const inAudit = r => !DATA.meta.audit || !!r.audit;
const rows = () => DATA[task()].filter(inAudit);
const keyIn = (t, r) => t === "b1" ? r.unit_key : t === "b2" ? r.child_uid : r.url;
const keyOf = r => keyIn(task(), r);
const rec = r => store[task()][keyOf(r)] || {};
const recIn = (t, r) => (store[t] || {})[keyIn(t, r)] || {};
const isDone = (r, t) => { const x = recIn(t || task(), r); return !!(x.label || x.parent || x.unsure || x.check); };
function setRec(r, patch) { const k = keyOf(r); store[task()][k] = Object.assign({}, store[task()][k] || {}, patch); save(); }
function cur() { return Math.min(Math.max(store.cur[task()] || 0, 0), rows().length - 1); }
function go(d) { store.cur[task()] = (cur() + d + rows().length) % rows().length; save(); render(); }
function nextTodo(from) {
  const n = rows().length, start = from == null ? cur() : from;
  for (let i = 1; i <= n; i++) { const j = (start + i) % n; if (!isDone(rows()[j])) { store.cur[task()] = j; save(); render(); return; } }
  toast("这一张表已经全部标完");
}
function viewB1(r, i) {
  const same = DATA.b1.filter(o => o.pair_id === r.pair_id), pos = same.indexOf(r) + 1;
  const val = /^h:/.test(r.value) ? "（人名，已哈希，看片段中的高亮）" : esc(r.value);
  return '<div class="meta"><span class="pill">第 ' + (i + 1) + " / " + rows().length + ' 条</span><span class="pill">版本对 ' + esc(r.pair_id) +
    "，本对第 " + pos + "/" + same.length + ' 个</span><span class="pill">' + esc(r.agent) + "</span>" +
    (isDone(r) ? '<span class="pill done">已标</span>' : '<span class="pill todo">未标</span>') + "</div>" +
    '<div class="unit"><span class="k">要判断的事实</span><b>' + esc(r.unit_type) + '</b><span class="k" style="margin-left:12px">值</span><mark class="v">' + val +
    '</mark><span class="k" style="margin-left:12px">上下文</span>' + (r.context_key ? esc(r.context_key) : "无") + "</div>" +
    '<div class="cols"><section class="col"><h3>PREV（重写前）</h3>' + winsHtml(splitWins(r.prev_excerpt)) +
    '</section><section class="col"><h3>NEXT（重写后）</h3>' + winsHtml(splitWins(r.next_excerpt)) + "</section></div>" +
    (r.earlier_excerpt ? '<section class="col earlier"><h3>EARLIER（更早的版本）</h3>' + winsHtml(splitWins(r.earlier_excerpt)) + "</section>" : "") +
    (DATA.full && DATA.full[r.pair_id] ? '<button class="btn fullbtn" id="b-full"><kbd>F</kbd>' + (showFull ? "收起完整版本" : "查看完整版本（可用 Cmd+F 搜索）") + "</button>" +
      (showFull ? fullHtml(r) : "") : "");
}
let showFull = false;
function hl(text, value) {
  let h = esc(text);
  if (value && !/^h:/.test(value)) { const v = esc(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); h = h.replace(new RegExp(v, "g"), m => '<mark class="v">' + m + "</mark>"); }
  return h;
}
function fullHtml(r) {
  const f = DATA.full[r.pair_id];
  return '<div class="fullwrap"><section class="col"><h3>PREV 全文（' + f.prev.length.toLocaleString() + ' 字符）</h3><div class="fulltext">' + hl(f.prev, r.value) +
    '</div></section><section class="col"><h3>NEXT 全文（' + f.next.length.toLocaleString() + ' 字符）</h3><div class="fulltext">' + hl(f.next, r.value) + "</div></section></div>";
}
function candsOf(r) {
  const out = [];
  for (let k = 1; k <= 6; k++) {
    const ch = r["cand_" + k + "_channel"], ex = r["cand_" + k + "_excerpt"];
    if (ch || ex) out.push({k, ch, who: r["cand_" + k + "_who"], dt: r["cand_" + k + "_dt_h"], ex});
  }
  return out;
}
function fmtDt(dt) { const x = parseFloat(dt); return isFinite(x) ? (x < 1 ? Math.round(x * 60) + " 分钟" : x.toFixed(1) + " 小时") : esc(dt); }
function viewB2(r, i) {
  const x = rec(r);
  return '<div class="meta"><span class="pill">第 ' + (i + 1) + " / " + rows().length + ' 条</span><span class="pill">' + esc(r.child_agent) +
    '</span><span class="pill">出现在 ' + esc(r.child_source) + "</span>" + (isDone(r) ? '<span class="pill done">已标</span>' : '<span class="pill todo">未标</span>') + "</div>" +
    '<div class="child"><div class="note">CHILD：' + esc(r.unit_type) + (r.unit_value ? "，值 " + esc(r.unit_value) : "") + "</div>" + marks(r.child_excerpt) + "</div>" +
    '<div class="cands">' + candsOf(r).map(c => '<div class="cand' + (x.parent === String(c.k) ? " sel" : "") + '" data-k="' + c.k + '"><div class="hd"><span class="num">' + c.k +
      "</span><b>" + esc(c.ch) + "</b><span>" + esc(c.who) + '</span><span class="note">早 ' + fmtDt(c.dt) + "</span></div>" + marks(c.ex) + "</div>").join("") + "</div>";
}
function footB1(r) {
  const x = rec(r);
  return B1_LABELS.map(([v, k, tip]) => '<button class="lab' + (x.label === v ? " on" : "") + '" data-v="' + v + '" title="' + tip + '"><kbd>' + k + "</kbd>" + v + "</button>").join("") +
    '<button class="lab unsure' + (x.unsure ? " on" : "") + '" data-v="__unsure" title="判断不了，在备注写原因"><kbd>U</kbd>判断不了</button>' +
    '<button class="lab' + (/bad_unit/.test(x.notes || "") ? " on" : "") + '" data-v="__bad" title="单元抽错了，仍按值是否出现来标"><kbd>B</kbd>bad_unit</button>' +
    '<input id="notes" placeholder="备注（按 / 进入，Enter 或 Esc 退出）" value="' + esc(x.notes || "") + '">';
}
function footB2(r) {
  const x = rec(r);
  return candsOf(r).map(c => '<button class="lab' + (x.parent === String(c.k) ? " on" : "") + '" data-v="' + c.k + '"><kbd>' + c.k + "</kbd>候选 " + c.k + "</button>").join("") +
    '<button class="lab' + (x.parent === "env" ? " on" : "") + '" data-v="env" title="agent 自己在电脑上看到的"><kbd>E</kbd>env</button>' +
    '<button class="lab' + (x.parent === "none" ? " on" : "") + '" data-v="none" title="所有候选都不像来源"><kbd>N</kbd>none</button>' +
    '<button class="lab unsure' + (x.unsure ? " on" : "") + '" data-v="__unsure"><kbd>U</kbd>判断不了</button>' +
    '<button class="lab' + (/bad_unit/.test(x.notes || "") ? " on" : "") + '" data-v="__bad"><kbd>B</kbd>bad_unit</button>' +
    '<input id="notes" placeholder="备注（按 / 进入，Enter 或 Esc 退出）" value="' + esc(x.notes || "") + '">';
}
function counts(t) { return DATA[t].filter(r => (t === "tz" || inAudit(r)) && isDone(r, t)).length; }
function total(t) { return DATA[t].filter(r => t === "tz" || inAudit(r)).length; }
const KIND = {turn: "电脑操作（turn）", agent_msg: "聊天发言", pause: "暂停"};
function viewOv() {
  const card = (t, title, desc) => { const n = total(t), d = counts(t);
    return '<div class="ovcard"><h3>' + title + '</h3><div class="note">' + desc + '</div><div class="bar"><span style="width:' + (100 * d / n).toFixed(1) +
      '%"></span></div><div class="ovrow"><span>已完成 ' + d + " / " + n + '</span><button class="btn" data-go="' + t + '">' + (d === 0 ? "开始" : d === n ? "查看" : "继续") + "</button></div></div>"; };
  return '<h2 class="ovh">需要你做的事</h2><div class="ovgrid">' +
    card("b1", "B1 memory 事实（抽查）", "随机抽出的 " + total("b1") + " 条。每条看一个事实在 memory 重写前后的状态，选 kept、modified、dropped、new 或 restored。键盘 K、M、D、N、R，按 F 看全文。") +
    card("b2", "B2 父节点（抽查）", "随机抽出的 " + total("b2") + " 条。每条从随机排序的候选里选出这条信息的来源，选候选编号、env 或 none。键盘 1 到 6、E、N。") + "</div>" +
    '<div class="note">其余条目由 Claude 独立盲标，时区核对也由 Claude 完成。你的抽查用来测 Claude 标得准不准，请独立判断。</div>' +
    '<h2 class="ovh">完成后</h2><div class="note">点右上角"导出 CSV"，会下载 memory_pairs_labeled.csv 和 parents_labeled.csv（以及一个可以忽略的 timezone_check.csv），然后告诉我。之前标过、但不在抽查里的条目也会一起导出，同样有用。标注自动保存在这个浏览器里，可以分几次标；按 ? 看标注说明。</div>' +
    '<h2 class="ovh">另外需要你决定（在对话里回复）</h2><div class="note">新发现的 63 个很可能是明文密码、且不在已发报告里的登录值，要不要补报给 AI Digest。</div>';
}
function viewTz() {
  const opts = [["match", "对得上"], ["offset", "时刻有固定偏差"], ["mismatch", "对不上"], ["cannot", "打不开或看不出"]];
  return '<div class="note" style="margin-bottom:10px">' + DATA.meta.tzhelp + "</div>" + DATA.tz.map((r, i) => { const x = recIn("tz", r);
    return '<div class="tzrow' + (x.check ? " done" : "") + '"><div class="tzinfo"><b>' + (i + 1) + ".</b> " + esc(r.ts_pt) + "（village day " + esc(r.village_day) + "），" +
      esc(r.agent) + "，" + esc(KIND[r.kind] || r.kind) + '<a href="' + esc(r.url) + '" target="_blank" rel="noopener noreferrer">打开网页</a></div><div class="tzbtns">' +
      opts.map(([v, l]) => '<button class="lab tzb' + (x.check === v ? " on" : "") + '" data-i="' + i + '" data-v="' + v + '">' + l + "</button>").join("") +
      '<input class="tznote" data-i="' + i + '" placeholder="备注，比如偏差几小时" value="' + esc(x.notes || "") + '"></div></div>'; }).join("");
}
function render() {
  const t = task();
  const tabs = {ov: "总览", b1: "B1 memory 事实（" + total("b1") + "）", b2: "B2 父节点（" + total("b2") + "）", tz: "时区核对（" + DATA.tz.length + "）"};
  document.getElementById("t-tz").style.display = DATA.meta.audit ? "none" : "";
  Object.keys(tabs).forEach(k => { const el = document.getElementById("t-" + k); el.textContent = tabs[k]; el.classList.toggle("on", t === k); });
  ["b-prev", "b-next", "b-todo"].forEach(id => document.getElementById(id).style.display = (t === "b1" || t === "b2") ? "" : "none");
  const all = DATA.meta.audit ? ["b1", "b2"] : ["b1", "b2", "tz"], done = all.reduce((s, k) => s + counts(k), 0), n = all.reduce((s, k) => s + total(k), 0);
  document.getElementById("cnt").textContent = all.map(k => ({b1: "B1 ", b2: "B2 ", tz: "时区 "}[k] + counts(k) + "/" + total(k))).join("，");
  document.getElementById("barfill").style.width = (100 * done / n).toFixed(1) + "%";
  const view = document.getElementById("view"), foot = document.getElementById("foot");
  if (t === "ov" || t === "tz") {
    if (t === "tz" && DATA.meta.audit) { store.task = "ov"; return render(); }
    view.innerHTML = t === "ov" ? viewOv() : viewTz(); foot.innerHTML = ""; foot.style.display = "none"; view.scrollTop = 0;
    view.querySelectorAll("[data-go]").forEach(el => el.onclick = () => { store.task = el.dataset.go; save(); render(); });
    view.querySelectorAll(".tzb").forEach(el => el.onclick = () => { const r = DATA.tz[+el.dataset.i], x = recIn("tz", r);
      store.tz[r.url] = Object.assign({}, x, {check: x.check === el.dataset.v ? "" : el.dataset.v}); save(); const y = view.scrollTop; render(); view.scrollTop = y; });
    view.querySelectorAll(".tznote").forEach(el => el.oninput = () => { const r = DATA.tz[+el.dataset.i]; store.tz[r.url] = Object.assign({}, recIn("tz", r), {notes: el.value}); save(); });
    return;
  }
  foot.style.display = "";
  const i = cur(), r = rows()[i];
  view.innerHTML = t === "b1" ? viewB1(r, i) : viewB2(r, i);
  foot.innerHTML = t === "b1" ? footB1(r) : footB2(r);
  view.scrollTop = 0;
  const bf = document.getElementById("b-full"); if (bf) bf.onclick = () => { showFull = !showFull; render(); };
  document.querySelectorAll(".cand").forEach(el => el.onclick = () => choose(el.dataset.k));
  document.querySelectorAll("#foot .lab").forEach(el => el.onclick = () => choose(el.dataset.v));
  const notes = document.getElementById("notes");
  notes.oninput = () => setRec(rows()[cur()], {notes: notes.value});
}
function choose(v) {
  const r = rows()[cur()], x = rec(r);
  if (v === "__bad") { const has = /bad_unit/.test(x.notes || ""); setRec(r, {notes: has ? (x.notes || "").replace(/\s*bad_unit\s*/, " ").trim() : ((x.notes || "") + " bad_unit").trim()}); render(); return; }
  if (v === "__unsure") { setRec(r, task() === "b1" ? {label: "", unsure: !x.unsure} : {parent: "", unsure: !x.unsure}); render(); if (!x.unsure) document.getElementById("notes").focus(); return; }
  if (task() === "b1") setRec(r, {label: x.label === v ? "" : v, unsure: false});
  else setRec(r, {parent: x.parent === String(v) ? "" : String(v), unsure: false});
  const nowDone = isDone(r);
  render();
  if (nowDone) setTimeout(() => nextTodo(cur()), 180);
}
function csvCell(v) { return '"' + String(v == null ? "" : v).replace(/"/g, '""') + '"'; }
function exportCsv() {
  ["b1", "b2", "tz"].forEach(t => {
    const cols = DATA.meta.cols[t];
    const out = DATA[t].map(r => { const x = recIn(t, r); const o = Object.assign({}, r);
      if (t === "b1") o.human_label = x.label || ""; else if (t === "b2") o.human_parent = x.parent || ""; else o.human_check = x.check || "";
      o.notes = x.notes || ""; return o; });
    const text = "\ufeff" + [cols.map(csvCell).join(",")].concat(out.map(o => cols.map(c => csvCell(o[c])).join(","))).join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], {type: "text/csv;charset=utf-8"}));
    a.download = {b1: "memory_pairs_labeled.csv", b2: "parents_labeled.csv", tz: "timezone_check.csv"}[t];
    document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  });
  toast("已导出三个 CSV 到浏览器的下载文件夹");
}
function parseCsv(text) {
  text = text.replace(/^\ufeff/, "");
  const out = []; let row = [], f = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += c; }
    else if (c === '"') q = true;
    else if (c === ",") { row.push(f); f = ""; }
    else if (c === "\n" || c === "\r") { if (c === "\r" && text[i + 1] === "\n") i++; row.push(f); out.push(row); row = []; f = ""; }
    else f += c;
  }
  if (f.length || row.length) { row.push(f); out.push(row); }
  const head = out.shift() || [];
  return out.filter(r => r.length > 1).map(r => Object.fromEntries(head.map((h, j) => [h, r[j] || ""])));
}
document.getElementById("imp").onchange = ev => {
  const file = ev.target.files[0]; if (!file) return;
  file.text().then(text => {
    const rs = parseCsv(text); let n = 0;
    rs.forEach(o => {
      if (o.unit_key && "human_label" in o) { if (o.human_label || o.notes) { store.b1[o.unit_key] = {label: o.human_label.trim().toLowerCase(), notes: o.notes || "", unsure: !o.human_label && !!o.notes}; n++; } }
      else if (o.url && "human_check" in o) { if (o.human_check || o.notes) { store.tz[o.url] = {check: o.human_check.trim().toLowerCase(), notes: o.notes || ""}; n++; } }
      else if (o.child_uid && "human_parent" in o) { if (o.human_parent || o.notes) { store.b2[o.child_uid] = {parent: o.human_parent.trim().toLowerCase(), notes: o.notes || "", unsure: !o.human_parent && !!o.notes}; n++; } }
    });
    save(); render(); toast("导入了 " + n + " 行标注");
  });
  ev.target.value = "";
};
function toast(msg) { const el = document.getElementById("toast"); el.textContent = msg; el.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => el.classList.remove("show"), 2200); }
document.getElementById("helpbox").innerHTML = DATA.meta.help;
const help = document.getElementById("help");
help.onclick = e => { if (e.target === help) help.classList.remove("show"); };
document.getElementById("b-help").onclick = () => help.classList.toggle("show");
document.getElementById("t-ov").onclick = () => { store.task = "ov"; save(); render(); };
document.getElementById("t-tz").onclick = () => { store.task = "tz"; save(); render(); };
document.getElementById("t-b1").onclick = () => { store.task = "b1"; save(); render(); };
document.getElementById("t-b2").onclick = () => { store.task = "b2"; save(); render(); };
document.getElementById("b-prev").onclick = () => go(-1);
document.getElementById("b-next").onclick = () => go(1);
document.getElementById("b-todo").onclick = () => nextTodo();
document.getElementById("b-export").onclick = exportCsv;
document.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT") { if (e.key === "Escape" || e.key === "Enter") { e.preventDefault(); e.target.blur(); } return; }
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (help.classList.contains("show")) { if (k === "escape" || k === "?") help.classList.remove("show"); return; }
  if (task() !== "b1" && task() !== "b2") { if (k === "?") { e.preventDefault(); help.classList.add("show"); } return; }
  let handled = true;
  if (k === "arrowright" || k === "]") go(1);
  else if (k === "arrowleft" || k === "[") go(-1);
  else if (k === "g") nextTodo();
  else if (k === "?") help.classList.add("show");
  else if (k === "/") document.getElementById("notes").focus();
  else if (k === "u") choose("__unsure");
  else if (k === "b") choose("__bad");
  else if (k === "f" && task() === "b1") { showFull = !showFull; render(); }
  else if (task() === "b1" && B1_LABELS.some(l => l[1].toLowerCase() === k)) choose(B1_LABELS.find(l => l[1].toLowerCase() === k)[0]);
  else if (task() === "b2" && /^[1-6]$/.test(k) && candsOf(rows()[cur()]).some(c => String(c.k) === k)) choose(k);
  else if (task() === "b2" && k === "e") choose("env");
  else if (task() === "b2" && k === "n") choose("none");
  else handled = false;
  if (handled) e.preventDefault();
});
render();
</script>
</body>
</html>
"""

HELP = """<h2>标注说明</h2>
<p>所有模型给的标签、后验和推断结果都已去掉，B2 的候选顺序是随机的。请只根据片段原文判断。标注只存在这个浏览器里（自动保存），标完点"导出 CSV"，把下载的两个文件交给我。</p>
<h3>B1：memory 事实（human_label）</h3>
<ul>
<li><b>K kept</b>：PREV 和 NEXT 都有这个事实，写法可以不同。</li>
<li><b>M modified</b>：PREV 有；NEXT 里这个事实还在，但取值换了，比如捐款人数从 56 变成 60。</li>
<li><b>D dropped</b>：PREV 有；NEXT 里既没有这个值，也没有同一事实的新值。</li>
<li><b>N new</b>：PREV 没有，NEXT 有，更早的版本里也没有。</li>
<li><b>R restored</b>：PREV 没有，NEXT 有，更早的版本里出现过同一个事实。</li>
</ul>
<p>注意：黄色高亮只标出程序找到的同值文字，同一个值换了写法（别的连字符，"56 位捐款人"写成"捐款人：56"）不会高亮，请以原文为准。蓝色高亮是同一上下文里的其他取值。EARLIER 只说明更早版本出现过相同的取值，只有说的是同一个事实才算 restored，用在不相关的地方应标 new。数字、金额、百分比和时刻要连同上下文一起看。</p>
<h3>B2：父节点（human_parent）</h3>
<ul>
<li><b>1 到 6</b>：CHILD 最可能是从这条候选得到这条信息的。</li>
<li><b>E env</b>：agent 是自己在电脑上看到的，独立得到。</li>
<li><b>N none</b>：所有候选都不像来源。</li>
</ul>
<p>看内容是否对得上（同样的数字、同样的说法、直接回复），不要只看时间最近。</p>
<h3>时区核对</h3>
<p>每个链接会把 AI Village 网页定位到那一天、那个时刻。看网页上这个时刻附近，表里写的 agent 是否在做表里写的事（电脑操作、聊天发言或暂停）。如果每条都差同样几个小时，选"时刻有固定偏差"并在备注写差几小时。</p>
<h3>通用</h3>
<ul>
<li><b>F</b>（B1）展开或收起 PREV 和 NEXT 的全文，黄色是和值完全相同的文字，换了写法的请用 Cmd+F 搜索。</li>
<li><b>U</b> 判断不了：标签留空，在备注写原因。<b>B</b> bad_unit：单元抽错了，仍按值是否出现来标。</li>
<li><b>← →</b> 翻页，<b>G</b> 跳到下一条未标，<b>/</b> 写备注（Enter 或 Esc 退出），<b>?</b> 打开或关闭说明。选好标签后自动跳到下一条未标。</li>
<li>再按一次同一个标签可以取消。换浏览器或电脑时，用"导入 CSV"载入之前导出的文件继续标。</li>
</ul>
<p>页面里有 memory 和聊天的原文片段，含人名等个人信息。这个文件和导出的 CSV 只留在本机，不要分享或上传。</p>"""


TZHELP = ("阶段 0 的抽查：每个链接把 AI Village 网页定位到那一天、那个时刻（表里的时间是太平洋时间）。请看那个时刻附近，"
          "表里写的 agent 是否在做表里写的事。全部对得上，说明我们的时区和 village day 换算是对的。如果都差同样几个小时，"
          "选\"时刻有固定偏差\"并在备注写差几小时。")


def read(path: Path) -> tuple[list[dict], list[str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        return list(rd), list(rd.fieldnames or [])


def main() -> None:
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    b1, c1 = read(src / "memory_pairs_blind.csv")
    b2, c2 = read(src / "parents_blind.csv")
    tz, c3 = read(src / "timezone_spotcheck.csv")
    ap = src / "audit_sample.json"
    audit = json.loads(ap.read_text(encoding="utf-8")) if ap.exists() else None
    if audit:
        for r in b1:
            r["audit"] = r["unit_key"] in audit["b1"]
        for r in b2:
            r["audit"] = r["child_uid"] in audit["b2"]
    fp = src / "memory_pairs_fulltext.json"
    full = json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else {}
    data = {"meta": {"id": "blind_20261001", "cols": {"b1": c1, "b2": c2, "tz": c3}, "help": HELP, "tzhelp": TZHELP, "audit": bool(audit)},
            "b1": b1, "b2": b2, "tz": tz, "full": full}
    blob = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")  # no "<" left, so no </script> or <!-- inside the JSON
    out.write_text(TEMPLATE.replace("__DATA__", blob), encoding="utf-8")
    out.chmod(0o600)
    print(f"{out}: B1 {len(b1)} rows, B2 {len(b2)} rows, timezone {len(tz)} rows, {out.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
