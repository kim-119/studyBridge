from main import app
from multi_chat_stream_compat import router as multi_chat_stream_compat_router

paths = {getattr(route, "path", None) for route in app.routes}

if "/api/ai/multi-chat/stream" not in paths:
    app.include_router(multi_chat_stream_compat_router)
