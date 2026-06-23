# Dialogue-Act Gate — basic 모드 후속 발화 수정 (핸드오프)

## 무엇을 고쳤나
기본(basic) 모드에서 직전 대화가 있을 때 들어온 **짧은 후속 발화**
("아니왜?", "왜?", "그게 맞아?", "예시로", "더 쉽게", "ㅇㅇ" 등)를
**새 질문으로 오인해 3명이 직전 답변을 통째로 반복**하던 문제를 차단한다.

LLM 기반(결정론 우선 + 선택적 LLM) **Dialogue Act Classifier**가 메시지를
직전 맥락(`request.previousAnswers`)과 함께 분류하고, `NEW_STUDY_QUERY`가 아니면
**짧은 맥락 답변 턴**(3명 유지·1~2문장·검증/피드백 없음·직전 답변 반복 금지)으로 보낸다.

> ⚠️ **하드코딩 용어 금지 준수**: 분류기는 주제어(예: 특정 기술명)에 전혀 의존하지 않고
> 대화행위 패턴(왜/예시/더쉽게…)만 본다. 폴백 답변도 직전 내용을 본문에 박지 않는다
> (그 단어가 답 반복을 유발하므로 의도적으로 content-free). 직전 핵심은 동적으로만 참조.

## 신규 파일 (untracked — autodeploy reset에도 생존)
- `fastapi/app/services/dialogue_act_classifier.py` — 14종 dialogue act 분류기(결정론+선택 LLM)
- `fastapi/app/services/basic_contextual_turn.py` — 짧은 맥락 턴 스트림 + anti-repeat 가드
- `fastapi/tests/test_dialogue_act_classifier.py`
- `fastapi/tests/test_basic_contextual_turn.py`
- `fastapi/tests/test_basic_anti_repeat.py`

## 유일한 tracked 수정 (autodeploy가 ~2분마다 reset → 직접 commit+push 필요)
**파일**: `fastapi/app/services/orchestrator_service.py`
**위치**: `build_orchestrator_stream()` 안, `social = _is_social_input(request)` 줄과
`yield { "event": "turn_start" ... }` 사이.

아래 블록을 그 사이에 삽입한다:

```python
    # ── basic 모드 후속 발화 게이트 ────────────────────────────────────────────
    # 직전 대화가 있을 때 "아니왜?/왜?/그게 맞아?/예시로/더 쉽게/ㅇㅇ" 같은 후속 발화는
    # 새 질문이 아니므로, 3명이 직전 답변을 통째로 반복하지 않고 짧은 맥락 답변만 낸다.
    # (위치별 역할분담 풀답변 경로와 상보적 — 후속 발화는 애초에 풀답변을 타지 않는다.)
    # 분류는 결정론 우선(+선택적 LLM). 어떤 오류든 기존 풀답변 경로로 폴백(additive).
    if effective_mode == "basic":
        try:
            from app.services.dialogue_act_classifier import (
                build_previous_context,
                classify_dialogue_act,
                NEW_STUDY_QUERY,
            )
            prev_ctx = build_previous_context(request.previousAnswers, mode=effective_mode)
            if prev_ctx.has_context:
                decision = classify_dialogue_act(
                    request.message,
                    previous_context=prev_ctx,
                    mode=request.mode,
                    learning_mode=getattr(request, "learningMode", None),
                )
                if decision.act != NEW_STUDY_QUERY:
                    from app.services.basic_contextual_turn import (
                        run_basic_contextual_turn_stream,
                    )
                    logger.info(
                        "[Orchestrator] basic followup act=%s depth=%s conf=%.2f → contextual turn",
                        decision.act, decision.answer_depth, decision.confidence,
                    )
                    yield from run_basic_contextual_turn_stream(
                        request, agents, decision, prev_ctx, min_gap=min_gap,
                    )
                    return
        except Exception as e:  # pragma: no cover - 방어: 무조건 기존 경로로 폴백
            logger.warning("[Orchestrator] dialogue-act 게이트 건너뜀: %s", e)

```

## 라이브 반영(durable) 절차
```bash
cd /home/ai07/capstoneLLM
# 1) 위 블록을 orchestrator_service.py 에 삽입(또는 docs/handoff 패치 적용)
# 2) 신규 5개 파일 + orchestrator 수정 commit
git add fastapi/app/services/dialogue_act_classifier.py \
        fastapi/app/services/basic_contextual_turn.py \
        fastapi/app/services/orchestrator_service.py \
        fastapi/tests/test_dialogue_act_classifier.py \
        fastapi/tests/test_basic_contextual_turn.py \
        fastapi/tests/test_basic_anti_repeat.py
git commit -m "fix(studymate): basic 후속발화(아니왜?/예시로/더쉽게) dialogue-act 게이트로 반복 차단"
git push origin LLM-clean         # autodeploy가 이걸 reset 기준으로 삼아 생존
# 3) 라이브 서비스 재시작(sudo)
sudo systemctl restart studybridge-ai.service    # 또는 운영 유닛명
```

## 검증
```bash
cd /home/ai07/capstoneLLM/fastapi
.venv/bin/python -m pytest -q \
  tests/test_dialogue_act_classifier.py \
  tests/test_basic_contextual_turn.py \
  tests/test_basic_anti_repeat.py
# → 47 passed
```
SSE 스모크(라이브 재시작 후): 1차로 새 질문, 2차로 같은 roomId에 "아니왜?" 전송 →
`/api/ai/multi-chat/stream` 응답에 `dialogueAct=FOLLOWUP_WHY`, `agent_answer` 3개,
`validation`/`peer_feedback` 없음, 직전 답변 전문 반복 없음.

## 옵션 (env)
- `DIALOGUE_ACT_USE_LLM=1` : 결정론 신뢰도가 낮은 애매한 경우에만 LLM(think=False) 보조 분류.
  기본 0(결정론만) — 빠르고 재현 가능. 분류기는 비활성/실패 시 항상 결정론으로 폴백.
