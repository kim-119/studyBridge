#!/usr/bin/env python3
"""
scan_java_files.py
Java 파일 목록을 수집하고 기본 정보를 추출한다.

실행 예시:
  python app/scripts/scan_java_files.py --root backend --out app/reports/java_files.json
"""
import argparse
import json
import re
import sys
from pathlib import Path

# 분석 제외 경로 패턴
EXCLUDE_DIRS = {
    "build", "target", ".gradle", "out", "node_modules",
    "__pycache__", ".venv", "venv", ".git", "dist"
}

def should_exclude(path: Path) -> bool:
    return any(part in EXCLUDE_DIRS for part in path.parts)

def extract_package(content: str) -> str:
    m = re.search(r'^package\s+([\w.]+)\s*;', content, re.MULTILINE)
    return m.group(1) if m else ""

def extract_class_name(content: str) -> str:
    m = re.search(r'(?:public\s+)?(?:class|interface|enum|record)\s+(\w+)', content)
    return m.group(1) if m else ""

def extract_annotations(content: str) -> list:
    return re.findall(r'@(\w+)', content)

def scan_java_files(root: str) -> list:
    root_path = Path(root)
    if not root_path.exists():
        print(f"[ERROR] 경로를 찾을 수 없습니다: {root}", file=sys.stderr)
        return []

    results = []
    for java_file in root_path.rglob("*.java"):
        if should_exclude(java_file):
            continue

        try:
            content = java_file.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            print(f"[WARN] 읽기 실패: {java_file} — {e}", file=sys.stderr)
            continue

        lines = content.splitlines()
        is_test = "src/test" in java_file.as_posix()
        annotations = extract_annotations(content)

        results.append({
            "file_path": java_file.as_posix(),
            "relative_path": java_file.relative_to(root_path).as_posix(),
            "is_test": is_test,
            "line_count": len(lines),
            "size_bytes": java_file.stat().st_size,
            "package_name": extract_package(content),
            "class_name_candidate": extract_class_name(content),
            "annotations": list(set(annotations)),
            "has_ai_keyword": any(kw in content.lower() for kw in
                ["fastapi", "webclient", "resttemplate", "openai", "qwen", "tavily",
                 "rag", "material", "pdf", "extraction", "ai"]),
            "has_security_keyword": any(kw in content.lower() for kw in
                ["jwt", "security", "authentication", "authorization", "password", "secret"]),
        })

    return results

def main():
    parser = argparse.ArgumentParser(description="Java 파일 목록 수집기")
    parser.add_argument("--root", required=True, help="스캔할 루트 경로 (예: backend)")
    parser.add_argument("--out", required=True, help="결과 JSON 저장 경로")
    parser.add_argument("--summary", action="store_true", help="마크다운 요약도 출력")
    args = parser.parse_args()

    print(f"[INFO] 스캔 시작: {args.root}")
    files = scan_java_files(args.root)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(files, ensure_ascii=False, indent=2), encoding="utf-8")

    main_count = sum(1 for f in files if not f["is_test"])
    test_count = sum(1 for f in files if f["is_test"])
    ai_count = sum(1 for f in files if f["has_ai_keyword"])

    print(f"[INFO] 총 Java 파일: {len(files)}개 (main: {main_count}, test: {test_count})")
    print(f"[INFO] AI 관련 키워드 파일: {ai_count}개")
    print(f"[INFO] 결과 저장: {args.out}")

    if args.summary:
        md_path = out_path.with_suffix(".md")
        lines = ["# Java 파일 스캔 결과\n",
                 f"- 총 파일: {len(files)}개\n",
                 f"- main: {main_count}개 / test: {test_count}개\n",
                 f"- AI 관련: {ai_count}개\n\n",
                 "## 파일 목록\n\n",
                 "| 파일 | 패키지 | 클래스 | AI관련 |\n",
                 "|---|---|---|---|\n"]
        for f in files:
            ai_mark = "✅" if f["has_ai_keyword"] else ""
            lines.append(f"| `{f['relative_path']}` | `{f['package_name']}` | `{f['class_name_candidate']}` | {ai_mark} |\n")
        md_path.write_text("".join(lines), encoding="utf-8")
        print(f"[INFO] 마크다운 요약 저장: {md_path}")

if __name__ == "__main__":
    main()
