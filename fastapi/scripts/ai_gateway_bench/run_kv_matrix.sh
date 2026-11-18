#!/usr/bin/env bash
# (승인 후 실행) 설정 후보 A/B·C/D 품질·성능 비교. 운영 Ollama 설정은 바꾸지 않는다(B·C·D 는 :11436 격리 인스턴스).
#   A   = 운영 데몬(:11434) NUM_PARALLEL=1, KV f16 (Flash Attention 은 0.24.0 이 qwen3 에 자동 활성)
#   B·C = 격리 NUM_PARALLEL=2, KV f16 (FA 자동 활성이라 B 와 C 는 같은 구성)
#   D   = 격리 NUM_PARALLEL=2, KV q8_0
# 안전장치: 단계마다 운영 트래픽 확인(있으면 중단), 종료 시 모든 모델 언로드·격리 데몬 종료.
set -u
cd "$(dirname "$0")/../.."
OUT=${1:?out dir}; mkdir -p "$OUT"
PY=${PY:-.venv/bin/python}
START=$(date '+%Y-%m-%d %H:%M:%S')
guard(){ n=$(journalctl -u studybridge-ai --since "$START" --no-pager -o cat | grep -c '"POST /api/'); [ "$n" -eq 0 ] || { echo "PROD TRAFFIC — abort" | tee -a "$OUT/log"; cleanup; exit 3; }; }
unload(){ curl -s -m 30 "$1/api/generate" -d "{\"model\":\"qwen3:14b\",\"keep_alive\":0}" >/dev/null 2>&1; }
TP=""
cleanup(){ unload http://127.0.0.1:11434; unload http://127.0.0.1:11436; [ -n "$TP" ] && kill $TP 2>/dev/null; wait $TP 2>/dev/null; TP=""; }
trap cleanup EXIT
[ "$(curl -s 127.0.0.1:11434/api/ps)" = '{"models":[]}' ] || { echo "prod model resident — abort"; exit 2; }
guard
$PY scripts/ai_gateway_bench/kv_quality_eval.py http://127.0.0.1:11434 A_p1_f16 "$OUT/A.json" | tee -a "$OUT/log"; unload http://127.0.0.1:11434; guard
for CFG in f16 q8_0; do
  env OLLAMA_HOST=127.0.0.1:11436 OLLAMA_MODELS=$HOME/ollama-bench/models OLLAMA_NUM_PARALLEL=2 OLLAMA_KV_CACHE_TYPE=$CFG \
      OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_KEEP_ALIVE=5m /usr/local/bin/ollama serve >> "$OUT/tuned_$CFG.log" 2>&1 & TP=$!
  for i in $(seq 1 40); do curl -s 127.0.0.1:11436/api/version >/dev/null && break; sleep 0.5; done
  $PY scripts/ai_gateway_bench/kv_quality_eval.py http://127.0.0.1:11436 P2_$CFG "$OUT/P2_$CFG.json" | tee -a "$OUT/log"
  curl -s 127.0.0.1:11436/api/ps >> "$OUT/ps_$CFG.json"; nvidia-smi --query-gpu=memory.used --format=csv,noheader >> "$OUT/ps_$CFG.json"
  grep -oE "FlashAttention:[A-Za-z]+|KvCacheType:[a-z0-9_]*|Parallel:[0-9]+|KvSize:[0-9]+" "$OUT/tuned_$CFG.log" | sort | uniq -c >> "$OUT/log"
  cleanup; guard
done
for CFG in f16 q8_0; do
  COMPARE_PLAN=tuned_only TUNED_PAR=2 TUNED_KV=$CFG TUNED_NS=10 TUNED_POLICY=adaptive \
    $PY scripts/ai_gateway_bench/real_compare.py "$OUT/perf_$CFG" 2>&1 | grep -E "tuned_|STOPPED|restored" | tee -a "$OUT/log"
  guard
done
echo "DONE $(date)" | tee -a "$OUT/log"
