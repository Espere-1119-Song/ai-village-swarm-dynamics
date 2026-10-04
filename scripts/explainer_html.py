"""Self-contained HTML of the Chinese explainer, with the figures embedded.

    python scripts/explainer_html.py     # reports/findings_zh.md -> reports/findings_zh.html

Handles the subset the explainer uses: # and ## headings, paragraphs, - and 1. lists, **bold**,
`code` and ![alt](path) images on their own line.
"""

from __future__ import annotations

import base64
import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "reports" / "findings_zh.md"
OUT = ROOT / "reports" / "findings_zh.html"

CSS = """
:root { --ink: #202124; --blue: #1967D2; --red: #C5221F; --muted: #5F6368; --line: #DADCE0; --bg: #FFFFFF; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font-family: "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
  font-size: 17px; line-height: 1.8; }
main { max-width: 860px; margin: 0 auto; padding: 32px 20px 64px; }
h1 { font-size: 30px; line-height: 1.35; margin: 8px 0 18px; }
h2 { font-size: 23px; margin: 44px 0 12px; padding-top: 18px; border-top: 1px solid var(--line); }
p { margin: 10px 0; }
strong { color: var(--red); font-weight: 600; }
code { font-family: Menlo, Consolas, monospace; font-size: 0.9em; background: #F1F3F4; padding: 1px 5px; border-radius: 4px; }
ul, ol { padding-left: 1.4em; }
li { margin: 4px 0; }
figure { margin: 18px 0 22px; }
figure img { width: 100%; height: auto; display: block; border: 1px solid var(--line); border-radius: 6px; }
nav { font-size: 15px; color: var(--muted); margin-bottom: 8px; }
nav a { color: var(--blue); margin-right: 14px; text-decoration: none; border-bottom: 1px solid var(--line); }
"""


def inline(text: str) -> str:
    t = html.escape(text)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)


def image(alt: str, path: str) -> str:
    data = base64.b64encode((SRC.parent / path).read_bytes()).decode()
    return f'<figure><img alt="{html.escape(alt)}" src="data:image/png;base64,{data}"></figure>'


def convert(md: str) -> tuple[str, str, list[tuple[str, str]]]:
    out, para, lst, title, toc = [], [], None, "", []

    def flush():
        nonlocal para, lst
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para = []
        if lst:
            tag, items = lst
            out.append(f"<{tag}>" + "".join(f"<li>{inline(i)}</li>" for i in items) + f"</{tag}>")
            lst = None

    for line in md.splitlines():
        s = line.strip()
        m_img = re.fullmatch(r"!\[(.*?)\]\((.+?)\)", s)
        m_ul = re.match(r"-\s+(.*)", s)
        m_ol = re.match(r"\d+\.\s+(.*)", s)
        if not s:
            flush()
        elif s.startswith("## "):
            flush()
            k = len(toc) + 1
            toc.append((f"s{k}", s[3:]))
            out.append(f'<h2 id="s{k}">{inline(s[3:])}</h2>')
        elif s.startswith("# "):
            flush()
            title = s[2:]
            out.append(f"<h1>{inline(title)}</h1>")
        elif m_img:
            flush()
            out.append(image(m_img.group(1), m_img.group(2)))
        elif m_ul or m_ol:
            if para:
                flush()
            tag = "ul" if m_ul else "ol"
            if lst and lst[0] != tag:
                flush()
            lst = lst or (tag, [])
            lst[1].append((m_ul or m_ol).group(1))
        else:
            para.append(s)
    flush()
    return title, "\n".join(out), toc


def main() -> None:
    title, body, toc = convert(SRC.read_text(encoding="utf-8"))
    nav = "<nav>" + "".join(f'<a href="#{i}">{html.escape(t)}</a>' for i, t in toc) + "</nav>"
    head, rest = body.split("\n", 1)
    page = (f'<!doctype html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{html.escape(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n<main>\n"
            f"{head}\n{nav}\n{rest}\n</main>\n</body>\n</html>\n")
    OUT.write_text(page, encoding="utf-8")
    print(f"{OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
