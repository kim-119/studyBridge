"""EC2(Spring)↔ai07 버전드 내부 계약의 ai07 측 Pydantic adapter.

정규(canonical) owner 는 EC2 다. 이 패키지는 EC2 가 확정한 fixture 를 그대로 읽어 검증하는 adapter 이며,
EC2 합의 전까지 fixtures/_meta.json 의 status 는 PROPOSED_BY_AI07 이다. 필드를 임의로 추가/재정의하지 않는다
(새 필드는 schemaVersion 을 올려서만 추가한다 → v1 모델은 extra='forbid').
"""
