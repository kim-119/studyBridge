"""turn_semantic_dedup — 같은 turn/같은 화자의 '의미 중복 답변' 탐지 단위 테스트.

핵심 계약:
  - 표현만 다르고 의미가 같은 재진술(정의 반복) → near-duplicate(True)
  - 같은 주제라도 보안 심화/명령어 예시 등 '새로운 정보' → distinct(False)
  - priors 가 없으면(=새 turn 첫 발화) 절대 중복 아님(False)
  - 다른 화자 비교는 호출부 스코프 책임. 이 모듈은 주어진 priors 만 본다.
"""
import pytest

from app.services import turn_semantic_dedup as D


# 실측(2026-06-23 라이브 SSE) 기반 표본.
DEF_LONG = (
    "정의하면 SSH는 Secure Shell의 약자로, 원격 접속을 위한 암호화된 프로토콜이다. "
    "구분 기준은 일반적인 Telnet이나 FTP와 달리 데이터 전송 시 암호화를 적용하는 점이다. "
    "작동 방식은 클라이언트와 서버 간에 암호화된 통신 채널을 생성하고, 이후 명령어를 "
    "실행하거나 파일을 전송하는 방식이다. 주의할 점은 SSH 접속 시 공개키 인증을 "
    "사용하는 것이 좋다는 점이다."
)
WRAP_RESTATE = "SSH는 원격 서버에 안전하게 접속하기 위한 암호화 통신 프로토콜이다. 보안상 주의할 점은 무엇인가?"
DEF_SHORT_1 = "SSH는 암호화된 원격 접속 프로토콜이다"
DEF_SHORT_2 = "SSH는 암호화된 방식으로 원격 서버에 연결하는 프로토콜이다"
SEC_EXPAND = (
    "개인키 권한을 600으로 설정하고, 비밀번호 로그인을 차단한 뒤 known_hosts 검증을 "
    "켜야 한다. 가장 먼저 점검할 것은 개인키 파일 권한이다."
)
CMD_EXAMPLE = (
    "실습으로 ssh-keygen -t ed25519 로 키를 만들고 ssh-copy-id 로 서버에 등록한 뒤 "
    "ssh user@host 로 접속해보자."
)


@pytest.fixture(autouse=True)
def _force_on(monkeypatch):
    monkeypatch.setenv("TURN_SEMANTIC_DEDUP", "on")
    monkeypatch.delenv("TURN_SEMANTIC_DEDUP_MIN_NOVELTY", raising=False)


# ── 중복으로 잡아야 하는 케이스(정의 재진술) ──────────────────────────────────
def test_wrap_restating_definition_is_near_duplicate():
    assert D.is_near_duplicate(WRAP_RESTATE, [DEF_LONG]) is True


def test_paraphrased_short_definition_is_near_duplicate():
    # 프롬프트가 명시한 핵심 시나리오: 표현만 다른 두 정의.
    assert D.is_near_duplicate(DEF_SHORT_2, [DEF_SHORT_1]) is True


def test_exact_repeat_is_near_duplicate():
    assert D.is_near_duplicate(DEF_SHORT_1, [DEF_SHORT_1]) is True


# ── 통과해야 하는 케이스(새로운 정보 = 확장) ──────────────────────────────────
def test_security_expansion_is_not_duplicate():
    assert D.is_near_duplicate(SEC_EXPAND, [DEF_LONG]) is False


def test_command_example_is_not_duplicate():
    assert D.is_near_duplicate(CMD_EXAMPLE, [DEF_LONG]) is False


def test_no_priors_is_never_duplicate():
    assert D.is_near_duplicate(DEF_LONG, []) is False


def test_empty_candidate_is_not_duplicate():
    assert D.is_near_duplicate("", [DEF_LONG]) is False


# ── 스코프/escape hatch ───────────────────────────────────────────────────────
def test_disabled_via_env_returns_false(monkeypatch):
    monkeypatch.setenv("TURN_SEMANTIC_DEDUP", "off")
    assert D.is_near_duplicate(WRAP_RESTATE, [DEF_LONG]) is False


def test_novelty_separation_holds():
    # 재진술 < 임계 < 확장. 회귀 시 마진 붕괴를 잡는다.
    restate = D.novelty_ratio(WRAP_RESTATE, [DEF_LONG])
    expand = D.novelty_ratio(SEC_EXPAND, [DEF_LONG])
    assert restate < 0.78 <= expand
