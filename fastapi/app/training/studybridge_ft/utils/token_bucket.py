"""시퀀스 길이 → 512/1024/2048 버킷. 2048 비율 상한 강제."""


def estimate_tokens(sample: dict) -> int:
    chars = sum(len(m.get("content", "")) for m in sample.get("messages", []))
    return max(1, chars // 2)


def bucket_of(n_tokens: int, short_max=512, long_max=1024, xlong_max=2048) -> int:
    if n_tokens <= short_max:
        return 512
    if n_tokens <= long_max:
        return 1024
    return 2048


def assign_buckets(samples: list[dict], cfg: dict) -> dict:
    sm, lm, xm = cfg["short_max"], cfg["long_max"], cfg["xlong_max"]
    cap = cfg["xlong_ratio_cap"]
    res = {"512": [], "1024": [], "2048": [], "dropped_xlong": 0}
    xlong = []
    for s in samples:
        b = bucket_of(estimate_tokens(s), sm, lm, xm)
        (xlong if b == 2048 else res[str(b)]).append(s)
    non_x = len(res["512"]) + len(res["1024"])
    # kept_x <= cap*(non_x+kept_x)  =>  kept_x <= cap/(1-cap)*non_x
    allow = int((cap / (1 - cap)) * non_x) if cap < 1 else len(xlong)
    res["2048"] = xlong[:allow]
    res["dropped_xlong"] = len(xlong) - len(res["2048"])
    return res
