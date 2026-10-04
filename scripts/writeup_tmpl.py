"""Typeset reports/writeup.md in the arxivtmpl template (reports/paper/) and copy the PDF to reports/writeup.pdf.

The body comes from writeup_pdf.convert; the summary becomes the abstract, Figure 1 the teaser and the opening
paragraph the introduction. Needs pdflatex and latexmk.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import writeup_pdf as wp  # noqa: E402

PAPER = ROOT / "reports" / "paper"
OUT = ROOT / "reports" / "writeup.pdf"
UNICODE = {"−": r"\ensuremath{-}", "×": r"\ensuremath{\times}", "ρ": r"\ensuremath{\rho}", "λ": r"\ensuremath{\lambda}",
           "μ": r"\ensuremath{\mu}", "γ": r"\ensuremath{\gamma}", "Σ": r"\ensuremath{\Sigma}", "∝": r"\ensuremath{\propto}",
           "≤": r"\ensuremath{\leq}", "≥": r"\ensuremath{\geq}", "′": r"\ensuremath{'}", "→": r"\ensuremath{\rightarrow}",
           "²": r"\ensuremath{^2}", "≈": r"\ensuremath{\approx}", "∈": r"\ensuremath{\in}", "β": r"\ensuremath{\beta}",
           "α": r"\ensuremath{\alpha}", "₁": r"\ensuremath{_1}", "σ": r"\ensuremath{\sigma}", "Δ": r"\ensuremath{\Delta}", "δ": r"\ensuremath{\delta}"}
NATIVE = set("–’‘“”·éèáíóúüöäçñ")


def main() -> None:
    doc = wp.convert(wp.SRC.read_text(encoding="utf-8"))
    body = doc.split(r"\begin{document}", 1)[1].rsplit(r"\end{document}", 1)[0].strip()
    blocks = body.replace("../reports/figures/", "").split("\n\n")
    assert blocks[0] == r"\maketitle" and blocks[2].startswith(r"\begin{figure}") and blocks[3] == r"\section{Summary}", blocks[:4]
    intro, fig1, summary, rest = blocks[1], blocks[2], blocks[4], blocks[5:]
    graphic = re.search(r"\\includegraphics\[[^\]]*\]\{([^}]+)\}", fig1).group(1)
    caption = re.search(r"\\caption\{(.*)\}\s*\\end\{figure\}", fig1, re.S).group(1)
    rest = "\n\n".join(rest).replace(r"\section{Acknowledgements and citation}", r"\section*{Acknowledgments}")
    rest = rest.replace(r"\subsection*{References}", r"\section*{References}")
    text = intro + summary + caption + rest
    odd = sorted({c for c in text if ord(c) > 127} - NATIVE - set(UNICODE))
    if odd:
        raise SystemExit(f"characters without a mapping: {odd}")
    decl = "\n".join(rf"\DeclareUnicodeCharacter{{{ord(c):04X}}}{{{UNICODE[c]}}}" for c in sorted(UNICODE) if c in text)
    tex = "\n".join([
        r"\documentclass{arxivtmpl}", "", r"\input{commands}", r"\graphicspath{{../figures/}}", r"\newcolumntype{L}{>{\raggedright\arraybackslash}X}", decl, "",
        r"\title{Influence Between Agents in the AI Village}", "",
        r"\author[1]{Enxin Song}", r"\author[2]{Wenhao Chai}", r"\affil[1]{University of Pennsylvania}",
        r"\affil[2]{Princeton University}", "",
        r"\begin{document}", "", r"\maketitle", "", r"\thispagestyle{firstpagestyle}", "",
        r"\begin{abstract}", r"{\sffamily\fontseries{eb}\normalsize\selectfont Abstract}\par\vspace{0.15\baselineskip}",
        r"\small", summary, r"\end{abstract}", "",
        r"\teaserfigure{\includegraphics[width=\linewidth]{" + graphic + "}}{" + caption + "}", "",
        r"\clearpage", r"\section{Introduction}", "", intro, "",
        r"\setcounter{tocdepth}{2}", r"\begingroup", r"\hypersetup{linkcolor=black}", r"\tableofcontents", r"\endgroup",
        r"\clearpage", "", rest, "", r"\end{document}", ""])
    PAPER.mkdir(parents=True, exist_ok=True)
    (PAPER / "main.tex").write_text(tex, encoding="utf-8")
    r = subprocess.run(["latexmk", "-pdf", "-shell-escape", "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
                       cwd=PAPER, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-4000:])
        raise SystemExit("latexmk failed; see reports/paper/main.log")
    shutil.copy(PAPER / "main.pdf", OUT)
    print(f"{OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
