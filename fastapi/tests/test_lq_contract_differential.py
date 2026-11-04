"""ai07 Python ↔ EC2 Java 계약 차등 테스트(B1).

- canonical fixture 30개: EC2 expectations.json 의 canonical 판정과 ai07 판정이 전부 같다(+ contentHash 벡터 4개).
- 차등 케이스 600여 개(scripts/contract_crosscheck/build_cases.py 로 생성): EC2 Java 계약 클래스를 실제로 실행해
  기록한 판정(java-verdicts.v1.jsonl)과 Python 판정이 같다. 다른 것은 known-divergences.v1.json 에 있는 항목뿐이고,
  그 항목은 모두 'Java VALID / Python INVALID'(Python 이 더 엄격)여야 한다.
- JDK·Jackson·EC2 ref 가 있으면 Java 판정을 다시 실행해 기록과 같은지(EC2 코드 변경 감지) 확인한다. 없으면 skip.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess

import pytest
from pydantic import ValidationError

from app.contracts.learning_context_v1 import LearningContextV1
from app.contracts.response_quality_v1 import QualityInput, QualityOutput
from app.contracts.training_sample_v1 import TrainingSampleV1, compute_content_hash
from scripts.contract_crosscheck.python_verdicts import verdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
FX = ROOT / "app" / "contracts" / "fixtures"
DIFF = FX / "differential"


def _jsonl(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _key(r):
    eff = (r.get("verdict") == "VALID" and bool(r.get("displayable"))) if "displayable" in r else None
    return r.get("verdict"), r.get("outcome"), eff


def test_canonical_30_fixtures_match_ec2_expectations():
    exp = json.loads((FX / "expectations.json").read_text(encoding="utf-8"))
    assert exp["status"] == "CANONICAL_EC2_V1" and len(exp["fixtures"]) == 30
    wrong = []
    for key, e in exp["fixtures"].items():
        sub, name = key.split("/")
        model = {"learning-context.v1": LearningContextV1, "training-sample.v1": TrainingSampleV1}.get(sub) \
            or (QualityOutput if e.get("model") == "output" else QualityInput)
        try:
            model.model_validate(json.loads((FX / sub / name).read_text(encoding="utf-8")))
            got = "VALID"
        except ValidationError:
            got = "INVALID"
        if got != e["canonical"]:
            wrong.append((key, got, e["canonical"]))
    assert wrong == []
    for name, h in exp["contentHash"].items():
        assert compute_content_hash(h["question"], h["answer"]) == h["hash"], name


@pytest.mark.parametrize("issue_fixture", [
    "learning-context.v1/ec2_invalid_request_id_trailing_newline.json",   # C-ID-1
    "learning-context.v1/ec2_invalid_string_material_id.json",            # C-TYPE-1
    "response-quality.v1/ec2_invalid_output_score_above_100.json",        # C-RQ-2
    "training-sample.v1/ec2_invalid_naive_datetime.json",                 # C-TIME-1
])
def test_previously_open_issues_now_rejected(issue_fixture):
    sub, name = issue_fixture.split("/")
    model = {"learning-context.v1": LearningContextV1, "training-sample.v1": TrainingSampleV1,
             "response-quality.v1": QualityOutput}[sub]
    with pytest.raises(ValidationError):
        model.model_validate(json.loads((FX / sub / name).read_text(encoding="utf-8")))


def test_meta_marks_ec2_as_canonical_owner():
    meta = json.loads((FX / "_meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "CANONICAL_EC2_V1" and meta["owner"].startswith("EC2")
    vec = json.loads((FX / "signing-vectors.v1.json").read_text(encoding="utf-8"))
    assert vec["status"] == "CANONICAL_EC2_V1"


def test_python_matches_recorded_java_verdicts_except_tracked_stricter_cases():
    cases = _jsonl(DIFF / "cases.v1.jsonl")
    java = {r["id"]: r for r in _jsonl(DIFF / "java-verdicts.v1.jsonl")}
    known = json.loads((DIFF / "known-divergences.v1.json").read_text(encoding="utf-8"))["divergences"]
    assert len(cases) >= 600 and set(java) == {c["id"] for c in cases}, "케이스가 바뀌면 Java 판정을 다시 기록해야 한다"
    diverged = {}
    for c in cases:
        py = verdict(c)
        if _key(py) != _key(java[c["id"]]):
            diverged[c["id"]] = (_key(java[c["id"]]), _key(py))
    assert set(diverged) == set(known), {k: v for k, v in diverged.items() if k not in known}
    for cid, (j, p) in diverged.items():
        assert j[0] == "VALID" and p[0] == "INVALID", f"Python 이 더 느슨한 불일치 금지: {cid}"


def test_no_python_exception_leaks_from_signing_paths():
    for c in _jsonl(DIFF / "cases.v1.jsonl"):
        if c["model"].startswith("sig-"):
            assert not verdict(c)["outcome"].startswith("PYTHON_EXCEPTION"), c["id"]


def _java_available():
    jdk = shutil.which("javac") or any(pathlib.Path.home().glob(".local/jdk-*/bin/javac")) or (
        os.getenv("JAVA_HOME") and (pathlib.Path(os.environ["JAVA_HOME"]) / "bin" / "javac").exists())
    jars = os.getenv("JACKSON_CP") or os.getenv("AI_CONTRACT_FETCH_JARS") == "1" or any(
        (pathlib.Path.home() / ".gradle/caches/modules-2/files-2.1/com.fasterxml.jackson.core" / "jackson-databind").glob("2.15.*"))
    in_tree = (ROOT.parent / "backend/src/main/java/com/studybridge/api/ai/contract/v1/ContractJson.java").exists()
    ref = in_tree or subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", "-q", "origin/feature/learning-loop-ec2"],
                                    capture_output=True).returncode == 0
    return bool(jdk and jars and ref)


@pytest.mark.skipif(not _java_available(), reason="JDK/Jackson/EC2 git ref 없음 — 기록된 Java 판정으로만 비교")
def test_live_java_harness_reproduces_recorded_verdicts():
    out = subprocess.run(["bash", str(ROOT / "scripts/contract_crosscheck/run_java_crosscheck.sh"),
                          str(DIFF / "cases.v1.jsonl")], capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    live = {r["id"]: _key(r) for r in map(json.loads, out.stdout.splitlines())}
    rec = {r["id"]: _key(r) for r in _jsonl(DIFF / "java-verdicts.v1.jsonl")}
    assert live == rec
