# StudyMate 성격 부각 + 확률적 다중답변 — 작업 핸드오프 (노트북에서 이어받기)

- 날짜: 2026-06-23
- 작업 머신: ai07 (`/home/ai07/capstoneLLM`)
- **격리 worktree**: `/home/ai07/capstoneLLM-studymate-wt`
- **브랜치**: `feature/studymate-personality-discussion` (base = `LLM-clean`@28579193)
- 설계 스펙: `docs/superpowers/specs/2026-06-23-studymate-personality-emphasis-discussion-planner-design.md`

## 왜 worktree에 있나
ai07은 autodeploy가 ~2분마다 `LLM-clean`을 `reset --hard`로 되돌려 작업 중 tracked 파일을
날린다. 그래서 별도 worktree/브랜치에서 작업했다(라이브 자동배포도 안 건드림).

---

## ✅ 지금까지 완료된 것 (전부 커밋됨, TDD)

### A. 성격 부각 (전체 모드)
- 6종 coreDirective는 이미 `app/policies/agent_personality_profiles.yaml`에 사용자 표 문구로
  존재함이 확인됨(전제-근거-결론 / 유치원 선생님 / 직설 / 4차원 / 개조식 / 비꼬는 반말).
  → **추가 강화는 B 작업 안에서 reaction/wrap 프롬프트에 persona directive를 주입하는 것으로 반영.**
  (YAML 자체는 이미 충분히 생생해서 이번엔 텍스트 교체를 최소화함. 더 세게 원하면 노트북에서 조정.)

### B. 확률적 다중답변 피드백 (기본개념모드 전용) — 핵심 신규
- **신규 순수함수 플래너**: `app/services/studymate_discussion_planner.py`
  - `plan_discussion(agent_ids, seed, min_acts=3, max_acts=7)` → `SpeechAct` 리스트
  - 행위유형: `DIRECT_ANSWER`(기본 라운드) / `REACTION`(다른 에이전트에 반박·보완) / `WRAP`(사용자용 정리)
  - 답변(DIRECT+REACTION) 수 **[3,7] 확률 클램프**, 가중치 중심 ~4-5. 첫=DIRECT, 끝=WRAP 보장.
  - 가중 셔플, 자기자신 반응 금지, 직전 동일쌍 반복 회피, 2명 패딩/8명 캡 엣지 처리.
- **라이브 배선**: `app/services/orchestrator_service.py`
  - `build_orchestrator_stream`이 basic/default + 비잡담 + planner ON일 때
    `_run_discussion_planner_stream`으로 분기(아니면 기존 1인1답 폴백).
  - 신규 헬퍼: `_discussion_planner_enabled / _discussion_seed / _discussion_band /
    _followup_suggestions / _generate_reaction / _generate_wrap / _run_discussion_planner_stream`.
  - SSE `agent_answer`에 **`actType`/`replyTo` 필드 추가**. `all_complete`에 **`followUpSuggestions`**(재개입 칩).
  - "사용자 중심" 하드보장: 첫 발화 직답 / REACTION 프롬프트에 "결국 사용자에게 설명" 못박음 /
    마지막 WRAP은 한 줄 결론+다음 질문 / 끝에 재개입 칩.
- **안전장치(env)**:
  - `STUDYMATE_DISCUSSION_PLANNER` (기본 on, `off`면 기존 1인1답 즉시 롤백)
  - `STUDYMATE_DISCUSSION_SEED` (테스트 재현)
  - `STUDYMATE_DISCUSSION_MIN` / `STUDYMATE_DISCUSSION_MAX` (기본 3 / 7)

### 테스트 (TDD)
- 신규 `tests/test_studymate_discussion_planner.py` (15) — 플래너 불변식/분포/엣지
- 신규 `tests/test_studymate_discussion_stream.py` (9) — 스트림 통합(밴드/actType/replyTo/재개입칩/모드게이팅)
- `tests/test_studymate_per_agent_pacing.py` 2건 — 레거시 1인1답 계약이라 `PLANNER=off` 핀 추가
- 확인: `discussion_planner + discussion_stream + per_agent_pacing + personality_policy` = **73 passed**
- `test_studymate_personality_label_contract::test_mixed_agents_each_keep_own_label` — agentId 없는
  에이전트에서 키 충돌하던 것 **수정 완료**(플래너를 위치 인덱스로 키잉).

---

## ⏳ 노트북에서 이어서 할 일 (오류 테스트 마저)

1. **전체 회귀 스위프**:
   ```
   cd fastapi
   .venv/bin/python -m pytest tests/ -q
   ```
   - ⚠️ **사전존재 실패(내 작업과 무관)**: `tests/test_major_analysis_*` 4개가
     `ImportError: cannot import name '_attach_page_schema'`로 collection 에러. base(LLM-clean)에서
     이미 깨져 있음 → 내 변경과 별개로 따로 처리.
   - ⚠️ `test_studymate_personality_label_contract.py` 일부는 **실 ollama**(localhost:11434)를 호출함.
     ollama가 404/미기동이면 흔들림. ollama 띄우거나 해당 케이스 mock 보강 필요.
2. **실 LLM E2E 스모크**: ollama qwen3로 basic 모드 스트림 한 번 돌려서
   - agent_answer 개수가 매 시드마다 3~7 사이로 흔들리는지
   - REACTION이 진짜 상대 답을 받아 보충/반박하는지(사용자에게 말하는 톤 유지)
   - WRAP이 한 줄 결론+다음 질문으로 끝나는지 눈으로 확인.
3. **프론트 렌더**: `actType`/`replyTo`/`followUpSuggestions`를 프론트가 소비하도록 연결
   (B 에이전트가 A에게 반응 → "↪ 전문봇에게" 식 표시, 재개입 칩 버튼). 프론트는 EC2 빌드 필요.
4. (선택) 성격을 더 세게 원하면 YAML coreDirective/temperature 추가 튜닝.

## 노트북에서 코드 가져오는 법
이 브랜치는 ai07 로컬 worktree에 커밋돼 있다. 노트북이 별도 클론이면 **feature 브랜치를 origin에
푸시**해야 받을 수 있다(이건 LLM-clean이 아니므로 **자동배포 안 됨, 안전**):
```
# ai07에서 (사용자 승인 후):
cd /home/ai07/capstoneLLM-studymate-wt
git push -u origin feature/studymate-personality-discussion
# 노트북에서:
git fetch origin && git checkout feature/studymate-personality-discussion
```
라이브 반영은 따로: 검증 끝나면 `LLM-clean`에 머지+push → autodeploy → `studybridge-ai` restart.

## 변경 파일
- `app/services/studymate_discussion_planner.py` (신규)
- `app/services/orchestrator_service.py` (B 배선 + 헬퍼)
- `tests/test_studymate_discussion_planner.py` (신규)
- `tests/test_studymate_discussion_stream.py` (신규)
- `tests/test_studymate_per_agent_pacing.py` (레거시 2건 PLANNER=off 핀)
- `docs/superpowers/specs/2026-06-23-studymate-*` (설계+핸드오프)
