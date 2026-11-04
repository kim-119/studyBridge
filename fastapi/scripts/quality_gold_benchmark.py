"""사람 검수 gold 벤치마크 실행기(quality-gold.v1).

    cd fastapi && python -m scripts.quality_gold_benchmark --items <gold.jsonl> --out /tmp/gold_report.json

- 결정적 평가기만 쓴다(기본). --judge 는 AI_QUALITY_JUDGE=ollama 일 때 같은 운영 모델을 쓰므로 GPU 승인 후에만.
- 보고서에는 문항 본문을 넣지 않는다(itemId/영역/점수/코드만).
- HUMAN_REVIEWED 문항이 부족하면 measurementStatus=PREPARED_NOT_MEASURED — '측정 완료'로 보고하지 않는다.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--judge", action="store_true", help="judge 사용(운영 Ollama 사용 — 승인 필요)")
    a = ap.parse_args()
    from app.quality_gate.evaluator import clear_cache, evaluate
    from app.quality_gate.gold_benchmark import load_items, run_benchmark
    judge = None
    if a.judge:
        if (os.getenv("AI_QUALITY_JUDGE") or "").lower() != "ollama":
            print("--judge 는 AI_QUALITY_JUDGE=ollama 필요", file=sys.stderr)
            return 2
        from app.quality_gate.judge import get_judge
        judge = get_judge()
    items = load_items(Path(a.items))
    clear_cache()
    fam = os.getenv("AI_QUALITY_JUDGE_MODEL") or os.getenv("OLLAMA_MODEL") or ("qwen3" if judge else None)
    rep = asyncio.run(run_benchmark(items, lambda i: evaluate(i, judge=judge), judge_enabled=judge is not None,
                                    judge_family=(fam or "").split(":")[0] or None))
    Path(a.out).write_text(json.dumps(rep.to_dict(), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"measurementStatus": rep.measurementStatus, "reasons": rep.reasons,
                      "FAR": rep.overall["FAR"], "FRR": rep.overall["FRR"], "basis": rep.overall["basis"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
