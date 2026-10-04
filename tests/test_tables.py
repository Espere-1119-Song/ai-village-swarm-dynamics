import gzip
import json

import polars as pl

from avsd.io.tables import SPECS, convert_table


def _write(path, rows):
    with gzip.open(path, "wt") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_events_split_main_and_text(tmp_path):
    rows = [
        {
            "id": f"e{i}", "event_index": i, "village_id": "v",
            "created_at": "2025-12-29 18:49:21.291984", "updated_at": "2025-12-29 18:49:21",
            "data": {"actionType": "AGENT_TALK", "speakerId": "a1", "messageId": f"m{i}",
                     "content": "hello", "output": {"content": [{"type": "text"}]}},
        }
        for i in range(5)
    ] + [{"id": "u1", "event_index": 9, "created_at": "2025-12-29 19:00:00.000001",
          "data": {"actionType": "USER_TALK", "speakerName": "someone"}, "extra": 1}]
    _write(tmp_path / "events.jsonl.gz", rows)
    spec = SPECS["events"]
    spec.chunk_rows = 2
    stats = convert_table(spec, tmp_path, tmp_path / "out")
    main = pl.read_parquet(tmp_path / "out" / "events.parquet")
    text = pl.read_parquet(tmp_path / "out" / "events_text.parquet")
    assert stats.rows == 6 and main.height == 6 and text.height == 6
    assert stats.unknown_keys["extra"] == 1
    assert main["created_at"].null_count() == 0
    assert str(main["created_at"].dtype) == "Datetime(time_unit='us', time_zone='UTC')"
    assert main.filter(pl.col("id") == "e0")["content_len"].item() == 5
    assert "speaker_name" not in main.columns
    assert json.loads(text.filter(pl.col("id") == "e0")["output"].item())["content"][0]["type"] == "text"


def test_turns_action_name(tmp_path):
    rows = [
        {"id": "t1", "session_id": "s", "created_at": "2026-01-01 00:00:00.5",
         "agent_action": {"action": "left_click", "coordinate": [1, 2]}, "output": None},
        {"id": "t2", "session_id": "s", "created_at": "2026-01-01 00:00:01.5",
         "agent_action": {"command": "ls"}, "output": "a\nb", "agent_messages": [{"x": 1}]},
        {"id": "t3", "session_id": "s", "created_at": "2026-01-01 00:00:02.5", "agent_action": None},
    ]
    _write(tmp_path / "computer_use_turns.jsonl.gz", rows)
    convert_table(SPECS["computer_use_turns"], tmp_path, tmp_path / "out")
    main = pl.read_parquet(tmp_path / "out" / "computer_use_turns.parquet").sort("id")
    assert main["action_name"].to_list() == ["left_click", "bash", None]
    assert main["output_len"].to_list() == [None, 3, None]
