import json

from app.studymate.sse_contract import envelope, serialize


def test_korean_emoji_newlines_roundtrip():
    text = "한글 답변\n줄바꿈 \"따옴표\" 😀 \\역슬래시"
    s = serialize("agent_answer", envelope("agent_answer", {"answer": text}, request_id="r", turn_id="t", mode="basic"))
    assert s.startswith("event: agent_answer\ndata: ") and s.endswith("\n\n")
    data_line = s.split("\n")[1]
    assert "\\u" not in data_line  # ensure_ascii=False
    assert json.loads(data_line[6:])["answer"] == text
    assert s.count("\n\n") == 1  # 본문 줄바꿈이 SSE 프레임을 깨지 않는다
