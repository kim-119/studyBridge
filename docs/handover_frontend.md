# 💻 StudyBridge 그룹스터디 & SSE 실시간 통신 명세서 - 프론트엔드 개발자용

본 문서는 StudyBridge 백엔드(Spring Boot)와 연동하여 그룹스터디 관리, 실시간 화상회의(OpenVidu WebRTC SFU), 실시간 소켓 채팅 및 퀴즈 게임, 그리고 AI 멀티 에이전트 실시간 SSE(Server-Sent Events) 스트리밍 화면을 개발하는 프론트엔드 개발자용 명세서입니다.

---

## 📌 1. 전체 REST API 명세
모든 요청 헤더에는 반드시 로그인 시 획득한 JWT 토큰을 포함해야 합니다:
`Authorization: Bearer <JWT_TOKEN>`

> [!IMPORTANT]
> **모집글 개설 및 수정 API 변경 사항**:
> 1. 기존의 JSON Body 전송(`application/json`)에서 **Multipart Form-Data(`multipart/form-data`)**로 변경되었습니다.
> 2. 기획 변경으로 인해 모든 스키마 및 DTO에서 **목표 (`goal`)** 필드가 완전히 삭제되었습니다.
> 3. 개설 및 수정 시 해시태그(`hashtags` - String) 및 대표 이미지 파일(`image` - MultipartFile)을 폼 필드로 전송할 수 있습니다.

| HTTP 메서드 | 엔드포인트 | 설명 | 요청/응답 특징 |
| :--- | :--- | :--- | :--- |
| **POST** | `/api/groups` | 그룹스터디 신규 모집글 개설 | `multipart/form-data` 사용. 폼 필드로 DTO 값 전달 및 대표 이미지 파일(`image`, optional) 첨부. |
| **PUT** | `/api/groups/{id}` | 그룹스터디 정보 수정 | `multipart/form-data` 사용. 폼 필드로 DTO 수정값 전달 및 이미지 파일(`image`, optional) 첨부. 이미지 초기화 시 `clearImage=true` 전송. |
| **GET** | `/api/groups` | 전체 그룹스터디 리스트 조회 | 생성일 역순 반환. 각 그룹 응답 DTO에 `hashtags`, `coverImageUrl` 포함. |
| **GET** | `/api/groups/{id}` | 특정 그룹스터디 상세 정보 조회 | 가입 승인여부 등 조회. |
| **POST** | `/api/groups/{id}/apply` | 그룹스터디 가입 지원서 제출 | `isPublic: false` 방은 대기(`PENDING`), `true` 방은 즉시 가입 완료. |
| **GET** | `/api/groups/{id}/members` | 스터디 정식 가입 멤버 명단 조회 | 각 멤버 정보 외에 **`recentAttendanceTime`**(최근 출석 시간), **`recentStudyTimeSeconds`**(최근 공부 시간), **`cumulativeStudyTimeSeconds`**(누적 공부 시간) 통계 포함. |
| **DELETE** | `/api/groups/{id}/members/{memberUserId}` | [그룹장 전용] 특정 멤버 강제 퇴장(강퇴) | 해당 유저의 멤버 레코드 제거 및 현재 참여 인원 수 자동 차감. |
| **GET** | `/api/groups/{id}/applications` | [그룹장 전용] 승인 대기 중 지원서 조회 | 지원 동기 및 각오 확인. |
| **POST** | `/api/groups/applications/{appId}/approve` | [그룹장 전용] 지원서 최종 가입 승인 | 정원 찼을 시 에러 반환. |
| **POST** | `/api/groups/applications/{appId}/reject` | [그룹장 전용] 지원서 가입 거절 | |
| **POST** | `/api/groups/{groupId}/materials/upload-quiz` | PDF 자료 업로드 & AI 퀴즈 자동 생성 | Multipart 데이터 (`file`, `title`) 전송. S3에 저장 시 원본 파일명 표시 헤더 처리 적용. |
| **GET** | `/api/groups/{groupId}/materials` | 그룹 자료 목록 조회 (1회용 URL 포함) | 그룹 정식 멤버만 조회 권한 가능. |
| **GET** | `/api/groups/materials/{materialId}/download` | 다운로드 전용 Presigned S3 URL 요청 | 1시간 유효 임시 URL 반환. |
| **POST** | `/api/timers/sync/{groupStudyId}` | 대시보드 타이머 스터디룸 진입 동기화 | 작동 중이던 대시보드 타이머를 그룹스터디에 귀속시키고 즉시 당일 출석 체크. |
| **POST** | `/api/groups/{id}/video/token` | WebRTC SFU 화상회의 룸 입장 토큰 생성 | 10인 동시 화상통화 지원을 위한 토큰 반환. |
| **POST** | `/api/groups/{groupId}/reports` | 그룹스터디 룸 내부 악성 유저 신고 접수 | `reportedUserId` 및 사유 전송. |

---

### 1.1 개설 / 수정시 Form-Data 규격
* **개설(POST `/api/groups`) 폼 필드**:
  * `title` (String, 필수)
  * `description` (String, 필수)
  * `startDate` (String, 필수 - 포맷: `YYYY-MM-DD`)
  * `endDate` (String, 필수 - 포맷: `YYYY-MM-DD`)
  * `capacity` (Integer, 필수 - 최소 2, 최대 10)
  * `isPublic` (Boolean, 필수 - true / false)
  * `hashtags` (String, 선택 - 예: `#Java #Spring #CS`)
  * `image` (File, 선택 - 대표 썸네일 이미지 파일)
* **수정(PUT `/api/groups/{id}`) 폼 필드**:
  * 개설 폼 필드와 동일하게 변경이 필요한 필드만 전송 (선택적).
  * `image` (File, 선택 - 변경할 새 이미지 파일)
  * `clearImage` (Boolean, 선택 - `true`로 보낼 시 기존 대표 이미지 삭제 후 초기화)

### 1.2 멤버 목록 조회 응답 예시 (GET `/api/groups/{id}/members`)
```json
[
  {
    "userId": 2,
    "displayName": "잠재용",
    "photoUrl": "https://...",
    "major": "컴퓨터공학과",
    "role": "MEMBER",
    "points": 120,
    "joinedAt": "2026-06-03T11:22:00",
    "recentAttendanceTime": "2026-06-03T09:30:00",
    "recentStudyTimeSeconds": 4800,
    "cumulativeStudyTimeSeconds": 116100
  }
]
```

---

## ⚡ 2. AI 멀티 에이전트 실시간 SSE 스트리밍 연동

에이전트들이 실시간으로 토론하며 한 글자씩 글자를 출력하는 연동 명세입니다. 백엔드는 비동기 스트림 방출 에뮬레이션을 통해 React 프론트엔드가 자연스럽게 타이핑 애니메이션을 받도록 제공합니다.

* **엔드포인트**: `POST /api/groups/${groupId}/chats/stream`
* **헤더**: `Authorization: Bearer <JWT_TOKEN>`, `Content-Type: application/json`
* **미디어 타입**: `text/event-stream`

#### Request Body
```json
{
  "message": "자바 멀티스레딩에 대해서 에이전트들이 설명해줘",
  "mode": "multi_agent_discussion",
  "rounds": 3,
  "showFinalSynthesis": true,
  "targetAgentId": null,
  "agents": [
    {
      "id": 1,
      "agentId": 1,
      "name": "SummaryAgent",
      "role": "요약봇",
      "personality": "전문적",
      "personalityStrength": "extreme",
      "style": "전문적",
      "tone": "전문적",
      "knowledgeLevel": "학사 수준",
      "customInstruction": "쉽게 설명해 줘"
    }
  ]
}
```

#### Response Stream Format (JSON Chunks)
백엔드가 연결 상태를 유지하며 실시간으로 `data: ` 프리픽스를 가진 JSON 데이터를 한 라인씩 방출합니다:
```text
data: {"agentName": "SummaryAgent", "content": "자바", "done": false}
data: {"agentName": "SummaryAgent", "content": "는 ", "done": false}
data: {"agentName": "SummaryAgent", "content": "스레", "done": false}
data: {"agentName": "SummaryAgent", "content": "드를 ", "done": false}
...
data: {"done": true}
```

#### 💡 React 프론트엔드 연동 팁 및 구현 예제
보통 일반적인 `axios`나 `fetch`는 전체 응답이 끝날 때까지 대기하므로 스트리밍 통신에는 적합하지 않습니다. `@microsoft/fetch-event-source` 라이브러리 등을 사용하는 것이 편리합니다.

```typescript
import { fetchEventSource } from '@microsoft/fetch-event-source';

interface ChatChunk {
  agentName?: string;
  content?: string;
  done: boolean;
}

const startAiStream = async (groupId: number, userMessage: string) => {
  // 1. 에이전트별 메시지 버퍼 초기화
  const messageBuffers: Record<string, string> = {};

  await fetchEventSource(`http://localhost:8080/api/groups/${groupId}/chats/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`
    },
    body: JSON.stringify({
      message: userMessage,
      mode: 'multi_agent_discussion',
      rounds: 3,
      showFinalSynthesis: true,
      agents: [] // 비워두면 백엔드가 디폴트 에이전트(요약봇, 퀴즈봇, 검색봇)로 작동
    }),
    onmessage(ev) {
      try {
        const data: ChatChunk = JSON.parse(ev.data);
        
        if (data.done) {
          console.log("스트리밍 종료");
          return;
        }

        if (data.agentName && data.content) {
          // 기존 에이전트 메시지에 청크 텍스트 누적 결합
          messageBuffers[data.agentName] = (messageBuffers[data.agentName] || "") + data.content;
          
          // React State 업데이트 등으로 UI 렌더링 반영
          updateUiState(data.agentName, messageBuffers[data.agentName]);
        }
      } catch (err) {
        console.error("JSON 파싱 에러", err);
      }
    },
    onerror(err) {
      console.error("스트리밍 통신 오류", err);
    }
  });
};
```

---

## 💬 3. WebSocket STOMP 실시간 연동 규격
실시간 채팅 및 퀴즈 게임방 동기화를 구현하기 위해 WebSocket STOMP 프로토콜을 사용합니다.
* **WebSocket 엔드포인트**: `ws://localhost:8080/ws-group`
* **연결 방식**: SockJS 지원 클라이언트 사용 권장.

### 1) 실시간 룸 채팅 (Chatting Room Isolation)
* **구독 경로 (Subscribe)**: `/topic/group/{groupId}/chat`
* **발행 경로 (Publish)**: `/pub/group/{groupId}/chat`
* **메시지 Payload 규격**:
  ```json
  {
    "senderName": "홍길동",
    "content": "오늘도 3시간 열공해봅시다!"
  }
  ```

### 2) 실시간 포인트제 퀴즈 게임 (Point Quiz System)
* **시작 발행 (방장 전용)**:
  * 방장이 특정 퀴즈 세트를 시작하면 다음 경로로 시작 신호를 보냅니다.
  * **발행 경로**: `/pub/group/{groupId}/quiz/start`
  * **Payload**: `{"quizId": 1}`
* **문제 브로드캐스트 수신 (모든 멤버)**:
  * 서버에서 구독자 전체에게 한 문항씩 문제를 전파합니다.
  * **구독 경로**: `/topic/group/{groupId}/quiz/question`
  * **서버에서 보내주는 Payload**:
    ```json
    {
      "quizId": 1,
      "quizTitle": "[자료구조] 학습 퀴즈",
      "questionId": 23,
      "questionText": "다음 중 시간 복잡도가 O(1)인 자료구조 탐색 연산은?",
      "options": ["이진 탐색 트리", "배열의 인덱스 접근", "연결 리스트 맨 뒤 삽입", "해시 테이블 최악의 경우"],
      "currentIndex": 0,
      "totalQuestions": 3,
      "timeLimitSeconds": 30
    }
    ```
* **정답 제출 (사용자 개별)**:
  * 제한시간 내에 사용자가 보기를 클릭하면 정답 제출 패킷을 전송합니다.
  * **발행 경로**: `/pub/group/{groupId}/quiz/submit`
  * **Payload**:
    ```json
    {
      "userId": 42,
      "questionId": 23,
      "submittedAnswer": 1,
      "timeTakenSeconds": 8
    }
    ```
* **실시간 랭킹보드 수신 (모든 멤버)**:
  * 정답 제출 시 서버가 채점을 처리(남은 시간 비례 보너스 포인트 지급 포함) 후 그룹 전체 실시간 석차표를 갱신해 줍니다.
  * **구독 경로**: `/topic/group/{groupId}/quiz/scoreboard`
  * **서버에서 수신받는 Payload (정렬된 리스트)**:
    ```json
    [
      { "userId": 42, "displayName": "김철수", "points": 25 },
      { "userId": 15, "displayName": "이영희", "points": 10 },
      { "userId": 88, "displayName": "홍길동", "points": 0 }
    ]
    ```

---

## 📹 4. WebRTC SFU 화상회의(OpenVidu CE) 연동 가이드
최대 10명 이상의 안정적인 동시 화상 통신(비디오/오디오 스트림) 환경을 보장하기 위해 P2P Mesh 방식 대신 오픈소스 SFU 엔진인 **OpenVidu CE**를 백엔드와 연동하여 사용합니다.

### 4.1 화상통화 연결 흐름
1. 프론트엔드가 백엔드 API인 `POST /api/groups/{groupId}/video/token`을 호출하여 입장 권한을 확인하고 토큰을 발급받습니다.
2. 백엔드는 OpenVidu 서버와 통신하여 해당 스터디룸용 Session ID를 생성/조회하고 연결 Token을 반환합니다.
3. 프론트엔드는 반환받은 Token을 **OpenVidu Browser SDK**에 넘겨서 미디어 서버 세션에 접속(Connect)합니다.
4. 접속 완료 시 자신의 비디오/오디오 스트림을 발행(Publisher)하고, 다른 사용자의 스트림을 구독(Subscriber)하여 화면에 렌더링합니다.
5. P2P 방식에 비해 클라이언트 네트워크 및 CPU 점유율이 획기적으로 낮으므로 최대 10인 통신도 끊김 없이 부드럽게 지원됩니다.
