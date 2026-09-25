"""
Stage 지시 빌더 + 할루시네이션 가드 + 답변 안전 검증 단위 테스트 (stage_support).

LLM/네트워크 호출 없음. 순수 함수만 검증한다.
"""
from app.services import stage_support as SS


# ── stage 지시 빌더 ──────────────────────────────────────────────────────────
def test_stage_directives_present_and_distinct():
    first = SS.first_answer_directive()
    val = SS.validation_directive()
    peer = SS.peer_feedback_directive("에이전트 2, 에이전트 3")
    assert "1차 빠른 초안" in first
    assert "2차 검증" in val
    assert "3차 상호 피드백" in peer
    assert first != val != peer


def test_hallucination_guard_included_in_answer_stages():
    guard_head = "[정확성·불확실성 규칙"
    assert guard_head in SS.first_answer_directive()
    assert guard_head in SS.validation_directive()
    # with_guard=False 면 미포함
    assert guard_head not in SS.first_answer_directive(with_guard=False)


def test_hallucination_guard_content():
    g = SS.hallucination_guard_directive()
    assert "모른다" in g
    assert "근거" in g
    assert "확인 필요" in g


def test_peer_feedback_directive_mentions_targets():
    d = SS.peer_feedback_directive("봇A, 봇B")
    assert "봇A, 봇B" in d
    assert ("동어 반복" in d or "단순 칭찬" in d)


# ── 답변 안전/품질 검증 ───────────────────────────────────────────────────────
def test_validate_empty_is_error():
    r = SS.validate_answer_safety("", "RAG란?")
    assert r["severity"] == "error"
    assert r["ok"] is False
    assert r["flags"]["empty"] is True


def test_validate_fallback_message_is_error():
    r = SS.validate_answer_safety("현재 Ollama 서버에 연결할 수 없습니다.", "RAG란?")
    assert r["severity"] == "error"
    assert r["flags"]["fallback"] is True


def test_validate_too_short_is_warning():
    r = SS.validate_answer_safety("응 맞아.", "RAG에서 chunk size는?", min_chars=20)
    assert r["severity"] == "warning"
    assert r["flags"]["tooShort"] is True


def test_validate_overconfidence_flagged():
    r = SS.validate_answer_safety(
        "이 방법은 무조건 100% 옳습니다. RAG는 검색증강생성 기법입니다 그리고 더 자세한 설명입니다.",
        "RAG란?",
    )
    assert r["flags"]["overconfident"] is True
    assert r["severity"] == "warning"


def test_validate_offtopic_flagged_for_long_irrelevant_answer():
    ans = ("오늘 날씨가 아주 좋고 산책하기 적당한 바람이 불며 커피 한 잔과 함께 "
           "여유로운 오후를 보내기에 정말 좋은 하루라고 생각합니다 정말로 좋네요")
    r = SS.validate_answer_safety(ans, "WebSocket과 HTTP polling 차이를 설명해줘")
    assert r["flags"]["offTopic"] is True


def test_validate_good_answer_is_ok():
    r = SS.validate_answer_safety(
        "RAG는 외부 지식을 검색해 LLM 답변 품질을 높이는 기법입니다. chunk size와 overlap으로 맥락을 보존합니다.",
        "RAG에서 chunk size와 overlap은 왜 필요한가?",
    )
    assert r["severity"] == "ok"
    assert r["ok"] is True


def test_validate_never_raises_on_bad_input():
    # 비정상 입력에도 예외를 던지지 않고 ok 로 폴백
    r = SS.validate_answer_safety(None, None)  # type: ignore[arg-type]
    assert "severity" in r and "flags" in r


def test_token_splitter_separates_ascii_and_hangul():
    assert SS.re_split_tokens("RAG란 무엇인가?") == ["RAG", "란", "무엇인가"]
