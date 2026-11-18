from app.training.studybridge_ft.balanced import taxonomy as tx


def test_taxonomy_integrity():
    tx.validate_taxonomy()  # 예외 없어야 함


def test_12_domains_each_with_subdomains():
    assert len(tx.DOMAINS) == 12
    for d in tx.all_domains():
        assert len(tx.subdomains(d)) >= 3, f"{d} 세부주제 3개 미만"  # 스펙 69


def test_required_axes_present():
    assert set(tx.TASK_TYPES) >= {"concept", "quiz", "debate", "professor",
                                  "format_safety", "summary", "feedback", "roadmap"}
    assert tx.DIFFICULTIES == ["입문", "학사", "석사", "박사", "전문가"]
    assert len(tx.PERSONAS) == 6


def test_risk_domains_flagged():
    assert tx.is_risk_domain("의학/보건")
    assert tx.is_risk_domain("법/정책")
    assert tx.is_risk_domain("경제/경영")
    assert not tx.is_risk_domain("물리학")


def test_even_split_within_caps():
    # 12학문 균등 = 8.3% → [5%,15%] 안
    assert tx.DOMAIN_CAP_LOW <= 1 / 12 <= tx.DOMAIN_CAP_HIGH
    # 8태스크 균등 = 12.5% → [7%,25%] 안
    assert tx.TASK_CAP_LOW <= 1 / 8 <= tx.TASK_CAP_HIGH
