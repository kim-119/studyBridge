"""Vision API 실측 부하 테스트 (실제 VLM). 결과는 stdout JSON — 수치는 측정값만 기록한다.

사용:
  AI_SERVER_API_KEY=... .venv/bin/python scripts/vision_load_test.py \
      --url http://127.0.0.1:8012 --concurrency 1 2 5 10 --same-group

화면 픽스처(Python 오류 / 수식 / 이진트리 도식)는 메모리에서 생성하며 디스크에 쓰지 않는다.
--dump-dir 를 주면 확인용으로 픽스처 JPEG 만 저장한다.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import statistics
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import psutil
from PIL import Image, ImageDraw, ImageFont

MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
CJK = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"


def _font(path: str, size: int, index: int = 0):
    try:
        return ImageFont.truetype(path, size, index=index)
    except OSError:
        return ImageFont.load_default()


def _jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82)
    return buf.getvalue()


def fixture_python_error() -> bytes:
    img = Image.new("RGB", (1280, 720), (30, 30, 30))
    d = ImageDraw.Draw(img)
    f = _font(MONO, 22)
    lines = [
        ("main.py", (200, 200, 200)),
        ("1  def average(scores):", (220, 220, 170)),
        ("2      total = sum(scores)", (220, 220, 220)),
        ("3      return total / len(scores)", (220, 220, 220)),
        ("4", (220, 220, 220)),
        ("5  print(average([]))", (220, 220, 220)),
        ("", (0, 0, 0)),
        ("$ python main.py", (150, 220, 150)),
        ("Traceback (most recent call last):", (240, 120, 120)),
        ('  File "main.py", line 5, in <module>', (240, 120, 120)),
        ("    print(average([]))", (240, 120, 120)),
        ('  File "main.py", line 3, in average', (240, 120, 120)),
        ("    return total / len(scores)", (240, 120, 120)),
        ("ZeroDivisionError: division by zero", (255, 90, 90)),
    ]
    y = 30
    for text, color in lines:
        d.text((40, y), text, font=f, fill=color)
        y += 40
    return _jpeg(img)


def fixture_math() -> bytes:
    img = Image.new("RGB", (1024, 576), "white")
    d = ImageDraw.Draw(img)
    f = _font(CJK, 34, index=1)
    d.text((40, 30), "이차방정식의 근의 공식", font=f, fill="black")
    d.text((60, 120), "ax² + bx + c = 0  (a ≠ 0)", font=_font(MONO, 34), fill="black")
    d.text((60, 200), "x = (-b ± √(b² - 4ac)) / 2a", font=_font(MONO, 34), fill=(20, 20, 160))
    d.text((60, 300), "예: x² - 5x + 6 = 0", font=f, fill="black")
    # 간단한 그래프 축 + 포물선
    ox, oy = 700, 500
    d.line((600, oy, 1000, oy), fill="gray", width=2)
    d.line((ox, 300, ox, 560), fill="gray", width=2)
    pts = [(ox + (x - 2.5) * 60, oy - ((x - 2) * (x - 3)) * 40) for x in [i / 10 for i in range(0, 51)]]
    d.line(pts, fill="red", width=3)
    return _jpeg(img)


def fixture_diagram() -> bytes:
    img = Image.new("RGB", (1024, 640), "white")
    d = ImageDraw.Draw(img)
    f = _font(MONO, 30)
    nodes = {"8": (512, 80), "3": (300, 260), "10": (724, 260), "1": (180, 440), "6": (420, 440), "14": (850, 440)}
    edges = [("8", "3"), ("8", "10"), ("3", "1"), ("3", "6"), ("10", "14")]
    for a, b in edges:
        d.line((*nodes[a], *nodes[b]), fill="black", width=3)
    for k, (x, y) in nodes.items():
        d.ellipse((x - 40, y - 40, x + 40, y + 40), fill=(220, 235, 255), outline="black", width=3)
        d.text((x - 9 * len(k), y - 17), k, font=f, fill="black")
    d.text((30, 580), "Binary Search Tree", font=f, fill="black")
    return _jpeg(img)


CASES = [
    ("python_error", fixture_python_error, "이 화면에 표시된 Python 오류의 원인은 무엇이고 어떻게 고치면 되나요?"),
    ("math", fixture_math, "화면의 예시 방정식의 해를 근의 공식으로 구해 설명해줘."),
    ("diagram", fixture_diagram, "이 이진 탐색 트리를 중위 순회하면 어떤 순서가 되나요?"),
]


class Sampler(threading.Thread):
    """0.5초 간격 CPU/RAM/GPU/VRAM 샘플링."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.samples: list[dict] = []
        self._halt = threading.Event()

    def run(self) -> None:
        psutil.cpu_percent(None)
        while not self._halt.is_set():
            s = {"cpu": psutil.cpu_percent(None), "ramUsedMiB": (psutil.virtual_memory().used) // 2**20}
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=2).stdout.strip().split(",")
                s["gpuUtil"], s["vramUsedMiB"] = int(out[0]), int(out[1])
            except Exception:
                pass
            self.samples.append(s)
            self._halt.wait(0.5)

    def stop(self) -> dict:
        self._halt.set()
        self.join()
        def agg(k):
            v = [x[k] for x in self.samples if k in x]
            return {"avg": round(statistics.mean(v), 1), "max": max(v)} if v else None
        return {k: agg(k) for k in ("cpu", "ramUsedMiB", "gpuUtil", "vramUsedMiB")} | {"n": len(self.samples)}


def pct(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    vals = sorted(vals)
    k = (len(vals) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (k - lo), 1)


def one(url: str, key: str, case, group, timeout: float) -> dict:
    name, fx, q = case
    body = {"requestId": str(uuid.uuid4()), "groupId": group, "streamId": "loadtest", "sharerUserId": 1,
            "askerUserId": 2, "question": q, "image": base64.b64encode(fx()).decode(), "mime": "image/jpeg"}
    t0 = time.monotonic()
    try:
        r = httpx.post(f"{url}/api/ai/vision/analyze", json=body, timeout=timeout,
                       headers={"Authorization": f"Bearer {key}"})
        wall = (time.monotonic() - t0) * 1000
        j = r.json()
        return {"case": name, "status": r.status_code, "wallMs": round(wall), "server": j}
    except httpx.TimeoutException:
        return {"case": name, "status": "client_timeout", "wallMs": round((time.monotonic() - t0) * 1000)}


def burst(url, key, n, same_group, timeout) -> dict:
    sampler = Sampler()
    sampler.start()
    t0 = time.monotonic()
    with ThreadPoolExecutor(n) as ex:
        futs = [ex.submit(one, url, key, CASES[i % len(CASES)], 1 if same_group else 100 + i, timeout)
                for i in range(n)]
        res = [f.result() for f in futs]
    total = (time.monotonic() - t0) * 1000
    res_stats = sampler.stop()
    ok = [r for r in res if r["status"] == 200]
    lat = [r["wallMs"] for r in ok]
    codes: dict[str, int] = {}
    for r in res:
        if r["status"] != 200:
            c = r.get("server", {}).get("error", {}).get("code") if isinstance(r.get("server"), dict) else r["status"]
            codes[str(c)] = codes.get(str(c), 0) + 1
    try:
        h = httpx.get(f"{url}/api/ai/vision/health", headers={"Authorization": f"Bearer {key}"}, timeout=5).json()
    except Exception:
        h = {}
    return {
        "n": n, "sameGroup": same_group, "success": len(ok), "failure": n - len(ok), "failureCodes": codes,
        "timeouts": sum(1 for r in res if r["status"] in ("client_timeout", 504)),
        "batchWallMs": round(total),
        "latencyMs": {"avg": round(statistics.mean(lat), 1) if lat else None,
                      "p50": pct(lat, .5), "p95": pct(lat, .95), "p99": pct(lat, .99)},
        "serverInferenceMs": [r["server"].get("inferenceMs") for r in ok],
        "serverQueueWaitMs": [r["server"].get("queueWaitMs") for r in ok],
        "gate": h.get("gate"), "resources": res_stats,
        "answers": [{"case": r["case"], "answer": r["server"]["answer"][:600], "model": r["server"]["model"]}
                    for r in ok],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8012")
    ap.add_argument("--concurrency", type=int, nargs="+", default=[1, 2, 5, 10])
    ap.add_argument("--same-group", action="store_true")
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--dump-dir")
    a = ap.parse_args()
    if a.dump_dir:
        os.makedirs(a.dump_dir, exist_ok=True)
        for name, fx, _ in CASES:
            with open(os.path.join(a.dump_dir, f"{name}.jpg"), "wb") as f:
                f.write(fx())
    key = os.environ.get("AI_SERVER_API_KEY", "")
    out = [burst(a.url, key, n, a.same_group, a.timeout) for n in a.concurrency]
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
