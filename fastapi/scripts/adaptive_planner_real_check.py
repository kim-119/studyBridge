"""적응형 학습 엔진 실모델 검증 — 라이브 앱(hotfix_main, in-process) + AI Gateway + 실제 qwen3:14b / qwen3-vl.

합성 학습 데이터만 쓴다(실사용자 데이터 없음). 운영 Ollama(:11434)·비전 데몬(:11435)을 그대로 쓰되 부하는 가볍게
(동시 최대 4건) 둔다. 안전장치: VRAM 15800MiB 이상이면 중단. 실행 중 운영 studybridge-ai 에 들어온 POST 수를 기록한다
(같은 GPU 를 쓰므로 지연 수치 해석에 반영).
usage: python scripts/adaptive_planner_real_check.py OUT_JSON
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime

OUT = sys.argv[1]
sys.path.insert(0, os.getcwd())
KEY = "adaptive-real-check-local-key"
TEXT = "http://127.0.0.1:11434"
os.environ.update({
    "AI_GATEWAY_ENABLED": "true", "AI_GW_GPU_GUARD": "true", "AI_GW_VISION_PRESSURE_POLICY": "adaptive",
    "AI_SERVER_API_KEY": KEY, "VISION_API_ENABLED": "true", "EMBEDDING_DEVICE": "cpu",
    "OLLAMA_BASE_URL": TEXT, "STUDYMATE_OLLAMA_BASE_URL": TEXT, "OLLAMA_MODEL": "qwen3:14b",
    "OPENAI_API_KEY": "", "STUDYMATE_REDIS": "off", "STUDYMATE_GROUNDING": "off",
})
START = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
URL = "/api/ai/planner/adaptive"
H = {"Authorization": f"Bearer {KEY}"}
samples, stop = [], threading.Event()
state = {"abort": "", "prod_posts": 0}


def smi() -> int:
    return int(subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                              capture_output=True, text=True, timeout=3).stdout.strip())


def sampler():
    while not stop.is_set():
        try:
            u = smi()
            samples.append((time.time(), u))
            if u >= 15800:
                state["abort"] = f"VRAM {u}"
        except Exception:
            pass
        stop.wait(0.3)


def prod_posts() -> int:
    o = subprocess.run(["journalctl", "-u", "studybridge-ai", "--since", START, "--no-pager", "-o", "cat"],
                       capture_output=True, text=True, timeout=10).stdout
    return o.count('"POST /api/')


def check():
    if state["abort"]:
        raise RuntimeError("ABORT " + state["abort"])
    state["prod_posts"] = prod_posts()


# ── 합성 데이터 ───────────────────────────────────────────────────────────

def roadmap(minutes, rid, quiz=None, user=55):
    return {"requestId": rid, "userId": user, "plannerId": 123, "roadmapId": 9, "mode": "ROADMAP_COACH",
            "availableMinutes": minutes, "timezone": "Asia/Seoul", "currentStepId": "cnn-3",
            "items": [
                {"id": "cnn-1", "title": "신경망 기초", "status": "COMPLETED", "orderIndex": 1},
                {"id": "cnn-2", "title": "활성화 함수", "status": "COMPLETED", "orderIndex": 2},
                {"id": "cnn-3", "title": "합성곱 연산", "status": "IN_PROGRESS", "orderIndex": 3,
                 "description": "필터가 입력 위를 이동하며 특징맵을 만드는 과정을 이해한다.",
                 "tasks": [{"id": 31, "text": "3x3 커널 손계산"}, {"id": 32, "text": "PyTorch Conv2d 실습"},
                           {"id": 33, "text": "패딩과 스트라이드 비교"}]},
                {"id": "cnn-4", "title": "풀링 계층", "status": "PENDING", "orderIndex": 4}],
            "quizResults": quiz or []}


def manual(minutes, rid, user=55, items=None):
    return {"requestId": rid, "userId": user, "plannerId": 456, "mode": "MANUAL_NEXT", "availableMinutes": minutes,
            "timezone": "Asia/Seoul",
            "items": items or [
                {"id": 9001, "title": "Java 예외 처리 복습", "subject": "Java", "status": "PENDING",
                 "priority": "보통", "dueDate": "2026-10-31", "estimatedMinutes": 40},
                {"id": 9002, "title": "SQLD 기출문제 풀이", "subject": "SQLD", "status": "PENDING",
                 "priority": "높음", "dueDate": "2026-10-29", "estimatedMinutes": 50},
                {"id": 9003, "title": "네트워크 OSI 7계층", "subject": "네트워크", "status": "COMPLETED"},
                {"id": 9004, "title": "미적분 문제 풀이", "subject": "수학", "status": "PENDING",
                 "dueDate": "2026-10-27", "estimatedMinutes": 60,
                 "tasks": [{"id": "c1", "text": "치환적분 5문제"}, {"id": "c2", "text": "부분적분 5문제"},
                           {"id": "c3", "text": "오답 정리"}]}]}


QUIZ = [{"questionId": "q-101", "correct": False, "conceptTags": ["ReLU"], "itemId": "cnn-2",
         "question": "ReLU 의 음수 입력 출력은?"},
        {"questionId": "q-102", "correct": True, "conceptTags": ["시그모이드"], "itemId": "cnn-2"}]


def jpeg():
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (1280, 720), (250, 250, 252))
    d = ImageDraw.Draw(img)
    for i, line in enumerate(["def average(xs):", "    return sum(xs) / len(xs)", "", "print(average([]))", "",
                              "Traceback (most recent call last):", "ZeroDivisionError: division by zero"]):
        d.text((60, 80 + i * 40), line, fill=(20, 20, 20))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode()


async def main_async(report):
    import httpx
    import hotfix_main
    import app.ai_gateway as gw
    from app.adaptive_planner import service

    service.metrics.reset()
    img = jpeg()
    lat = []

    async def adaptive(c, body, tag):
        t0 = time.perf_counter()
        r = await c.post(URL, json=body, headers=H)
        ms = int((time.perf_counter() - t0) * 1000)
        j = r.json()
        rec = j.get("recommendation") or {}
        lat.append(ms)
        row = {"tag": tag, "status": r.status_code, "clientMs": ms, "source": j.get("source"),
               "engineStatus": j.get("status"), "itemId": rec.get("itemId"),
               "activities": [(a["type"], a["minutes"], a["title"]) for a in rec.get("activities", [])],
               "fallback": (j.get("meta") or {}).get("fallbackReason"),
               "reject": (j.get("meta") or {}).get("llmRejectReasons"),
               "llmMs": (j.get("meta") or {}).get("llmLatencyMs")}
        print("ADAPTIVE", tag, row["status"], ms, row["source"], row["fallback"], row["itemId"], flush=True)
        return row, j

    def chat():
        from app.services.ollama_client import ask_ollama
        t0 = time.perf_counter()
        out = ask_ollama("너는 친절한 튜터다.", "TCP와 UDP 차이를 3문장으로", max_tokens=256, timeout=120)
        return {"ms": int((time.perf_counter() - t0) * 1000), "chars": len(out or "")}

    def multi_agent():
        from app.ai_gateway.context import workload
        from app.ai_gateway.policy import WorkloadClass as W
        from app.studymate import llm_gateway as lg
        t0 = time.perf_counter()
        n = 0
        with workload(W.MULTI_AGENT, "cu:adaptive-check"):
            for k in range(3):
                req = lg.LLMRequest(system=f"너는 교수 {k}이다.", user="프로세스와 스레드 차이", model="qwen3:14b",
                                    num_ctx=8192, num_predict=200, timeout_s=120)
                n += len(lg.generate(req).content)
        return {"ms": int((time.perf_counter() - t0) * 1000), "agents": 3, "chars": n}

    async def vision(c, rid):
        body = {"requestId": rid, "groupId": 7001, "streamId": "con_7001", "question": "이 오류의 원인은?",
                "image": img, "mime": "image/jpeg"}
        t0 = time.perf_counter()
        r = await c.post("/api/ai/vision/analyze", json=body, headers=H)
        j = r.json()
        return {"status": r.status_code, "ms": int((time.perf_counter() - t0) * 1000),
                "error": (j.get("error") or {}).get("code")}

    report["vramStart"] = smi()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=hotfix_main.app), base_url="http://t",
                                 timeout=300) as c:
        ex = {}
        # 1) 단일 요청 — 인수 조건 A/B/C/D 의 실제 응답(JSON 원본 보관)
        single = []
        for tag, body in [("roadmap15", roadmap(15, "rc-15")), ("roadmap30", roadmap(30, "rc-30")),
                          ("roadmap60", roadmap(60, "rc-60")), ("roadmap30_quiz", roadmap(30, "rc-q", QUIZ)),
                          ("manual30", manual(30, "mn-30")), ("manual15", manual(15, "mn-15")),
                          ("manual60", manual(60, "mn-60"))]:
            row, j = await adaptive(c, body, tag)
            single.append(row)
            ex[tag] = {"request": body, "response": j}
            check()
        report["single"] = single
        report["examples"] = ex

        if True:
            # 2) 서로 다른 사용자 2명 동시(데이터 격리)
            r = await asyncio.gather(adaptive(c, manual(30, "u1", user=1, items=[
                {"id": "a1", "title": "사용자A 영어 단어 50개", "dueDate": "2026-10-29"}]), "userA"),
                adaptive(c, manual(30, "u2", user=2, items=[
                    {"id": "b1", "title": "사용자B 운영체제 스케줄링", "dueDate": "2026-10-29"}]), "userB"))
            (ra, ja), (rb, jb) = r
            report["twoUsers"] = {"rows": [ra, rb], "isolated":
                                  ra["itemId"] == "a1" and rb["itemId"] == "b1"
                                  and "사용자B" not in json.dumps(ja, ensure_ascii=False)
                                  and "사용자A" not in json.dumps(jb, ensure_ascii=False)}
            check()
            # 3) ROADMAP + MANUAL 동시
            r = await asyncio.gather(adaptive(c, roadmap(30, "mix-r"), "mix_roadmap"),
                                     adaptive(c, manual(30, "mix-m"), "mix_manual"))
            report["roadmapPlusManual"] = [x[0] for x in r]
            check()

        if True:
            # 4) 일반 채팅: 단독 기준선 → 추천과 동시
            base_chat = await asyncio.to_thread(chat)
            r = await asyncio.gather(asyncio.to_thread(chat), adaptive(c, manual(30, "cc-m"), "with_chat"))
            report["chat"] = {"alone": base_chat, "withAdaptive": r[0], "adaptive": r[1][0]}
            check()
            # 5) 비전 + 추천
            base_vis = await vision(c, f"v-base-{time.time_ns()}")
            r = await asyncio.gather(vision(c, f"v-c-{time.time_ns()}"), adaptive(c, roadmap(30, "cv-r"), "with_vision"))
            report["vision"] = {"alone": base_vis, "withAdaptive": r[0], "adaptive": r[1][0]}
            check()
            # 6) 멀티에이전트 + 추천
            base_ma = await asyncio.to_thread(multi_agent)
            r = await asyncio.gather(asyncio.to_thread(multi_agent), adaptive(c, roadmap(30, "cm-r"), "with_multi_agent"))
            report["multiAgent"] = {"alone": base_ma, "withAdaptive": r[0], "adaptive": r[1][0]}
            check()
            # 7) GPU 대기열 포화: 멀티에이전트+채팅이 텍스트 큐를 잡은 직후 추천 2건 → 규칙 결과 즉시
            ma = asyncio.create_task(asyncio.to_thread(multi_agent))
            ch1 = asyncio.create_task(asyncio.to_thread(chat))
            ch2 = asyncio.create_task(asyncio.to_thread(chat))
            await asyncio.sleep(1.5)
            busy = await asyncio.gather(adaptive(c, manual(30, "busy-1", user=11), "gpu_busy_1"),
                                        adaptive(c, roadmap(30, "busy-2", user=12), "gpu_busy_2"))
            others = await asyncio.gather(ma, ch1, ch2)
            report["gpuBusy"] = {"adaptive": [x[0] for x in busy], "others": others,
                                 "textQueueAtEnd": gw.get_scheduler().snapshot()["backends"]}
            check()

        # 8) LLM 타임아웃(실모델, 1.5초 예산) → 규칙 결과
        os.environ["ADAPTIVE_LLM_TIMEOUT_S"] = "1.5"
        report["llmTimeout"] = (await adaptive(c, roadmap(60, "to-1"), "llm_timeout"))[0]
        os.environ.pop("ADAPTIVE_LLM_TIMEOUT_S")
        # 9) Ollama 장애(닫힌 포트) → 규칙 결과
        os.environ["STUDYMATE_OLLAMA_BASE_URL"] = "http://127.0.0.1:9"
        report["llmDown"] = (await adaptive(c, manual(30, "down-1"), "llm_down"))[0]
        os.environ["STUDYMATE_OLLAMA_BASE_URL"] = TEXT

        h = (await c.get(URL + "/health")).json()
        report["metrics"] = h["metrics"]
        report["gateway"] = gw.status()
    report["adaptiveLatencyMs"] = {"n": len(lat), "p50": statistics.median(lat),
                                   "p95": sorted(lat)[max(0, int(round(.95 * (len(lat) - 1))))]}


def main():
    report = {"start": START}
    th = threading.Thread(target=sampler, daemon=True)
    th.start()
    try:
        asyncio.run(main_async(report))
    except Exception as e:  # noqa: BLE001
        report["error"] = f"{type(e).__name__}: {e}"
    finally:
        stop.set()
        th.join(2)
        report["vramPeak"] = max((u for _, u in samples), default=None)
        report["vramEnd"] = smi()
        report["prodPostsDuringRun"] = prod_posts()
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1, default=str)
        print("REPORT", OUT, report.get("error") or "ok", flush=True)


if __name__ == "__main__":
    main()
