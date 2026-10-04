/* avsd report: tabs, interactive tables, the module C chart. Vanilla JS, no network. */
(function () {
  "use strict";

  var PAGE = 50;
  var NULL_KEY = "\u0000null";
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
  var VIEWS = JSON.parse(document.getElementById("avsd-views").textContent);
  var DATA = {};
  var WIDGETS = {};
  var TABS = $$(".tab").map(function (a) { return a.getAttribute("data-tab"); });
  var nf = new Intl.NumberFormat("en-US");
  var collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
  var WEEK = "日一二三四五六";

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }
  function debounce(fn, ms) {
    var t;
    return function () { var a = arguments, s = this; clearTimeout(t); t = setTimeout(function () { fn.apply(s, a); }, ms); };
  }
  function isNum(c) { return c.type === "int" || c.type === "float"; }
  function isNil(v) { return v === null || v === undefined || v === ""; }

  /* ---------- embedded data ---------- */
  function decode(raw) {
    var cols = raw.columns.map(function (c, k) { return { name: c.n, type: c.t, k: k }; });
    var arrays = raw.data.map(function (c) {
      return Array.isArray(c) ? c : c.i.map(function (j) { return c.d[j]; });
    });
    var rows = new Array(raw.n);
    for (var r = 0; r < raw.n; r++) {
      var row = new Array(cols.length);
      for (var k = 0; k < cols.length; k++) row[k] = arrays[k][r];
      rows[r] = row;
    }
    return { name: raw.name, cols: cols, rows: rows, total: raw.total, truncated: raw.truncated, hidden: raw.hidden || [] };
  }
  function getData(id) {
    if (!(id in DATA)) {
      var node = document.getElementById(id);
      DATA[id] = node ? decode(JSON.parse(node.textContent)) : null;
    }
    return DATA[id];
  }

  /* ---------- cell formatting ---------- */
  function fmtNum(v, type) {
    if (typeof v !== "number") return String(v);
    var a = Math.abs(v);
    if (a === 0) return "0";
    if (type === "int") return a >= 10000 ? nf.format(v) : String(v);
    if (a >= 1e15 || a < 1e-4) return v.toExponential(2);
    if (Number.isInteger(v)) return a >= 10000 ? nf.format(v) : v.toFixed(1);
    if (a >= 10000) return nf.format(Math.round(v));
    if (a >= 100) return v.toFixed(1);
    return String(Number(v.toPrecision(4)));
  }
  var URL_RE = /^https?:\/\/\S+$/;
  function renderCell(td, v, col) {
    if (isNil(v)) { td.className = "nil"; return; }
    if (isNum(col)) {
      var s = fmtNum(v, col.type);
      td.className = "num";
      td.textContent = s;
      if (s !== String(v)) td.title = String(v);
      return;
    }
    if (col.type === "bool") {
      td.className = "bool " + (v ? "is-true" : "is-false");
      td.textContent = String(v);
      return;
    }
    var str = String(v);
    if (/^https?:\/\//.test(str)) {
      var parts = str.split(/\s+/).filter(Boolean);
      if (parts.every(function (p) { return URL_RE.test(p); })) {
        td.className = "links";
        parts.forEach(function (p, i) {
          var a = el("a", null, parts.length > 1 ? "链接 " + (i + 1) : "链接");
          a.href = p; a.target = "_blank"; a.rel = "noopener noreferrer"; a.title = p;
          td.appendChild(a);
        });
        return;
      }
    }
    td.textContent = str;
    if (str.length > 40) { td.className = "long"; td.title = str; }
  }
  function csvCell(v) {
    if (isNil(v)) return "";
    var s = String(v);
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }
  function optionLabel(v) { return v === NULL_KEY ? "（空）" : v; }

  /* ---------- interactive table ---------- */
  function TableWidget(node) {
    var view = VIEWS[node.id] || {};
    var T = getData(view.src || node.getAttribute("data-src"));
    this.listeners = []; this.context = []; this.filtered = []; this.filters = [];
    node.textContent = "";
    if (!T) { node.appendChild(el("p", "loading", "数据缺失")); return; }
    var self = this;
    this.node = node; this.T = T; this.view = view;
    var idx = {};
    T.cols.forEach(function (c) { idx[c.name] = c.k; });
    this.idx = idx;
    var fixed = (view.fixed || []).filter(function (f) { return f.col in idx; });
    this.base = [];
    for (var r = 0; r < T.rows.length; r++) {
      var row = T.rows[r];
      if (fixed.every(function (f) { return passFixed(row[idx[f.col]], f); })) this.base.push(r);
    }
    var cols = (view.columns || []).map(function (n) { return idx[n]; }).filter(function (k) { return k !== undefined; });
    this.defaultVisible = cols.length ? cols : T.cols.map(function (c) { return c.k; });
    this.visible = this.defaultVisible.slice();
    this.filters = (view.filters || []).filter(function (f) { return f.col in idx; }).map(function (f) {
      return { type: f.type, col: f.col, label: f.label || f.col, k: idx[f.col], dflt: f["default"] };
    });
    this.sort = null; this.page = 0; this.q = ""; this.hayKey = ""; this.hay = null;
    this.build();
    this.reset();
    node.addEventListener("click", function (e) {
      var td = e.target.closest ? e.target.closest("td.long") : null;
      if (td && self.tbody.contains(td)) td.classList.toggle("open");
    });
  }
  function passFixed(v, f) {
    if (f.op === "notnull") return !isNil(v);
    if (f.op === "prefix") return !isNil(v) && String(v).indexOf(f.value) === 0;
    if (f.op === "eq") return String(v) === String(f.value);
    return true;
  }
  TableWidget.prototype.build = function () {
    var self = this, T = this.T;
    var bar = el("div", "toolbar");
    var qWrap = el("label", "ctl", "筛选（当前显示的列）");
    var q = el("input"); q.type = "search"; q.placeholder = "输入关键词";
    q.addEventListener("input", debounce(function () { self.q = q.value; self.page = 0; self.apply(); }, 150));
    qWrap.appendChild(q); bar.appendChild(qWrap); this.qInput = q;

    this.filters.forEach(function (f) {
      var wrap = f.type === "daterange" ? el("div", "ctl ctl-date", f.label) : el("label", "ctl", f.label);
      if (f.type === "daterange") wrap.setAttribute("role", "group");
      if (f.type === "select") {
        var s = el("select"), counts = {};
        self.base.forEach(function (r) {
          var v = T.rows[r][f.k], key = isNil(v) ? NULL_KEY : String(v);
          counts[key] = (counts[key] || 0) + 1;
        });
        var keys = Object.keys(counts), num = isNum(T.cols[f.k]);
        keys.sort(function (a, b) {
          if (a === NULL_KEY || b === NULL_KEY) return a === NULL_KEY ? 1 : -1;
          return num ? Number(a) - Number(b) : collator.compare(a, b);
        });
        s.appendChild(new Option("全部", ""));
        keys.forEach(function (k) { s.appendChild(new Option(optionLabel(k) + "（" + nf.format(counts[k]) + "）", k)); });
        s.addEventListener("change", function () { f.value = s.value; self.page = 0; self.apply(); });
        f.input = s; wrap.appendChild(s);
      } else if (f.type === "text") {
        var t = el("input"); t.type = "search"; t.placeholder = "包含…";
        t.addEventListener("input", debounce(function () { f.value = t.value.trim().toLowerCase(); self.page = 0; self.apply(); }, 150));
        f.input = t; wrap.appendChild(t);
      } else if (f.type === "daterange") {
        var lo = null, hi = null;
        self.base.forEach(function (r) {
          var v = T.rows[r][f.k];
          if (isNil(v)) return;
          v = String(v).slice(0, 10);
          if (lo === null || v < lo) lo = v;
          if (hi === null || v > hi) hi = v;
        });
        var range = el("span", "range"), a = el("input"), b = el("input");
        [a, b].forEach(function (x) { x.type = "date"; if (lo) x.min = lo; if (hi) x.max = hi; });
        a.setAttribute("aria-label", f.label + " 起"); b.setAttribute("aria-label", f.label + " 止");
        var on = function () { f.from = a.value; f.to = b.value; self.page = 0; self.apply(); };
        a.addEventListener("change", on); b.addEventListener("change", on);
        range.appendChild(a); range.appendChild(el("span", null, "至")); range.appendChild(b);
        f.inputs = [a, b]; wrap.appendChild(range);
      }
      bar.appendChild(wrap);
    });

    if (T.cols.length > 6) {
      var pick = el("details", "colpick");
      var sum = el("summary", "btn"); pick.appendChild(sum); this.colSummary = sum;
      var panel = el("div", "colpick-panel");
      var acts = el("div", "colpick-actions");
      var all = el("button", "btn", "全部列"), def = el("button", "btn", "默认列");
      all.type = def.type = "button";
      all.addEventListener("click", function () { self.visible = T.cols.map(function (c) { return c.k; }); self.syncCols(); self.apply(); });
      def.addEventListener("click", function () { self.visible = self.defaultVisible.slice(); self.syncCols(); self.apply(); });
      acts.appendChild(all); acts.appendChild(def); panel.appendChild(acts);
      this.colBoxes = T.cols.map(function (c) {
        var lab = el("label"), box = el("input");
        box.type = "checkbox"; box.value = c.k;
        box.addEventListener("change", function () {
          var on = {};
          self.colBoxes.forEach(function (b) { if (b.checked) on[b.value] = 1; });
          self.visible = T.cols.filter(function (cc) { return on[cc.k]; }).map(function (cc) { return cc.k; });
          self.syncCols(); self.apply();
        });
        lab.appendChild(box); lab.appendChild(document.createTextNode(c.name)); panel.appendChild(lab);
        return box;
      });
      pick.appendChild(panel);
      document.addEventListener("click", function (e) { if (pick.open && !pick.contains(e.target)) pick.open = false; });
      bar.appendChild(pick);
    }
    var reset = el("button", "btn", "重置"); reset.type = "button"; reset.title = "恢复默认筛选、排序与列";
    reset.addEventListener("click", function () { self.reset(); });
    var dl = el("button", "btn primary", "下载 CSV"); dl.type = "button"; dl.title = "导出筛选后的行（当前显示的列）";
    dl.addEventListener("click", function () { self.download(); });
    bar.appendChild(reset); bar.appendChild(dl);
    this.node.appendChild(bar);

    this.info = el("p", "info");
    this.node.appendChild(this.info);
    var scroll = el("div", "scroll"), table = el("table", "data-table");
    this.thead = el("thead"); this.tbody = el("tbody");
    table.appendChild(this.thead); table.appendChild(this.tbody); scroll.appendChild(table);
    this.node.appendChild(scroll); this.scroll = scroll;
    this.thead.addEventListener("click", function (e) {
      var b = e.target.closest ? e.target.closest("button.sort") : null;
      if (!b) return;
      var k = Number(b.getAttribute("data-k"));
      if (!self.sort || self.sort.k !== k) self.sort = { k: k, dir: 1 };
      else if (self.sort.dir === 1) self.sort.dir = -1;
      else self.sort = null;
      self.apply();
    });
    this.pager = el("div", "pager");
    this.node.appendChild(this.pager);
    var notes = [];
    if (T.truncated) notes.push("文件共 " + nf.format(T.total) + " 行，页面只嵌入前 " + nf.format(T.rows.length) + " 行");
    if (T.hidden.length) notes.push("按隐私规则隐藏列：" + T.hidden.join("、"));
    if (notes.length) { this.node.appendChild(el("p", "info", notes.join("；") + "。")); }
  };
  TableWidget.prototype.syncCols = function () {
    var on = {};
    this.visible.forEach(function (k) { on[k] = 1; });
    if (this.colBoxes) this.colBoxes.forEach(function (b) { b.checked = !!on[b.value]; });
    if (this.colSummary) this.colSummary.textContent = "列 " + this.visible.length + "/" + this.T.cols.length;
  };
  TableWidget.prototype.reset = function () {
    this.q = ""; this.qInput.value = ""; this.sort = null; this.page = 0;
    this.filters.forEach(function (f) {
      if (f.type === "select") {
        var d = f.dflt === undefined || f.dflt === null ? "" : String(f.dflt);
        var ok = Array.prototype.some.call(f.input.options, function (o) { return o.value === d; });
        f.value = ok ? d : ""; f.input.value = f.value;
      } else if (f.type === "text") { f.value = ""; f.input.value = ""; }
      else if (f.type === "daterange") { f.from = f.to = ""; f.inputs[0].value = f.inputs[1].value = ""; }
    });
    this.visible = this.defaultVisible.slice();
    this.syncCols();
    this.apply();
  };
  TableWidget.prototype.haystack = function (r) {
    var key = this.visible.join(",");
    if (this.hayKey !== key) { this.hay = {}; this.hayKey = key; }
    if (!(r in this.hay)) {
      var row = this.T.rows[r];
      this.hay[r] = this.visible.map(function (k) { return isNil(row[k]) ? "" : String(row[k]); }).join("\u0001").toLowerCase();
    }
    return this.hay[r];
  };
  TableWidget.prototype.apply = function () {
    var T = this.T, self = this, q = this.q.trim().toLowerCase();
    var sel = this.filters.filter(function (f) { return f.type === "select" && f.value; });
    var txt = this.filters.filter(function (f) { return f.type === "text" && f.value; });
    var dr = this.filters.filter(function (f) { return f.type === "daterange" && (f.from || f.to); });
    // `context` passes every filter except the date range; the linked chart draws it.
    var out = [], context = [];
    for (var i = 0; i < this.base.length; i++) {
      var r = this.base[i], row = T.rows[r], ok = true, j, f, v;
      for (j = 0; ok && j < sel.length; j++) {
        f = sel[j]; v = row[f.k];
        ok = f.value === NULL_KEY ? isNil(v) : (!isNil(v) && String(v) === f.value);
      }
      for (j = 0; ok && j < txt.length; j++) {
        f = txt[j]; v = row[f.k];
        ok = !isNil(v) && String(v).toLowerCase().indexOf(f.value) >= 0;
      }
      if (ok && q) ok = this.haystack(r).indexOf(q) >= 0;
      if (!ok) continue;
      context.push(row);
      for (j = 0; ok && j < dr.length; j++) {
        f = dr[j]; v = row[f.k];
        if (isNil(v)) { ok = false; break; }
        v = String(v).slice(0, 10);
        ok = !(f.from && v < f.from) && !(f.to && v > f.to);
      }
      if (ok) out.push(r);
    }
    this.context = context;
    if (this.sort) {
      var k = this.sort.k, dir = this.sort.dir, col = T.cols[k], num = isNum(col);
      out.sort(function (a, b) {
        var va = T.rows[a][k], vb = T.rows[b][k];
        var na = isNil(va) || (num && typeof va !== "number"), nb = isNil(vb) || (num && typeof vb !== "number");
        if (na || nb) return na === nb ? a - b : (na ? 1 : -1);
        var c = num ? va - vb : col.type === "bool" ? (va === vb ? 0 : va ? 1 : -1) : collator.compare(String(va), String(vb));
        return c === 0 ? a - b : c * dir;
      });
    }
    this.filtered = out;
    var pages = Math.max(1, Math.ceil(out.length / PAGE));
    if (this.page >= pages) this.page = pages - 1;
    this.render();
    this.listeners.forEach(function (fn) { fn(context, self); });
  };
  TableWidget.prototype.onChange = function (fn) {
    this.listeners.push(fn);
    fn(this.context, this);
  };
  TableWidget.prototype.dateFilter = function () {
    return this.filters.filter(function (f) { return f.type === "daterange"; })[0] || null;
  };
  TableWidget.prototype.setDateRange = function (from, to) {
    var f = this.dateFilter();
    if (!f) return;
    f.from = from || ""; f.to = to || "";
    f.inputs[0].value = f.from; f.inputs[1].value = f.to;
    this.page = 0;
    this.apply();
  };
  TableWidget.prototype.render = function () {
    var self = this, T = this.T, s = this.sort;
    this.thead.textContent = "";
    var tr = el("tr");
    this.visible.forEach(function (k) {
      var c = T.cols[k], th = el("th", isNum(c) ? "num" : "");
      th.scope = "col";
      th.setAttribute("aria-sort", s && s.k === k ? (s.dir > 0 ? "ascending" : "descending") : "none");
      var b = el("button", "sort", c.name);
      b.type = "button"; b.setAttribute("data-k", k); b.title = "点击排序";
      b.appendChild(el("span", "ind", s && s.k === k ? (s.dir > 0 ? "▲" : "▼") : ""));
      th.appendChild(b); tr.appendChild(th);
    });
    this.thead.appendChild(tr);
    this.tbody.textContent = "";
    var n = this.filtered.length, start = this.page * PAGE, end = Math.min(n, start + PAGE);
    var frag = document.createDocumentFragment();
    for (var i = start; i < end; i++) {
      var row = T.rows[this.filtered[i]], r = el("tr");
      for (var j = 0; j < this.visible.length; j++) {
        var td = el("td");
        renderCell(td, row[this.visible[j]], T.cols[this.visible[j]]);
        r.appendChild(td);
      }
      frag.appendChild(r);
    }
    if (!n) {
      var er = el("tr"), ed = el("td", "empty-row", "没有符合条件的行");
      ed.colSpan = Math.max(1, this.visible.length); er.appendChild(ed); frag.appendChild(er);
    }
    this.tbody.appendChild(frag);
    var txt = n ? "显示第 " + nf.format(start + 1) + "–" + nf.format(end) + " 行，共 " + nf.format(n) + " 行" : "共 0 行";
    if (n !== this.base.length) txt += "（筛选自 " + nf.format(this.base.length) + " 行）";
    this.info.textContent = txt;
    this.pager.textContent = "";
    var pages = Math.max(1, Math.ceil(n / PAGE));
    if (pages > 1) {
      var mk = function (label, page, disabled) {
        var b = el("button", "btn", label); b.type = "button"; b.disabled = disabled;
        b.addEventListener("click", function () { self.page = page; self.render(); self.scroll.scrollTop = 0; });
        self.pager.appendChild(b);
      };
      mk("« 首页", 0, this.page === 0);
      mk("‹ 上一页", this.page - 1, this.page === 0);
      this.pager.appendChild(el("span", null, "第 " + (this.page + 1) + " / " + pages + " 页"));
      mk("下一页 ›", this.page + 1, this.page >= pages - 1);
      mk("末页 »", pages - 1, this.page >= pages - 1);
    }
  };
  TableWidget.prototype.download = function () {
    var T = this.T, vis = this.visible;
    var lines = [vis.map(function (k) { return csvCell(T.cols[k].name); }).join(",")];
    this.filtered.forEach(function (r) {
      var row = T.rows[r];
      lines.push(vis.map(function (k) { return csvCell(row[k]); }).join(","));
    });
    var blob = new Blob(["﻿" + lines.join("\r\n") + "\r\n"], { type: "text/csv;charset=utf-8" });
    var a = el("a");
    a.href = URL.createObjectURL(blob);
    a.download = T.name.replace(/\.[^.]+$/, "") + "_filtered.csv";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
  };

  /* ---------- static markdown tables: click to sort ---------- */
  function makeSortable(table) {
    if (!table.tHead || !table.tBodies.length) return;
    var ths = Array.prototype.slice.call(table.tHead.rows[0].cells);
    ths.forEach(function (th, k) {
      th.classList.add("sortable"); th.tabIndex = 0; th.title = "点击排序";
      var go = function () {
        var dir = th.getAttribute("aria-sort") === "ascending" ? -1 : 1;
        ths.forEach(function (t) { t.removeAttribute("aria-sort"); });
        th.setAttribute("aria-sort", dir > 0 ? "ascending" : "descending");
        var body = table.tBodies[0], rows = Array.prototype.slice.call(body.rows);
        var key = function (r) { return r.cells[k] ? r.cells[k].textContent.trim() : ""; };
        var parse = function (s) { return Number(s.replace(/[,%\s]/g, "").replace(/^\+/, "")); };
        var num = rows.every(function (r) { var s = key(r); return s === "" || !isNaN(parse(s)); });
        rows.forEach(function (r, i) { r._i = i; });
        rows.sort(function (a, b) {
          var sa = key(a), sb = key(b);
          if (sa === "" || sb === "") return sa === sb ? a._i - b._i : (sa === "" ? 1 : -1);
          var c = num ? parse(sa) - parse(sb) : collator.compare(sa, sb);
          return c === 0 ? a._i - b._i : c * dir;
        });
        rows.forEach(function (r) { body.appendChild(r); });
      };
      th.addEventListener("click", go);
      th.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    });
  }

  /* ---------- module C chart ---------- */
  var SVGNS = "http://www.w3.org/2000/svg";
  function svg(tag, attrs, parent) {
    var e = document.createElementNS(SVGNS, tag);
    for (var a in attrs) e.setAttribute(a, attrs[a]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function dayNum(s) {
    if (isNil(s)) return null;
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(s));
    return m ? Math.round(Date.UTC(+m[1], +m[2] - 1, +m[3]) / 864e5) : null;
  }
  function dayStr(d) { return new Date(d * 864e5).toISOString().slice(0, 10); }
  function niceTicks(max) {
    if (max <= 0) return [0, 1];
    var raw = max / 4, mag = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / mag;
    var step = Math.max(1, (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * mag);
    var out = [];
    for (var v = 0; v <= Math.ceil(max / step) * step + 1e-9; v += step) out.push(v);
    return out;
  }

  function CpChart(node, panel) {
    var cfg = VIEWS[node.id] || {}, T = getData(cfg.src), self = this;
    node.textContent = "";
    if (!T) { node.appendChild(el("p", "loading", "数据缺失")); return; }
    var ci = function (n) { var c = T.cols.filter(function (x) { return x.name === n; })[0]; return c ? c.k : -1; };
    this.k = { date: ci("date"), run: ci("run_day"), aligned: ci("aligned"), doc: ci("aligned_documented"),
      goal: ci("nearest_goal_transition_date") };
    if (this.k.date < 0) { node.appendChild(el("p", "loading", "变点表缺少 date 列")); return; }
    this.node = node; this.T = T; this.basis = this.k.aligned >= 0 ? this.k.aligned : this.k.doc;
    this.entries = (cfg.entries || []).map(function (e) {
      return { id: e.id, c: e.c, r: e.r, s: e.s, e: e.e, sd: dayNum(e.s), ed: dayNum(e.e) };
    }).filter(function (e) { return e.sd !== null; });
    // Village goal transitions: the distinct nearest_goal_transition_date values of the table.
    var lo = Infinity, hi = -Infinity, runOf = {}, goals = new Set();
    T.rows.forEach(function (row) {
      var d = dayNum(row[self.k.date]);
      if (self.k.goal >= 0 && !isNil(row[self.k.goal])) goals.add(dayNum(row[self.k.goal]));
      if (d === null) return;
      if (d < lo) lo = d;
      if (d > hi) hi = d;
      if (self.k.run >= 0 && !isNil(row[self.k.run])) runOf[d] = row[self.k.run];
    });
    goals.delete(null);
    this.goals = goals;
    this.entries.forEach(function (e) { lo = Math.min(lo, e.sd); hi = Math.max(hi, e.ed); });
    if (!isFinite(lo)) { node.appendChild(el("p", "loading", "没有可画的日期")); return; }
    this.lo = lo - 3; this.hi = hi + 3; this.runOf = runOf;

    var controls = el("div", "cp-controls"), legend = el("div", "legend");
    var keys = [["sw aligned", "对齐"], ["sw unaligned", "未对齐"], ["sw mark", "CHANGELOG 变更"], ["sw mark2", "roster 变动"]];
    if (goals.size) keys.push(["sw dot", "village goal 切换"]);
    keys.forEach(function (x) {
      var s = el("span"); s.appendChild(el("i", x[0])); s.appendChild(document.createTextNode(x[1])); legend.appendChild(s);
    });
    controls.appendChild(legend);
    if (this.k.aligned >= 0 && this.k.doc >= 0) {
      var lab = el("label", null, "对齐口径 "), sel = el("select");
      sel.appendChild(new Option("CHANGELOG 条目（aligned）", "aligned"));
      sel.appendChild(new Option("已知事件，含 goal 切换（aligned_documented）", "doc"));
      sel.className = "btn";
      sel.addEventListener("change", function () { self.basis = self.k[sel.value]; self.draw(); });
      lab.appendChild(sel); controls.appendChild(lab);
    }
    node.appendChild(controls);
    this.summary = el("p", "cp-summary");
    node.appendChild(this.summary);
    this.wrap = el("div", "cp-wrap");
    this.wrap.tabIndex = 0;
    this.wrap.setAttribute("role", "group");
    this.wrap.setAttribute("aria-label", "每个运行日的变点数柱状图；左右方向键移动，回车筛选表格");
    this.tip = el("div", "tooltip"); this.tip.hidden = true;
    node.appendChild(this.wrap);

    var tblNode = panel.querySelector('.tbl[data-src="' + cfg.src + '"]');
    this.table = tblNode ? WIDGETS[tblNode.id] : null;
    this.rows = T.rows;
    if (this.table && this.table.onChange) this.table.onChange(function (rows) { self.rows = rows; self.draw(); });
    else this.draw();

    var redraw = debounce(function () { self.draw(); }, 120);
    if (window.ResizeObserver) new ResizeObserver(redraw).observe(this.wrap);
    else window.addEventListener("resize", redraw);
    var pointer = function (e) {
      var rect = self.wrap.getBoundingClientRect();
      self.hover(self.snap(e.clientX - rect.left), e.clientX - rect.left, e.clientY - rect.top);
    };
    this.wrap.addEventListener("pointermove", pointer);
    this.wrap.addEventListener("pointerdown", pointer);
    this.wrap.addEventListener("pointerleave", function () { self.hover(null); });
    this.wrap.addEventListener("click", function (e) {
      var rect = self.wrap.getBoundingClientRect(), d = self.snap(e.clientX - rect.left);
      if (d !== null) self.pick(d);
    });
    this.wrap.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight" && e.key !== "Enter") return;
      e.preventDefault();
      var days = self.days(), cur = self.cur;
      if (!days.length) return;
      if (e.key === "Enter") { if (cur !== null && cur !== undefined) self.pick(cur); return; }
      var i = cur === null || cur === undefined ? -1 : days.indexOf(cur);
      i = e.key === "ArrowRight" ? Math.min(days.length - 1, i + 1) : Math.max(0, i < 0 ? days.length - 1 : i - 1);
      var x = self.x(days[i]);
      self.hover(days[i], x, self.geom.top + 10);
    });
  }
  CpChart.prototype.days = function () {
    var set = {};
    this.byDay.forEach(function (v, d) { set[d] = 1; });
    this.entries.forEach(function (e) { set[e.sd] = 1; });
    this.goals.forEach(function (d) { set[d] = 1; });
    return Object.keys(set).map(Number).sort(function (a, b) { return a - b; });
  };
  CpChart.prototype.draw = function () {
    var self = this, W = Math.max(320, Math.round(this.wrap.clientWidth || 800)), small = W < 600;
    var H = small ? 224 : 264, m = { l: 46, r: 12, t: 58, b: 26 };
    var byDay = new Map(), total = 0, nA = 0, kA = this.basis;
    this.rows.forEach(function (row) {
      var d = dayNum(row[self.k.date]);
      if (d === null) return;
      var c = byDay.get(d);
      if (!c) { c = { a: 0, u: 0 }; byDay.set(d, c); }
      if (kA >= 0 && row[kA] === true) { c.a++; nA++; } else c.u++;
      total++;
    });
    this.byDay = byDay;
    var ymax = 0;
    byDay.forEach(function (c) { ymax = Math.max(ymax, c.a + c.u); });
    var ticks = niceTicks(ymax), ytop = ticks[ticks.length - 1] || 1;
    var span = this.hi - this.lo, pw = W - m.l - m.r, ppd = pw / span;
    var x = function (d) { return m.l + (d - self.lo) * ppd; };
    var y = function (v) { return H - m.b - v / ytop * (H - m.t - m.b); };
    this.x = x; this.ppd = ppd; this.geom = { top: m.t, bottom: H - m.b, left: m.l, right: W - m.r, H: H };
    var bw = Math.max(1, Math.min(8, ppd * 0.72));

    this.wrap.textContent = "";
    var s = svg("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H, role: "img",
      "aria-label": "每个运行日的变点数，按是否对齐分色，顶部为 CHANGELOG 条目" }, this.wrap);
    ticks.forEach(function (t) {
      svg("line", { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), "class": t === 0 ? "axis" : "grid" }, s);
      svg("text", { x: m.l - 6, y: y(t) + 4, "text-anchor": "end", "class": "tick-text" }, s).textContent = nf.format(t);
    });
    var d0 = new Date(this.lo * 864e5), step = small ? 3 : pw < 900 ? 2 : 1;
    var mo = new Date(Date.UTC(d0.getUTCFullYear(), d0.getUTCMonth() + 1, 1)), n = 0, lastYear = null;
    while (mo.getTime() / 864e5 <= this.hi) {
      var dn = Math.round(mo.getTime() / 864e5), mon = mo.getUTCMonth() + 1, yr = mo.getUTCFullYear();
      if ((mon - 1) % step === 0) {
        svg("line", { x1: x(dn), x2: x(dn), y1: H - m.b, y2: H - m.b + 4, "class": "axis" }, s);
        var label = yr !== lastYear ? yr + "年" + mon + "月" : mon + "月";
        svg("text", { x: x(dn), y: H - m.b + 16, "text-anchor": "middle", "class": "tick-text" }, s).textContent = label;
        lastYear = yr; n++;
      }
      mo = new Date(Date.UTC(yr, mon, 1));
    }
    var rows2 = [[m.t - 54, m.t - 42, "变更", "mark", 0], [m.t - 36, m.t - 26, "roster", "mark2", 1]];
    rows2.forEach(function (r) {
      svg("text", { x: m.l - 6, y: r[1] - 1, "text-anchor": "end", "class": "row-label" }, s).textContent = r[2];
      self.entries.forEach(function (e) {
        if (e.r !== r[4]) return;
        svg("line", { x1: x(e.sd), x2: x(e.sd), y1: r[0], y2: r[1], "class": r[3] }, s);
        if (e.ed > e.sd) svg("line", { x1: x(e.sd), x2: x(e.ed), y1: (r[0] + r[1]) / 2, y2: (r[0] + r[1]) / 2, "class": r[3] }, s);
      });
    });
    if (this.goals.size) {
      svg("text", { x: m.l - 6, y: m.t - 11, "text-anchor": "end", "class": "row-label" }, s).textContent = "goal";
      this.goals.forEach(function (d) { svg("circle", { cx: x(d), cy: m.t - 14, r: 2.5, "class": "goal" }, s); });
    }
    var range = this.table && this.table.dateFilter ? this.table.dateFilter() : null;
    if (range && (range.from || range.to)) {
      var r0 = range.from ? dayNum(range.from) : this.lo, r1 = range.to ? dayNum(range.to) : this.hi, pad = Math.max(3, bw);
      if (r0 !== null && r1 !== null && r1 >= r0) {
        svg("rect", { x: x(r0) - pad, y: m.t, width: x(r1) - x(r0) + 2 * pad, height: H - m.t - m.b, "class": "selected" }, s);
      }
    }
    byDay.forEach(function (c, d) {
      var x0 = x(d) - bw / 2;
      if (c.a) svg("rect", { x: x0, y: y(c.a), width: bw, height: y(0) - y(c.a), "class": "bar-a" }, s);
      if (c.u) svg("rect", { x: x0, y: y(c.a + c.u), width: bw, height: y(c.a) - y(c.a + c.u), "class": "bar-u" }, s);
    });
    this.guide = svg("line", { x1: 0, x2: 0, y1: 4, y2: H - m.b, "class": "guide", visibility: "hidden" }, s);
    this.wrap.appendChild(this.tip);
    var pct = total ? Math.round(100 * nA / total) : 0;
    this.summary.textContent = "按表格当前筛选（日期除外）：" + nf.format(total) + " 个变点，分布在 " + nf.format(byDay.size) +
      " 个运行日；对齐 " + nf.format(nA) + "（" + pct + "%），未对齐 " + nf.format(total - nA) + "。" +
      (range && (range.from || range.to) ? " 表格日期筛选 " + (range.from || "…") + " 至 " + (range.to || "…") + "，图中以浅色带标出。" : "");
  };
  CpChart.prototype.snap = function (px) {
    if (!this.byDay || px < this.geom.left - 8 || px > this.geom.right + 8) return null;
    var d = Math.round(this.lo + (px - this.geom.left) / this.ppd), R = Math.max(1, Math.ceil(6 / this.ppd));
    var self = this, has = function (dd) {
      return self.byDay.has(dd) || self.goals.has(dd) || self.entries.some(function (e) { return e.sd === dd; });
    };
    for (var k = 0; k <= R; k++) {
      if (has(d - k)) return d - k;
      if (has(d + k)) return d + k;
    }
    return null;
  };
  CpChart.prototype.hover = function (d, px, py) {
    this.cur = d;
    if (d === null || d === undefined) { this.tip.hidden = true; this.guide.setAttribute("visibility", "hidden"); return; }
    var x = this.x(d);
    this.guide.setAttribute("x1", x); this.guide.setAttribute("x2", x); this.guide.setAttribute("visibility", "visible");
    var c = this.byDay.get(d) || { a: 0, u: 0 }, tip = this.tip, date = dayStr(d);
    tip.textContent = "";
    var head = el("div", "tt-date", date + "（周" + WEEK[new Date(d * 864e5).getUTCDay()] + "）" +
      (this.runOf[d] !== undefined ? " · run day " + this.runOf[d] : ""));
    tip.appendChild(head);
    tip.appendChild(el("div", "tt-total", nf.format(c.a + c.u) + " 个变点"));
    [["对齐", c.a, "var(--c-aligned)"], ["未对齐", c.u, "var(--c-unaligned)"]].forEach(function (r) {
      var row = el("div", "tt-row"), key = el("i", "key");
      key.style.background = r[2];
      row.appendChild(key); row.appendChild(el("b", null, nf.format(r[1]))); row.appendChild(el("span", null, r[0]));
      tip.appendChild(row);
    });
    var es = this.entries.filter(function (e) { return e.sd <= d && d <= e.ed; });
    if (es.length || this.goals.has(d)) {
      var box = el("div", "tt-entries");
      if (this.goals.has(d)) box.appendChild(el("div", null, "village goal 切换"));
      es.slice(0, 6).forEach(function (e) {
        box.appendChild(el("div", null, e.id + (e.c ? "（" + e.c + "）" : "") + (e.ed > e.sd ? " " + e.s + " 至 " + e.e : "")));
      });
      if (es.length > 6) box.appendChild(el("div", null, "另有 " + (es.length - 6) + " 条"));
      tip.appendChild(box);
    }
    if (this.table && this.table.dateFilter && this.table.dateFilter()) tip.appendChild(el("div", "tt-date", "点击把表格筛到当天"));
    tip.hidden = false;
    var W = this.wrap.clientWidth, tw = tip.offsetWidth, left = (px === undefined ? x : px) + 14;
    if (left + tw > W) left = Math.max(0, (px === undefined ? x : px) - tw - 14);
    tip.style.left = left + "px";
    tip.style.top = Math.max(0, (py === undefined ? this.geom.top : py) - 10) + "px";
  };
  CpChart.prototype.pick = function (d) {
    if (!this.table || !this.table.setDateRange) return;
    var f = this.table.dateFilter(), s = dayStr(d);
    if (f && f.from === s && f.to === s) this.table.setDateRange("", "");
    else this.table.setDateRange(s, s);
  };

  /* ---------- panels and tabs ---------- */
  function initPanel(panel) {
    if (!panel || panel.getAttribute("data-ready")) return;
    panel.setAttribute("data-ready", "1");
    $$(".tbl", panel).forEach(function (n) {
      try { WIDGETS[n.id] = new TableWidget(n); } catch (e) { n.textContent = "表格渲染失败：" + e.message; console.error(e); }
    });
    $$(".cpchart", panel).forEach(function (n) {
      try { WIDGETS[n.id] = new CpChart(n, panel); } catch (e) { n.textContent = "图表渲染失败：" + e.message; console.error(e); }
    });
    $$("table.md-table", panel).forEach(makeSortable);
  }
  function show(token) {
    if (TABS.indexOf(token) < 0) token = "overview";
    document.documentElement.setAttribute("data-tab", token);
    $$(".tab").forEach(function (a) {
      var on = a.getAttribute("data-tab") === token;
      a.setAttribute("aria-selected", on ? "true" : "false");
      a.tabIndex = on ? 0 : -1;
      if (on && a.scrollIntoView && a.parentNode.scrollWidth > a.parentNode.clientWidth) {
        a.parentNode.scrollLeft = a.offsetLeft - a.parentNode.clientWidth / 2 + a.offsetWidth / 2;
      }
    });
    initPanel(document.getElementById("tab-" + token));
  }
  window.addEventListener("hashchange", function () { show(location.hash.slice(1)); window.scrollTo(0, 0); });
  document.querySelector(".tabs").addEventListener("keydown", function (e) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    var cur = TABS.indexOf(document.documentElement.getAttribute("data-tab"));
    var next = TABS[(cur + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length];
    location.hash = next;
    document.getElementById("tabbtn-" + next).focus();
  });

  /* ---------- QA reports ---------- */
  function showQA(stem) {
    var found = false;
    $$(".qa-report").forEach(function (a) { var on = a.getAttribute("data-qa-report") === stem; a.hidden = !on; found = found || on; });
    if (!found) return;
    $$(".qa-item").forEach(function (b) {
      var on = b.getAttribute("data-qa") === stem;
      b.classList.toggle("active", on);
      if (on) b.setAttribute("aria-current", "true"); else b.removeAttribute("aria-current");
    });
    var sel = document.querySelector(".qa-select");
    if (sel) sel.value = stem;
    initPanel(document.getElementById("tab-qa"));
  }
  document.addEventListener("click", function (e) {
    var t = e.target.closest ? e.target.closest("[data-qa], [data-scroll]") : null;
    if (!t) return;
    if (t.hasAttribute("data-scroll")) {
      var h = document.getElementById(t.getAttribute("data-scroll"));
      if (h) h.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    e.preventDefault();
    showQA(t.getAttribute("data-qa"));
    if (location.hash !== "#qa") location.hash = "qa";
    window.scrollTo(0, 0);
  });
  var qaSel = document.querySelector(".qa-select");
  if (qaSel) qaSel.addEventListener("change", function () { showQA(qaSel.value); });
  var firstQA = document.querySelector(".qa-report");
  if (firstQA) showQA(firstQA.getAttribute("data-qa-report"));

  /* ---------- figures: lightbox ---------- */
  var box = document.getElementById("lightbox"), boxImg = box.querySelector("img");
  document.addEventListener("click", function (e) {
    var img = e.target.closest ? e.target.closest("img.zoomable") : null;
    if (img) { boxImg.src = img.src; boxImg.alt = img.alt; box.hidden = false; return; }
    if (!box.hidden && box.contains(e.target)) { box.hidden = true; boxImg.removeAttribute("src"); }
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !box.hidden) { box.hidden = true; boxImg.removeAttribute("src"); } });

  /* ---------- theme ---------- */
  var themeBtn = document.getElementById("theme-btn"), NAMES = { auto: "自动", light: "浅色", dark: "深色" };
  var mode = document.documentElement.getAttribute("data-theme") || "auto";
  var paintTheme = function () {
    if (mode === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", mode);
    themeBtn.textContent = "主题：" + NAMES[mode];
  };
  themeBtn.addEventListener("click", function () {
    mode = mode === "auto" ? "light" : mode === "light" ? "dark" : "auto";
    try { if (mode === "auto") localStorage.removeItem("avsd-theme"); else localStorage.setItem("avsd-theme", mode); } catch (e) { /* storage unavailable */ }
    paintTheme();
  });
  paintTheme();

  show(location.hash.slice(1));
})();
