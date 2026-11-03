"""오프라인 QLoRA 사전 점검(read-only). 학습을 시작하지 않는다.

- 운영 GGUF(Ollama qwen3:14b Q4_K_M)는 HF QLoRA(NF4) 학습 베이스가 아니다 → HF 원본(Qwen/Qwen3-14B@revision) 필요.
- 16GB 단일 GPU 에서 운영 Ollama 와 동시 학습 가능한지 메모리 추정으로 판정한다. 운영 모델 unload/종료는 하지 않는다.
- canStart=True 가 되려면: AI_QLORA_TRAINING_ENABLED=true + 승인 ID(AI_QLORA_APPROVAL_ID) + 추정 VRAM 이 현재 여유보다 작음
  + 운영 Ollama 에 로드된 모델 없음(동시 실행 금지) + 디스크 여유. 하나라도 아니면 시작 불가/연기.

  cd fastapi && .venv/bin/python -m app.training_pipeline.qlora_preflight [--dataset-dir DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class MemoryEstimate:
    base_4bit_gib: float
    embed_head_bf16_gib: float
    lora_and_optimizer_gib: float
    activations_gib: float
    logits_gib: float
    cuda_context_gib: float
    fragmentation_gib: float

    @property
    def total_gib(self) -> float:
        return round(sum(asdict(self).values()), 2)


def estimate_qlora_vram(*, params_b: float = 14.8, hidden: int = 5120, layers: int = 40, intermediate: int = 17408,
                        vocab: int = 151936, kv_dim: int = 1024, seq_len: int = 512, micro_batch: int = 1,
                        lora_r: int = 16, tied_embeddings: bool = False, grad_checkpointing: bool = True) -> MemoryEstimate:
    """NF4+double-quant 베이스 + BF16 임베딩/lm_head + LoRA(q,k,v,o) + AdamW + 체크포인팅 활성값 추정(GiB)."""
    gib = 1024 ** 3
    embed_params = vocab * hidden * (1 if tied_embeddings else 2)
    linear_params = params_b * 1e9 - embed_params
    base4 = linear_params * (0.5 + 0.127 / 8) / gib                       # 4bit + double-quant 상수
    emb = embed_params * 2 / gib                                           # bf16 유지
    lora_params = layers * lora_r * ((hidden + hidden) * 2 + (hidden + kv_dim) * 2)
    lora_opt = lora_params * (2 + 4 + 4 + 4) / gib                         # bf16 w + fp32 grad + adam m,v
    tokens = seq_len * micro_batch
    if grad_checkpointing:
        act = (layers * tokens * hidden * 2 + 4 * tokens * max(intermediate, hidden) * 2) / gib
    else:
        act = layers * tokens * (hidden * 12 + intermediate * 3) * 2 / gib
    logits = tokens * vocab * 4 * 2 / gib                                  # fp32 logits + grad
    ctx = 0.6
    frag = 0.1 * (base4 + emb + act + logits)
    return MemoryEstimate(round(base4, 2), round(emb, 2), round(lora_opt, 2), round(act, 2), round(logits, 2), ctx,
                          round(frag, 2))


@dataclass
class Preflight:
    can_start: bool
    reasons: List[str] = field(default_factory=list)
    facts: Dict[str, object] = field(default_factory=dict)


def _gpu() -> Dict[str, object]:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,compute_cap,driver_version",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout.strip()
        name, tot, used, free, cap, drv = [x.strip() for x in out.split(",")]
        return {"name": name, "totalMiB": int(tot), "usedMiB": int(used), "freeMiB": int(free), "computeCap": cap, "driver": drv}
    except Exception as e:  # noqa: BLE001
        return {"error": type(e).__name__}


def _ollama_loaded(url: str) -> Optional[List[str]]:
    try:
        import httpx
        return [m["name"] for m in httpx.get(f"{url}/api/ps", timeout=3).json().get("models", [])]
    except Exception:  # noqa: BLE001
        return None


def _hf_snapshot(model_id: str, revision: str) -> Dict[str, object]:
    root = Path.home() / ".cache/huggingface/hub" / ("models--" + model_id.replace("/", "--"))
    snap = root / "snapshots" / revision
    info: Dict[str, object] = {"cached": snap.is_dir(), "path": str(snap) if snap.is_dir() else None}
    if snap.is_dir():
        cfg = json.loads((snap / "config.json").read_text())
        info.update({"architectures": cfg.get("architectures"), "torch_dtype": cfg.get("torch_dtype"),
                     "shards": len(list(snap.glob("model-*.safetensors"))),
                     "chatTemplate": "chat_template" in json.loads((snap / "tokenizer_config.json").read_text())})
    return info


def run_preflight(*, seq_len: int = 512, lora_r: int = 16) -> Preflight:
    import importlib.util as iu
    reasons: List[str] = []
    facts: Dict[str, object] = {}
    vers = {}
    for m in ("torch", "transformers", "peft", "trl", "bitsandbytes", "accelerate"):
        if iu.find_spec(m) is None:
            vers[m] = None
            reasons.append(f"MISSING_{m.upper()}")
        else:
            vers[m] = getattr(__import__(m), "__version__", "?")
    facts["libraries"] = vers
    gpu = _gpu()
    facts["gpu"] = gpu
    base_id = os.getenv("AI_QLORA_BASE_MODEL", "Qwen/Qwen3-14B")
    rev = os.getenv("AI_QLORA_BASE_REVISION", "40c069824f4251a91eefaf281ebe4c544efd3e18")
    facts["baseModel"] = {"id": base_id, "revision": rev, "license": os.getenv("AI_QLORA_BASE_LICENSE", "apache-2.0"),
                          **_hf_snapshot(base_id, rev)}
    if not facts["baseModel"]["cached"]:
        reasons.append("BASE_MODEL_NOT_CACHED")
    est = estimate_qlora_vram(seq_len=seq_len, lora_r=lora_r)
    facts["vramEstimateGiB"] = {**asdict(est), "total": est.total_gib, "seqLen": seq_len, "loraR": lora_r}
    text = _ollama_loaded(os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    vision = _ollama_loaded(os.getenv("VISION_OLLAMA_BASE_URL", "http://127.0.0.1:11435"))
    facts["ollamaLoaded"] = {"text": text, "vision": vision}
    if text is None or vision is None:
        reasons.append("OLLAMA_STATE_UNKNOWN")
    elif text or vision:
        reasons.append("PRODUCTION_INFERENCE_LOADED")          # 동시 실행 금지: 운영 모델을 내리지 않는다
    if "freeMiB" in gpu and est.total_gib * 1024 > int(gpu["freeMiB"]) * 0.95:
        reasons.append("INSUFFICIENT_FREE_VRAM")
    if "totalMiB" in gpu and est.total_gib * 1024 + 9619 > int(gpu["totalMiB"]):
        reasons.append("CANNOT_COEXIST_WITH_QWEN3_14B_INFERENCE")   # 9.6GiB = 실측 qwen3:14b 상주량(2026-11-04)
    free_disk = shutil.disk_usage(str(Path.home())).free / 1024 ** 3
    facts["diskFreeGiB"] = round(free_disk, 1)
    if free_disk < 80:
        reasons.append("INSUFFICIENT_DISK")
    if (os.getenv("AI_QLORA_TRAINING_ENABLED") or "false").lower() != "true":
        reasons.append("FEATURE_FLAG_OFF")
    if not os.getenv("AI_QLORA_APPROVAL_ID"):
        reasons.append("NO_APPROVAL_RECORD")
    return Preflight(can_start=not reasons, reasons=reasons, facts=facts)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seq-len", type=int, default=512)
    ap.add_argument("--lora-r", type=int, default=16)
    a = ap.parse_args()
    pf = run_preflight(seq_len=a.seq_len, lora_r=a.lora_r)
    print(json.dumps({"canStart": pf.can_start, "reasons": pf.reasons, **pf.facts}, ensure_ascii=False, indent=2))
