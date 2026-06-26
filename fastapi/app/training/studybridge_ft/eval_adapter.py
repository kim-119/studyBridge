"""학습된 QLoRA 어댑터를 실제 로드해 eval_studybridge.run_eval(responder)를 구동.

eval_studybridge.py는 responder 주입형이라 CLI 러너가 없다. 이 모듈이 그 어댑터다.
실행:  cd ~/capstoneLLM/fastapi && python -m app.training.studybridge_ft.eval_adapter
"""
import argparse
import os
from pathlib import Path

import yaml

from . import paths
from .eval_studybridge import run_eval


def build_responder(base_model: str, adapter_dir: Path, max_seq_length: int):
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    from peft import PeftModel
    from .train_qlora import build_bnb_config

    tok = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        base_model, quantization_config=build_bnb_config(),
        device_map="auto", trust_remote_code=True)
    model = PeftModel.from_pretrained(model, str(adapter_dir))
    model.eval()

    def responder(messages):
        prompt = tok.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        inputs = tok(prompt, return_tensors="pt", truncation=True,
                     max_length=max_seq_length).to(model.device)
        with torch.no_grad():
            out = model.generate(
                **inputs, max_new_tokens=256, do_sample=False,
                pad_token_id=tok.pad_token_id)
        gen = out[0][inputs["input_ids"].shape[1]:]
        return tok.decode(gen, skip_special_tokens=True).strip()

    return responder


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--adapter", default=None, help="학습 산출(LoRA) 디렉토리")
    a = ap.parse_args()

    cfg_path = Path(a.config) if a.config else paths.PKG_DIR / "config.example.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    tc = cfg["train"]

    adapter_dir = Path(a.adapter) if a.adapter else (
        paths.SUBDIRS["outputs"] / "qwen14b-studybridge-lora")
    if not (adapter_dir / "adapter_config.json").exists():
        raise SystemExit(f"FAIL: LoRA 어댑터를 찾을 수 없습니다: {adapter_dir}")

    print(f"[eval] base={tc['base_model']} adapter={adapter_dir}")
    responder = build_responder(tc["base_model"], adapter_dir, int(tc["max_seq_length"]))
    result = run_eval(responder, out_dir=paths.SUBDIRS["outputs"])
    print(f"[eval] PASSED {result['passed']}/10")
    for r in result["results"]:
        print(f"  [{'x' if r['ok'] else ' '}] {r['id']}. {r['name']}")


if __name__ == "__main__":
    main()
