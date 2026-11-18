from app.studymate import quality as Q


def test_verdict_thresholds():
    four = {"a": True, "b": True, "c": True, "d": True}
    assert Q.RubricResult(four, four).verdict == Q.PASS
    assert Q.RubricResult({**four, "d": False}, four).verdict == Q.REPAIR
    assert Q.RubricResult({**four, "c": False, "d": False}, four).verdict == Q.REGENERATE


def test_repair_instruction_keeps_content_and_targets_missing():
    s = Q.repair_instruction(["contains_counterexample", "contains_limitation"], ["37%"])
    assert "최대한 유지" in s and "반례" in s and "한계" in s and "37%" in s
