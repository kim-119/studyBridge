"""KV 캐시 f16 vs q8_0 품질 평가 — 정답이 정해진 문항으로 정확도를 비교한다(주관 판정 없음).

문항: 수학(정수 답) · 코드 출력 예측(실행 없이 정답 비교) · 한국어 객관식 · 장문 needle(5천 토큰대 문맥 속 코드).
temperature 0 / seed 7 / think=false / num_ctx 8192 고정. 모델이 낸 코드는 실행하지 않는다.
usage: python kv_quality_eval.py BASE_URL LABEL OUT_JSON
"""
from __future__ import annotations

import json
import random
import re
import sys
import time

import requests

BASE, LABEL, OUT = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
MODEL = "qwen3:14b"

ITEMS = [
    # (id, category, prompt, checker)
    ("m1", "math", "2의 10제곱에 3의 5제곱을 더한 값은? 숫자만 답하라.", ("int", 1267)),
    ("m2", "math", "1부터 100까지의 자연수 중 3의 배수의 합은? 숫자만 답하라.", ("int", 1683)),
    ("m3", "math", "x^2 - 5x + 6 = 0 의 두 근의 곱은? 숫자만 답하라.", ("int", 6)),
    ("m4", "math", "삼각형의 두 내각이 47도와 68도일 때 나머지 한 각은 몇 도인가? 숫자만 답하라.", ("int", 65)),
    ("m5", "math", "원금 1000만원을 연이율 5% 복리로 2년 맡기면 원리금은 몇 원인가? 숫자만 답하라(쉼표 없이).", ("int", 11025000)),
    ("m6", "math", "사과 17개 중 5개를 먹고, 남은 개수의 3배를 친구에게서 더 받았다. 지금 사과는 몇 개인가? 숫자만 답하라.", ("int", 48)),
    ("c1", "code", "다음 파이썬 코드의 출력만 답하라.\n```python\na = [1, 2, 3, 4, 5, 6]\nprint(a[1:5:2])\n```", ("text", "[2, 4]")),
    ("c2", "code", "다음 파이썬 코드의 출력만 답하라.\n```python\nd = {}\nfor w in 'banana':\n    d[w] = d.get(w, 0) + 1\nprint(sorted(d.items()))\n```", ("text", "[('a', 3), ('b', 1), ('n', 2)]")),
    ("c3", "code", "다음 파이썬 코드의 출력만 답하라.\n```python\ndef f(n):\n    return 1 if n <= 1 else n * f(n - 1)\nprint(f(6) // 7)\n```", ("int", 102)),
    ("c4", "code", "다음 Java 코드의 출력만 답하라.\n```java\nint x = 7;\nint y = x++ + ++x;\nSystem.out.println(x + \" \" + y);\n```", ("text", "9 16")),
    ("c5", "code", "다음 파이썬 코드의 출력만 답하라.\n```python\ns = 'StudyBridge'\nprint(s[::-1][:5].upper())\n```", ("text", "EGDIR")),
    ("k1", "korean", "다음 중 맞춤법이 올바른 문장의 기호만 답하라.\nA. 금새 비가 그쳤다.\nB. 오랫만에 친구를 만났다.\nC. 왠지 기분이 좋다.\nD. 어의없는 일이 생겼다.", ("choice", "C")),
    ("k2", "korean", "'드리다'는 '주다'의 어떤 높임 표현인가? 기호만 답하라.\nA. 주체 높임\nB. 객체 높임\nC. 상대 높임\nD. 높임 아님", ("choice", "B")),
    ("k3", "korean", "다음 글의 중심 내용으로 가장 알맞은 것의 기호만 답하라.\n글: 운동은 신체 건강뿐 아니라 스트레스를 줄이고 수면의 질을 높여 정신 건강에도 도움이 된다. 따라서 규칙적인 운동은 몸과 마음 모두를 위한 투자다.\nA. 운동은 수면에 해롭다\nB. 운동은 몸과 마음 모두에 이롭다\nC. 스트레스는 운동으로만 줄일 수 있다\nD. 정신 건강은 운동과 무관하다", ("choice", "B")),
    ("k4", "korean", "훈민정음이 반포된 해는 서기 몇 년인가? 숫자만 답하라.", ("int", 1446)),
]

FILLER = ("스터디브릿지는 학습자들이 함께 공부하는 플랫폼이다. 그룹 스터디에서는 화면을 공유하고 퀴즈를 풀며 "
          "서로의 진도를 확인한다. 학습 기록은 매일 정리되어 복습 일정에 반영된다. ")


def needle_items():
    rng = random.Random(11)
    out = []
    for i, depth in enumerate((0.1, 0.5, 0.9)):
        code = rng.randint(1000, 9999)
        n = 70                                     # 약 5천 토큰
        parts = [FILLER] * n
        parts.insert(int(n * depth), f"중요: 오늘의 비밀 코드는 {code} 이다. ")
        prompt = "".join(parts) + "\n\n위 글에서 '오늘의 비밀 코드'는 무엇인가? 숫자만 답하라."
        out.append((f"n{i+1}", "long_context", prompt, ("int", code)))
    return out


def grade(answer: str, chk) -> bool:
    kind, expect = chk
    a = answer.strip()
    if kind == "int":
        nums = re.findall(r"-?\d[\d,]*", a)
        return any(int(n.replace(",", "")) == expect for n in nums[:3])
    if kind == "choice":
        m = re.search(r"\b([A-D])\b", a.upper())
        return bool(m) and m.group(1) == expect
    return expect.replace(" ", "") in a.replace(" ", "").replace("`", "")


def main():
    rows = []
    for iid, cat, prompt, chk in ITEMS + needle_items():
        body = {"model": MODEL, "stream": False, "think": False, "keep_alive": "5m",
                "messages": [{"role": "user", "content": prompt}],
                "options": {"num_ctx": 8192, "num_predict": 200, "temperature": 0, "seed": 7}}
        t0 = time.perf_counter()
        d = requests.post(f"{BASE}/api/chat", json=body, timeout=300).json()
        ans = (d.get("message") or {}).get("content") or ""
        rows.append({"id": iid, "cat": cat, "ok": grade(ans, chk), "answer": ans[:200],
                     "latency_s": round(time.perf_counter() - t0, 2),
                     "prompt_tokens": d.get("prompt_eval_count"), "eval_tps": round(
                         (d.get("eval_count") or 0) / max(1e-9, (d.get("eval_duration") or 1) / 1e9), 1)})
    acc = {}
    for cat in sorted({r["cat"] for r in rows}):
        rs = [r for r in rows if r["cat"] == cat]
        acc[cat] = f"{sum(r['ok'] for r in rs)}/{len(rs)}"
    summary = {"label": LABEL, "accuracy": acc, "total": f"{sum(r['ok'] for r in rows)}/{len(rows)}"}
    json.dump({"summary": summary, "rows": rows}, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
