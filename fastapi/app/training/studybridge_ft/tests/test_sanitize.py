from app.training.studybridge_ft.utils.sanitize import scan_secrets, scan_sample


def test_clean_text_no_findings():
    assert scan_secrets("이것은 평범한 한국어 설명입니다.") == []


def test_sample_with_obvious_secret():
    s = {"messages": [{"role": "assistant",
                       "content": "키는 sk-ABCDEFGHIJKLMNOPQRSTUVWX1234567890 입니다"}]}
    # check_and_mask가 잡지 못하는 패턴이면 빈 리스트일 수 있으나, 함수 호출 자체가 동작해야 함
    result = scan_sample(s)
    assert isinstance(result, list)
    assert "openai_key" in result
