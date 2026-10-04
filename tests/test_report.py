import base64
import json
import re

import pytest
from typer.testing import CliRunner

from avsd.report import build
from avsd.report import markdown as md
from avsd.report.build import build_report
from avsd.report.progress import parse_progress
from avsd.report.tables import encode_table, is_forbidden, make_table, read_csv_table

TAB_LABELS = ["总览", "数据与事件表", "聊天激发", "记忆保留", "变点", "模拟与依赖图", "外部验证", "QA 报告"]
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)

PROGRESS = """# 进度

## 阶段 0（P0）

| 任务 | 状态 | 产出与验收 |
|---|---|---|
| 3.1 仓库结构 | Completed | 目录与 `pyproject.toml` |
| 4.1-8 QA 报告 | In progress | ingest 与 build_events |

## 模块 B1、C（P0）

| 任务 | 状态 | 产出与验收 |
|---|---|---|
| B1 memory 链 | Blocked | 等用户标注 |
| C 变点与 CHANGELOG 对齐 | Not started | |

## 工作日志（美东时间）

| 时间 | 步骤 | 结果 |
|---|---|---|
| 9/30 18:02 | 建仓库骨架 | 完成 |

| 9/30 18:04 | 读数据集文档 | 写入 schema_notes |
"""

QA_MD = """# QA: module C

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village

## 1. Inputs

- Run days: **389**.
- Labels use `<agent name>` and plain <b>tags</b>.

| method | changepoints | email |
|---|---:|---|
| pelt_l2 | 2314 | someone@example.com |

<details><summary>Series list</summary>

| series_id | n_cp |
|---|---|
| family:Anthropic:msg_count | 15 |

</details>

## 2. Alignment

1. First step.
2. Second step.
"""

CHANGELOG_MD = """| entry_id | date | tags | categories | flags | text |
|---|---|---|---|---|---|
| cl-2025-04-16-1 | 2025-04-16 | Memory | prompt, memory |  | SECRET-CELL-2 |
| roster-2025-04-16-join-o3 | 2025-04-16 | Roster | model, roster |  | Agent joined: o3 |
| cl-2025-04-24-1 | 2025-04-24 to 2025-04-25 | Prompt | prompt |  | Asked Gemini |
"""

DOC, UNID = "aligned with a documented event", "cause unidentified"
CHANGEPOINTS = "\n".join([
    "series_id,level,metric_label,method,run_day,date,magnitude,aligned,aligned_documented,cause,"
    "cause_documented,evidence_text,monitor_n_findings",
    "family:Anthropic:msg_count,family,Messages,pelt_l2,16,2025-04-21,-35.06548961962977,true,true,"
    f"aligned with CHANGELOG,{DOC},SECRET-CELL-1,",
    f"family:OpenAI:msg_len,family,Mean length,pelt_l2,26,2025-05-05,61.6,false,true,{UNID},{DOC},SECRET-CELL-1,12",
    f"agent:o3:msg_count,agent,Messages,pelt_rbf,87,2025-07-24,NaN,false,false,{UNID},{UNID},SECRET-CELL-1,",
]) + "\n"


def _data_blocks(html: str) -> dict[str, dict]:
    blocks = re.findall(r'<script type="application/json" id="(d-[^"]+)">(.*?)</script>', html, re.DOTALL)
    return {k: json.loads(v) for k, v in blocks}


def _columns(block: dict) -> list[str]:
    return [c["n"] for c in block["columns"]]


def _values(block: dict, name: str) -> list:
    col = block["data"][_columns(block).index(name)]
    return col if isinstance(col, list) else [col["d"][i] for i in col["i"]]


@pytest.fixture
def tree(tmp_path):
    out = tmp_path / "outputs"
    for sub in ("qa", "tables", "figures"):
        (out / sub).mkdir(parents=True)
    (out / "qa" / "changepoint.md").write_text(QA_MD, encoding="utf-8")
    (out / "qa" / "ingest.md").write_text(
        "# QA report: ingest\n\n### agents\n\n- Rows read 46, rows written 46, unparseable lines 0.\n"
        "- Manifest rows 46, difference +0.\n- Duplicate ids 0.\n", encoding="utf-8")
    (out / "tables" / "changepoints.csv").write_text(CHANGEPOINTS, encoding="utf-8")
    (out / "tables" / "changepoint_alignment.csv").write_text(
        "method,cp_set,series_set,entry_set,w,aligned,null1_p\n"
        "pelt_l2,all,all,all,3,1929,0.679\npelt_l2,all,all,monitor conflict (high),3,12,0.5\n", encoding="utf-8")
    (out / "tables" / "memory_hazard_v2.csv").write_text(
        "scope,stratum,g,h,h_lo,h_hi\nfamily,All standard,1,0.52,0.45,0.58\nfamily,OpenAI,1,0.63,0.55,0.68\n",
        encoding="utf-8")
    (out / "tables" / "mystery_stats.csv").write_text("kind,value,summary\na,1,SECRET-CELL-3\nb,2,x\n",
                                                      encoding="utf-8")
    (out / "tables" / "changelog_review.md").write_text(CHANGELOG_MD, encoding="utf-8")
    (out / "tables" / "changepoint_monitor_findings.parquet").write_bytes(b"PAR1 not embedded")
    (out / "figures" / "F5_changepoint_timeline.png").write_bytes(PNG)
    (out / "figures" / "F5_changepoint_timeline.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "PROGRESS.md").write_text(PROGRESS, encoding="utf-8")
    return tmp_path


def _cfg(root):
    return {"paths": {"outputs": root / "outputs", "reports": root / "reports"}}


def test_forbidden_column_names():
    for name in ("text", "text_head", "content_len", "heading_note", "summary", "Summaries", "evidence",
                 "email", "e-mail", "userEmail", "`text`", "摘要"):
        assert is_forbidden(name), name
    for name in ("context_len", "series_id", "n_units", "entries_within_w", "monitor_by_category"):
        assert not is_forbidden(name), name


def test_csv_types_privacy_and_encoding(tmp_path):
    p = tmp_path / "t.csv"
    rows = ["id,n,x,flag,date,code,content_len,label"]
    rows += [f"s{i},{i},{i / 3},{'true' if i % 2 else 'false'},2025-04-{i % 28 + 1:02d},007,{i},grp{i % 3}"
             for i in range(60)]
    rows.append("s60,60,NaN,,2025-05-01,007,1,grp0")
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    t = read_csv_table(p)
    assert t.columns == ["id", "n", "x", "flag", "date", "code", "label"]
    assert t.hidden == ["content_len"]
    assert dict(zip(t.columns, t.types, strict=True)) == {"id": "str", "n": "int", "x": "float", "flag": "bool",
                                             "date": "date", "code": "str", "label": "str"}
    payload = json.loads(encode_table(t))
    assert payload["n"] == payload["total"] == 61 and not payload["truncated"]
    assert _values(payload, "x")[-1] == "NaN"            # non-finite kept as its source token
    assert _values(payload, "label")[:3] == ["grp0", "grp1", "grp2"]
    assert isinstance(payload["data"][_columns(payload).index("label")], dict)  # dictionary-encoded
    assert _values(payload, "code")[0] == "007"


def test_row_cap_and_byte_budget(tmp_path):
    p = tmp_path / "big.csv"
    p.write_text("a,b\n" + "".join(f"{i},row{i}\n" for i in range(300)), encoding="utf-8")
    t = read_csv_table(p, max_rows=250)
    assert (t.n_rows, t.n_total, t.truncated) == (250, 300, True)
    payload = json.loads(encode_table(make_table("x.csv", ["a"], [[str(i)] for i in range(5000)]), budget=8000))
    assert payload["truncated"] and 100 <= payload["n"] < 5000 and payload["total"] == 5000


def test_markdown_subset():
    html = md.to_html(QA_MD, heading_offset=2, id_prefix="qa-x")
    assert '<h3 id="qa-x-h0">QA: module C</h3>' in html
    assert "<strong>389</strong>" in html
    assert "<code>&lt;agent name&gt;</code>" in html and "&lt;b&gt;tags&lt;/b&gt;" in html
    assert '<a href="https://theaidigest.org/village"' in html
    assert '<details class="md-details"><summary>Series list</summary>' in html and "</details>" in html
    assert "<ol><li>First step.</li><li>Second step.</li></ol>" in html
    assert 'class="a-right"' in html
    assert "someone@example.com" not in html and "按隐私规则隐藏列：email" in html
    assert md.sections(QA_MD, ("2.",)).startswith("## 2. Alignment")
    assert [t for _, _, t in md.headings(QA_MD)] == ["QA: module C", "1. Inputs", "2. Alignment"]


def test_progress_tables_and_log():
    p = parse_progress(PROGRESS)
    assert [t.title for t in p.tasks] == ["阶段 0（P0）", "模块 B1、C（P0）"]
    assert p.status_counts() == {"Completed": 1, "In progress": 1, "Not started": 1, "Blocked": 1}
    assert p.rows_for("moduleB1") == [("B1 memory 链", "Blocked")]
    assert p.rows_for("moduleC") == [("C 变点与 CHANGELOG 对齐", "Not started")]
    assert len(p.rows_for("data")) == 2
    assert [r[1] for r in p.log.rows] == ["建仓库骨架", "读数据集文档"]  # rows after a blank line continue


def test_build_report(tree):
    out = build_report(_cfg(tree))
    assert out == tree / "reports" / "index.html"
    html = out.read_text(encoding="utf-8")
    assert "AVSD 结果浏览" in html
    for label in TAB_LABELS:
        assert f">{label}</a>" in html, label
    for token in ("overview", "data", "moduleA", "moduleB1", "moduleC", "moduleD", "validation", "qa"):
        assert f'id="tab-{token}"' in html and f'href="#{token}"' in html
    # Embedded data, without free-text columns or their values.
    blocks = _data_blocks(html)
    cp = blocks["d-tables-changepoints-csv"]
    assert "family:Anthropic:msg_count" in _values(cp, "series_id")
    assert _values(cp, "magnitude")[0] == -35.06548961962977 and _values(cp, "aligned")[:2] == [True, False]
    assert "evidence_text" not in _columns(cp) and cp["hidden"] == ["evidence_text"]
    assert "summary" not in _columns(blocks["d-tables-mystery-stats-csv"])
    assert "text" not in _columns(blocks["d-tables-changelog-review-md"])
    for secret in ("SECRET-CELL-1", "SECRET-CELL-2", "SECRET-CELL-3", "someone@example.com"):
        assert secret not in html
    assert not any("parquet" in k for k in blocks)
    assert "changepoint_monitor_findings.parquet" in html and "parquet 表不嵌入" in html
    # Figures inline, no external resources.
    assert "data:image/png;base64," + base64.b64encode(PNG).decode() in html
    assert re.search(r"<script[^>]+src=", html) is None and "<link" not in html and "@import" not in html
    # Markdown, PROGRESS status pills, work log, ingest summary.
    assert "&lt;agent name&gt;" in html and '<details class="md-details">' in html
    for css, status in (("done", "Completed"), ("doing", "In progress"), ("todo", "Not started"),
                        ("blocked", "Blocked")):
        assert f'<span class="pill {css}">{status}</span>' in html
    assert "建仓库骨架" in html and "读数据集文档" in html
    assert _values(blocks["d-ingest-summary"], "rows_written") == [46]
    # Views: chart entries from changelog_review.md, defaults and fixed filters, unknown file routing.
    views = json.loads(re.search(r'id="avsd-views">(.*?)</script>', html, re.DOTALL).group(1))
    chart = next(v for v in views.values() if "entries" in v)
    entry = next(e for e in chart["entries"] if e["id"] == "cl-2025-04-24-1")
    assert (entry["s"], entry["e"], entry["r"]) == ("2025-04-24", "2025-04-25", 0)
    assert next(e for e in chart["entries"] if e["id"].startswith("roster"))["r"] == 1
    fixed = [v for v in views.values() if v.get("fixed")]
    assert {f["op"] for v in fixed for f in v["fixed"]} == {"prefix", "notnull"}
    cp_view = next(v for v in views.values() if v.get("src") == "d-tables-changepoints-csv" and "columns" in v
                   and not v.get("fixed"))
    assert next(f for f in cp_view["filters"] if f["col"] == "method")["default"] == "pelt_l2"
    assert "mystery_stats.csv" in html
    # Missing outputs are listed with their expected names.
    assert "尚未产出" in html and "outputs/tables/hawkes_*.csv" in html
    assert "outputs/figures/F6_memory_retention_v2.png" in html


def test_build_report_empty_tree(tmp_path):
    out = build_report(_cfg(tmp_path))
    html = out.read_text(encoding="utf-8")
    for label in TAB_LABELS:
        assert f">{label}</a>" in html
    assert "未找到 PROGRESS.md" in html and "尚未产出" in html
    for name in ("outputs/tables/changepoints.csv", "outputs/figures/F5_changepoint_timeline.png",
                 "outputs/tables/memory_hazard_v2.csv", "outputs/qa/*.md", "outputs/tables/hawkes_*.csv"):
        assert name in html, name
    assert "data:image/png" not in html


def test_unreadable_file_becomes_error_card(tree, monkeypatch):
    def boom(path, *args, **kwargs):
        raise ValueError(f"cannot parse {path.name}")

    monkeypatch.setattr(build, "read_csv_table", boom)
    html = build_report(_cfg(tree)).read_text(encoding="utf-8")
    assert "无法读取这个文件" in html and "cannot parse memory_hazard_v2.csv" in html
    assert "AVSD 结果浏览" in html


def test_cli_report(tree):
    cfg = tree / "cfg.yaml"
    cfg.write_text(f"paths:\n  outputs: {tree / 'outputs'}\n  reports: {tree / 'reports'}\n", encoding="utf-8")
    from avsd.cli import app

    result = CliRunner().invoke(app, ["report", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "index.html" in result.output and "MB" in result.output
