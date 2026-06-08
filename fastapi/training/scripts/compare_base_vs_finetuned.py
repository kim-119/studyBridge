#!/usr/bin/env python3
"""
base 모델 vs fine-tuned adapter 응답 비교 스크립트.

동일한 질문에 대해 base 모델과 fine-tuned(커스텀) 모델의 응답을 나란히 출력한다.
실제 품질 판단은 사람이 직접 읽고 결정해야 한다.
학습 완료 = 품질 개선 보장이 아니다.

실행 예시:
  python compare_base_vs_finetuned.py \
    --base qwen2.5:14b \
    --finetuned studybridge-qwen25-14b \
    --output ./eval/comparison_result.jsonl
"""
import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

COMPARE_PROMPTS = [
    {
        "system": (
            "너는 학습 도우미 에이전트 '설명봇'이다.\n"
            "[지식수준] 학사: 개념 정의와 작동 원리, 기본 예시.\n"
            "[말투] 친절_설명형: 따뜻하고 친근하게."
        ),
        "user": "Python의 GIL이 무엇이고 왜 문제가 되나요?",
    },
    {
        "system": (
            "너는 비판적 분석 에이전트 '분석봇'이다.\n"
            "[지식수준] 석사: 구조, 한계, 적용 조건.\n"
            "[말투] 비판적_분析형: 지적 후 개선 방향."
        ),
        "user": "Docker를 쓰면 모든 배포 문제가 해결되나요?",
    },
    {
        "system": (
            "너는 요약 에이전트 '요약봇'이다.\n"
            "[지식수준] 입문: 쉬운 비유.\n"
            "[말투] 간결_요약형: 핵심만 압축."
        ),
        "user": "데이터베이스 인덱스를 쉽게 설명해줘.",
    },
]


def ask(model: str, system: str, user: str, base_url: str) -> Optional[str]:
    try:
        import requests
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "stream": False,
            "options": {"temperature": 0.4, "num_predict": 400},
        }
        resp = requests.post(f"{base_url}/api/chat", json=payload, timeout=90)
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")
    except Exception as e:
        return f"[오류] {e}"


def main():
    parser = argparse.ArgumentParser(description="base vs fine-tuned 비교")
    parser.add_argument("--base",      default="qwen2.5:14b",           help="base 모델명")
    parser.add_argument("--finetuned", default="studybridge-qwen25-14b", help="fine-tuned 모델명")
    parser.add_argument("--base-url",  default="http://localhost:11434", help="Ollama base URL")
    parser.add_argument("--output",    default="./eval/comparison_result.jsonl", help="결과 저장 경로")
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n[비교 시작]")
    print(f"  base:      {args.base}")
    print(f"  finetuned: {args.finetuned}")
    print(f"  결과 저장: {output_path}")
    print("=" * 60)

    results = []
    for i, prompt in enumerate(COMPARE_PROMPTS, 1):
        print(f"\n[{i}/{len(COMPARE_PROMPTS)}] 질문: {prompt['user']}")

        base_ans      = ask(args.base,      prompt["system"], prompt["user"], args.base_url)
        finetuned_ans = ask(args.finetuned, prompt["system"], prompt["user"], args.base_url)

        print(f"\n  [BASE — {args.base}]\n  {(base_ans or '')[:200].replace(chr(10), ' ')}...")
        print(f"\n  [FINETUNED — {args.finetuned}]\n  {(finetuned_ans or '')[:200].replace(chr(10), ' ')}...")

        record = {
            "timestamp": datetime.now().isoformat(),
            "base_model": args.base,
            "finetuned_model": args.finetuned,
            "system": prompt["system"],
            "user": prompt["user"],
            "base_answer": base_ans,
            "finetuned_answer": finetuned_ans,
        }
        results.append(record)

    with open(output_path, "w", encoding="utf-8") as f:
        for rec in results:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\n[완료] {len(results)}건 저장: {output_path}")
    print("\n[주의]")
    print("- 위 출력은 키워드/길이 기준이 아닌 사람이 직접 읽고 판단해야 합니다.")
    print("- 학습 완료 = 품질 개선 보장이 아닙니다.")
    print("- base가 더 나으면 adapter를 쓰지 않아도 됩니다.")


if __name__ == "__main__":
    main()
