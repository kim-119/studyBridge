#!/usr/bin/env bash
# EC2 로드맵 분할기(MaterialRoadmapQualityGate.segmenter) + 체크섬 규칙을 git ref 에서 읽기 전용 추출·컴파일해 실행한다.
# 사용: run_segment_crosscheck.sh <cases.jsonl> [git-ref]   (기본 ref = origin/feature/learning-loop-ec2, 같은 checkout 에 backend/ 가 있으면 작업 트리)
# 필요: JDK 17+, Jackson 2.15.x jar(JACKSON_CP 또는 ~/.gradle 캐시 또는 AI_CONTRACT_FETCH_JARS=1 — run_java_crosscheck.sh 와 같은 규칙).
set -euo pipefail
CASES="$1"; REF="${2:-origin/feature/learning-loop-ec2}"
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(git -C "$HERE" rev-parse --show-toplevel)"
JAVA_BIN="${JAVA_HOME:+$JAVA_HOME/bin/}"
if ! command -v "${JAVA_BIN}javac" >/dev/null 2>&1; then
  J=$(ls -d "$HOME"/.local/jdk-*/ 2>/dev/null | sort | tail -1 || true); [ -n "$J" ] && JAVA_BIN="$J/bin/"
fi
command -v "${JAVA_BIN}javac" >/dev/null 2>&1 || { echo "JDK_NOT_FOUND" >&2; exit 3; }
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
if [ -z "${JACKSON_CP:-}" ]; then
  G="$HOME/.gradle/caches/modules-2/files-2.1"; V="${JACKSON_VERSION:-2.15.4}"
  JACKSON_CP=$(ls "$G"/com.fasterxml.jackson.core/jackson-databind/$V/*/jackson-databind-$V.jar \
    "$G"/com.fasterxml.jackson.core/jackson-core/$V/*/jackson-core-$V.jar \
    "$G"/com.fasterxml.jackson.core/jackson-annotations/$V/*/jackson-annotations-$V.jar 2>/dev/null | tr '\n' ':' || true)
fi
if [ -z "$JACKSON_CP" ] && [ "${AI_CONTRACT_FETCH_JARS:-0}" = "1" ]; then
  M=https://repo1.maven.org/maven2/com/fasterxml/jackson
  while read -r sum path; do
    out="$W/jars/$(basename "$path")"; mkdir -p "$W/jars"
    curl -fsSL --max-time 60 "$M/$path" -o "$out" || { echo "JACKSON_DOWNLOAD_FAILED" >&2; exit 3; }
    echo "$sum  $out" | sha256sum -c --quiet - || { echo "JACKSON_CHECKSUM_MISMATCH" >&2; exit 3; }
    JACKSON_CP="$JACKSON_CP$out:"
  done <<'JARS'
0f99ff7719eef3ee85608b3dee6ecf3c698003fe9d6e34eabbfabccdc9b5ac2c core/jackson-databind/2.15.4/jackson-databind-2.15.4.jar
8dc9210dd285db366f45f518dd1e6a9ccfeb0f1a8e184a899fe96d29edf1fd94 core/jackson-core/2.15.4/jackson-core-2.15.4.jar
f204ebbd552614a22b8531ffe350d47f8fd42c45bb60517c07974dc27a5a1dd3 core/jackson-annotations/2.15.4/jackson-annotations-2.15.4.jar
JARS
fi
[ -n "$JACKSON_CP" ] || { echo "JACKSON_NOT_FOUND" >&2; exit 3; }
F=backend/src/main/java/com/studybridge/api/service/MaterialRoadmapQualityGate.java
if [ -f "$REPO/$F" ] && [ -z "${2:-}" ]; then SRC=$(cat "$REPO/$F"); REF=WORKTREE; else SRC=$(git -C "$REPO" show "$REF:$F"); fi
BODY=$(printf '%s\n' "$SRC" | awk '/static SegmentedQualityGate.Segmenter segmenter\(int budget\)/,/^    }$/' | sed 's/SegmentedQualityGate\.//g')
[ -n "$BODY" ] || { echo "SEGMENTER_NOT_FOUND" >&2; exit 4; }
mkdir -p "$W/src/x" "$W/classes"
awk -v body="$BODY" '{ if ($0 == "//@@SEGMENTER@@") print body; else print }' "$HERE/SegmentChecksumHarness.java.in" > "$W/src/x/SegmentChecksumHarness.java"
echo "[segment-crosscheck] segmenter source: $REF" >&2
"${JAVA_BIN}javac" -nowarn -encoding UTF-8 -cp "$JACKSON_CP" -d "$W/classes" "$W/src/x/SegmentChecksumHarness.java" >&2
"${JAVA_BIN}java" -cp "$W/classes:$JACKSON_CP" x.SegmentChecksumHarness < "$CASES"
