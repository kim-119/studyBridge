# StudyMate 멀티에이전트 작업 인수인계서 (2026-06-23, 최신)

> 기준 커밋: `3f0336f7` (origin/LLM-clean). 이 문서는 StudyMate "교수님들과 대화" 멀티에이전트
> 개편 작업 전체 + 라이브 운영/배포 구조를 정리한다.

## 1. 무엇을 했나 (한눈에)
StudyMate 멀티에이전트를 **단일 LLM 호출 → 에이전트별 순차 호출(per-agent)**로 재구성:
- 답변이 **하나씩 4초 간격**으로 등장(스트림 페이싱)
- **6종 성격을 행동 지시문(coreDirective)으로 강하게 주입** (전문적/친근함/솔직함/독특함/효율적/냉소적)
- **조건부 동료 피드백**: 앞 에이전트 답을 뒤 에이전트가 받아 보충/반박/피드백
- **욕설만 차단**, 인사·잡담도 에이전트가 대화로 받음
- 프론트: 교수 말풍선(닫기·미리보기/더보기), 마인드맵 토글, hover 라벨 위치, 마크다운 렌더, 방 전환 잔상 제거
- **CI/CD에 fastapi 자동배포 추가** + EC2 fastapi를 systemd 서비스화

## 2. 시스템 토폴로지
- **ai07** (`~/capstoneLLM`): 개발/로컬 GPU 머신. **Ollama(qwen3:14b)** 가 여기서 추론. systemd `studybridge-ai`(hotfix_main:app) + EC2로 reverse SSH 터널.
- **EC2** (`ip-10-0-1-215`, `~/studyBridge`): Spring/Nginx/프론트(dist) + **라이브 FastAPI**(systemd `studybridge-fastapi`, hotfix_main:app, :8000).
- 라이브 엔트리포인트는 **항상 `hotfix_main:app`** (= `from main import app` + `/api/ai/multi-chat/stream` compat 라우터). `main:app` 단독은 stream 라우트 없음 → 404.

## 3. 라이브 호출 경로 (스트림 = 오케스트레이터)
```
브라우저 → EC2 Nginx → FastAPI(hotfix_main:app)
  → multi_chat_stream_compat.build_stream_generator
  → multi_agent_service._build_stream_generator_impl
       ├ ABUSE(욕설) → run_direct_reply_stream (차단)
       └ 그 외 전부 → orchestrator_service.build_orchestrator_stream  ← 오케스트레이터(per-agent)
```
확인법(EC2): `journalctl -u studybridge-fastapi --since "3 min ago" | grep "\[Orchestrator\]"`

## 4. 변경 파일

### 백엔드 (`fastapi/`)
| 파일 | 내용 |
|---|---|
| `app/services/orchestrator_service.py` | per-agent 순차 호출, 4초 페이싱(`_min_gap_seconds`, env), 단일 에이전트 프롬프트 빌더, 조건부 동료 피드백(`_cross_feedback_enabled`), SSE 라벨(personality/knowledge) 재계산, all_complete.messages |
| `app/services/personality_prompt_builder.py` | `coreDirective`를 **customInstruction보다 우선** 적용, 프론트 영문키(honest/efficient/cynical/unique/professional/friendly) → 백엔드 성격 매핑 |
| `app/policies/agent_personality_profiles.yaml` | 6종 성격에 `coreDirective`(사용자 verbatim 행동 지시문) 추가 |
| `app/services/multi_agent_service.py` | 스트림 하드스톱을 **ABUSE만**으로 축소(인사·잡담 통과) |
| `tests/test_studymate_per_agent_pacing.py` | 신규 테스트(성격 매핑/스트림/페이싱/피드백/우선순위), 24 케이스 |

### 프론트엔드 (`frontend/`)
| 파일 | 내용 |
|---|---|
| `components/studymate/pixel/ProfessorSpeechBubble.jsx` (신규) | 교수 말풍선: 미리보기120자+더보기/접기, × 닫기 |
| `components/studymate/pixel/PixelProfessorStage.jsx` | `bubbles` prop으로 교수별 말풍선 렌더 |
| `components/studymate/RichText.jsx` (신규) | 경량 마크다운 렌더러(채팅탭/교수뷰 공유) |
| `components/studymate/AgentDiscussionThread.jsx` | 본문을 RichText로 렌더(마크다운 `**` 처리) |
| `pages/StudyMate.jsx` | `professorBubbles`/`showMindmap` 상태, 마인드맵 토글, 방 전환 시 교수뷰 잔상 초기화 |
| `components/studymate/pixel/pixelProfessor.css` | 무대 확대, sprite 스케일↑, hover 라벨 머리위→발밑, 말풍선/닫기 스타일 |

### 운영/CI (`ops/`, `.github/`)
| 파일 | 내용 |
|---|---|
| `ops/studybridge-fastapi.service` (신규) | EC2 fastapi systemd 유닛(hotfix_main:app, Restart=always, enabled) |
| `.github/workflows/cd.yml` | **fastapi-deploy 잡 추가**: fastapi/ 또는 ops/유닛 변경 시 EC2 ssh→git reset --hard SHA→systemd 재기동. (frontend/backend 배포는 기존) |

## 5. 환경변수 (운영 튜닝)
- `STUDYMATE_MIN_ANSWER_GAP_SECONDS` — 답변 사이 최소 간격(초). 기본 4.
- `STUDYMATE_CROSS_FEEDBACK` — `auto`(기본)/`on`/`off`. 동료 피드백 토글. auto = 2명↑ & 인사/잡담 아닐 때.
- `AI_ORCHESTRATOR_MAX_TOKENS` — 에이전트당 max_tokens(기본 4096).

## 6. 배포 (전부 push만으로 자동)
| 영역 | 트리거 | 동작 |
|---|---|---|
| frontend | `frontend/` 변경 push | CD: npm build→EC2 scp→nginx reload |
| Spring | `backend/`·`docker-compose.yml` 변경 | CD: docker 빌드→compose recreate |
| **fastapi(AI)** | `fastapi/`·`ops/유닛` 변경 | CD: EC2 git sync→systemd 재기동 |
- 수동 nohup/pkill 불필요(systemd가 자동 재시작/부팅 기동).

## 7. 커밋 이력 (이 작업 범위)
```
ed72c029 per-agent 순차 답변(4초 페이싱)+성격
3c6655a6 평범한 대화 허용+대화흐름+조건부 동료피드백+말풍선 닫기/라벨 발밑
28fb83d3 동료피드백 잡담판단 하드코딩 키워드→guardrail 라우터 재사용
79eebbcc 교수 뷰 마크다운 렌더(RichText 공유)+방 전환 잔상 초기화
c5850ddd 6종 성격 coreDirective를 customInstruction보다 우선(반말 성격 반말 강제)
369c097c ci(cd): fastapi 자동 배포 추가(EC2 systemd 서비스화)
01e0c5ae fix(cd): 과거 mask 해제 후 유닛 설치
4bb1d297 fix(cd): 포트 정리 pkill→fuser(스크립트 자기종료 방지)
91e69dd5 프론트 영문 성격키 매핑+짧은질문 피드백 허용+동료반박 이름지목
4287ee25 동료 피드백 정확한 이름 지목+복붙 금지
4e9c3c97 test 단언 수정
0942f0c9 의도 분류기 비활성화(일상 대화에도 성격 적용)         # 협업 커밋
ee8ce395 잡담/불만 최우선 감지 및 성격 톤 강제 주입             # 협업 커밋
3f0336f7 기본 모드 '친구처럼 자연스럽게' 지시문 제거(성격 희석 해결)  # 협업 커밋 (HEAD)
```

## 8. 운영 함정 / 디버깅 메모
- **포트 8000 충돌**: 같은 머신에서 `main:app`(stream 없음)이 8000 선점 → `hotfix_main:app`이 Errno98 크래시루프 → SSE 404. 정리: 레거시 종료(`fuser -k 8000/tcp`) + 정상 서비스 재기동.
- **과거 `systemctl mask` 잔재**(/dev/null 심볼릭) → enable 실패. `unmask` 후 설치.
- **`pkill -f "uvicorn..."` 금지**: 배포 스크립트 자신을 매칭해 SIGTERM(143). 포트 기준 `fuser -k` 사용.
- **ai07 autodeploy 타이머**가 origin과 다르면 reset --hard로 미커밋 변경 소실 → 작업은 항상 commit+push.

## 9. 알려진 이슈 / TODO
- [ ] **성격 겹침: 솔직함 ↔ 냉소적** — 둘 다 반말 직설 비판이라 답변이 거의 동일. (제안: 솔직함=존댓말 팩트직설, 냉소적=반말 비꼼으로 분리)
- [ ] 동료 피드백 시 가끔 잘못된 이름 지목/복붙 → 4287ee25에서 보강했으나 모델 의존, 재확인 필요
- [ ] (선택) 기본 모드 상호 반박을 **시각 카드**로(interaction_event emit → ProfessorInteractionTimeline)
- [ ] 비스트림 경로 통일 여부 결정(현재 라이브는 스트림만 사용)

## 10. 테스트
- `cd fastapi && .venv/bin/python -m pytest tests/test_studymate_per_agent_pacing.py -q` → 24 pass
- 라벨 계약: `tests/test_studymate_personality_label_contract.py` → 18 pass (실 Ollama)
