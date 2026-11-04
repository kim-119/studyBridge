"""운영 로그 원문 유출 회귀 가드.

2026-11-04 운영 journal 72시간 비식별 분석(36,205줄)에서 학습메이트 [MODE-TRACE]/[MEMORY-TRACE] 가 사용자 메시지 앞
80자를 userId/roomId 와 함께 42회 기록한 것을 확인했다. logger 인자에 사용자 원문/LLM 출력 계열 값을 '잘라서'(x[:80])
넣는 호출을 금지한다(길이/해시가 필요하면 app.utils.log_safety.fp 사용).
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SENS = {"question", "message", "content", "answer", "text", "query", "user_query", "userquestion", "memo", "memotext",
        "prompt", "user_prompt", "draft", "response", "raw", "ai_response", "corrected_answer"}
TARGETS = [ROOT / "app", ROOT / "main.py", ROOT / "multi_chat_stream_compat.py", ROOT / "quiz_text_compat.py",
           ROOT / "hotfix_main.py"]


def _names(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            yield n.id.lower()
        elif isinstance(n, ast.Attribute):
            yield n.attr.lower()


def _is_raw_slice(a) -> bool:
    if isinstance(a, ast.Call) and isinstance(a.func, ast.Name) and a.func.id in ("repr", "str") and a.args:
        a = a.args[0]
    if isinstance(a, ast.Subscript) and isinstance(a.slice, ast.Slice) and isinstance(a.value, (ast.Name, ast.Attribute, ast.BoolOp)):
        return any(n in SENS for n in _names(a.value))
    if isinstance(a, ast.IfExp):
        return _is_raw_slice(a.body) or _is_raw_slice(a.orelse)
    return False


def _files():
    for t in TARGETS:
        if t.is_file():
            yield t
        elif t.is_dir():
            for p in t.rglob("*.py"):
                if "/training/" not in str(p):
                    yield p


def test_fingerprint_hides_content():
    from app.utils.log_safety import fp
    s = fp("김민수 학생이 질문한 내용")
    assert s.startswith("len=") and "김민수" not in s and len(s) < 40


def test_no_logger_call_logs_sliced_user_or_llm_text():
    hits = []
    for p in _files():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and \
                    n.func.attr in ("info", "warning", "debug", "error", "exception", "critical") and \
                    isinstance(n.func.value, ast.Name) and n.func.value.id in ("logger", "log", "_log", "LOGGER"):
                if any(_is_raw_slice(a) for a in n.args[1:]):
                    hits.append(f"{p.relative_to(ROOT)}:{n.lineno}")
    assert hits == [], hits
