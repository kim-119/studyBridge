# Redis 사용 가이드

---

## 1. Redis 키 구조

| 키 패턴 | 용도 | TTL |
|---|---|---|
| `validation:{job_id}` | GPT 검증 작업 상태 | 1시간 |
| `chat_lock:{user_id}:{hash}` | 중복 요청 방지 lock | 30초 |
| `ai_cache:{agent_id}:{level}:{hash}` | AI 답변 캐시 | 10분 |
| `tavily_cache:{query_hash}` | Tavily 검색 결과 캐시 | 10분 |
| `wiki_cache:{query_hash}` | Wikipedia 검색 결과 캐시 | 30분 |
| `agent_round:{session_id}` | 티키타카 라운드 상태 | 10분 |
| `rate_limit:ai:{user_id}` | 사용자별 요청 rate limit | 1분 |

## 2. 저장하면 안 되는 데이터

- 사용자 대화 원문 전체 (→ ai-db PostgreSQL에 저장)
- 학습 후보 원본 Q/A (→ ai.training_candidate 테이블)
- 개인정보, 인증 토큰

## 3. Redis 연결 실패 시 동작

Redis 연결에 실패해도 FastAPI 서버 전체가 죽지 않는다.

| 기능 | Redis 없을 때 동작 |
|---|---|
| 검증 작업 상태 | 인메모리 dict fallback |
| AI 답변 캐시 | 캐시 없이 매번 생성 |
| Rate limit | 제한 없이 허용 |
| 티키타카 상태 | 매 요청마다 새로 생성 |

## 4. Redis 설정 (infra/docker-compose.ai.local.yml)

```yaml
redis:
  image: redis:7-alpine
  command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru
```

- `--appendonly yes`: 재시작 후 데이터 복구
- `--maxmemory 256mb`: 메모리 한도
- `--maxmemory-policy allkeys-lru`: 한도 초과 시 LRU 방식으로 삭제

## 5. 연결 설정

```
# Docker 내부 (컨테이너명: capstone-redis)
REDIS_URL=redis://capstone-redis:6379/0

# 로컬 직접 실행 (호스트 포트 6380)
REDIS_URL=redis://localhost:6380/0
```
