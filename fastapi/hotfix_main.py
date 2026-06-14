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

# StudyBridge 업로드 자료 유형 자동 판별 endpoint (Spring classify-before-save 가 호출)
try:
    from app.api.material_classify_routes import router as material_classify_router
    paths = {getattr(route, "path", None) for route in app.routes}
    if "/api/ai/material/classify" not in paths:
        app.include_router(material_classify_router)
except Exception as e:
    import logging
    logging.getLogger(__name__).warning("material_classify 라우터 로드 실패 (계속 기동): %s", e)

# StudyBridge 자료보관함 퀴즈/로드맵 streaming + SSE job + 폴링 endpoint
# (Spring /api/materials/{id}/quiz|roadmap/jobs|poll 가 릴레이)
try:
    from app.api.material_stream_routes import router as material_stream_router
    paths = {getattr(route, "path", None) for route in app.routes}
    if "/api/ai/quiz/generate-stream" not in paths:
        app.include_router(material_stream_router)
except Exception as e:
    import logging
    logging.getLogger(__name__).warning("material_stream 라우터 로드 실패 (계속 기동): %s", e)

# StudyBridge 오답노트 AI endpoint (해설/유사문제 생성 — Spring review-notes 가 호출)
try:
    from app.api.review_ai_routes import router as review_ai_router
    paths = {getattr(route, "path", None) for route in app.routes}
    if "/api/ai/review/wrong-note-feedback" not in paths:
        app.include_router(review_ai_router)
except Exception as e:
    import logging
    logging.getLogger(__name__).warning("review_ai 라우터 로드 실패 (계속 기동): %s", e)

# StudyBridge 자료보관함 통합 계약 endpoint
# (자료 자동 분류 /api/ai/material-classify, 오답노트 유사문제/AI 해설 /api/ai/review-note/*)
try:
    from app.api.review_note_routes import router as review_note_router
    paths = {getattr(route, "path", None) for route in app.routes}
    if "/api/ai/material-classify" not in paths:
        app.include_router(review_note_router)
except Exception as e:
    import logging
    logging.getLogger(__name__).warning("review_note 라우터 로드 실패 (계속 기동): %s", e)
