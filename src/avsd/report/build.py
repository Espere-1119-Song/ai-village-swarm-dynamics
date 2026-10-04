"""`avsd report` (SPEC 10.1): one self-contained static page, reports/index.html.

Inputs are aggregates only: outputs/qa/*.md, outputs/tables/*.csv and *.md,
outputs/figures/*.png and PROGRESS.md. data/ is never read. CSS, JS, figures
(base64 PNG) and table data (JSON) are inlined, so the page opens from disk and
makes no network requests. Missing outputs show as "尚未产出" and new files are
picked up on the next build: known names get their captions, other names are
routed to a tab by pattern (registry.py). A file that cannot be read becomes an
error card instead of failing the build.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import base64
import fnmatch
import re
from collections import Counter
from collections.abc import Callable, Container
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from avsd.report import markdown as md
from avsd.report.progress import STATUS_CSS, STATUSES, Progress, parse_progress
from avsd.report.registry import MODULE_TABS, QA_ORDER, TAB_LABELS, Item, Tab
from avsd.report.tables import (
    MAX_JSON_BYTES,
    Table,
    auto_filters,
    encode_table,
    json_script,
    make_table,
    read_csv_table,
)

ASSETS = Path(__file__).with_name("assets")
SUBDIRS = ("qa", "tables", "figures")
try:
    ET = ZoneInfo("America/New_York")   # PROGRESS.md logs in US Eastern time
except ZoneInfoNotFoundError:            # no tz database: fall back to the machine's zone
    ET = datetime.now().astimezone().tzinfo
LOG_ROWS = 10                       # work-log rows shown before "显示其余"
TABLE_BUDGET = 8_000_000            # embedded table JSON, all tables together
IMAGE_BUDGET = 5_000_000            # embedded PNG bytes, all figures together
ROUTE_ORDER = ("data", "moduleC", "moduleA", "moduleB2", "moduleB1", "moduleD", "validation")
WEEKDAYS = "一二三四五六日"
SHOWN = {"figure": "图", "table": "交互表", "md_table": "交互表", "ingest": "交互表（摘要）",
         "md_sections": "文档摘录", "markdown": "文档", "cp_chart": "交互表", "error": "读取失败",
         "pdf": "PDF（与同名 PNG 相同，未嵌入）", "listed": "仅列出（未嵌入）"}


@dataclass
class OutFile:
    rel: str                 # e.g. "tables/changepoints.csv"
    path: Path
    size: int
    mtime: datetime
    tab: str = "overview"    # tab whose name patterns match (for files without a known item)
    shown: str = ""          # how the page shows it
    pages: list[str] = field(default_factory=list)
    why: str = ""            # reason a listed file is not embedded

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def ext(self) -> str:
        return self.path.suffix.lower().lstrip(".")

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8", errors="replace")

    def mark(self, page: str, shown: str) -> None:
        self.shown = self.shown or shown
        if page not in self.pages:
            self.pages.append(page)


def _fmt_time(t: datetime) -> str:
    return f"{t:%Y-%m-%d %H:%M}"


def _slug(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "-", s).strip("-")


def _unique_id(base: str, taken: Container[str]) -> str:
    out, k = base, 2
    while out in taken:
        out, k = f"{base}-{k}", k + 1
    return out


def _fmt_size(n: int) -> str:
    return f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{n / 1e3:.0f} KB" if n >= 1e3 else f"{n} B"


def _scan(outputs: Path) -> dict[str, OutFile]:
    files = {}
    for sub in SUBDIRS:
        d = outputs / sub
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.is_file() and not p.name.startswith("."):
                st = p.stat()
                rel = f"{sub}/{p.name}"
                files[rel] = OutFile(rel, p, st.st_size, datetime.fromtimestamp(st.st_mtime, ET))
    return files


def _route(name: str, tabs: dict[str, Tab]) -> str:
    """The tab whose pattern matches the file name first (pilot_ runs go with their module)."""
    base = name.removeprefix("pilot_")
    for token in ROUTE_ORDER:
        if any(fnmatch.fnmatch(base, p) for p in tabs[token].patterns):
            return token
    return "overview"


class _Page:
    """Collects embedded data blocks, widget configs and the size budgets while tabs are assembled."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}      # data id -> JSON text
        self.views: dict[str, dict] = {}    # widget id -> config
        self._ids: dict[str, str] = {}      # table key -> data id
        self._tables: dict[str, Table] = {}
        self.table_bytes = 0
        self.image_bytes = 0

    def table(self, key: str, load: Callable[[], Table]) -> tuple[str, Table]:
        """Embed a table once per key; returns its data id and the table."""
        if key not in self._ids:
            t = load()
            data_id = _unique_id("d-" + _slug(key), self.data)
            budget = min(MAX_JSON_BYTES, max(200_000, TABLE_BUDGET - self.table_bytes))
            self.data[data_id] = encode_table(t, budget)
            self.table_bytes += len(self.data[data_id].encode())
            self._tables[data_id] = t
            self._ids[key] = data_id
        data_id = self._ids[key]
        return data_id, self._tables[data_id]

    def widget(self, config: dict) -> str:
        wid = f"w{len(self.views) + 1}"
        self.views[wid] = config
        return wid

    def table_card(self, title: str, note: str, f: OutFile, key: str, load: Callable[[], Table],
                   view: dict | None) -> dict:
        data_id, t = self.table(key, load)
        view = dict(view or {})
        columns = set(t.columns)
        view["filters"] = [x for x in view.get("filters", auto_filters(t)) if x["col"] in columns]
        view["columns"] = [c for c in view.get("columns", []) if c in columns]
        view["fixed"] = [x for x in view.get("fixed", []) if x["col"] in columns]
        view["src"] = data_id
        meta = f"{t.n_total:,} 行 × {len(t.columns)} 列 · 更新于 {_fmt_time(f.mtime)}"
        return {"kind": "table", "title": title, "note": note, "src": f"outputs/{f.rel}", "meta": meta,
                "widget": self.widget(view), "data_id": data_id}

    def figure_card(self, title: str, note: str, f: OutFile) -> dict | None:
        """A base64 figure, or None when the image budget is used up."""
        if self.image_bytes + f.size > IMAGE_BUDGET:
            f.why = f"图片总量超过 {IMAGE_BUDGET // 1_000_000} MB，未嵌入"
            return None
        self.image_bytes += f.size
        b64 = base64.b64encode(f.path.read_bytes()).decode()
        return {"kind": "figure", "title": title, "note": note, "src": f"outputs/{f.rel}",
                "img": f"data:image/png;base64,{b64}", "meta": f"{_fmt_size(f.size)} · 更新于 {_fmt_time(f.mtime)}"}


def _html_card(title: str, note: str, f: OutFile, html: str) -> dict:
    return {"kind": "html", "title": title, "note": note, "src": f"outputs/{f.rel}",
            "meta": f"更新于 {_fmt_time(f.mtime)}", "html": Markup(html)}


def _error_card(title: str, f: OutFile, err: Exception) -> dict:
    return {"kind": "error", "title": title, "src": f"outputs/{f.rel}", "meta": f"更新于 {_fmt_time(f.mtime)}",
            "note": f"无法读取这个文件（{type(err).__name__}: {err}）。其余内容不受影响。"}


def _num(s: str | None) -> str:
    return s.replace(",", "").lstrip("+") if s else ""


def _ingest_table(text: str) -> Table | None:
    """Per-table counts from the bullets of outputs/qa/ingest.md."""
    header = ["table", "rows_read", "rows_written", "manifest_rows", "difference", "duplicate_ids",
              "unparseable_lines", "ts_parse_failures"]
    rows = []
    for part in re.split(r"^### ", text, flags=re.MULTILINE)[1:]:
        name, _, body = part.partition("\n")
        read = re.search(r"Rows read ([\d,]+), rows written ([\d,]+), unparseable lines ([\d,]+)", body)
        if not read:
            continue
        manifest = re.search(r"Manifest rows ([\d,]+), difference ([+-]?[\d,]+)", body)
        dup = re.search(r"Duplicate ids ([\d,]+)", body)
        fails = sum(int(_num(x)) for x in re.findall(r"parse failures ([\d,]+)", body))
        rows.append([name.strip(), _num(read[1]), _num(read[2]), _num(manifest and manifest[1]),
                     _num(manifest and manifest[2]), _num(dup and dup[1]), _num(read[3]), str(fails)])
    return make_table("ingest_summary.csv", header, rows) if rows else None


def _changelog_entries(f: OutFile | None) -> list[dict]:
    """CHANGELOG entries (id, first and last date, categories, roster flag) for the module C chart."""
    found = md.tables(f.read()) if f is not None else []
    if not found:
        return []
    header = [md.plain(h) for h in found[0].header]
    if "entry_id" not in header or "date" not in header:
        return []
    out = []
    for r in found[0].rows:
        row = {h: md.plain(r[k]) if k < len(r) else "" for k, h in enumerate(header)}
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", row["date"])
        if dates:
            cats = row.get("categories", "")
            out.append({"id": row["entry_id"], "s": dates[0], "e": dates[-1], "c": cats,
                        "r": int(row["entry_id"].startswith("roster") or "roster" in cats)})
    return out


def _known_card(it: Item, f: OutFile, tab: Tab, page: _Page, files: dict[str, OutFile]) -> dict | None:
    kind = it.resolved_kind
    if kind == "figure":
        return page.figure_card(it.title, it.note, f)
    if kind == "table":
        return page.table_card(it.title, it.note, f, it.path, lambda: read_csv_table(f.path), it.view)
    if kind == "md_table":
        found = md.tables(f.read())
        if not found:
            return _html_card(it.title, it.note, f, md.to_html(f.read(), 3))
        t = found[0]
        return page.table_card(it.title, it.note, f, it.path, lambda: make_table(
            f.path.stem + ".csv", [md.plain(h) for h in t.header], t.rows), it.view)
    if kind == "ingest":
        t = _ingest_table(f.read())
        return None if t is None else page.table_card(it.title, it.note, f, "ingest-summary", lambda: t,
                                                      {"filters": []})
    if kind == "md_sections":
        text = md.sections(f.read(), it.sections)
        return _html_card(it.title, it.note, f, md.to_html(text, 2)) if text.strip() else None
    if kind == "markdown":
        return _html_card(it.title, it.note, f, md.to_html(f.read(), 3))
    if kind == "cp_chart":
        data_id, _ = page.table(it.path, lambda: read_csv_table(f.path))
        review = files.get("tables/changelog_review.md")
        entries = _changelog_entries(review)
        if review is not None:
            review.mark(tab.token, "md_table")
        note = it.note if entries else it.note + "未找到 changelog_review.md 中的条目，图中不显示 CHANGELOG。"
        return {"kind": "chart", "title": it.title, "note": note,
                "src": "outputs/tables/changepoints.csv + outputs/tables/changelog_review.md",
                "meta": f"更新于 {_fmt_time(f.mtime)}",
                "widget": page.widget({"src": data_id, "entries": entries}), "data_id": data_id}
    return None


def _item_cards(tab: Tab, page: _Page, files: dict[str, OutFile]) -> tuple[list[dict], list[tuple[str, str]]]:
    """Cards for the tab's known items, and (path, description) of what is still missing."""
    cards, missing = [], []
    for it in tab.items:
        f = files.get(it.path)
        if f is None:
            if f"outputs/{it.path}" not in {m[0] for m in missing}:
                missing.append((f"outputs/{it.path}", it.title))
            continue
        try:
            card = _known_card(it, f, tab, page, files)
        except Exception as err:  # one unreadable file must not break the report
            card = _error_card(it.title, f, err)
        if card is not None:
            f.mark(tab.token, card["kind"] if card["kind"] == "error" else it.resolved_kind)
            cards.append(card)
    for pattern, desc in tab.expected:
        pats = [p.strip() for p in pattern.split(",")]
        if not any(fnmatch.fnmatch(rel, p) for rel in files for p in pats):
            missing.append((", ".join(f"outputs/{p}" for p in pats), desc))
    return cards, missing


def _other_cards(token: str, page: _Page, files: dict[str, OutFile]) -> tuple[list[dict], list[OutFile]]:
    """Files routed to a tab that no known item shows: rendered generically, or listed."""
    cards, listed = [], []
    pngs = {f.path.stem for f in files.values() if f.ext == "png"}
    for f in files.values():
        if f.tab != token or f.shown:
            continue
        card, shown = None, "listed"
        try:
            if f.ext == "csv":
                card, shown = page.table_card(f.name, "", f, f.rel, lambda f=f: read_csv_table(f.path), None), "table"
            elif f.ext == "png":
                card = page.figure_card(f.name, "", f)
                shown = "figure" if card else "listed"
            elif f.ext == "md":
                card, shown = _html_card(f.name, "", f, md.to_html(f.read(), 3)), "markdown"
            elif f.ext == "pdf" and f.path.stem in pngs:
                shown = "pdf"
            else:
                f.why = "parquet 表不嵌入（只读 CSV）" if f.ext == "parquet" else "该类型不嵌入"
        except Exception as err:
            card, shown = _error_card(f.name, f, err), "error"
        f.mark(token, shown)
        if card is not None:
            cards.append(card)
        elif shown == "listed":
            listed.append(f)
    return cards, listed


def _qa_reports(files: dict[str, OutFile]) -> list[dict]:
    qa = [f for f in files.values() if f.rel.startswith("qa/") and f.ext == "md"]
    order = {s: k for k, s in enumerate(QA_ORDER)}
    qa.sort(key=lambda f: (f.path.stem.startswith("pilot_"), order.get(f.path.stem, len(order)), f.name))
    out: list[dict] = []
    for f in qa:
        f.mark("qa", "markdown")
        text, stem = f.read(), f.path.stem
        prefix = _unique_id("qa-" + _slug(stem), {r["id"] for r in out})
        out.append({"stem": stem, "id": prefix, "title": md.title(text) or stem, "file": f.name,
                    "meta": f"{_fmt_size(f.size)} · 更新于 {_fmt_time(f.mtime)}",
                    "html": Markup(md.to_html(text, 2, prefix)),
                    "toc": [(f"{prefix}-h{k}", t) for k, lvl, t in md.headings(text) if lvl == 2]})
    return out


def _status_cell(text: str) -> str:
    s = md.plain(text)
    return f'<span class="pill {STATUS_CSS[s]}">{s}</span>' if s in STATUS_CSS else md.inline(text)


def _progress_html(progress: Progress) -> tuple[list[dict], dict | None]:
    sections = [{"title": t.title, "html": Markup(md.table_html(
        md.MdTable(t.header, t.rows), cell=_status_cell, css="md-table tasks", wrap="scroll flat"))}
        for t in progress.tasks]
    log = None
    if progress.log and progress.log.rows:
        rows, header = progress.log.rows[::-1], progress.log.header
        recent = md.table_html(md.MdTable(header, rows[:LOG_ROWS]), css="md-table log", wrap="scroll flat")
        rest = md.table_html(md.MdTable(header, rows[LOG_ROWS:]), css="md-table log", wrap="scroll flat")
        log = {"title": progress.log.title, "n": len(rows), "recent": Markup(recent),
               "rest": Markup(rest) if len(rows) > LOG_ROWS else None}
    return sections, log


def _file_index(files: dict[str, OutFile]) -> Table:
    rows = [[f.name, f.rel.split("/")[0], f.ext, f"{f.size / 1e3:.1f}", _fmt_time(f.mtime),
             "、".join(TAB_LABELS.get(p, p) for p in f.pages) or TAB_LABELS.get(f.tab, f.tab),
             f.why or SHOWN.get(f.shown, SHOWN["listed"])]
            for f in sorted(files.values(), key=lambda f: f.rel)]
    header = ["文件", "目录", "类型", "大小 (KB)", "更新时间", "所在页", "展示方式"]
    return make_table("outputs_index.csv", header, rows)


def _panel(tab: Tab, cards: list[dict], missing: list, page: _Page, files: dict[str, OutFile],
           qa_reports: list[dict], progress: Progress) -> dict:
    others, listed = _other_cards(tab.token, page, files)
    known = {it.path for it in tab.items}
    tab_files = [f for f in files.values() if f.tab == tab.token or f.rel in known]
    status = progress.rows_for(tab.token)
    counts = Counter(s for _, s in status)
    many = len(status) > 3   # overview cards then show counts plus the open tasks only
    return {
        "tab": tab, "cards": cards, "missing": missing, "others": others, "listed": listed,
        "qa": [r["stem"] for r in qa_reports if any(r["stem"].removeprefix("pilot_").startswith(q) for q in tab.qa)],
        "status": status,
        "status_counts": [(s, counts[s]) for s in STATUSES if counts[s]] if many else [],
        "status_brief": [r for r in status if r[1] != "Completed"][:3] if many else status,
        "n_known": len(known & files.keys()),
        "n_expected": len(known) + len(tab.expected),
        "n_files": len(tab_files),
        "latest": _fmt_time(max(f.mtime for f in tab_files)) if tab_files else "",
    }


def build_report(cfg: dict) -> Path:
    """Write reports/index.html from outputs/ and PROGRESS.md; returns the path."""
    outputs = Path(cfg["paths"]["outputs"])
    out_path = Path(cfg["paths"]["reports"]) / "index.html"
    progress_path = Path(cfg["paths"].get("progress", outputs.parent / "PROGRESS.md"))
    built = datetime.now(ET)
    files = _scan(outputs)
    tabs = {t.token: t for t in MODULE_TABS}
    for f in files.values():
        f.tab = "qa" if f.rel.startswith("qa/") else _route(f.name, tabs)
    page = _Page()
    qa_reports = _qa_reports(files)
    progress_text = progress_path.read_text(encoding="utf-8") if progress_path.is_file() else ""
    progress = parse_progress(progress_text)

    # Known items of every tab first, so that "other files" never repeats a known file.
    items = {tab.token: _item_cards(tab, page, files) for tab in MODULE_TABS}
    panels = [_panel(tab, *items[tab.token], page, files, qa_reports, progress) for tab in MODULE_TABS]
    overview_others, overview_listed = _other_cards("overview", page, files)
    index_id, _ = page.table("outputs-index", lambda: _file_index(files))
    index_filters = [{"type": "select", "col": c, "label": c} for c in ("目录", "类型", "所在页")]
    index_widget = page.widget({"src": index_id, "columns": [], "fixed": [], "filters": index_filters})
    task_sections, log = _progress_html(progress)
    latest = max(files.values(), key=lambda f: f.mtime) if files else None

    env = Environment(loader=FileSystemLoader(ASSETS), autoescape=True, trim_blocks=True, lstrip_blocks=True)
    html = env.get_template("page.html.j2").render(
        built=f"{built:%Y-%m-%d %H:%M} {built.tzname()}", built_iso=built.isoformat(timespec="seconds"),
        weekday=WEEKDAYS[built.weekday()], tab_labels=TAB_LABELS, status_css=STATUS_CSS,
        panels=panels, qa_reports=qa_reports, task_sections=task_sections, log=log,
        statuses=[(s, STATUS_CSS[s], n) for s, n in progress.status_counts().items()],
        has_progress=bool(progress_text),
        progress_mtime=_fmt_time(datetime.fromtimestamp(progress_path.stat().st_mtime, ET)) if progress_text else "",
        counts={k: sum(1 for f in files.values() if f.rel.startswith(k + "/")) for k in SUBDIRS},
        latest=latest and {"rel": latest.rel, "time": _fmt_time(latest.mtime)}, n_files=len(files),
        overview_others=overview_others, overview_listed=overview_listed, index_widget=index_widget,
        data_blocks=page.data, views=Markup(json_script(page.views)), fmt_size=_fmt_size,
        css=Markup((ASSETS / "report.css").read_text(encoding="utf-8")),
        js=Markup((ASSETS / "report.js").read_text(encoding="utf-8")),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
