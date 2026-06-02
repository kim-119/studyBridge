"""
Qwen2.5 생성(generation) 파라미터 중앙 관리.
qwen_service.py에서 직접 참조한다.
"""

# 기본 생성 파라미터 — 필요 시 개별 호출에서 오버라이드 가능
TEMPERATURE: float = 0.3
MAX_TOKENS: int    = 1024

# RAG 답변처럼 정확성이 더 중요한 경우 낮은 temperature 사용
RAG_TEMPERATURE: float = 0.2
RAG_MAX_TOKENS: int    = 2048
