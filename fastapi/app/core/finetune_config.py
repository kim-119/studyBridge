"""
파인튜닝 및 모델 엔진 설정.

주력 엔진: Ollama (Qwen2.5 14B 양자화)
vLLM은 사용하지 않는다.
QLoRA/adapter는 선택적 보조 실험용이며 기본값은 비활성화다.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ----- 주력 모델 엔진 -----
# "ollama" 고정. vLLM은 제거됨.
MODEL_ENGINE: str = os.getenv("MODEL_ENGINE", "ollama")

# ----- fine-tuned adapter (optional, 기본 비활성) -----
# adapter 실험 성공 후 ollama create로 생성한 커스텀 모델명 또는 경로를 입력한다.
# 예: FINETUNED_ADAPTER_PATH=studybridge-qwen25-14b-style
FINETUNED_MODEL_ENABLED: bool = os.getenv("FINETUNED_MODEL_ENABLED", "false").lower() == "true"
FINETUNED_ADAPTER_PATH: str | None = os.getenv("FINETUNED_ADAPTER_PATH")

# ----- QLoRA optional 실험 -----
# QLoRA는 향미제 수준의 보조 실험이다. 기본값 비활성화.
# 서버컴에서 bitsandbytes/CUDA 호환 확인 후 활성화한다.
QLORA_OPTIONAL_ENABLED: bool = os.getenv("QLORA_OPTIONAL_ENABLED", "false").lower() == "true"
QLORA_ADAPTER_OUTPUT_DIR: str = os.getenv("QLORA_ADAPTER_OUTPUT_DIR", "./adapters/qwen25_14b_studybridge")

# ----- 학습 데이터 -----
SFT_DATASET_PATH: str = os.getenv("SFT_DATASET_PATH", "./data/sft_train.jsonl")
SFT_EVAL_DATASET_PATH: str = os.getenv("SFT_EVAL_DATASET_PATH", "./data/sft_eval.jsonl")
