"""JSONL 입출력 — atomic write, UTF-8, ensure_ascii=False."""
import json
import os
import tempfile
from pathlib import Path


def read_jsonl(path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def write_jsonl(path, rows: list[dict]) -> int:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    n = 0
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    os.replace(tmp, p)
    return n


def append_jsonl(path, row: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def count_lines(path) -> int:
    p = Path(path)
    if not p.exists():
        return 0
    return sum(1 for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip())
