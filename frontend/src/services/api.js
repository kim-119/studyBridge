import axios from 'axios';

// AI 요청 timeout. 중복 export 금지.
export const AI_TIMEOUT_MS = Number(
  import.meta.env.VITE_AI_TIMEOUT_MS ||
  import.meta.env.VITE_FRONTEND_AI_TIMEOUT_MS ||
  import.meta.env.FRONTEND_AI_TIMEOUT_MS ||
  180000
);

// 자료 업로드(POST /api/materials/upload) 전용 timeout.
//  - 업로드 본 요청은 S3 저장 + DB insert 만 동기로 수행하고 텍스트 추출은 @Async 로 분리되어 있다.
//  - 따라서 AI(180s) 타임아웃을 그대로 쓰면 S3/네트워크가 막혔을 때 "저장 중..." 이 과도하게 길어진다.
//  - 60초로 묶어 무한 pending 을 방지하고, 초과 시 catch → 에러 알림 + 저장 중 해제가 보장되게 한다.
export const MATERIAL_UPLOAD_TIMEOUT_MS = Number(
  import.meta.env.VITE_MATERIAL_UPLOAD_TIMEOUT_MS || 60000
);

// 퀴즈/로드맵 생성 전용 timeout(90초). 초과 시 axios가 ECONNABORTED 로 끊고,
//  화면은 catch → deterministic fallback 으로 전환한다(무한 "생성 중" 방지, 90초 UX 보장).
export const AI_FALLBACK_TIMEOUT_MS = Number(
  import.meta.env.VITE_AI_FALLBACK_TIMEOUT_MS || 90000
);

const hostname =
  typeof window !== 'undefined'
    ? window.location.hostname === 'localhost'
      ? '127.0.0.1'
      : window.location.hostname
    : '127.0.0.1';

// 로컬 개발(localhost/127.0.0.1에서 직접 실행) 여부
const isLocalDev =
  typeof window !== 'undefined' &&
  ['localhost', '127.0.0.1'].includes(window.location.hostname);

// 운영(배포)에서는 같은 오리진의 상대경로로 요청한다.
//  - Nginx가 /api/ → Spring(127.0.0.1:8080)으로 프록시하므로 mixed-content/CORS가 발생하지 않는다.
//  - 호출 경로가 이미 '/api/...' 형태이므로 baseURL은 오리진만 담당한다('/api/api' 중복 방지).
//  - 다른 백엔드를 강제하려면 VITE_API_BASE_URL을 지정한다.
const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  import.meta.env.VITE_BACKEND_URL ||
  '';

const FASTAPI_BASE_URL =
  import.meta.env.VITE_FASTAPI_BASE_URL ||
  '';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: AI_TIMEOUT_MS,
  headers: {
    'Content-Type': 'application/json',
  },
});

const fastApi = axios.create({
  baseURL: FASTAPI_BASE_URL,
  timeout: AI_TIMEOUT_MS,
  headers: {
    'Content-Type': 'application/json',
  },
});

const normalizeAgentFromRoom = (room) => {
  const primaryAgent = Array.isArray(room?.agents) && room.agents.length > 0 ? room.agents[0] : {};

  return {
    ...primaryAgent,
    id: room?.roomId ?? room?.id ?? primaryAgent?.id ?? primaryAgent?.agentId,
    agentId: primaryAgent?.agentId ?? primaryAgent?.id,
    roomId: room?.roomId ?? room?.id,
    roomName: room?.roomName,
    learningMode: room?.learningMode || 'basic',
    name: primaryAgent?.name || room?.roomName || 'AI 에이전트',
    role: primaryAgent?.role || '학습 도우미',
    persona: primaryAgent?.persona || '',
    tone: primaryAgent?.tone || '전문적',
    goal: primaryAgent?.goal || '',
    agents: room?.agents || [],
    createdAt: room?.createdAt,
  };
};

const normalizeAgentRoomPayload = (agentData) => {
  if (agentData?.roomName && Array.isArray(agentData?.agents)) {
    return agentData;
  }

  const agentName = agentData?.name || 'AI 에이전트';

  return {
    roomName: agentData?.roomName || agentName,
    agents: [
      {
        name: agentName,
        role: agentData?.role || '학습 도우미',
        persona:
          agentData?.persona ||
          agentData?.customInstruction ||
          agentData?.goal ||
          '사용자의 학습을 돕는다',
        tone: agentData?.tone || agentData?.personality || '전문적',
        goal: agentData?.goal || '사용자의 학습을 돕는다',
        personality: agentData?.personality,
        personalityStrength:
          agentData?.personalityStrength ||
          agentData?.personality_strength ||
          'extreme',
        personality_strength:
          agentData?.personality_strength ||
          agentData?.personalityStrength ||
          'extreme',
        style: agentData?.style || agentData?.personality,
        knowledgeLevel: agentData?.knowledgeLevel,
        knowledge_level: agentData?.knowledge_level || agentData?.knowledgeLevel,
        customInstruction: agentData?.customInstruction,
        custom_instruction: agentData?.custom_instruction || agentData?.customInstruction,
      },
    ],
  };
};

const normalizeChatResponse = (data) => {
  if (Array.isArray(data?.messages)) {
    return {
      ...data,
      mode: data.mode || 'multi_agent_discussion',
      messages: data.messages,
      answer: '',
    };
  }

  if (data?.answer) {
    return data;
  }

  if (Array.isArray(data?.replies)) {
    const answer = data.replies
      .map((reply) => {
        const name = reply.agentName || reply.agent_name || 'AI';
        const text = reply.answer || '';
        return data.replies.length > 1 ? `${name}: ${text}` : text;
      })
      .filter(Boolean)
      .join('\n\n');

    return {
      ...data,
      answer,
    };
  }

  return {
    ...data,
    answer: '',
  };
};

api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token');

    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }

    return config;
  },
  (error) => Promise.reject(error)
);

api.interceptors.response.use(
  (res) => res,
  async (err) => {
    // 개발자 콘솔에는 상세히 출력한다(네트워크/CORS/엔드포인트 문제 진단용).
    const cfg = err.config || {};
    console.error('API 에러 상세:', {
      message: err.message,
      code: err.code,
      method: cfg.method,
      baseURL: cfg.baseURL,
      url: cfg.url,
      // 요청은 나갔으나 응답이 없으면(=network/CORS/mixed-content) err.response가 없다.
      noResponse: !err.response,
      status: err.response?.status,
      data: err.response?.data,
    });

    const originalRequest = err.config;

    if (
      err.response &&
      (err.response.status === 401 || err.response.status === 403) &&
      !originalRequest._retry
    ) {
      if (
        originalRequest.url.includes('/api/users/refresh') ||
        originalRequest.url.includes('/api/users/login')
      ) {
        return Promise.reject(err);
      }

      originalRequest._retry = true;

      try {
        const refreshToken = localStorage.getItem('refreshToken');

        if (!refreshToken) {
          throw new Error('No refresh token');
        }

        const res = await axios.post(
          `${API_BASE_URL}/api/users/refresh?refreshToken=${refreshToken}`,
          null,
          {
            timeout: AI_TIMEOUT_MS,
          }
        );

        if (res.data && res.data.accessToken) {
          localStorage.setItem('token', res.data.accessToken);
          localStorage.setItem('refreshToken', res.data.refreshToken);

          originalRequest.headers.Authorization = `Bearer ${res.data.accessToken}`;
          return api(originalRequest);
        }
      } catch (refreshErr) {
        console.warn('토큰 갱신 실패. 로그아웃 처리됩니다.');
        localStorage.removeItem('token');
        localStorage.removeItem('refreshToken');
        window.dispatchEvent(new Event('auth-change'));
        return Promise.reject(refreshErr);
      }
    }

    return Promise.reject(err);
  }
);

fastApi.interceptors.response.use(
  (res) => res,
  (err) => Promise.reject(err)
);

export const agentService = {
  getAgents: async () => {
    const res = await api.get('/api/agent-rooms');
    return (res.data || []).map(normalizeAgentFromRoom);
  },

  createAgent: async (userId, agentData) => {
    const payload = normalizeAgentRoomPayload(agentData);
    const res = await api.post('/api/agent-rooms', payload);
    return normalizeAgentFromRoom(res.data);
  },

  deleteAgent: async (userId, agentId) => {
    const res = await api.delete(`/api/agent-rooms/${agentId}`);
    return res.data;
  },

  sendMessage: async (userId, agentId, payloadOrMessage) => {
    const basePayload =
      typeof payloadOrMessage === 'string'
        ? { message: payloadOrMessage, agentId, roomId: agentId }
        : { agentId, roomId: agentId, ...payloadOrMessage };

    const payload = {
      personality: basePayload.personality || '',
      style: basePayload.style || '',
      tone: basePayload.tone || '',
      knowledgeLevel: basePayload.knowledgeLevel || '',
      knowledge_level: basePayload.knowledge_level || basePayload.knowledgeLevel || '',
      customInstruction: basePayload.customInstruction || '',
      custom_instruction:
        basePayload.custom_instruction || basePayload.customInstruction || '',
      persona: basePayload.persona || '',
      agent_name: basePayload.agent_name || basePayload.agentName || '',
      ...basePayload,
    };

    console.debug('[api.agentService.sendMessage] request body', payload);

    const res = await api.post(`/api/agent-rooms/${agentId}/chat`, payload);
    return normalizeChatResponse(res.data);
  },

  streamMessage: async (userId, agentId, payloadOrMessage, handlers = {}, opts = {}) => {
    const basePayload =
      typeof payloadOrMessage === 'string'
        ? { message: payloadOrMessage, agentId, roomId: agentId }
        : { agentId, roomId: agentId, ...payloadOrMessage };

    const token = localStorage.getItem('token');

    const resp = await fetch(`${API_BASE_URL}/api/agent-rooms/${agentId}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(basePayload),
      // 무한 loading 방지용 watchdog abort 신호(선택)
      ...(opts.signal ? { signal: opts.signal } : {}),
    });

    if (!resp.ok || !resp.body) {
      throw new Error(`stream http ${resp.status}`);
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    const dispatch = (frame) => {
      let event = 'message';
      const dataLines = [];
      let commentSeen = false;

      for (const line of frame.split('\n')) {
        // SSE 주석 라인(':' 로 시작, 예: Spring keepalive ':hb')은 이벤트가 아니다.
        // 다만 '연결 생존(liveness)' 신호이므로 watchdog 갱신을 위해 따로 알린다.
        if (line.startsWith(':')) {
          commentSeen = true;
        } else if (line.startsWith('event:')) {
          event = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).replace(/^ /, ''));
        }
      }

      // data 없는 프레임(주석/빈 keepalive)은 파싱하지 않지만, 주석이면 liveness만 통지한다.
      if (dataLines.length === 0) {
        if (commentSeen) handlers.onComment?.(frame);
        return;
      }

      let data = null;

      // 프레임 단위로만 JSON.parse 한다(청크 경계로 깨지지 않음). 1프레임 파싱 실패가
      // 스트림 전체를 죽이지 않도록 null 로 흘려보내고 다음 프레임을 계속 처리한다.
      try {
        data = JSON.parse(dataLines.join('\n'));
      } catch (parseErr) {
        if (import.meta.env.DEV) console.warn('[SSE] frame parse 실패(무시하고 계속):', dataLines.join('\n').slice(0, 200));
        handlers.onParseError?.(event, dataLines.join('\n'), parseErr);
        return;
      }

      // 진단/성능 측정용 단일 훅 — 첫 이벤트 도착 시각/liveness 갱신을 한 지점에서 잰다.
      handlers.onAnyEvent?.(event, data);

      if (event === 'turn_start') handlers.onTurnStart?.(data);
      else if (event === 'heartbeat') handlers.onHeartbeat?.(data);
      else if (event === 'progress') handlers.onProgress?.(data);
      // 픽셀 교수 안무/상호작용 이벤트(visual layer). 답변 append 로직과 무관.
      else if (event === 'professor_motion') handlers.onProfessorMotion?.(data);
      else if (event === 'interaction_event') handlers.onInteractionEvent?.(data);
      else if (event === 'synthesis_diff') handlers.onSynthesisDiff?.(data);
      else if (event === 'agent_start') handlers.onAgentStart?.(data);
      else if (event === 'agent_answer') handlers.onAgentAnswer?.(data);
      else if (event === 'agent_error') handlers.onAgentError?.(data);
      else if (event === 'stage_start') handlers.onStageStart?.(data);
      else if (event === 'stage_complete') handlers.onStageComplete?.(data);
      else if (event === 'agent_stage_complete') handlers.onAgentStageComplete?.(data);
      else if (event === 'debate_section') handlers.onDebateSection?.(data);
      else if (event === 'socratic_step') handlers.onSocraticStep?.(data);
      else if (event === 'socratic_answer') handlers.onSocraticAnswer?.(data);
      else if (event === 'simulation_stage') handlers.onSimulationStage?.(data);
      // Intent Router 라우팅 이벤트 (DIRECT_REPLY/BLOCK/CLARIFY/QUIZ 등)
      else if (event === 'route_message') handlers.onRouteMessage?.(data);
      else if (event === 'route_notice') handlers.onRouteNotice?.(data);
      else if (event === 'route_pipeline') handlers.onRoutePipeline?.(data);
      // 확률적 다중답변 플래너: 끝에 오는 재개입 칩(더 깊이/다른 의견/쉬운 예시).
      else if (event === 'follow_up_suggestions') handlers.onFollowUpSuggestions?.(data);
      else if (event === 'all_complete') handlers.onAllComplete?.(data);
      // done: FastAPI finally 가 보내는 종결 이벤트. 과거엔 디스패치되지 않아 무시됐다.
      //  → all_complete 와 함께 '최종 수신(finalReceived)' 판정에 쓰도록 명시 전달한다.
      else if (event === 'done') handlers.onDone?.(data);
      else if (event === 'error') handlers.onError?.(data);
    };

    // SSE 프레임은 '\n\n' 로 구분된다. CRLF(\r\n) 도 허용하도록 정규화 후 분리한다.
    const drainFrames = () => {
      buffer = buffer.replace(/\r\n/g, '\n');
      let idx;
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        if (frame.trim()) dispatch(frame);
      }
    };

    while (true) {
      const { done, value } = await reader.read();

      if (done) {
        // 멀티바이트 tail flush + 종결 '\n\n' 없이 끝난 마지막 프레임도 유실 없이 처리한다.
        buffer += decoder.decode();
        drainFrames();
        const tail = buffer.replace(/\r\n/g, '\n').trim();
        if (tail) dispatch(tail);
        buffer = '';
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      drainFrames();
    }
  },

  getChatHistory: async (userId, agentId) => {
    const res = await api.get(`/api/agent-rooms/${agentId}/history`);
    return res.data;
  },

  getRooms: async () => {
    const res = await api.get('/api/agent-rooms');
    return res.data;
  },

  createRoom: async (userId, roomData) => {
    const res = await api.post('/api/agent-rooms', roomData);
    return res.data;
  },

  deleteRoom: async (userId, roomId) => {
    const res = await api.delete(`/api/agent-rooms/${roomId}`);
    return res.data;
  },

  sendAgentMessage: async (payload) => {
    if (payload?.roomId) {
      console.debug('[api.agentService.sendAgentMessage] request body', payload);

      const unifiedPayload = {
        ...payload,
        agent_name: payload.agent_name || payload.agentName,
        knowledge_level: payload.knowledge_level || payload.knowledgeLevel,
        personality: payload.personality,
      };

      const res = await api.post(
        `/api/agent-rooms/${payload.roomId}/chat`,
        unifiedPayload
      );

      return normalizeChatResponse(res.data);
    }

    const res = await fastApi.post('/agents/1/chat', payload);
    return res.data;
  },

  sendMultiAgentMessage: async (payload) => {
    const unifiedPayload = {
      ...payload,
      agent_name: payload.agent_name || payload.agentName,
      knowledge_level: payload.knowledge_level || payload.knowledgeLevel,
      personality: payload.personality,
    };

    const res = await fastApi.post('/api/ai/chat', unifiedPayload);
    return res.data;
  },

  requestFeedback: async (payload) => {
    const reviewerAgentId =
      payload?.reviewer_agent_id ||
      payload?.reviewerAgentId ||
      payload?.agent_id ||
      payload?.agentId;

    if (reviewerAgentId) {
      const res = await fastApi.post(`/agents/${reviewerAgentId}/feedback`, payload);
      return res.data;
    }

    const unifiedPayload = {
      ...payload,
      agent_name: payload.agent_name || payload.agentName,
      knowledge_level: payload.knowledge_level || payload.knowledgeLevel,
      personality: payload.personality,
    };

    const res = await fastApi.post('/api/ai/chat', unifiedPayload);
    return res.data;
  },

  createStudyRoom: async (payload) => {
    const res = await api.post('/api/agent-rooms', payload);
    return res.data;
  },

  sendFeedbackRequest: async (payload) => {
    return agentService.requestFeedback(payload);
  },
};

export const authService = {
  register: async (userData) => {
    try {
      const res = await api.post('/api/users/register', userData);
      return res.data;
    } catch (err) {
      throw err.response?.data || { message: '회원가입 실패' };
    }
  },

  login: async (credentials) => {
    try {
      const res = await api.post('/api/users/login', credentials);
      return res.data;
    } catch (err) {
      // 백엔드가 응답을 준 경우(401/400 등)는 그 본문을 그대로 전달한다.
      if (err.response?.data) {
        const data = err.response.data;
        throw typeof data === 'object'
          ? { ...data, status: err.response.status }
          : { message: String(data), status: err.response.status };
      }
      // 응답이 없는 경우(=네트워크/CORS/mixed-content) 상세를 보존해 던진다.
      throw {
        message:
          '서버에 연결할 수 없습니다. 네트워크 상태를 확인해주세요.',
        networkError: true,
        detail: err.message,
        url: `${err.config?.baseURL || ''}${err.config?.url || ''}`,
      };
    }
  },

  getProfile: async (userId) => {
    try {
      const res = await api.get('/api/users/profile');
      return res.data;
    } catch (err) {
      throw err.response?.data || { message: '프로필 조회 실패' };
    }
  },

  updateProfile: async (userId, profileData) => {
    try {
      const res = await api.put('/api/users/profile', profileData);
      return res.data;
    } catch (err) {
      throw err.response?.data || { message: '프로필 업데이트 실패' };
    }
  },

  uploadProfileImage: async (file) => {
    try {
      const formData = new FormData();
      formData.append('file', file);

      const token = localStorage.getItem('token');

      const res = await axios.post(`${API_BASE_URL}/api/users/profile/image`, formData, {
        timeout: AI_TIMEOUT_MS,
        headers: {
          'Content-Type': 'multipart/form-data',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });

      return res.data;
    } catch (err) {
      throw err.response?.data || { message: '프로필 이미지 업로드 실패' };
    }
  },

  updatePassword: async (passwordData) => {
    try {
      const res = await api.put('/api/users/password', passwordData);
      return res.data;
    } catch (err) {
      throw err.response?.data || { message: '비밀번호 변경 실패' };
    }
  },

  verifyPassword: async (credentials) => {
    try {
      const res = await api.post('/api/users/login', credentials);
      return { verified: true, data: res.data };
    } catch (err) {
      throw err.response?.data || { message: '본인 확인 실패' };
    }
  },
};

export const todoService = {
  getTodos: async (userId) => {
    const res = await api.get('/api/todos');
    return res.data;
  },

  createTodo: async (userId, todoData) => {
    const res = await api.post('/api/todos', todoData);
    return res.data;
  },

  toggleTodo: async (todoId) => {
    const res = await api.patch(`/api/todos/${todoId}/toggle`);
    return res.data;
  },

  deleteTodo: async (todoId) => {
    const res = await api.delete(`/api/todos/${todoId}`);
    return res.data;
  },
};

export const roomService = {
  getRooms: async (userId) => {
    const res = await api.get('/api/agent-rooms');
    return res.data;
  },

  createRoom: async (userId, roomData) => {
    const res = await api.post('/api/agent-rooms', roomData);
    return res.data;
  },

  sendMessage: async (userId, roomId, payloadOrMessage) => {
    const basePayload =
      typeof payloadOrMessage === 'string'
        ? { message: payloadOrMessage, agentId: roomId, roomId }
        : { agentId: roomId, roomId, ...payloadOrMessage };

    const payload = {
      personality: basePayload.personality || '',
      style: basePayload.style || '',
      tone: basePayload.tone || '',
      knowledgeLevel: basePayload.knowledgeLevel || '',
      knowledge_level: basePayload.knowledge_level || basePayload.knowledgeLevel || '',
      customInstruction: basePayload.customInstruction || '',
      custom_instruction:
        basePayload.custom_instruction || basePayload.customInstruction || '',
      persona: basePayload.persona || '',
      agent_name: basePayload.agent_name || basePayload.agentName || '',
      ...basePayload,
    };

    console.debug('[api.roomService.sendMessage] request body', payload);

    const res = await api.post(`/api/agent-rooms/${roomId}/chat`, payload);
    return res.data;
  },

  getChatHistory: async (userId, roomId) => {
    const res = await api.get(`/api/agent-rooms/${roomId}/history`);
    return res.data;
  },

  deleteRoom: async (userId, roomId) => {
    const res = await api.delete(`/api/agent-rooms/${roomId}`);
    return res.data;
  },
};

export const timerService = {
  startTimer: async (userId, startTime) => {
    const res = await api.post('/api/timers/start', { startTime });
    return res.data;
  },

  endTimer: async (userId, endTime, durationSeconds) => {
    const res = await api.post('/api/timers/end', { endTime, durationSeconds });
    return res.data;
  },

  getCurrentSession: async (userId) => {
    const res = await api.get('/api/timers/current');
    return res.data;
  },

  getTimerHistory: async (userId) => {
    const res = await api.get('/api/timers');
    return res.data;
  },

  syncTimer: async (groupId) => {
    const res = await api.post(`/api/timers/sync/${groupId}`);
    return res.data;
  },
};

export const studyTimeService = {
  getToday: async (userId) => {
    const res = await api.get('/api/study-time/today');
    return res.data;
  },

  getWeekly: async (userId) => {
    const res = await api.get('/api/study-time/weekly');
    return res.data;
  },

  getPrediction: async (userId) => {
    const res = await api.get('/api/study-time/predict');
    return res.data;
  },
};

export const activityService = {
  getWeeklyGraph: async (payload) => {
    const res = await fastApi.post('/activity/weekly', payload);
    return res.data;
  },
};

export const materialService = {
  getMaterials: async () => {
    const res = await api.get('/api/materials');
    return res.data;
  },

  // 자료보관함 폴더 뷰: 현재 위치(parentId)의 하위 폴더 + 자료 + breadcrumb. parentId=null 이면 루트(홈).
  // domain(학습자료/플래너/학습일지)으로 폴더·자료를 분리 조회한다(탭 간 혼입 방지).
  getArchiveItems: async (parentId, domain) => {
    const params = {};
    if (parentId != null) params.parentId = parentId;
    if (domain) params.domain = domain;
    const res = await api.get('/api/materials/items', {
      params: Object.keys(params).length ? params : undefined,
    });
    return res.data; // { currentFolderId, breadcrumb, folders, materials }
  },

  // 자료를 다른 폴더로 이동 (folderId=null 이면 루트로)
  moveMaterial: async (materialId, folderId) => {
    const res = await api.patch(`/api/materials/${materialId}/move`, { folderId: folderId ?? null });
    return res.data;
  },

  // context='review-note' 일 때만 오답노트(REVIEW_NOTE) 상세 허용(전용 복습 화면). 일반 상세는 오답노트 차단(404).
  getMaterialDetail: async (materialId, context) => {
    const res = await api.get(`/api/materials/${materialId}`, context ? { params: { context } } : undefined);
    return res.data;
  },

  createStudyLog: async (studyLogData) => {
    const res = await api.post('/api/materials/log', studyLogData);
    return res.data;
  },

  uploadMaterial: async (title, materialType, keywords, file, folderId) => {
    const formData = new FormData();
    formData.append('title', title);
    formData.append('materialType', materialType);

    if (keywords) {
      formData.append('keywords', keywords);
    }
    // 폴더 안에서 업로드한 경우에만 folderId 전송. 루트면 생략(서버에서 null=루트).
    if (folderId != null) {
      formData.append('folderId', folderId);
    }

    formData.append('file', file);

    const token = localStorage.getItem('token');

    const res = await axios.post(`${API_BASE_URL}/api/materials/upload`, formData, {
      timeout: MATERIAL_UPLOAD_TIMEOUT_MS,
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });

    return res.data;
  },

  // 업로드 전 AI 파일 유형 판별 (저장하지 않음). selectedType 은 ai07 vocab(STUDY_PDF/PLANNER/...).
  classifyBeforeSave: async (selectedType, title, keywords, file) => {
    const formData = new FormData();
    formData.append('selectedType', selectedType);
    if (title) formData.append('title', title);
    if (keywords) formData.append('keywords', keywords);
    formData.append('file', file);
    const token = localStorage.getItem('token');
    const res = await axios.post(`${API_BASE_URL}/api/materials/classify-before-save`, formData, {
      timeout: 30000,
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    });
    return res.data;
  },

  updateMaterial: async (materialId, updateData) => {
    const res = await api.put(`/api/materials/${materialId}`, updateData);
    return res.data;
  },

  deleteMaterial: async (materialId) => {
    const res = await api.delete(`/api/materials/${materialId}`);
    return res.data;
  },

  getSummary: async (materialId) => {
    const res = await api.get(`/api/materials/${materialId}/summary`, {
      timeout: AI_TIMEOUT_MS,
    });
    return res.data;
  },

  // AI 핵심 요약 노트(전공 분야·핵심 객체 중심). PDF 외 자료는 null. status: PENDING/RUNNING/SUCCESS/FAILED
  getStudyNote: async (materialId) => {
    const res = await api.get(`/api/materials/${materialId}/study-note`);
    return res.data;
  },

  getFeedback: async (materialId) => {
    const res = await api.get(`/api/materials/${materialId}/feedback`);
    return res.data;
  },

  getMemo: async (materialId) => {
    const res = await api.get(`/api/materials/${materialId}/memo`);
    return res.data;
  },

  saveMemo: async (materialId, content) => {
    const res = await api.put(`/api/materials/${materialId}/memo`, { content });
    return res.data;
  },

  // 학습일지: 검증(ai07) 통과분만 S3 저장 + DB 메타데이터. 원문은 상세 조회 시 S3에서 읽음.
  getStudyJournals: async (materialId) => {
    const res = await api.get(`/api/materials/${materialId}/study-journals`);
    return res.data;
  },

  // listStudyJournals: getStudyJournals 별칭(메모 탭 목록 표시용 명시 이름)
  listStudyJournals: async (materialId) => {
    const res = await api.get(`/api/materials/${materialId}/study-journals`);
    return res.data;
  },

  // 성공 시 메타데이터 반환. 검증 실패 시 axios가 422를 throw → err.response.data 에 {decision,category,reason,suggestion}.
  createStudyJournal: async (materialId, content) => {
    const res = await api.post(`/api/materials/${materialId}/study-journals`, { content });
    return res.data;
  },

  getStudyJournal: async (materialId, journalId) => {
    const res = await api.get(`/api/materials/${materialId}/study-journals/${journalId}`);
    return res.data;
  },

  deleteStudyJournal: async (materialId, journalId) => {
    const res = await api.delete(`/api/materials/${materialId}/study-journals/${journalId}`);
    return res.data;
  },

  getQuizzes: async (materialId) => {
    const res = await api.get(`/api/materials/${materialId}/quiz`);
    return res.data;
  },

  generateQuiz: async (materialId, quizRequest) => {
    const res = await api.post(`/api/materials/${materialId}/quiz`, quizRequest, {
      timeout: AI_FALLBACK_TIMEOUT_MS, // 90초 초과 시 끊고 프론트 fallback 으로 전환
    });
    return res.data;
  },

  askQuestion: async (materialId, questionRequest) => {
    const res = await api.post(`/api/materials/${materialId}/question`, questionRequest, {
      timeout: AI_TIMEOUT_MS,
    });
    return res.data;
  },

  getRoadmap: async (materialId) => {
    const res = await api.get(`/api/materials/${materialId}/roadmap`, {
      timeout: AI_TIMEOUT_MS,
    });
    return res.data;
  },

  toggleRoadmapTask: async (materialId, taskId) => {
    const res = await api.put(
      `/api/materials/${materialId}/roadmap/tasks/${taskId}/toggle`
    );
    return res.data;
  },

  // 84일(12주x7일) 로드맵 재생성 — 난이도(level) 포함, 레거시 로드맵 교체
  regenerateRoadmap: async (materialId, level = 'intermediate') => {
    const res = await api.post(`/api/materials/${materialId}/roadmap/regenerate`, { level, difficulty: level }, {
      timeout: AI_FALLBACK_TIMEOUT_MS, // 90초 초과 시 끊고 프론트 fallback 로드맵으로 전환
    });
    return res.data;
  },

  // 균형 잡힌 AI 피드백 다시 생성
  regenerateFeedback: async (materialId) => {
    const res = await api.post(`/api/materials/${materialId}/feedback/regenerate`, null, { timeout: AI_TIMEOUT_MS });
    return res.data;
  },

  // 84일 로드맵 일자(day) 완료 토글
  toggleRoadmapDay: async (materialId, week, dayIndex) => {
    const res = await api.put(`/api/materials/${materialId}/roadmap/days/toggle`, { week, dayIndex });
    return res.data;
  },

  // 핵심 키워드 개념 정의 (chip 클릭 → GPT/Wikipedia)
  defineKeyword: async (materialId, body) => {
    const res = await api.post(`/api/materials/${materialId}/keywords/define`, body, {
      timeout: AI_TIMEOUT_MS,
    });
    return res.data;
  },
};

// 자료보관함 폴더 CRUD. 폴더는 자료(material) id 체계와 분리된 별도 엔티티이며 AI 처리 대상이 아니다.
export const folderService = {
  listFolders: async () => {
    const res = await api.get('/api/folders');
    return res.data;
  },
  createFolder: async (name, parentId, domain) => {
    const res = await api.post('/api/folders', { name, parentId: parentId ?? null, domain: domain ?? null });
    return res.data;
  },
  renameFolder: async (folderId, name) => {
    const res = await api.patch(`/api/folders/${folderId}`, { name });
    return res.data;
  },
  moveFolder: async (folderId, parentId) => {
    const res = await api.patch(`/api/folders/${folderId}/move`, { parentId: parentId ?? null });
    return res.data;
  },
  deleteFolder: async (folderId) => {
    const res = await api.delete(`/api/folders/${folderId}`);
    return res.data;
  },
};

export const groupService = {
  getGroups: async () => {
    const res = await api.get('/api/groups');
    return res.data;
  },

  getGroupDetail: async (id) => {
    const res = await api.get(`/api/groups/${id}`);
    return res.data;
  },

  createGroup: async (groupData) => {
    const formData = new FormData();

    Object.keys(groupData).forEach((key) => {
      if (groupData[key] !== undefined && groupData[key] !== null) {
        formData.append(key, groupData[key]);
      }
    });

    const res = await api.post('/api/groups', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });

    return res.data;
  },

  updateGroup: async (id, groupData) => {
    const formData = new FormData();

    Object.keys(groupData).forEach((key) => {
      if (groupData[key] !== undefined && groupData[key] !== null) {
        formData.append(key, groupData[key]);
      }
    });

    const res = await api.put(`/api/groups/${id}`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });

    return res.data;
  },

  reportUser: async (groupId, reportData) => {
    const res = await api.post(`/api/groups/${groupId}/reports`, reportData);
    return res.data;
  },

  applyGroup: async (id, applyData) => {
    const res = await api.post(`/api/groups/${id}/apply`, applyData);
    return res.data;
  },

  getMembers: async (id) => {
    const res = await api.get(`/api/groups/${id}/members`);
    return res.data;
  },

  getApplications: async (id) => {
    const res = await api.get(`/api/groups/${id}/applications`);
    return res.data;
  },

  approveApplication: async (applicationId) => {
    const res = await api.post(`/api/groups/applications/${applicationId}/approve`);
    return res.data;
  },

  rejectApplication: async (applicationId) => {
    const res = await api.post(`/api/groups/applications/${applicationId}/reject`);
    return res.data;
  },

  deleteGroup: async (id) => {
    const res = await api.delete(`/api/groups/${id}`);
    return res.data;
  },

  kickMember: async (groupId, memberUserId) => {
    const res = await api.delete(`/api/groups/${groupId}/members/${memberUserId}`);
    return res.data;
  },

  completeRecruitment: async (id) => {
    const res = await api.post(`/api/groups/${id}/complete`);
    return res.data;
  },

  getVideoToken: async (id) => {
    const res = await api.post(`/api/groups/${id}/video/token`);
    return res.data;
  },

  uploadQuizMaterial: async (groupId, title, file) => {
    const formData = new FormData();
    formData.append('title', title);
    formData.append('file', file);

    const token = localStorage.getItem('token');
    const res = await axios.post(
      `${API_BASE_URL}/api/groups/${groupId}/materials/upload-quiz`,
      formData,
      {
        timeout: AI_TIMEOUT_MS,
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      }
    );

    return res.data;
  },

  getGroupMaterials: async (groupId) => {
    const res = await api.get(`/api/groups/${groupId}/materials`);
    return res.data;
  },

  getGroupMaterialDownloadUrl: async (materialId) => {
    const res = await api.get(`/api/groups/materials/${materialId}/download`);
    return res.data;
  },

  getGroupQuizzes: async (groupId) => {
    const res = await api.get(`/api/groups/${groupId}/quizzes`);
    return res.data;
  },

  getQuizSession: async (groupId) => {
    const res = await api.get(`/api/groups/${groupId}/quiz/session`);
    return res.data;
  },

  // 이미 업로드된 PDF 자료 기반 퀴즈 (재)생성
  generateMaterialQuiz: async (groupId, materialId) => {
    const res = await api.post(`/api/groups/${groupId}/materials/${materialId}/quiz`);
    return res.data;
  },
};

export const knowledgeService = {
  getPosts: async () => {
    const res = await api.get('/api/blogs');
    return res.data;
  },

  getPostDetail: async (blogId) => {
    const res = await api.get(`/api/blogs/${blogId}`);
    return res.data;
  },

  createPost: async (title, content, imageFile, pdfFile) => {
    const formData = new FormData();
    formData.append('title', title);
    formData.append('content', content);

    if (imageFile) {
      formData.append('image', imageFile);
    }

    if (pdfFile) {
      formData.append('pdf', pdfFile);
    }

    const token = localStorage.getItem('token');

    const res = await axios.post(`${API_BASE_URL}/api/blogs`, formData, {
      timeout: AI_TIMEOUT_MS,
      headers: {
        'Content-Type': 'multipart/form-data',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });

    return res.data;
  },

  updatePost: async (
    blogId,
    title,
    content,
    imageFile,
    pdfFile,
    clearImage = false,
    clearPdf = false
  ) => {
    const formData = new FormData();

    if (title) {
      formData.append('title', title);
    }

    if (content) {
      formData.append('content', content);
    }

    if (imageFile) {
      formData.append('image', imageFile);
    }

    if (pdfFile) {
      formData.append('pdf', pdfFile);
    }

    formData.append('clearImage', clearImage);
    formData.append('clearPdf', clearPdf);

    const token = localStorage.getItem('token');

    const res = await axios.put(`${API_BASE_URL}/api/blogs/${blogId}`, formData, {
      timeout: AI_TIMEOUT_MS,
      headers: {
        'Content-Type': 'multipart/form-data',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });

    return res.data;
  },

  deletePost: async (blogId) => {
    const res = await api.delete(`/api/blogs/${blogId}`);
    return res.data;
  },

  searchPosts: async (keyword) => {
    const res = await api.get('/api/blogs/search', {
      params: {
        keyword,
      },
    });

    return res.data;
  },

  toggleLike: async (blogId) => {
    const res = await api.post(`/api/blogs/${blogId}/like`);
    return res.data;
  },

  addComment: async (blogId, content) => {
    const res = await api.post(`/api/blogs/${blogId}/comments`, { content });
    return res.data;
  },

  deleteComment: async (blogId, commentId) => {
    const res = await api.delete(`/api/blogs/${blogId}/comments/${commentId}`);
    return res.data;
  },

  reportPost: async (reportedBlogId, reportData) => {
    const res = await api.post('/api/reports/post', { reportedBlogId, ...reportData });
    return res.data;
  },

  reportComment: async (reportedCommentId, reportData) => {
    const res = await api.post('/api/reports/comment', { reportedCommentId, ...reportData });
    return res.data;
  },
};

export const adminService = {
  getGroupReports: async () => {
    const res = await api.get('/api/admin/reports/groups');
    return res.data;
  },

  getGeneralReports: async () => {
    const res = await api.get('/api/reports');
    return res.data;
  },

  resolveReport: async (reportId, status) => {
    const res = await api.put(`/api/reports/${reportId}/resolve`, null, {
      params: { status },
    });
    return res.data;
  },

  deleteGroup: async (groupId) => {
    const res = await api.delete(`/api/admin/groups/${groupId}`);
    return res.data;
  },

  deletePost: async (blogId) => {
    const res = await api.delete(`/api/admin/blogs/${blogId}`);
    return res.data;
  },

  deleteComment: async (commentId) => {
    const res = await api.delete(`/api/admin/comments/${commentId}`);
    return res.data;
  },

  getInquiries: async () => {
    const res = await api.get('/api/admin/inquiries');
    return res.data;
  },

  replyInquiry: async (inquiryId, replyData) => {
    const res = await api.post(`/api/admin/inquiries/${inquiryId}/reply`, replyData);
    return res.data;
  },

  suspendUser: async (userId, suspendData) => {
    const res = await api.post(`/api/admin/users/${userId}/suspend`, suspendData);
    return res.data;
  },

  banUser: async (userId, banData) => {
    const res = await api.post(`/api/admin/users/${userId}/ban`, banData);
    return res.data;
  },
};

export const inquiryService = {
  submitInquiry: async (inquiryData) => {
    const res = await api.post('/api/inquiries', inquiryData);
    return res.data;
  },

  getInquiries: async () => {
    const res = await api.get('/api/inquiries');
    return res.data;
  },
};

// 메인 배너: 백엔드가 내려주는 S3 이미지 URL/문구만 사용(외부 원본 URL·MCP 값 노출 금지)
export const bannerService = {
  getMainBanner: async () => {
    const res = await api.get('/api/banners/main');
    return res.data;
  },
};

// 공부 플래너: 작성/조회/PDF생성/자료보관함 저장/다운로드/삭제
export const plannerService = {
  createPlanner: async (data) => {
    const res = await api.post('/api/planners', data);
    return res.data;
  },
  updatePlanner: async (id, data) => {
    const res = await api.put(`/api/planners/${id}`, data);
    return res.data;
  },
  getPlanners: async () => {
    const res = await api.get('/api/planners');
    return res.data;
  },
  // 로드맵(84일) → 플래너 84개 생성. 플래너 도메인에만 저장(주간일정 무관).
  createFromRoadmap: async (data) => {
    const res = await api.post('/api/planners/from-roadmap', data);
    return res.data;
  },
  getPlanner: async (id) => {
    const res = await api.get(`/api/planners/${id}`);
    return res.data;
  },
  generatePdf: async (id) => {
    const res = await api.post(`/api/planners/${id}/pdf`);
    return res.data;
  },
  archive: async (id) => {
    const res = await api.post(`/api/planners/${id}/archive`);
    return res.data;
  },
  getDownloadUrl: async (id) => {
    const res = await api.get(`/api/planners/${id}/download-url`);
    return res.data;
  },
  deletePlanner: async (id) => {
    const res = await api.delete(`/api/planners/${id}`);
    return res.data;
  },
  // 자료 기반(ROADMAP_AUTO) 플래너 전체삭제. payload: { scope, materialId, sourceRoadmapId, sourceType, plannerIds }
  bulkDeletePlanners: async (payload) => {
    const res = await api.delete('/api/planners/bulk', { data: payload });
    return res.data;
  },
  // 체크박스 선택 삭제. 선택한 본인 소유 플래너만 삭제. payload: { plannerIds: [1,2,3] }
  bulkDeleteSelectedPlanners: async (plannerIds) => {
    const res = await api.delete('/api/planners/bulk-selected', { data: { plannerIds } });
    return res.data;
  },

  // 플래너 전용 AI: 학습 실행 관리 피드백 (로드맵/퀴즈/문서질문 없음)
  assistPlanner: async (id) => {
    const res = await api.post(`/api/planners/${id}/ai-assist`, {}, { timeout: AI_TIMEOUT_MS });
    return res.data;
  },
  getPlannerAiResult: async (id) => {
    const res = await api.get(`/api/planners/${id}/ai-result`);
    return res.data;
  },
};

// AI 계획 분석(PDF/플래너 문장 단위 학습 진행) 서비스. 모두 Spring(/api) 경유.
export const planAnalysisService = {
  // 분석 생성/재생성 (PDF/플래너 텍스트 → 문장/행동 단위 체크리스트)
  analyze: async (materialId) => {
    const res = await api.post(`/api/materials/${materialId}/plan-analysis`, {}, { timeout: AI_TIMEOUT_MS });
    return res.data;
  },
  // 저장된 분석 조회 (없으면 empty=true)
  get: async (materialId) => {
    const res = await api.get(`/api/materials/${materialId}/plan-analysis`);
    return res.data;
  },
  // 항목 완료/숨김 상태 변경 (체크: {completed}, 지우기: {completed:true, hidden:true})
  patchItem: async (itemId, patch) => {
    const res = await api.patch(`/api/plan-analysis/items/${itemId}`, patch);
    return res.data;
  },
  // 다음 학습 추천(미완료 항목 기반) 재생성
  recommend: async (materialId) => {
    const res = await api.post(`/api/materials/${materialId}/plan-recommendation`, {});
    return res.data;
  },
  getProgress: async (materialId) => {
    const res = await api.get(`/api/materials/${materialId}/progress`);
    return res.data;
  },
};

// 오답노트(복습 전용) 서비스.
//  - 백엔드(/api/review-notes)가 아직 없으므로 404/501/네트워크 오류는 빈 상태로 흡수한다.
//  - 화면에서 500/404를 터뜨리지 않도록 getReviewNotes 는 항상 배열을 반환한다.
//  - apiReady=false 를 함께 돌려주어 페이지가 "API 미준비" 안내를 띄울 수 있게 한다.
const REVIEW_NOTE_NOT_READY = new Set([404, 501, 503]);
const isReviewApiMissing = (err) => {
  const status = err?.response?.status;
  // 응답 자체가 없는(네트워크/프록시 미연결) 경우도 미준비로 간주
  if (status == null) return true;
  return REVIEW_NOTE_NOT_READY.has(status);
};

export const reviewNoteService = {
  // 퀴즈 오답으로 오답노트 생성. quizSessionId = 퀴즈(quizId), answers = { [문항index]: 선택index }
  createFromQuiz: async (quizSessionId, answers, extra = {}) => {
    const body = { answers, saveToArchive: true, createPdf: true, uploadToS3: true, ...extra };
    const res = await api.post(`/api/review-notes/from-quiz/${quizSessionId}`, body, { timeout: AI_TIMEOUT_MS });
    return res.data;
  },
  // 목록: 실패해도 throw 하지 않고 { items, apiReady } 형태로 안전 반환 (구버전 호환)
  getReviewNotes: async () => {
    try {
      const res = await api.get('/api/review-notes');
      const items = Array.isArray(res.data) ? res.data : (res.data?.items ?? []);
      return { items, apiReady: true };
    } catch (err) {
      if (isReviewApiMissing(err)) return { items: [], apiReady: false };
      throw err;
    }
  },
  // 신버전: API 실패(에러)와 빈 목록(empty)을 명확히 구분한다.
  //  - 성공: { ok: true, items: [...] }   (items.length === 0 이면 화면에서 empty 처리)
  //  - 실패: { ok: false, items: [], error: '...' }  (절대 empty로 처리하지 않음)
  listReviewNotes: async () => {
    try {
      const res = await api.get('/api/review-notes');
      const items = Array.isArray(res.data) ? res.data : (res.data?.items ?? []);
      return { ok: true, items, error: '' };
    } catch (err) {
      return { ok: false, items: [], error: '오답노트 목록을 불러오지 못했습니다. 다시 시도해주세요.' };
    }
  },
  getReviewNote: async (id) => {
    const res = await api.get(`/api/review-notes/${id}`);
    return res.data;
  },
  // 유사문제: 난이도 하/중/상(easy|normal|hard). body { wrongQuestionId, difficulty, count }
  variantQuestion: async (id, body) => {
    const res = await api.post(`/api/review-notes/${id}/variant-question`, body, { timeout: AI_TIMEOUT_MS });
    return res.data;
  },
  // PDF 다운로드 URL(또는 메타) 조회
  getDownloadUrl: async (id) => {
    const res = await api.get(`/api/review-notes/${id}/download`);
    return res.data;
  },
  // 다시 풀기: 틀린 문제 세트 조회
  retry: async (id) => {
    const res = await api.get(`/api/review-notes/${id}/retry`);
    return res.data;
  },
  // 메모 수정/저장
  updateMemo: async (id, memo) => {
    const res = await api.patch(`/api/review-notes/${id}/memo`, { memo });
    return res.data;
  },
  // 복습 필요 분석: 오답노트 데이터 기반 AI 생성 텍스트. { reviewNoteId, reviewNeededText }
  reviewNeeded: async (id) => {
    const res = await api.post(`/api/review-notes/${id}/review-needed`, null, { timeout: AI_TIMEOUT_MS });
    return res.data;
  },
  // 오답노트 삭제(서버에서 연동 Material/S3까지 함께 정리)
  deleteReviewNote: async (id) => {
    const res = await api.delete(`/api/review-notes/${id}`);
    return res.data;
  },
};

// 학습 왕복 루프(Learning Loop) — React는 Spring(/api/learning-loop/*)만 호출한다(FastAPI 직접 호출 금지).
//  - 학습/AI 행동 이벤트를 기록·조회하고, 복습 추천일 계산 → 플래너(주간일정) 등록까지 연결한다.
export const learningLoopService = {
  // 이벤트 이력 조회. params: { materialId, documentId, sourceType, sourceId, limit }
  getEvents: async (params = {}) => {
    try {
      const res = await api.get('/api/learning-loop/events', { params });
      return { ok: true, items: Array.isArray(res.data) ? res.data : [] };
    } catch (err) {
      return { ok: false, items: [] };
    }
  },
  // 이벤트 직접 기록(실패해도 화면을 깨뜨리지 않음)
  recordEvent: async (body) => {
    try {
      const res = await api.post('/api/learning-loop/events', body);
      return res.data;
    } catch (err) {
      return { saved: false };
    }
  },
  // 다음 AI 호출용 컨텍스트 패키지. { learningLoopContext, hasContext, usedSources }
  getContext: async (params = {}) => {
    try {
      const res = await api.get('/api/learning-loop/context', { params });
      return res.data;
    } catch (err) {
      return { learningLoopContext: {}, hasContext: false, usedSources: [] };
    }
  },
  // 복습 추천일 계산. body { materialId, wrongNoteId, difficulty, wrongCount }
  // → { recommendReviewInDays, recommendedReviewDate, reviewReason }
  recommendReview: async (body) => {
    const res = await api.post('/api/learning-loop/review-recommendation', body);
    return res.data;
  },
  // 복습 일정을 플래너(주간일정)에 등록. body { materialId, wrongNoteId, title, scheduledDate, reason }
  // → { plannerId, title, scheduledDate }
  registerReviewSchedule: async (body) => {
    const res = await api.post('/api/learning-loop/review-schedule', body);
    return res.data;
  },
  // 학습 이벤트를 학습일지 기록으로 연결. body { eventId, materialId, title, content }
  studyLog: async (body) => {
    const res = await api.post('/api/learning-loop/study-log', body);
    return res.data;
  },
};

// 소크라테스 복습 세션 — React는 Spring 프록시(/api/materials/{id}/socratic-review/*)만 호출한다.
//  - ai07 FastAPI 직접 호출 금지(백엔드가 화이트리스트 sanitize + 소유권 검증).
//  - 모든 응답에 aiAvailable 플래그가 붙는다(false면 "AI 서버 재시작 필요" 안내).
export const socraticReviewService = {
  // 세션 시작. body { maxTurnsPerChunk?, maxChunks? }
  start: async (materialId, body = {}) => {
    const res = await api.post(`/api/materials/${materialId}/socratic-review/sessions`, body, { timeout: AI_TIMEOUT_MS });
    return res.data;
  },
  // 답변 제출. body { answer }
  answer: async (materialId, sessionId, answer) => {
    const res = await api.post(
      `/api/materials/${materialId}/socratic-review/sessions/${sessionId}/answers`,
      { answer },
      { timeout: AI_TIMEOUT_MS },
    );
    return res.data;
  },
  // 세션 완료(요약/추천 복습일 산출)
  finish: async (materialId, sessionId) => {
    const res = await api.post(
      `/api/materials/${materialId}/socratic-review/sessions/${sessionId}/finish`,
      {},
      { timeout: AI_TIMEOUT_MS },
    );
    return res.data;
  },
  // 다음 복습일 주간 일정(플래너 DB) 등록. body { reviewDate? } (없으면 백엔드가 추천일 사용)
  scheduleReview: async (materialId, sessionId, reviewDate) => {
    const res = await api.post(
      `/api/materials/${materialId}/socratic-review/sessions/${sessionId}/schedule-review`,
      reviewDate ? { reviewDate } : {},
    );
    return res.data;
  },
};

// AI 학습메이트(질문 중심) — 같은 질문 4가지 모드 + 빠른 조정. 기존 멀티에이전트 채팅 API와 분리.
export const learningMateService = {
  chat: async (payload) => {
    const res = await api.post('/api/learning-mate/chat', payload, { timeout: AI_TIMEOUT_MS });
    return res.data;
  },
};

export default api;
