"""Adaptive Learning Intelligence — POST /api/ai/planner/adaptive.

ENGINE A ROADMAP_COACH : 로드맵의 '현재 단계'를 주어진 시간(15/30/60분) 안에 학습하도록 코칭한다.
                         다음 단계는 추천하지 않는다(순서는 로드맵이 이미 정했다).
ENGINE B MANUAL_NEXT   : 수기 플래너의 미완료 항목 중 무엇을 먼저 할지 결정적 점수로 고른다.

공통: 대상 선정·시간 배분·근거 ID 는 결정적 규칙이 정하고, Qwen3 는 필요할 때 문구만 다듬는다.
LLM 출력은 검증을 통과해야만 쓰이고, 실패하면 규칙 결과를 그대로 낸다. ai07 은 DB 를 바꾸지 않는다.
연동 계약: docs/planner/적응형_학습엔진_API_연동계약.md
"""
