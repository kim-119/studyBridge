#!/usr/bin/env python3
"""
SFT(Supervised Fine-Tuning) 데이터셋 준비 스크립트.

training_candidate DB에서 auto_approved 데이터를 추출하여
Qwen2.5 14B SFT용 JSONL 포맷으로 변환한다.

JSONL 포맷 (messages 형식):
  {"messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]}

실행 예시:
  python prepare_sft_dataset.py --output ./data/sft_train.jsonl --limit 1000
  python prepare_sft_dataset.py --output ./data/sft_train.jsonl --smoke

주의:
- 실제 DB 연결이 필요하다. AI_DATABASE_URL 환경변수를 설정할 것.
- rejected/duplicate/unsafe 데이터는 제외한다.
- auto_approved=true 데이터만 사용한다.
- 실제 학습 전 validate_sft_dataset.py로 검증할 것.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


SMOKE_EXAMPLES = [
    {
        "messages": [
            {
                "role": "system",
                "content": (
                    "너는 StudyBridge AI 에이전트 '설명봇'이다.\n"
                    "역할: 학습 도우미\n"
                    "[지식수준] 학사: 개념 정의와 작동 원리, 기본 예시를 포함하라.\n"
                    "[말투/성격] 친절_설명형: 따뜻하고 친근한 말투로 설명하라."
                ),
            },
            {"role": "user", "content": "Python에서 리스트와 튜플의 차이가 뭐예요?"},
            {
                "role": "assistant",
                "content": (
                    "좋은 질문이에요! 리스트와 튜플은 둘 다 여러 값을 담는 자료구조인데, "
                    "가장 큰 차이는 **변경 가능 여부**예요.\n\n"
                    "- 리스트 `[]`: 값을 자유롭게 추가/수정/삭제할 수 있어요.\n"
                    "- 튜플 `()`: 한번 만들면 값을 바꿀 수 없어요 (불변).\n\n"
                    "예를 들어, 학생 점수처럼 자주 바뀌는 데이터엔 리스트, "
                    "좌표처럼 고정된 데이터엔 튜플이 어울려요."
                ),
            },
        ]
    },
    {
        "messages": [
            {
                "role": "system",
                "content": (
                    "너는 StudyBridge AI 에이전트 '분석봇'이다.\n"
                    "역할: 비판적 분석 전문가\n"
                    "[지식수준] 석사: 구조, 한계, 적용 조건을 포함하라.\n"
                    "[말투/성격] 비판적_분析형: 헷갈리기 쉬운 지점을 짚되 개선 방향을 제시하라."
                ),
            },
            {"role": "user", "content": "OOP의 상속이 항상 좋은 설계인가요?"},
            {
                "role": "assistant",
                "content": (
                    "그렇게만 이해하면 반은 맞고 반은 틀려요. "
                    "상속은 코드 재사용을 위한 강력한 도구지만, "
                    "무분별하게 쓰면 오히려 설계를 망가뜨립니다.\n\n"
                    "핵심 문제는 **취약한 기반 클래스(Fragile Base Class)**예요. "
                    "부모 클래스를 수정하면 모든 자식 클래스에 영향이 퍼집니다. "
                    "이를 피하려면 상속 대신 **조합(Composition)**을 고려해보세요. "
                    "GoF의 원칙도 '상속보다 조합을 선호하라'고 말합니다."
                ),
            },
        ]
    },
]


def build_from_db(limit: int, auto_approved_only: bool = True) -> list[dict]:
    """AI DB에서 학습 후보를 추출한다."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / "fastapi" / ".env")
    except ImportError:
        pass

    try:
        import os
        import psycopg
        db_url = os.getenv("AI_DATABASE_URL") or os.getenv("VECTOR_DATABASE_URL")
        if not db_url:
            print("[경고] AI_DATABASE_URL 미설정. smoke 예시 데이터를 사용합니다.")
            return []

        # 테이블/컬럼은 운영 스키마(ai.training_candidate, 단수)에 통일한다.
        #  - 컬럼: question/answer/system_prompt (training_candidate_manager INSERT 기준)
        #  - 승인 필터: quality_status='auto_approved' + is_duplicate/is_unsafe FALSE
        #    (jsonl_export_service._fetch_approved와 동일 규칙)
        query = """
            SELECT system_prompt, question, answer
            FROM ai.training_candidate
            WHERE quality_status = 'auto_approved'
              AND is_duplicate = false
              AND is_unsafe = false
            ORDER BY created_at DESC
            LIMIT %s
        """
        with psycopg.connect(db_url) as conn:
            rows = conn.execute(query, (limit,)).fetchall()

        records = []
        for row in rows:
            system_p, user_msg, assistant_ans = row
            if not (system_p and user_msg and assistant_ans):
                continue
            records.append({
                "messages": [
                    {"role": "system",    "content": system_p.strip()},
                    {"role": "user",      "content": user_msg.strip()},
                    {"role": "assistant", "content": assistant_ans.strip()},
                ]
            })
        return records

    except Exception as e:
        print(f"[경고] DB 추출 실패: {e}. smoke 예시 데이터를 사용합니다.")
        return []


def save_jsonl(records: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"저장 완료: {output_path} ({len(records)}건)")


def main():
    parser = argparse.ArgumentParser(description="SFT 데이터셋 준비")
    parser.add_argument("--output", default="./data/sft_train.jsonl", help="출력 JSONL 경로")
    parser.add_argument("--limit", type=int, default=1000, help="DB에서 추출할 최대 건수")
    parser.add_argument("--smoke", action="store_true", help="DB 연결 없이 smoke 예시 데이터 사용")
    args = parser.parse_args()

    output_path = Path(args.output)

    if args.smoke:
        print("[SMOKE] 예시 데이터 사용")
        records = SMOKE_EXAMPLES
    else:
        print(f"[DB] auto_approved 데이터 추출 (최대 {args.limit}건)")
        records = build_from_db(args.limit)
        if not records:
            print("[INFO] DB 데이터 없음. smoke 예시로 대체.")
            records = SMOKE_EXAMPLES

    save_jsonl(records, output_path)


if __name__ == "__main__":
    main()
