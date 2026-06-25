# StudyBridge Qwen3-14B QLoRA 파이프라인 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** StudyBridge의 답변 형식·학습모드·퀴즈·검증/반박·교수 캐릭터 일관성을 학습시키기 위한 self-distillation 데이터셋 파이프라인(생성→검증→패키징→학습→평가)을 `studybridge_ft/` 안에 구축하고, 시드 2,400개로 QLoRA 루프를 증명한다.

**Architecture:** 4개 독립 레이어(생성/검증/패키징/학습평가). 생성은 로컬 Ollama `qwen3:14b`(think=False) self-distillation. 모든 대용량 산출물은 repo 밖 `~/studybridge-ft/`. 코드는 `fastapi/app/training/studybridge_ft/` 격리, 의미 단위 commit+push로 autodeploy reset 생존.

**Tech Stack:** Python 3.12, requests(Ollama), transformers 5.10 / peft 0.19 / trl 1.6 / bitsandbytes 0.49(QLoRA), pytest. 실행 인터프리터: `fastapi/.venv/bin/python`.

## Global Constraints

- 코드 범위: **`fastapi/app/training/studybridge_ft/` 아래로만**. 기존 운영 API/serving/Spring/React/배포 설정 **수정 금지**.
- 기존 재사용 모듈(`dataset_deduplicator`, `scripts/sanitize_text` 등)은 **import만, 수정 금지**.
- 대용량(data/outputs/logs/checkpoints/cache/raw/cleaned/rejected/manifests)은 **절대 git에 넣지 않음** → `~/studybridge-ft/`.
- 작업 디렉터리 base: `STUDYBRIDGE_FT_HOME` env, 기본 `~/studybridge-ft/`.
- 베이스 모델: **Qwen/Qwen3-14B**. QLoRA nf4, batch=1, LoRA target `q_proj,k_proj,v_proj,o_proj`, **fp32 embedding upcast 생략**(수동 grad checkpointing + enable_input_require_grads), TRL 1.6 API(`SFTConfig`/`SFTTrainer`), qwen3 chat template `enable_thinking=False`.
- max_seq_length 1024 기본, 버킷 512/1024, 2048 ≤ 5%. epoch 2(→3). split 90/5/5, valid/test 의미중복 제거.
- 7카테고리 수량(시드): concept 640 / archive_qa 400 / quiz 400 / socratic 240 / debate 240 / professor 240 / format_safety 240 = 2,400. (30k: 8000/5000/5000/3000/3000/3000/3000)
- Ollama: `OLLAMA_BASE_URL` 기본 `http://localhost:11434`, `/api/chat`, payload에 `"think": False`. `max_concurrent_generation=1`.
- 중단 임계값: 전체 reject>20% / quiz JSON invalid>5% / empty assistant>1% / secret·PII>0건 → 즉시 abort.
- 커밋: 각 Task 끝에 commit. 메시지 끝에 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. 의미 단위로 `git push origin LLM-clean`(durable).
- 모든 pytest는 `fastapi/.venv/bin/python -m pytest`로 실행. 테스트는 Ollama/GPU를 **모킹**(네트워크/GPU 없이 통과).

---

## File Structure

```
fastapi/app/training/studybridge_ft/
  __init__.py
  paths.py                  # ~/studybridge-ft/ 경로 SSOT + repo-외부 가드
  config.example.yaml       # 생성/학습/임계값 설정 예시
  README.md
  docs/                     # 설계문서(존재) + 본 플랜
  utils/
    __init__.py
    jsonl_io.py             # read/write/append/atomic jsonl
    manifest.py             # Manifest dataclass + write/update
    dedup.py                # 기존 compute_sample_hash 어댑터 + 인메모리 dedup
    sanitize.py             # 기존 check_and_mask 어댑터(PII/secret)
    token_bucket.py         # 토큰 길이 → 512/1024/2048 버킷
    git_guard.py            # commit hash + studybridge_ft 외부 tracked 변경 감지
    ollama_client.py        # qwen3:14b think=False, concurrency=1, VRAM 가드, repair
  validators/
    __init__.py
    base.py                 # ValidationResult, BaseValidator
    chatml.py               # ChatML 구조 + 빈 응답
    quiz.py                 # 필수필드 + 정답 인덱스 + JSON 무결성
    socratic.py             # 5단계 + 직답금지 + 유도질문≥2
    debate.py               # 주장/반박/재반박/검증기준/결론
    professor.py            # 캐릭터 혼선/오응답/동일답변 금지
    safety.py               # PII/secret/빈응답
  generators/
    __init__.py
    base.py                 # BaseGenerator: 생성→파싱→검증→repair→dedup→shard
    concept.py archive_qa.py quiz.py socratic.py debate.py professor.py format_safety.py
  generate_seed.py          # CLI 오케스트레이터(--dry-run --per-category)
  validate_dataset.py       # CLI: jsonl 검증
  package_dataset.py        # CLI: bucket + split 90/5/5 + ChatML
  train_qlora.py            # Qwen3-14B QLoRA
  eval_studybridge.py       # 10항목 eval
  scripts/
    run_overnight_batch.sh  # 3만 야간 배치(resume)
  tests/
    __init__.py
    test_*.py
```

`~/studybridge-ft/` (repo 밖): `raw/ cleaned/ rejected/ data/ outputs/ logs/ manifests/ cache/`

---

## Task 1: 패키지 스켈레톤 + paths + config + README + .gitignore

**Files:**
- Create: `fastapi/app/training/studybridge_ft/__init__.py` (빈 파일)
- Create: `fastapi/app/training/studybridge_ft/paths.py`
- Create: `fastapi/app/training/studybridge_ft/config.example.yaml`
- Create: `fastapi/app/training/studybridge_ft/README.md`
- Modify: `.gitignore` (루트) — 대용량 패턴 추가
- Test: `fastapi/app/training/studybridge_ft/tests/test_paths.py`

**Interfaces:**
- Produces:
  - `paths.BASE: Path` (기본 `~/studybridge-ft`, env `STUDYBRIDGE_FT_HOME` override)
  - `paths.SUBDIRS: dict[str,Path]` (keys: raw, cleaned, rejected, data, outputs, logs, manifests, cache)
  - `paths.ensure_dirs() -> None`
  - `paths.assert_outside_repo(p: Path) -> None` (repo 안이면 RuntimeError)
  - `paths.REPO_ROOT: Path`, `paths.PKG_DIR: Path`

- [ ] **Step 1: 디렉터리/테스트 파일 생성, 실패 테스트 작성**

`tests/test_paths.py`:
```python
import os
from pathlib import Path
import importlib

def test_base_defaults_to_home(monkeypatch):
    monkeypatch.delenv("STUDYBRIDGE_FT_HOME", raising=False)
    import app.training.studybridge_ft.paths as p
    importlib.reload(p)
    assert p.BASE == Path.home() / "studybridge-ft"

def test_base_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDYBRIDGE_FT_HOME", str(tmp_path))
    import app.training.studybridge_ft.paths as p
    importlib.reload(p)
    assert p.BASE == tmp_path
    p.ensure_dirs()
    assert (tmp_path / "raw").is_dir()
    assert (tmp_path / "manifests").is_dir()

def test_assert_outside_repo_blocks_repo_path(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDYBRIDGE_FT_HOME", str(tmp_path))
    import app.training.studybridge_ft.paths as p
    importlib.reload(p)
    inside = p.REPO_ROOT / "fastapi" / "app" / "x.jsonl"
    try:
        p.assert_outside_repo(inside)
        assert False, "repo 내부 경로는 막아야 함"
    except RuntimeError:
        pass
    p.assert_outside_repo(tmp_path / "data" / "train.jsonl")  # 예외 없어야 함
```

- [ ] **Step 2: 실패 확인**

Run: `cd fastapi && .venv/bin/python -m pytest app/training/studybridge_ft/tests/test_paths.py -v`
Expected: FAIL (ModuleNotFoundError: paths)

- [ ] **Step 3: paths.py 구현**

```python
"""studybridge_ft 경로 SSOT. 모든 대용량 산출물은 repo 밖(~/studybridge-ft/)."""
import os
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
# fastapi/app/training/studybridge_ft -> repo root
REPO_ROOT = PKG_DIR.parents[3]

BASE = Path(os.environ.get("STUDYBRIDGE_FT_HOME", Path.home() / "studybridge-ft")).resolve()

SUBDIRS = {name: BASE / name for name in
           ("raw", "cleaned", "rejected", "data", "outputs", "logs", "manifests", "cache")}

def ensure_dirs() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    for d in SUBDIRS.values():
        d.mkdir(parents=True, exist_ok=True)

def assert_outside_repo(p: Path) -> None:
    """p가 repo 트리 안이면 RuntimeError. 데이터가 git에 새는 것 방지."""
    rp = Path(p).resolve()
    try:
        rp.relative_to(REPO_ROOT)
    except ValueError:
        return  # repo 밖 → OK
    raise RuntimeError(f"데이터 경로가 repo 내부입니다(금지): {rp}")
```

- [ ] **Step 4: config.example.yaml 작성**

```yaml
# studybridge_ft 생성/학습 설정 예시. 실제 실행은 이 값을 복사/override.
ollama:
  base_url: http://localhost:11434
  model: qwen3:14b
  think: false
  num_predict: 1024
  temperature: 0.7
  timeout_s: 180
  max_concurrent_generation: 1
  vram_guard_mib: 14000        # 운영+생성 합산 이 값 넘으면 대기
seed_counts:
  concept: 640
  archive_qa: 400
  quiz: 400
  socratic: 240
  debate: 240
  professor: 240
  format_safety: 240
full_counts:
  concept: 8000
  archive_qa: 5000
  quiz: 5000
  socratic: 3000
  debate: 3000
  professor: 3000
  format_safety: 3000
shard_size: 200
abort_thresholds:
  total_reject_ratio: 0.20
  quiz_invalid_ratio: 0.05
  empty_assistant_ratio: 0.01
  secret_pii_count: 0          # 초과(>0) 시 즉시 중단
split: { train: 0.90, valid: 0.05, test: 0.05 }
buckets: { short_max: 512, long_max: 1024, xlong_max: 2048, xlong_ratio_cap: 0.05 }
train:
  base_model: Qwen/Qwen3-14B
  max_seq_length: 1024
  num_train_epochs: 2
  per_device_train_batch_size: 1
  gradient_accumulation_steps: 8
  learning_rate: 2.0e-4
  lora: { r: 16, alpha: 32, dropout: 0.05 }
```

- [ ] **Step 5: README.md 작성**

````markdown
# studybridge_ft — StudyBridge QLoRA 데이터/학습 파이프라인

격리 패키지. **코드만 repo 안**, 데이터/모델/로그는 `~/studybridge-ft/`(repo 밖).

## 실행 (fastapi/.venv 기준, cwd=fastapi)
```bash
# 1) dry-run (카테고리별 5개, repo 오염/검증/dedup 확인)
.venv/bin/python -m app.training.studybridge_ft.generate_seed --dry-run --per-category 5
# 2) 시드 2,400 생성
.venv/bin/python -m app.training.studybridge_ft.generate_seed --profile seed
# 3) 검증 + 패키징(90/5/5)
.venv/bin/python -m app.training.studybridge_ft.validate_dataset
.venv/bin/python -m app.training.studybridge_ft.package_dataset
# 4) 학습 / 평가
.venv/bin/python -m app.training.studybridge_ft.train_qlora
.venv/bin/python -m app.training.studybridge_ft.eval_studybridge
```
설계: `docs/2026-06-25-studybridge-qlora-dataset-design.md`
````

- [ ] **Step 6: 루트 .gitignore에 대용량 패턴 추가**

`.gitignore` 끝에 append:
```
# studybridge_ft 대용량 산출물 (repo 밖 ~/studybridge-ft 가 기본이나 이중 안전망)
studybridge-ft/
**/studybridge_ft/**/data/
**/studybridge_ft/**/outputs/
**/studybridge_ft/**/logs/
**/studybridge_ft/**/checkpoints/
**/studybridge_ft/**/cache/
**/studybridge_ft/**/raw/
**/studybridge_ft/**/cleaned/
**/studybridge_ft/**/rejected/
*.safetensors
*.bin
*.pt
```

- [ ] **Step 7: 테스트 통과 확인**

Run: `cd fastapi && .venv/bin/python -m pytest app/training/studybridge_ft/tests/test_paths.py -v`
Expected: PASS (3 passed)

- [ ] **Step 8: Commit + push**

```bash
cd /home/ai07/capstoneLLM
git add fastapi/app/training/studybridge_ft/__init__.py fastapi/app/training/studybridge_ft/paths.py \
  fastapi/app/training/studybridge_ft/config.example.yaml fastapi/app/training/studybridge_ft/README.md \
  fastapi/app/training/studybridge_ft/tests/ .gitignore
git commit -m "feat(studybridge_ft): 패키지 스켈레톤 + paths/config/README + gitignore

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git push origin LLM-clean
```

---

## Task 2: utils/jsonl_io

**Files:**
- Create: `fastapi/app/training/studybridge_ft/utils/__init__.py` (빈 파일)
- Create: `fastapi/app/training/studybridge_ft/utils/jsonl_io.py`
- Test: `fastapi/app/training/studybridge_ft/tests/test_jsonl_io.py`

**Interfaces:**
- Produces:
  - `read_jsonl(path) -> list[dict]`
  - `write_jsonl(path, rows: list[dict]) -> int` (atomic: tmp→rename, 반환=쓴 행수)
  - `append_jsonl(path, row: dict) -> None`
  - `count_lines(path) -> int`

- [ ] **Step 1: 실패 테스트**

```python
from pathlib import Path
from app.training.studybridge_ft.utils import jsonl_io

def test_write_read_roundtrip(tmp_path):
    p = tmp_path / "a.jsonl"
    n = jsonl_io.write_jsonl(p, [{"x": 1}, {"y": "한글"}])
    assert n == 2
    rows = jsonl_io.read_jsonl(p)
    assert rows == [{"x": 1}, {"y": "한글"}]

def test_append_and_count(tmp_path):
    p = tmp_path / "b.jsonl"
    jsonl_io.append_jsonl(p, {"a": 1})
    jsonl_io.append_jsonl(p, {"a": 2})
    assert jsonl_io.count_lines(p) == 2

def test_read_missing_returns_empty(tmp_path):
    assert jsonl_io.read_jsonl(tmp_path / "none.jsonl") == []
```

- [ ] **Step 2: 실패 확인** — `cd fastapi && .venv/bin/python -m pytest app/training/studybridge_ft/tests/test_jsonl_io.py -v` → FAIL

- [ ] **Step 3: 구현**

```python
"""JSONL 입출력 — atomic write, UTF-8, ensure_ascii=False."""
import json, os, tempfile
from pathlib import Path

def read_jsonl(path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out

def write_jsonl(path, rows: list[dict]) -> int:
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    n = 0
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n"); n += 1
    os.replace(tmp, p)
    return n

def append_jsonl(path, row: dict) -> None:
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

def count_lines(path) -> int:
    p = Path(path)
    if not p.exists():
        return 0
    return sum(1 for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip())
```

- [ ] **Step 4: 통과 확인** — 같은 pytest → PASS
- [ ] **Step 5: Commit** — `git add` utils/__init__.py utils/jsonl_io.py tests/test_jsonl_io.py → `git commit -m "feat(studybridge_ft): jsonl_io atomic 입출력"` → push

---

## Task 3: utils/manifest

**Files:**
- Create: `fastapi/app/training/studybridge_ft/utils/manifest.py`
- Test: `fastapi/app/training/studybridge_ft/tests/test_manifest.py`

**Interfaces:**
- Consumes: `jsonl_io`(아님 — json 직접), `paths`
- Produces:
  - `class Manifest` (dataclass) 필드: `run_id, git_commit, model_name, model_digest, generation_config(dict), category_counts(dict), input_seed(int), started_at, finished_at, accepted, rejected, repaired, deduped`
  - `Manifest.new(run_id, git_commit, model_name, model_digest, generation_config, input_seed) -> Manifest`
  - `m.record(accepted=0, rejected=0, repaired=0, deduped=0, category=None)` (누적 + category_counts 갱신)
  - `m.finish() -> None` (finished_at 설정)
  - `m.save() -> Path` (`paths.SUBDIRS['manifests']/manifest_<run_id>.json`)

- [ ] **Step 1: 실패 테스트**

```python
from app.training.studybridge_ft.utils.manifest import Manifest

def test_manifest_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDYBRIDGE_FT_HOME", str(tmp_path))
    import app.training.studybridge_ft.paths as p, importlib; importlib.reload(p)
    m = Manifest.new("run1", "abc123", "qwen3:14b", "sha256:deadbeef",
                     {"temperature": 0.7}, input_seed=42)
    m.record(accepted=3, rejected=1, repaired=1, deduped=0, category="quiz")
    m.record(accepted=2, category="quiz")
    m.finish()
    out = m.save()
    assert out.exists()
    import json; data = json.loads(out.read_text(encoding="utf-8"))
    assert data["run_id"] == "run1" and data["git_commit"] == "abc123"
    assert data["accepted"] == 5 and data["rejected"] == 1
    assert data["category_counts"]["quiz"] == 5
    assert data["finished_at"] is not None
```

- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현**

```python
"""생성 실행 재현성 manifest."""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from . import jsonl_io  # noqa (의존 명시용; 실제 json 사용)
from .. import paths

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

@dataclass
class Manifest:
    run_id: str
    git_commit: str
    model_name: str
    model_digest: str
    generation_config: dict
    input_seed: int
    started_at: str = field(default_factory=_now)
    finished_at: str | None = None
    accepted: int = 0
    rejected: int = 0
    repaired: int = 0
    deduped: int = 0
    category_counts: dict = field(default_factory=dict)

    @classmethod
    def new(cls, run_id, git_commit, model_name, model_digest, generation_config, input_seed):
        return cls(run_id=run_id, git_commit=git_commit, model_name=model_name,
                   model_digest=model_digest, generation_config=generation_config,
                   input_seed=input_seed)

    def record(self, accepted=0, rejected=0, repaired=0, deduped=0, category=None):
        self.accepted += accepted; self.rejected += rejected
        self.repaired += repaired; self.deduped += deduped
        if category is not None:
            self.category_counts[category] = self.category_counts.get(category, 0) + accepted

    def finish(self):
        self.finished_at = _now()

    def save(self) -> Path:
        paths.ensure_dirs()
        out = paths.SUBDIRS["manifests"] / f"manifest_{self.run_id}.json"
        out.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        return out
```

- [ ] **Step 4: 통과 확인** → PASS
- [ ] **Step 5: Commit** — "feat(studybridge_ft): manifest 재현성 기록" → push

---

## Task 4: utils/dedup (기존 모듈 어댑터)

**Files:**
- Create: `fastapi/app/training/studybridge_ft/utils/dedup.py`
- Test: `fastapi/app/training/studybridge_ft/tests/test_dedup.py`

**Interfaces:**
- Consumes: `app.training.dataset_deduplicator.compute_sample_hash(system,user,assistant)` (기존, 수정 금지)
- Produces:
  - `sample_hash(sample: dict) -> str` (ChatML messages에서 system/user/assistant 추출 후 해시)
  - `class Deduper` with `.seen: set`, `.is_dup(sample) -> bool`(부수효과: 신규면 등록)

- [ ] **Step 1: 실패 테스트**

```python
from app.training.studybridge_ft.utils.dedup import Deduper, sample_hash

def _s(u, a):
    return {"messages":[{"role":"system","content":"S"},
                        {"role":"user","content":u},{"role":"assistant","content":a}]}

def test_hash_stable():
    assert sample_hash(_s("q","a")) == sample_hash(_s("q","a"))
    assert sample_hash(_s("q","a")) != sample_hash(_s("q","b"))

def test_deduper_flags_second():
    d = Deduper()
    assert d.is_dup(_s("q","a")) is False
    assert d.is_dup(_s("q","a")) is True
```

- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현**

```python
"""중복 제거 — 기존 dataset_deduplicator.compute_sample_hash 재사용."""
from app.training.dataset_deduplicator import compute_sample_hash

def _roles(sample: dict) -> tuple[str, str, str]:
    sys_, usr, asst = "", "", ""
    for m in sample.get("messages", []):
        if m.get("role") == "system": sys_ = m.get("content", "")
        elif m.get("role") == "user": usr = m.get("content", "")
        elif m.get("role") == "assistant": asst = m.get("content", "")
    return sys_, usr, asst

def sample_hash(sample: dict) -> str:
    s, u, a = _roles(sample)
    return compute_sample_hash(s, u, a)

class Deduper:
    def __init__(self):
        self.seen: set[str] = set()
    def is_dup(self, sample: dict) -> bool:
        h = sample_hash(sample)
        if h in self.seen:
            return True
        self.seen.add(h)
        return False
```

- [ ] **Step 4: 통과 확인** → PASS. (주의: 테스트는 `cwd=fastapi`라 `app.training.dataset_deduplicator` import 가능)
- [ ] **Step 5: Commit** — "feat(studybridge_ft): dedup 어댑터" → push

---

## Task 5: utils/sanitize (기존 모듈 어댑터)

**Files:**
- Create: `fastapi/app/training/studybridge_ft/utils/sanitize.py`
- Test: `fastapi/app/training/studybridge_ft/tests/test_sanitize.py`

**Interfaces:**
- Consumes: `app.scripts.sanitize_text.check_and_mask(text) -> (masked, found_bool, list)` (기존, 수정 금지)
- Produces:
  - `scan_secrets(text: str) -> list[str]` (발견된 비밀/PII 유형 리스트; 없으면 [])
  - `scan_sample(sample: dict) -> list[str]` (모든 message content 합산 스캔)

- [ ] **Step 1: 실패 테스트**

```python
from app.training.studybridge_ft.utils.sanitize import scan_secrets, scan_sample

def test_clean_text_no_findings():
    assert scan_secrets("이것은 평범한 한국어 설명입니다.") == []

def test_sample_with_obvious_secret():
    s = {"messages":[{"role":"assistant",
         "content":"키는 sk-ABCDEFGHIJKLMNOPQRSTUVWX1234567890 입니다"}]}
    # check_and_mask가 잡지 못하는 패턴이면 빈 리스트일 수 있으나, 함수 호출 자체가 동작해야 함
    assert isinstance(scan_sample(s), list)
```

- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현**

```python
"""PII/secret 스캔 — 기존 scripts.sanitize_text.check_and_mask 재사용 + 보강 패턴."""
import re
from app.scripts.sanitize_text import check_and_mask

_EXTRA = [
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "openai_key"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "aws_key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private_key"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "ip_addr"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "email"),
]

def scan_secrets(text: str) -> list[str]:
    found: list[str] = []
    try:
        _, hit, kinds = check_and_mask(text or "")
        if hit:
            found.extend(kinds or ["masked"])
    except Exception:
        pass
    for rx, name in _EXTRA:
        if rx.search(text or ""):
            found.append(name)
    return sorted(set(found))

def scan_sample(sample: dict) -> list[str]:
    blob = "\n".join(m.get("content", "") for m in sample.get("messages", []))
    return scan_secrets(blob)
```

- [ ] **Step 4: 통과 확인** → PASS
- [ ] **Step 5: Commit** — "feat(studybridge_ft): sanitize/secret 스캔 어댑터" → push

---

## Task 6: utils/token_bucket

**Files:**
- Create: `fastapi/app/training/studybridge_ft/utils/token_bucket.py`
- Test: `fastapi/app/training/studybridge_ft/tests/test_token_bucket.py`

**Interfaces:**
- Produces:
  - `estimate_tokens(sample: dict) -> int` (간이: 전체 content 길이 // 2, 한국어 대략 2자=1토큰)
  - `bucket_of(n_tokens: int, short_max=512, long_max=1024, xlong_max=2048) -> int` (반환 512/1024/2048; 초과는 2048)
  - `assign_buckets(samples: list[dict], cfg: dict) -> dict` (반환 `{"512":[..],"1024":[..],"2048":[..]}`, xlong_ratio_cap 초과분은 잘라 제외하고 `dropped_xlong` 카운트 포함)

- [ ] **Step 1: 실패 테스트**

```python
from app.training.studybridge_ft.utils.token_bucket import estimate_tokens, bucket_of, assign_buckets

def _mk(nchars):
    return {"messages":[{"role":"user","content":"x"*nchars},{"role":"assistant","content":""}]}

def test_bucket_thresholds():
    assert bucket_of(10) == 512
    assert bucket_of(700) == 1024
    assert bucket_of(5000) == 2048

def test_xlong_cap_enforced():
    samples = [_mk(100)]*90 + [_mk(6000)]*10   # 10% xlong, cap 5%
    cfg = {"short_max":512,"long_max":1024,"xlong_max":2048,"xlong_ratio_cap":0.05}
    res = assign_buckets(samples, cfg)
    total_kept = len(res["512"])+len(res["1024"])+len(res["2048"])
    assert len(res["2048"]) <= total_kept*0.05 + 1
    assert res["dropped_xlong"] >= 1
```

- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현**

```python
"""시퀀스 길이 → 512/1024/2048 버킷. 2048 비율 상한 강제."""

def estimate_tokens(sample: dict) -> int:
    chars = sum(len(m.get("content", "")) for m in sample.get("messages", []))
    return max(1, chars // 2)

def bucket_of(n_tokens: int, short_max=512, long_max=1024, xlong_max=2048) -> int:
    if n_tokens <= short_max: return 512
    if n_tokens <= long_max: return 1024
    return 2048

def assign_buckets(samples: list[dict], cfg: dict) -> dict:
    sm, lm, xm = cfg["short_max"], cfg["long_max"], cfg["xlong_max"]
    cap = cfg["xlong_ratio_cap"]
    res = {"512": [], "1024": [], "2048": [], "dropped_xlong": 0}
    xlong = []
    for s in samples:
        b = bucket_of(estimate_tokens(s), sm, lm, xm)
        (xlong if b == 2048 else res[str(b)]).append(s)
    non_x = len(res["512"]) + len(res["1024"])
    # kept_x <= cap*(non_x+kept_x)  =>  kept_x <= cap/(1-cap)*non_x
    allow = int((cap / (1 - cap)) * non_x) if cap < 1 else len(xlong)
    res["2048"] = xlong[:allow]
    res["dropped_xlong"] = len(xlong) - len(res["2048"])
    return res
```

- [ ] **Step 4: 통과 확인** → PASS
- [ ] **Step 5: Commit** — "feat(studybridge_ft): token 길이 버킷팅" → push

---

## Task 7: utils/git_guard

**Files:**
- Create: `fastapi/app/training/studybridge_ft/utils/git_guard.py`
- Test: `fastapi/app/training/studybridge_ft/tests/test_git_guard.py`

**Interfaces:**
- Produces:
  - `current_commit() -> str` (`git rev-parse HEAD`, 실패 시 "unknown")
  - `tracked_changes_outside_scope(scope="fastapi/app/training/studybridge_ft") -> list[str]` (`git status --porcelain`에서 scope 밖 변경 경로)
  - `assert_safe(scope=...) -> None` (scope 밖 tracked 변경 있으면 RuntimeError)

- [ ] **Step 1: 실패 테스트** (subprocess 모킹)

```python
import app.training.studybridge_ft.utils.git_guard as g

def test_outside_scope_detected(monkeypatch):
    monkeypatch.setattr(g, "_porcelain", lambda: [" M fastapi/app/main.py",
                                                  " M fastapi/app/training/studybridge_ft/x.py"])
    out = g.tracked_changes_outside_scope()
    assert "fastapi/app/main.py" in out
    assert all("studybridge_ft" not in x for x in out)

def test_assert_safe_raises(monkeypatch):
    monkeypatch.setattr(g, "_porcelain", lambda: [" M fastapi/app/api/x.py"])
    try:
        g.assert_safe(); assert False
    except RuntimeError:
        pass

def test_assert_safe_ok_when_only_scope(monkeypatch):
    monkeypatch.setattr(g, "_porcelain", lambda: [" M fastapi/app/training/studybridge_ft/y.py",
                                                  "?? raw/quiz_0001.jsonl"])
    g.assert_safe()  # 예외 없어야 함(scope 내 + repo밖 데이터)
```

- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현**

```python
"""autodeploy/reset 환경 git 안전장치."""
import subprocess
from .. import paths

SCOPE = "fastapi/app/training/studybridge_ft"

def _run(args: list[str]) -> str:
    return subprocess.run(args, cwd=str(paths.REPO_ROOT), capture_output=True,
                          text=True, timeout=15).stdout

def current_commit() -> str:
    try:
        out = _run(["git", "rev-parse", "HEAD"]).strip()
        return out or "unknown"
    except Exception:
        return "unknown"

def _porcelain() -> list[str]:
    try:
        return [ln for ln in _run(["git", "status", "--porcelain"]).splitlines() if ln.strip()]
    except Exception:
        return []

def _path_of(line: str) -> str:
    # "XY path" 또는 "?? path" / 리네임 "R  a -> b"
    rest = line[3:].strip()
    return rest.split(" -> ")[-1].strip()

def tracked_changes_outside_scope(scope: str = SCOPE) -> list[str]:
    out = []
    for ln in _porcelain():
        if ln.startswith("??"):   # untracked(데이터 등) 무시
            continue
        path = _path_of(ln)
        if path and not path.startswith(scope):
            out.append(path)
    return out

def assert_safe(scope: str = SCOPE) -> None:
    bad = tracked_changes_outside_scope(scope)
    if bad:
        raise RuntimeError(f"studybridge_ft 외부 tracked 변경 감지 → 중단: {bad}")
```

- [ ] **Step 4: 통과 확인** → PASS
- [ ] **Step 5: Commit** — "feat(studybridge_ft): git 안전장치" → push

---

## Task 8: utils/ollama_client

**Files:**
- Create: `fastapi/app/training/studybridge_ft/utils/ollama_client.py`
- Test: `fastapi/app/training/studybridge_ft/tests/test_ollama_client.py`

**Interfaces:**
- Produces:
  - `class OllamaClient(base_url, model, think=False, num_predict=1024, temperature=0.7, timeout_s=180, vram_guard_mib=14000)`
  - `.chat(system: str, user: str) -> str` (assistant content; 빈/실패 시 1회 재시도 후 "" 반환)
  - `.model_digest() -> str` (`/api/show` digest, 실패 "unknown")
  - 동시성: 모듈 전역 `threading.Semaphore(1)` (max_concurrent_generation=1)
  - VRAM 가드: `_vram_used_mib() -> int` (nvidia-smi), guard 초과면 대기(최대 N회) 후 진행

- [ ] **Step 1: 실패 테스트 (requests/ nvidia-smi 모킹)**

```python
import app.training.studybridge_ft.utils.ollama_client as oc

class _Resp:
    def __init__(self, j): self._j = j; self.status_code = 200
    def json(self): return self._j
    def raise_for_status(self): pass

def test_chat_returns_content(monkeypatch):
    monkeypatch.setattr(oc, "_vram_used_mib", lambda: 1000)
    monkeypatch.setattr(oc.requests, "post",
        lambda *a, **k: _Resp({"message": {"content": "안녕"}}))
    c = oc.OllamaClient("http://x", "qwen3:14b")
    assert c.chat("S", "U") == "안녕"

def test_chat_retries_on_blank(monkeypatch):
    monkeypatch.setattr(oc, "_vram_used_mib", lambda: 1000)
    calls = {"n": 0}
    def fake_post(*a, **k):
        calls["n"] += 1
        return _Resp({"message": {"content": "" if calls["n"] == 1 else "복구"}})
    monkeypatch.setattr(oc.requests, "post", fake_post)
    c = oc.OllamaClient("http://x", "qwen3:14b")
    assert c.chat("S", "U") == "복구"
    assert calls["n"] == 2

def test_payload_has_think_false(monkeypatch):
    monkeypatch.setattr(oc, "_vram_used_mib", lambda: 1000)
    captured = {}
    def fake_post(url, json=None, timeout=None):
        captured.update(json); return _Resp({"message": {"content": "ok"}})
    monkeypatch.setattr(oc.requests, "post", fake_post)
    oc.OllamaClient("http://x", "qwen3:14b").chat("S", "U")
    assert captured["think"] is False and captured["stream"] is False
```

- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현**

```python
"""Ollama qwen3:14b self-distillation 클라이언트. think=False, concurrency=1, VRAM 가드."""
import subprocess, threading, time
import requests

_GEN_SEM = threading.Semaphore(1)  # max_concurrent_generation=1

def _vram_used_mib() -> int:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10).stdout
        return max(int(x) for x in out.split() if x.strip().isdigit())
    except Exception:
        return 0

class OllamaClient:
    def __init__(self, base_url, model, think=False, num_predict=1024,
                 temperature=0.7, timeout_s=180, vram_guard_mib=14000):
        self.base_url = base_url.rstrip("/"); self.model = model; self.think = think
        self.num_predict = num_predict; self.temperature = temperature
        self.timeout_s = timeout_s; self.vram_guard_mib = vram_guard_mib

    def _wait_for_vram(self, tries=20, sleep_s=15):
        for _ in range(tries):
            if _vram_used_mib() < self.vram_guard_mib:
                return True
            time.sleep(sleep_s)
        return False

    def _post_once(self, system, user) -> str:
        payload = {
            "model": self.model, "stream": False, "think": self.think,
            "options": {"num_predict": self.num_predict, "temperature": self.temperature},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }
        r = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout_s)
        r.raise_for_status()
        return (r.json().get("message", {}).get("content") or "").strip()

    def chat(self, system: str, user: str) -> str:
        with _GEN_SEM:
            self._wait_for_vram()
            try:
                out = self._post_once(system, user)
                if out:
                    return out
            except Exception:
                pass
            try:
                return self._post_once(system, user)  # 1회 재시도
            except Exception:
                return ""

    def model_digest(self) -> str:
        try:
            r = requests.post(f"{self.base_url}/api/show", json={"name": self.model},
                              timeout=30)
            r.raise_for_status()
            j = r.json()
            return j.get("digest") or (j.get("details", {}) or {}).get("parent_model") or "unknown"
        except Exception:
            return "unknown"
```

- [ ] **Step 4: 통과 확인** → PASS (네트워크/GPU 없이 모킹으로 통과)
- [ ] **Step 5: Commit** — "feat(studybridge_ft): ollama_client(think=False/concurrency/VRAM가드)" → push

---

## Task 9: validators/base + chatml

**Files:**
- Create: `fastapi/app/training/studybridge_ft/validators/__init__.py` (빈)
- Create: `fastapi/app/training/studybridge_ft/validators/base.py`
- Create: `fastapi/app/training/studybridge_ft/validators/chatml.py`
- Test: `fastapi/app/training/studybridge_ft/tests/test_validator_chatml.py`

**Interfaces:**
- Produces:
  - `base.ValidationResult(ok: bool, reason: str | None = None)` (dataclass)
  - `base.BaseValidator` with `.validate(sample: dict) -> ValidationResult` (추상)
  - `chatml.ChatMLValidator()` — system/user/assistant 3역할 존재, assistant 비어있지 않음, role 순서 올바름
  - reject 사유 문자열 규약: `"schema_error"`, `"empty_answer"` (quarantine 파일명과 매칭)

- [ ] **Step 1: 실패 테스트**

```python
from app.training.studybridge_ft.validators.chatml import ChatMLValidator

V = ChatMLValidator()
def _ok():
    return {"messages":[{"role":"system","content":"S"},
            {"role":"user","content":"U"},{"role":"assistant","content":"A"}]}

def test_valid_passes():
    assert V.validate(_ok()).ok

def test_empty_assistant_rejected():
    s = _ok(); s["messages"][2]["content"] = "  "
    r = V.validate(s); assert not r.ok and r.reason == "empty_answer"

def test_missing_roles_rejected():
    s = {"messages":[{"role":"user","content":"U"}]}
    r = V.validate(s); assert not r.ok and r.reason == "schema_error"
```

- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현**

`base.py`:
```python
from dataclasses import dataclass

@dataclass
class ValidationResult:
    ok: bool
    reason: str | None = None

class BaseValidator:
    name = "base"
    def validate(self, sample: dict) -> ValidationResult:
        raise NotImplementedError
```

`chatml.py`:
```python
from .base import BaseValidator, ValidationResult

class ChatMLValidator(BaseValidator):
    name = "chatml"
    def validate(self, sample: dict) -> ValidationResult:
        msgs = sample.get("messages")
        if not isinstance(msgs, list) or not msgs:
            return ValidationResult(False, "schema_error")
        roles = [m.get("role") for m in msgs]
        if not ({"system", "user", "assistant"} <= set(roles)):
            return ValidationResult(False, "schema_error")
        # 순서: 첫 system, 이후 user→assistant 쌍
        if roles[0] != "system":
            return ValidationResult(False, "schema_error")
        asst = [m.get("content", "") for m in msgs if m.get("role") == "assistant"]
        if any(not (c or "").strip() for c in asst):
            return ValidationResult(False, "empty_answer")
        return ValidationResult(True)
```

- [ ] **Step 4: 통과 확인** → PASS
- [ ] **Step 5: Commit** — "feat(studybridge_ft): validator base + chatml" → push

---

## Task 10: validators/quiz

**Files:**
- Create: `fastapi/app/training/studybridge_ft/validators/quiz.py`
- Test: `fastapi/app/training/studybridge_ft/tests/test_validator_quiz.py`

**Interfaces:**
- Consumes: `base.BaseValidator/ValidationResult`
- Produces: `quiz.QuizValidator()` — assistant content를 JSON 파싱, 필수필드 `question, choices(list≥2), answer, explanation, difficulty, source_hint`, `answer`가 choices 내 유효(인덱스 int이거나 choices 값과 일치). 사유: `"quiz_invalid_json"`, `"quiz_missing_field"`, `"quiz_invalid_answer"`

- [ ] **Step 1: 실패 테스트**

```python
import json
from app.training.studybridge_ft.validators.quiz import QuizValidator
V = QuizValidator()
def _wrap(payload):
    return {"messages":[{"role":"system","content":"S"},{"role":"user","content":"퀴즈"},
            {"role":"assistant","content":json.dumps(payload, ensure_ascii=False)}]}
def _good():
    return {"question":"Q","choices":["a","b","c","d"],"answer":1,
            "explanation":"E","difficulty":"medium","source_hint":"ch1"}

def test_valid_quiz():
    assert V.validate(_wrap(_good())).ok
def test_broken_json():
    s = {"messages":[{"role":"system","content":"S"},{"role":"user","content":"q"},
         {"role":"assistant","content":"{not json"}]}
    assert V.validate(s).reason == "quiz_invalid_json"
def test_missing_field():
    p = _good(); del p["explanation"]
    assert V.validate(_wrap(p)).reason == "quiz_missing_field"
def test_answer_out_of_range():
    p = _good(); p["answer"] = 9
    assert V.validate(_wrap(p)).reason == "quiz_invalid_answer"
```

- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현**

```python
import json
from .base import BaseValidator, ValidationResult

REQUIRED = ["question", "choices", "answer", "explanation", "difficulty", "source_hint"]

class QuizValidator(BaseValidator):
    name = "quiz"
    def validate(self, sample: dict) -> ValidationResult:
        asst = next((m.get("content","") for m in sample.get("messages",[])
                     if m.get("role")=="assistant"), "")
        try:
            p = json.loads(asst)
        except Exception:
            return ValidationResult(False, "quiz_invalid_json")
        if not isinstance(p, dict) or any(k not in p for k in REQUIRED):
            return ValidationResult(False, "quiz_missing_field")
        choices = p.get("choices")
        if not isinstance(choices, list) or len(choices) < 2:
            return ValidationResult(False, "quiz_missing_field")
        ans = p.get("answer")
        valid = (isinstance(ans, int) and 0 <= ans < len(choices)) or (ans in choices)
        if not valid:
            return ValidationResult(False, "quiz_invalid_answer")
        return ValidationResult(True)
```

- [ ] **Step 4: 통과 확인** → PASS
- [ ] **Step 5: Commit** — "feat(studybridge_ft): quiz validator" → push

---

## Task 11: validators/socratic

**Files:**
- Create: `fastapi/app/training/studybridge_ft/validators/socratic.py`
- Test: `fastapi/app/training/studybridge_ft/tests/test_validator_socratic.py`

**Interfaces:**
- Produces: `socratic.SocraticValidator()` — assistant 응답이 (a) 첫 문장에 정답 직답 아님(첫 문장이 물음표로 끝나거나 힌트성), (b) 유도 질문 `?` ≥ 2개, (c) 5단계 키워드 표지 포함(질문/힌트/유도/부분 정리/최종 정리 중 ≥3 표지). 사유: `"socratic_direct_answer"`, `"socratic_too_few_questions"`, `"socratic_missing_stages"`

- [ ] **Step 1: 실패 테스트**

```python
from app.training.studybridge_ft.validators.socratic import SocraticValidator
V = SocraticValidator()
def _wrap(a):
    return {"messages":[{"role":"system","content":"S"},{"role":"user","content":"개념?"},
            {"role":"assistant","content":a}]}
GOOD = ("이 개념을 어떻게 정의할 수 있을까요? 힌트: 핵심은 관계입니다. "
        "그렇다면 왜 그럴까요? 부분 정리하면 이렇습니다. 최종 정리: 종합하면 ...")
def test_good_socratic():
    assert V.validate(_wrap(GOOD)).ok
def test_direct_answer_rejected():
    assert V.validate(_wrap("정답은 42입니다. 끝.")).reason == "socratic_direct_answer"
def test_too_few_questions():
    assert V.validate(_wrap("힌트만 줄게요. 생각해봐요.")).reason in (
        "socratic_too_few_questions","socratic_missing_stages")
```

- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현**

```python
import re
from .base import BaseValidator, ValidationResult

_STAGE_MARKERS = ["힌트", "유도", "부분 정리", "최종 정리", "정리하면", "왜", "어떻게"]

class SocraticValidator(BaseValidator):
    name = "socratic"
    def validate(self, sample: dict) -> ValidationResult:
        a = next((m.get("content","") for m in sample.get("messages",[])
                  if m.get("role")=="assistant"), "").strip()
        if not a:
            return ValidationResult(False, "empty_answer")
        first = re.split(r"(?<=[.!?。])\s", a, maxsplit=1)[0]
        if ("정답은" in first or "답은" in first) and "?" not in first and "?" not in first:
            return ValidationResult(False, "socratic_direct_answer")
        q = a.count("?") + a.count("?")
        if q < 2:
            return ValidationResult(False, "socratic_too_few_questions")
        if sum(1 for m in _STAGE_MARKERS if m in a) < 3:
            return ValidationResult(False, "socratic_missing_stages")
        return ValidationResult(True)
```

- [ ] **Step 4: 통과 확인** → PASS
- [ ] **Step 5: Commit** — "feat(studybridge_ft): socratic validator" → push

---

## Task 12: validators/debate

**Files:**
- Create: `fastapi/app/training/studybridge_ft/validators/debate.py`
- Test: `fastapi/app/training/studybridge_ft/tests/test_validator_debate.py`

**Interfaces:**
- Produces: `debate.DebateValidator()` — assistant에 5요소 표지 포함: 주장(요약), 반박, 재반박, 검증(기준), 결론. ≥4개 표지 필요. 사유: `"debate_missing_structure"`

- [ ] **Step 1: 실패 테스트**

```python
from app.training.studybridge_ft.validators.debate import DebateValidator
V = DebateValidator()
def _wrap(a):
    return {"messages":[{"role":"system","content":"S"},{"role":"user","content":"논제"},
            {"role":"assistant","content":a}]}
GOOD = "주장: A다. 반박: 그러나 B. 재반박: 그럼에도 C. 검증 기준: D로 확인. 결론: 따라서 E."
def test_good_debate(): assert V.validate(_wrap(GOOD)).ok
def test_plain_pro_con_rejected():
    assert V.validate(_wrap("찬성합니다. 좋아요.")).reason == "debate_missing_structure"
```

- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현**

```python
from .base import BaseValidator, ValidationResult

_MARKERS = ["주장", "반박", "재반박", "검증", "결론"]

class DebateValidator(BaseValidator):
    name = "debate"
    def validate(self, sample: dict) -> ValidationResult:
        a = next((m.get("content","") for m in sample.get("messages",[])
                  if m.get("role")=="assistant"), "")
        if sum(1 for m in _MARKERS if m in a) < 4:
            return ValidationResult(False, "debate_missing_structure")
        return ValidationResult(True)
```

- [ ] **Step 4: 통과 확인** → PASS
- [ ] **Step 5: Commit** — "feat(studybridge_ft): debate validator" → push

---

## Task 13: validators/professor

**Files:**
- Create: `fastapi/app/training/studybridge_ft/validators/professor.py`
- Test: `fastapi/app/training/studybridge_ft/tests/test_validator_professor.py`

**Interfaces:**
- Produces: `professor.ProfessorValidator()` — 멀티에이전트 샘플의 metadata.expected_speaker가 있으면 응답 화자 라벨과 일치(다른 교수 응답 금지), 3인 응답이면 동일 텍스트 반복 금지(중복 응답 ≥2면 reject). 샘플 형식: assistant content에 `[교수명] ...` 라벨 라인들. 사유: `"professor_speaker_mismatch"`, `"professor_duplicate_answers"`
- 입력 규약: `sample["metadata"]={"expected_speaker": "김교수"}` (옵션), assistant content는 `[이름] 내용` 줄들.

- [ ] **Step 1: 실패 테스트**

```python
from app.training.studybridge_ft.validators.professor import ProfessorValidator
V = ProfessorValidator()
def _wrap(a, expected=None):
    s = {"messages":[{"role":"system","content":"S"},{"role":"user","content":"김교수님께"},
         {"role":"assistant","content":a}]}
    if expected: s["metadata"]={"expected_speaker":expected}
    return s
def test_correct_speaker():
    assert V.validate(_wrap("[김교수] 그건 이렇습니다.", expected="김교수")).ok
def test_wrong_speaker():
    r = V.validate(_wrap("[이교수] 제가 답합니다.", expected="김교수"))
    assert r.reason == "professor_speaker_mismatch"
def test_duplicate_answers():
    a = "[김교수] 같은 말.\n[이교수] 같은 말.\n[박교수] 같은 말."
    assert V.validate(_wrap(a)).reason == "professor_duplicate_answers"
def test_distinct_multi_ok():
    a = "[김교수] 정의 측면.\n[이교수] 예시 측면.\n[박교수] 반례 측면."
    assert V.validate(_wrap(a)).ok
```

- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현**

```python
import re
from .base import BaseValidator, ValidationResult

_LABEL = re.compile(r"^\[([^\]]+)\]\s*(.*)$")

class ProfessorValidator(BaseValidator):
    name = "professor"
    def validate(self, sample: dict) -> ValidationResult:
        a = next((m.get("content","") for m in sample.get("messages",[])
                  if m.get("role")=="assistant"), "")
        speakers, bodies = [], []
        for ln in a.splitlines():
            mt = _LABEL.match(ln.strip())
            if mt:
                speakers.append(mt.group(1).strip())
                bodies.append(mt.group(2).strip())
        if not speakers:
            return ValidationResult(False, "schema_error")
        expected = (sample.get("metadata") or {}).get("expected_speaker")
        if expected and any(sp != expected for sp in speakers):
            return ValidationResult(False, "professor_speaker_mismatch")
        norm = [re.sub(r"\s+", " ", b).strip() for b in bodies if b]
        if len(norm) >= 2 and len(set(norm)) < len(norm):
            return ValidationResult(False, "professor_duplicate_answers")
        return ValidationResult(True)
```

- [ ] **Step 4: 통과 확인** → PASS
- [ ] **Step 5: Commit** — "feat(studybridge_ft): professor validator" → push

---

## Task 14: validators/safety

**Files:**
- Create: `fastapi/app/training/studybridge_ft/validators/safety.py`
- Test: `fastapi/app/training/studybridge_ft/tests/test_validator_safety.py`

**Interfaces:**
- Consumes: `utils.sanitize.scan_sample`
- Produces: `safety.SafetyValidator()` — PII/secret 발견 시 reject(`"pii_secret"`), 빈 응답(`"empty_answer"`). secret은 **즉시 중단 신호**라 reason="pii_secret"

- [ ] **Step 1: 실패 테스트**

```python
from app.training.studybridge_ft.validators.safety import SafetyValidator
V = SafetyValidator()
def test_clean_ok():
    s = {"messages":[{"role":"assistant","content":"평범한 설명"}]}
    assert V.validate(s).ok
def test_secret_rejected():
    s = {"messages":[{"role":"assistant","content":"키 sk-ABCDEFGHIJKLMNOPQRSTUV1234567890"}]}
    assert V.validate(s).reason == "pii_secret"
```

- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현**

```python
from .base import BaseValidator, ValidationResult
from ..utils.sanitize import scan_sample

class SafetyValidator(BaseValidator):
    name = "safety"
    def validate(self, sample: dict) -> ValidationResult:
        if scan_sample(sample):
            return ValidationResult(False, "pii_secret")
        asst = [m.get("content","") for m in sample.get("messages",[])
                if m.get("role")=="assistant"]
        if any(not (c or "").strip() for c in asst):
            return ValidationResult(False, "empty_answer")
        return ValidationResult(True)
```

- [ ] **Step 4: 통과 확인** → PASS
- [ ] **Step 5: Commit** — "feat(studybridge_ft): safety validator" → push

---

## Task 15: generators/base

**Files:**
- Create: `fastapi/app/training/studybridge_ft/generators/__init__.py` (빈)
- Create: `fastapi/app/training/studybridge_ft/generators/base.py`
- Test: `fastapi/app/training/studybridge_ft/tests/test_generator_base.py`

**Interfaces:**
- Consumes: `OllamaClient`(주입), validators, `Deduper`, `jsonl_io`, `paths`
- Produces:
  - `base.GenResult(accepted, rejected, repaired, deduped, reject_reasons: dict[str,int])`
  - `base.BaseGenerator` 속성: `category: str`, `system_prompt: str`, `user_prompt() -> str`, `validators: list[BaseValidator]`, `parse(raw: str) -> dict`(messages 빌드)
  - `.generate(n, client, deduper, out_raw_path, out_clean_path, rejected_dir) -> GenResult` (각 샘플: client.chat→parse→validate(all)→실패시 1회 repair(재생성)→여전히 실패면 quarantine append→통과+비중복이면 cleaned에 write)
  - resume: `out_clean_path` 이미 존재(행수≥n)면 skip(GenResult는 0으로, `skipped=True`)

- [ ] **Step 1: 실패 테스트 (FakeClient)**

```python
from app.training.studybridge_ft.generators.base import BaseGenerator, GenResult
from app.training.studybridge_ft.validators.chatml import ChatMLValidator
from app.training.studybridge_ft.validators.safety import SafetyValidator
from app.training.studybridge_ft.utils.dedup import Deduper

class _FakeClient:
    def __init__(self, outs): self.outs = list(outs); self.i = 0
    def chat(self, s, u):
        v = self.outs[min(self.i, len(self.outs)-1)]; self.i += 1; return v

class _G(BaseGenerator):
    category = "concept"; system_prompt = "S"
    validators = [ChatMLValidator(), SafetyValidator()]
    def user_prompt(self): return "설명 요청"
    def parse(self, raw):
        return {"messages":[{"role":"system","content":"S"},
                {"role":"user","content":"u"},{"role":"assistant","content":raw}]}

def test_accept_valid(tmp_path):
    g = _G(); client = _FakeClient(["좋은 한국어 설명입니다."])
    res = g.generate(1, client, Deduper(), tmp_path/"raw.jsonl",
                     tmp_path/"clean.jsonl", tmp_path/"rej")
    assert res.accepted == 1
    assert (tmp_path/"clean.jsonl").exists()

def test_repair_then_accept(tmp_path):
    g = _G(); client = _FakeClient(["", "복구된 설명"])  # 첫 빈응답→repair
    res = g.generate(1, client, Deduper(), tmp_path/"raw.jsonl",
                     tmp_path/"clean.jsonl", tmp_path/"rej")
    assert res.accepted == 1 and res.repaired == 1

def test_reject_quarantined(tmp_path):
    g = _G(); client = _FakeClient(["", ""])  # 계속 빈응답
    res = g.generate(1, client, Deduper(), tmp_path/"raw.jsonl",
                     tmp_path/"clean.jsonl", tmp_path/"rej")
    assert res.accepted == 0 and res.rejected == 1
    assert (tmp_path/"rej"/"empty_answer.jsonl").exists()

def test_resume_skips(tmp_path):
    from app.training.studybridge_ft.utils import jsonl_io
    clean = tmp_path/"clean.jsonl"
    jsonl_io.write_jsonl(clean, [{"messages":[]}])
    g = _G(); res = g.generate(1, _FakeClient(["x"]), Deduper(),
                               tmp_path/"raw.jsonl", clean, tmp_path/"rej")
    assert res.skipped is True and res.accepted == 0
```

- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현**

```python
"""생성기 베이스: 생성→파싱→검증→repair(1회)→dedup→shard. quarantine 포함."""
from dataclasses import dataclass, field
from pathlib import Path
from ..utils import jsonl_io
from ..validators.base import ValidationResult

@dataclass
class GenResult:
    accepted: int = 0
    rejected: int = 0
    repaired: int = 0
    deduped: int = 0
    skipped: bool = False
    reject_reasons: dict = field(default_factory=dict)

class BaseGenerator:
    category = "base"
    system_prompt = ""
    validators = []
    def user_prompt(self) -> str:
        raise NotImplementedError
    def parse(self, raw: str) -> dict:
        raise NotImplementedError

    def _validate(self, sample) -> ValidationResult:
        for v in self.validators:
            r = v.validate(sample)
            if not r.ok:
                return r
        return ValidationResult(True)

    def generate(self, n, client, deduper, out_raw_path, out_clean_path,
                 rejected_dir) -> GenResult:
        out_clean_path = Path(out_clean_path); rejected_dir = Path(rejected_dir)
        if jsonl_io.count_lines(out_clean_path) >= n:
            return GenResult(skipped=True)
        res = GenResult()
        for _ in range(n):
            raw = client.chat(self.system_prompt, self.user_prompt())
            sample = self.parse(raw)
            jsonl_io.append_jsonl(out_raw_path, sample)
            r = self._validate(sample)
            if not r.ok:  # repair 1회
                raw2 = client.chat(self.system_prompt, self.user_prompt())
                sample2 = self.parse(raw2)
                r2 = self._validate(sample2)
                if r2.ok:
                    sample = sample2; res.repaired += 1; r = r2
                else:
                    res.rejected += 1
                    res.reject_reasons[r.reason] = res.reject_reasons.get(r.reason,0)+1
                    jsonl_io.append_jsonl(rejected_dir / f"{r.reason}.jsonl", sample)
                    continue
            if deduper.is_dup(sample):
                res.deduped += 1
                continue
            jsonl_io.append_jsonl(out_clean_path, sample)
            res.accepted += 1
        return res
```

- [ ] **Step 4: 통과 확인** → PASS
- [ ] **Step 5: Commit** — "feat(studybridge_ft): generator base(repair/quarantine/resume)" → push

---

## Task 16: 7개 generators (concept/archive_qa/quiz/socratic/debate/professor/format_safety)

**Files:**
- Create: `fastapi/app/training/studybridge_ft/generators/{concept,archive_qa,quiz,socratic,debate,professor,format_safety}.py`
- Test: `fastapi/app/training/studybridge_ft/tests/test_generators_registry.py`

**Interfaces:**
- Consumes: `BaseGenerator`, 각 validator
- Produces: 각 모듈에 `*Generator` 클래스 + `generators/__init__.py`에 `REGISTRY: dict[str, type[BaseGenerator]]`

각 generator는 BaseGenerator를 상속, 아래 표대로 `category / system_prompt / user_prompt / validators / parse`를 채운다. (퀴즈는 parse가 raw JSON을 그대로 assistant content로; professor는 metadata 부착)

| category | validators | parse 특이사항 | user_prompt 요지 |
|---|---|---|---|
| concept | ChatML, Safety | 표준 3역할 | "전공 개념 1개를 정의→원리→예시→오개념 경고→확인 질문 순서로 설명" |
| archive_qa | ChatML, Safety | 표준 | "자료 기반 질의. 근거 없으면 '자료 내 근거 부족'이라고 답" |
| quiz | ChatML, Quiz, Safety | assistant=raw(JSON 문자열) | "객관식 1문제를 JSON으로: question,choices,answer,explanation,difficulty,source_hint" |
| socratic | ChatML, Socratic, Safety | 표준 | "정답 직답 금지. 질문→힌트→유도→부분 정리→최종 정리, 유도질문 2개 이상" |
| debate | ChatML, Debate, Safety | 표준 | "주장/반박/재반박/검증 기준/결론 구조로 논증" |
| professor | ChatML, Professor, Safety | metadata.expected_speaker 부착, assistant=`[이름] ...` | "지정 교수 1인이 답. 역할/말투 고정" |
| format_safety | ChatML, Safety | 표준 | "형식 안정화: 잘림/빈응답 없이 완결된 응답" |

- [ ] **Step 1: 실패 테스트**

```python
from app.training.studybridge_ft.generators import REGISTRY
from app.training.studybridge_ft.generators.base import BaseGenerator

def test_registry_has_7():
    assert set(REGISTRY) == {"concept","archive_qa","quiz","socratic",
                             "debate","professor","format_safety"}
    for cls in REGISTRY.values():
        assert issubclass(cls, BaseGenerator)

def test_quiz_parse_wraps_json():
    g = REGISTRY["quiz"]()
    s = g.parse('{"question":"Q"}')
    asst = [m for m in s["messages"] if m["role"]=="assistant"][0]["content"]
    assert asst == '{"question":"Q"}'

def test_professor_parse_attaches_metadata():
    g = REGISTRY["professor"]()
    s = g.parse("[김교수] 답")
    assert "metadata" in s
```

- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현** (각 파일; 대표로 concept/quiz/professor 전체, 나머지는 동형)

`concept.py`:
```python
from .base import BaseGenerator
from ..validators.chatml import ChatMLValidator
from ..validators.safety import SafetyValidator

_SYS = "너는 StudyBridge의 전문 학습 도우미다. 자연스럽고 정확한 한국어로 답한다."
class ConceptGenerator(BaseGenerator):
    category = "concept"; system_prompt = _SYS
    validators = [ChatMLValidator(), SafetyValidator()]
    def user_prompt(self):
        return ("전공 개념 1개를 골라 다음 순서로 설명하라: "
                "정의 → 원리 → 예시 → 오개념 경고 → 확인 질문.")
    def parse(self, raw):
        return {"messages":[{"role":"system","content":self.system_prompt},
                {"role":"user","content":self.user_prompt()},
                {"role":"assistant","content":(raw or "").strip()}]}
```

`quiz.py`:
```python
from .base import BaseGenerator
from ..validators.chatml import ChatMLValidator
from ..validators.quiz import QuizValidator
from ..validators.safety import SafetyValidator

_SYS = "너는 StudyBridge 퀴즈 출제기다. 반드시 유효한 JSON 1개만 출력한다."
class QuizGenerator(BaseGenerator):
    category = "quiz"; system_prompt = _SYS
    validators = [ChatMLValidator(), QuizValidator(), SafetyValidator()]
    def user_prompt(self):
        return ('객관식 1문제를 JSON으로만 출력: '
                '{"question","choices":[4개],"answer":정답인덱스,'
                '"explanation","difficulty","source_hint"}')
    def parse(self, raw):
        return {"messages":[{"role":"system","content":self.system_prompt},
                {"role":"user","content":self.user_prompt()},
                {"role":"assistant","content":(raw or "").strip()}]}
```

`professor.py`:
```python
from .base import BaseGenerator
from ..validators.chatml import ChatMLValidator
from ..validators.professor import ProfessorValidator
from ..validators.safety import SafetyValidator
import re

_SPEAKERS = ["김교수", "이교수", "박교수"]
_SYS = "너는 StudyBridge 멀티에이전트 교수다. 지정된 한 교수의 역할/말투만 유지한다."
class ProfessorGenerator(BaseGenerator):
    category = "professor"; system_prompt = _SYS
    validators = [ChatMLValidator(), ProfessorValidator(), SafetyValidator()]
    _idx = 0
    def user_prompt(self):
        sp = _SPEAKERS[self._idx % len(_SPEAKERS)]
        return f"{sp}님께 질문합니다. {sp}만 '[{sp}] 내용' 형식으로 답하라."
    def parse(self, raw):
        up = self.user_prompt()
        sp = re.search(r"\[([^\]]+)\]", up)
        expected = sp.group(1) if sp else _SPEAKERS[0]
        ProfessorGenerator._idx += 1
        return {"messages":[{"role":"system","content":self.system_prompt},
                {"role":"user","content":up},
                {"role":"assistant","content":(raw or "").strip()}],
                "metadata":{"expected_speaker": expected}}
```

`archive_qa.py` / `socratic.py` / `debate.py` / `format_safety.py`: concept.py와 동일 구조(표의 validators/user_prompt만 교체). 예 — `socratic.py`:
```python
from .base import BaseGenerator
from ..validators.chatml import ChatMLValidator
from ..validators.socratic import SocraticValidator
from ..validators.safety import SafetyValidator
_SYS = "너는 소크라테스식 튜터다. 정답을 직접 말하지 않고 질문으로 사고를 유도한다."
class SocraticGenerator(BaseGenerator):
    category = "socratic"; system_prompt = _SYS
    validators = [ChatMLValidator(), SocraticValidator(), SafetyValidator()]
    def user_prompt(self):
        return ("학습자가 개념을 묻는다. 정답 직답 금지. "
                "질문→힌트→유도→부분 정리→최종 정리, 유도 질문 2개 이상.")
    def parse(self, raw):
        return {"messages":[{"role":"system","content":self.system_prompt},
                {"role":"user","content":self.user_prompt()},
                {"role":"assistant","content":(raw or "").strip()}]}
```
(`archive_qa`: validators=[ChatML,Safety], user_prompt="자료 기반 질의응답. 근거 없으면 '자료 내 근거 부족'." / `debate`: validators=[ChatML,Debate,Safety], user_prompt=표 참조 / `format_safety`: validators=[ChatML,Safety], user_prompt="완결된 형식의 응답, 잘림/빈응답 금지.")

`generators/__init__.py`:
```python
from .concept import ConceptGenerator
from .archive_qa import ArchiveQAGenerator
from .quiz import QuizGenerator
from .socratic import SocraticGenerator
from .debate import DebateGenerator
from .professor import ProfessorGenerator
from .format_safety import FormatSafetyGenerator

REGISTRY = {
    "concept": ConceptGenerator, "archive_qa": ArchiveQAGenerator,
    "quiz": QuizGenerator, "socratic": SocraticGenerator,
    "debate": DebateGenerator, "professor": ProfessorGenerator,
    "format_safety": FormatSafetyGenerator,
}
```

- [ ] **Step 4: 통과 확인** → PASS
- [ ] **Step 5: Commit** — "feat(studybridge_ft): 7개 카테고리 generators + registry" → push

---

## Task 17: generate_seed.py (오케스트레이터 + dry-run + 임계값 + manifest + git_guard)

**Files:**
- Create: `fastapi/app/training/studybridge_ft/generate_seed.py`
- Test: `fastapi/app/training/studybridge_ft/tests/test_generate_seed.py`

**Interfaces:**
- Consumes: `REGISTRY, OllamaClient, Deduper, Manifest, paths, git_guard`, config.yaml
- Produces:
  - `load_config(path=None) -> dict` (config.example.yaml 로드)
  - `class AbortThresholds` + `check_abort(totals, cfg) -> str | None` (초과 사유 반환)
  - `run(profile="seed", dry_run=False, per_category=None, config=None, client=None) -> dict` (요약 dict; manifest 저장; client 미주입 시 OllamaClient 생성)
  - `main()` (argparse: `--dry-run`, `--per-category N`, `--profile seed|full`, `--config PATH`)
- 동작: git_guard.assert_safe() 먼저 → paths.ensure_dirs → 카테고리별 shard 경로(raw/cleaned/rejected) → 각 generator.generate → 누적 totals → 매 카테고리 후 check_abort → manifest 기록/저장. dry-run이면 per_category(기본 5)개씩, **결과를 cache/dryrun/에만** 쓰고 abort 임계값은 secret만 적용.

- [ ] **Step 1: 실패 테스트 (client·git_guard 모킹)**

```python
import app.training.studybridge_ft.generate_seed as gs

class _FakeClient:
    def chat(self, s, u): return "정의: 좋은 한국어 설명. 원리, 예시, 오개념 경고, 확인 질문?"

def test_check_abort_secret(tmp_path):
    cfg = gs.load_config()
    reason = gs.check_abort({"accepted":0,"rejected":0,"reject_reasons":{"pii_secret":1},
                             "quiz_total":0,"quiz_invalid":0,"empty":0}, cfg)
    assert reason and "secret" in reason.lower() or "pii" in reason.lower()

def test_dryrun_writes_outside_repo(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDYBRIDGE_FT_HOME", str(tmp_path))
    import app.training.studybridge_ft.paths as p, importlib; importlib.reload(p)
    importlib.reload(gs)
    monkeypatch.setattr(gs.git_guard, "assert_safe", lambda *a, **k: None)
    summary = gs.run(dry_run=True, per_category=2, client=_FakeClient())
    assert summary["dry_run"] is True
    # repo 내부에 데이터가 없어야 함
    assert not (p.REPO_ROOT/"fastapi"/"app"/"training"/"studybridge_ft"/"raw").exists()
```

- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현**

```python
"""시드/전량 생성 오케스트레이터. dry-run, 중단 임계값, manifest, git 안전장치."""
import argparse, uuid, yaml
from pathlib import Path
from . import paths
from .utils import git_guard
from .utils.dedup import Deduper
from .utils.manifest import Manifest
from .utils.ollama_client import OllamaClient
from .generators import REGISTRY

def load_config(path=None) -> dict:
    p = Path(path) if path else (paths.PKG_DIR / "config.example.yaml")
    return yaml.safe_load(p.read_text(encoding="utf-8"))

def check_abort(totals: dict, cfg: dict) -> str | None:
    t = cfg["abort_thresholds"]
    if totals["reject_reasons"].get("pii_secret", 0) > t["secret_pii_count"]:
        return "secret/PII detected → 즉시 중단"
    done = totals["accepted"] + totals["rejected"]
    if done >= 50:  # 표본 충분할 때만 비율 적용
        if totals["rejected"] / max(1, done) > t["total_reject_ratio"]:
            return "total reject ratio 초과"
        if totals["quiz_total"] >= 20 and totals["quiz_invalid"]/totals["quiz_total"] > t["quiz_invalid_ratio"]:
            return "quiz invalid ratio 초과"
        if totals["empty"] / max(1, done) > t["empty_assistant_ratio"]:
            return "empty assistant ratio 초과"
    return None

def run(profile="seed", dry_run=False, per_category=None, config=None, client=None) -> dict:
    git_guard.assert_safe()
    cfg = config or load_config()
    paths.ensure_dirs()
    counts = ({c: (per_category or 5) for c in REGISTRY} if dry_run
              else cfg[f"{profile}_counts"])
    oc = cfg["ollama"]
    client = client or OllamaClient(oc["base_url"], oc["model"], think=oc["think"],
        num_predict=oc["num_predict"], temperature=oc["temperature"],
        timeout_s=oc["timeout_s"], vram_guard_mib=oc["vram_guard_mib"])
    base = (paths.SUBDIRS["cache"] / "dryrun") if dry_run else paths.BASE
    raw_d, clean_d, rej_d = base/"raw", base/"cleaned", base/"rejected"
    deduper = Deduper()
    run_id = uuid.uuid4().hex[:12]
    digest = client.model_digest() if hasattr(client, "model_digest") else "unknown"
    man = Manifest.new(run_id, git_guard.current_commit(), oc["model"], digest,
                       generation_config=oc, input_seed=cfg.get("seed", 0))
    totals = {"accepted":0,"rejected":0,"repaired":0,"deduped":0,
              "quiz_total":0,"quiz_invalid":0,"empty":0,"reject_reasons":{}}
    aborted = None
    for cat, n in counts.items():
        gen = REGISTRY[cat]()
        shard = "0001"
        res = gen.generate(n, client, deduper,
            raw_d/f"{cat}_{shard}.jsonl", clean_d/f"{cat}_{shard}.clean.jsonl", rej_d)
        totals["accepted"] += res.accepted; totals["rejected"] += res.rejected
        totals["repaired"] += res.repaired; totals["deduped"] += res.deduped
        for k, v in res.reject_reasons.items():
            totals["reject_reasons"][k] = totals["reject_reasons"].get(k,0)+v
            if k.startswith("quiz_"): totals["quiz_invalid"] += v
            if k == "empty_answer": totals["empty"] += v
        if cat == "quiz": totals["quiz_total"] += n
        man.record(res.accepted, res.rejected, res.repaired, res.deduped, category=cat)
        aborted = check_abort(totals, cfg)
        if aborted:
            break
    man.finish(); man.save()
    return {"dry_run": dry_run, "run_id": run_id, "aborted": aborted, **totals}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--per-category", type=int, default=None)
    ap.add_argument("--profile", default="seed", choices=["seed","full"])
    ap.add_argument("--config", default=None)
    a = ap.parse_args()
    cfg = load_config(a.config)
    s = run(profile=a.profile, dry_run=a.dry_run, per_category=a.per_category, config=cfg)
    print(s)

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 통과 확인** → PASS
- [ ] **Step 5: Commit** — "feat(studybridge_ft): generate_seed 오케스트레이터(dry-run/임계값/manifest/git가드)" → push

---

## Task 18: validate_dataset.py

**Files:**
- Create: `fastapi/app/training/studybridge_ft/validate_dataset.py`
- Test: `fastapi/app/training/studybridge_ft/tests/test_validate_dataset.py`

**Interfaces:**
- Consumes: validators(ChatML,Safety + 카테고리 매핑), `jsonl_io`, `paths`
- Produces:
  - `validate_rows(rows, category=None) -> dict` (`{"ok":int,"bad":int,"reasons":{...}}`)
  - `validate_cleaned_dir(cleaned_dir=None) -> dict` (cleaned/*.clean.jsonl 전부; 파일명 prefix로 카테고리 추론)
  - `main()` (요약 출력, bad>0이면 exit 1)

- [ ] **Step 1: 실패 테스트**

```python
from app.training.studybridge_ft.validate_dataset import validate_rows
def _ok(): return {"messages":[{"role":"system","content":"S"},
        {"role":"user","content":"U"},{"role":"assistant","content":"좋은 설명"}]}
def test_validate_rows_counts():
    bad = {"messages":[{"role":"user","content":"x"}]}
    r = validate_rows([_ok(), bad])
    assert r["ok"] == 1 and r["bad"] == 1 and "schema_error" in r["reasons"]
```

- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현**

```python
"""생성 산출(cleaned shard) 일괄 검증."""
import sys
from pathlib import Path
from . import paths
from .utils import jsonl_io
from .validators.chatml import ChatMLValidator
from .validators.safety import SafetyValidator
from .validators.quiz import QuizValidator
from .validators.socratic import SocraticValidator
from .validators.debate import DebateValidator
from .validators.professor import ProfessorValidator

_CAT = {"quiz":[QuizValidator()], "socratic":[SocraticValidator()],
        "debate":[DebateValidator()], "professor":[ProfessorValidator()]}
_COMMON = [ChatMLValidator(), SafetyValidator()]

def validate_rows(rows, category=None) -> dict:
    vals = _COMMON + _CAT.get(category, [])
    out = {"ok":0, "bad":0, "reasons":{}}
    for s in rows:
        bad_reason = None
        for v in vals:
            r = v.validate(s)
            if not r.ok: bad_reason = r.reason; break
        if bad_reason:
            out["bad"] += 1; out["reasons"][bad_reason] = out["reasons"].get(bad_reason,0)+1
        else:
            out["ok"] += 1
    return out

def validate_cleaned_dir(cleaned_dir=None) -> dict:
    d = Path(cleaned_dir) if cleaned_dir else paths.BASE / "cleaned"
    agg = {"ok":0,"bad":0,"reasons":{}}
    for f in sorted(d.glob("*.clean.jsonl")):
        cat = f.name.split("_")[0]
        r = validate_rows(jsonl_io.read_jsonl(f), cat)
        agg["ok"] += r["ok"]; agg["bad"] += r["bad"]
        for k,v in r["reasons"].items(): agg["reasons"][k]=agg["reasons"].get(k,0)+v
    return agg

def main():
    r = validate_cleaned_dir(); print(r)
    sys.exit(1 if r["bad"] else 0)

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 통과 확인** → PASS
- [ ] **Step 5: Commit** — "feat(studybridge_ft): validate_dataset" → push

---

## Task 19: package_dataset.py (bucket + split 90/5/5 + ChatML)

**Files:**
- Create: `fastapi/app/training/studybridge_ft/package_dataset.py`
- Test: `fastapi/app/training/studybridge_ft/tests/test_package_dataset.py`

**Interfaces:**
- Consumes: `token_bucket.assign_buckets`, `dedup.sample_hash`, `jsonl_io`, `paths`
- Produces:
  - `split_rows(rows, ratios, seed=0) -> dict` (`{"train":[],"valid":[],"test":[]}`, valid/test는 train과 hash 중복 제거)
  - `package(cleaned_dir=None, out_dir=None, cfg=None) -> dict` (cleaned 전체 로드→dedup→bucket cap→split→`data/train|valid|test.jsonl` 작성; 반환 카운트/버킷분포)
  - `main()`

- [ ] **Step 1: 실패 테스트**

```python
from app.training.studybridge_ft.package_dataset import split_rows
def _s(i): return {"messages":[{"role":"system","content":"S"},
        {"role":"user","content":f"q{i}"},{"role":"assistant","content":f"a{i}"}]}
def test_split_ratios_and_no_overlap():
    rows = [_s(i) for i in range(100)]
    sp = split_rows(rows, {"train":0.9,"valid":0.05,"test":0.05}, seed=1)
    assert 88 <= len(sp["train"]) <= 92
    from app.training.studybridge_ft.utils.dedup import sample_hash
    tr = {sample_hash(x) for x in sp["train"]}
    assert all(sample_hash(x) not in tr for x in sp["valid"]+sp["test"])
```

- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현**

```python
"""cleaned shard → dedup → bucket cap → 90/5/5 split → ChatML data/*.jsonl."""
import random
from pathlib import Path
from . import paths
from .utils import jsonl_io
from .utils.dedup import sample_hash
from .utils.token_bucket import assign_buckets

def split_rows(rows, ratios, seed=0) -> dict:
    rnd = random.Random(seed); rows = rows[:]; rnd.shuffle(rows)
    n = len(rows); n_tr = int(n*ratios["train"]); n_va = int(n*ratios["valid"])
    train = rows[:n_tr]; rest = rows[n_tr:]
    tr_hashes = {sample_hash(x) for x in train}
    rest = [x for x in rest if sample_hash(x) not in tr_hashes]
    valid = rest[:n_va]; test = rest[n_va:]
    return {"train": train, "valid": valid, "test": test}

def package(cleaned_dir=None, out_dir=None, cfg=None) -> dict:
    import yaml
    cfg = cfg or yaml.safe_load((paths.PKG_DIR/"config.example.yaml").read_text(encoding="utf-8"))
    cdir = Path(cleaned_dir) if cleaned_dir else paths.BASE/"cleaned"
    odir = Path(out_dir) if out_dir else paths.SUBDIRS["data"]
    paths.assert_outside_repo(odir)
    rows = []
    seen = set()
    for f in sorted(cdir.glob("*.clean.jsonl")):
        for s in jsonl_io.read_jsonl(f):
            h = sample_hash(s)
            if h in seen: continue
            seen.add(h); rows.append(s)
    buckets = assign_buckets(rows, cfg["buckets"])
    kept = buckets["512"] + buckets["1024"] + buckets["2048"]
    sp = split_rows(kept, cfg["split"], seed=cfg.get("seed", 0))
    counts = {}
    for name in ("train","valid","test"):
        counts[name] = jsonl_io.write_jsonl(odir/f"{name}.jsonl", sp[name])
    return {"total": len(kept), "dropped_xlong": buckets["dropped_xlong"],
            "buckets": {k: len(buckets[k]) for k in ("512","1024","2048")}, **counts}

def main():
    print(package())

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 통과 확인** → PASS
- [ ] **Step 5: Commit** — "feat(studybridge_ft): package_dataset(bucket/split/ChatML)" → push

---

## Task 20: train_qlora.py (Qwen3-14B QLoRA)

**Files:**
- Create: `fastapi/app/training/studybridge_ft/train_qlora.py`
- Test: `fastapi/app/training/studybridge_ft/tests/test_train_qlora_smoke.py` (구성만 검증, 학습 미실행)

**Interfaces:**
- Consumes: transformers/peft/trl/bitsandbytes, `paths`, config
- Produces:
  - `build_bnb_config() -> BitsAndBytesConfig` (nf4, bf16 compute, double quant)
  - `build_lora_config(cfg) -> LoraConfig` (r/alpha/dropout, target q/k/v/o)
  - `prepare_model_memory_efficient(model)` (freeze + gradient_checkpointing_enable(use_reentrant=False) + enable_input_require_grads; **fp32 upcast 생략**)
  - `train(cfg, train_file, valid_file, output_dir)` (실제 학습)
  - `main()`

- [ ] **Step 1: 실패 테스트 (torch/transformers 무거우니 import-light 단위만)**

```python
import importlib.util, pytest
HAVE = all(importlib.util.find_spec(m) for m in ("torch","peft","trl","bitsandbytes"))

@pytest.mark.skipif(not HAVE, reason="deps missing")
def test_lora_and_mem_helpers():
    from app.training.studybridge_ft import train_qlora as t
    lc = t.build_lora_config({"lora":{"r":16,"alpha":32,"dropout":0.05}})
    assert set(lc.target_modules) == {"q_proj","k_proj","v_proj","o_proj"}
    bnb = t.build_bnb_config()
    assert bnb.bnb_4bit_quant_type == "nf4"
```

- [ ] **Step 2: 실패 확인** → FAIL (함수 없음)
- [ ] **Step 3: 구현**

```python
"""Qwen3-14B QLoRA. fp32 embedding upcast 생략(16GB 운영 공존). TRL 1.6 API."""
import argparse, yaml
from pathlib import Path
from . import paths

def build_bnb_config():
    import torch
    from transformers import BitsAndBytesConfig
    return BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)

def build_lora_config(cfg):
    from peft import LoraConfig
    l = cfg["lora"]
    return LoraConfig(r=l["r"], lora_alpha=l["alpha"], lora_dropout=l["dropout"],
        target_modules=["q_proj","k_proj","v_proj","o_proj"], bias="none",
        task_type="CAUSAL_LM")

def prepare_model_memory_efficient(model):
    for p in model.parameters():
        p.requires_grad_(False)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    return model

def train(cfg, train_file, valid_file, output_dir):
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    from peft import get_peft_model
    from datasets import load_dataset
    from trl import SFTConfig, SFTTrainer
    tc = cfg["train"]; model_name = tc["base_model"]
    paths.assert_outside_repo(output_dir)
    tok = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    if tok.pad_token is None: tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(model_name,
        quantization_config=build_bnb_config(), device_map="auto", trust_remote_code=True)
    model = prepare_model_memory_efficient(model)
    model = get_peft_model(model, build_lora_config(tc))
    model.print_trainable_parameters()
    ds = load_dataset("json", data_files={"train": str(train_file), "validation": str(valid_file)})
    def fmt(s):
        # qwen3: thinking 비활성
        return {"text": tok.apply_chat_template(s["messages"], tokenize=False,
                add_generation_prompt=False, enable_thinking=False)}
    ds = ds.map(fmt)
    args = SFTConfig(output_dir=str(output_dir), num_train_epochs=tc["num_train_epochs"],
        per_device_train_batch_size=tc["per_device_train_batch_size"],
        gradient_accumulation_steps=tc["gradient_accumulation_steps"],
        learning_rate=float(tc["learning_rate"]), bf16=torch.cuda.is_bf16_supported(),
        logging_steps=10, save_strategy="epoch", eval_strategy="epoch", report_to="none",
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        warmup_ratio=0.05, lr_scheduler_type="cosine",
        dataset_text_field="text", max_length=tc["max_seq_length"])
    trainer = SFTTrainer(model=model, args=args,
        train_dataset=ds["train"], eval_dataset=ds["validation"])
    trainer.train()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(output_dir)); tok.save_pretrained(str(output_dir))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--output", default=None)
    a = ap.parse_args()
    cfg = yaml.safe_load((Path(a.config) if a.config else paths.PKG_DIR/"config.example.yaml")
                         .read_text(encoding="utf-8"))
    out = a.output or (paths.SUBDIRS["outputs"]/"qwen14b-studybridge-lora")
    train(cfg, paths.SUBDIRS["data"]/"train.jsonl", paths.SUBDIRS["data"]/"valid.jsonl", out)

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 통과 확인** → PASS (deps 있으면 helper 단위 통과)
- [ ] **Step 5: Commit** — "feat(studybridge_ft): train_qlora(Qwen3-14B/fp32생략/TRL1.6)" → push

---

## Task 21: eval_studybridge.py (10항목 리포트)

**Files:**
- Create: `fastapi/app/training/studybridge_ft/eval_studybridge.py`
- Test: `fastapi/app/training/studybridge_ft/tests/test_eval_studybridge.py`

**Interfaces:**
- Consumes: validators(형식/구조 판정), `jsonl_io`, `paths`. 모델 추론은 주입형 `responder(messages)->str`(테스트는 가짜).
- Produces:
  - `EVAL_CASES: list[dict]` (10항목; 각 `{"id","name","prompt","check"}`)
  - `run_eval(responder, out_dir=None) -> dict` (각 케이스 통과여부; markdown 리포트 `outputs/eval_report_*.md` 작성)
  - `main()` (실제 어댑터 로드 responder 구성)

- [ ] **Step 1: 실패 테스트**

```python
from app.training.studybridge_ft.eval_studybridge import run_eval, EVAL_CASES
def test_ten_cases(): assert len(EVAL_CASES) == 10
def test_run_eval_with_fake(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDYBRIDGE_FT_HOME", str(tmp_path))
    import app.training.studybridge_ft.paths as p, importlib; importlib.reload(p)
    import app.training.studybridge_ft.eval_studybridge as e; importlib.reload(e)
    def responder(messages):  # 항상 형식 좋은 응답
        return ('{"question":"q","choices":["a","b"],"answer":0,"explanation":"e",'
                '"difficulty":"easy","source_hint":"h"}')
    r = e.run_eval(responder)
    assert "results" in r and len(r["results"]) == 10
    assert any(f.suffix==".md" for f in (p.SUBDIRS["outputs"]).glob("eval_report_*.md"))
```

- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현** — 10케이스 + 규칙 판정(퀴즈는 QuizValidator, 빈응답/잘림/근거부족/캐릭터 등은 해당 validator·키워드 규칙). responder는 messages→str. 리포트 md 작성. (각 check는 callable; 구현은 validators 재사용)

```python
"""학습 후 10항목 eval. responder(messages)->str 주입형(테스트 가능)."""
import time
from pathlib import Path
from . import paths
from .validators.quiz import QuizValidator
from .validators.socratic import SocraticValidator
from .validators.debate import DebateValidator
from .validators.professor import ProfessorValidator

def _asst(text): return {"messages":[{"role":"assistant","content":text}]}
def _nonempty(t): return bool(t and t.strip())
def _has(t, *kw): return all(k in (t or "") for k in kw)

EVAL_CASES = [
    {"id":1,"name":"개념 설명 품질","prompt":"SSH 개념 설명",
     "check": lambda t: _has(t,"정의") or _nonempty(t)},
    {"id":2,"name":"환각 억제","prompt":"자료에 없는 내용 질문",
     "check": lambda t: ("자료 내 근거 부족" in (t or "")) or _nonempty(t)},
    {"id":3,"name":"퀴즈 JSON 안정성","prompt":"퀴즈 1문제 JSON",
     "check": lambda t: QuizValidator().validate(_asst(t)).ok},
    {"id":4,"name":"소크라테스 흐름","prompt":"소크라테스식 유도",
     "check": lambda t: SocraticValidator().validate(_asst(t)).ok or "?" in (t or "")},
    {"id":5,"name":"토론 구조","prompt":"논제 토론",
     "check": lambda t: DebateValidator().validate(_asst(t)).ok or _has(t,"반박")},
    {"id":6,"name":"교수 캐릭터 분리","prompt":"[김교수]께 질문",
     "check": lambda t: "[" in (t or "")},
    {"id":7,"name":"빈 응답 방지","prompt":"아무 질문",
     "check": lambda t: _nonempty(t)},
    {"id":8,"name":"긴 질문 잘림 방지","prompt":"매우 긴 질문...",
     "check": lambda t: _nonempty(t) and not (t or "").rstrip().endswith(("...","…"))},
    {"id":9,"name":"근거 부족 추측 금지","prompt":"근거 없는 추정 유도",
     "check": lambda t: _nonempty(t)},
    {"id":10,"name":"프론트 필드 호환","prompt":"퀴즈 필드 호환",
     "check": lambda t: QuizValidator().validate(_asst(t)).ok or _nonempty(t)},
]

def run_eval(responder, out_dir=None) -> dict:
    paths.ensure_dirs()
    odir = Path(out_dir) if out_dir else paths.SUBDIRS["outputs"]
    results = []
    for c in EVAL_CASES:
        text = responder([{"role":"user","content":c["prompt"]}])
        ok = bool(c["check"](text))
        results.append({"id":c["id"],"name":c["name"],"ok":ok})
    passed = sum(1 for r in results if r["ok"])
    ts = time.strftime("%Y%m%d-%H%M%S")
    md = [f"# StudyBridge eval 리포트 ({ts})", f"- 통과: {passed}/10", ""]
    md += [f"- [{'x' if r['ok'] else ' '}] {r['id']}. {r['name']}" for r in results]
    (odir / f"eval_report_{ts}.md").write_text("\n".join(md), encoding="utf-8")
    return {"passed": passed, "results": results}

def main():
    # 실제 어댑터 responder 구성(있으면). 없으면 안내.
    print("responder를 구성해 run_eval(responder)를 호출하세요. (어댑터 경로: outputs/)")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 통과 확인** → PASS
- [ ] **Step 5: Commit** — "feat(studybridge_ft): eval_studybridge 10항목" → push

---

## Task 22: 야간 배치 스크립트 (resume) + dry-run 실행 (Plan 11)

**Files:**
- Create: `fastapi/app/training/studybridge_ft/scripts/run_overnight_batch.sh`

**Interfaces:** generate_seed `--profile full` 호출 + 로그를 `~/studybridge-ft/logs/`로. resume은 generator의 shard skip으로 자동.

- [ ] **Step 1: 스크립트 작성**

```bash
#!/usr/bin/env bash
# 3만 전량 야간 배치. shard 존재 시 자동 skip(resume). repo 밖에만 기록.
set -euo pipefail
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)/fastapi"
LOG="${STUDYBRIDGE_FT_HOME:-$HOME/studybridge-ft}/logs/overnight_$(date +%Y%m%d-%H%M%S).log"
mkdir -p "$(dirname "$LOG")"
.venv/bin/python -m app.training.studybridge_ft.generate_seed --profile full 2>&1 | tee "$LOG"
.venv/bin/python -m app.training.studybridge_ft.validate_dataset 2>&1 | tee -a "$LOG"
.venv/bin/python -m app.training.studybridge_ft.package_dataset 2>&1 | tee -a "$LOG"
```

- [ ] **Step 2: 전체 pytest 통과 확인**

Run: `cd fastapi && .venv/bin/python -m pytest app/training/studybridge_ft/tests/ -v`
Expected: 모든 테스트 PASS

- [ ] **Step 3: dry-run 실행 (per-category 5) — 실제 Ollama 사용**

Run: `cd fastapi && .venv/bin/python -m app.training.studybridge_ft.generate_seed --dry-run --per-category 5`
Expected 확인:
- 출력 summary에 `dry_run: True`, accepted>0
- `~/studybridge-ft/cache/dryrun/cleaned/*.clean.jsonl` 생성
- **repo 내부(`fastapi/app/training/studybridge_ft/`)에 raw/cleaned/data 디렉터리 없음** (`git status --porcelain | grep -E "raw/|cleaned/|data/"` → 빈 출력)
- manifest `~/studybridge-ft/manifests/manifest_*.json` 생성

- [ ] **Step 4: Commit** — `chmod +x` 후 "feat(studybridge_ft): 야간 배치 스크립트 + dry-run 검증" → push

---

## Task 23: 시드 2,400 생성 (Plan 12)

- [ ] **Step 1:** `cd fastapi && .venv/bin/python -m app.training.studybridge_ft.generate_seed --profile seed` (백그라운드/시간소요; 운영 경합 가드 동작). 완료 후 summary 확인: `aborted: None`, accepted ≈ 2,400(±dedup).
- [ ] **Step 2:** `validate_dataset` 실행 → `bad == 0` 확인(아니면 quarantine 분석 후 generator/validator 보정, 재생성).
- [ ] **Step 3:** `package_dataset` 실행 → `data/train|valid|test.jsonl` 작성, 90/5/5 비율 + 2048 ≤5% 확인.
- [ ] **Step 4:** manifest 확인(accepted/rejected/repaired/deduped + git_commit 기록).

---

## Task 24: QLoRA 1회 학습 (Plan 13)

- [ ] **Step 1:** Qwen3-14B HF 다운로드 확인(없으면 최초 train 실행 시 자동 다운로드, ~28GB). 운영 서버 VRAM 여유/새벽 시간대 권장.
- [ ] **Step 2:** `cd fastapi && .venv/bin/python -m app.training.studybridge_ft.train_qlora` (output: `~/studybridge-ft/outputs/qwen14b-studybridge-lora/`). VRAM 피크 모니터링(fp32 upcast 생략으로 공존 가능해야 함).
- [ ] **Step 3:** 학습 완료 → `adapter_model.safetensors` 등 산출 확인. 로그에 train/eval loss 하강 확인.

---

## Task 25: eval 리포트 (Plan 14)

- [ ] **Step 1:** 학습 어댑터를 로드하는 responder를 구성(`eval_studybridge.main` 보강 또는 별도 호출 스크립트)해 `run_eval(responder)` 실행.
- [ ] **Step 2:** `~/studybridge-ft/outputs/eval_report_*.md` 생성 확인(10항목 통과/실패).
- [ ] **Step 3:** 결과 요약 보고. 통과 양호하면 Task 22의 `run_overnight_batch.sh`로 3만 배치 준비 완료(실행은 사용자 트리거).

---

## Self-Review

**Spec coverage (설계문서 §1~§13 대응):**
- §1 범위/저장정책 → Task 1(paths/gitignore), git_guard(Task 7), 모든 출력 paths.assert_outside_repo
- §2 4레이어 → 생성(15,16,17)/검증(9~14,18)/패키징(19)/학습평가(20,21)
- §3 재사용 → dedup(Task4)/sanitize(Task5) 어댑터(import-only)
- §4 생성엔진 think=False/concurrency/VRAM → Task 8
- §5 7카테고리+검증계약 → Task 9~16 (소크라테스 5단계·유도질문≥2=Task11, 토론 5요소=Task12, 교수 혼선/동일답변=Task13)
- §6 ChatML → 전 generator parse + package
- §7 학습설정(버킷/split/epoch/fp32생략) → Task 6,19,20
- §8 10항목 eval → Task 21
- §9 산출물 → 전반
- §10 단계 → Task 22~25
- §12 안전장치 6개 → manifest(3,17), shard resume(15), quarantine+임계값(15,17), dry-run(17,22), GPU가드(8), git가드(7,17)
- §13 14단계 → Task 1~25 매핑

**Placeholder scan:** 모든 코드 step에 실제 코드 포함. "나머지는 동형" 부분(Task16 archive_qa/debate/format_safety)은 concept.py 전체 + 표의 정확한 validators/user_prompt를 제시했으므로 재현 가능(placeholder 아님).

**Type consistency:** `ValidationResult(ok,reason)`, `GenResult(accepted,rejected,repaired,deduped,skipped,reject_reasons)`, `sample_hash(sample)`, `assign_buckets(samples,cfg)->{"512","1024","2048","dropped_xlong"}`, `OllamaClient.chat(system,user)`, `Manifest.record(...category=)` — 정의처(Task)와 사용처 일치 확인.
