# 교차 언어 계약 점검: ai07 Pydantic adapter 로 같은 fixture 를 검증해 expectations.json 의 canonical 과 비교한다.
# 사용: python -I tools/crosscheck_pydantic.py <ai07 fastapi 디렉터리> <이 v1 디렉터리>  (ai07 PR #116 체크아웃 필요)
import json, sys, pathlib
sys.path.insert(0, sys.argv[1])               # ai07 PR fastapi dir (app.contracts)
fx = pathlib.Path(sys.argv[2])                # fixtures root
from pydantic import ValidationError
from app.contracts.learning_context_v1 import LearningContextV1
from app.contracts.response_quality_v1 import QualityInput, QualityOutput
from app.contracts.training_sample_v1 import TrainingSampleV1, compute_content_hash
out = {}
for sub, model in [("learning-context.v1", LearningContextV1), ("response-quality.v1", None), ("training-sample.v1", TrainingSampleV1)]:
    for f in sorted((fx / sub).glob("*.json")):
        if f.name.startswith("legacy_"):
            continue
        m = model or (QualityOutput if "output" in f.name else QualityInput)
        try:
            m.model_validate(json.loads(f.read_text(encoding="utf-8"))); r = "VALID"
        except ValidationError:
            r = "INVALID"
        out[f"{sub}/{f.name}"] = r
hashes = {}
for name, q, a in [("ascii", "Q", "A"), ("nbsp_fullwidth", "TCP  핸드셰이크　단계", "ＳＹＮ　ＡＣＫ"),
                   ("separators_1c_1f", "a\x1cb\x1d c", "  x\x1fy\n\n"), ("emoji_ogham", "😀 끝", "줄 바꿈 ")]:
    hashes[name] = {"question": q, "answer": a, "hash": compute_content_hash(q, a)}
exp = json.loads((fx / "expectations.json").read_text(encoding="utf-8"))
fails = 0
for k, e in sorted(exp["fixtures"].items()):
    got = out.get(k, "MISSING")
    if got != e["canonical"]:
        fails += 1
        print(f"CONTRACT_MISMATCH {k}: canonical={e['canonical']} ai07={got} issue={e.get('openIssue', '-')}")
for name, h in exp["contentHash"].items():
    if compute_content_hash(h["question"], h["answer"]) != h["hash"]:
        fails += 1
        print(f"CONTENT_HASH_MISMATCH {name}")
print(f"fixtures={len(exp['fixtures'])} mismatches={fails}")
sys.exit(1 if fails else 0)
