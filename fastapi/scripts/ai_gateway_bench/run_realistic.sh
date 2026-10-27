#!/usr/bin/env bash
# realistic_mix.py 매트릭스: Ollama 병렬 1/2 × 게이트웨이 OFF/ON × light/peak(+heavy 사용자). GPU 미사용.
set -u
cd "$(dirname "$0")/../.."
OUT=${1:?out dir}; mkdir -p "$OUT"
PY=${PY:-.venv/bin/python}
S=0.2
sc(){ python3 -c "print(max(1,int(round($1*$S))))"; }
scf(){ python3 -c "print($1*$S)"; }
for PAR in 1 2; do
  $PY scripts/ai_gateway_bench/fake_ollama.py 18434 $PAR text $S & T=$!
  $PY scripts/ai_gateway_bench/fake_ollama.py 18435 1 vision $S & V=$!
  for i in $(seq 1 40); do curl -s 127.0.0.1:18434/api/tags >/dev/null && curl -s 127.0.0.1:18435/api/tags >/dev/null && break; sleep 0.25; done
  for SPEC in ${REALISTIC_SPECS:-light:0 peak:0 peak:1}; do
    PROF=${SPEC%:*}; HEAVY=${SPEC#*:}
    for GW in ${REALISTIC_GW:-false true}; do
      env OLLAMA_BASE_URL=http://127.0.0.1:18434 VISION_OLLAMA_BASE_URL=http://127.0.0.1:18435 \
          OLLAMA_MODEL=qwen3:14b VISION_BACKEND=ollama OPENAI_API_KEY= STUDYMATE_REDIS=off \
          OLLAMA_TIMEOUT_SECONDS=$(sc 120) QUIZ_TIMEOUT_SECONDS=$(sc 120) INTENT_ROUTER_TIMEOUT_SEC=$(sc 5) \
          AI_FIRST_TOKEN_TIMEOUT_SEC=$(sc 60) AI_TOTAL_TIMEOUT_SEC=$(sc 90) \
          VISION_INFERENCE_TIMEOUT_SECONDS=$(scf 90) VISION_QUEUE_TIMEOUT_SECONDS=$(scf 120) VISION_MAX_QUEUE=8 \
          AI_GATEWAY_ENABLED=$GW AI_GW_GPU_GUARD=false AI_GW_TEXT_SLOTS=$PAR AI_GW_VISION_SLOTS=1 \
          AI_GW_INTERACTIVE_CHAT_QUEUE_TIMEOUT_S=$(scf 60) AI_GW_MULTI_AGENT_QUEUE_TIMEOUT_S=$(scf 90) \
          AI_GW_VISION_QUEUE_TIMEOUT_S=$(scf 30) AI_GW_DOCUMENT_QUIZ_QUEUE_TIMEOUT_S=$(scf 180) \
          AI_GW_DOCUMENT_ANALYSIS_QUEUE_TIMEOUT_S=$(scf 240) AI_GW_RESERVE_HOLD_S=$(scf 20) BENCH_SCALE=$S \
          MIX_PROFILE=$PROF MIX_HEAVY=$HEAVY MIX_DURATION=300 \
          $PY scripts/ai_gateway_bench/realistic_mix.py "p${PAR}_${PROF}_h${HEAVY}_gw${GW}" "$OUT/p${PAR}_${PROF}_h${HEAVY}_gw${GW}.json" \
          2>>"$OUT/stderr.log" | tee -a "$OUT/summary.jsonl"
    done
  done
  kill $T $V; wait $T $V 2>/dev/null
done
