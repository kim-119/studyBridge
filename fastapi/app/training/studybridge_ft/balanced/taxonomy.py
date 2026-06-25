"""균형 데이터셋 taxonomy: 학문(domain)×세부주제(subdomain), 태스크, 난이도, 페르소나.

스펙 19, 25-36, 38, 42, 49 반영. 모든 분포 게이트/샘플러/프롬프트의 SSOT.
"""

# 12개 학문 영역 → 세부 주제 풀 (스펙 19, 25-36)
DOMAINS: dict[str, list[str]] = {
    "물리학": ["역학", "전자기학", "열역학", "파동", "광학", "현대물리"],
    "수학": ["미적분", "선형대수", "확률통계", "이산수학", "해석학", "대수학", "기하학"],
    "화학": ["일반화학", "유기화학", "무기화학", "물리화학", "분석화학", "생화학"],
    "생물학": ["세포생물학", "유전학", "분자생물학", "생태학", "생리학", "진화생물학"],
    "의학/보건": ["해부생리", "병리학", "약리학", "역학(疫學)", "공중보건", "임상의사결정기초"],
    "경제/경영": ["미시경제", "거시경제", "재무관리", "회계", "마케팅", "조직행동", "전략경영"],
    "컴퓨터공학/AI": ["자료구조", "알고리즘", "운영체제", "네트워크", "데이터베이스",
                  "머신러닝", "딥러닝", "소프트웨어공학"],
    "전기전자/기계/공학": ["전기전자", "기계", "토목", "환경", "재료", "제어", "신호처리"],
    "철학/논리학": ["인식론", "윤리학", "형이상학", "논리학", "과학철학", "정치철학"],
    "심리학/교육학": ["인지심리", "발달심리", "상담심리", "학습이론", "교육평가", "동기이론"],
    "역사/사회과학": ["세계사", "한국사", "사회학", "정치학", "문화인류학", "국제관계"],
    "법/정책": ["헌법", "민법", "형법기초", "행정법", "지식재산", "개인정보보호", "AI정책"],
}

# 태스크 타입 (스펙 38)
TASK_TYPES: list[str] = [
    "concept", "quiz", "debate", "professor",
    "format_safety", "summary", "feedback", "roadmap",
]

# 난이도 (스펙 49)
DIFFICULTIES: list[str] = ["입문", "학사", "석사", "박사", "전문가"]

# 교수 페르소나 (스펙 42)
PERSONAS: list[str] = ["친절형", "비판형", "논리형", "창의형", "간결형", "직접입력형"]

# 위험 도메인 — 단정/처방/자문/투자권유 금지, 교육용 설명으로 제한 (스펙 66-68)
RISK_DOMAINS: dict[str, str] = {
    "의학/보건": "진단 확정·처방 지시 금지, 교육용 설명으로 제한",
    "법/정책": "법률 자문처럼 단정 금지, 학습용 개념 설명으로 제한",
    "경제/경영": "투자 권유 금지, 이론·분석 중심으로 작성",
}

# 분포 캡 (스펙 21, 22, 47, 48)
DOMAIN_CAP_HIGH = 0.15   # 학문 상한
DOMAIN_CAP_LOW = 0.05    # 학문 하한
TASK_CAP_HIGH = 0.25     # 태스크 상한
TASK_CAP_LOW = 0.07      # 태스크 하한

# 편향 드리프트 감지용 키워드 — 해당 학문이 아닌데 이 단어로 도배되면 reject (스펙 65, 84)
DRIFT_KEYWORDS = ["운동량", "인공지능", "딥러닝", "머신러닝", "알고리즘", "ai 모델", "신경망"]
# 드리프트 키워드가 정당한(관련 있는) 학문
DRIFT_OK_DOMAINS = {"물리학", "컴퓨터공학/AI"}


def all_domains() -> list[str]:
    return list(DOMAINS.keys())


def subdomains(domain: str) -> list[str]:
    return DOMAINS[domain]


def is_risk_domain(domain: str) -> bool:
    return domain in RISK_DOMAINS


def validate_taxonomy() -> None:
    """taxonomy 자체 무결성 — 빈 풀/중복 방지."""
    assert len(DOMAINS) == 12, f"학문 12개여야 함, 현재 {len(DOMAINS)}"
    for d, subs in DOMAINS.items():
        assert subs, f"{d} 세부주제 비어있음"
        assert len(subs) == len(set(subs)), f"{d} 세부주제 중복"
    assert len(TASK_TYPES) == len(set(TASK_TYPES))
    assert len(DIFFICULTIES) == 5
    assert len(PERSONAS) == 6
    # 캡 정합성: 균등분할이 캡 범위 안에 들어와야 실현 가능
    even_domain = 1 / len(DOMAINS)
    assert DOMAIN_CAP_LOW <= even_domain <= DOMAIN_CAP_HIGH, "학문 균등분할이 캡 밖"
    even_task = 1 / len(TASK_TYPES)
    assert TASK_CAP_LOW <= even_task <= TASK_CAP_HIGH, "태스크 균등분할이 캡 밖"
