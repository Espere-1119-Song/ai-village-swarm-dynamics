"""Task status tables and the work log from PROGRESS.md."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from avsd.report.markdown import parse_blocks, plain

STATUSES = ("Completed", "In progress", "Not started", "Blocked")
STATUS_CSS = {"Completed": "done", "In progress": "doing", "Not started": "todo", "Blocked": "blocked"}
_MODULE_TAB = {"A": "moduleA", "B": "moduleB1", "B2": "moduleB2", "C": "moduleC", "D": "moduleD"}


@dataclass
class TaskTable:
    title: str
    header: list[str]
    rows: list[list[str]]
    status_col: int | None = None
    tabs: list[str | None] = field(default_factory=list)   # report tab of each row


@dataclass
class Progress:
    tasks: list[TaskTable]
    log: TaskTable | None

    def status_counts(self) -> dict[str, int]:
        counts = dict.fromkeys(STATUSES, 0)
        for t in self.tasks:
            for r in t.rows:
                s = plain(r[t.status_col]) if t.status_col is not None and t.status_col < len(r) else ""
                if s in counts:
                    counts[s] += 1
        return counts

    def rows_for(self, tab: str) -> list[tuple[str, str]]:
        """(task, status) rows that belong to a report tab."""
        out = []
        for t in self.tasks:
            for r, rt in zip(t.rows, t.tabs, strict=True):
                if rt == tab and t.status_col is not None:
                    out.append((plain(r[0]), plain(r[t.status_col]) if t.status_col < len(r) else ""))
        return out


def _tab_of(section: str, task: str) -> str | None:
    """Map a task row to a report tab from its section heading and task name."""
    if "阶段 0" in section:
        return "data"
    if "外部验证" in section:
        return "validation"
    prefix = re.match(r"([A-E])(\d?)(?![\w])", task)
    letters: list[str] = []
    if m := re.match(r"\s*模块\s*([^（(]+)", section):
        letters = [x.strip() for x in re.split(r"[、,/，\s]+", m.group(1)) if x.strip()]
    if prefix and (not letters or any(x.startswith(prefix.group(1)) for x in letters)):
        return _MODULE_TAB.get(prefix.group(0)) or _MODULE_TAB.get(prefix.group(1))
    if len(letters) == 1:
        return _MODULE_TAB.get(letters[0]) or _MODULE_TAB.get(letters[0][:1])
    return None


def parse_progress(text: str) -> Progress:
    tasks: list[TaskTable] = []
    log: TaskTable | None = None
    section = ""
    for b in parse_blocks(text):
        if b.kind == "heading" and b.level <= 2:
            section = plain(b.text)
        elif b.kind == "table" and section:
            header = [plain(h) for h in b.table.header]
            status_col = next((k for k, h in enumerate(header) if h in ("状态", "Status")), None)
            table = TaskTable(section, header, b.table.rows, status_col)
            if section.startswith("工作日志"):
                log = log or table
            elif status_col is not None:
                table.tabs = [_tab_of(section, plain(r[0]) if r else "") for r in table.rows]
                tasks.append(table)
    return Progress(tasks, log)
