"""QLoRA 툴체인 스모크(학습 아님): 데이터셋 → Qwen3 채팅 템플릿/라벨 마스킹(CPU) + 0.5B NF4 몇 스텝(GPU, 선택).

- stage 1 (CPU): export_service 로 합성 데이터셋을 만들고 Qwen3-14B 토크나이저로 템플릿 적용·assistant 토큰만 학습 라벨.
- stage 2 (--gpu): Qwen2.5-0.5B-Instruct(로컬 캐시) NF4+double quant, LoRA r=8, gradient checkpointing, ≤6 step.
  운영 Ollama 에 모델이 로드돼 있거나 GPU 여유가 14GiB 미만이면 시작하지 않는다. 메모리 상한 per-process fraction.
  14B 학습이 아니며 운영 품질 개선을 의미하지 않는다.

  cd fastapi && .venv/bin/python -m scripts.qlora_toolchain_smoke --workdir /tmp/x [--gpu]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

Q14 = Path.home() / ".cache/huggingface/hub/models--Qwen--Qwen3-14B/snapshots/40c069824f4251a91eefaf281ebe4c544efd3e18"
Q05 = next((Path.home() / ".cache/huggingface/hub/models--Qwen--Qwen2.5-0.5B-Instruct/snapshots").glob("*"), None)


async def make_dataset(workdir: Path) -> Path:
    os.environ["AI_TRAINING_DATASET_DIR"] = str(workdir / "datasets")
    os.environ["AI_AUDIT_LOG_PATH"] = str(workdir / "audit.jsonl")
    from app.training_pipeline import candidate_service as cs
    from app.training_pipeline.export_service import export_dataset
    from app.training_pipeline.repository import InMemoryTrainingRepository
    from tests.lq_helpers import make_sample
    repo = InMemoryTrainingRepository()
    rv = cs.Actor("smoke-reviewer", "training_reviewer", "req-smoke-0001")
    for i in range(28):
        r = await cs.collect_sample(repo, make_sample(i, user=f"pk_smoke_{i % 7:011d}"))
        await cs.review(repo, r.candidate_id, decision="VERIFY", actor=rv)
    res = await export_dataset(repo, actor="smoke", request_id="req-smoke-exp1")
    assert res.status == "completed", res
    return workdir / "datasets" / res.dataset_id


def tokenize(tok, messages, max_len):
    prompt = tok.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True, enable_thinking=False)
    full = tok.apply_chat_template(messages, tokenize=False, enable_thinking=False)
    p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
    f_ids = tok(full, add_special_tokens=False)["input_ids"][:max_len]
    labels = [-100] * min(len(p_ids), len(f_ids)) + f_ids[len(p_ids):]
    return f_ids, labels[:len(f_ids)], f_ids[:len(p_ids)] == p_ids


def stage1(ds_dir: Path) -> dict:
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(str(Q14), local_files_only=True)
    out = {}
    for split in ("train", "validation", "test"):
        rows = [json.loads(l) for l in (ds_dir / f"{split}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        lens, lab, prefix_ok = [], [], 0
        for r in rows:
            ids, labels, ok = tokenize(tok, r["messages"], 1024)
            lens.append(len(ids))
            lab.append(sum(1 for x in labels if x != -100))
            prefix_ok += int(ok)
        out[split] = {"n": len(rows), "maxTokens": max(lens) if lens else 0, "meanTokens": round(sum(lens) / max(1, len(lens)), 1),
                      "assistantLabelTokensMean": round(sum(lab) / max(1, len(lab)), 1), "promptPrefixConsistent": prefix_ok}
    manifest = json.loads((ds_dir / "manifest.json").read_text(encoding="utf-8"))
    out["manifestSplits"] = {k: v["count"] for k, v in manifest["splits"].items()}
    out["thinkTagsInTarget"] = any("<think>" in l for l in (ds_dir / "train.jsonl").read_text(encoding="utf-8").splitlines())
    return out


def stage2(ds_dir: Path, workdir: Path) -> dict:
    import httpx
    import torch
    for url in ("http://127.0.0.1:11434", "http://127.0.0.1:11435"):
        if httpx.get(f"{url}/api/ps", timeout=3).json().get("models"):
            return {"skipped": f"PRODUCTION_MODEL_LOADED:{url}"}
    free, total = torch.cuda.mem_get_info()
    if free < 14 * 1024 ** 3:
        return {"skipped": f"FREE_VRAM_{free // 2**20}MiB"}
    torch.cuda.set_per_process_memory_fraction(0.15)       # ≈2.4GiB 상한
    from peft import LoraConfig, PeftModel, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    t0 = time.time()
    tok = AutoTokenizer.from_pretrained(str(Q05), local_files_only=True)
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                             bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(str(Q05), quantization_config=bnb, local_files_only=True,
                                                 device_map={"": 0}, dtype=torch.bfloat16)
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model = get_peft_model(model, LoraConfig(r=8, lora_alpha=16, lora_dropout=0.05, task_type="CAUSAL_LM",
                                             target_modules=["q_proj", "k_proj", "v_proj", "o_proj"]))
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    rows = [json.loads(l) for l in (ds_dir / "train.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()][:6]
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=2e-4)
    losses = []
    model.train()
    for r in rows:
        ids, labels, _ = tokenize(tok, r["messages"], 256)
        x = torch.tensor([ids], device="cuda")
        y = torch.tensor([labels], device="cuda")
        loss = model(input_ids=x, labels=y).loss
        loss.backward()
        opt.step()
        opt.zero_grad()
        losses.append(round(float(loss.detach()), 4))
    peak = torch.cuda.max_memory_allocated() / 2 ** 20
    ad = workdir / "adapter-smoke"
    model.save_pretrained(str(ad))
    del model, opt
    torch.cuda.empty_cache()
    base = AutoModelForCausalLM.from_pretrained(str(Q05), quantization_config=bnb, local_files_only=True, device_map={"": 0})
    reloaded = PeftModel.from_pretrained(base, str(ad))
    reloaded.eval()
    with torch.no_grad():
        g = reloaded.generate(**tok("TCP 는", return_tensors="pt").to("cuda"), max_new_tokens=4, do_sample=False)
    res = {"model": "Qwen/Qwen2.5-0.5B-Instruct (toolchain smoke only)", "steps": len(losses), "losses": losses,
           "trainableParams": trainable, "peakAllocatedMiB": round(peak, 1), "seconds": round(time.time() - t0, 1),
           "adapterFiles": sorted(p.name for p in ad.iterdir()), "reloadGenerateTokens": int(g.shape[1])}
    del reloaded, base
    torch.cuda.empty_cache()
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--gpu", action="store_true")
    a = ap.parse_args()
    wd = Path(a.workdir)
    wd.mkdir(parents=True, exist_ok=True)
    ds = asyncio.run(make_dataset(wd))
    out = {"dataset": ds.name, "stage1_cpu": stage1(ds)}
    if a.gpu:
        out["stage2_gpu"] = stage2(ds, wd)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
