#!/usr/bin/env python3
"""
train_qlora.py
QLoRA 파인튜닝 스크립트 (Qwen2.5-14B-Instruct 기반).

학습 전 반드시 readiness gate 통과가 필요하다.
현재 데이터 상태에서는 학습을 시작하지 않는다.

실행 예시:
  python app/training/train_qlora.py \
    --model_name Qwen/Qwen2.5-14B-Instruct \
    --train_file app/dataset/final/train.jsonl \
    --validation_file app/dataset/final/validation.jsonl \
    --output_dir app/models/studybridge-qwen2.5-14b-qlora \
    --max_seq_length 2048 \
    --num_train_epochs 1 \
    --per_device_train_batch_size 1 \
    --gradient_accumulation_steps 8 \
    --learning_rate 2e-4 \
    --lora_r 16 \
    --lora_alpha 32 \
    --lora_dropout 0.05 \
    --load_in_4bit true
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

NOT_READY_MESSAGE = """\
현재 데이터셋은 QLoRA 학습 조건을 충족하지 못했습니다.
학습은 실행하지 않았습니다.
먼저 reviewed/approved 샘플 300개 이상, 실제 PDF RAG 데이터, 사람 검수 validation/test set, \
Qwen baseline evaluation set, validate_dataset_jsonl.py 통과가 필요합니다.
"""

MIN_REVIEWED_APPROVED = 300


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    samples = []
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        if line.strip():
            try:
                samples.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return samples


def pre_flight_check(args) -> tuple[bool, list[str]]:
    failures = []

    train_path = Path(args.train_file)
    val_path = Path(args.validation_file)
    eval_path = Path("app/dataset/eval/qwen_baseline_eval.jsonl")
    test_path = train_path.parent / "test.jsonl"

    if not train_path.exists():
        failures.append(f"train.jsonl 없음: {args.train_file}")
    if not val_path.exists():
        failures.append(f"validation.jsonl 없음: {args.validation_file}")
    if not test_path.exists() or test_path.stat().st_size == 0:
        failures.append(f"test.jsonl 없음 또는 비어 있음: {test_path}")
    if not eval_path.exists():
        failures.append(f"qwen_baseline_eval.jsonl 없음: {eval_path}")

    train_samples = load_jsonl(train_path) if train_path.exists() else []
    reviewed_approved = sum(
        1 for s in train_samples
        if s.get("metadata", {}).get("quality_status") in {"reviewed", "approved"}
    )
    if reviewed_approved < MIN_REVIEWED_APPROVED:
        failures.append(
            f"reviewed/approved 샘플 {reviewed_approved}개 ({MIN_REVIEWED_APPROVED}개 이상 필요)"
        )

    eval_samples = load_jsonl(eval_path) if eval_path.exists() else []
    baseline_missing = sum(1 for s in eval_samples if s.get("baseline_missing"))
    if baseline_missing > 0:
        failures.append(f"baseline_missing=true인 eval 항목 {baseline_missing}개")

    try:
        import torch
        if not torch.cuda.is_available():
            failures.append("CUDA 사용 불가 — GPU 환경 필요")
    except ImportError:
        failures.append("torch 미설치")

    if not args.model_name:
        failures.append("model_name 없음")

    return len(failures) == 0, failures


def train(args) -> None:
    try:
        import torch
        from transformers import (
            AutoTokenizer,
            AutoModelForCausalLM,
            TrainingArguments,
            BitsAndBytesConfig,
        )
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from datasets import load_dataset
        from trl import SFTTrainer
    except ImportError as e:
        print(f"[ERROR] 필수 패키지 미설치: {e}", file=sys.stderr)
        print("pip install transformers datasets accelerate peft bitsandbytes trl")
        sys.exit(1)

    print(f"[INFO] 모델 로드: {args.model_name}")

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )

    tokenizer = AutoTokenizer.from_pretrained(args.model_name, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        args.model_name,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

    lora_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    dataset = load_dataset("json", data_files={
        "train": args.train_file,
        "validation": args.validation_file,
    })

    def format_sample(sample):
        messages = sample.get("messages", [])
        text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=False
        )
        return {"text": text}

    dataset = dataset.map(format_sample)

    use_bf16 = torch.cuda.is_bf16_supported()
    log_dir = Path("app/logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=args.output_dir,
        num_train_epochs=args.num_train_epochs,
        per_device_train_batch_size=args.per_device_train_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        bf16=use_bf16,
        fp16=not use_bf16,
        logging_dir=str(log_dir),
        logging_steps=10,
        save_strategy="epoch",
        evaluation_strategy="epoch",
        report_to="none",
        gradient_checkpointing=True,
        warmup_ratio=0.05,
        lr_scheduler_type="cosine",
    )

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset["train"],
        eval_dataset=dataset["validation"],
        dataset_text_field="text",
        max_seq_length=args.max_seq_length,
        tokenizer=tokenizer,
    )

    print("[INFO] 학습 시작")
    trainer.train()

    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(output_path))
    tokenizer.save_pretrained(str(output_path))
    print(f"[INFO] 모델 저장 완료: {args.output_dir}")


def main():
    parser = argparse.ArgumentParser(description="QLoRA 파인튜닝 (readiness gate 포함)")
    parser.add_argument("--model_name", default="Qwen/Qwen2.5-14B-Instruct")
    parser.add_argument("--train_file", default="app/dataset/final/train.jsonl")
    parser.add_argument("--validation_file", default="app/dataset/final/validation.jsonl")
    parser.add_argument("--output_dir", default="app/models/studybridge-qwen2.5-14b-qlora")
    parser.add_argument("--max_seq_length", type=int, default=2048)
    parser.add_argument("--num_train_epochs", type=int, default=1)
    parser.add_argument("--per_device_train_batch_size", type=int, default=1)
    parser.add_argument("--gradient_accumulation_steps", type=int, default=8)
    parser.add_argument("--learning_rate", type=float, default=2e-4)
    parser.add_argument("--lora_r", type=int, default=16)
    parser.add_argument("--lora_alpha", type=int, default=32)
    parser.add_argument("--lora_dropout", type=float, default=0.05)
    parser.add_argument("--load_in_4bit", default="true")
    parser.add_argument("--skip_readiness_check", action="store_true",
                        help="절대 사용하지 마십시오 (테스트 전용)")
    args = parser.parse_args()

    print("[INFO] Readiness gate 검사 중...")

    if not args.skip_readiness_check:
        ready, failures = pre_flight_check(args)
        if not ready:
            print(NOT_READY_MESSAGE, file=sys.stderr)
            print("[INFO] 실패 사유:", file=sys.stderr)
            for f in failures:
                print(f"  - {f}", file=sys.stderr)
            sys.exit(1)
    else:
        print("[WARN] skip_readiness_check 사용됨 — 운영 환경에서 절대 사용 금지")

    print("[INFO] Readiness gate 통과 — 학습을 시작합니다.")
    train(args)


if __name__ == "__main__":
    main()
