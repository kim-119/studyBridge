from pathlib import Path
from app.training.studybridge_ft.utils import jsonl_io


def test_write_read_roundtrip(tmp_path):
    p = tmp_path / "a.jsonl"
    n = jsonl_io.write_jsonl(p, [{"x": 1}, {"y": "한글"}])
    assert n == 2
    rows = jsonl_io.read_jsonl(p)
    assert rows == [{"x": 1}, {"y": "한글"}]


def test_append_and_count(tmp_path):
    p = tmp_path / "b.jsonl"
    jsonl_io.append_jsonl(p, {"a": 1})
    jsonl_io.append_jsonl(p, {"a": 2})
    assert jsonl_io.count_lines(p) == 2


def test_read_missing_returns_empty(tmp_path):
    assert jsonl_io.read_jsonl(tmp_path / "none.jsonl") == []
