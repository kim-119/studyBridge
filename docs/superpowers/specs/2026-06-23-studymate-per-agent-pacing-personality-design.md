# StudyMate 멀티에이전트 — 순차(per-agent) 페이싱 + 성격 강화 설계

- 작성일: 2026-06-23
- 대상: `fastapi/` (AI 서버). 프론트/백엔드 무변경.
- 배포: 커밋 + `LLM-clean` push → ai07 autodeploy가 `studybridge-ai` 자동 재시작.

## 1. 목표 (사용자 요구)

1. **UX 시차 노출**: 답변이 한꺼번에 뜨지 않고, 에이전트별로 **하나씩** 나오되 **최소 4초 간격**을 두고 등장한다.
2. **성격 도드라짐**: 6종 성격이 "답변 톤" 라벨에 머무르지 않고 **구체적 행동 지시문**으로 변환되어 답변 문장에 분명히 드러난다.
3. **전 모드 적용**: 기본 멀티에이전트 / 토론 / 소크라테스 / 상황극 모두 동일하게 per-agent 페이싱.

## 2. 현재 구조와 문제점

- 라이브 스트림 경로: `compat 라우터 → multi_agent_service.build_stream_generator → orchestrator_service.build_orchestrator_stream`.
- `build_orchestrator_stream`은 `run_orchestrator`를 **1회** 호출해 전원 답을 한 번에 받고, `agent_answer`를 즉시 N개 연달아 emit → **거의 동시 표시**.
- `run_orchestrator`의 프롬프트(`build_system_prompt`)는 **모드별** 프롬프트일 뿐, 성격은 `_agents_to_json_list`의 "답변 톤" 라벨(예: "친절형")만 JSON에 넣어 모델에게 맡김 → 성격이 약하게 나옴.
- 이미 존재하는 강력한 성격 빌더(`personality_prompt_builder.build_personality_prompt` / `build_persona_directive`, SSOT=`policies/agent_personality_profiles.yaml`)를 **오케스트레이터가 전혀 사용하지 않음** → 이것이 성격이 죽던 근본 원인.

## 3. 설계

### 3.1 per-agent 순차 호출 + 최소 간격 (스트림)

`build_orchestrator_stream(request, agents)` 재작성:

```
yield turn_start (1회)
for idx, agent in enumerate(agents, displayOrder 순):
    t0 = time.time()
    sys = _build_single_agent_system_prompt(agent, effective_mode, request)
    usr = _build_single_agent_user_prompt(agent, request, wiki_context, context)
    answer = ask_ollama(system_prompt=sys, user_prompt=usr,
                        temperature=<성격별>, max_tokens=..., think=False)
    answer = <빈응답 가드/think strip>
    yield agent_start(idx, agent)
    yield agent_answer(idx, agent, answer)
    # 최소 간격 보장: 마지막 에이전트 뒤에는 sleep 안 함
    if idx < len(agents)-1:
        elapsed = time.time() - t0
        gap = MIN_GAP - elapsed
        if gap > 0: time.sleep(gap)
yield all_complete (1회, answers 집계)
```

- `MIN_GAP` = `float(os.getenv("STUDYMATE_MIN_ANSWER_GAP_SECONDS", "4"))`.
- 첫 답변은 turn_start 직후 즉시 생성 시작(앞단 불필요 대기 없음).
- SSE 이벤트 형태(`turn_start/agent_start/agent_answer/all_complete`)와 필드는 **현행 유지** → 프론트 무변경.
- 빈 에이전트 목록이면 즉시 all_complete(빈 answers)로 안전 종료.

### 3.2 성격 행동 지시문 주입

- 에이전트별 system 프롬프트를 새 헬퍼 `_build_single_agent_system_prompt(agent, mode, request)`로 구성:
  - **성격 블록**: `personality_prompt_builder.build_personality_prompt(personality_label, customInstruction)` 사용.
  - **성격 강한 못박기**: user 프롬프트 끝에 `build_persona_directive(personality_label, customInstruction)` 부착(이 빌더는 system만으론 모델이 성격을 버리는 문제를 보완하도록 설계됨).
  - **지식수준 정책**: 기존 `_agents_to_json_list`의 "학습자 수준" 표현을 문장 지시로 포함.
  - **모드 프레이밍**: `effective_mode`(basic/debate/socratic/simulation)에 맞는 1~2줄 역할 지시(토론=입장 견지, 소크라테스=정답 대신 꼬리질문, 상황극=배역 유지). 기존 `build_system_prompt`의 모드 텍스트를 단일 에이전트용으로 축약 재사용.
  - **금지 가드**: 냉소/솔직 성격에도 인신공격·욕설 금지(기존 YAML `forbidden`/`speechRegister` 규칙 그대로 적용).
- 성격별 temperature는 `get_generation_params(personality_label)` 사용(creative 0.85 ~ logical 0.35 등).

### 3.3 6종 성격 지시문을 YAML SSOT에 반영 (사용자 verbatim)

`build_personality_prompt`는 **YAML 프로필을 fallback dict보다 우선**한다. 따라서 사용자 지시문은
`fastapi/app/policies/agent_personality_profiles.yaml`에 반영해야 실제로 적용된다.
각 키에 최우선 지시 필드 `coreDirective`(verbatim)를 추가하고, `_compose_prompt_from_profile`/`build_persona_directive`가
이 필드를 **맨 앞에 그대로** 배치하도록 빌더를 보강한다. 매핑:

| 프론트 라벨 | YAML 키 | coreDirective(요지, 전문은 verbatim) |
|---|---|---|
| 전문적 | professional | 학술적·격식 문어체, 주관 감정 배제, 전제-근거-결론, 백과사전처럼 차분·깊이 |
| 친근함 | friendly | 유치원 선생님 말투(~해요/~하죠), "아주 좋은 질문이에요!"/"조금만 더 힘내봐요!" 격려·칭찬 |
| 솔직함 | critical | 포장 없이 핵심만 팩트 폭력으로 직설, 단점·치명적 한계까지 가차없이 까발림 |
| 독특함 | creative | 평범한 설명 거부, 엉뚱한 사물/상황 비유, "음.../아하!" 감탄사, 4차원적 관점 |
| 효율적 | concise | 인사·서론·감정 제거, 결론부터 1줄, 개조식(1.2.3) 요점 요약 |
| 냉소적 | sardonic | 시니컬·까칠한 반말 비꼼, 한숨("이걸 아직도..진짜 귀찮네"), 단 설명은 허점을 날카롭게 |

- fallback dict `_PERSONALITY_PROMPTS`도 동일 취지로 동기화(YAML 부재 시 대비).
- 냉소/솔직의 반말·직설은 기존 `forbidden`(인신공격·욕설 금지)과 공존.
- 주의: 프론트 "솔직함"은 기존 `critical` 키에 alias됨 → critical의 coreDirective를 Honest 정의로 채운다(별칭 매핑은 변경 없음).

### 3.4 비스트림 경로

- `run_orchestrator`도 동일하게 **per-agent 순차 호출**로 변경(성격 일관성). 단 비스트림은 한 번에 응답이므로 sleep 없음.
- `displayDelayMs`를 `idx * MIN_GAP*1000`으로 설정해 프론트가 비스트림 결과를 받을 때도 시차 렌더 가능하게 힌트 제공.
- 참고: **라이브 비스트림 멀티챗은 `fastapi/main.py`의 자체 경로**라 본 변경(run_orchestrator)은 라이브 비스트림에 직접 영향 없음. 정합성 차원에서만 맞춰 둔다.

## 4. 변경 파일

1. `fastapi/app/services/orchestrator_service.py` — `build_orchestrator_stream` 재작성(루프+페이싱), 신규 헬퍼 2개, `run_orchestrator` per-agent화.
2. `fastapi/app/services/personality_prompt_builder.py` — `coreDirective` 최우선 배치 로직 추가, fallback 동기화.
3. `fastapi/app/policies/agent_personality_profiles.yaml` — 6키에 `coreDirective` verbatim 추가.
4. `fastapi/tests/test_studymate_per_agent_pacing.py` (신규).

## 5. 테스트

- **단위(성격)**: 6라벨 각각 `build_personality_prompt` 결과에 coreDirective 핵심 키워드 포함(예: friendly→"~해요"/격려, concise→"결론부터"/개조식, sardonic→반말/한숨).
- **스트림(구조)**: `build_orchestrator_stream`을 ask_ollama monkeypatch로 호출 → 이벤트 순서 `turn_start → (agent_start, agent_answer)×N → all_complete`, agent_answer N개, all_complete 1회.
- **스트림(페이싱)**: ask_ollama를 즉시 반환하도록 패치하고 `MIN_GAP`을 작은 값(예: 0.2s)으로 설정 → 인접 agent_answer emit 간 경과시간 ≥ MIN_GAP 검증(마지막 뒤엔 미적용).
- **모드**: debate/socratic/simulation에서도 동일 이벤트 계약과 페이싱 적용 확인.
- **실 qwen3 스모크**: 서로 다른 성격 2~3명 → 답 톤이 확연히 다른지(개조식 vs 반말 vs 격려체) 육안 확인.

## 6. 위험 / 고려사항

- **총 응답시간 증가**: N×생성 + (N-1)×최대 MIN_GAP. 3명이면 대략 15~30s. **사용자가 원한 UX라 수용**.
- think:false 유지로 빈응답/thinking 소진 방지. 빈응답 가드 유지.
- 전 모드를 per-agent로 통일하므로 토론의 라운드·소크라테스의 단계 같은 다단계 구조는 **단일 프롬프트 품질에 의존**(이번 스코프는 페이싱+성격; 다단계 정교화는 후속).
- `STUDYMATE_MIN_ANSWER_GAP_SECONDS` env로 운영 중 간격 조절 가능(escape hatch).

## 7. 프론트엔드 (교수님들과 대화 UI) — 추가 스코프

> 참고: 프론트는 코드만 작성 가능하고 **라이브 반영은 EC2 빌드/배포 필요**(ai07 autodeploy 대상 아님).

대상: `frontend/src/pages/StudyMate.jsx`(professor 탭), `components/studymate/pixel/PixelProfessorStage.jsx`, 신규 말풍선 컴포넌트, `pixelProfessor.css`.

### 7.1 교수별 답변 말풍선
- `agent_answer` SSE 도착 시 해당 교수 sprite 위에 말풍선을 띄우고 답변을 넣는다.
- 교수↔에이전트 매핑은 기존 `ROLE_TO_AGENT_INDEX` 사용. per-agent 4초 페이싱과 동기化되어 하나씩 등장.
- 신규 컴포넌트 `ProfessorSpeechBubble`(또는 기존 MinuteRecapBubble 패턴 재사용), 에이전트 색(`agentColor`) 보더.

### 7.2 긴 답변: 미리보기 + 더보기 (사용자 선택 = 안 1)
- 말풍선엔 **앞 2~3줄(약 120자) 미리보기**만. 초과 시 말끝 `…` + **"더보기"** 버튼.
- "더보기" → 아래 채팅 스레드의 해당 메시지로 스크롤/펼침(전체 답변은 항상 스레드에 존재). 말풍선 자체는 길어지지 않음.

### 7.3 무대 확대
- `pixel-professor-stage` 영역을 더 크게(높이/스케일 ↑). CSS 위주, sprite 좌표(`pos`) 비례 유지.

### 7.4 마인드맵 분리 (버튼 토글)
- 현재 professor 탭의 `professor-tree-section`(`AgentDiscussionThread` = 마인드맵)을 **기본 숨김**.
- **"마인드맵 보기" 토글 버튼** 추가 → 누르면 별도 섹션으로 표시/숨김. 상태는 로컬 useState(`showMindmap`).
- `ProfessorInteractionTimeline`/트리 로직은 불변, 가시성만 토글.

### 7.5 프론트 검증
- `npm run build` 통과(CLAUDE.md 요구). 라이브 반영은 EC2.

## 8. 비목표 (YAGNI)

- Spring(backend/) 수정.
- 토론/소크라테스/상황극의 다단계 엔진 복원.
- 스트리밍 토큰 단위(부분 타이핑) 출력 — 본 스코프는 "답변 단위" 시차.
