#!/usr/bin/env python3
"""
AI 서버 최소 smoke test.
서버가 http://localhost:8000으로 실행 중일 때 실행한다.
"""
import sys
import time
try:
    import requests
except ImportError:
    print("requests 미설치: pip install requests")
    sys.exit(1)

BASE = "http://localhost:8000"
HEADERS = {}

# AI_SERVER_API_KEY가 있으면 헤더에 포함
import os
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except Exception:
    pass
key = os.getenv("AI_SERVER_API_KEY", "")
if key:
    HEADERS["Authorization"] = f"Bearer {key}"

PASS = "✓"
FAIL = "✗"


def test(name, fn):
    try:
        result = fn()
        print(f"  {PASS} {name}")
        return True
    except AssertionError as e:
        print(f"  {FAIL} {name}: {e}")
        return False
    except Exception as e:
        print(f"  {FAIL} {name}: {type(e).__name__}: {e}")
        return False


print("\nStudyBridge AI Server Smoke Test")
print("=" * 40)

results = []

# 1. Health check
def health():
    r = requests.get(f"{BASE}/api/health", timeout=5)
    assert r.status_code == 200, f"HTTP {r.status_code}"
    data = r.json()
    assert data["status"] == "ok", f"status={data.get('status')}"
results.append(test("GET /api/health → 200 ok", health))

# 2. Swagger docs
def swagger():
    r = requests.get(f"{BASE}/docs", timeout=5)
    assert r.status_code == 200
results.append(test("GET /docs → 200", swagger))

# 3. AI Chat (인증 있을 때만)
if key:
    def chat():
        r = requests.post(
            f"{BASE}/api/ai/chat",
            json={
                "question": "안녕하세요",
                "knowledge_level": "입문",
                "personality": "친절_설명형",
                "agent_name": "테스트",
                "use_gpt_validation": False,
            },
            headers=HEADERS,
            timeout=30,
        )
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        data = r.json()
        assert "answer" in data, "answer 필드 없음"
        assert len(data["answer"]) > 0, "빈 답변"
    results.append(test("POST /api/ai/chat → answer 반환", chat))

# 4. Migration files exist
def migration_files():
    from pathlib import Path
    d = Path(__file__).parent.parent / "app" / "db" / "migrations"
    assert d.exists(), f"{d} 없음"
    files = list(d.glob("*.sql"))
    assert len(files) >= 3, f"SQL 파일 {len(files)}개 (3개 이상 필요)"
results.append(test("마이그레이션 SQL 파일 존재", migration_files))

# 5. run_migrations dry-run
def dry_run():
    import subprocess
    r = subprocess.run(
        [sys.executable, "scripts/run_migrations.py"],
        capture_output=True, text=True,
        cwd=Path(__file__).parent.parent,
    )
    assert "[DRY-RUN]" in r.stdout, f"dry-run 출력 없음:\n{r.stdout}"
results.append(test("run_migrations.py dry-run 동작", dry_run))

# 6. .env.example exists
def env_example():
    from pathlib import Path
    p = Path(__file__).parent.parent / ".env.example"
    assert p.exists(), ".env.example 없음"
    content = p.read_text()
    assert "AI_DATABASE_URL" in content, "AI_DATABASE_URL 없음"
    assert "REDIS_URL" in content, "REDIS_URL 없음"
results.append(test(".env.example 존재 및 필수 항목 포함", env_example))

print()
passed = sum(results)
total = len(results)
print(f"결과: {passed}/{total} 통과")
if passed < total:
    sys.exit(1)
