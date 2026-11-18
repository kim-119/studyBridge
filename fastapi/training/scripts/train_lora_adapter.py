#!/usr/bin/env python3
"""
Qwen2.5 14B QLoRA adapter 학습 스크립트 (선택적 보조 실험).

중요:
- 이 스크립트는 주력이 아니라 보조 실험용 향미제 수준이다.
- 실제 시연 품질은 14B Ollama 추론 + prompt/controller + RAG/GPT로 만든다.
- 이 스크립트 실패 = 전체 구조 실패가 아니다.
- 서버컴에서 bitsandbytes/CUDA 호환을 확인한 뒤 실행한다.
- 14B full fine-tuning(모든 가중치 학습)은 하지 않는다.
- QLoRA: 4-bit 양자화된 base model + LoRA adapter 학습.

실행 예시:
  # 파이프라인 동작 확인 (smoke)
  python train_lora_adapter.py --config ../configs/qwen25_14b_qlora_optional.yaml --smoke-test

  # 실제 학습 (pilot)
  python train_lora_adapter.py --config ../configs/qwen25_14b_qlora_optional.yaml

필요 패키지 (requirements-finetune.txt):
  pip install -r requirements-finetune.txt

주의:
- 실제 학습을 실행하지 않은 상태에서 학습 완료라고 말하지 않는다.
- 학습 완료 여부와 효과는 compare_base_vs_finetuned.py로 비교 후 판단한다.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


def load_yaml_config(config_path: Path) -> dict:
    try:
        import yaml
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except ImportError:
        print("[오류] pyyaml이 설치되지 않았습니다: pip install pyyaml")
        sys.exit(1)
    except FileNotFoundError:
        print(f"[오류] config 파일 없음: {config_path}")
        sys.exit(1)


def check_dependencies() -> bool:
    missing = []
    for pkg in ["torch", "transformers", "peft", "trl", "bitsandbytes", "datasets"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"[오류] 누락된 패키지: {missing}")
        print("설치: pip install -r requirements-finetune.txt")
        return False
    return True


def smoke_test(cfg: dict) -> None:
    """파이프라인 동작 확인 (실제 학습 없이)."""
    print("\n[SMOKE TEST] 파이프라인 구조 확인 중...")
    print(f"  모델: {cfg['model']['model_name_or_path']}")
    print(f"  LoRA r={cfg['lora']['r']}, alpha={cfg['lora']['lora_alpha']}")
    print(f"  max_seq_length={cfg['training']['max_seq_length']}")
    print(f"  batch_size={cfg['training']['per_device_train_batch_size']}")
    print(f"  output_dir={cfg['training']['output_dir']}")
    print("\n[SMOKE TEST] 의존성 확인:")
    ok = check_dependencies()
    if ok:
        print("  ✓ 모든 패키지 설치됨")
    else:
        print("  ✗ 누락 패키지 있음 (위 오류 참고)")
    print("\n[SMOKE TEST] 완료. 실제 학습은 --smoke-test 없이 실행하세요.")


def run_training(cfg: dict) -> None:
    """실제 QLoRA adapter 학습."""
    if not check_dependencies():
        sys.exit(1)

    import torch
    if not torch.cuda.is_available():
        print("[경고] CUDA를 사용할 수 없습니다. CPU 학습은 매우 느립니다.")

    from datasets import load_dataset
    from transformers import AutoTokenizer, AutoModelForCausalLM, TrainingArguments
    from peft import LoraConfig, get_peft_model, TaskType
    from trl import SFTTrainer
    import bitsandbytes as bnb
    from transformers import BitsAndBytesConfig

    model_path = cfg["model"]["model_name_or_path"]
    output_dir = cfg["training"]["output_dir"]
    dataset_path = cfg["training"]["dataset_path"]

    print(f"\n[학습 시작]")
    print(f"  모델: {model_path}")
    print(f"  데이터: {dataset_path}")
    print(f"  출력: {output_dir}")

    # 4-bit 양자화 설정
    bnb_cfg = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
    )

    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        quantization_config=bnb_cfg,
        device_map="auto",
        trust_remote_code=True,
    )

    lora_cfg = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=cfg["lora"]["r"],
        lora_alpha=cfg["lora"]["lora_alpha"],
        lora_dropout=cfg["lora"]["lora_dropout"],
        target_modules=cfg["lora"]["target_modules"],
        bias=cfg["lora"]["bias"],
    )
    model = get_peft_model(model, lora_cfg)
    model.print_trainable_parameters()

    dataset = load_dataset("json", data_files={"train": dataset_path}, split="train")

    train_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=cfg["training"]["num_train_epochs"],
        per_device_train_batch_size=cfg["training"]["per_device_train_batch_size"],
        gradient_accumulation_steps=cfg["training"]["gradient_accumulation_steps"],
        learning_rate=cfg["training"]["learning_rate"],
        lr_scheduler_type=cfg["training"]["lr_scheduler_type"],
        warmup_ratio=cfg["training"]["warmup_ratio"],
        bf16=cfg["training"]["bf16"],
        fp16=cfg["training"]["fp16"],
        gradient_checkpointing=cfg["training"]["gradient_checkpointing"],
        logging_steps=cfg["training"]["logging_steps"],
        save_steps=cfg["training"]["save_steps"],
        save_total_limit=cfg["training"]["save_total_limit"],
        report_to="none",
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        args=train_args,
        train_dataset=dataset,
        max_seq_length=cfg["training"]["max_seq_length"],
    )

    trainer.train()
    trainer.save_model(output_dir)
    tokenizer.save_pretrained(output_dir)
    print(f"\n[학습 완료] adapter 저장: {output_dir}")
    print("다음 단계: compare_base_vs_finetuned.py로 품질 비교 후 Ollama에 로드 여부 결정")


def main():
    parser = argparse.ArgumentParser(description="Qwen2.5 14B QLoRA adapter 학습 (optional)")
    parser.add_argument("--config", required=True, help="YAML config 경로")
    parser.add_argument("--smoke-test", action="store_true", help="파이프라인 구조 확인만 (실제 학습 없음)")
    args = parser.parse_args()

    cfg = load_yaml_config(Path(args.config))

    if args.smoke_test:
        smoke_test(cfg)
    else:
        print("[주의] 실제 QLoRA 학습을 시작합니다.")
        print("  - 서버컴 CUDA/bitsandbytes 호환 확인 완료 전제")
        print("  - 학습 완료 = 품질 개선 보장 아님. compare_base_vs_finetuned.py로 확인 필요")
        run_training(cfg)


if __name__ == "__main__":
    main()
