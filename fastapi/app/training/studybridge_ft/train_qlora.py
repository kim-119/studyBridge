"""Qwen3-14B QLoRA. fp32 embedding upcast 생략(16GB 운영 공존). TRL 1.6 API."""
import argparse
import re
import yaml
from pathlib import Path
from . import paths


def find_last_checkpoint(output_dir: str):
    """output_dir 안 checkpoint-* 중 step 숫자가 가장 큰 경로. 없으면 None."""
    output_path = Path(output_dir)
    if not output_path.exists():
        return None
    checkpoints = []
    for path in output_path.glob("checkpoint-*"):
        if path.is_dir():
            match = re.search(r"checkpoint-(\d+)$", path.name)
            if match:
                checkpoints.append((int(match.group(1)), str(path)))
    if not checkpoints:
        return None
    checkpoints.sort(key=lambda x: x[0])
    return checkpoints[-1][1]


def build_bnb_config():
    import torch
    from transformers import BitsAndBytesConfig
    return BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)


def build_lora_config(cfg):
    from peft import LoraConfig
    l = cfg["lora"]
    return LoraConfig(r=l["r"], lora_alpha=l["alpha"], lora_dropout=l["dropout"],
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"], bias="none",
        task_type="CAUSAL_LM")


def prepare_model_memory_efficient(model):
    for p in model.parameters():
        p.requires_grad_(False)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    return model


def train(cfg, train_file, valid_file, output_dir, overrides=None):
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    from peft import get_peft_model
    from datasets import load_dataset
    from trl import SFTConfig, SFTTrainer
    ov = overrides or {}
    tc = cfg["train"]
    model_name = tc["base_model"]
    paths.assert_outside_repo(output_dir)
    tok = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(model_name,
        quantization_config=build_bnb_config(), device_map="auto", trust_remote_code=True)
    model = prepare_model_memory_efficient(model)
    model = get_peft_model(model, build_lora_config(tc))
    model.print_trainable_parameters()
    ds = load_dataset("json", data_files={"train": str(train_file), "validation": str(valid_file)})

    def fmt(s):
        # qwen3: thinking 비활성
        return {"text": tok.apply_chat_template(s["messages"], tokenize=False,
                add_generation_prompt=False, enable_thinking=False)}

    ds = ds.map(fmt)

    # safe55 운용값: 인자(overrides)로 받되 미지정 시 config/보수적 기본값.
    max_steps = int(ov.get("max_steps", -1))            # -1=full, >0=dry-run/제한
    save_steps = int(ov.get("save_steps", 200))         # plan: 200 또는 500
    save_total_limit = int(ov.get("save_total_limit", 10))
    eval_steps = int(ov.get("eval_steps", 1000))
    epochs = float(ov.get("num_train_epochs", tc["num_train_epochs"]))
    grad_accum = int(ov.get("gradient_accumulation_steps", tc["gradient_accumulation_steps"]))
    warmup_ratio = float(ov.get("warmup_ratio", 0.03))
    max_grad_norm = float(ov.get("max_grad_norm", 0.3))
    # dry-run(짧은 max_steps)인데 save_steps가 그보다 크면 체크포인트가 안 생긴다 → 자동 축소.
    if max_steps > 0 and save_steps >= max_steps:
        save_steps = max(10, max_steps // 2)

    args = SFTConfig(output_dir=str(output_dir), num_train_epochs=epochs, max_steps=max_steps,
        per_device_train_batch_size=tc["per_device_train_batch_size"],
        # eval 기본 배치(8)는 logits.float() 업캐스트로 8x1024xvocab fp32(~5GiB) 단일할당 → 16GB OOM.
        # 학습 배치(1)와 동일하게 1로 낮춰 spike를 ~0.6GiB로 억제(prediction_loss_only로 누적도 없음).
        per_device_eval_batch_size=1,
        eval_accumulation_steps=1,
        gradient_accumulation_steps=grad_accum,
        learning_rate=float(tc["learning_rate"]), bf16=torch.cuda.is_bf16_supported(),
        optim="paged_adamw_8bit", max_grad_norm=max_grad_norm,
        logging_steps=10, save_strategy="steps", save_steps=save_steps,
        save_total_limit=save_total_limit,
        eval_strategy="steps", eval_steps=eval_steps, report_to="none",
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        warmup_ratio=warmup_ratio, lr_scheduler_type="cosine",
        dataset_text_field="text", max_length=tc["max_seq_length"])
    trainer = SFTTrainer(model=model, args=args,
        train_dataset=ds["train"], eval_dataset=ds["validation"])

    # 중단 복구: output_dir 안 마지막 checkpoint 자동 탐색 → 있으면 resume.
    last_checkpoint = find_last_checkpoint(str(output_dir))
    print(f"[INFO] output_dir = {output_dir}")
    print(f"[INFO] last_checkpoint = {last_checkpoint}")
    if last_checkpoint:
        print(f"[RESUME] Resuming from checkpoint: {last_checkpoint}")
        trainer.train(resume_from_checkpoint=last_checkpoint)
    else:
        print("[START] No checkpoint found. Starting from scratch.")
        trainer.train()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(output_dir))
    tok.save_pretrained(str(output_dir))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--output", default=None)
    # 데이터 파일 직접 지정(미지정 시 ~/studybridge-ft/data/{train,valid}.jsonl). 원본 무수정.
    ap.add_argument("--train_file", default=None)
    ap.add_argument("--valid_file", default=None)
    # safe55 운용/복구용 override (미지정 시 train() 내부 기본값).
    ap.add_argument("--max_steps", type=int, default=None, help="dry-run/제한 학습용. -1 또는 미지정=full")
    ap.add_argument("--save_steps", type=int, default=None)
    ap.add_argument("--save_total_limit", type=int, default=None)
    ap.add_argument("--eval_steps", type=int, default=None)
    ap.add_argument("--num_train_epochs", type=float, default=None)
    ap.add_argument("--gradient_accumulation_steps", type=int, default=None)
    ap.add_argument("--warmup_ratio", type=float, default=None)
    ap.add_argument("--max_grad_norm", type=float, default=None)
    a = ap.parse_args()
    cfg = yaml.safe_load((Path(a.config) if a.config else paths.PKG_DIR / "config.example.yaml")
                         .read_text(encoding="utf-8"))
    out = a.output or (paths.SUBDIRS["outputs"] / "qwen14b-studybridge-lora")
    overrides = {k: v for k, v in {
        "max_steps": a.max_steps, "save_steps": a.save_steps,
        "save_total_limit": a.save_total_limit, "eval_steps": a.eval_steps,
        "num_train_epochs": a.num_train_epochs,
        "gradient_accumulation_steps": a.gradient_accumulation_steps,
        "warmup_ratio": a.warmup_ratio, "max_grad_norm": a.max_grad_norm,
    }.items() if v is not None}
    train_file = Path(a.train_file) if a.train_file else paths.SUBDIRS["data"] / "train.jsonl"
    valid_file = Path(a.valid_file) if a.valid_file else paths.SUBDIRS["data"] / "valid.jsonl"
    print(f"[INFO] train_file = {train_file}")
    print(f"[INFO] valid_file = {valid_file}")
    train(cfg, train_file, valid_file, out, overrides=overrides)


if __name__ == "__main__":
    main()
