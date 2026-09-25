#!/usr/bin/env python3
"""
evaluate_qlora.py
학습된 QLoRA 어댑터를 Qwen baseline과 비교 평가한다.

실행 예시:
  python app/training/evaluate_qlora.py \
    --model_dir app/models/studybridge-qwen2.5-14b-qlora \
    --eval_file app/dataset/eval/qwen_baseline_eval.jsonl \
    --output app/dataset/reports/qlora_eval_results.jsonl \
    --report app/dataset/reports/qlora_eval_report.md
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


NOT_READY_MESSAGE = """\
현재 데이터셋은 QLoRA 학습 조건을 충족하지 못했습니다.
학습은 실행하지 않았습니다.
먼저 reviewed/approved 샘플 300개 이상, 실제 PDF RAG 데이터, 사람 검수 validation/test set, \
Qwen baseline evaluation set, validate_dataset_jsonl.py 통과가 필요합니다.
"""


def check_prerequisites(args) -> tuple[bool, list[str]]:
    failures = []
    model_dir = Path(args.model_dir)
    eval_path = Path(args.eval_file)

    if not model_dir.exists():
        failures.append(f"모델 디렉토리 없음: {args.model_dir}")
    if not eval_path.exists():
        failures.append(f"eval 파일 없음: {args.eval_file}")
    else:
        eval_samples = []
        for line in eval_path.read_text(encoding="utf-8").strip().splitlines():
            if line.strip():
                try:
                    eval_samples.append(json.loads(line))
                except Exception:
                    pass
        baseline_missing = sum(1 for s in eval_samples if s.get("baseline_missing"))
        if baseline_missing > 0:
            failures.append(
                f"baseline_missing=true 항목 {baseline_missing}개 — Qwen 추론 결과 없음"
            )
        if len(eval_samples) < 50:
            failures.append(f"eval 항목 수 부족: {len(eval_samples)}개 (50개 이상 필요)")

    try:
        import torch
        if not torch.cuda.is_available():
            failures.append("CUDA 사용 불가")
    except ImportError:
        failures.append("torch 미설치")

    return len(failures) == 0, failures


def evaluate(args) -> None:
    try:
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM
        from peft import PeftModel
    except ImportError as e:
        print(f"[ERROR] 필수 패키지 미설치: {e}", file=sys.stderr)
        sys.exit(1)

    eval_path = Path(args.eval_file)
    eval_samples = []
    for line in eval_path.read_text(encoding="utf-8").strip().splitlines():
        if line.strip():
            try:
                eval_samples.append(json.loads(line))
            except Exception:
                pass

    print(f"[INFO] 모델 로드: {args.model_dir}")
    base_model_name = "Qwen/Qwen2.5-14B-Instruct"
    tokenizer = AutoTokenizer.from_pretrained(args.model_dir, trust_remote_code=True)

    base_model = AutoModelForCausalLM.from_pretrained(
        base_model_name, device_map="auto", trust_remote_code=True
    )
    model = PeftModel.from_pretrained(base_model, args.model_dir)
    model.eval()

    results = []
    for item in eval_samples:
        question = item.get("question", "")
        context = item.get("context", "")
        messages = [
            {"role": "system", "content": context},
            {"role": "user", "content": question},
        ]
        input_text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = tokenizer(input_text, return_tensors="pt").to(model.device)

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=512,
                temperature=0.1,
                do_sample=False,
            )
        generated = tokenizer.decode(
            outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True
        )

        result = {
            "id": item.get("id"),
            "source_type": item.get("source_type"),
            "question": question,
            "baseline_answer": item.get("baseline_answer", ""),
            "qlora_answer": generated,
            "rubric": item.get("rubric", {}),
            "human_eval_required": True,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
        results.append(result)
        print(f"[INFO] 평가 완료: {item.get('id')}")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[INFO] 평가 결과 저장: {args.output} ({len(results)}개)")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    report_lines = [
        "# QLoRA 평가 리포트\n\n",
        f"생성일시: {now_str}\n\n",
        f"- 평가 모델: `{args.model_dir}`\n",
        f"- eval 항목 수: {len(eval_samples)}\n",
        f"- 평가 완료: {len(results)}개\n",
        "\n## 주의\n\n",
        "- `qlora_answer`는 QLoRA 모델이 생성한 답변입니다.\n",
        "- `human_eval_required=true`: 루브릭 기준 사람 평가가 필요합니다.\n",
    ]

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("".join(report_lines), encoding="utf-8")
    print(f"[INFO] 리포트 저장: {args.report}")


def main():
    parser = argparse.ArgumentParser(description="QLoRA 평가")
    parser.add_argument("--model_dir", required=True)
    parser.add_argument("--eval_file", default="app/dataset/eval/qwen_baseline_eval.jsonl")
    parser.add_argument("--output", default="app/dataset/reports/qlora_eval_results.jsonl")
    parser.add_argument("--report", default="app/dataset/reports/qlora_eval_report.md")
    args = parser.parse_args()

    ready, failures = check_prerequisites(args)
    if not ready:
        print(NOT_READY_MESSAGE, file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        sys.exit(1)

    evaluate(args)


if __name__ == "__main__":
    main()
