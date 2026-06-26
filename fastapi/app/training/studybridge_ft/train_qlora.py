"""Qwen3-14B QLoRA. fp32 embedding upcast 생략(16GB 운영 공존). TRL 1.6 API."""
import argparse
import yaml
from pathlib import Path
from . import paths


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


def train(cfg, train_file, valid_file, output_dir):
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    from peft import get_peft_model
    from datasets import load_dataset
    from trl import SFTConfig, SFTTrainer
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
    args = SFTConfig(output_dir=str(output_dir), num_train_epochs=tc["num_train_epochs"],
        per_device_train_batch_size=tc["per_device_train_batch_size"],
        # eval 기본 배치(8)는 logits.float() 업캐스트로 8x1024xvocab fp32(~5GiB) 단일할당 → 16GB OOM.
        # 학습 배치(1)와 동일하게 1로 낮춰 spike를 ~0.6GiB로 억제(prediction_loss_only로 누적도 없음).
        per_device_eval_batch_size=1,
        eval_accumulation_steps=1,
        gradient_accumulation_steps=tc["gradient_accumulation_steps"],
        learning_rate=float(tc["learning_rate"]), bf16=torch.cuda.is_bf16_supported(),
        logging_steps=10, save_strategy="epoch", eval_strategy="epoch", report_to="none",
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        warmup_ratio=0.05, lr_scheduler_type="cosine",
        dataset_text_field="text", max_length=tc["max_seq_length"])
    trainer = SFTTrainer(model=model, args=args,
        train_dataset=ds["train"], eval_dataset=ds["validation"])
    trainer.train()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(output_dir))
    tok.save_pretrained(str(output_dir))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--output", default=None)
    a = ap.parse_args()
    cfg = yaml.safe_load((Path(a.config) if a.config else paths.PKG_DIR / "config.example.yaml")
                         .read_text(encoding="utf-8"))
    out = a.output or (paths.SUBDIRS["outputs"] / "qwen14b-studybridge-lora")
    train(cfg, paths.SUBDIRS["data"] / "train.jsonl", paths.SUBDIRS["data"] / "valid.jsonl", out)


if __name__ == "__main__":
    main()
