# StudyBridge AI & RAG Database Schemas (최종 합의본)

이 문서는 StudyBridge 플랫폼의 **AI 멀티 에이전트 시스템** 및 **RAG(Retrieval-Augmented Generation) 데이터베이스**에 최종 정의된 테이블 스키마와 인덱스 사양입니다.

> [!IMPORTANT]
> **아키텍처 요약:**
> * 기존 PostgreSQL/RDS 내부에 `ai` 및 `rag` 스키마(Schema)를 추가하여 관리합니다.
> * 기존 `public` 스키마의 서비스 테이블은 전혀 수정하지 않고 독립적으로 운영됩니다.
> * PostgreSQL에 **`pgvector` 확장**을 활성화하여 `rag.document_chunk` 테이블에 직접 **1536차원 임베딩 벡터 값**을 저장하고, 고속 HNSW 코사인 유사도 검색을 수행합니다. (외부 벡터 DB 추가 구축이 불필요합니다.)

---

## 1. `rag` 스키마 (자료보관함 PDF 벡터 임베딩 및 RAG 로그)

### ① `document_chunk` (문서 청크 및 임베딩 저장 테이블)
자료보관함 PDF 문서를 분석하기 위해 분할한 텍스트 청크 원문과 **1536차원 벡터 임베딩 값**을 저장합니다.

* **테이블명:** `rag.document_chunk`
* **DDL:**
  ```sql
  -- 1. pgvector 확장 기능 활성화 (최초 1회 실행 필요)
  CREATE EXTENSION IF NOT EXISTS vector;

  -- 2. 테이블 생성
  CREATE TABLE IF NOT EXISTS rag.document_chunk (
      id             BIGSERIAL    PRIMARY KEY,
      material_id    BIGINT       NOT NULL,        -- Spring Boot materials.id 참조용 (FK 없음)
      document_title TEXT,                         -- PDF 파일 제목
      chunk_index    INTEGER      NOT NULL,        -- 청크 순서 (0-based)
      page_start     INTEGER,                      -- 시작 페이지 번호
      page_end       INTEGER,                      -- 끝 페이지 번호
      content        TEXT         NOT NULL,        -- 잘라낸 본문 텍스트
      content_hash   VARCHAR(128),                 -- 중복 방지용 해시
      embedding_model VARCHAR(100),                -- 사용된 임베딩 모델 (예: text-embedding-3-small)
      metadata       JSONB        DEFAULT '{}'::jsonb,
      embedding      vector(1536) NOT NULL,        -- OpenAI 1536차원 임베딩 벡터값 저장!
      created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
      updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
      UNIQUE (material_id, chunk_index)
  );

  -- 3. 인덱스 생성
  CREATE INDEX IF NOT EXISTS idx_document_chunk_material_id ON rag.document_chunk(material_id);
  CREATE INDEX IF NOT EXISTS idx_document_chunk_content_hash ON rag.document_chunk(content_hash);

  -- 4. HNSW 코사인 유사도 고속 검색 인덱스 생성
  CREATE INDEX IF NOT EXISTS idx_rag_document_chunk_embedding_hnsw
      ON rag.document_chunk
      USING hnsw (embedding vector_cosine_ops)
      WITH (m = 16, ef_construction = 64);
  ```

---

### ② `rag_query_log` (RAG 검색 이력 로그)
사용자 질문 시 어떤 PDF 청크가 참조되었고 어떤 유사도 점수를 얻었는지 기록합니다.

* **테이블명:** `rag.rag_query_log`
* **DDL:**
  ```sql
  CREATE TABLE IF NOT EXISTS rag.rag_query_log (
      id              BIGSERIAL    PRIMARY KEY,
      session_id      BIGINT,                          -- ai.conversation_session.id 참조용
      user_id         BIGINT,
      material_id     BIGINT,
      query           TEXT         NOT NULL,           -- 사용자 질문 내용
      query_embedding vector(1536),                    -- 질문의 1536차원 임베딩 벡터값
      top_k           INTEGER      NOT NULL DEFAULT 5,
      retrieved_chunk_ids JSONB,                       -- 매칭되어 조회된 document_chunk.id 목록 (JSON)
      similarity_scores JSONB,                         -- 매칭된 청크별 유사도 점수 목록 (JSON)
      used_for_answer BOOLEAN      NOT NULL DEFAULT FALSE,
      created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
  );

  CREATE INDEX IF NOT EXISTS idx_rag_query_log_session_id ON rag.rag_query_log(session_id);
  CREATE INDEX IF NOT EXISTS idx_rag_query_log_user_id ON rag.rag_query_log(user_id);
  CREATE INDEX IF NOT EXISTS idx_rag_query_log_material_id ON rag.rag_query_log(material_id);
  CREATE INDEX IF NOT EXISTS idx_rag_query_log_created_at ON rag.rag_query_log(created_at);
  ```

---

## 2. `ai` 스키마 (대화 기록, 답변 검증 및 자동 학습 후보)

### ① `conversation_session` (대화 세션)
에이전트와의 챗봇 세션 정보를 저장합니다.

* **테이블명:** `ai.conversation_session`
* **DDL:**
  ```sql
  CREATE TABLE IF NOT EXISTS ai.conversation_session (
      id BIGSERIAL PRIMARY KEY,
      user_id BIGINT,
      room_id BIGINT,
      material_id BIGINT,
      session_type VARCHAR(50) NOT NULL,
      title VARCHAR(255),
      status VARCHAR(30) NOT NULL DEFAULT 'active',
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );

  CREATE INDEX IF NOT EXISTS idx_conversation_session_user_id ON ai.conversation_session(user_id);
  CREATE INDEX IF NOT EXISTS idx_conversation_session_room_id ON ai.conversation_session(room_id);
  CREATE INDEX IF NOT EXISTS idx_conversation_session_material_id ON ai.conversation_session(material_id);
  ```

---

### ② `conversation_message` (대화 메시지)
사용자 질문 및 AI의 답변 텍스트 로그를 저장합니다.

* **테이블명:** `ai.conversation_message`
* **DDL:**
  ```sql
  CREATE TABLE IF NOT EXISTS ai.conversation_message (
      id BIGSERIAL PRIMARY KEY,
      session_id BIGINT NOT NULL,
      user_id BIGINT,
      agent_id BIGINT,
      role VARCHAR(30) NOT NULL,
      content TEXT NOT NULL,
      model_name VARCHAR(100),
      source_type VARCHAR(50),
      token_count INTEGER,
      response_time_ms INTEGER,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );

  CREATE INDEX IF NOT EXISTS idx_conversation_message_session_id ON ai.conversation_message(session_id);
  CREATE INDEX IF NOT EXISTS idx_conversation_message_user_id ON ai.conversation_message(user_id);
  CREATE INDEX IF NOT EXISTS idx_conversation_message_agent_id ON ai.conversation_message(agent_id);
  CREATE INDEX IF NOT EXISTS idx_conversation_message_created_at ON ai.conversation_message(created_at);
  ```

---

### ③ `agent_turn` (에이전트 발화 턴)
멀티 에이전트 토론(티키타카) 모드 시 발화 주체와 라운드 번호, 발화 순서를 정밀 기록합니다.

* **테이블명:** `ai.agent_turn`
* **DDL:**
  ```sql
  CREATE TABLE IF NOT EXISTS ai.agent_turn (
      id BIGSERIAL PRIMARY KEY,
      session_id BIGINT NOT NULL,
      round_no INTEGER NOT NULL,
      turn_order INTEGER NOT NULL,
      agent_id BIGINT,
      input_message_id BIGINT,
      output_message_id BIGINT,
      turn_type VARCHAR(50) NOT NULL,
      status VARCHAR(30) NOT NULL DEFAULT 'pending',
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      completed_at TIMESTAMPTZ
  );

  CREATE INDEX IF NOT EXISTS idx_agent_turn_session_id ON ai.agent_turn(session_id);
  CREATE INDEX IF NOT EXISTS idx_agent_turn_round ON ai.agent_turn(session_id, round_no);
  CREATE INDEX IF NOT EXISTS idx_agent_turn_agent_id ON ai.agent_turn(agent_id);
  ```

---

### ④ `validation_job` (AI 답변 품질 검증 작업)
AI 답변의 신뢰성과 정합성을 평가한 GPT 및 Tavily/Wikipedia 검증 결과를 저장합니다.

* **테이블명:** `ai.validation_job`
* **DDL:**
  ```sql
  CREATE TABLE IF NOT EXISTS ai.validation_job (
      id UUID PRIMARY KEY,
      session_id BIGINT,
      message_id BIGINT,
      user_id BIGINT,
      status VARCHAR(30) NOT NULL DEFAULT 'pending',
      validation_type VARCHAR(50) NOT NULL DEFAULT 'full',
      used_tavily BOOLEAN NOT NULL DEFAULT FALSE,
      used_gpt BOOLEAN NOT NULL DEFAULT FALSE,
      used_wikipedia BOOLEAN NOT NULL DEFAULT FALSE,
      tavily_result JSONB,
      gpt_verdict JSONB,
      corrected_answer TEXT,
      error_message TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      completed_at TIMESTAMPTZ
  );

  CREATE INDEX IF NOT EXISTS idx_validation_job_session_id ON ai.validation_job(session_id);
  CREATE INDEX IF NOT EXISTS idx_validation_job_message_id ON ai.validation_job(message_id);
  CREATE INDEX IF NOT EXISTS idx_validation_job_status ON ai.validation_job(status);
  CREATE INDEX IF NOT EXISTS idx_validation_job_created_at ON ai.validation_job(created_at);
  ```

---

### ⑤ `training_candidate` (자동 학습 후보 데이터)
사용자 Q/A에서 선별되어 파인튜닝 학습 데이터 후보로 분류된 이력을 상세 관리합니다.

* **테이블명:** `ai.training_candidate`
* **DDL:**
  ```sql
  CREATE TABLE IF NOT EXISTS ai.training_candidate (
      id BIGSERIAL PRIMARY KEY,
      session_id BIGINT,
      question_message_id BIGINT,
      answer_message_id BIGINT,
      user_id BIGINT,
      room_id BIGINT,
      material_id BIGINT,
      agent_id BIGINT,
      question TEXT NOT NULL,
      answer TEXT NOT NULL,
      system_prompt TEXT,
      agent_personality VARCHAR(100),
      agent_role VARCHAR(100),
      knowledge_level VARCHAR(50),
      custom_instruction TEXT,
      source_type VARCHAR(50) NOT NULL,
      used_rag BOOLEAN NOT NULL DEFAULT FALSE,
      used_tavily BOOLEAN NOT NULL DEFAULT FALSE,
      used_wikipedia BOOLEAN NOT NULL DEFAULT FALSE,
      used_gpt BOOLEAN NOT NULL DEFAULT FALSE,
      rag_context_hash VARCHAR(128),
      quality_status VARCHAR(50) NOT NULL DEFAULT 'auto_collected',
      quality_score INTEGER NOT NULL DEFAULT 0,
      validation_notes TEXT,
      gpt_verdict_json JSONB,
      tavily_result_json JSONB,
      duplicate_hash VARCHAR(128),
      duplicate_score NUMERIC(5,4),
      contains_sensitive_info BOOLEAN NOT NULL DEFAULT FALSE,
      user_feedback VARCHAR(50),
      exported_dataset_version VARCHAR(50),
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );

  CREATE INDEX IF NOT EXISTS idx_training_candidate_status ON ai.training_candidate(quality_status);
  CREATE INDEX IF NOT EXISTS idx_training_candidate_score ON ai.training_candidate(quality_score);
  CREATE INDEX IF NOT EXISTS idx_training_candidate_user_id ON ai.training_candidate(user_id);
  CREATE INDEX IF NOT EXISTS idx_training_candidate_agent_id ON ai.training_candidate(agent_id);
  CREATE INDEX IF NOT EXISTS idx_training_candidate_material_id ON ai.training_candidate(material_id);
  CREATE INDEX IF NOT EXISTS idx_training_candidate_duplicate_hash ON ai.training_candidate(duplicate_hash);
  CREATE INDEX IF NOT EXISTS idx_training_candidate_created_at ON ai.training_candidate(created_at);
  ```

---

### ⑥ `training_export_job` (학습 데이터 내보내기 이력)
승인된 데이터셋을 JSONL 파일 형식으로 추출한 이력을 저장합니다.

* **테이블명:** `ai.training_export_job`
* **DDL:**
  ```sql
  CREATE TABLE IF NOT EXISTS ai.training_export_job (
      id BIGSERIAL PRIMARY KEY,
      dataset_version VARCHAR(50) NOT NULL,
      export_status VARCHAR(30) NOT NULL DEFAULT 'pending',
      approved_count INTEGER NOT NULL DEFAULT 0,
      rejected_count INTEGER NOT NULL DEFAULT 0,
      duplicate_count INTEGER NOT NULL DEFAULT 0,
      unsafe_count INTEGER NOT NULL DEFAULT 0,
      holdout_count INTEGER NOT NULL DEFAULT 0,
      output_file_path TEXT,
      error_message TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      completed_at TIMESTAMPTZ
  );

  CREATE INDEX IF NOT EXISTS idx_training_export_job_version ON ai.training_export_job(dataset_version);
  CREATE INDEX IF NOT EXISTS idx_training_export_job_status ON ai.training_export_job(export_status);
  ```
