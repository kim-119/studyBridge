# EC2 가 실제로 보낸 학습 파이프라인 요청(TrainingPipelinePostgresTest.dumpRealRequestsForAi07Verification 산출물)을
# ai07 PR #116 의 검증 코드로 판정한다. 서버를 띄우지 않고 ai07 라우트가 쓰는 함수 그대로 호출한다:
#   collect-v1          : verify_body → parse_sample_json → X-Request-Id==eventId → verify_consent_token(rid, sub)
#                         → training_candidate_routes.collect_v1 의 동의 불일치 판정(scope/granted/cv/dtid/ct==consentTimestamp/ct 미래 5분)
#   consent-withdrawal / deletion / feedback : app.training_pipeline.control.verify_control(서명→계약→messageType→rid→issuedAt 미래 30s)
# 사용: python -I verify_training_requests_ai07.py <ai07 fastapi 디렉터리> <requests.json>
# 키는 테스트 전용 값(산출물에 포함)이며 운영 키가 아니다. 출력에는 본문 원문을 싣지 않는다.
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, sys.argv[1])
dump = json.load(open(sys.argv[2], encoding="utf-8"))
os.environ["AI_TRAINING_SAMPLE_SIGNING_KEY"] = dump["sampleKey"]
os.environ["AI_TRAINING_CONSENT_SIGNING_KEY"] = dump["consentKey"]
for n in ("AI_SCOPE_SIGNING_KEY", "AI_SERVER_API_KEY", "AI_SERVER_API_KEY_SECONDARY"):
    os.environ.pop(n, None)

from app.contracts.jtypes import parse_offset_datetime  # noqa: E402
from app.contracts.signing import SignatureError, verify_body, verify_consent_token  # noqa: E402
from app.contracts.training_sample_v1 import parse_sample_json  # noqa: E402
from app.training_pipeline.control import ControlError, MessageType, verify_control  # noqa: E402

ROUTES = {"consent-withdrawal": MessageType.CONSENT_WITHDRAWAL, "deletion": MessageType.DELETION, "feedback": MessageType.FEEDBACK}
fails, results = 0, []
for r in dump["requests"]:
    leaf = r["path"].rsplit("/", 1)[-1]
    raw = r["body"].encode("utf-8")
    now = float(r["dumpedAt"])
    sig, ts, rid = r["sig"], r["ts"], r["rid"]
    try:
        if leaf == "collect-v1":
            verify_body(raw, sig, ts, now=now)
            sample = parse_sample_json(raw)
            if rid != sample.eventId:
                raise ValueError("REQUEST_ID_EVENT_MISMATCH")
            claim = verify_consent_token(r["consent"], expected_request_id=sample.eventId, expected_sub=sample.pseudonymousUserKey, now=now)
            ct = parse_offset_datetime(claim.consent_timestamp)
            te = sample.trainingEligibility
            if "MODEL_TRAINING" not in claim.scope or "MODEL_TRAINING" not in te.consentScope:
                raise ValueError("CONSENT_SCOPE_MISSING")
            if not te.consentGranted or te.consentWithdrawn:
                raise ValueError("CONSENT_NOT_GRANTED")
            if claim.consent_version != sample.consentVersion:
                raise ValueError("CONSENT_VERSION_MISMATCH")
            if claim.deletion_tracking_id != sample.deletionTrackingId:
                raise ValueError("CONSENT_DELETION_ID_MISMATCH")
            if sample.consentTimestamp is None or ct != sample.consentTimestamp:
                raise ValueError("CONSENT_TIMESTAMP_MISMATCH")
            if ct > datetime.fromtimestamp(now, timezone.utc) + timedelta(seconds=300):
                raise ValueError("CONSENT_TIMESTAMP_IN_FUTURE")
            if sample.pseudonymousUserKey != r["sub"]:
                raise ValueError("SUB_MISMATCH")
            results.append((leaf, "ACCEPT", sample.sourceKind.value if hasattr(sample.sourceKind, "value") else str(sample.sourceKind)))
        elif leaf in ROUTES:
            msg = verify_control(raw, signature=sig, timestamp=ts, request_id=rid, expected=ROUTES[leaf],
                                 now=datetime.fromtimestamp(now, timezone.utc))
            if msg.pseudonymousUserKey is not None and msg.pseudonymousUserKey != r["sub"]:
                raise ValueError("SUB_MISMATCH")
            results.append((leaf, "ACCEPT", msg.messageType.value))
            # 용도 간 재사용 차단: 같은 바이트를 다른 제어 라우트로 보내면 거부돼야 한다.
            for other, mt in ROUTES.items():
                if other != leaf:
                    try:
                        verify_control(raw, signature=sig, timestamp=ts, request_id=rid, expected=mt,
                                       now=datetime.fromtimestamp(now, timezone.utc))
                        fails += 1
                        results.append((leaf, "CROSS_ROUTE_ACCEPTED(" + other + ")", ""))
                    except ControlError as e:
                        if e.code != "CONTROL_MESSAGE_TYPE_MISMATCH":
                            fails += 1
                            results.append((leaf, "CROSS_ROUTE_WRONG_CODE(" + e.code + ")", ""))
            # 변조: 본문 1바이트 → 서명 실패(401)
            try:
                verify_control(raw.replace(b"\"", b" \"", 1), signature=sig, timestamp=ts, request_id=rid, expected=ROUTES[leaf],
                               now=datetime.fromtimestamp(now, timezone.utc))
                fails += 1
                results.append((leaf, "TAMPER_ACCEPTED", ""))
            except ControlError as e:
                if e.status != 401:
                    fails += 1
                    results.append((leaf, "TAMPER_WRONG_STATUS(" + str(e.status) + ")", ""))
        else:
            raise ValueError("UNKNOWN_ROUTE")
    except (SignatureError, ControlError, ValueError) as e:
        fails += 1
        results.append((leaf, "REJECT", getattr(e, "code", None) or str(e)[:80]))
for leaf, verdict, extra in results:
    print(f"{leaf:20s} {verdict:10s} {extra}")
print(f"requests={len(dump['requests'])} failures={fails}")
sys.exit(1 if fails else 0)
