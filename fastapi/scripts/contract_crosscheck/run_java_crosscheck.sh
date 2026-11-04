#!/usr/bin/env bash
# EC2 canonical Java 계약 클래스(git ref 에서 추출) + ContractDiffHarness 를 컴파일해 cases(JSONL) 의 Java 판정을 출력한다.
# 사용: run_java_crosscheck.sh <cases.jsonl> [git-ref]   (기본 ref = origin/feature/learning-loop-ec2)
# 필요: JDK 17+ (JAVA_HOME 또는 PATH 또는 ~/.local/jdk-*), Jackson 2.15.x jar(JACKSON_CP 또는 ~/.gradle 캐시).
# 운영 영향 없음: 임시 디렉터리에서만 컴파일·실행한다. Spring 소스는 수정하지 않는다(읽기 전용 추출).
set -euo pipefail
CASES="$1"; REF="${2:-origin/feature/learning-loop-ec2}"   # WORKTREE = 같은 checkout 의 backend/ 소스
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
    "$G"/com.fasterxml.jackson.core/jackson-annotations/$V/*/jackson-annotations-$V.jar \
    "$G"/com.fasterxml.jackson.datatype/jackson-datatype-jsr310/$V/*/jackson-datatype-jsr310-$V.jar 2>/dev/null | tr '\n' ':' || true)
fi
if [ -z "$JACKSON_CP" ] && [ "${AI_CONTRACT_FETCH_JARS:-0}" = "1" ]; then
  # CI 전용: Spring Boot 3.2.4 와 같은 Jackson 2.15.4 를 Maven Central 에서 받고 SHA-256 고정값으로 검증한다.
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
472498cbba2726012ff82f86fc8feef9593663bda1a695a17db804a63fa733ff datatype/jackson-datatype-jsr310/2.15.4/jackson-datatype-jsr310-2.15.4.jar
JARS
fi
[ -n "$JACKSON_CP" ] || { echo "JACKSON_NOT_FOUND" >&2; exit 3; }
P=com/studybridge/api/ai/contract/v1; mkdir -p "$W/src/$P" "$W/classes"
D=backend/src/main/java/$P
# EC2 소스: 같은 checkout 에 있으면(두 PR 병합 후) 작업 트리 파일, 없으면 git ref 에서 읽기 전용 추출.
src() {
  if [ "$REF" = "WORKTREE" ] || { [ -z "${2:-}" ] && [ -f "$REPO/$D/ContractJson.java" ]; }; then cat "$REPO/$D/$1.java"
  else git -C "$REPO" show "$REF:$D/$1.java"; fi
}
[ -n "${2:-}" ] || { [ -f "$REPO/$D/ContractJson.java" ] && REF=WORKTREE; }
for f in AiContractException AiContractSigning CanonicalJson ContractJson LearningContextV1 ResponseQualityV1 TrainingSampleV1; do
  src "$f" > "$W/src/$P/$f.java"
done
echo "[crosscheck] java sources: $REF" >&2
# AiSigningKeys 는 Spring(@Component/@Value) 의존 → 서명 검증에 필요한 상수만 스텁으로 대체(값은 EC2 원본에서 추출).
MIN=$(src AiSigningKeys | sed -n 's/.*MIN_KEY_BYTES *= *\([0-9]*\);.*/\1/p')
printf 'package com.studybridge.api.ai.contract.v1;\npublic class AiSigningKeys { public static final int MIN_KEY_BYTES = %s; }\n' "$MIN" > "$W/src/$P/AiSigningKeys.java"
cp "$HERE/ContractDiffHarness.java" "$W/src/$P/"
"${JAVA_BIN}javac" -nowarn -encoding UTF-8 -cp "$JACKSON_CP" -d "$W/classes" $(find "$W/src" -name '*.java') >&2
"${JAVA_BIN}java" -cp "$W/classes:$JACKSON_CP" com.studybridge.api.ai.contract.v1.ContractDiffHarness < "$CASES"
