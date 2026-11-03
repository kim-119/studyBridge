"""learning-loop/quality-gate 테스트 공용 헬퍼(운영 DB/Ollama/Redis 에 닿지 않는다)."""
import json
from datetime import datetime, timezone
from pathlib import Path

from app.contracts.training_sample_v1 import TrainingSampleV1, compute_content_hash

INTERNAL_KEY = "k" * 40
ADMIN_TOKEN = "a" * 48
PK = "pk_7f3a9c2e1b4d6a8f"
FIXTURES = Path(__file__).resolve().parents[1] / "app" / "contracts" / "fixtures"


def fixture(sub: str, name: str) -> dict:
    return json.loads((FIXTURES / sub / name).read_text(encoding="utf-8"))


def admin_headers(role="training_admin", actor="reviewer-01", rid="req-admin-0001"):
    return {"Authorization": f"Bearer {INTERNAL_KEY}", "X-Training-Admin-Token": ADMIN_TOKEN,
            "X-Actor-Id": actor, "X-Actor-Role": role, "X-Request-Id": rid}


def service_headers():
    return {"Authorization": f"Bearer {INTERNAL_KEY}"}


_TOPICS = [
    ("이진 탐색의 시간 복잡도는?", "정렬된 배열에서 절반씩 범위를 줄이므로 O(log n) 이다."),
    ("광합성에서 빛 에너지는 어떻게 쓰이나?", "엽록체의 틸라코이드에서 빛 에너지로 ATP 와 NADPH 를 만든다."),
    ("TCP 3-way handshake 단계는?", "SYN, SYN-ACK, ACK 세 단계로 연결을 수립한다."),
    ("뉴턴 제2법칙을 설명해줘", "힘은 질량과 가속도의 곱 F=ma 로 표현된다."),
    ("파이썬 리스트와 튜플 차이는?", "리스트는 변경 가능하고 튜플은 변경 불가능한 시퀀스다."),
    ("세포 분열에서 감수 분열의 특징은?", "염색체 수가 절반인 생식 세포를 만들며 두 번 분열한다."),
    ("수요 곡선이 우하향하는 이유는?", "가격이 오르면 대체 효과와 소득 효과로 수요량이 줄기 때문이다."),
    ("SQL 에서 JOIN 과 UNION 차이는?", "JOIN 은 열을 옆으로 결합하고 UNION 은 행을 위아래로 합친다."),
    ("산화 환원 반응이란?", "전자를 잃는 산화와 전자를 얻는 환원이 동시에 일어나는 반응이다."),
    ("해시 테이블 평균 탐색 시간은?", "좋은 해시 함수와 적재율 관리 시 평균 O(1) 이다."),
    ("조선 훈민정음 창제 목적은?", "백성이 쉽게 글을 익혀 뜻을 펼 수 있게 하려는 것이다."),
    ("미분의 기하학적 의미는?", "곡선 위 한 점에서의 접선의 기울기를 뜻한다."),
    ("운영체제 교착 상태 4조건은?", "상호 배제, 점유 대기, 비선점, 순환 대기 네 조건이 모두 성립할 때다."),
    ("DNA 이중 나선 염기쌍 규칙은?", "아데닌은 티민과, 구아닌은 사이토신과 수소 결합한다."),
]


def make_sample(i: int = 0, *, user=PK, kind="GENERAL_QA", rights="NO_THIRD_PARTY_CONTENT", feedback=None,
                question=None, answer=None, evidence=None, consent=True, scope=("MODEL_TRAINING",),
                revision=None, verified=None) -> TrainingSampleV1:
    t = _TOPICS[i % len(_TOPICS)]
    q = question or f"{t[0]} (세트 {i // len(_TOPICS)}-{i})"
    a = answer or f"{t[1]} 참고 번호 {i * 7919 % 10007}."
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    return TrainingSampleV1.model_validate({
        "schemaVersion": "training-sample.v1", "eventId": f"evt-test-{i:06d}", "pseudonymousUserKey": user,
        "consentVersion": "tc-2026-10" if consent else None, "consentTimestamp": now.isoformat() if consent else None,
        "sourceKind": kind, "sourceRevisionHash": revision, "rightsStatus": rights, "question": q,
        "candidateAnswer": a, "verifiedAnswer": verified, "evidence": evidence or [],
        "feedback": ({"score": feedback, "updatedAt": now.isoformat(), "history": [feedback]} if feedback is not None else None),
        "modelName": "qwen3:14b", "modelDigest": "bdbd181c33f2", "contentHash": compute_content_hash(q, a),
        "createdAt": now.isoformat(), "deletionTrackingId": f"del-{user[:10]}-{i:04d}",
        "retentionPolicy": "TRAINING_CANDIDATE_365D",
        "trainingEligibility": {"consentGranted": consent, "consentScope": list(scope), "consentWithdrawn": False,
                                "decidedAt": now.isoformat()},
    })
