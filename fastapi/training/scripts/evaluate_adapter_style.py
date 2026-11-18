#!/usr/bin/env python3
"""
adapter 스타일 평가 스크립트.

Ollama API를 통해 StudyBridge 스타일 프롬프트를 보내고
성격별/지식수준별 응답이 의도대로 나오는지 정성 평가한다.

실행 예시:
  python evaluate_adapter_style.py --model qwen2.5:14b
  python evaluate_adapter_style.py --model studybridge-qwen25-14b  # 커스텀 모델
"""
import argparse
import json
import sys
from typing import Optional

EVAL_CASES = [
    {
        "name": "친절_설명형 × 입문",
        "system": (
            "너는 StudyBridge 에이전트 '설명봇'이다.\n"
            "[지식수준] 입문: 쉬운 비유와 핵심 개념만.\n"
            "[말투] 친절_설명형: 따뜻하고 친근하게."
        ),
        "user": "운영체제가 뭐예요?",
        "checks": ["쉽게", "비유", "예를 들"],
    },
    {
        "name": "비판적_분析형 × 학사",
        "system": (
            "너는 StudyBridge 에이전트 '분석봇'이다.\n"
            "[지식수준] 학사: 개념 정의와 작동 원리.\n"
            "[말투] 비판적_분析형: 지적 후 개선 방향 제시."
        ),
        "user": "상속이 항상 좋은 OOP 설계인가요?",
        "checks": ["문제", "틀려", "대신", "조합"],
    },
    {
        "name": "간결_요약형 × 전문가",
        "system": (
            "너는 StudyBridge 에이전트 '요약봇'이다.\n"
            "[지식수준] 전문가: 실무, 운영, 리스크.\n"
            "[말투] 간결_요약형: 핵심만 압축."
        ),
        "user": "MSA와 모놀리식 아키텍처 선택 기준을 알려줘.",
        "checks": ["원인", "운영", "리스크", "결론"],
    },
]


def call_ollama(model: str, system: str, user: str, base_url: str) -> Optional[str]:
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
        resp = requests.post(f"{base_url}/api/chat", json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")
    except Exception as e:
        print(f"  [오류] Ollama 호출 실패: {e}")
        return None


def evaluate(model: str, base_url: str) -> None:
    print(f"\n[스타일 평가] 모델: {model}")
    print(f"  Ollama URL: {base_url}")
    print("=" * 60)

    results = []
    for case in EVAL_CASES:
        print(f"\n케이스: {case['name']}")
        print(f"  질문: {case['user']}")

        answer = call_ollama(model, case["system"], case["user"], base_url)
        if answer is None:
            print("  결과: [응답 없음]")
            results.append({"case": case["name"], "passed": False, "answer": ""})
            continue

        print(f"  응답 ({len(answer)}자):\n    {answer[:200].replace(chr(10), ' ')}...")

        # 간단 키워드 체크 (정성 평가 보조)
        lowered = answer.lower()
        hits = [kw for kw in case["checks"] if kw in lowered]
        passed = len(hits) >= max(1, len(case["checks"]) // 2)

        print(f"  키워드 체크: {hits} / {case['checks']} → {'✓' if passed else '✗'}")
        results.append({"case": case["name"], "passed": passed, "answer": answer})

    print("\n" + "=" * 60)
    passed_count = sum(1 for r in results if r["passed"])
    print(f"결과: {passed_count}/{len(results)} 통과")
    print("\n[주의] 이 평가는 키워드 기반 보조 지표이며, 정성 평가를 대체하지 않습니다.")
    print("실제 품질 판단은 사람이 직접 응답을 읽고 판단해야 합니다.")


def main():
    parser = argparse.ArgumentParser(description="adapter 스타일 평가")
    parser.add_argument("--model", default="qwen2.5:14b", help="평가할 Ollama 모델명")
    parser.add_argument("--base-url", default="http://localhost:11434", help="Ollama base URL")
    args = parser.parse_args()

    evaluate(args.model, args.base_url)


if __name__ == "__main__":
    main()
