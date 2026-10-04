"""Aggregate tables for the HTML report: typed columns, a privacy filter and compact JSON.

Tables are read from outputs/tables/*.csv (or from markdown pipe tables) and embedded
column-major. String columns with many repeats are dictionary-encoded, so a 4 MB CSV
stays a few MB of JSON. Columns whose name looks like free text are dropped as a
safeguard, even though outputs/ is meant to hold aggregates only.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_ROWS = 20_000            # rows embedded per table
MAX_JSON_BYTES = 4_000_000   # encoded size budget per table

# A column is dropped when one of its name tokens contains one of these stems.
_FORBIDDEN = re.compile(r"text|content|heading|summar|evidence|mail")
_TOKEN_SPLIT = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]+|(?<=[a-z])(?=[A-Z])")
_INT = re.compile(r"[+-]?(0|[1-9]\d*)$")  # no leading zeros: "007" stays a string
_FLOAT = re.compile(r"[+-]?((0|[1-9]\d*)(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
_NONFINITE = {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}$")
_BOOL = {"true": True, "false": False}


def is_forbidden(name: str) -> bool:
    """True for column names like text, content, heading, summary, evidence or email."""
    tokens = [t.lower() for t in _TOKEN_SPLIT.split(name.strip("`*_ ")) if t]
    return any(_FORBIDDEN.search(t) and not t.startswith("context") for t in tokens)


@dataclass
class Table:
    name: str                       # file name, shown in captions and used for CSV export
    columns: list[str]
    types: list[str]                # int | float | bool | date | str
    data: list[list]                # column-major values
    n_total: int                    # rows in the source
    hidden: list[str] = field(default_factory=list)
    truncated: bool = False

    @property
    def n_rows(self) -> int:
        return len(self.data[0]) if self.data else 0


def _column_type(values: list[str | None]) -> str:
    present = [v for v in values if v is not None]
    if not present:
        return "str"
    if all(_INT.match(v) for v in present) and all(abs(int(v)) < 2**53 for v in present):
        return "int"
    if all(_FLOAT.match(v) or v.lower() in _NONFINITE for v in present):
        return "float"
    if all(v.lower() in _BOOL for v in present):
        return "bool"
    if all(_DATE.match(v) for v in present):
        return "date"
    return "str"


def _convert(values: list[str | None], typ: str) -> list:
    if typ == "int":
        return [None if v is None else int(v) for v in values]
    if typ == "float":
        out = []
        for v in values:
            x = None if v is None else float(v)
            # JSON has no NaN or infinity: keep the source token as a string.
            out.append(v if x is not None and not math.isfinite(x) else x)
        return out
    if typ == "bool":
        return [None if v is None else _BOOL[v.lower()] for v in values]
    return values


def make_table(name: str, header: list[str], rows: list[list[str]], n_total: int | None = None) -> Table:
    """Build a Table from string rows; empty cells become None. Forbidden columns are dropped."""
    keep = [i for i, h in enumerate(header) if not is_forbidden(h)]
    hidden = [h.strip() for h in header if is_forbidden(h)]
    columns, types, data = [], [], []
    for i in keep:
        raw = [(r[i] if i < len(r) else "").strip() or None for r in rows]
        typ = _column_type(raw)
        columns.append(header[i].strip())
        types.append(typ)
        data.append(_convert(raw, typ))
    n = len(rows) if n_total is None else n_total
    return Table(name, columns, types, data, n, hidden, truncated=n > len(rows))


def read_csv_table(path: Path, max_rows: int = MAX_ROWS) -> Table:
    """Read a CSV with the standard library (no type guessing surprises); keep the first max_rows."""
    csv.field_size_limit(2**31 - 1)  # long list-valued cells
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f)
        header = next(reader, None) or []
        rows: list[list[str]] = []
        n_total = 0
        for row in reader:
            if not row:
                continue
            n_total += 1
            if len(rows) < max_rows:
                rows.append(row)
    return make_table(path.name, header, rows, n_total)


def _encode_column(values: list, typ: str) -> list | dict:
    if typ in ("str", "date") and len(values) > 40:
        index: dict = {}
        codes = [index.setdefault(v, len(index)) for v in values]
        if len(index) <= len(values) // 2:
            return {"d": list(index), "i": codes}
    return values


def encode_table(table: Table, budget: int = MAX_JSON_BYTES) -> str:
    """Column-major JSON; rows are cut (with a flag) when the encoding exceeds the budget."""
    n = table.n_rows
    while True:
        payload = {
            "name": table.name,
            "columns": [{"n": c, "t": t} for c, t in zip(table.columns, table.types, strict=True)],
            "data": [_encode_column(col[:n], t) for col, t in zip(table.data, table.types, strict=True)],
            "n": n,
            "total": table.n_total,
            "hidden": table.hidden,
            "truncated": table.truncated or n < table.n_rows,
        }
        text = json_script(payload)
        if len(text.encode()) <= budget or n <= 100:
            return text
        n = max(100, int(n * budget / len(text.encode()) * 0.9))


def json_script(obj: object) -> str:
    """JSON that is safe inside <script type="application/json">."""
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return text.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def auto_filters(table: Table, limit: int = 4) -> list[dict]:
    """Dropdown filters for low-cardinality string and boolean columns of a generic table."""
    out = []
    for name, typ, col in zip(table.columns, table.types, table.data, strict=True):
        if typ not in ("str", "bool") or table.n_rows < 10:
            continue
        distinct = {v for v in col if v is not None}
        if 2 <= len(distinct) <= 15:
            out.append({"type": "select", "col": name})
        if len(out) == limit:
            break
    return out
