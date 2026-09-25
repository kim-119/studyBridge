"""
agent_chat_service.py — agent_chat_manager 호환 래퍼.

ai_chat_routes.py 가 `from app.services.agent_chat_service import run_agent_chat` 로
import하므로, 실제 구현은 agent_chat_manager 에 두고 여기서 재노출한다.
"""
from app.services.agent_chat_manager import run_agent_chat  # noqa: F401
