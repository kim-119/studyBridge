# StudyMate 성격 부각 + 확률적 다중답변 피드백 구조 설계

- 날짜: 2026-06-23
- 대상 기능: 학습메이트(멀티에이전트) StudyMate
- 작업자 컨텍스트: 브랜치 `LLM-clean`, FastAPI 백엔드 `fastapi/app`

## 1. 목표

두 갈래의 개선을 한다.

- **A. 성격 부각 (전체 모드 적용)**: 6종 성격(전문적/친근함/솔직함/독특함/효율적/냉소적)이 실제
  출력 문장에 분명히 드러나게 강화한다. GPT 중립톤으로 회귀하는 현상을 줄인다.
- **B. 확률적 다중답변 피드백 구조 (기본개념모드에만 적용)**: 에이전트가 3명이라도 답변이 정확히
  3개가 아니라, 확률적으로 **최소 3개 ~ 최대 7개**가 나오게 한다. 에이전트끼리 서로 반박/보완하며
  상호작용하되, **항상 사용자가 중심**이 되도록 한다.

## 2. 범위 결정 (확정)

- 성격 부각(A): 기본/토론/소크라테스 **전체 모드**에 적용.
- 확률적 다중답변(B): **기본개념모드(default mode)에만** 적용. 토론(논제선택→찬반/중재 고정역할),
  소크라테스(한 턴 한 질문)는 기존 전용 엔진의 계약을 **건드리지 않는다**.

## 3. 현재 구조 (출발점)

- 성격 SSOT: `fastapi/app/policies/agent_personality_profiles.yaml` (coreDirective 등).
- 성격 프롬프트 빌더: `fastapi/app/services/personality_prompt_builder.py`
  (`build_personality_prompt`, `build_persona_directive`).
- 멀티에이전트 답변 흐름: `fastapi/app/services/multi_agent_service.py`
  - 현재 default 모드는 3단계: `_stage1_initial`(초안) → `_stage2_validate`(검증) →
    `_stage3_feedback`(피어 피드백). **에이전트 1명당 정확히 1개 답변**이 나온다.
  - 합성: `_generate_synthesis`.
- 라이브 default 스트림 경로: compat 라우터 → `build_stream_generator`의 default 분기.
  비스트림 경로는 `main.py`의 multi_chat_endpoint(자체 스키마).

## 4. 섹션 A 설계 — 성격 부각

### 4.1 문제
coreDirective는 이미 존재하나, 모델이 정확성/안전 지시에 눌려 무색무취(GPT톤)로 회귀한다.

### 4.2 변경
1. **YAML coreDirective를 더 생생하게 교체** (요청 표 기준, 주제어 하드코딩 없이 말투·태도만):
   - 전문적: 학술적·격식 문어체, 주관 감정 배제, 전제-근거-결론, 백과사전처럼 차분·깊이.
   - 친근함: 유치원 선생님 말투(~해요/~하죠), "아주 좋은 질문이에요!"/"조금만 더 힘내봐요!" 격려.
   - 솔직함: 포장 없이 핵심만 직설, 단점·치명적 한계까지 가차없이 짚음(조롱/인신공격은 금지).
   - 독특함: 평범한 설명 거부, 엉뚱한 사물/상황 비유, "음.../아하!" 감탄사, 4차원적 관점.
   - 효율적: 인사·서론·감정 제거, 결론부터 1줄, 개조식(1.2.3) 요점. "결론:" 기계 반복은 금지.
   - 냉소적: 시니컬·까칠한 반말 비꼼, 한숨("이걸 아직도..진짜 귀찮네"), 단 지적은 날카롭게.
2. **persona directive를 모든 발화 단계에 주입**: 초안뿐 아니라 반응/정리 단계에도
   `build_persona_directive`를 user 턴 끝에 다시 못박는다.
3. **성격 약한 답변 재생성 게이트를 조금 더 민감하게** (기존 repair 로직 재사용, 임계만 조정).
4. **생생한 성격은 temperature 폭 확대** (creative/sardonic 등). 기존 `_GEN_PARAMS` 조정.

### 4.3 비목표
- 주제 도메인 용어를 로직/폴백에 하드코딩하지 않는다(반복 유발). 말투/태도 패턴만 강화한다.
- 성격 검증 점수의 사용자 노출은 변경하지 않는다(기존 debug-only 유지).

## 5. 섹션 B 설계 — 확률적 다중답변 피드백 (기본개념모드)

### 5.1 새 모듈: `fastapi/app/services/studymate_discussion_planner.py`
순수 함수(시드 주면 재현). N명 에이전트 + 질문 → **발화 계획**(speech act 순서 리스트)을 만든다.

각 act = `(speaker_agent, act_type, target_agent_or_None)`.

#### 행위 유형 (전부 기존 생성 함수 재사용)
| 유형 | 의미 | 재사용 함수 |
|---|---|---|
| `DIRECT_ANSWER` | 질문에 직접 답(기본 라운드) | `_stage1_initial` |
| `REACTION` | 다른 에이전트 답에 반박/보완 | `_stage3_feedback`(피어 피드백) |
| `WRAP` | 사용자용 한 줄 정리 + 다음 질문 | `_generate_synthesis` |

#### 개수 메커니즘
- **바닥(floor) = 기본 라운드**: 모든 에이전트가 `DIRECT_ANSWER` 1번씩 → N명이면 N개.
- **추가 반응**: 확률 분포로 0~4개의 `REACTION`을 더 붙인다. 가중치는 총합이 ~4-5개에 몰리도록.
  예시 가중치(추가 개수): `0→10%, 1→20%, 2→30%, 3→25%, 4→15%` (구현 시 조정 가능).
- **클램프**: 총합을 항상 `[min,max] = [3,7]`로 강제. 환경변수로 외부화.
- **가중 셔플**: 기본 라운드 순서를 섞고, REACTION의 (reactor, target) 쌍을 확률로 고른다.
  자기자신 대상 금지, 직전 동일 쌍 즉시 반복 회피.

#### 에이전트 수 엣지 케이스
- N < 3 (예: 2명): REACTION으로 패딩해 최소 3을 채운다.
- N > 7: 기본 라운드를 7로 캡(앞 7명만 발화).

### 5.2 "항상 사용자 중심" 하드 보장
- **첫 act는 무조건 `DIRECT_ANSWER`** — 메타/잡담으로 시작 금지.
- **REACTION 프롬프트에 "반박해도 결국 사용자에게 설명하라" 명시** — 에이전트끼리만 떠들지 않게.
- **마지막 act는 무조건 `WRAP`** — 한 줄 결론 + 다음 질문 제안(요청 3번).
- **끝에 재개입 칩 이벤트** — "더 파고들기 / 다른 의견 듣기" 등 후속 택을 사용자에게(요청 4번).
- 매너 기본값: 모든 발화는 사용자를 향해 말하는 어조(요청 1·2번)를 깐다.

### 5.3 계약 / SSE
- 각 act는 기존 `agent_answer` 이벤트로 방출하되 필드 추가:
  - `actType`: `DIRECT_ANSWER | REACTION | WRAP`
  - `replyTo`: REACTION일 때 대상 에이전트 id(아니면 null)
- `all_complete`는 끝에 **1회만** (기존 보장 유지).
- 재개입 칩: 마지막에 별도 이벤트(예: `follow_up_suggestions`) 또는 `all_complete` 페이로드에 포함.
- 라이브 배선: compat → `build_stream_generator`의 **default 분기에만** 플래너를 연결.
  비스트림(main.py) 경로는 최소한 floor(기본 라운드) 동작은 유지.

### 5.4 안전장치 / 운영
- `STUDYMATE_DISCUSSION_PLANNER` (on/off, 기본 on): off면 기존 1인1답으로 즉시 롤백.
- `STUDYMATE_DISCUSSION_SEED`: 테스트 재현용 시드.
- `STUDYMATE_DISCUSSION_MIN` / `STUDYMATE_DISCUSSION_MAX`: 기본 3 / 7.

## 6. 테스트 전략
- **플래너 단위(순수함수, 시드 스윕)**:
  - 총합이 항상 `[3,7]`.
  - 첫 act = `DIRECT_ANSWER`, 마지막 act = `WRAP`.
  - 모든 `REACTION`은 유효하고 서로 다른 대상(자기자신 금지).
  - 분포가 대략 가중치를 따른다(통계적 허용오차).
  - 에이전트 2명/5명/8명 엣지에서 불변식 유지.
- **통합(TestClient, default 스트림)**:
  - `agent_answer` 이벤트 개수 ∈ `[3,7]`.
  - `all_complete` 정확히 1회.
  - `actType`/`replyTo` 필드 존재 및 일관성.
  - `STUDYMATE_DISCUSSION_PLANNER=off`면 기존(1인1답) 동작.
- **성격(A)**: 기존 personality 라벨/검증 테스트가 계속 통과. 6종 coreDirective 변경 후에도
  normalize/라벨 계약 회귀 없음.

## 7. 리스크 / 주의
- 이 환경(ai07)은 autodeploy가 ~2분마다 `origin/LLM-clean`으로 `reset --hard` → 커밋 안 한 tracked
  `.py` 변경은 다음 push 때 소실. 실제 반영은 commit+push(+서비스 restart)가 필요하며, 그 경로는
  사용자 승인 사안이다(별도 확인).
- qwen3는 think 토큰 소진 시 빈응답 이슈가 있으므로 플래너 중간에 LLM 판단을 끼우지 않는다
  (순수 결정론 플래너 채택 이유).
- 토론/소크라테스 계약은 절대 건드리지 않는다.

## 8. 변경 파일(예상)
- `fastapi/app/policies/agent_personality_profiles.yaml` (A: coreDirective 강화)
- `fastapi/app/services/personality_prompt_builder.py` (A: 주입/파라미터)
- `fastapi/app/services/multi_agent_service.py` (A·B: persona 주입, default 분기에 플래너 배선)
- `fastapi/app/services/studymate_discussion_planner.py` (B: 신규)
- `fastapi/app/schemas/...` (B: agent_answer에 actType/replyTo 필드)
- `fastapi/tests/test_studymate_discussion_planner.py` (B: 신규)
- `fastapi/tests/test_studymate_discussion_stream.py` (B: 통합, 신규)
