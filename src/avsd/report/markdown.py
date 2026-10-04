"""A small markdown converter for the QA reports and PROGRESS.md.

Supported subset: ATX headings, paragraphs, bullet and numbered lists, pipe tables
(rows after a blank line continue the previous table when the width matches), inline
code, bold, bare URLs, fenced code, `<details><summary>` lines and horizontal rules.
Everything else is escaped. Table columns named like free text are dropped
(see `tables.is_forbidden`).
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from avsd.report.tables import is_forbidden

_HEADING = re.compile(r"(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"(\s*)[-*+]\s+(.*)$")
_ORDERED = re.compile(r"(\s*)\d+[.)]\s+(.*)$")
_SEPARATOR = re.compile(r"\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_DETAILS_OPEN = re.compile(r"\s*<details>\s*(?:<summary>(.*?)</summary>)?\s*$", re.IGNORECASE)
_DETAILS_CLOSE = re.compile(r"\s*</details>\s*$", re.IGNORECASE)
_HR = re.compile(r"\s*(-{3,}|\*{3,}|_{3,})\s*$")
_FENCE = re.compile(r"\s*(```|~~~)")
_URL = re.compile(r"https?://[^\s<>\"'`]+[^\s<>\"'`.,;:!?)\]]")
_BOLD = re.compile(r"\*\*(.+?)\*\*")


@dataclass
class MdTable:
    header: list[str]
    rows: list[list[str]]
    align: list[str] = field(default_factory=list)


@dataclass
class Block:
    kind: str                  # heading | para | ul | ol | table | code | details | /details | hr
    text: str = ""
    level: int = 0
    items: list[str] = field(default_factory=list)
    table: MdTable | None = None


def split_row(line: str) -> list[str]:
    """Cells of a pipe-table row; `\\|` is a literal pipe."""
    s = line.strip().removeprefix("|")
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


def _align(sep: str) -> list[str]:
    out = []
    for c in split_row(sep):
        c = c.strip()
        out.append("center" if c.startswith(":") and c.endswith(":") else "right" if c.endswith(":") else "")
    return out


def _is_table_start(lines: list[str], i: int) -> bool:
    return (lines[i].lstrip().startswith("|") and i + 1 < len(lines)
            and bool(_SEPARATOR.match(lines[i + 1])) and "-" in lines[i + 1])


def parse_blocks(text: str) -> list[Block]:
    lines = text.replace("\r\n", "\n").split("\n")
    blocks: list[Block] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if m := _FENCE.match(line):
            fence, body = m.group(1), []
            i += 1
            while i < n and not lines[i].strip().startswith(fence):
                body.append(lines[i])
                i += 1
            blocks.append(Block("code", "\n".join(body)))
            i += 1
        elif m := _HEADING.match(line):
            blocks.append(Block("heading", m.group(2), level=len(m.group(1))))
            i += 1
        elif m := _DETAILS_OPEN.match(line):
            blocks.append(Block("details", m.group(1) or "Details"))
            i += 1
        elif _DETAILS_CLOSE.match(line):
            blocks.append(Block("/details"))
            i += 1
        elif _is_table_start(lines, i):
            table = MdTable(split_row(line), [], _align(lines[i + 1]))
            i += 2
            while i < n and lines[i].lstrip().startswith("|"):
                table.rows.append(split_row(lines[i]))
                i += 1
            blocks.append(Block("table", table=table))
        elif (line.lstrip().startswith("|") and blocks and blocks[-1].kind == "table"
              and len(split_row(line)) == len(blocks[-1].table.header)):
            # A row after blank lines continues the previous table (PROGRESS.md work log).
            while i < n and lines[i].lstrip().startswith("|"):
                blocks[-1].table.rows.append(split_row(lines[i]))
                i += 1
        elif _HR.match(line):
            blocks.append(Block("hr"))
            i += 1
        elif (m := _BULLET.match(line)) or (m := _ORDERED.match(line)):
            kind = "ul" if _BULLET.match(line) else "ol"
            pattern = _BULLET if kind == "ul" else _ORDERED
            items = [m.group(2)]
            i += 1
            while i < n and lines[i].strip():
                if mm := pattern.match(lines[i]):
                    items.append(mm.group(2))
                elif lines[i].startswith((" ", "\t")) and not _is_block_start(lines, i):
                    items[-1] += " " + lines[i].strip()
                else:
                    break
                i += 1
            blocks.append(Block(kind, items=items))
        else:
            para = [line.strip()]
            i += 1
            while i < n and lines[i].strip() and not _is_block_start(lines, i):
                para.append(lines[i].strip())
                i += 1
            blocks.append(Block("para", " ".join(para)))
    return blocks


def _is_block_start(lines: list[str], i: int) -> bool:
    line = lines[i]
    return bool(_HEADING.match(line) or _BULLET.match(line) or _ORDERED.match(line)
                or _FENCE.match(line) or _DETAILS_OPEN.match(line) or _DETAILS_CLOSE.match(line)
                or _HR.match(line) or line.lstrip().startswith("|"))


def inline(text: str) -> str:
    """Escape, then render `code`, **bold** and bare URLs."""
    out = []
    for k, part in enumerate(re.split(r"(`[^`]+`)", text)):
        if k % 2:
            out.append(f"<code>{html.escape(part[1:-1])}</code>")
            continue
        s = html.escape(part, quote=False)
        s = _BOLD.sub(r"<strong>\1</strong>", s)
        s = _URL.sub(lambda m: f'<a href="{m.group(0)}" target="_blank" rel="noopener noreferrer">'
                     f"{m.group(0)}</a>", s)
        out.append(s)
    return "".join(out)


def plain(text: str) -> str:
    """Cell text without markdown markers (for headers and filters)."""
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text).replace("`", "").strip()


def visible_table(t: MdTable) -> tuple[MdTable, list[str]]:
    """Drop forbidden columns; returns the reduced table and the hidden column names."""
    keep = [k for k, h in enumerate(t.header) if not is_forbidden(plain(h))]
    hidden = [plain(h) for k, h in enumerate(t.header) if k not in keep]

    def pick(row: list[str]) -> list[str]:
        return [row[k] if k < len(row) else "" for k in keep]

    align = [t.align[k] if k < len(t.align) else "" for k in keep]
    return MdTable(pick(t.header), [pick(r) for r in t.rows], align), hidden


def table_html(t: MdTable, cell: Callable[[str], str] = inline, css: str = "md-table",
               wrap: str = "scroll") -> str:
    """A static HTML table inside a scroll container; forbidden columns are dropped with a note."""
    t, hidden = visible_table(t)
    head = "".join(f'<th{_style(t.align, k)}>{inline(h)}</th>' for k, h in enumerate(t.header))
    body = "".join(
        "<tr>" + "".join(f"<td{_style(t.align, k)}>{cell(c)}</td>" for k, c in enumerate(r)) + "</tr>"
        for r in t.rows
    )
    note = (f'<p class="hidden-cols">Columns hidden by the privacy rules: {html.escape(", ".join(hidden))}</p>'
            if hidden else "")
    return (f'<div class="{wrap}"><table class="{css}"><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>{note}")


def _style(align: list[str], k: int) -> str:
    a = align[k] if k < len(align) else ""
    return f' class="a-{a}"' if a else ""


def to_html(text: str, heading_offset: int = 2, id_prefix: str = "") -> str:
    """Render markdown to HTML. `#` becomes h(1 + offset); headings get ids `<prefix>-h<k>`."""
    out, open_details, k = [], 0, 0
    for b in parse_blocks(text):
        if b.kind == "heading":
            level = min(6, b.level + heading_offset)
            hid = f' id="{id_prefix}-h{k}"' if id_prefix else ""
            out.append(f"<h{level}{hid}>{inline(b.text)}</h{level}>")
            k += 1
        elif b.kind == "para":
            out.append(f"<p>{inline(b.text)}</p>")
        elif b.kind in ("ul", "ol"):
            items = "".join(f"<li>{inline(x)}</li>" for x in b.items)
            out.append(f"<{b.kind}>{items}</{b.kind}>")
        elif b.kind == "table":
            out.append(table_html(b.table))
        elif b.kind == "code":
            out.append(f"<pre><code>{html.escape(b.text)}</code></pre>")
        elif b.kind == "details":
            out.append(f'<details class="md-details"><summary>{inline(b.text)}</summary>')
            open_details += 1
        elif b.kind == "/details" and open_details:
            out.append("</details>")
            open_details -= 1
        elif b.kind == "hr":
            out.append("<hr>")
    out += ["</details>"] * open_details
    return "\n".join(out)


def headings(text: str, max_level: int = 2) -> list[tuple[int, int, str]]:
    """(index, level, plain text) of headings up to max_level, matching the ids of `to_html`."""
    found = [b for b in parse_blocks(text) if b.kind == "heading"]
    return [(k, b.level, plain(b.text)) for k, b in enumerate(found) if b.level <= max_level]


def sections(text: str, prefixes: tuple[str, ...], level: int = 2) -> str:
    """The markdown of the level-`level` sections whose heading starts with one of `prefixes`."""
    out, keep = [], False
    for line in text.replace("\r\n", "\n").split("\n"):
        m = _HEADING.match(line)
        if m and len(m.group(1)) <= level:
            keep = len(m.group(1)) == level and plain(m.group(2)).startswith(prefixes)
        if keep:
            out.append(line)
    return "\n".join(out)


def tables(text: str) -> list[MdTable]:
    return [b.table for b in parse_blocks(text) if b.kind == "table"]


def title(text: str) -> str:
    """The first level-1 heading, or ''."""
    for b in parse_blocks(text):
        if b.kind == "heading" and b.level == 1:
            return plain(b.text)
    return ""
