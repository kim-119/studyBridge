from main import app
from multi_chat_stream_compat import router as multi_chat_stream_compat_router

paths = {getattr(route, "path", None) for route in app.routes}

if "/api/ai/multi-chat/stream" not in paths:
    app.include_router(multi_chat_stream_compat_router)

# StudyBridge Spring PDF extraction compatibility endpoint
try:
    from .extract_compat import router as extract_compat_router
except Exception:
    from extract_compat import router as extract_compat_router

paths = {getattr(route, "path", None) for route in app.routes}
if "/api/extract" not in paths:
    app.include_router(extract_compat_router)

# StudyBridge group-study realtime quiz endpoint
try:
    from app.api.realtime_quiz_routes import router as realtime_quiz_router
    paths = {getattr(route, "path", None) for route in app.routes}
    if "/api/ai/realtime-quiz/generate" not in paths:
        app.include_router(realtime_quiz_router)
except Exception as e:
    import logging
    logging.getLogger(__name__).warning("realtime_quiz 라우터 로드 실패 (계속 기동): %s", e)

# StudyBridge 텍스트 기반 퀴즈 생성 endpoint (자료 본문 직접 전달용)
try:
    from quiz_text_compat import router as quiz_text_router
    paths = {getattr(route, "path", None) for route in app.routes}
    if "/api/quiz/generate" not in paths:
        app.include_router(quiz_text_router)
except Exception as e:
    import logging
    logging.getLogger(__name__).warning("quiz_text 라우터 로드 실패 (계속 기동): %s", e)
