#!/usr/bin/env bash
# 가짜 Ollama 로 A~D 혼합 4/10/20명 × 게이트웨이 OFF/ON × Ollama 병렬 1/2 매트릭스 (GPU 미사용).
# usage: bash scripts/ai_gateway_bench/run_mock_matrix.sh OUT_DIR
set -u
cd "$(dirname "$0")/../.."
OUT=${1:?out dir}; mkdir -p "$OUT"
PY=${PY:-.venv/bin/python}
S=0.2                                  # 시간 축척: 실제의 20% 로 재생, 결과는 실제 초로 환산
sc(){ python3 -c "print(max(1,int(round($1*$S))))"; }
scf(){ python3 -c "print($1*$S)"; }
for PAR in 1 2; do
  $PY scripts/ai_gateway_bench/fake_ollama.py 18434 $PAR text $S & T=$!
  $PY scripts/ai_gateway_bench/fake_ollama.py 18435 1 vision $S & V=$!
  for i in $(seq 1 40); do curl -s 127.0.0.1:18434/api/tags >/dev/null && curl -s 127.0.0.1:18435/api/tags >/dev/null && break; sleep 0.25; done
  for GW in ${BENCH_GW_MODES:-false true}; do
    for N in 4 10 20; do
      curl -s -XPOST 127.0.0.1:18434/reset >/dev/null; curl -s -XPOST 127.0.0.1:18435/reset >/dev/null
      env OLLAMA_BASE_URL=http://127.0.0.1:18434 VISION_OLLAMA_BASE_URL=http://127.0.0.1:18435 \
          OLLAMA_MODEL=qwen3:14b VISION_BACKEND=ollama OPENAI_API_KEY= \
          OLLAMA_TIMEOUT_SECONDS=$(sc 120) QUIZ_TIMEOUT_SECONDS=$(sc 120) INTENT_ROUTER_TIMEOUT_SEC=$(sc 5) \
          VISION_INFERENCE_TIMEOUT_SECONDS=$(scf 90) VISION_QUEUE_TIMEOUT_SECONDS=$(scf 120) VISION_MAX_QUEUE=8 \
          AI_GATEWAY_ENABLED=$GW AI_GW_GPU_GUARD=false AI_GW_TEXT_SLOTS=$PAR AI_GW_VISION_SLOTS=1 \
          AI_GW_INTERACTIVE_CHAT_QUEUE_TIMEOUT_S=$(scf 60) AI_GW_MULTI_AGENT_QUEUE_TIMEOUT_S=$(scf 90) \
          AI_GW_VISION_QUEUE_TIMEOUT_S=$(scf 30) AI_GW_DOCUMENT_QUIZ_QUEUE_TIMEOUT_S=$(scf 180) \
          AI_GW_DOCUMENT_ANALYSIS_QUEUE_TIMEOUT_S=$(scf 240) BENCH_SCALE=$S \
          $PY scripts/ai_gateway_bench/harness.py $N "p${PAR}_gw${GW}_n${N}" "$OUT/p${PAR}_gw${GW}_n${N}.json" \
          2>>"$OUT/harness.stderr" | tee -a "$OUT/summary.jsonl"
      echo "fake_text_stats p${PAR}_gw${GW}_n${N} $(curl -s 127.0.0.1:18434/stats)" >> "$OUT/fake_stats.txt"
    done
  done
  kill $T $V; wait $T $V 2>/dev/null
done
