#!/usr/bin/env python3
import os
import re
import sys
import json
import argparse
from hashlib import sha256

EXCLUDE_DIRS = {"node_modules", ".git", "dist", "build", "target", "__pycache__", ".venv", "venv"}

SENSITIVE_PATTERNS = [
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    re.compile(r"(?i)api[_-]?key\b"),
    re.compile(r"(?i)secret\b"),
    re.compile(r"(?i)token\b"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"sk_live_[0-9a-zA-Z]{24,}"),
    re.compile(r"\+?\d{2,3}[ -]?\d{3,4}[ -]?\d{4}")
]

DEFAULT_SYSTEM = "너는 학습자를 돕는 전문적인 개발 교육 AI다."


def is_sensitive(text):
    if not text:
        return False
    for p in SENSITIVE_PATTERNS:
        if p.search(text):
            return True
    return False


def normalize_role(r):
    if not r:
        return None
    r = r.strip().lower()
    if r in ("system", "user", "assistant"):
        return r
    if r in ("instruction", "prompt", "question"):
        return "user"
    if r in ("output", "response", "answer", "completion"):
        return "assistant"
    return None


def convert_obj_to_messages(obj):
    # If already has messages
    if isinstance(obj, dict) and "messages" in obj and isinstance(obj["messages"], list):
        msgs = []
        for m in obj["messages"]:
            if not isinstance(m, dict):
                continue
            role = normalize_role(m.get("role") or m.get("speaker"))
            content = m.get("content") or m.get("text") or m.get("message")
            if role and content and isinstance(content, str) and content.strip():
                msgs.append({"role": role, "content": content.strip()})
        return msgs

    # Try common key conversions
    keys = {k.lower(): v for k, v in (obj.items() if isinstance(obj, dict) else [])}
    instruction = keys.get("instruction") or keys.get("prompt") or keys.get("question") or keys.get("input")
    output = keys.get("output") or keys.get("response") or keys.get("answer") or keys.get("completion")
    text = keys.get("text") or keys.get("content")

    msgs = []
    if instruction and isinstance(instruction, str):
        msgs.append({"role": "user", "content": instruction.strip()})
    if text and isinstance(text, str) and not instruction:
        # ambiguous single text
        # treat as user if there's no output
        if not output:
            msgs.append({"role": "user", "content": text.strip()})
    if output and isinstance(output, str):
        msgs.append({"role": "assistant", "content": output.strip()})

    if msgs:
        return msgs

    return None


def clean_jsonl_file(path, out_path):
    stats = {"orig": 0, "parsed": 0, "kept": 0, "skipped_parse": 0, "skipped_sensitive": 0, "skipped_short": 0, "skipped_no_pair": 0, "duplicates": 0}
    seen = set()
    with open(path, "r", encoding="utf-8") as rf, open(out_path, "w", encoding="utf-8") as wf:
        for line in rf:
            stats["orig"] += 1
            line = line.strip()
            if not line:
                stats["skipped_parse"] += 1
                continue
            try:
                obj = json.loads(line)
                stats["parsed"] += 1
            except Exception:
                stats["skipped_parse"] += 1
                continue

            msgs = convert_obj_to_messages(obj)
            if not msgs:
                stats["skipped_no_pair"] += 1
                continue

            # Normalize roles and filter empty
            sys_present = any(m["role"] == "system" for m in msgs)
            user_cnt = sum(1 for m in msgs if m["role"] == "user")
            assistant_cnt = sum(1 for m in msgs if m["role"] == "assistant")

            if not sys_present:
                msgs.insert(0, {"role": "system", "content": DEFAULT_SYSTEM})

            # Remove messages with empty content
            msgs = [m for m in msgs if isinstance(m.get("content"), str) and m.get("content").strip()]

            if user_cnt < 1 or assistant_cnt < 1:
                stats["skipped_no_pair"] += 1
                continue

            combined = "\n".join(m["content"] for m in msgs)
            if is_sensitive(combined):
                stats["skipped_sensitive"] += 1
                continue

            # enforce assistant length
            assistant_texts = [m["content"] for m in msgs if m["role"] == "assistant"]
            if not assistant_texts or any(len(t.strip()) < 50 for t in assistant_texts):
                stats["skipped_short"] += 1
                continue

            # deduplicate
            h = sha256(json.dumps(msgs, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            if h in seen:
                stats["duplicates"] += 1
                continue
            seen.add(h)

            out_obj = {"messages": msgs}
            wf.write(json.dumps(out_obj, ensure_ascii=False) + "\n")
            stats["kept"] += 1

    return stats


def clean_md_file(path, out_path):
    with open(path, "r", encoding="utf-8") as rf:
        text = rf.read()

    # mask emails and other obvious secrets
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", text)
    text = re.sub(r"sk_live_[0-9a-zA-Z]{24,}", "[REDACTED_SECRET]", text)
    # remove common temp markers
    lines = text.splitlines()
    cleaned_lines = []
    todos = []
    for ln in lines:
        if any(tok in ln for tok in ("TODO", "FIXME", "임시", "TBD", "tmp", "일시적", "확인 필요")):
            todos.append(ln.strip())
            continue
        cleaned_lines.append(ln.rstrip())

    # remove repeated adjacent identical lines
    deduped = []
    prev = None
    for ln in cleaned_lines:
        if ln == prev:
            continue
        deduped.append(ln)
        prev = ln

    # collapse multiple blank lines
    out_lines = []
    blank_count = 0
    for ln in deduped:
        if not ln.strip():
            blank_count += 1
            if blank_count > 1:
                continue
        else:
            blank_count = 0
        out_lines.append(ln)

    # find title and purpose
    title = None
    para = []
    for ln in out_lines:
        if ln.strip().startswith("#") and not title:
            title = ln.strip().lstrip('#').strip()
        if ln.strip() and not ln.strip().startswith("#"):
            para.append(ln.strip())
        if len(para) >= 2:
            break

    if not title:
        title = os.path.splitext(os.path.basename(path))[0]

    purpose = para[0] if para else "확인 필요"

    # find code/file mentions
    file_matches = set(re.findall(r"[\w\-/\\.]+\.(py|java|md|jsonl|json|yml|yaml|sh|sql)", text))

    # extract code blocks
    code_blocks = re.findall(r"```([\s\S]*?)```", text)

    new_sections = []
    new_sections.append(f"# {title}\n")
    new_sections.append("## 1. 목적\n")
    new_sections.append(purpose + "\n")
    new_sections.append("## 2. 현재 상태\n")
    new_sections.append(("\n".join(para[1:3]) if len(para) > 1 else "확인 필요") + "\n")
    new_sections.append("## 3. 주요 파일\n")
    if file_matches:
        for f in sorted(file_matches):
            new_sections.append(f"- {f}\n")
    else:
        new_sections.append("- 확인 필요\n")

    new_sections.append("## 4. 작업 내용\n")
    # put remainder of document (up to 3000 chars) as summary
    remainder = "\n".join(out_lines)[:3000]
    new_sections.append(remainder + "\n")

    new_sections.append("## 5. 수정 기준\n")
    new_sections.append("확인 필요\n")
    new_sections.append("## 6. 실행 방법\n")
    if code_blocks:
        for cb in code_blocks:
            new_sections.append("```\n" + cb.strip() + "\n```\n")
    else:
        new_sections.append("확인 필요\n")

    new_sections.append("## 7. 검증 방법\n")
    new_sections.append("확인 필요\n")
    new_sections.append("## 8. 주의사항\n")
    new_sections.append(("마스킹 적용됨\n") if "[REDACTED_EMAIL]" in text else "없음\n")
    new_sections.append("## 9. 남은 작업\n")
    new_sections.append(("\n".join(todos) if todos else "없음") + "\n")

    with open(out_path, "w", encoding="utf-8") as wf:
        wf.write("\n".join(new_sections))

    return {"orig": len(lines), "todos": len(todos)}


def should_skip_dir(dirpath, exclude):
    parts = set(dirpath.split(os.sep))
    return bool(parts & exclude)


def main(root):
    report = {"md": [], "jsonl": [], "stats": {}}
    for dirpath, dirnames, filenames in os.walk(root):
        # skip excluded dirs
        if should_skip_dir(dirpath, EXCLUDE_DIRS):
            continue
        for fname in filenames:
            lower = fname.lower()
            full = os.path.join(dirpath, fname)
            if lower.endswith(".jsonl") and not lower.endswith("_clean.jsonl"):
                out_path = os.path.join(dirpath, fname[:-6] + "_clean.jsonl")
                print(f"Cleaning JSONL: {full} -> {out_path}")
                stats = clean_jsonl_file(full, out_path)
                report["jsonl"].append({"src": full, "out": out_path, "stats": stats})
            elif lower.endswith(".md") and not lower.endswith("_clean.md"):
                out_path = os.path.join(dirpath, fname[:-3] + "_clean.md")
                print(f"Cleaning MD: {full} -> {out_path}")
                stats = clean_md_file(full, out_path)
                report["md"].append({"src": full, "out": out_path, "stats": stats})

    # write summary report
    rep_path = os.path.join(root, "cleanup_report.md")
    total_deleted = sum((r["stats"].get("orig", 0) - r["stats"].get("kept", 0)) for r in report["jsonl"])
    total_kept = sum((r["stats"].get("kept", 0)) for r in report["jsonl"])
    with open(rep_path, "w", encoding="utf-8") as rf:
        rf.write("# Cleanup Report\n\n")
        rf.write("## JSONL files processed:\n")
        for r in report["jsonl"]:
            rf.write(f"- {r['src']} -> {r['out']} (kept={r['stats'].get('kept',0)}, orig={r['stats'].get('orig',0)})\n")
        rf.write("\n## MD files processed:\n")
        for r in report["md"]:
            rf.write(f"- {r['src']} -> {r['out']} (lines={r['stats'].get('orig',0)})\n")
        rf.write(f"\nTotal JSONL kept: {total_kept}\n")
        rf.write(f"Total JSONL removed lines: {total_deleted}\n")

    print(f"Cleanup complete. Report: {rep_path}")


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--root', default='.', help='workspace root')
    args = p.parse_args()
    main(args.root)
