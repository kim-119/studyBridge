import axios from 'axios';

// 현재 브라우저가 접속 중인 호스트 주소(IP 혹은 localhost)를 동적으로 알아냅니다!
const hostname = typeof window !== 'undefined' ? window.location.hostname : 'localhost';

const api = axios.create({
  baseURL: `http://${hostname}:8080`,
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token');
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

api.interceptors.response.use(
  (res) => res,
  async (err) => {
    console.error('API 에러:', err.response || err.message);
    const originalRequest = err.config;

    if (err.response && (err.response.status === 401 || err.response.status === 403) && !originalRequest._retry) {
      // 무한 루프 방지용 플래그
      // Refresh token 요청일 경우 제외
      if (originalRequest.url.includes('/api/users/refresh')) {
        return Promise.reject(err);
      }
      
      originalRequest._retry = true;
      try {
        const refreshToken = localStorage.getItem('refreshToken');
        if (!refreshToken) throw new Error('No refresh token');
        
        const res = await axios.post(`http://${hostname}:8080/api/users/refresh?refreshToken=${refreshToken}`);
        
        if (res.data && res.data.accessToken) {
          localStorage.setItem('token', res.data.accessToken);
          localStorage.setItem('refreshToken', res.data.refreshToken);
          
          originalRequest.headers['Authorization'] = `Bearer ${res.data.accessToken}`;
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

const fastApi = axios.create({
  baseURL: `http://${hostname}:8000`,
  headers: {
    'Content-Type': 'application/json',
  },
});

fastApi.interceptors.response.use(
  (res) => res,
  (err) => {
    // 404 Not Found 에러 등 불필요한 로그 출력 방지
    // console.error('FastAPI 에러:', err.response || err.message);
    return Promise.reject(err);
  }
);

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
      throw err.response?.data || { message: '로그인 실패' };
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
  sendMessage: async (userId, roomId, message) => {
    const res = await api.post(`/api/chat/rooms/${roomId}`, { message });
    return res.data;
  },
  getChatHistory: async (userId, roomId) => {
    const res = await api.get(`/api/chat/rooms/${roomId}/history`);
    return res.data;
  },
  deleteRoom: async (userId, roomId) => {
    const res = await api.delete(`/api/agent-rooms/${roomId}`);
    return res.data;
  }
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
  }
};

export const studyTimeService = {
  getToday: async (userId) => {
    const res = await api.get('/api/study-time/today');
    return res.data;
  },
  getWeekly: async (userId) => {
    const res = await api.get('/api/study-time/weekly');
    return res.data;
  }
};

export const activityService = {
  getWeeklyGraph: async (payload) => {
    const res = await fastApi.post('/activity/weekly', payload);
    return res.data;
  }
};

export const materialService = {
  getMaterials: async () => {
    const res = await api.get('/api/materials');
    return res.data;
  },
  getMaterialDetail: async (materialId) => {
    const res = await api.get(`/api/materials/${materialId}`);
    return res.data;
  },
  createStudyLog: async (studyLogData) => {
    const res = await api.post('/api/materials/log', studyLogData);
    return res.data;
  },
  uploadMaterial: async (title, materialType, keywords, file) => {
    const formData = new FormData();
    formData.append('title', title);
    formData.append('materialType', materialType);
    if (keywords) {
      formData.append('keywords', keywords);
    }
    formData.append('file', file);
    
    const res = await api.post('/api/materials/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
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
    const res = await api.get(`/api/materials/${materialId}/summary`);
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
  getQuizzes: async (materialId) => {
    const res = await api.get(`/api/materials/${materialId}/quiz`);
    return res.data;
  },
  generateQuiz: async (materialId, quizRequest) => {
    const res = await api.post(`/api/materials/${materialId}/quiz`, quizRequest);
    return res.data;
  },
  askQuestion: async (materialId, questionRequest) => {
    const res = await api.post(`/api/materials/${materialId}/question`, questionRequest);
    return res.data;
  },
  getRoadmap: async (materialId) => {
    const res = await api.get(`/api/materials/${materialId}/roadmap`);
    return res.data;
  },
  toggleRoadmapTask: async (materialId, taskId) => {
    const res = await api.put(`/api/materials/${materialId}/roadmap/tasks/${taskId}/toggle`);
    return res.data;
  }
};

export default api;