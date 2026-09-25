"""테스트 공통 격리: 학습메이트 v2 가 운영 Redis/외부 grounding 에 닿지 않게 한다.
(ai07 에서는 127.0.0.1:16379 이 운영 Redis 터널이라 테스트 키가 운영에 섞일 수 있다)"""
import os

os.environ.setdefault("STUDYMATE_REDIS", "off")
os.environ.setdefault("STUDYMATE_ROLLING_SUMMARY", "off")
os.environ.setdefault("STUDYMATE_GROUNDING", "off")
# 게이트웨이 hermetic: 가짜 transport(tests/studymate_fakes.py)를 설치하지 않은 테스트가 실제 GPU(Ollama)를
# 호출하지 않게 닫힌 포트로 둔다(2026-09-17: 레거시 테스트가 v2 경로에서 운영 Ollama 를 9분간 점유).
os.environ.setdefault("STUDYMATE_OLLAMA_BASE_URL", "http://127.0.0.1:9")
