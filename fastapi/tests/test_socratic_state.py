"""소크라테스 persistent state: 버전 스키마, Redis 영속/복원, 매 턴 DIAGNOSIS 재시작 금지."""
import json

from app.services import learning_session as LS
from app.services import socratic_mode_handler as H
from app.services import socratic_multi_agent as MA
from app.services import socratic_session_engine as SE


class FakeRedis:
    def __init__(self):
        self.d = {}

    def get(self, k):
        return self.d.get(k)

    def set(self, k, v, ex=None):
        self.d[k] = v

    def delete(self, k):
        self.d.pop(k, None)


def test_session_survives_process_memory_loss(monkeypatch):
    fr = FakeRedis()
    from app.studymate import redis_sync
    monkeypatch.setattr(redis_sync, "client", lambda: fr)
    s = LS.LearningSession(session_id="socratic-abc", mode="socratic", topic="캐시", state=SE.ASK, turn_index=1,
                           data={"stateV2": {"version": 2, "stage": "ASK"}})
    LS.save("room-1:socratic", s)
    LS.clear_all()                       # 프로세스 재시작 시뮬레이션
    got = LS.get("room-1:socratic")
    assert got is not None and got.state == SE.ASK and got.turn_index == 1
    assert json.loads(fr.d["studybridge:learning-session:room-1:socratic"])["schemaVersion"] == LS.SESSION_SCHEMA_VERSION


def test_stage_progresses_after_first_turn():
    assert H._progress_stage(MA.PROBE, True, "", False)[0] == "DIAGNOSIS"
    assert H._progress_stage(MA.PROBE, False, SE.WRONG, False)[0] == "HINT"
    assert H._progress_stage(MA.PROBE, False, SE.PARTIAL, False)[0] == "APPLICATION"
    assert H._progress_stage(MA.VERIFY, False, SE.CORRECT, True)[0] == "SELF_EXPLANATION"


def test_state_v2_schema_accumulates():
    s = LS.LearningSession(session_id="x", mode="socratic", topic="t", state=SE.DEEPEN, turn_index=2,
                           data={"hintLevel": 1, "stateV2": {"knownMisconceptions": [{"turn": 1}]}})
    sp = MA.AgentSpeech(role=MA.PROBE, agent_id=1, agent_name="a", agent_index=1, text="…", question="왜일까?",
                        assessment=SE.WRONG)
    st = H._socratic_state_v2(s, "캐시는 무조건 빠르다", [sp], is_new=False)
    for k in ("version", "stage", "learnerHypothesis", "knownMisconceptions", "hintsGiven", "previousQuestion", "confidence"):
        assert k in st
    assert st["version"] == 2 and len(st["knownMisconceptions"]) == 2 and st["previousQuestion"] == "왜일까?"
    assert st["confidence"] < 0.5
