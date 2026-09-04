from app.api.planner_ai_routes import _analyze_sync


def test_planner_analyze_accepts_current_spring_payload():
    result = _analyze_sync({
        "plannerId": 304,
        "title": "자료구조 3일차",
        "subject": "자료구조",
        "content": "트리 개념 정리\n순회 문제 풀이",
        "goalTime": "3시간",
        "netStudyTime": "1시간 30분",
        "dDay": "5",
        "studyType": "시험 준비",
        "priority": "높음",
        "checklist": ["트리 개념 정리", "순회 문제 풀이"],
        "completedTasks": [],
        "incompleteTasks": ["트리 개념 정리", "순회 문제 풀이"],
        "progress": 0,
    })

    assert result["success"] is True
    assert isinstance(result["schedule"], list) and result["schedule"]
    assert isinstance(result["checklist"], list) and result["checklist"]
    assert isinstance(result["scheduleAnalysis"], list) and result["scheduleAnalysis"]
    assert isinstance(result["problemPoints"], list) and result["problemPoints"]
    assert isinstance(result["improvementActions"], list) and result["improvementActions"]
    assert isinstance(result["balanceAssessment"], str) and result["balanceAssessment"]
