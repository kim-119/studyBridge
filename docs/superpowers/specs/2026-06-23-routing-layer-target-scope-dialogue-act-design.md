# Routing Layer: Target Scope + Dialogue Act (no hardcoded semantics)

Date: 2026-06-23
Scope: FastAPI `/api/ai/multi-chat/stream` basic mode. No commit/push.

## Problem
1. `@친절한 개념 선생 ...` → 3명 다 답함 (target resolver 없음/무시).
2. `안녕` → 1명만 답함 (이전 target 잔류 / 잘못된 SINGLE 경로).
3. `왜 그런거임?` → 범용 학습 템플릿 반복 (dialogue act 분류 없음 / generic fallback 선실행).

## Absolute constraint
Production code에 **의미 단어/문장 리스트 금지**. 허용은 구조 신호/스키마 값뿐:
targetScope, targetAgentId, targetAgentName, selectedProfessor, targetAgent,
agents[].name/displayName/roleName/id, @mention 동적 매칭, roomId/sessionId/conversationId,
previous_context 존재 여부, DialogueAct/TargetScope enum.

## Architecture (order matters)
```
message → TargetScopeResolver (구조신호만) → context load → DialogueActClassifier (LLM)
        → target_agents 결정 → answer_depth 결정 → SSE
```
Target scope는 dialogue act보다 **먼저**. (`@교수 안녕`은 GREETING이지만 1명만.)

## 1. target_scope_resolver.py (new, structural-only)
`resolve_target_scope(message, agents, *, target_agent_id, target_agent_name, target_scope) -> TargetScopeDecision`
- `TargetScopeDecision{scope: SINGLE_AGENT|MULTI_AGENT|ALL_AGENTS|UNKNOWN, target_agents, mentioned_agent_names, reason}`
- 우선순위: explicit payload(targetScope/targetAgentId/targetAgentName) → `@mention` 동적 매칭
  (agents[].name/displayName/roleName/agentId/id, 공백 포함 이름 처리) → `@all/전체/모두` 구조 토큰 → default 전체.
- 교수 이름 하드코딩 0. 오직 runtime `agents` 배열.
- SINGLE이면 target_agents 길이 1, 나머지 절대 답변 X.

## 2. dialogue_act_classifier.py (re-architect)
- **삭제**: `_GREETING/_THANKS/_BACKCHANNEL/_AGREEMENT/_DISAGREEMENT/_WHY/_CHALLENGE/_SIMPLIFY/_EXAMPLE/_CONTINUE/_CLARIFY/_NEW_MARKERS` 등 의미 단어 리스트 전부.
- `classify_dialogue_act(message, *, previous_context, target_scope, classifier=None)`:
  - **항상 LLM** classifier 호출 (default = Ollama ask_ollama, think=False, JSON only). 주입 가능 interface.
  - act enum에 **FOLLOWUP_META** 추가 (시스템/라우팅/반복/응답방식 질문).
- **Fallback (LLM 실패) = 의미 판단 금지**: target scope만 유지, dialogue act = UNKNOWN 또는 ask_clarification.
  NEW_STUDY_QUERY로 억지 승격 금지. 구조 신호만(message 길이로 GREETING/BACKCHANNEL 판단 금지).
- **캐싱**: Redis TTL 5~15분. key = roomId/sessionId + normalized previous_context hash + target_scope + message.
  다른 맥락의 같은 문장 오염 방지.

## 3. basic_targeted_contextual_stream.py (new)
`run_contextual_targeted_turn_stream(message, target_decision, dialogue_decision, previous_context, *, reply_fn=None, min_gap)`
- `target_decision.target_agents` 사용 (1 or N). **`agents[:3]` override 금지.**
- turn_start(targetScope/targetAgentCount/dialogueAct/answerDepth) → agent_start/agent_answer ×N(phase=contextual_targeted)
  → all_complete(suppressValidation/suppressPeerFeedback=True) ×1.
- non-NEW act: validation/peer_feedback/성격검증/근거검증 출력 금지.
- anti-repeat guard 재사용(SequenceMatcher 0.72 → regenerate 1회 → content-free compact fallback). 이미 의미단어 0.
- reply prompt: agent personality + target scope + dialogue act + answer depth + previous context 반영.
  generic 템플릿 금지, FOLLOWUP_META는 개념설명 금지·"방금 흐름 기준으로는…" 조심스럽게.

## 4. Wiring (build_orchestrator_stream, basic)
resolve target scope → load context → classify →
- act != NEW_STUDY_QUERY → run_contextual_targeted_turn_stream(target_agents) → return.
- NEW + SINGLE → 1 agent full. NEW + MULTI/ALL → 기존 N-agent full 경로 (target_agents 전달).
- 기존 socratic/debate/simulation 미변경.

## 5. Schema (additive)
MultiChatRequest에 optional: targetScope, targetAgentName, sessionId, conversationId (AliasChoices, 하위호환).

## 6. Context state
Redis 가능 시 `multiagent:ctx:{roomId>sessionId>conversationId}` TTL 30m–2h;
없으면 `request.previousAnswers` graceful fallback(현행). build_previous_context 재사용.

## 7. Tests (injected classifier, no Ollama)
- test_target_scope_resolver.py: @mention 1명 / 일반 전체 3명 / @교수 인사 1명 / @all 전체 / targetAgentId / 공백이름.
- test_dialogue_act_classifier.py: LLM 주입 결과 반영 / fallback=UNKNOWN(NEW 승격 금지) / FOLLOWUP_META / 캐시 hit.
- test_basic_targeted_contextual_stream.py: SINGLE=agent_answer 1, MULTI=3, GREETING micro, no validation/peer, no generic template.
- test_basic_anti_repeat.py: 반복→교체.
- **test_no_hardcoded_semantic_word_lists**: 소스 스캔 — GREETING_WORDS/FOLLOWUP_WORDS/CASUAL_WORDS/THANKS_WORDS/CHALLENGE_WORDS 및 `if "안녕"/"왜"/"ㅇㅇ"/"고마워" in` 패턴 부재.
- **test_no_generic_template_fallback**: 소스 스캔 — "개념 정의와 실제 예시"/"개념을 명확히 이해"/"실제 상황에 어떻게 적용" 고정 문장 부재.

## Success criteria
@교수 1명 / 안녕 3명 micro / @교수 안녕 1명 / 왜 그런거임?→FOLLOWUP(META) 짧게·템플릿 금지 /
ㅇㅇ micro / gRPC?→NEW (scope 따라 1 or 3). 기존 모드 무영향. no commit/push.
