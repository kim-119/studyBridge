"""테스트 공통 격리: 학습메이트 v2 가 운영 Redis/외부 grounding 에 닿지 않게 한다.
(ai07 에서는 127.0.0.1:16379 이 운영 Redis 터널이라 테스트 키가 운영에 섞일 수 있다)"""
import os

os.environ.setdefault("STUDYMATE_REDIS", "off")
os.environ.setdefault("STUDYMATE_ROLLING_SUMMARY", "off")
os.environ.setdefault("STUDYMATE_GROUNDING", "off")
# 게이트웨이 hermetic: 가짜 transport(tests/studymate_fakes.py)를 설치하지 않은 테스트가 실제 GPU(Ollama)를
# 호출하지 않게 닫힌 포트로 둔다(2026-09-17: 레거시 테스트가 v2 경로에서 운영 Ollama 를 9분간 점유).
os.environ.setdefault("STUDYMATE_OLLAMA_BASE_URL", "http://127.0.0.1:9")

import pytest


@pytest.fixture(autouse=True)
def _ai_gateway_isolation():
    """AI Gateway 의 프로세스 전역 상태(슬롯/브레이커)가 테스트 사이로 새지 않게 매 테스트 초기화한다.
    (장애 주입 테스트의 연속 ConnectionError 가 브레이커를 열어 뒤 테스트가 CIRCUIT_OPEN 을 받는 것을 막음)"""
    try:
        import app.ai_gateway as _gw
        _gw.reset_for_tests(None)
    except Exception:
        _gw = None
    yield
    if _gw is not None:
        _gw.reset_for_tests(None)
