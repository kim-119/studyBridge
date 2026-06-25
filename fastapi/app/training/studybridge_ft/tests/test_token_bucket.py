from app.training.studybridge_ft.utils.token_bucket import (
    estimate_tokens,
    bucket_of,
    assign_buckets,
)


def _mk(nchars):
    return {"messages": [{"role": "user", "content": "x" * nchars},
                         {"role": "assistant", "content": ""}]}


def test_bucket_thresholds():
    assert bucket_of(10) == 512
    assert bucket_of(700) == 1024
    assert bucket_of(5000) == 2048


def test_estimate_tokens():
    assert estimate_tokens(_mk(100)) == 50


def test_xlong_cap_enforced():
    samples = [_mk(100)] * 90 + [_mk(6000)] * 10  # 10% xlong, cap 5%
    cfg = {"short_max": 512, "long_max": 1024, "xlong_max": 2048, "xlong_ratio_cap": 0.05}
    res = assign_buckets(samples, cfg)
    total_kept = len(res["512"]) + len(res["1024"]) + len(res["2048"])
    assert len(res["2048"]) <= total_kept * 0.05 + 1
    assert res["dropped_xlong"] >= 1
