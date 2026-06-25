# StudyBridge Qwen3-14B QLoRA 데이터셋 & 학습 파이프라인 설계

- 작성일: 2026-06-25
- 베이스 모델: **Qwen3-14B** (HF, 운영 Ollama `qwen3:14b`와 동일 계열)
- 학습 방식: QLoRA, nf4 4-bit, batch=1, LoRA target = `q_proj,k_proj,v_proj,o_proj`
- GPU: RTX 5070 Ti 16GB (운영 FastAPI 서버와 공존)
- 목적: **지식 암기가 아니라** StudyBridge의 답변 형식 / 학습모드 / 퀴즈 생성 / 검증·반박 구조 / 교수 캐릭터 일관성 학습

> 위치 주: 브레인스토밍 기본 스펙 경로(`docs/superpowers/specs/`) 대신, 사용자 범위 제약("모든 산출물은 `fastapi/app/training/studybridge_ft/` 아래로만")에 따라 본 문서를 해당 디렉터리 하위에 둔다.

---

## 1. 범위 및 불변 제약 (Hard Constraints)

- **코드 범위는 `fastapi/app/training/studybridge_ft/` 아래로만 제한한다.**
- 기존 운영 API, serving 코드, Spring, React, 배포 설정(docker-compose, nginx, systemd 등)은 **수정하지 않는다.**
- 코드는 **commit+push 가능한 durable artifact**로 만든다. autodeploy/reset(이 리포는 ~2분마다 origin/LLM-clean으로 reset)으로 미커밋 파일이 소실되지 않도록 **의미 있는 단위마다 commit** 한다.
- **대용량 데이터·모델·로그·체크포인트는 절대 git에 넣지 않는다.** 기본 작업 디렉터리는 `~/studybridge-ft/`.

### 저장 정책 (SSOT)

| 종류 | 위치 |
|---|---|
| 코드 / `config.example.yaml` / `README.md` / eval / validator / train script / 본 설계문서 | **repo**: `fastapi/app/training/studybridge_ft/` |
| `train.jsonl` / `valid.jsonl` / `test.jsonl` / raw samples / outputs / logs / cache / checkpoints | **repo 밖**: `~/studybridge-ft/` |

- `.gitignore`에 다음이 포함되어야 한다(현재 없음 → 추가): `data/`, `outputs/`, `logs/`, `checkpoints/`, `cache/`, `*.safetensors`, `*.bin`, `*.pt`, 그리고 대용량 `*.jsonl` 산출물. (단 repo 내 소량 fixture/예시는 화이트리스트로 예외 허용)

---

## 2. 아키텍처 — 4개 독립 레이어

```
[1 생성]  category generators (7종) ── ollama qwen3:14b (think=False)
              │  샘플 단위: prompt → 생성 → 파싱
              ▼
[2 검증/정제]  per-category validators + repair(1회 재생성) + sanitize(PII/secret) + dedup(content_hash)
              │  깨진 JSON·역할혼선·빈응답·정답오류·중복 → 폐기 또는 재생성
              ▼
[3 패키징]  bucket(512/1024, 2048 ≤5%) + split 90/5/5(의미중복 제거) + ChatML JSONL
              ▼
[4 학습/평가]  train_qlora.py (Qwen3-14B nf4 b1, fp32 embedding upcast 생략) + eval_studybridge.py (10항목)
```

각 레이어는 독립 실행 가능하고(중간 산출물은 `~/studybridge-ft/`에 단계별 파일로 보존) 단위 테스트 가능하다.

---

## 3. 기존 인프라 재사용 (신규 최소화)

- **재사용**: `dataset_deduplicator`, `training_data_validator`, `scripts/sanitize_text`, `scripts/split_dataset`, `jsonl_exporter`, `scripts/convert_jsonl_to_messages`, `teacher_label_generator`(ollama 호출 래퍼). 단, **이들 기존 파일은 수정하지 않고 import/호출만** 한다(운영 영향 0). 동작이 부족하면 `studybridge_ft` 내부에 얇은 어댑터를 둔다.
- **신규**(전부 `studybridge_ft/` 아래): 7개 카테고리 생성기, 카테고리별 validator, 파이프라인 오케스트레이터, `train_qlora.py`(Qwen3-14B 전용), `eval_studybridge.py`, 30k 야간 배치 스크립트, `config.example.yaml`, `README.md`.
- `train_qlora.py`는 이번 세션에서 실증한 설정으로 신규 작성: **Qwen3-14B + nf4 + fp32 embedding upcast 생략(수동 grad checkpointing + enable_input_require_grads) + TRL 1.6 API(`SFTConfig`/`SFTTrainer`) + qwen3 chat template(enable_thinking=False)**.

---

## 4. 생성 엔진

- 백엔드: 로컬 Ollama `qwen3:14b`, **think=False 필수**(qwen3 thinking이 num_predict를 소진해 빈 응답 유발).
- 동시성: 단일 16GB GPU가 운영과 공유되므로 보수적(직렬 또는 낮은 병렬도). 야간 배치에서만 상향.
- 각 샘플 파이프라인: 프롬프트(시스템+few-shot) → 생성 → 파싱 → **validator** → 실패 시 **repair 1회 재생성** → 그래도 실패 시 폐기 → sanitize → content_hash dedup → 저장.
- 시스템/사용자 프롬프트는 **과도하게 길게 반복하지 않는다**(토큰 절약 + 형식 안정).

---

## 5. 7개 카테고리 — 수량 및 검증 계약

생성기와 검증기는 1:1로 동봉한다.

| # | 카테고리 | 수 | 핵심 검증 |
|--|--|--|--|
| 1 | 일반 학습 설명 | 8,000 | 구조 **정의→원리→예시→오개념 경고→확인 질문**, 자연스러운 전문 한국어, 빈 응답 금지 |
| 2 | 자료 요약/키워드/QA | 5,000 | 근거 없으면 추측 금지 → **"자료 내 근거 부족"** 으로 답, 환각 억제 |
| 3 | 퀴즈 생성 | 5,000 | 필드 `question, choices, answer, explanation, difficulty, source_hint` 필수, 정답 인덱스 유효(choices 범위 내), JSON 무결성, 정답 오류 제거 |
| 4 | 소크라테스 | 3,000 | 아래 5.4 |
| 5 | 토론/반박/검증 | 3,000 | 아래 5.5 |
| 6 | 멀티에이전트 교수 캐릭터 | 3,000 | 아래 5.6 |
| 7 | 실패방지/형식 안정화 | 3,000 | 빈 응답·답변 잘림·형식 붕괴 방지(네거티브 + 회복 샘플) |

### 5.4 소크라테스 검증
- 구조: **질문 → 힌트 → 사고 유도 → 부분 정리 → 최종 정리**
- 정답을 **첫 문장에 바로 노출하지 않음**
- **최소 2개 이상의 유도 질문** 포함

### 5.5 토론/반박/검증 검증
- **주장 요약, 반박, 재반박 가능성, 검증 기준, 결론** 포함
- 단순 찬반이 아니라 **논증 구조**를 유지

### 5.6 멀티에이전트 교수 캐릭터 검증
- 캐릭터명/역할/말투 **혼선 금지**
- 특정 교수에게 질문했는데 **다른 교수가 답하는 패턴 금지**
- **3명 모두 같은 답변을 반복하는 패턴 금지**

### 공통 품질 게이트(전 카테고리)
- assistant 답변 **빈 문자열 금지**
- 깨진 JSON / 중복 / 개인정보(PII) / API 키 / 서버 접속정보 **제거**
- 한국어 자연스러움·전문성 휴리스틱 통과

---

## 6. 데이터 형식 (ChatML JSONL)

```json
{"messages":[
  {"role":"system","content":"StudyBridge 시스템 역할 지시문"},
  {"role":"user","content":"사용자 질문 또는 작업 요청"},
  {"role":"assistant","content":"정답 응답"}
]}
```

퀴즈 카테고리의 구조화 필드(question/choices/answer/explanation/difficulty/source_hint)는 assistant content 내부의 JSON으로 직렬화하며, 검증기는 그 JSON을 파싱·검증한다. 프론트엔드가 기대하는 응답 필드와 호환되도록 키 이름을 유지한다.

---

## 7. 학습 설정

- `max_seq_length`: 1024 기본
- 버킷팅: short → **512 bucket**, long → **1024 bucket**. **2048 샘플은 전체의 5% 이하**로 제한.
- epoch: **2 기본**, loss/검증셋 품질에 따라 **3까지 확장**.
- split: **train/valid/test = 90/5/5**. valid/test는 학습셋과 **의미 중복 없음**(content_hash + 근사중복 제거).
- QLoRA: nf4, batch=1, LoRA r=16/alpha=32/dropout=0.05, target `q,k,v,o`. **fp32 embedding upcast 생략**(16GB 운영 공존 필수). grad checkpointing(use_reentrant=False) + enable_input_require_grads.
- 출력: `~/studybridge-ft/outputs/qwen14b-studybridge-lora/`, 학습 로그.

> 근거(이번 세션 실측): 표준 `prepare_model_for_kbit_training`은 임베딩 fp32 업캐스트로 로드 13.15GB → 운영 1.4GB 공존 시 OOM. 업캐스트 생략 시 로드 10.03GB로 공존 학습 성공. 처리량(batch1): seq512 ≈1.54 step/s, seq1024 ≈0.85 step/s.

---

## 8. 검증 — `eval_studybridge.py` (학습 후 10항목)

1. 일반 개념 설명 품질
2. 자료 기반 질의에서 환각 억제
3. 객관식 퀴즈 JSON 형식 안정성
4. 소크라테스 모드 질문 흐름
5. 토론 모드 반박/재반박 구조
6. 교수 캐릭터별 말투 분리
7. 빈 응답 방지
8. 긴 질문에서 답변 잘림 방지
9. RAG 근거 부족 상황에서 추측 금지
10. StudyBridge 프론트엔드가 기대하는 응답 필드와 호환성

판정은 결정론적 규칙(형식/구조/필드) + 필요한 항목에 한해 LLM-judge를 혼합한다. 결과는 `~/studybridge-ft/outputs/eval_report_*.md`로 저장.

---

## 9. 산출물

- `~/studybridge-ft/data/train.jsonl`, `valid.jsonl`, `test.jsonl`
- repo: `studybridge_ft/scripts/validate_dataset.py`, `train_qlora.py`, `eval_studybridge.py`, 생성기/검증기 모듈, `config.example.yaml`, `README.md`
- `~/studybridge-ft/outputs/qwen14b-studybridge-lora/`(어댑터)
- 학습 로그, 검증 리포트(repo 밖)

---

## 10. 단계 실행 (이번 세션 = 1~5, 6은 산출물만 준비)

1. **파이프라인 작성** (생성기 7 + 검증기 + 오케스트레이터 + train/eval/validate 스크립트 + config/README + .gitignore 정비) — 의미 단위 commit
2. **시드 약 2,400개 생성** (7카테고리 비율 유지: 8:5:5:3:3:3:3 → 640/400/400/240/240/240/240)
3. **validator 통과** (전 샘플 품질 게이트 + split 90/5/5)
4. **Qwen3-14B QLoRA 1회 학습** (2 epoch)
5. **eval 10항목 리포트 생성**
6. **검증 OK 시** 동일 스크립트로 **3만 야간 배치 스크립트 준비**(실행은 사용자 트리거)

> 본 세션 목표는 **3만 전량 생성이 아니다.** 루프(생성→검증→학습→평가)를 끝까지 증명하고, 스케일업 배치 스크립트를 준비하는 것이다.

---

## 11. 비목표 (Non-Goals / YAGNI)

- 3만 전량 생성(야간 배치로 분리)
- 운영 서빙 연동(어댑터 merge→GGUF→Ollama 교체)는 별도 후속 작업
- 자동 재학습 상시화(단일 GPU SPOF라 비권장; 새벽 1회성 배치만)
- 기존 운영/serving/Spring/React/배포 설정 변경
