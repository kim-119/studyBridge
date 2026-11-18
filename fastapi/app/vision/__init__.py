"""화면공유 프레임 1장 + 질문 → VLM 답변 (POST /api/ai/vision/analyze).

기존 기능과 격리된 additive 패키지다. 운영 등록은 hotfix_main.py 에서
``from app.vision.router import router`` 를 include 하면 된다.
"""
