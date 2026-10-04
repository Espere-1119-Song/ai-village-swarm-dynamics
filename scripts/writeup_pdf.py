"""Typeset reports/writeup.md as a paper-style PDF with XeLaTeX.

    python scripts/writeup_pdf.py      # writes reports/writeup.pdf (build files in reports/build/)

Handles the Markdown subset the write-up uses: # to ### headings, paragraphs, pipe tables with a
**Table N.** caption after them, images with a **Figure N.** caption after them, bullet lists, the two
display equations, **bold**, `code` and URLs. Figures use the PDF version when it exists. Needs
XeLaTeX and the STIX Two fonts from TeX Live.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "reports" / "writeup.md"
BUILD = ROOT / "reports" / "build"
OUT = ROOT / "reports" / "writeup.pdf"
VENUE = r"AI Swarm Dynamics Hackathon, AI Village $\times$ Grove Research, October 2026"
REPO = "https://github.com/Espere-1119-Song/ai-village-swarm-dynamics"

EQUATIONS = {
    "λ_i(t) = μ_{i,b(t)} + Σ_j Σ_{t_l < t} n_ij g_{c(i,j)}(t − t_l),":
        r"\[ \lambda_i(t) = \mu_{i,b(t)} + \sum_j \sum_{t_l < t} n_{ij}\, g_{c(i,j)}(t - t_l), \]",
    "P(parent(i) = j) ∝ E_ij K_ij exp(γ S_ij),":
        r"\[ P\bigl(\mathrm{parent}(i) = j\bigr) \propto E_{ij}\, K_{ij}\, \exp(\gamma\, S_{ij}), \]",
}
MATH = {"n_ij + n_ji": r"$n_{ij} + n_{ji}$", "n_ij": r"$n_{ij}$", "n_ji": r"$n_{ji}$", "E_ij": r"$E_{ij}$",
        "K_ij": r"$K_{ij}$", "S_ij": r"$S_{ij}$", "L_B": r"$L_B$", "T_k": r"$T_k$", "g_c": r"$g_c$", "h_g": r"$h_g$"}

PREAMBLE = r"""\documentclass[11pt]{article}
\usepackage[textwidth=6.32in, top=1in, bottom=1in]{geometry}
\usepackage{fontspec}
\usepackage{unicode-math}
\setmainfont{STIXTwoText}[Extension=.otf, UprightFont=*-Regular, BoldFont=*-Bold, ItalicFont=*-Italic, BoldItalicFont=*-BoldItalic]
\setmathfont{STIXTwoMath-Regular.otf}
\usepackage{microtype}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{tabularx}
\usepackage{array}
\usepackage{enumitem}
\usepackage[font=small,labelfont=bf]{caption}
\usepackage{xcolor}
\definecolor{LinkBlue}{HTML}{1967D2}
\usepackage[colorlinks=true, linkcolor=LinkBlue, urlcolor=LinkBlue, citecolor=LinkBlue]{hyperref}
\usepackage{xurl}
\setlength{\parindent}{1.2em}
\setlength{\parskip}{0.25em}
\renewcommand{\arraystretch}{1.12}
\setlength{\tabcolsep}{5pt}
\newcolumntype{L}{>{\raggedright\arraybackslash}X}
\setlength{\emergencystretch}{2.5em}
\widowpenalty=10000
\clubpenalty=10000
\displaywidowpenalty=10000
"""


def esc(s: str) -> str:
    return (s.replace("\\", r"\textbackslash{}").replace("%", r"\%").replace("#", r"\#").replace("&", r"\&")
            .replace("_", r"\_").replace("$", r"\$").replace("{", r"\{").replace("}", r"\}"))


def inline(s: str) -> str:
    slots: list[str] = []

    def keep(tex: str) -> str:
        slots.append(tex)
        return f"\x00{len(slots) - 1}\x00"

    s = re.sub(r"\$[^$]+\$", lambda m: keep(m.group(0)), s)
    s = re.sub(r"\[([^\[\]\s]{1,20}), ([^\[\]\s]{1,20})\]", lambda m: keep("[" + esc(m.group(1)) + ",~" + esc(m.group(2)) + "]"), s)
    s = re.sub(r"\*\*(.+?)\*\*", lambda m: keep(r"\textbf{" + inline(m.group(1)) + "}"), s)
    s = re.sub(r"`([^`]+)`", lambda m: keep(r"\texttt{" + breakable(esc(m.group(1))) + "}"), s)
    s = re.sub(r"https?://[^\s<>\"]+[^\s<>\".,;:)\]]", lambda m: keep(r"\url{" + m.group(0).replace("%", r"\%").replace("#", r"\#") + "}"), s)
    s = s.replace("≈", "\x01")
    s = re.sub(r"(?<![\w/])(?:[\w.-]+/)+[\w.-]+\.\w+\b", lambda m: keep(r"\texttt{" + breakable(esc(m.group(0))) + "}"), s)
    s = re.sub(r"\b[0-9a-f]{20,}\b", lambda m: keep(r"\texttt{" + r"\allowbreak{}".join(m.group(0)[k:k + 10] for k in range(0, len(m.group(0)), 10)) + "}"), s)
    for k in sorted(MATH, key=len, reverse=True):
        s = re.sub(rf"(?<![\w]){re.escape(k)}(?![\w])", lambda m, k=k: keep(MATH[k]), s)
    s = re.sub(r"\b[a-z]+(?:_[a-z]+)+\b", lambda m: keep(r"\texttt{" + esc(m.group(0)) + "}"), s)
    s = re.sub(r'"([^"]+)"', lambda m: "``" + m.group(1) + "''", s)
    s = esc(s).replace("\x01", r"$\approx$").replace(" = ", "~=~")
    return re.sub(r"\x00(\d+)\x00", lambda m: slots[int(m.group(1))], s)


def breakable(tex: str) -> str:
    """Allow line breaks after dots, slashes, underscores and hyphens inside words in typewriter text."""
    return re.sub(r"(\.|/|(?<=\w)-(?=\w)|\\_)", lambda m: m.group(1) + r"\allowbreak{}", tex)


def table(block: str, caption: str) -> str:
    lines = [l.strip() for l in block.splitlines() if l.strip()]
    rows = [[c.strip() for c in l.strip("|").split("|")] for l in lines]
    header, sep, body = rows[0], rows[1], rows[2:]
    n = len(header)
    right = [c.endswith(":") for c in sep]
    widths = [max(len(r[j]) if j < len(r) else 0 for r in rows if r is not sep) for j in range(n)]
    long_text = max(widths) > 40
    spec = []
    for j in range(n):
        if right[j]:
            spec.append("r")
        elif long_text and widths[j] > 18:
            spec.append("L")
        else:
            spec.append("l")
    env = "tabularx" if "L" in spec else "tabular"
    head = r"\begin{tabularx}{\linewidth}{" + "".join(spec) + "}" if env == "tabularx" else r"\begin{tabular}{" + "".join(spec) + "}"
    out = [r"\begin{table}[htbp]", r"\centering", r"\small", r"\caption{" + inline(caption) + "}", head, r"\toprule",
           " & ".join(inline(c) for c in header) + r" \\", r"\midrule"]
    for r in body:
        r = r + [""] * (n - len(r))
        out.append(" & ".join(inline(c) for c in r[:n]) + r" \\")
    out += [r"\bottomrule", r"\end{" + env + "}", r"\end{table}"]
    tex = "\n".join(out)
    if env == "tabular" and sum(widths) > 80:
        tex = tex.replace(head, r"\resizebox{\linewidth}{!}{" + head).replace(r"\end{tabular}", r"\end{tabular}}")
    return tex


def figure(path: str, caption: str) -> str:
    p = (ROOT / "reports" / path).resolve()
    pdf = p.with_suffix(".pdf")
    use = pdf if pdf.exists() else p
    rel = Path("..") / use.relative_to(ROOT)
    return "\n".join([r"\begin{figure}[htbp]", r"\centering", r"\includegraphics[width=\linewidth]{" + str(rel) + "}",
                      r"\caption{" + inline(caption) + "}", r"\end{figure}"])


def convert(md: str) -> str:
    blocks = [b.strip("\n") for b in md.split("\n\n") if b.strip()]
    out, i, title, author = [], 0, "", ""
    while i < len(blocks):
        b = blocks[i]
        nxt = blocks[i + 1] if i + 1 < len(blocks) else ""
        if b.startswith("# "):
            title = b[2:].strip()
            out.append(r"\maketitle")
            if nxt and not nxt.startswith("#") and len(nxt) < 80:
                author = nxt.strip()
                i += 1
        elif b.startswith("## Appendix"):
            out.append(r"\appendix" + "\n" + r"\section{" + inline(re.sub(r"^Appendix\.?\s*", "", b[3:].strip())) + "}" + "\n"
                       + r"\renewcommand{\thetable}{A\arabic{table}}\setcounter{table}{0}")
        elif b.startswith("### References"):
            out.append(r"\subsection*{References}")
        elif b.startswith("### "):
            out.append(r"\subsection{" + inline(re.sub(r"^\d+\.\d+\s+", "", b[4:].strip())) + "}")
        elif b.startswith("## "):
            out.append(r"\section{" + inline(re.sub(r"^\d+\.\s+", "", b[3:].strip())) + "}")
        elif b.strip() in EQUATIONS:
            out[-1] = out[-1] + "\n" + EQUATIONS[b.strip()] + "\n" + inline(nxt)
            i += 1
        elif b.startswith("!["):
            m = re.match(r"!\[[^\]]*\]\(([^)]+)\)", b)
            cap = re.sub(r"^\*\*Figure \d+\.\*\*\s*", "", nxt) if nxt.startswith("**Figure") else ""
            out.append(figure(m.group(1), cap))
            i += 1 if cap else 0
        elif b.startswith("|"):
            cap = re.sub(r"^\*\*Table [A-Z]?\d+\.\*\*\s*", "", nxt) if nxt.startswith("**Table") else ""
            out.append(table(b, cap))
            i += 1 if cap else 0
        elif b.startswith("- "):
            items = [l[2:].strip() for l in b.splitlines() if l.startswith("- ")]
            env = r"\begin{itemize}[leftmargin=1.5em, itemsep=1pt, parsep=0pt, label={}]" if out and out[-1].startswith(r"\subsection*{References}") \
                else r"\begin{itemize}[leftmargin=1.5em, itemsep=1pt]"
            body = "\n".join(r"\item " + inline(x) for x in items)
            if "label={}" in env:
                body = r"\small" + "\n" + body
            out.append(env + "\n" + body + "\n" + r"\end{itemize}")
        else:
            out.append(inline(b))
        i += 1
    head = PREAMBLE + r"\title{" + inline(title) + "}\n" + r"\author{" + inline(author).replace(" and ", r"\qquad ") + r"\\[2pt] \small " + VENUE + r"\\ \small Code and data products: \url{" + REPO + "}}\n" + r"\date{}" + "\n"
    return head + r"\begin{document}" + "\n\n" + "\n\n".join(out) + "\n\n" + r"\end{document}" + "\n"


def main() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    tex = BUILD / "writeup.tex"
    tex.write_text(convert(SRC.read_text(encoding="utf-8")), encoding="utf-8")
    for _ in range(2):
        r = subprocess.run(["xelatex", "-interaction=nonstopmode", "-halt-on-error", "-output-directory", str(BUILD), str(tex)],
                           cwd=ROOT / "reports", capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout[-3000:])
            raise SystemExit("xelatex failed; see reports/build/writeup.log")
    shutil.copy(BUILD / "writeup.pdf", OUT)
    print(f"{OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
